"""Test LLM matchmaking by rediscovering KataGo ratings from old games.

Each KataGo player is removed from the rating history, assigned the LLM prior,
and scheduled in color-swapped pairs by a selectable matchmaking policy.
Scheduled results are sampled without replacement from the corresponding
historical matchup, so this script never launches a Go engine.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import random
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

# These matrices are only about 135x135. Multithreaded BLAS startup and
# cross-process oversubscription cost much more than the arithmetic itself.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np

import arena


DEFAULT_MAX_GAMES = 100
DEFAULT_PLAYER_COUNT = 40
NEW_PLAYER_PRIOR = (2_000.0, 3_000.0)
MATCHMAKING_ALGORITHMS = (
    "maximum_information_gain",
    "maximum_nontransitivity_information_gain",
    "maximum_nontransitivity_disagreement_gain",
    "maximum_nontransitivity_hybrid_gain",
    "proportional_information_gain",
    "random_within_400_elo",
    "random_overlapping_ci",
    "top_6_proportional_information_gain",
    "maximum_first_20_then_half_top_6",
    "half_maximum_half_top_6",
    "eighty_percent_maximum_twenty_percent_top_6",
    "staged_max_80_50_top_6",
    "exclusive_80_max_20_top_6",
    "ci_adaptive_max_top_6",
    "annealed_max_top_6",
    "softmax_information_gain",
    "rank_weighted_top_6",
    "diversity_penalized_information_gain",
    "robust_information_gain",
)
DEFAULT_MATCHMAKING_ALGORITHM = MATCHMAKING_ALGORITHMS[0]
INFORMATION_GAIN_ALGORITHMS = frozenset(
    algorithm
    for algorithm in MATCHMAKING_ALGORITHMS
    if algorithm not in {
        "random_within_400_elo", "random_overlapping_ci"
    }
)


@dataclass(frozen=True)
class MatchupHistory:
    players: tuple[str, ...]
    matchups: tuple[tuple[str, str], ...]
    totals: np.ndarray
    scores: np.ndarray
    outcomes: dict[tuple[str, str], tuple[int, int, int]]
    games: int


@dataclass(frozen=True)
class GroupedData:
    names: tuple[str, ...]
    positions: dict[str, int]
    black: np.ndarray
    white: np.ndarray
    totals: np.ndarray
    scores: np.ndarray


@dataclass(frozen=True)
class Fit:
    ratings: dict[str, float]
    color: arena.ColorAdvantageModel
    covariance: np.ndarray
    positions: dict[str, int]


@dataclass(frozen=True)
class TrajectoryPoint:
    player: str
    games: int
    elo: float
    ci_low: float
    ci_high: float
    old_elo: float

    @property
    def difference(self):
        return self.elo - self.old_elo


@dataclass(frozen=True)
class NontransitivityEstimate:
    """Information in a matchup beyond what a scalar Elo model represents."""

    posterior_mean: float
    posterior_variance: float
    uncertainty_information: float
    disagreement_information: float


def load_history(log_root: Path) -> MatchupHistory:
    """Load all locally available KataGo-vs-KataGo arena results."""
    aggregates: dict[tuple[str, str], list[float]] = {}
    outcome_counts: dict[tuple[str, str], list[int]] = {}
    players: set[str] = set()
    game_count = 0
    result_paths = sorted(log_root.glob("arena_*/results.csv"))
    if not result_paths:
        raise ValueError(f"no arena results found under {log_root}")

    for path in result_paths:
        metadata_path = path.with_name("run.json")
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read {metadata_path}: {exc}") from exc
        if not isinstance(metadata, dict):
            raise ValueError(f"arena metadata is not an object: {metadata_path}")
        for field, expected in (
            ("board_size", arena._Arena.BOARD_SIZE),
            ("komi", arena._Arena.KOMI),
            ("rules", arena._Arena.RULES),
        ):
            if metadata.get(field) != expected:
                raise ValueError(
                    f"{metadata_path} has incompatible {field}: "
                    f"{metadata.get(field)!r}"
                )

        row_count = 0
        with path.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            required = {"black", "white", "score_black"}
            if not required <= set(reader.fieldnames or ()):
                raise ValueError(f"historical results are missing columns: {path}")
            for line_number, row in enumerate(reader, start=2):
                row_count += 1
                black, white = row["black"], row["white"]
                if not (black.startswith("kata1-") and white.startswith("kata1-")):
                    continue
                score = float(row["score_black"])
                if not math.isfinite(score) or score not in {0.0, 0.5, 1.0}:
                    raise ValueError(f"{path}:{line_number}: invalid score_black")
                key = black, white
                aggregate = aggregates.setdefault(key, [0.0, 0.0])
                aggregate[0] += 1.0
                aggregate[1] += score
                outcome_counts.setdefault(key, [0, 0, 0])[int(score * 2)] += 1
                players.update(key)
                game_count += 1
        expected_rows = metadata.get("completed_games")
        if isinstance(expected_rows, int) and row_count != expected_rows:
            raise ValueError(
                f"{path} has {row_count} rows but run.json says {expected_rows}"
            )

    matchups = tuple(sorted(aggregates))
    if arena._Arena.ANCHOR not in players:
        raise ValueError(f"history does not contain anchor {arena._Arena.ANCHOR}")
    return MatchupHistory(
        players=tuple(sorted(players)),
        matchups=matchups,
        totals=np.asarray([aggregates[key][0] for key in matchups]),
        scores=np.asarray([aggregates[key][1] for key in matchups]),
        outcomes={key: tuple(value) for key, value in outcome_counts.items()},
        games=game_count,
    )


def grouped_data(names, matchups, totals, scores):
    rating_names = [name for name in names if name != arena._Arena.ANCHOR]
    positions = {name: index for index, name in enumerate(rating_names)}
    return GroupedData(
        names=tuple(names),
        positions=positions,
        black=np.asarray([positions.get(pair[0], -1) for pair in matchups]),
        white=np.asarray([positions.get(pair[1], -1) for pair in matchups]),
        totals=np.asarray(totals, dtype=float).copy(),
        scores=np.asarray(scores, dtype=float).copy(),
    )


def _prior_vectors(data, new_player):
    means = np.zeros(len(data.positions))
    precision = np.full(
        len(data.positions), arena._Arena.DEFAULT_PLAYER_PRIOR[1] ** -2
    )
    if new_player is not None:
        position = data.positions[new_player]
        means[position] = NEW_PLAYER_PRIOR[0]
        precision[position] = NEW_PLAYER_PRIOR[1] ** -2
    return means, precision


def _prediction(data, values, features=None):
    prediction = np.zeros(len(data.totals))
    black_mask, white_mask = data.black >= 0, data.white >= 0
    prediction[black_mask] += values[data.black[black_mask]]
    prediction[white_mask] -= values[data.white[white_mask]]
    if features is not None:
        prediction += features @ values[len(data.positions) :]
    return prediction


def _objective(data, values, means, precision, features):
    logits = arena._Arena.ELO_SCALE * _prediction(data, values, features)
    likelihood = data.scores * logits - data.totals * np.logaddexp(0, logits)
    penalty = np.sum(precision * (values - means) ** 2) / 2
    return float(np.sum(likelihood) - penalty)


def _gradient_and_information(data, values, means, precision, features=None):
    rating_count = len(data.positions)
    logits = arena._Arena.ELO_SCALE * _prediction(data, values, features)
    probability = 1.0 / (1.0 + np.exp(-logits))
    residual = arena._Arena.ELO_SCALE * (data.scores - data.totals * probability)
    weights = (
        arena._Arena.ELO_SCALE**2
        * data.totals
        * probability
        * (1.0 - probability)
    )
    gradient = -precision * (values - means)
    information = np.diag(precision.copy())
    black_mask, white_mask = data.black >= 0, data.white >= 0
    np.add.at(gradient, data.black[black_mask], residual[black_mask])
    np.add.at(gradient, data.white[white_mask], -residual[white_mask])
    np.add.at(
        information,
        (data.black[black_mask], data.black[black_mask]),
        weights[black_mask],
    )
    np.add.at(
        information,
        (data.white[white_mask], data.white[white_mask]),
        weights[white_mask],
    )
    both = black_mask & white_mask
    np.add.at(
        information,
        (data.black[both], data.white[both]),
        -weights[both],
    )
    np.add.at(
        information,
        (data.white[both], data.black[both]),
        -weights[both],
    )

    if features is not None:
        color_slice = slice(rating_count, len(values))
        gradient[color_slice] += features.T @ residual
        information[color_slice, color_slice] += (features.T * weights) @ features
        for indices, sign in ((data.black, 1.0), (data.white, -1.0)):
            mask = indices >= 0
            cross = np.zeros((rating_count, features.shape[1]))
            np.add.at(
                cross,
                indices[mask],
                sign * weights[mask, None] * features[mask],
            )
            information[:rating_count, color_slice] += cross
            information[color_slice, :rating_count] += cross.T
    return gradient, information


def _solve_cholesky(lower, right_hand_side):
    """Solve L L.T x = b without invoking a multithreaded dense solver."""
    right = np.asarray(right_hand_side, dtype=float)
    intermediate = np.empty_like(right)
    for row in range(len(lower)):
        product = lower[row, :row] @ intermediate[:row]
        intermediate[row] = (right[row] - product) / lower[row, row]
    solution = np.empty_like(right)
    for row in range(len(lower) - 1, -1, -1):
        product = lower[row + 1 :, row] @ solution[row + 1 :]
        solution[row] = (intermediate[row] - product) / lower[row, row]
    return solution


def _fit_logit(data, initial, means, precision, features=None):
    """arena._fit_logit specialized for sparse, pre-grouped matchup rows."""
    values = np.asarray(initial, dtype=float).copy()
    for _iteration in range(100):
        gradient, information = _gradient_and_information(
            data, values, means, precision, features
        )
        try:
            lower = np.linalg.cholesky(information)
            change = _solve_cholesky(lower, gradient)
        except np.linalg.LinAlgError as exc:
            raise arena.ArenaError(
                "rating information matrix is not positive definite"
            ) from exc
        objective = _objective(data, values, means, precision, features)
        step = 1.0
        while step >= 1 / 1024:
            option = values + step * change
            if _objective(data, option, means, precision, features) >= objective:
                values = option
                break
            step /= 2
        else:
            break
        if max(abs(step * change), default=0.0) < 1e-7:
            break
    return values


def fit_grouped(
    data,
    *,
    new_player=None,
    initial_ratings=None,
    initial_joint_ratings=None,
    initial_color=None,
):
    """Fit the exact arena rating/color model to aggregated game counts."""
    rating_count = len(data.positions)
    rating_means, rating_precision = _prior_vectors(data, new_player)
    initial = np.asarray(
        [
            initial_ratings.get(name, rating_means[position])
            if initial_ratings
            else rating_means[position]
            for name, position in data.positions.items()
        ]
    )
    base_values = _fit_logit(data, initial, rating_means, rating_precision)
    baseline = {arena._Arena.ANCHOR: 0.0}
    baseline.update(
        (name, float(base_values[position]))
        for name, position in data.positions.items()
    )
    position_names = {position: name for name, position in data.positions.items()}
    averages = np.asarray(
        [
            0.5
            * (
                (baseline[position_names[black]] if black >= 0 else 0.0)
                + (baseline[position_names[white]] if white >= 0 else 0.0)
            )
            for black, white in zip(data.black, data.white)
        ]
    )
    nodes = arena._fixed_elo_nodes(
        averages[data.totals > 0], arena._Arena.COLOR_ADVANTAGE_NODE_SPACING
    )
    features = np.asarray(
        [arena._piecewise_linear_basis(value, nodes) for value in averages]
    )
    if initial_color is None:
        color_initial = np.zeros(len(nodes))
    else:
        color_initial = np.asarray(
            [
                sum(
                    coefficient * weight
                    for coefficient, weight in zip(
                        initial_color.coefficients,
                        arena._piecewise_linear_basis(node, initial_color.nodes),
                    )
                )
                for node in nodes
            ]
        )
    means = np.append(rating_means, np.zeros(len(nodes)))
    precision = np.append(
        rating_precision,
        np.full(len(nodes), arena._Arena.COLOR_ADVANTAGE_PRIOR_ELO_SD**-2),
    )
    joint_rating_initial = np.asarray(
        [
            initial_joint_ratings.get(name, base_values[position])
            if initial_joint_ratings
            else base_values[position]
            for name, position in data.positions.items()
        ]
    )
    values = _fit_logit(
        data,
        np.append(joint_rating_initial, color_initial),
        means,
        precision,
        features,
    )
    ratings = {arena._Arena.ANCHOR: 0.0}
    ratings.update(
        (name, float(values[position])) for name, position in data.positions.items()
    )
    color = arena.ColorAdvantageModel(
        nodes=tuple(nodes),
        coefficients=tuple(values[rating_count:]),
        baseline_ratings=baseline,
    )
    _gradient, information = _gradient_and_information(
        data, values, means, precision, features
    )
    try:
        lower = np.linalg.cholesky(information)
        covariance = _solve_cholesky(lower, np.eye(len(lower)))
    except np.linalg.LinAlgError as exc:
        raise arena.ArenaError(
            "rating information matrix is not positive definite"
        ) from exc
    covariance = (covariance + covariance.T) / 2
    return Fit(ratings, color, covariance, data.positions)


def candidate_data(history, player):
    opponents = tuple(
        opponent
        for opponent in history.players
        if opponent != player
        and sum(history.outcomes.get((player, opponent), ()))
        and sum(history.outcomes.get((opponent, player), ()))
    )
    if not opponents:
        raise ValueError(f"{player} has no historical color-swapped matchup")
    entries = [
        (key, total, score)
        for key, total, score in zip(
            history.matchups, history.totals, history.scores
        )
        if player not in key
    ]
    entries += [((player, opponent), 0.0, 0.0) for opponent in opponents]
    entries += [((opponent, player), 0.0, 0.0) for opponent in opponents]
    entries.sort(key=lambda entry: entry[0])
    matchups = tuple(entry[0] for entry in entries)
    data = grouped_data(
        history.players,
        matchups,
        [entry[1] for entry in entries],
        [entry[2] for entry in entries],
    )
    return data, opponents, {key: index for index, key in enumerate(matchups)}


def matchmaking_gains(player, opponents, fit, *, player_rating=None):
    """The active-player row of arena.information_gain_matrix."""
    rating_count = len(fit.positions)
    active_rating = (
        fit.ratings[player] if player_rating is None else player_rating
    )
    gains = []
    for opponent in opponents:
        features = fit.color.features(player, opponent)
        color_terms = [
            (rating_count + index, coefficient)
            for index, coefficient in enumerate(features)
            if coefficient
        ]
        gain = arena._paired_information_gain(
            fit.covariance,
            fit.positions.get(player),
            fit.positions.get(opponent),
            active_rating - fit.ratings[opponent],
            fit.color.advantage(player, opponent),
            color_terms,
            [fit.positions[player]],
        )
        if not math.isfinite(gain) or gain < 0:
            raise ValueError("invalid matchmaking information gain")
        gains.append(gain)
    return gains


def _elo_probability(rating_difference):
    return 1.0 / (1.0 + math.exp(-arena._Arena.ELO_SCALE * rating_difference))


def _paired_matchup_statistics(left, right, fit, data, matchup_positions):
    """Return residual, game count, and fitted score for `left` over both colors."""
    total = score = fitted_score = 0.0
    forward = matchup_positions.get((left, right))
    if forward is not None:
        games = float(data.totals[forward])
        total += games
        score += float(data.scores[forward])
        fitted_score += games * _elo_probability(
            fit.ratings[left]
            - fit.ratings[right]
            + fit.color.advantage(left, right)
        )
    reverse = matchup_positions.get((right, left))
    if reverse is not None:
        games = float(data.totals[reverse])
        total += games
        score += games - float(data.scores[reverse])
        fitted_score += games * _elo_probability(
            fit.ratings[left]
            - fit.ratings[right]
            - fit.color.advantage(right, left)
        )
    if total == 0.0:
        return 0.0, 0.0, 0.5
    fitted_probability = fitted_score / total
    return score / total - fitted_probability, total, fitted_probability


def _bernoulli_js_information(first, second):
    """Jensen-Shannon information in nats between two Bernoulli models."""
    epsilon = 1e-12

    def entropy(probability):
        probability = min(max(probability, epsilon), 1.0 - epsilon)
        return -probability * math.log(probability) - (
            1.0 - probability
        ) * math.log(1.0 - probability)

    midpoint = (first + second) / 2.0
    return max(entropy(midpoint) - (entropy(first) + entropy(second)) / 2.0, 0.0)


def nontransitivity_estimates(
    player,
    opponents,
    fit,
    data,
    matchup_positions,
    opponent_pair_counts,
):
    """Fit a residual-style GP and quantify two kinds of nontransitive gain.

    Every established player gets a fingerprint consisting of its color-aware
    score residual against every third player.  Similar fingerprints induce a
    covariance kernel for the new player's as-yet-unmodeled matchup residuals.
    Games already played by the new player condition this small Gaussian
    process.  A candidate then has:

    * uncertainty information: expected information from observing its latent
      nontransitive residual; and
    * disagreement information: Jensen-Shannon information separating the
      scalar-Elo prediction from the residual model's prediction.

    Both quantities are in nats and are zero only when the added model has
    nothing useful to distinguish among candidates.
    """
    pair_counts = opponent_pair_counts or {}
    played = tuple(opponent for opponent, count in pair_counts.items() if count)
    modeled = tuple(dict.fromkeys((*opponents, *played)))
    references = tuple(name for name in data.names if name != player)
    fingerprints = np.zeros((len(modeled), len(references)))
    historical_residuals = []
    for row, opponent in enumerate(modeled):
        for column, reference in enumerate(references):
            if reference == opponent:
                continue
            residual, games, _fitted = _paired_matchup_statistics(
                opponent, reference, fit, data, matchup_positions
            )
            if games:
                reliability = games / (games + 4.0)
                fingerprints[row, column] = residual * math.sqrt(reliability)
                historical_residuals.append(residual * math.sqrt(reliability))

    norms = np.linalg.norm(fingerprints, axis=1)
    nonzero = norms > 1e-12
    fingerprints[nonzero] /= norms[nonzero, None]
    # White noise keeps unrelated styles independent while the Gram component
    # transfers active-player residual evidence between similar opponents.
    style_kernel = 0.5 * np.eye(len(modeled)) + 0.5 * (
        fingerprints @ fingerprints.T
    )
    residual_rms = (
        math.sqrt(float(np.mean(np.square(historical_residuals))))
        if historical_residuals
        else 0.10
    )
    prior_sd = min(max(residual_rms, 0.05), 0.20)
    covariance = prior_sd**2 * style_kernel

    modeled_positions = {name: index for index, name in enumerate(modeled)}
    training = [name for name in played if name in modeled_positions]
    training_indices = [modeled_positions[name] for name in training]
    observations = []
    observation_noise = []
    for opponent in training:
        residual, games, fitted_probability = _paired_matchup_statistics(
            player, opponent, fit, data, matchup_positions
        )
        if games == 0.0:
            continue
        observations.append(residual)
        # The residual is the mean of the color-swapped Bernoulli outcomes.
        # A small floor also absorbs error from treating the fitted Elo as fixed.
        observation_noise.append(
            max(fitted_probability * (1.0 - fitted_probability) / games, 0.0025)
        )
    if len(observations) != len(training_indices):
        raise ValueError("played opponent is missing its sampled matchup data")

    candidate_indices = [modeled_positions[name] for name in opponents]
    candidate_covariance = covariance[np.ix_(candidate_indices, candidate_indices)]
    if training_indices:
        training_covariance = covariance[np.ix_(training_indices, training_indices)]
        training_covariance += np.diag(observation_noise)
        cross_covariance = covariance[np.ix_(candidate_indices, training_indices)]
        try:
            lower = np.linalg.cholesky(training_covariance)
            coefficients = _solve_cholesky(lower, np.asarray(observations))
            projected = _solve_cholesky(lower, cross_covariance.T)
        except np.linalg.LinAlgError as exc:
            raise ValueError(
                "nontransitivity covariance is not positive definite"
            ) from exc
        posterior_means = cross_covariance @ coefficients
        posterior_variances = np.diag(candidate_covariance) - np.sum(
            cross_covariance * projected.T, axis=1
        )
    else:
        posterior_means = np.zeros(len(opponents))
        posterior_variances = np.diag(candidate_covariance)

    estimates = []
    for opponent, mean, variance in zip(
        opponents, posterior_means, posterior_variances
    ):
        variance = max(float(variance), 0.0)
        _residual, _games, fitted_probability = _paired_matchup_statistics(
            player, opponent, fit, data, matchup_positions
        )
        # Noise for the next color-swapped pair (two Bernoulli observations).
        next_pair_noise = max(
            fitted_probability * (1.0 - fitted_probability) / 2.0, 0.0025
        )
        uncertainty_information = 0.5 * math.log1p(variance / next_pair_noise)
        corrected_probability = min(
            max(fitted_probability + mean, 1e-9), 1.0 - 1e-9
        )
        disagreement_information = _bernoulli_js_information(
            fitted_probability, corrected_probability
        )
        estimates.append(
            NontransitivityEstimate(
                posterior_mean=float(mean),
                posterior_variance=variance,
                uncertainty_information=uncertainty_information,
                disagreement_information=disagreement_information,
            )
        )
    return estimates


def _normalized(values):
    maximum = max(values, default=0.0)
    if maximum <= 0.0:
        return [0.0] * len(values)
    return [value / maximum for value in values]


def _nontransitivity_adjusted_gains(gains, estimates, algorithm):
    """Fold dimensionless nontransitivity information into the Elo gain."""
    uncertainty = _normalized(
        [estimate.uncertainty_information for estimate in estimates]
    )
    disagreement = _normalized(
        [estimate.disagreement_information for estimate in estimates]
    )
    if algorithm == "maximum_nontransitivity_information_gain":
        bonuses = uncertainty
    elif algorithm == "maximum_nontransitivity_disagreement_gain":
        bonuses = [2.0 * value for value in disagreement]
    elif algorithm == "maximum_nontransitivity_hybrid_gain":
        bonuses = [
            0.75 * uncertain + 1.25 * disagree
            for uncertain, disagree in zip(uncertainty, disagreement)
        ]
    else:
        raise ValueError(f"not a nontransitivity algorithm: {algorithm}")
    return [gain * (1.0 + bonus) for gain, bonus in zip(gains, bonuses)]


def rating_interval(player, fit):
    error = (
        0.0
        if player == arena._Arena.ANCHOR
        else math.sqrt(
            max(
                float(
                    fit.covariance[fit.positions[player], fit.positions[player]]
                ),
                0.0,
            )
        )
    )
    half_width = arena._Arena.CONFIDENCE_Z * error
    return fit.ratings[player] - half_width, fit.ratings[player] + half_width


def _ranked_gain_indices(opponents, gains, count=6):
    return sorted(
        range(len(opponents)), key=gains.__getitem__, reverse=True
    )[:count]


def _maximum_gain_opponent(opponents, gains):
    return opponents[max(range(len(opponents)), key=gains.__getitem__)]


def _sample_top_information_gain(
    opponents, gains, rng, count=6, *, exclude_maximum=False
):
    """Sample by gain after restricting candidates to the top `count`."""
    top_indices = _ranked_gain_indices(opponents, gains, count)
    if exclude_maximum:
        top_indices = top_indices[1:]
    if not top_indices:
        return _maximum_gain_opponent(opponents, gains)
    weights = [gains[index] for index in top_indices]
    if not any(weight > 0.0 for weight in weights):
        raise ValueError("all top matchup candidates have zero information gain")
    return rng.choices(
        [opponents[index] for index in top_indices], weights=weights, k=1
    )[0]


def _sample_softmax_information_gain(opponents, gains, rng):
    """Softmax-sample all opponents with a scale-adaptive temperature."""
    maximum = max(gains)
    median = float(np.median(gains))
    temperature = max((maximum - median) / 4.0, maximum * 1e-9, 1e-12)
    weights = [math.exp((gain - maximum) / temperature) for gain in gains]
    return rng.choices(opponents, weights=weights, k=1)[0]


def _sample_rank_weighted_top_6(opponents, gains, rng, temperature=1.5):
    top_indices = _ranked_gain_indices(opponents, gains)
    weights = [math.exp(-rank / temperature) for rank in range(len(top_indices))]
    return rng.choices(
        [opponents[index] for index in top_indices], weights=weights, k=1
    )[0]


def choose_opponent(
    player,
    opponents,
    fit,
    rng,
    algorithm,
    games_played=0,
    opponent_pair_counts=None,
    matchup_data=None,
    matchup_positions=None,
):
    """Choose one opponent according to a supported matchmaking policy."""
    gains = (
        matchmaking_gains(player, opponents, fit)
        if algorithm in INFORMATION_GAIN_ALGORITHMS
        else None
    )
    if algorithm == "maximum_information_gain":
        return _maximum_gain_opponent(opponents, gains)
    if algorithm in {
        "maximum_nontransitivity_information_gain",
        "maximum_nontransitivity_disagreement_gain",
        "maximum_nontransitivity_hybrid_gain",
    }:
        if matchup_data is None or matchup_positions is None:
            raise ValueError(
                f"{algorithm} requires the current matchup data"
            )
        estimates = nontransitivity_estimates(
            player,
            opponents,
            fit,
            matchup_data,
            matchup_positions,
            opponent_pair_counts,
        )
        adjusted_gains = _nontransitivity_adjusted_gains(
            gains, estimates, algorithm
        )
        return _maximum_gain_opponent(opponents, adjusted_gains)
    if algorithm == "proportional_information_gain":
        if not any(gain > 0.0 for gain in gains):
            raise ValueError("all available matchups have zero information gain")
        return rng.choices(opponents, weights=gains, k=1)[0]
    if algorithm == "top_6_proportional_information_gain":
        return _sample_top_information_gain(opponents, gains, rng)
    if algorithm == "maximum_first_20_then_half_top_6":
        if games_played < 20 or rng.random() < 0.5:
            return _maximum_gain_opponent(opponents, gains)
        return _sample_top_information_gain(opponents, gains, rng)
    if algorithm == "half_maximum_half_top_6":
        if rng.random() < 0.5:
            return _maximum_gain_opponent(opponents, gains)
        return _sample_top_information_gain(opponents, gains, rng)
    if algorithm == "eighty_percent_maximum_twenty_percent_top_6":
        if rng.random() < 0.8:
            return _maximum_gain_opponent(opponents, gains)
        return _sample_top_information_gain(opponents, gains, rng)
    if algorithm == "staged_max_80_50_top_6":
        if games_played < 20:
            return _maximum_gain_opponent(opponents, gains)
        maximum_probability = 0.8 if games_played < 60 else 0.5
        if rng.random() < maximum_probability:
            return _maximum_gain_opponent(opponents, gains)
        return _sample_top_information_gain(opponents, gains, rng)
    if algorithm == "exclusive_80_max_20_top_6":
        if rng.random() < 0.8:
            return _maximum_gain_opponent(opponents, gains)
        return _sample_top_information_gain(
            opponents, gains, rng, exclude_maximum=True
        )
    if algorithm == "ci_adaptive_max_top_6":
        low, high = rating_interval(player, fit)
        half_width = (high - low) / 2.0
        maximum_probability = min(1.0, max(0.5, (half_width - 50.0) / 200.0))
        if maximum_probability == 1.0 or rng.random() < maximum_probability:
            return _maximum_gain_opponent(opponents, gains)
        return _sample_top_information_gain(opponents, gains, rng)
    if algorithm == "annealed_max_top_6":
        maximum_probability = 0.5 + 0.5 * math.exp(-games_played / 30.0)
        if maximum_probability == 1.0 or rng.random() < maximum_probability:
            return _maximum_gain_opponent(opponents, gains)
        return _sample_top_information_gain(opponents, gains, rng)
    if algorithm == "softmax_information_gain":
        return _sample_softmax_information_gain(opponents, gains, rng)
    if algorithm == "rank_weighted_top_6":
        return _sample_rank_weighted_top_6(opponents, gains, rng)
    if algorithm == "diversity_penalized_information_gain":
        pair_counts = opponent_pair_counts or {}
        adjusted = [
            gain / math.sqrt(1 + pair_counts.get(opponent, 0))
            for opponent, gain in zip(opponents, gains)
        ]
        return _maximum_gain_opponent(opponents, adjusted)
    if algorithm == "robust_information_gain":
        low, high = rating_interval(player, fit)
        low_gains = matchmaking_gains(
            player, opponents, fit, player_rating=low
        )
        high_gains = matchmaking_gains(
            player, opponents, fit, player_rating=high
        )
        robust_gains = [
            min(low_gain, mean_gain, high_gain)
            for low_gain, mean_gain, high_gain in zip(low_gains, gains, high_gains)
        ]
        return _maximum_gain_opponent(opponents, robust_gains)
    if algorithm == "random_within_400_elo":
        eligible = [
            opponent
            for opponent in opponents
            if abs(fit.ratings[player] - fit.ratings[opponent]) <= 400.0
        ]
        if not eligible:
            raise ValueError(f"{player} has no available opponent within 400 Elo")
        return rng.choice(eligible)
    if algorithm == "random_overlapping_ci":
        player_low, player_high = rating_interval(player, fit)
        eligible = []
        for opponent in opponents:
            opponent_low, opponent_high = rating_interval(opponent, fit)
            if max(player_low, opponent_low) <= min(player_high, opponent_high):
                eligible.append(opponent)
        if not eligible:
            raise ValueError(
                f"{player} has no available opponent with an overlapping 95% CI"
            )
        return rng.choice(eligible)
    raise ValueError(f"unknown matchmaking algorithm: {algorithm}")


def simulate_player(
    history,
    player,
    old_fit,
    *,
    max_games,
    seed,
    matchmaking_algorithm=DEFAULT_MATCHMAKING_ALGORITHM,
    on_point=None,
):
    data, opponents, matchup_positions = candidate_data(history, player)
    initial_ratings = dict(old_fit.ratings)
    initial_ratings[player] = NEW_PLAYER_PRIOR[0]
    fit = fit_grouped(
        data,
        new_player=player,
        initial_ratings=initial_ratings,
        initial_joint_ratings=initial_ratings,
        initial_color=old_fit.color,
    )
    rng = random.Random(seed)
    opponent_pair_counts = defaultdict(int)
    remaining = {
        matchup: list(outcomes)
        for matchup, outcomes in history.outcomes.items()
        if player in matchup
    }
    trajectory = []
    for pair_number in range(1, max_games // 2 + 1):
        available = tuple(
            opponent
            for opponent in opponents
            if sum(remaining[(player, opponent)])
            and sum(remaining[(opponent, player)])
        )
        if not available:
            raise ValueError(
                f"{player} ran out of historical color-swapped pairs after "
                f"{2 * (pair_number - 1)} games"
            )
        opponent = choose_opponent(
            player,
            available,
            fit,
            rng,
            matchmaking_algorithm,
            games_played=2 * (pair_number - 1),
            opponent_pair_counts=opponent_pair_counts,
            matchup_data=data,
            matchup_positions=matchup_positions,
        )
        for matchup in ((player, opponent), (opponent, player)):
            index = matchup_positions[matchup]
            outcomes = remaining[matchup]
            score = rng.choices(
                (0.0, 0.5, 1.0), weights=outcomes, k=1
            )[0]
            outcomes[int(score * 2)] -= 1
            data.totals[index] += 1.0
            data.scores[index] += score
        opponent_pair_counts[opponent] += 1
        fit = fit_grouped(
            data,
            new_player=player,
            initial_ratings=fit.color.baseline_ratings,
            initial_joint_ratings=fit.ratings,
            initial_color=fit.color,
        )
        variance = max(
            float(fit.covariance[fit.positions[player], fit.positions[player]]), 0.0
        )
        half_width = arena._Arena.CONFIDENCE_Z * math.sqrt(variance)
        elo = fit.ratings[player]
        point = TrajectoryPoint(
            player,
            2 * pair_number,
            elo,
            elo - half_width,
            elo + half_width,
            old_fit.ratings[player],
        )
        trajectory.append(point)
        if on_point is not None:
            on_point(point)
    return trajectory


def sample_players_by_elo(old_fit, players, count):
    """Choose players nearest evenly spaced targets across the old Elo range."""
    candidates = [player for player in players if player != arena._Arena.ANCHOR]
    if count <= 0 or count > len(candidates):
        raise ValueError(
            f"player_count must be between 1 and {len(candidates)}, inclusive"
        )
    ordered = sorted(candidates, key=lambda player: (old_fit.ratings[player], player))
    targets = np.linspace(
        old_fit.ratings[ordered[0]], old_fit.ratings[ordered[-1]], count
    )
    available = set(ordered)
    selected = []
    for target in targets:
        player = min(
            available,
            key=lambda name: (
                abs(old_fit.ratings[name] - target),
                old_fit.ratings[name],
                name,
            ),
        )
        selected.append(player)
        available.remove(player)
    return tuple(selected)


def _history_signature(history):
    digest = hashlib.sha256()
    digest.update(json.dumps(history.players, separators=(",", ":")).encode())
    digest.update(json.dumps(history.matchups, separators=(",", ":")).encode())
    digest.update(np.asarray(history.totals, dtype="<f8").tobytes())
    digest.update(np.asarray(history.scores, dtype="<f8").tobytes())
    return digest.hexdigest()


def _selection_signature(players, old_fit):
    selected = [
        (player, round(old_fit.ratings[player], 5)) for player in players
    ]
    return hashlib.sha256(
        json.dumps(selected, separators=(",", ":")).encode()
    ).hexdigest()


TRAJECTORY_COLUMNS = (
    "player",
    "num_games",
    "elo",
    "ci_95_low",
    "ci_95_high",
    "old_elo",
    "elo_diff",
)


def _trajectory_values(point):
    return (
        point.player,
        point.games,
        point.elo,
        point.ci_low,
        point.ci_high,
        point.old_elo,
        point.difference,
    )


class TrajectoryCheckpoint:
    """Append trajectory rows and resume them from one self-describing CSV."""

    def __init__(
        self,
        path,
        *,
        history,
        players,
        old_fit,
        max_games,
        seed,
        matchmaking_algorithm,
    ):
        self.path = path
        self.player_order = {player: index for index, player in enumerate(players)}
        self.max_games = max_games
        self.old_fit = old_fit
        self._points = {}
        self.metadata = {
            "checkpoint_schema_version": "2",
            "history_sha256": _history_signature(history),
            "selection_sha256": _selection_signature(players, old_fit),
            "max_games": str(max_games),
            "seed": str(seed),
            "matchmaking_algorithm": matchmaking_algorithm,
            "new_player_prior_mean": str(NEW_PLAYER_PRIOR[0]),
            "new_player_prior_sd": str(NEW_PLAYER_PRIOR[1]),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self._load()
        else:
            write_trajectory(self.path, (), metadata=self.metadata)

    def _load(self):
        with self.path.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            required = set(TRAJECTORY_COLUMNS) | set(self.metadata)
            if not required <= set(reader.fieldnames or ()):
                raise ValueError(f"checkpoint is missing columns: {self.path}")
            for row in reader:
                actual_metadata = {key: row[key] for key in self.metadata}
                if actual_metadata != self.metadata:
                    raise ValueError(
                        f"checkpoint settings or game history do not match: "
                        f"{self.path}"
                    )
                point = TrajectoryPoint(
                    player=row["player"],
                    games=int(row["num_games"]),
                    elo=float(row["elo"]),
                    ci_low=float(row["ci_95_low"]),
                    ci_high=float(row["ci_95_high"]),
                    old_elo=float(row["old_elo"]),
                )
                if point.player not in self.player_order:
                    raise ValueError(
                        f"checkpoint contains unexpected player {point.player!r}"
                    )
                key = point.player, point.games
                if key in self._points:
                    raise ValueError(f"checkpoint contains duplicate row {key}")
                self._points[key] = point
        for player in self.player_order:
            games = sorted(
                point.games
                for point in self._points.values()
                if point.player == player
            )
            expected_games = list(range(2, (games[-1] if games else 0) + 1, 2))
            if games != expected_games or games and games[-1] > self.max_games:
                raise ValueError(f"checkpoint has invalid trajectory for {player}")
            if any(
                not math.isclose(
                    point.old_elo,
                    self.old_fit.ratings[player],
                    rel_tol=1e-10,
                    abs_tol=1e-5,
                )
                for point in self._points.values()
                if point.player == player
            ):
                raise ValueError(f"checkpoint old Elo does not match for {player}")

    def points(self):
        return sorted(
            self._points.values(),
            key=lambda point: (self.player_order[point.player], point.games),
        )

    def record(self, point):
        key = point.player, point.games
        existing = self._points.get(key)
        if existing is not None:
            fields = ("elo", "ci_low", "ci_high", "old_elo")
            if any(
                not math.isclose(
                    getattr(existing, field),
                    getattr(point, field),
                    rel_tol=1e-10,
                    abs_tol=1e-5,
                )
                for field in fields
            ):
                raise ValueError(f"resumed trajectory changed at {key}")
            return
        with self.path.open("a", encoding="utf-8", newline="") as destination:
            writer = csv.writer(destination)
            writer.writerow((*_trajectory_values(point), *self.metadata.values()))
        self._points[key] = point


def run_ablation(
    history,
    *,
    max_games=DEFAULT_MAX_GAMES,
    player_count=DEFAULT_PLAYER_COUNT,
    seed=arena._Arena.RANDOM_SEED,
    matchmaking_algorithm=DEFAULT_MATCHMAKING_ALGORITHM,
    selected_players=None,
    checkpoint_path=None,
    progress=None,
):
    if max_games <= 0 or max_games % 2:
        raise ValueError("max_games must be a positive even number")
    if matchmaking_algorithm not in MATCHMAKING_ALGORITHMS:
        raise ValueError(
            f"unknown matchmaking algorithm: {matchmaking_algorithm}"
        )
    old_fit = fit_grouped(
        grouped_data(
            history.players, history.matchups, history.totals, history.scores
        )
    )
    if selected_players is None:
        players = sample_players_by_elo(old_fit, history.players, player_count)
    else:
        requested = tuple(selected_players)
        unknown = set(requested) - set(history.players)
        if unknown:
            raise ValueError(
                f"players not found in history: {', '.join(sorted(unknown))}"
            )
        players = tuple(p for p in requested if p != arena._Arena.ANCHOR)
    checkpoint = (
        TrajectoryCheckpoint(
            Path(checkpoint_path),
            history=history,
            players=players,
            old_fit=old_fit,
            max_games=max_games,
            seed=seed,
            matchmaking_algorithm=matchmaking_algorithm,
        )
        if checkpoint_path is not None
        else None
    )
    trajectories = [] if checkpoint is None else checkpoint.points()
    completed = {
        point.player
        for point in trajectories
        if point.games == max_games
    }
    for player_number, player in enumerate(players, start=1):
        if player in completed:
            if progress is not None:
                progress(
                    f"[{matchmaking_algorithm}] "
                    f"[{player_number}/{len(players)}] {player}: resumed at "
                    f"{max_games}/{max_games} games"
                )
            continue

        def record(point):
            if checkpoint is not None:
                checkpoint.record(point)
            if progress is not None:
                progress(
                    f"[{matchmaking_algorithm}] "
                    f"[{player_number}/{len(players)}] {player}: "
                    f"{point.games}/{max_games} games, Elo {point.elo:.1f}, "
                    f"95% CI [{point.ci_low:.1f}, {point.ci_high:.1f}]"
                )

        result = simulate_player(
            history,
            player,
            old_fit,
            max_games=max_games,
            seed=seed + history.players.index(player),
            matchmaking_algorithm=matchmaking_algorithm,
            on_point=record,
        )
        if checkpoint is None:
            trajectories.extend(result)
        else:
            trajectories = checkpoint.points()
    return old_fit, trajectories


def _table(headers, rows, *, left=()):
    rows = [tuple(str(value) for value in row) for row in rows]
    widths = [
        max([len(header), *(len(row[index]) for row in rows)])
        for index, header in enumerate(headers)
    ]
    left = set(left)

    def line(row):
        return "  ".join(
            f"{value:<{width}}" if index in left else f"{value:>{width}}"
            for index, (value, width) in enumerate(zip(row, widths))
        )

    separator = tuple("-" * width for width in widths)
    return "\n".join((line(headers), line(separator), *(line(row) for row in rows)))


def format_tables(old_fit, trajectories):
    final = {}
    differences_by_games = defaultdict(list)
    for point in trajectories:
        final[point.player] = point
        differences_by_games[point.games].append(abs(point.difference))
    final_rows = sorted(final.values(), key=lambda row: (-row.old_elo, row.player))
    first = _table(
        ("Player", "Old Elo", "New Elo", "Diff", "New 95% CI"),
        (
            (
                row.player,
                f"{row.old_elo:.1f}",
                f"{row.elo:.1f}",
                f"{row.difference:+.1f}",
                f"[{row.ci_low:.1f}, {row.ci_high:.1f}]",
            )
            for row in final_rows
        ),
        left=(0,),
    )
    second = _table(
        ("Num Games", "Avg |Elo Diff|"),
        (
            (games, f"{sum(values) / len(values):.1f}")
            for games, values in sorted(differences_by_games.items())
        ),
    )
    return first, second


def write_trajectory(path, trajectories, metadata=None):
    metadata = {} if metadata is None else metadata
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination)
        writer.writerow((*TRAJECTORY_COLUMNS, *metadata))
        for point in trajectories:
            writer.writerow((*_trajectory_values(point), *metadata.values()))
    temporary.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-root", type=Path, default=arena._Arena.LOG_ROOT)
    parser.add_argument("--max-games", type=int, default=DEFAULT_MAX_GAMES)
    parser.add_argument("--player-count", type=int, default=DEFAULT_PLAYER_COUNT)
    parser.add_argument("--seed", type=int, default=arena._Arena.RANDOM_SEED)
    parser.add_argument(
        "--matchmaking-algorithm",
        "--algorithm",
        choices=MATCHMAKING_ALGORITHMS,
        default=DEFAULT_MATCHMAKING_ALGORITHM,
    )
    parser.add_argument(
        "--players",
        nargs="+",
        metavar="PLAYER",
        help="run only these players (useful for a quick ablation)",
    )
    parser.add_argument(
        "--trajectory-csv",
        type=Path,
        help="incrementally checkpoint every Elo and CI; matching runs resume",
    )
    args = parser.parse_args(argv)
    try:
        history = load_history(args.log_root)
        old_fit, trajectories = run_ablation(
            history,
            max_games=args.max_games,
            player_count=args.player_count,
            seed=args.seed,
            matchmaking_algorithm=args.matchmaking_algorithm,
            selected_players=tuple(args.players) if args.players else None,
            checkpoint_path=args.trajectory_csv,
            progress=lambda message: print(message, file=sys.stderr, flush=True),
        )
        first, second = format_tables(old_fit, trajectories)
    except (OSError, ValueError, arena.ArenaError) as exc:
        parser.error(str(exc))
    print(first)
    print()
    print(second)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
