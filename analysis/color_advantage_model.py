#!/usr/bin/env python3
"""Compare Bradley--Terry color-advantage models on arena result files.

Inputs can be analysed independently or combined.  Scores of 1, 0, and 0.5
are treated as a Black win, White win, and half a win respectively.  The
random player is fixed at zero Elo when present; otherwise the
lexicographically first player is used as the reference.

The nonlinear matchup covariates are calculated once from the no-color fit.
This makes the subsequent models ordinary penalized Bradley--Terry models and
avoids feeding a model's own color estimate back into its strength covariate.
Confidence intervals are marginal Wald intervals from the joint penalized
Fisher/Laplace covariance, including all fitted color-effect parameters.
Grouped cross-validation keeps each scheduled color-swapped game pair in one
fold and repeats the complete two-stage fit using training games only.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from gobench.paths import ROOT

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover - exercised only on a bad install
    raise SystemExit("color_advantage_model.py requires NumPy") from exc

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover - exercised only on a bad install
    raise SystemExit("color_advantage_model.py requires Pillow for PNG plots") from exc


DEFAULT_INPUTS = (
    ROOT / "log/arena_20260717_215813_957127_3b740750/results.csv",
    ROOT / "log/arena_20260722_210708_427338_47435160/results.csv",
    ROOT / "log/arena_20260723_055601_438304_148a54e8/results.csv",
    ROOT / "log/arena_20260805_040447_246130_2072c54f/results.csv",
)
DEFAULT_CV_FOLDS = 5
DEFAULT_CV_SEED = 1729
PIECEWISE_LINEAR_SPACINGS = (250, 500, 1500)
PIECEWISE_CONSTANT_SPACINGS = (250, 500)
ELO_TO_LOGIT = math.log(10.0) / 400.0
CONFIDENCE_Z = 1.959963984540054
RATING_PRIOR_SD = 10_000.0
FIXED_COLOR_PRIOR_SD = 10_000.0
PLAYER_COLOR_PRIOR_SD = 100.0
SOURCE_COLOR_PRIOR_SD = 100.0
ANCHOR_CANDIDATE = "kata1-random"


class ModelError(RuntimeError):
    """An input or numerical fit is invalid."""


@dataclass(frozen=True)
class GameGroup:
    black: str
    white: str
    source: str
    games: int
    black_score: float


@dataclass(frozen=True)
class GameObservation:
    run: str
    game: int
    batch: int
    pair: int
    black: str
    white: str
    source: str
    score_black: float

    @property
    def pair_key(self) -> tuple[str, int, int]:
        return self.run, self.batch, self.pair


@dataclass(frozen=True)
class Dataset:
    path: Path
    groups: tuple[GameGroup, ...]
    players: tuple[str, ...]
    sources: tuple[str, ...]
    games: int


@dataclass(frozen=True)
class Parameter:
    name: str
    kind: str
    prior_sd: float


@dataclass
class ModelResult:
    name: str
    description: str
    parameters: tuple[Parameter, ...]
    coefficients: np.ndarray
    covariance: np.ndarray
    design: np.ndarray
    converged: bool
    iterations: int
    log_likelihood: float
    penalized_log_likelihood: float
    effective_parameters: float
    parameter_positions: dict[str, int]


@dataclass(frozen=True)
class CrossValidationSummary:
    model: str
    test_games: int
    log_loss: float
    fold_standard_error: float
    paired_delta_standard_error: float
    fold_log_losses: tuple[float, ...]


@dataclass(frozen=True)
class Covariates:
    average_elo: np.ndarray
    gap_elo: np.ndarray
    average_center: float
    average_scale: float
    gap_center: float
    gap_scale: float

    @property
    def average_z(self) -> np.ndarray:
        return (self.average_elo - self.average_center) / self.average_scale

    @property
    def gap_z(self) -> np.ndarray:
        return (self.gap_elo - self.gap_center) / self.gap_scale


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return slug or "dataset"


def _read_dataset(path: Path) -> Dataset:
    if not path.is_file():
        raise ModelError(f"input does not exist: {path}")

    required = {"black", "white", "score_black"}
    aggregates: dict[tuple[str, str, str], list[float]] = {}
    players: set[str] = set()
    sources: set[str] = set()
    games = 0
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise ModelError(f"{path} is missing columns: {', '.join(sorted(missing))}")
        for line_number, row in enumerate(reader, start=2):
            black = row["black"].strip()
            white = row["white"].strip()
            source = row.get("source", "").strip() or "unknown"
            if not black or not white:
                raise ModelError(f"{path}:{line_number}: blank player name")
            try:
                score = float(row["score_black"])
            except ValueError as exc:
                raise ModelError(
                    f"{path}:{line_number}: invalid score_black {row['score_black']!r}"
                ) from exc
            if not math.isfinite(score) or not 0.0 <= score <= 1.0:
                raise ModelError(f"{path}:{line_number}: score_black must be in [0, 1]")
            entry = aggregates.setdefault((black, white, source), [0.0, 0.0])
            entry[0] += 1.0
            entry[1] += score
            players.update((black, white))
            sources.add(source)
            games += 1

    if games == 0:
        raise ModelError(f"input contains no games: {path}")
    ordered_groups = tuple(
        GameGroup(black, white, source, int(values[0]), values[1])
        for (black, white, source), values in sorted(aggregates.items())
    )
    return Dataset(
        path=path.resolve(),
        groups=ordered_groups,
        players=tuple(sorted(players)),
        sources=tuple(sorted(sources)),
        games=games,
    )


def _dataset_from_observations(
    observations: Sequence[GameObservation],
    path: Path,
    *,
    players: Sequence[str] | None = None,
    sources: Sequence[str] | None = None,
) -> Dataset:
    if not observations:
        raise ModelError("cannot construct an empty dataset")
    aggregates: dict[tuple[str, str, str], list[float]] = {}
    observed_players: set[str] = set()
    observed_sources: set[str] = set()
    for game in observations:
        entry = aggregates.setdefault(
            (game.black, game.white, game.source), [0.0, 0.0]
        )
        entry[0] += 1.0
        entry[1] += game.score_black
        observed_players.update((game.black, game.white))
        observed_sources.add(game.source)
    all_players = tuple(sorted(players or observed_players))
    all_sources = tuple(sorted(sources or observed_sources))
    if not observed_players.issubset(all_players):
        raise ModelError("dataset player list omits an observed player")
    if not observed_sources.issubset(all_sources):
        raise ModelError("dataset source list omits an observed source")
    return Dataset(
        path=path.resolve(),
        groups=tuple(
            GameGroup(black, white, source, int(values[0]), values[1])
            for (black, white, source), values in sorted(aggregates.items())
        ),
        players=all_players,
        sources=all_sources,
        games=len(observations),
    )


def _read_paired_observations(paths: Sequence[Path]) -> tuple[GameObservation, ...]:
    observations: list[GameObservation] = []
    pairs: dict[tuple[str, int, int], list[GameObservation]] = {}
    for supplied_path in paths:
        path = supplied_path.resolve()
        if not path.is_file():
            raise ModelError(f"input does not exist: {path}")
        metadata_path = path.parent / "run.json"
        if not metadata_path.is_file():
            raise ModelError(f"paired cross-validation requires {metadata_path}")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        policy = metadata.get("batch_policy")
        if not isinstance(policy, dict):
            raise ModelError(f"{metadata_path} has no batch_policy")
        games_per_batch = int(policy.get("games_per_batch", 0))
        pairs_value = policy.get("sampled_pairs_per_batch")
        rule = str(policy.get("rule", "")).lower()
        if pairs_value is None and "paired colors" in rule:
            pairs_per_batch = games_per_batch // 2
        else:
            pairs_per_batch = int(pairs_value or 0)
        if games_per_batch != 2 * pairs_per_batch or pairs_per_batch <= 0:
            raise ModelError(
                f"{metadata_path} does not describe color-swapped game pairs"
            )
        required = {"game", "batch", "black", "white", "score_black"}
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = required.difference(reader.fieldnames or ())
            if missing:
                raise ModelError(
                    f"{path} is missing columns: {', '.join(sorted(missing))}"
                )
            for line_number, row in enumerate(reader, start=2):
                try:
                    game_number = int(row["game"])
                    batch = int(row["batch"])
                    score = float(row["score_black"])
                except ValueError as exc:
                    raise ModelError(
                        f"{path}:{line_number}: invalid game, batch, or score"
                    ) from exc
                expected_batch = (game_number - 1) // games_per_batch + 1
                if batch != expected_batch:
                    raise ModelError(
                        f"{path}:{line_number}: game {game_number} is in unexpected "
                        f"batch {batch}, expected {expected_batch}"
                    )
                if not math.isfinite(score) or not 0.0 <= score <= 1.0:
                    raise ModelError(
                        f"{path}:{line_number}: score_black must be in [0, 1]"
                    )
                position = (game_number - 1) % games_per_batch
                observation = GameObservation(
                    run=path.parent.name,
                    game=game_number,
                    batch=batch,
                    pair=position % pairs_per_batch,
                    black=row["black"].strip(),
                    white=row["white"].strip(),
                    source=row.get("source", "").strip() or "unknown",
                    score_black=score,
                )
                if not observation.black or not observation.white:
                    raise ModelError(f"{path}:{line_number}: blank player name")
                observations.append(observation)
                pairs.setdefault(observation.pair_key, []).append(observation)
    for key, games in pairs.items():
        if len(games) != 2:
            raise ModelError(f"scheduled pair {key} contains {len(games)} games")
        first, second = games
        if (first.black, first.white) != (second.white, second.black):
            raise ModelError(f"scheduled pair {key} is not color-swapped")
    return tuple(observations)


def _network_checkpoint_count(players: Sequence[str]) -> int:
    return len(
        {
            player.partition("-temp-")[0]
            for player in players
            if player != ANCHOR_CANDIDATE
        }
    )


def _anchor_for(dataset: Dataset) -> str:
    return (
        ANCHOR_CANDIDATE
        if ANCHOR_CANDIDATE in dataset.players
        else dataset.players[0]
    )


def _base_rating_design(
    dataset: Dataset, anchor: str
) -> tuple[np.ndarray, tuple[Parameter, ...], dict[str, int]]:
    variable_players = tuple(player for player in dataset.players if player != anchor)
    positions = {player: index for index, player in enumerate(variable_players)}
    design = np.zeros((len(dataset.groups), len(variable_players)), dtype=float)
    for row, group in enumerate(dataset.groups):
        if group.black in positions:
            design[row, positions[group.black]] += 1.0
        if group.white in positions:
            design[row, positions[group.white]] -= 1.0
    parameters = tuple(
        Parameter(f"rating:{player}", "rating", RATING_PRIOR_SD)
        for player in variable_players
    )
    return design, parameters, positions


def _scores(dataset: Dataset) -> tuple[np.ndarray, np.ndarray]:
    successes = np.asarray([group.black_score for group in dataset.groups])
    totals = np.asarray([group.games for group in dataset.groups], dtype=float)
    return successes, totals


def _sigmoid(values: np.ndarray) -> np.ndarray:
    result = np.empty_like(values)
    nonnegative = values >= 0.0
    result[nonnegative] = 1.0 / (1.0 + np.exp(-values[nonnegative]))
    exponential = np.exp(values[~nonnegative])
    result[~nonnegative] = exponential / (1.0 + exponential)
    return result


def _log_likelihood(
    design: np.ndarray,
    coefficients: np.ndarray,
    successes: np.ndarray,
    totals: np.ndarray,
) -> float:
    logits = ELO_TO_LOGIT * (design @ coefficients)
    return float(np.sum(successes * logits - totals * np.logaddexp(0.0, logits)))


def _fit(
    name: str,
    description: str,
    design: np.ndarray,
    parameters: Sequence[Parameter],
    successes: np.ndarray,
    totals: np.ndarray,
    initial: np.ndarray | None = None,
) -> ModelResult:
    parameter_tuple = tuple(parameters)
    if design.shape[1] != len(parameter_tuple):
        raise AssertionError("design and parameter count disagree")
    coefficients = (
        np.zeros(design.shape[1], dtype=float)
        if initial is None
        else np.asarray(initial, dtype=float).copy()
    )
    precisions = np.asarray([1.0 / p.prior_sd**2 for p in parameter_tuple])

    def penalized_objective(candidate: np.ndarray) -> float:
        return _log_likelihood(design, candidate, successes, totals) - float(
            0.5 * np.dot(precisions * candidate, candidate)
        )

    converged = False
    iterations = 0
    for iterations in range(1, 101):
        logits = ELO_TO_LOGIT * (design @ coefficients)
        probabilities = _sigmoid(logits)
        residuals = successes - totals * probabilities
        weights = totals * probabilities * (1.0 - probabilities)
        gradient = ELO_TO_LOGIT * (design.T @ residuals) - precisions * coefficients
        information = (
            ELO_TO_LOGIT**2 * (design.T @ (weights[:, None] * design))
            + np.diag(precisions)
        )
        try:
            change = np.linalg.solve(information, gradient)
        except np.linalg.LinAlgError:
            change = np.linalg.lstsq(information, gradient, rcond=None)[0]

        current = penalized_objective(coefficients)
        step = 1.0
        while step >= 2.0**-20:
            candidate = coefficients + step * change
            if penalized_objective(candidate) >= current - 1e-10:
                coefficients = candidate
                break
            step *= 0.5
        else:
            break
        if float(np.max(np.abs(step * change), initial=0.0)) < 1e-7:
            converged = True
            break

    logits = ELO_TO_LOGIT * (design @ coefficients)
    probabilities = _sigmoid(logits)
    weights = totals * probabilities * (1.0 - probabilities)
    information = (
        ELO_TO_LOGIT**2 * (design.T @ (weights[:, None] * design))
        + np.diag(precisions)
    )
    try:
        covariance = np.linalg.inv(information)
    except np.linalg.LinAlgError:
        covariance = np.linalg.pinv(information, rcond=1e-12)
    covariance = 0.5 * (covariance + covariance.T)
    data_information = information - np.diag(precisions)
    effective_parameters = float(np.trace(data_information @ covariance))
    log_likelihood = _log_likelihood(design, coefficients, successes, totals)
    penalized = log_likelihood - float(0.5 * np.dot(precisions * coefficients, coefficients))
    return ModelResult(
        name=name,
        description=description,
        parameters=parameter_tuple,
        coefficients=coefficients,
        covariance=covariance,
        design=design,
        converged=converged,
        iterations=iterations,
        log_likelihood=log_likelihood,
        penalized_log_likelihood=penalized,
        effective_parameters=effective_parameters,
        parameter_positions={p.name: index for index, p in enumerate(parameter_tuple)},
    )


def _fit_negative_exponential(
    name: str,
    description: str,
    base_design: np.ndarray,
    base_parameters: tuple[Parameter, ...],
    average_unit: np.ndarray,
    successes: np.ndarray,
    totals: np.ndarray,
    baseline: ModelResult,
    player_effects: np.ndarray | None = None,
    player_names: Sequence[str] | None = None,
    player_prior_sd: float | None = None,
) -> ModelResult:
    """Fit color advantage ``-a * exp(-b*x)`` with a,b constrained nonnegative."""
    rating_count = len(base_parameters)
    player_count = 0 if player_effects is None else player_effects.shape[1]
    if player_count != len(player_names or ()):
        raise ValueError("player-effect columns and player names disagree")
    player_parameters = tuple(
        Parameter(f"player_color:{player}", "player_color", float(player_prior_sd))
        for player in (player_names or ())
    )
    parameters = (
        *base_parameters,
        Parameter("color:negative_exp_a_elo", "fixed_color", FIXED_COLOR_PRIOR_SD),
        Parameter("color:negative_exp_b_per_unit", "fixed_shape", 10.0),
        *player_parameters,
    )
    a_position = rating_count
    b_position = rating_count + 1
    player_start = rating_count + 2
    precisions = np.asarray([1.0 / parameter.prior_sd**2 for parameter in parameters])

    def predictor_and_jacobian(candidate: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        a = candidate[a_position]
        b = candidate[b_position]
        exponential = np.exp(-b * average_unit)
        predictor = base_design @ candidate[:rating_count] - a * exponential
        jacobian = np.zeros((len(average_unit), len(parameters)), dtype=float)
        jacobian[:, :rating_count] = base_design
        jacobian[:, a_position] = -exponential
        jacobian[:, b_position] = a * average_unit * exponential
        if player_effects is not None:
            predictor += player_effects @ candidate[player_start:]
            jacobian[:, player_start:] = player_effects
        return predictor, jacobian

    def objective(candidate: np.ndarray) -> float:
        if candidate[a_position] < 0.0 or candidate[b_position] < 0.0:
            return -math.inf
        predictor, _jacobian = predictor_and_jacobian(candidate)
        logits = ELO_TO_LOGIT * predictor
        likelihood = float(
            np.sum(successes * logits - totals * np.logaddexp(0.0, logits))
        )
        return likelihood - float(0.5 * np.dot(precisions * candidate, candidate))

    # Profile several decay rates with an ordinary linear fit to obtain a
    # stable starting point for the joint nonlinear optimization.
    best_initial: np.ndarray | None = None
    best_objective = -math.inf
    for initial_b in (0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0):
        exponential_column = -np.exp(-initial_b * average_unit)
        columns = [base_design, exponential_column[:, None]]
        linear_parameters: tuple[Parameter, ...] = (
            *base_parameters,
            Parameter("color:negative_exp_a_elo", "fixed_color", FIXED_COLOR_PRIOR_SD),
        )
        if player_effects is not None:
            columns.append(player_effects)
            linear_parameters = (*linear_parameters, *player_parameters)
        linear_design = np.column_stack(columns)
        initial_linear = np.zeros(len(linear_parameters))
        initial_linear[:rating_count] = baseline.coefficients[:rating_count]
        initial_linear[a_position] = 100.0
        profiled = _fit(
            "profile",
            "profile",
            linear_design,
            linear_parameters,
            successes,
            totals,
            initial_linear,
        )
        if profiled.coefficients[a_position] < 0.0:
            continue
        candidate = np.zeros(len(parameters))
        candidate[: rating_count + 1] = profiled.coefficients[: rating_count + 1]
        candidate[b_position] = initial_b
        if player_effects is not None:
            candidate[player_start:] = profiled.coefficients[rating_count + 1 :]
        candidate_objective = objective(candidate)
        if candidate_objective > best_objective:
            best_objective = candidate_objective
            best_initial = candidate
    if best_initial is None:
        best_initial = np.zeros(len(parameters))
        best_initial[:rating_count] = baseline.coefficients[:rating_count]
        best_initial[a_position] = 1.0
        best_initial[b_position] = 1.0

    coefficients = best_initial
    converged = False
    iterations = 0
    for iterations in range(1, 201):
        predictor, jacobian = predictor_and_jacobian(coefficients)
        probabilities = _sigmoid(ELO_TO_LOGIT * predictor)
        residuals = successes - totals * probabilities
        weights = totals * probabilities * (1.0 - probabilities)
        gradient = ELO_TO_LOGIT * (jacobian.T @ residuals) - precisions * coefficients
        information = (
            ELO_TO_LOGIT**2 * (jacobian.T @ (weights[:, None] * jacobian))
            + np.diag(precisions)
        )
        try:
            change = np.linalg.solve(information, gradient)
        except np.linalg.LinAlgError:
            change = np.linalg.lstsq(information, gradient, rcond=None)[0]
        current = objective(coefficients)
        step = 1.0
        while step >= 2.0**-24:
            candidate = coefficients + step * change
            if objective(candidate) >= current - 1e-10:
                coefficients = candidate
                break
            step *= 0.5
        else:
            break
        improvement = objective(coefficients) - current
        if (
            float(np.max(np.abs(step * change), initial=0.0)) < 1e-7
            or improvement < 1e-9 * (1.0 + abs(current))
        ):
            converged = True
            break

    predictor, jacobian = predictor_and_jacobian(coefficients)
    probabilities = _sigmoid(ELO_TO_LOGIT * predictor)
    weights = totals * probabilities * (1.0 - probabilities)
    information = (
        ELO_TO_LOGIT**2 * (jacobian.T @ (weights[:, None] * jacobian))
        + np.diag(precisions)
    )
    covariance = np.linalg.pinv(information, rcond=1e-12)
    covariance = 0.5 * (covariance + covariance.T)
    data_information = information - np.diag(precisions)
    effective_parameters = float(np.trace(data_information @ covariance))
    logits = ELO_TO_LOGIT * predictor
    log_likelihood = float(
        np.sum(successes * logits - totals * np.logaddexp(0.0, logits))
    )
    return ModelResult(
        name=name,
        description=description,
        parameters=parameters,
        coefficients=coefficients,
        covariance=covariance,
        design=jacobian,
        converged=converged,
        iterations=iterations,
        log_likelihood=log_likelihood,
        penalized_log_likelihood=objective(coefficients),
        effective_parameters=effective_parameters,
        parameter_positions={parameter.name: index for index, parameter in enumerate(parameters)},
    )


def _weighted_center_scale(values: np.ndarray, weights: np.ndarray) -> tuple[float, float]:
    center = float(np.average(values, weights=weights))
    variance = float(np.average((values - center) ** 2, weights=weights))
    return center, max(math.sqrt(variance), 1.0)


def _make_covariates(
    dataset: Dataset,
    baseline: ModelResult,
    rating_positions: dict[str, int],
    totals: np.ndarray,
    anchor: str,
) -> Covariates:
    def rating(player: str) -> float:
        return 0.0 if player == anchor else float(baseline.coefficients[rating_positions[player]])

    averages = np.asarray(
        [0.5 * (rating(group.black) + rating(group.white)) for group in dataset.groups]
    )
    gaps = np.asarray(
        [abs(rating(group.black) - rating(group.white)) for group in dataset.groups]
    )
    average_center, average_scale = _weighted_center_scale(averages, totals)
    gap_center, gap_scale = _weighted_center_scale(gaps, totals)
    return Covariates(
        average_elo=averages,
        gap_elo=gaps,
        average_center=average_center,
        average_scale=average_scale,
        gap_center=gap_center,
        gap_scale=gap_scale,
    )


def _column(values: np.ndarray) -> np.ndarray:
    return np.asarray(values, dtype=float).reshape((-1, 1))


def _orthogonal_quadratic(values: np.ndarray) -> np.ndarray:
    return values**2 - 1.0


def _weighted_quantiles(
    values: np.ndarray, weights: np.ndarray, probabilities: Sequence[float]
) -> np.ndarray:
    """Return linearly interpolated weighted quantiles."""
    order = np.argsort(values)
    ordered_values = values[order]
    ordered_weights = weights[order]
    cumulative = np.cumsum(ordered_weights) - 0.5 * ordered_weights
    cumulative /= float(np.sum(ordered_weights))
    return np.interp(np.asarray(probabilities), cumulative, ordered_values)


def _cubic_bspline_knots(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Return the clamped knot vector for the fitted cubic B-spline."""
    degree = 3
    lower = float(np.min(values))
    upper = float(np.max(values))
    if upper - lower < 1e-12:
        return np.asarray([lower, upper], dtype=float)
    candidates = _weighted_quantiles(values, weights, (0.2, 0.4, 0.6, 0.8))
    tolerance = max((upper - lower) * 1e-10, 1e-12)
    interior: list[float] = []
    for candidate in candidates:
        value = float(candidate)
        if value <= lower + tolerance or value >= upper - tolerance:
            continue
        if not interior or value - interior[-1] > tolerance:
            interior.append(value)
    return np.asarray(
        [lower] * (degree + 1) + interior + [upper] * (degree + 1),
        dtype=float,
    )


def _cubic_bspline_basis_from_knots(
    values: np.ndarray, knots: np.ndarray
) -> np.ndarray:
    """Evaluate a clamped cubic B-spline basis at new values."""
    degree = 3
    if len(knots) == 2:
        return np.ones((len(values), 1), dtype=float)
    lower = float(knots[0])
    upper = float(knots[-1])

    basis = np.zeros((len(values), len(knots) - 1), dtype=float)
    for index in range(len(knots) - 1):
        basis[:, index] = (
            (values >= knots[index]) & (values < knots[index + 1])
        )
    basis[values == upper, len(knots) - degree - 2] = 1.0
    for current_degree in range(1, degree + 1):
        columns = len(knots) - current_degree - 1
        next_basis = np.zeros((len(values), columns), dtype=float)
        for index in range(columns):
            left_denominator = knots[index + current_degree] - knots[index]
            right_denominator = (
                knots[index + current_degree + 1] - knots[index + 1]
            )
            if left_denominator > 0.0:
                next_basis[:, index] += (
                    (values - knots[index]) / left_denominator
                ) * basis[:, index]
            if right_denominator > 0.0:
                next_basis[:, index] += (
                    (knots[index + current_degree + 1] - values)
                    / right_denominator
                ) * basis[:, index + 1]
        basis = next_basis
    if not np.allclose(np.sum(basis, axis=1), 1.0, atol=1e-10):
        raise ModelError("B-spline basis does not form a partition of unity")
    return basis


def _cubic_bspline_basis(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Return a clamped cubic B-spline basis with four weighted-quantile knots."""
    return _cubic_bspline_basis_from_knots(
        values, _cubic_bspline_knots(values, weights)
    )


def _fixed_elo_nodes(values: np.ndarray, spacing: float) -> np.ndarray:
    """Return observed boundaries and regularly spaced absolute-Elo nodes."""
    lower = float(np.min(values))
    upper = float(np.max(values))
    if spacing <= 0.0:
        raise ValueError("piecewise-linear spacing must be positive")
    if upper - lower < 1e-12:
        return np.asarray([lower])
    first = (math.floor(lower / spacing) + 1) * spacing
    regular = list(np.arange(first, upper, spacing, dtype=float))
    # Merge a very short tail into the preceding segment.  This deliberately
    # permits the last segment to be longer than the requested nominal spacing.
    if regular and upper - regular[-1] < 0.5 * spacing:
        regular.pop()
    return np.asarray([lower, *regular, upper], dtype=float)


def _piecewise_linear_basis(
    values: np.ndarray, nodes: np.ndarray
) -> np.ndarray:
    """Return continuous linear hat functions at the supplied nodes."""
    if len(nodes) == 1:
        return np.ones((len(values), 1), dtype=float)
    if np.any(np.diff(nodes) <= 0.0):
        raise ValueError("piecewise-linear nodes must be strictly increasing")
    basis = np.zeros((len(values), len(nodes)), dtype=float)
    for row, value in enumerate(values):
        if value <= nodes[0]:
            basis[row, 0] = 1.0
            continue
        if value >= nodes[-1]:
            basis[row, -1] = 1.0
            continue
        left = int(np.searchsorted(nodes, value, side="right") - 1)
        fraction = (value - nodes[left]) / (nodes[left + 1] - nodes[left])
        basis[row, left] = 1.0 - fraction
        basis[row, left + 1] = fraction
    if not np.allclose(np.sum(basis, axis=1), 1.0, atol=1e-12):
        raise ModelError("piecewise-linear basis does not form a partition of unity")
    return basis


def _piecewise_constant_basis(values: np.ndarray, nodes: np.ndarray) -> np.ndarray:
    """Return one-hot interval indicators for a discontinuous step function."""
    if len(nodes) == 1:
        return np.ones((len(values), 1), dtype=float)
    if np.any(np.diff(nodes) <= 0.0):
        raise ValueError("piecewise-constant nodes must be strictly increasing")
    basis = np.zeros((len(values), len(nodes) - 1), dtype=float)
    intervals = np.searchsorted(nodes[1:-1], values, side="right")
    basis[np.arange(len(values)), intervals] = 1.0
    return basis


def _model_inputs(
    dataset: Dataset,
    base_design: np.ndarray,
    base_parameters: tuple[Parameter, ...],
    covariates: Covariates,
) -> list[tuple[str, str, np.ndarray, tuple[Parameter, ...]]]:
    rows = len(dataset.groups)
    ones = np.ones(rows)
    average_z = covariates.average_z
    average_min = float(np.min(covariates.average_elo))
    average_range = float(np.max(covariates.average_elo) - average_min)
    average_unit = (
        np.zeros_like(covariates.average_elo)
        if average_range < 1e-12
        else (covariates.average_elo - average_min) / average_range
    )
    game_weights = np.asarray([group.games for group in dataset.groups], dtype=float)
    average_spline = _cubic_bspline_basis(average_unit, game_weights)
    piecewise: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    piecewise_constant: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for spacing in PIECEWISE_LINEAR_SPACINGS:
        elo_nodes = _fixed_elo_nodes(covariates.average_elo, float(spacing))
        unit_nodes = (
            np.zeros_like(elo_nodes)
            if average_range < 1e-12
            else (elo_nodes - average_min) / average_range
        )
        piecewise[spacing] = (
            _piecewise_linear_basis(average_unit, unit_nodes),
            elo_nodes,
        )
    for spacing in PIECEWISE_CONSTANT_SPACINGS:
        elo_nodes = _fixed_elo_nodes(covariates.average_elo, float(spacing))
        unit_nodes = (
            np.zeros_like(elo_nodes)
            if average_range < 1e-12
            else (elo_nodes - average_min) / average_range
        )
        piecewise_constant[spacing] = (
            _piecewise_constant_basis(average_unit, unit_nodes),
            elo_nodes,
        )

    def fixed(name: str) -> Parameter:
        return Parameter(name, "fixed_color", FIXED_COLOR_PRIOR_SD)

    def spline_parameters(label: str, columns: int, start: int = 0) -> tuple[Parameter, ...]:
        return tuple(
            fixed(f"color:{label}_spline_b{index}")
            for index in range(start, start + columns)
        )

    models: list[tuple[str, str, np.ndarray, tuple[Parameter, ...]]] = []
    models.append(
        (
            "no_color",
            "Bradley-Terry ratings with no color term",
            base_design,
            base_parameters,
        )
    )
    models.append(
        (
            "global_color",
            "one global Black advantage",
            np.column_stack((base_design, ones)),
            (*base_parameters, fixed("color:global")),
        )
    )
    average_features = np.column_stack(
        (ones, average_z, _orthogonal_quadratic(average_z))
    )
    average_parameters = (
        fixed("color:average_intercept"),
        fixed("color:average_linear"),
        fixed("color:average_quadratic"),
    )
    models.append(
        (
            "average_elo_quadratic",
            "quadratic Black advantage as a function of average baseline Elo",
            np.column_stack((base_design, average_features)),
            (*base_parameters, *average_parameters),
        )
    )

    average_spline_parameters = spline_parameters(
        "average", average_spline.shape[1]
    )
    models.append(
        (
            "average_elo_cubic_spline",
            (
                "cubic B-spline Black advantage over average baseline Elo "
                "with four weighted-quantile interior knots"
            ),
            np.column_stack((base_design, average_spline)),
            (*base_parameters, *average_spline_parameters),
        )
    )
    for spacing, (basis, elo_nodes) in piecewise.items():
        parameters = tuple(
            fixed(f"color:average_piecewise_{spacing}_at_elo_{elo:g}")
            for elo in elo_nodes
        )
        models.append(
            (
                f"average_elo_piecewise_linear_{spacing}",
                (
                    f"continuous piecewise-linear Black advantage with nominal "
                    f"{spacing}-Elo segments; a short tail is merged into the last segment"
                ),
                np.column_stack((base_design, basis)),
                (*base_parameters, *parameters),
            )
        )
    for spacing, (step_basis, elo_nodes) in piecewise_constant.items():
        step_parameters = tuple(
            fixed(
                f"color:average_constant_{spacing}_elo_"
                f"{elo_nodes[index]:g}_to_{elo_nodes[index + 1]:g}"
            )
            for index in range(len(elo_nodes) - 1)
        )
        models.append(
            (
                f"average_elo_piecewise_constant_{spacing}",
                (
                    f"discontinuous piecewise-constant Black advantage in nominal "
                    f"{spacing}-Elo bins; a short tail is merged into the last bin"
                ),
                np.column_stack((base_design, step_basis)),
                (*base_parameters, *step_parameters),
            )
        )
    return models


def _initial_from_baseline(
    parameters: Sequence[Parameter], baseline: ModelResult
) -> np.ndarray:
    initial = np.zeros(len(parameters), dtype=float)
    baseline_values = {
        parameter.name: baseline.coefficients[index]
        for index, parameter in enumerate(baseline.parameters)
    }
    for index, parameter in enumerate(parameters):
        if parameter.name in baseline_values:
            initial[index] = baseline_values[parameter.name]
    return initial


def _estimate_and_se(result: ModelResult, contrast: np.ndarray) -> tuple[float, float]:
    estimate = float(np.dot(contrast, result.coefficients))
    variance = float(contrast @ result.covariance @ contrast)
    return estimate, math.sqrt(max(variance, 0.0))


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _rating_contrast(result: ModelResult, player: str, anchor: str) -> np.ndarray:
    contrast = np.zeros(len(result.parameters))
    if player != anchor:
        contrast[result.parameter_positions[f"rating:{player}"]] = 1.0
    return contrast


def _write_model_outputs(
    directory: Path,
    dataset: Dataset,
    anchor: str,
    result: ModelResult,
    covariates: Covariates,
) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    rating_rows: list[dict[str, object]] = []
    for player in dataset.players:
        estimate, standard_error = _estimate_and_se(
            result, _rating_contrast(result, player, anchor)
        )
        rating_rows.append(
            {
                "player": player,
                "elo": estimate,
                "standard_error": standard_error,
                "ci_95_lower": estimate - CONFIDENCE_Z * standard_error,
                "ci_95_upper": estimate + CONFIDENCE_Z * standard_error,
                "anchor": player == anchor,
            }
        )
    rating_rows.sort(key=lambda row: float(row["elo"]), reverse=True)
    _write_csv(
        directory / "ratings.csv",
        ("player", "elo", "standard_error", "ci_95_lower", "ci_95_upper", "anchor"),
        rating_rows,
    )

    parameter_rows: list[dict[str, object]] = []
    for index, parameter in enumerate(result.parameters):
        estimate = float(result.coefficients[index])
        standard_error = math.sqrt(max(float(result.covariance[index, index]), 0.0))
        parameter_rows.append(
            {
                "parameter": parameter.name,
                "kind": parameter.kind,
                "estimate_elo": estimate,
                "standard_error": standard_error,
                "ci_95_lower": estimate - CONFIDENCE_Z * standard_error,
                "ci_95_upper": estimate + CONFIDENCE_Z * standard_error,
                "prior_sd": parameter.prior_sd,
            }
        )
    _write_csv(
        directory / "parameters.csv",
        (
            "parameter",
            "kind",
            "estimate_elo",
            "standard_error",
            "ci_95_lower",
            "ci_95_upper",
            "prior_sd",
        ),
        parameter_rows,
    )

    matchup_rows: list[dict[str, object]] = []
    rating_columns = np.asarray(
        [parameter.kind == "rating" for parameter in result.parameters], dtype=bool
    )
    for row, group in enumerate(dataset.groups):
        contrast = result.design[row].copy()
        contrast[rating_columns] = 0.0
        estimate, standard_error = _estimate_and_se(result, contrast)
        matchup_rows.append(
            {
                "black": group.black,
                "white": group.white,
                "source": group.source,
                "games": group.games,
                "baseline_average_elo": covariates.average_elo[row],
                "baseline_elo_gap": covariates.gap_elo[row],
                "black_advantage_elo": estimate,
                "standard_error": standard_error,
                "ci_95_lower": estimate - CONFIDENCE_Z * standard_error,
                "ci_95_upper": estimate + CONFIDENCE_Z * standard_error,
            }
        )
    _write_csv(
        directory / "matchup_color_advantage.csv",
        (
            "black",
            "white",
            "source",
            "games",
            "baseline_average_elo",
            "baseline_elo_gap",
            "black_advantage_elo",
            "standard_error",
            "ci_95_lower",
            "ci_95_upper",
        ),
        matchup_rows,
    )

    if any(parameter.kind == "player_color" for parameter in result.parameters):
        color_rating_rows: list[dict[str, object]] = []
        for player in dataset.players:
            rating = _rating_contrast(result, player, anchor)
            effect = np.zeros(len(result.parameters))
            effect[result.parameter_positions[f"player_color:{player}"]] = 1.0
            effect_estimate, effect_se = _estimate_and_se(result, effect)
            black_estimate, black_se = _estimate_and_se(result, rating + effect)
            white_estimate, white_se = _estimate_and_se(result, rating - effect)
            color_rating_rows.append(
                {
                    "player": player,
                    "u_elo": effect_estimate,
                    "u_standard_error": effect_se,
                    "u_ci_95_lower": effect_estimate - CONFIDENCE_Z * effect_se,
                    "u_ci_95_upper": effect_estimate + CONFIDENCE_Z * effect_se,
                    "black_performance_elo": black_estimate,
                    "black_ci_95_lower": black_estimate - CONFIDENCE_Z * black_se,
                    "black_ci_95_upper": black_estimate + CONFIDENCE_Z * black_se,
                    "white_performance_elo": white_estimate,
                    "white_ci_95_lower": white_estimate - CONFIDENCE_Z * white_se,
                    "white_ci_95_upper": white_estimate + CONFIDENCE_Z * white_se,
                }
            )
        _write_csv(
            directory / "player_color_ratings.csv",
            (
                "player",
                "u_elo",
                "u_standard_error",
                "u_ci_95_lower",
                "u_ci_95_upper",
                "black_performance_elo",
                "black_ci_95_lower",
                "black_ci_95_upper",
                "white_performance_elo",
                "white_ci_95_lower",
                "white_ci_95_upper",
            ),
            color_rating_rows,
        )


def _write_text_report(
    path: Path,
    dataset: Dataset,
    anchor: str,
    results: Sequence[ModelResult],
) -> None:
    """Write every model's fit summary, color terms, ratings, and CIs."""
    name_width = max(len(player) for player in dataset.players)
    lines = [
        "Bradley-Terry color-advantage model results",
        "=" * 47,
        f"Input: {dataset.path}",
        f"Games in this snapshot: {dataset.games:,}",
        f"Players: {len(dataset.players)}",
        f"Distinct network checkpoints: {_network_checkpoint_count(dataset.players)}",
        f"Anchor: {anchor} = 0 Elo",
        "Draws: score_black=0.5 is half a win for each player",
        "95% uncertainty: +/- half-width from joint penalized Fisher/Laplace covariance",
        "Nonlinear strength covariates: frozen from the no-color fit",
        "Spline and piecewise-linear average Elo input: min-max scaled to [0, 1]",
        "Negative exponential: -a*exp(-b*x), with a in Elo and b unitless",
        "Rating parameters exclude the fixed anchor; total p includes all color/random effects",
        "",
        "Model comparison (lower log loss/AIC/BIC is better)",
        "-" * 53,
        (
            f"{'Model':<39} {'Rating p':>8} {'Color p':>8} {'Total p':>8} "
            f"{'Log loss':>10} {'Eff. p':>9} {'AIC':>13} {'BIC':>13}"
        ),
    ]
    ordered = sorted(
        results,
        key=lambda result: (
            -2.0 * result.log_likelihood + 2.0 * result.effective_parameters
        ),
    )
    for result in ordered:
        rating_parameters = sum(
            parameter.kind == "rating" for parameter in result.parameters
        )
        color_parameters = len(result.parameters) - rating_parameters
        aic = -2.0 * result.log_likelihood + 2.0 * result.effective_parameters
        bic = -2.0 * result.log_likelihood + (
            math.log(dataset.games) * result.effective_parameters
        )
        lines.append(
            f"{result.name:<39} "
            f"{rating_parameters:>8} {color_parameters:>8} "
            f"{len(result.parameters):>8} "
            f"{-result.log_likelihood / dataset.games:>10.6f} "
            f"{result.effective_parameters:>9.2f} {aic:>13.2f} {bic:>13.2f}"
        )

    for result in results:
        lines.extend(
            (
                "",
                "=" * 100,
                result.name,
                result.description,
                (
                    f"Converged: {result.converged}; iterations: {result.iterations}; "
                    f"log likelihood: {result.log_likelihood:.6f}; "
                    f"mean log loss: {-result.log_likelihood / dataset.games:.8f}"
                ),
                "",
                "Color-model parameters (Elo except exponential b, which is unitless)",
                "-" * 35,
            )
        )
        color_indices = [
            index
            for index, parameter in enumerate(result.parameters)
            if parameter.kind not in {"rating", "player_color"}
        ]
        if color_indices:
            lines.append(
                f"{'Parameter':<48} {'Estimate':>10} {'SE':>9} {'95% +/-':>12}"
            )
            for index in color_indices:
                parameter = result.parameters[index]
                estimate = float(result.coefficients[index])
                standard_error = math.sqrt(
                    max(float(result.covariance[index, index]), 0.0)
                )
                half_width = CONFIDENCE_Z * standard_error
                lines.append(
                    f"{parameter.name:<48} {estimate:>10.2f} "
                    f"{standard_error:>9.2f} +/- {half_width:>8.2f}"
                )
        else:
            lines.append("(none)")

        lines.extend(
            (
                "",
                "Player ratings",
                "-" * 14,
                f"{'Player':<{name_width}} {'Elo':>10} {'SE':>9} {'95% +/-':>12}",
            )
        )
        rating_values: list[tuple[float, float, str]] = []
        for player in dataset.players:
            estimate, standard_error = _estimate_and_se(
                result, _rating_contrast(result, player, anchor)
            )
            rating_values.append((estimate, standard_error, player))
        for estimate, standard_error, player in sorted(rating_values, reverse=True):
            half_width = CONFIDENCE_Z * standard_error
            lines.append(
                f"{player:<{name_width}} {estimate:>10.2f} {standard_error:>9.2f} "
                f"+/- {half_width:>8.2f}"
            )

        if any(parameter.kind == "player_color" for parameter in result.parameters):
            lines.extend(
                (
                    "",
                    "Shrunken player color effects",
                    "Players are sorted by descending fitted Elo.",
                    "-" * 42,
                    (
                        f"{'Player':<{name_width}} {'Elo':>9} {'Elo 95% +/-':>14} "
                        f"{'u':>9} {'u 95% +/-':>14}"
                    ),
                )
            )
            effect_rows: list[tuple[float, float, float, float, str]] = []
            for player in dataset.players:
                rating = _rating_contrast(result, player, anchor)
                effect = np.zeros(len(result.parameters))
                effect[result.parameter_positions[f"player_color:{player}"]] = 1.0
                rating_estimate, rating_se = _estimate_and_se(result, rating)
                effect_estimate, effect_se = _estimate_and_se(result, effect)
                effect_rows.append(
                    (rating_estimate, rating_se, effect_estimate, effect_se, player)
                )
            for (
                rating_estimate,
                rating_se,
                effect_estimate,
                effect_se,
                player,
            ) in sorted(effect_rows, reverse=True):
                lines.append(
                    f"{player:<{name_width}} {rating_estimate:>9.2f} "
                    f"+/- {CONFIDENCE_Z * rating_se:>8.2f} "
                    f"{effect_estimate:>9.2f} "
                    f"+/- {CONFIDENCE_Z * effect_se:>8.2f}"
                )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _analyse_dataset(dataset: Dataset) -> tuple[list[ModelResult], Covariates]:
    anchor = _anchor_for(dataset)
    successes, totals = _scores(dataset)
    base_design, base_parameters, rating_positions = _base_rating_design(dataset, anchor)
    baseline = _fit(
        "no_color",
        "Bradley-Terry ratings with no color term",
        base_design,
        base_parameters,
        successes,
        totals,
    )
    covariates = _make_covariates(dataset, baseline, rating_positions, totals, anchor)
    specifications = _model_inputs(
        dataset, base_design, base_parameters, covariates
    )
    results: list[ModelResult] = []
    for name, description, design, parameters in specifications:
        result = (
            baseline
            if name == "no_color"
            else _fit(
                name,
                description,
                design,
                parameters,
                successes,
                totals,
                _initial_from_baseline(parameters, baseline),
            )
        )
        results.append(result)

    average_min = float(np.min(covariates.average_elo))
    average_range = float(np.max(covariates.average_elo) - average_min)
    average_unit = (
        np.zeros_like(covariates.average_elo)
        if average_range < 1e-12
        else (covariates.average_elo - average_min) / average_range
    )
    results.append(
        _fit_negative_exponential(
            "average_elo_negative_exponential",
            "monotone average-strength color function -a*exp(-b*x), a>=0 and b>=0",
            base_design,
            base_parameters,
            average_unit,
            successes,
            totals,
            baseline,
        )
    )
    return results, covariates


def _rating_values(
    dataset: Dataset, result: ModelResult, anchor: str
) -> tuple[np.ndarray, np.ndarray]:
    black = np.zeros(len(dataset.groups), dtype=float)
    white = np.zeros(len(dataset.groups), dtype=float)
    for row, group in enumerate(dataset.groups):
        if group.black != anchor:
            black[row] = result.coefficients[
                result.parameter_positions[f"rating:{group.black}"]
            ]
        if group.white != anchor:
            white[row] = result.coefficients[
                result.parameter_positions[f"rating:{group.white}"]
            ]
    return black, white


def _heldout_predictor(
    test: Dataset,
    train: Dataset,
    train_covariates: Covariates,
    result: ModelResult,
    baseline: ModelResult,
    anchor: str,
) -> np.ndarray:
    black_rating, white_rating = _rating_values(test, result, anchor)
    baseline_black, baseline_white = _rating_values(test, baseline, anchor)
    average_elo = 0.5 * (baseline_black + baseline_white)
    color = np.zeros(len(test.groups), dtype=float)
    positions = result.parameter_positions

    if result.name == "no_color":
        pass
    elif result.name == "global_color":
        color.fill(result.coefficients[positions["color:global"]])
    elif result.name == "average_elo_quadratic":
        z = (
            average_elo - train_covariates.average_center
        ) / train_covariates.average_scale
        color = (
            result.coefficients[positions["color:average_intercept"]]
            + result.coefficients[positions["color:average_linear"]] * z
            + result.coefficients[positions["color:average_quadratic"]]
            * _orthogonal_quadratic(z)
        )
    elif result.name == "average_elo_cubic_spline":
        lower = float(np.min(train_covariates.average_elo))
        value_range = float(np.max(train_covariates.average_elo) - lower)
        train_unit = (
            np.zeros_like(train_covariates.average_elo)
            if value_range < 1e-12
            else (train_covariates.average_elo - lower) / value_range
        )
        test_unit = (
            np.zeros_like(average_elo)
            if value_range < 1e-12
            else np.clip((average_elo - lower) / value_range, 0.0, 1.0)
        )
        train_weights = np.asarray(
            [group.games for group in train.groups], dtype=float
        )
        basis = _cubic_bspline_basis_from_knots(
            test_unit, _cubic_bspline_knots(train_unit, train_weights)
        )
        coefficients = np.asarray(
            [
                result.coefficients[positions[f"color:average_spline_b{index}"]]
                for index in range(basis.shape[1])
            ]
        )
        color = basis @ coefficients
    elif linear_match := re.fullmatch(
        r"average_elo_piecewise_linear_(250|500|1500)", result.name
    ):
        spacing = int(linear_match.group(1))
        nodes = _fixed_elo_nodes(
            train_covariates.average_elo, float(spacing)
        )
        basis = _piecewise_linear_basis(average_elo, nodes)
        coefficients = np.asarray(
            [
                result.coefficients[
                    positions[
                        f"color:average_piecewise_{spacing}_at_elo_{node:g}"
                    ]
                ]
                for node in nodes
            ]
        )
        color = basis @ coefficients
    elif constant_match := re.fullmatch(
        r"average_elo_piecewise_constant_(250|500)", result.name
    ):
        spacing = int(constant_match.group(1))
        nodes = _fixed_elo_nodes(
            train_covariates.average_elo, float(spacing)
        )
        basis = _piecewise_constant_basis(average_elo, nodes)
        coefficients = np.asarray(
            [
                result.coefficients[
                    positions[
                        f"color:average_constant_{spacing}_elo_"
                        f"{nodes[index]:g}_to_{nodes[index + 1]:g}"
                    ]
                ]
                for index in range(len(nodes) - 1)
            ]
        )
        color = basis @ coefficients
    elif result.name == "average_elo_negative_exponential":
        lower = float(np.min(train_covariates.average_elo))
        value_range = float(np.max(train_covariates.average_elo) - lower)
        unit = (
            np.zeros_like(average_elo)
            if value_range < 1e-12
            else (average_elo - lower) / value_range
        )
        a = result.coefficients[positions["color:negative_exp_a_elo"]]
        b = result.coefficients[positions["color:negative_exp_b_per_unit"]]
        color = -a * np.exp(-b * unit)
    else:
        raise ModelError(f"no held-out predictor for model: {result.name}")
    return black_rating - white_rating + color


def _heldout_log_likelihood(
    test: Dataset,
    train: Dataset,
    train_covariates: Covariates,
    result: ModelResult,
    baseline: ModelResult,
    anchor: str,
) -> float:
    predictor = _heldout_predictor(
        test, train, train_covariates, result, baseline, anchor
    )
    successes, totals = _scores(test)
    logits = ELO_TO_LOGIT * predictor
    return float(
        np.sum(successes * logits - totals * np.logaddexp(0.0, logits))
    )


def _cross_validate(
    observations: Sequence[GameObservation],
    *,
    folds: int,
    seed: int,
    label: Path,
) -> tuple[list[CrossValidationSummary], list[dict[str, object]], int]:
    if folds < 2:
        raise ValueError("cross-validation requires at least two folds")
    pairs: dict[tuple[str, int, int], list[GameObservation]] = {}
    players: set[str] = set()
    sources: set[str] = set()
    for game in observations:
        pairs.setdefault(game.pair_key, []).append(game)
        players.update((game.black, game.white))
        sources.add(game.source)

    pairs_by_run: dict[str, list[tuple[str, int, int]]] = {}
    for key in pairs:
        pairs_by_run.setdefault(key[0], []).append(key)
    rng = random.Random(seed)
    pair_fold: dict[tuple[str, int, int], int] = {}
    for run in sorted(pairs_by_run):
        keys = sorted(pairs_by_run[run])
        rng.shuffle(keys)
        for index, key in enumerate(keys):
            pair_fold[key] = index % folds

    ordered_players = tuple(sorted(players))
    ordered_sources = tuple(sorted(sources))
    fold_rows: list[dict[str, object]] = []
    losses: dict[str, list[float]] = {}
    log_likelihoods: dict[str, float] = {}
    test_game_totals: dict[str, int] = {}
    for fold in range(folds):
        train_games = [
            game for game in observations if pair_fold[game.pair_key] != fold
        ]
        test_games = [
            game for game in observations if pair_fold[game.pair_key] == fold
        ]
        train_dataset = _dataset_from_observations(
            train_games,
            label.with_name(f"{label.name}-fold-{fold + 1}-train"),
            players=ordered_players,
            sources=ordered_sources,
        )
        test_dataset = _dataset_from_observations(
            test_games,
            label.with_name(f"{label.name}-fold-{fold + 1}-test"),
            players=ordered_players,
            sources=ordered_sources,
        )
        print(
            f"Cross-validation fold {fold + 1}/{folds}: "
            f"{train_dataset.games:,} train, {test_dataset.games:,} test",
            flush=True,
        )
        results, covariates = _analyse_dataset(train_dataset)
        baseline = next(result for result in results if result.name == "no_color")
        anchor = _anchor_for(train_dataset)
        for result in results:
            log_likelihood = _heldout_log_likelihood(
                test_dataset,
                train_dataset,
                covariates,
                result,
                baseline,
                anchor,
            )
            log_loss = -log_likelihood / test_dataset.games
            losses.setdefault(result.name, []).append(log_loss)
            log_likelihoods[result.name] = (
                log_likelihoods.get(result.name, 0.0) + log_likelihood
            )
            test_game_totals[result.name] = (
                test_game_totals.get(result.name, 0) + test_dataset.games
            )
            fold_rows.append(
                {
                    "fold": fold + 1,
                    "model": result.name,
                    "train_games": train_dataset.games,
                    "test_games": test_dataset.games,
                    "test_log_likelihood": log_likelihood,
                    "test_log_loss": log_loss,
                }
            )

    pooled_losses = {
        model: -log_likelihoods[model] / test_game_totals[model]
        for model in losses
    }
    best_model = min(pooled_losses, key=pooled_losses.__getitem__)
    best_fold_losses = np.asarray(losses[best_model], dtype=float)
    summaries: list[CrossValidationSummary] = []
    for model, fold_losses in losses.items():
        values = np.asarray(fold_losses, dtype=float)
        paired_deltas = values - best_fold_losses
        summaries.append(
            CrossValidationSummary(
                model=model,
                test_games=test_game_totals[model],
                log_loss=pooled_losses[model],
                fold_standard_error=float(
                    np.std(values, ddof=1) / math.sqrt(len(values))
                ),
                paired_delta_standard_error=float(
                    np.std(paired_deltas, ddof=1) / math.sqrt(len(paired_deltas))
                ),
                fold_log_losses=tuple(map(float, values)),
            )
        )
    summaries.sort(key=lambda summary: summary.log_loss)
    return summaries, fold_rows, len(pairs)


def _write_cross_validation_outputs(
    directory: Path,
    summaries: Sequence[CrossValidationSummary],
    fold_rows: Sequence[dict[str, object]],
    *,
    folds: int,
    seed: int,
    pairs: int,
) -> tuple[Path, Path, Path]:
    summary_path = directory / "cross_validation.csv"
    best = min(summary.log_loss for summary in summaries)
    _write_csv(
        summary_path,
        (
            "model",
            "test_games",
            "cv_log_loss",
            "fold_standard_error",
            "delta_from_best",
            "paired_delta_standard_error",
            *(f"fold_{index + 1}_log_loss" for index in range(folds)),
        ),
        (
            {
                "model": summary.model,
                "test_games": summary.test_games,
                "cv_log_loss": summary.log_loss,
                "fold_standard_error": summary.fold_standard_error,
                "delta_from_best": summary.log_loss - best,
                "paired_delta_standard_error": (
                    summary.paired_delta_standard_error
                ),
                **{
                    f"fold_{index + 1}_log_loss": value
                    for index, value in enumerate(summary.fold_log_losses)
                },
            }
            for summary in summaries
        ),
    )
    folds_path = directory / "cross_validation_folds.csv"
    _write_csv(
        folds_path,
        (
            "fold",
            "model",
            "train_games",
            "test_games",
            "test_log_likelihood",
            "test_log_loss",
        ),
        fold_rows,
    )
    report_path = directory / "cross_validation.txt"
    lines = [
        "Grouped cross-validation of Black-advantage models",
        "=" * 52,
        f"Folds: {folds}",
        f"Seed: {seed}",
        f"Color-swapped game pairs: {pairs:,}",
        "Grouping: both colors of every scheduled pair remain in the same fold",
        "Baseline ratings and all feature transformations are refit on training games only",
        "Selection metric: pooled held-out mean log loss (lower is better)",
        "Fold SE: standard error of the fold-level mean log losses",
        "Paired SE: standard error of within-fold loss differences from the best model",
        "",
        (
            f"{'Model':<39} {'CV log loss':>12} {'Fold SE':>12} "
            f"{'Delta':>12} {'Paired SE':>12}"
        ),
    ]
    for summary in summaries:
        lines.append(
            f"{summary.model:<39} {summary.log_loss:>12.8f} "
            f"{summary.fold_standard_error:>12.8f} "
            f"{summary.log_loss - best:>12.8f} "
            f"{summary.paired_delta_standard_error:>12.8f}"
        )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary_path, folds_path, report_path


def _curve_grid(
    dataset: Dataset, result: ModelResult, covariates: Covariates
) -> np.ndarray:
    """Return a dense plotting grid, preserving discontinuous step boundaries."""
    lower = float(np.min(covariates.average_elo))
    upper = float(np.max(covariates.average_elo))
    grid = list(np.linspace(lower, upper, 401))
    constant_match = re.fullmatch(
        r"average_elo_piecewise_constant_(250|500)", result.name
    )
    if constant_match:
        nodes = _fixed_elo_nodes(
            covariates.average_elo, float(constant_match.group(1))
        )
        for boundary in nodes[1:-1]:
            grid.extend((float(np.nextafter(boundary, -math.inf)), float(boundary)))
    return np.asarray(sorted(set(grid)), dtype=float)


def _color_curve(
    dataset: Dataset,
    result: ModelResult,
    covariates: Covariates,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Evaluate a fitted color function and its pointwise joint-covariance CI."""
    x = _curve_grid(dataset, result, covariates)
    contrast = np.zeros((len(x), len(result.parameters)), dtype=float)
    nonlinear_estimate: np.ndarray | None = None
    positions = result.parameter_positions
    lower = float(np.min(covariates.average_elo))
    value_range = float(np.max(covariates.average_elo) - lower)
    x_unit = np.zeros_like(x) if value_range < 1e-12 else (x - lower) / value_range

    if result.name == "no_color":
        pass
    elif result.name == "global_color":
        contrast[:, positions["color:global"]] = 1.0
    elif result.name == "average_elo_quadratic":
        z = (x - covariates.average_center) / covariates.average_scale
        contrast[:, positions["color:average_intercept"]] = 1.0
        contrast[:, positions["color:average_linear"]] = z
        contrast[:, positions["color:average_quadratic"]] = _orthogonal_quadratic(z)
    elif result.name == "average_elo_cubic_spline":
        fitted_unit = (
            np.zeros_like(covariates.average_elo)
            if value_range < 1e-12
            else (covariates.average_elo - lower) / value_range
        )
        weights = np.asarray([group.games for group in dataset.groups], dtype=float)
        knots = _cubic_bspline_knots(fitted_unit, weights)
        basis = _cubic_bspline_basis_from_knots(x_unit, knots)
        for index in range(basis.shape[1]):
            contrast[:, positions[f"color:average_spline_b{index}"]] = basis[:, index]
    elif linear_match := re.fullmatch(
        r"average_elo_piecewise_linear_(250|500|1500)", result.name
    ):
        spacing = int(linear_match.group(1))
        nodes = _fixed_elo_nodes(covariates.average_elo, float(spacing))
        basis = _piecewise_linear_basis(x, nodes)
        for index, node in enumerate(nodes):
            name = f"color:average_piecewise_{spacing}_at_elo_{node:g}"
            contrast[:, positions[name]] = basis[:, index]
    elif constant_match := re.fullmatch(
        r"average_elo_piecewise_constant_(250|500)", result.name
    ):
        spacing = int(constant_match.group(1))
        nodes = _fixed_elo_nodes(covariates.average_elo, float(spacing))
        basis = _piecewise_constant_basis(x, nodes)
        for index in range(len(nodes) - 1):
            name = (
                f"color:average_constant_{spacing}_elo_"
                f"{nodes[index]:g}_to_{nodes[index + 1]:g}"
            )
            contrast[:, positions[name]] = basis[:, index]
    elif result.name == "average_elo_negative_exponential":
        a_position = positions["color:negative_exp_a_elo"]
        b_position = positions["color:negative_exp_b_per_unit"]
        a = float(result.coefficients[a_position])
        b = float(result.coefficients[b_position])
        exponential = np.exp(-b * x_unit)
        contrast[:, a_position] = -exponential
        contrast[:, b_position] = a * x_unit * exponential
        nonlinear_estimate = -a * exponential
    else:  # Keep plotting failures explicit when a new model is added.
        raise ModelError(f"no plot evaluator for model: {result.name}")

    estimate = (
        contrast @ result.coefficients
        if nonlinear_estimate is None
        else nonlinear_estimate
    )
    variance = np.einsum("ij,jk,ik->i", contrast, result.covariance, contrast)
    half_width = CONFIDENCE_Z * np.sqrt(np.maximum(variance, 0.0))
    return x, estimate, estimate - half_width, estimate + half_width


def _plot_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{filename}", size)
    except OSError:
        return ImageFont.load_default()


def _draw_dashed_horizontal(
    draw: ImageDraw.ImageDraw, left: int, right: int, y: int
) -> None:
    for start in range(left, right, 18):
        draw.line((start, y, min(start + 9, right), y), fill="#8b97a8", width=2)


def _draw_vertical_text(
    image: Image.Image,
    center: tuple[int, int],
    value: str,
    font: ImageFont.ImageFont,
    fill: str,
) -> None:
    """Draw a centered, antialiased vertical axis label."""
    left, top, right, bottom = font.getbbox(value)
    label = Image.new("RGBA", (right - left + 8, bottom - top + 8), (0, 0, 0, 0))
    label_draw = ImageDraw.Draw(label)
    label_draw.text((4 - left, 4 - top), value, font=font, fill=fill)
    rotated = label.rotate(90, expand=True, resample=Image.Resampling.BICUBIC)
    image.paste(
        rotated,
        (center[0] - rotated.width // 2, center[1] - rotated.height // 2),
        rotated,
    )


def _write_all_models_plot(
    path: Path,
    analyses: Sequence[tuple[Dataset, Covariates, Sequence[ModelResult]]],
) -> None:
    """Write one PNG with models in rows and independently fitted datasets in columns."""
    if not analyses:
        return
    model_names = [result.name for result in analyses[0][2]]
    for _dataset, _covariates, results in analyses[1:]:
        if [result.name for result in results] != model_names:
            raise ModelError("datasets have different model lists; cannot make joint plot")

    curves: list[list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]] = []
    y_ranges: list[tuple[float, float]] = []
    for dataset, covariates, results in analyses:
        dataset_curves = [
            _color_curve(dataset, result, covariates) for result in results
        ]
        curves.append(dataset_curves)
        all_lower = np.concatenate([curve[2] for curve in dataset_curves])
        all_upper = np.concatenate([curve[3] for curve in dataset_curves])
        y_lower = min(float(np.min(all_lower)), 0.0)
        y_upper = max(float(np.max(all_upper)), 0.0)
        padding = max((y_upper - y_lower) * 0.06, 5.0)
        y_ranges.append((y_lower - padding, y_upper + padding))

    columns = len(analyses)
    panel_width = 1320
    panel_height = 430
    outer_x = 45
    top = 155
    gap_x = 30
    gap_y = 16
    width = outer_x * 2 + columns * panel_width + (columns - 1) * gap_x
    height = top + len(model_names) * (panel_height + gap_y) + 35
    image = Image.new("RGB", (width, height), "#f4f7fb")
    draw = ImageDraw.Draw(image)
    title_font = _plot_font(36, bold=True)
    subtitle_font = _plot_font(20)
    panel_title_font = _plot_font(22, bold=True)
    label_font = _plot_font(17)
    tick_font = _plot_font(15)
    column_font = _plot_font(24, bold=True)

    draw.text(
        (width / 2, 22),
        "Bradley–Terry Black-advantage functions — all standalone models",
        fill="#182334",
        font=title_font,
        anchor="ma",
    )
    draw.text(
        (width / 2, 70),
        "Rows are models; columns are independently fitted datasets; shaded bands are pointwise 95% CIs",
        fill="#526073",
        font=subtitle_font,
        anchor="ma",
    )
    for column, (dataset, _covariates, _results) in enumerate(analyses):
        panel_left = outer_x + column * (panel_width + gap_x)
        arena_name = dataset.path.parent.name
        date_match = re.search(r"arena_(\d{4})(\d{2})(\d{2})", arena_name)
        date_label = (
            "-".join(date_match.groups()) if date_match else arena_name
        )
        draw.text(
            (panel_left + panel_width / 2, 112),
            f"{date_label} · {len(dataset.players)} players · {dataset.games:,} games",
            fill="#233247",
            font=column_font,
            anchor="mm",
        )

    display_names = {
        "no_color": "No color advantage",
        "global_color": "Global color advantage",
        "average_elo_quadratic": "Average-Elo quadratic",
        "average_elo_cubic_spline": "Average-Elo cubic spline",
        "average_elo_piecewise_linear_250": "Continuous piecewise linear · 250 Elo",
        "average_elo_piecewise_constant_250": "Piecewise constant · 250 Elo",
        "average_elo_piecewise_linear_500": "Continuous piecewise linear · 500 Elo",
        "average_elo_piecewise_linear_1500": "Continuous piecewise linear · 1500 Elo",
        "average_elo_piecewise_constant_500": "Piecewise constant · 500 Elo",
        "average_elo_negative_exponential": "Negative exponential",
    }
    for row, model_name in enumerate(model_names):
        for column, (dataset, covariates, _results) in enumerate(analyses):
            panel_left = outer_x + column * (panel_width + gap_x)
            panel_top = top + row * (panel_height + gap_y)
            panel_right = panel_left + panel_width
            panel_bottom = panel_top + panel_height
            draw.rounded_rectangle(
                (panel_left, panel_top, panel_right, panel_bottom),
                radius=16,
                fill="white",
                outline="#cbd5e1",
                width=2,
            )
            draw.text(
                (panel_left + 24, panel_top + 14),
                display_names.get(model_name, model_name),
                fill="#1d2939",
                font=panel_title_font,
            )
            plot_left = panel_left + 105
            plot_right = panel_right - 30
            plot_top = panel_top + 58
            plot_bottom = panel_bottom - 65
            x, estimate, ci_lower, ci_upper = curves[column][row]
            x_min = float(np.min(covariates.average_elo))
            x_max = float(np.max(covariates.average_elo))
            y_min, y_max = y_ranges[column]

            def px(value: float) -> float:
                return plot_left + (value - x_min) / (x_max - x_min) * (plot_right - plot_left)

            def py(value: float) -> float:
                return plot_bottom - (value - y_min) / (y_max - y_min) * (plot_bottom - plot_top)

            for tick_index in range(5):
                value = y_min + tick_index * (y_max - y_min) / 4.0
                y_pixel = py(value)
                draw.line(
                    (plot_left, y_pixel, plot_right, y_pixel),
                    fill="#e5eaf0",
                    width=1,
                )
                draw.text(
                    (plot_left - 10, y_pixel),
                    f"{value:.0f}",
                    fill="#58677a",
                    font=tick_font,
                    anchor="rm",
                )
            for tick_index in range(5):
                value = x_min + tick_index * (x_max - x_min) / 4.0
                x_pixel = px(value)
                draw.line(
                    (x_pixel, plot_top, x_pixel, plot_bottom),
                    fill="#eef1f5",
                    width=1,
                )
                draw.text(
                    (x_pixel, plot_bottom + 11),
                    f"{value:.0f}",
                    fill="#58677a",
                    font=tick_font,
                    anchor="ma",
                )
            if y_min <= 0.0 <= y_max:
                _draw_dashed_horizontal(draw, plot_left, plot_right, round(py(0.0)))

            upper_points = [(px(float(xv)), py(float(yv))) for xv, yv in zip(x, ci_upper)]
            lower_points = [
                (px(float(xv)), py(float(yv)))
                for xv, yv in zip(x[::-1], ci_lower[::-1])
            ]
            draw.polygon(upper_points + lower_points, fill="#d5e7fb")
            line_points = [(px(float(xv)), py(float(yv))) for xv, yv in zip(x, estimate)]
            draw.line(line_points, fill="#1769aa", width=4, joint="curve")
            draw.line(
                (plot_left, plot_top, plot_left, plot_bottom), fill="#29384a", width=2
            )
            draw.line(
                (plot_left, plot_bottom, plot_right, plot_bottom), fill="#29384a", width=2
            )
            draw.text(
                ((plot_left + plot_right) / 2, panel_bottom - 17),
                "Average baseline Elo",
                fill="#405066",
                font=label_font,
                anchor="mm",
            )
            _draw_vertical_text(
                image,
                (panel_left + 18, round((plot_top + plot_bottom) / 2)),
                "Black advantage (Elo)",
                label_font,
                "#405066",
            )

    image.save(path, format="PNG", optimize=True)


def _default_log_dir() -> Path:
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    return ROOT / "data/color_advantage" / f"color_advantage_{timestamp}"


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs",
        metavar="RESULTS_CSV",
        nargs="*",
        type=Path,
        help="result files (defaults to the current three 100k-game calibration logs)",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="new output directory (default: timestamped data/color_advantage directory)",
    )
    parser.add_argument(
        "--combine",
        action="store_true",
        help="combine all input result files into one dataset",
    )
    parser.add_argument(
        "--cross-validate",
        action="store_true",
        help="run grouped cross-validation (requires --combine)",
    )
    parser.add_argument(
        "--cv-folds",
        type=int,
        default=DEFAULT_CV_FOLDS,
        help=f"number of cross-validation folds (default: {DEFAULT_CV_FOLDS})",
    )
    parser.add_argument(
        "--cv-seed",
        type=int,
        default=DEFAULT_CV_SEED,
        help=f"cross-validation shuffle seed (default: {DEFAULT_CV_SEED})",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    inputs = tuple(args.inputs) if args.inputs else DEFAULT_INPUTS
    if args.cross_validate and not args.combine:
        raise ModelError("--cross-validate requires --combine")
    if args.cv_folds < 2:
        raise ModelError("--cv-folds must be at least 2")
    log_dir = (args.log_dir or _default_log_dir()).resolve()
    if log_dir.exists():
        raise ModelError(f"log directory already exists; choose a new path: {log_dir}")
    log_dir.mkdir(parents=True)

    used_names: set[str] = set()
    manifest: list[dict[str, object]] = []
    analyses: list[tuple[Dataset, Covariates, Sequence[ModelResult]]] = []
    if args.combine:
        observations = _read_paired_observations(inputs)
        players = tuple(
            sorted(
                {
                    player
                    for game in observations
                    for player in (game.black, game.white)
                }
            )
        )
        sources = tuple(sorted({game.source for game in observations}))
        combined_label = ROOT / "log/current_bot_pool/results.csv"
        datasets = (
            _dataset_from_observations(
                observations,
                combined_label,
                players=players,
                sources=sources,
            ),
        )
    else:
        observations = ()
        datasets = tuple(_read_dataset(path.resolve()) for path in inputs)

    for dataset in datasets:
        input_path = dataset.path
        base_name = _safe_slug(input_path.parent.name or input_path.stem)
        name = base_name
        suffix = 2
        while name in used_names:
            name = f"{base_name}_{suffix}"
            suffix += 1
        used_names.add(name)
        print(f"Fitting {dataset.games:,} games from {dataset.path}", flush=True)
        results, covariates = _analyse_dataset(dataset)
        analyses.append((dataset, covariates, results))
        report_path = log_dir / f"{name}.txt"
        _write_text_report(report_path, dataset, _anchor_for(dataset), results)
        entry: dict[str, object] = {
            "dataset": name,
            "inputs": [str(path.resolve()) for path in inputs]
            if args.combine
            else [str(dataset.path)],
            "games": dataset.games,
            "players": len(dataset.players),
            "network_checkpoints": _network_checkpoint_count(dataset.players),
            "models": [result.name for result in results],
            "text_report": report_path.name,
        }
        if args.cross_validate:
            summaries, fold_rows, pair_count = _cross_validate(
                observations,
                folds=args.cv_folds,
                seed=args.cv_seed,
                label=combined_label,
            )
            summary_path, folds_path, cv_report_path = (
                _write_cross_validation_outputs(
                    log_dir,
                    summaries,
                    fold_rows,
                    folds=args.cv_folds,
                    seed=args.cv_seed,
                    pairs=pair_count,
                )
            )
            entry["cross_validation"] = {
                "folds": args.cv_folds,
                "seed": args.cv_seed,
                "pairs": pair_count,
                "summary_csv": summary_path.name,
                "folds_csv": folds_path.name,
                "text_report": cv_report_path.name,
            }
        manifest.append(entry)

    plot_path = log_dir / "all_models.png"
    _write_all_models_plot(plot_path, analyses)
    (log_dir / "manifest.json").write_text(
        json.dumps(
            {
                "combined": args.combine,
                "datasets": manifest,
                "all_models_plot": plot_path.name,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote color-advantage analysis to {log_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ModelError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
