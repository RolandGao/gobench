#!/usr/bin/env python3
"""Evaluate every paper color model on random half-player splits.

The common no-color player ratings are estimated once from the complete
imported game pool and frozen.  Each repeat fits only the color function on
games between a random half of the players and scores the exact complement.
No games are launched or generated.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from analysis import color_advantage_model as base


@dataclass(frozen=True)
class HatCoordinates:
    left: np.ndarray
    right: np.ndarray
    left_weight: np.ndarray
    right_weight: np.ndarray


@dataclass(frozen=True)
class SparseDesign:
    rating_count: int
    color_count: int
    black_rating: np.ndarray
    white_rating: np.ndarray
    color: HatCoordinates

    @property
    def parameter_count(self) -> int:
        return self.rating_count + self.color_count

    def product(self, coefficients: np.ndarray) -> np.ndarray:
        values = np.zeros(len(self.black_rating), dtype=float)
        black_mask = self.black_rating >= 0
        white_mask = self.white_rating >= 0
        values[black_mask] += coefficients[self.black_rating[black_mask]]
        values[white_mask] -= coefficients[self.white_rating[white_mask]]
        color_coefficients = coefficients[self.rating_count :]
        values += self.color.left_weight * color_coefficients[self.color.left]
        values += self.color.right_weight * color_coefficients[self.color.right]
        return values

    def transpose_product(self, values: np.ndarray) -> np.ndarray:
        result = np.zeros(self.parameter_count, dtype=float)
        black_mask = self.black_rating >= 0
        white_mask = self.white_rating >= 0
        result[: self.rating_count] += np.bincount(
            self.black_rating[black_mask],
            weights=values[black_mask],
            minlength=self.rating_count,
        )
        result[: self.rating_count] -= np.bincount(
            self.white_rating[white_mask],
            weights=values[white_mask],
            minlength=self.rating_count,
        )
        color_result = np.bincount(
            self.color.left,
            weights=values * self.color.left_weight,
            minlength=self.color_count,
        )
        color_result += np.bincount(
            self.color.right,
            weights=values * self.color.right_weight,
            minlength=self.color_count,
        )
        result[self.rating_count :] = color_result
        return result

    def information_diagonal(
        self, weights: np.ndarray, precisions: np.ndarray
    ) -> np.ndarray:
        diagonal = precisions.copy()
        black_mask = self.black_rating >= 0
        white_mask = self.white_rating >= 0
        diagonal[: self.rating_count] += base.ELO_TO_LOGIT**2 * np.bincount(
            self.black_rating[black_mask],
            weights=weights[black_mask],
            minlength=self.rating_count,
        )
        diagonal[: self.rating_count] += base.ELO_TO_LOGIT**2 * np.bincount(
            self.white_rating[white_mask],
            weights=weights[white_mask],
            minlength=self.rating_count,
        )
        color_diagonal = np.bincount(
            self.color.left,
            weights=weights * self.color.left_weight**2,
            minlength=self.color_count,
        )
        color_diagonal += np.bincount(
            self.color.right,
            weights=weights * self.color.right_weight**2,
            minlength=self.color_count,
        )
        diagonal[self.rating_count :] += base.ELO_TO_LOGIT**2 * color_diagonal
        return diagonal


@dataclass(frozen=True)
class SparseFit:
    coefficients: np.ndarray
    converged: bool
    newton_iterations: int
    cg_iterations: int


def _hat_coordinates(values: np.ndarray, nodes: np.ndarray) -> HatCoordinates:
    if len(nodes) == 1:
        zeros = np.zeros(len(values), dtype=int)
        return HatCoordinates(
            left=zeros,
            right=zeros.copy(),
            left_weight=np.ones(len(values)),
            right_weight=np.zeros(len(values)),
        )
    clipped = np.clip(values, nodes[0], nodes[-1])
    left = np.searchsorted(nodes, clipped, side="right") - 1
    left = np.clip(left, 0, len(nodes) - 2).astype(int)
    right = left + 1
    fraction = (clipped - nodes[left]) / (nodes[right] - nodes[left])
    return HatCoordinates(
        left=left,
        right=right,
        left_weight=1.0 - fraction,
        right_weight=fraction,
    )


def _sparse_design(
    dataset: base.Dataset,
    anchor: str,
    rating_positions: dict[str, int],
    average_elo: np.ndarray,
    nodes: np.ndarray,
) -> SparseDesign:
    return SparseDesign(
        rating_count=len(rating_positions),
        color_count=len(nodes),
        black_rating=np.asarray(
            [rating_positions.get(group.black, -1) for group in dataset.groups],
            dtype=int,
        ),
        white_rating=np.asarray(
            [rating_positions.get(group.white, -1) for group in dataset.groups],
            dtype=int,
        ),
        color=_hat_coordinates(average_elo, nodes),
    )


def _pcg(
    product: Callable[[np.ndarray], np.ndarray],
    right_hand_side: np.ndarray,
    diagonal: np.ndarray,
    *,
    tolerance: float = 1e-9,
    max_iterations: int = 10_000,
) -> tuple[np.ndarray, int, float]:
    solution = np.zeros_like(right_hand_side)
    residual = right_hand_side.copy()
    right_norm = float(np.linalg.norm(right_hand_side))
    if right_norm == 0.0:
        return solution, 0, 0.0
    preconditioned = residual / diagonal
    direction = preconditioned.copy()
    residual_dot = float(np.dot(residual, preconditioned))
    relative_residual = 1.0
    for iteration in range(1, max_iterations + 1):
        product_direction = product(direction)
        denominator = float(np.dot(direction, product_direction))
        if denominator <= 0.0 or not math.isfinite(denominator):
            raise base.ModelError("non-positive curvature in conjugate gradient")
        alpha = residual_dot / denominator
        solution += alpha * direction
        residual -= alpha * product_direction
        relative_residual = float(np.linalg.norm(residual)) / right_norm
        if relative_residual <= tolerance:
            return solution, iteration, relative_residual
        preconditioned = residual / diagonal
        next_residual_dot = float(np.dot(residual, preconditioned))
        direction = preconditioned + (next_residual_dot / residual_dot) * direction
        residual_dot = next_residual_dot
    return solution, max_iterations, relative_residual


def _fit_sparse(
    design: SparseDesign,
    successes: np.ndarray,
    totals: np.ndarray,
    baseline_ratings: np.ndarray,
    offset: np.ndarray | None = None,
) -> SparseFit:
    coefficients = np.zeros(design.parameter_count, dtype=float)
    coefficients[: design.rating_count] = baseline_ratings
    fixed_offset = (
        np.zeros(len(successes), dtype=float)
        if offset is None
        else np.asarray(offset, dtype=float)
    )
    if fixed_offset.shape != successes.shape:
        raise ValueError("offset and score arrays must have the same shape")
    precisions = np.full(
        design.parameter_count, 1.0 / base.RATING_PRIOR_SD**2, dtype=float
    )

    def objective(candidate: np.ndarray) -> float:
        logits = base.ELO_TO_LOGIT * (fixed_offset + design.product(candidate))
        likelihood = float(
            np.sum(successes * logits - totals * np.logaddexp(0.0, logits))
        )
        return likelihood - 0.5 * float(
            np.dot(precisions * candidate, candidate)
        )

    total_cg_iterations = 0
    converged = False
    for newton_iteration in range(1, 101):
        predictor = fixed_offset + design.product(coefficients)
        probabilities = base._sigmoid(base.ELO_TO_LOGIT * predictor)
        residuals = successes - totals * probabilities
        weights = totals * probabilities * (1.0 - probabilities)
        gradient = (
            base.ELO_TO_LOGIT * design.transpose_product(residuals)
            - precisions * coefficients
        )

        def information_product(vector: np.ndarray) -> np.ndarray:
            projected = design.product(vector)
            return (
                base.ELO_TO_LOGIT**2
                * design.transpose_product(weights * projected)
                + precisions * vector
            )

        change, cg_iterations, _relative_residual = _pcg(
            information_product,
            gradient,
            design.information_diagonal(weights, precisions),
        )
        total_cg_iterations += cg_iterations
        current = objective(coefficients)
        step = 1.0
        while step >= 2.0**-20:
            candidate = coefficients + step * change
            if objective(candidate) >= current - 1e-10:
                coefficients = candidate
                break
            step *= 0.5
        else:
            break
        if float(np.max(np.abs(step * change), initial=0.0)) < 1e-7:
            converged = True
            break
    return SparseFit(
        coefficients=coefficients,
        converged=converged,
        newton_iterations=newton_iteration,
        cg_iterations=total_cg_iterations,
    )


def _baseline_fit(
    dataset: base.Dataset,
) -> tuple[base.ModelResult, base.Covariates, dict[str, int], str]:
    anchor = base._anchor_for(dataset)
    successes, totals = base._scores(dataset)
    rating_design, rating_parameters, rating_positions = base._base_rating_design(
        dataset, anchor
    )
    baseline = base._fit(
        "no_color",
        "Bradley-Terry ratings with no color term",
        rating_design,
        rating_parameters,
        successes,
        totals,
    )
    covariates = base._make_covariates(
        dataset, baseline, rating_positions, totals, anchor
    )
    return baseline, covariates, rating_positions, anchor


def _rating_features(
    dataset: base.Dataset,
    baseline: base.ModelResult,
    anchor: str,
) -> tuple[np.ndarray, np.ndarray]:
    def rating(player: str) -> float:
        if player == anchor:
            return 0.0
        return float(
            baseline.coefficients[
                baseline.parameter_positions[f"rating:{player}"]
            ]
        )

    black = np.asarray([rating(group.black) for group in dataset.groups])
    white = np.asarray([rating(group.white) for group in dataset.groups])
    return black - white, 0.5 * (black + white)


@dataclass(frozen=True)
class ColorFit:
    coefficients: np.ndarray
    converged: bool


def _objective(
    features: np.ndarray,
    coefficients: np.ndarray,
    offset: np.ndarray,
    successes: np.ndarray,
    totals: np.ndarray,
    precisions: np.ndarray,
) -> float:
    logits = base.ELO_TO_LOGIT * (offset + features @ coefficients)
    likelihood = float(
        np.sum(successes * logits - totals * np.logaddexp(0.0, logits))
    )
    return likelihood - 0.5 * float(
        np.dot(precisions * coefficients, coefficients)
    )


def _fit_dense_color(
    features: np.ndarray,
    offset: np.ndarray,
    successes: np.ndarray,
    totals: np.ndarray,
) -> ColorFit:
    coefficients = np.zeros(features.shape[1], dtype=float)
    precisions = np.full(features.shape[1], 1.0 / base.FIXED_COLOR_PRIOR_SD**2)
    converged = features.shape[1] == 0
    if converged:
        return ColorFit(coefficients, True)
    for _iteration in range(1, 101):
        predictor = offset + features @ coefficients
        probabilities = base._sigmoid(base.ELO_TO_LOGIT * predictor)
        residuals = successes - totals * probabilities
        weights = totals * probabilities * (1.0 - probabilities)
        gradient = (
            base.ELO_TO_LOGIT * (features.T @ residuals)
            - precisions * coefficients
        )
        information = (
            base.ELO_TO_LOGIT**2
            * (features.T @ (weights[:, None] * features))
            + np.diag(precisions)
        )
        try:
            change = np.linalg.solve(information, gradient)
        except np.linalg.LinAlgError:
            change = np.linalg.lstsq(information, gradient, rcond=None)[0]
        current = _objective(
            features, coefficients, offset, successes, totals, precisions
        )
        step = 1.0
        while step >= 2.0**-20:
            candidate = coefficients + step * change
            if (
                _objective(
                    features,
                    candidate,
                    offset,
                    successes,
                    totals,
                    precisions,
                )
                >= current - 1e-10
            ):
                coefficients = candidate
                break
            step *= 0.5
        else:
            break
        if float(np.max(np.abs(step * change), initial=0.0)) < 1e-7:
            converged = True
            break
    return ColorFit(coefficients, converged)


def _fit_negative_exponential(
    average_unit: np.ndarray,
    offset: np.ndarray,
    successes: np.ndarray,
    totals: np.ndarray,
) -> ColorFit:
    precisions = np.asarray(
        [1.0 / base.FIXED_COLOR_PRIOR_SD**2, 1.0 / 10.0**2]
    )

    def predictor_and_jacobian(
        coefficients: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        amplitude, decay = coefficients
        exponential = np.exp(-decay * average_unit)
        predictor = offset - amplitude * exponential
        jacobian = np.column_stack(
            (-exponential, amplitude * average_unit * exponential)
        )
        return predictor, jacobian

    def objective(coefficients: np.ndarray) -> float:
        if np.any(coefficients < 0.0):
            return -math.inf
        predictor, _jacobian = predictor_and_jacobian(coefficients)
        logits = base.ELO_TO_LOGIT * predictor
        likelihood = float(
            np.sum(successes * logits - totals * np.logaddexp(0.0, logits))
        )
        return likelihood - 0.5 * float(
            np.dot(precisions * coefficients, coefficients)
        )

    best = np.asarray([1.0, 1.0])
    best_objective = objective(best)
    for decay in (0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0):
        feature = -np.exp(-decay * average_unit)[:, None]
        profiled = _fit_dense_color(feature, offset, successes, totals)
        amplitude = float(profiled.coefficients[0])
        if amplitude < 0.0:
            continue
        candidate = np.asarray([amplitude, decay])
        value = objective(candidate)
        if value > best_objective:
            best = candidate
            best_objective = value

    coefficients = best
    converged = False
    for _iteration in range(1, 201):
        predictor, jacobian = predictor_and_jacobian(coefficients)
        probabilities = base._sigmoid(base.ELO_TO_LOGIT * predictor)
        residuals = successes - totals * probabilities
        weights = totals * probabilities * (1.0 - probabilities)
        gradient = (
            base.ELO_TO_LOGIT * (jacobian.T @ residuals)
            - precisions * coefficients
        )
        information = (
            base.ELO_TO_LOGIT**2
            * (jacobian.T @ (weights[:, None] * jacobian))
            + np.diag(precisions)
        )
        change = np.linalg.solve(information, gradient)
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
        if float(np.max(np.abs(step * change), initial=0.0)) < 1e-7:
            converged = True
            break
    return ColorFit(coefficients, converged)


def _log_loss(
    predictor: np.ndarray,
    successes: np.ndarray,
    totals: np.ndarray,
    games: int,
) -> float:
    logits = base.ELO_TO_LOGIT * predictor
    log_likelihood = float(
        np.sum(successes * logits - totals * np.logaddexp(0.0, logits))
    )
    return -log_likelihood / games


def _linear_features(
    train_average: np.ndarray,
    test_average: np.ndarray,
    train_totals: np.ndarray,
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    center, scale = base._weighted_center_scale(train_average, train_totals)
    train_z = (train_average - center) / scale
    test_z = (test_average - center) / scale
    features: dict[str, tuple[np.ndarray, np.ndarray]] = {
        "global_color": (
            np.ones((len(train_average), 1)),
            np.ones((len(test_average), 1)),
        ),
        "quadratic": (
            np.column_stack(
                (np.ones(len(train_z)), train_z, base._orthogonal_quadratic(train_z))
            ),
            np.column_stack(
                (np.ones(len(test_z)), test_z, base._orthogonal_quadratic(test_z))
            ),
        ),
    }

    lower = float(np.min(train_average))
    value_range = float(np.max(train_average) - lower)
    train_unit = (
        np.zeros_like(train_average)
        if value_range < 1e-12
        else (train_average - lower) / value_range
    )
    test_unit = (
        np.zeros_like(test_average)
        if value_range < 1e-12
        else np.clip((test_average - lower) / value_range, 0.0, 1.0)
    )
    knots = base._cubic_bspline_knots(train_unit, train_totals)
    features["cubic_spline"] = (
        base._cubic_bspline_basis_from_knots(train_unit, knots),
        base._cubic_bspline_basis_from_knots(test_unit, knots),
    )
    for knot_spacing in (250, 500):
        nodes = base._fixed_elo_nodes(train_average, float(knot_spacing))
        features[f"piecewise_constant_{knot_spacing}"] = (
            base._piecewise_constant_basis(train_average, nodes),
            base._piecewise_constant_basis(test_average, nodes),
        )
    return features


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument(
        "--start-repeat",
        type=int,
        default=1,
        help="skip fitting earlier deterministic splits while advancing the RNG",
    )
    parser.add_argument("--seed", type=int, default=base.DEFAULT_CV_SEED)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 2:
        parser.error("--repeats must be at least 2")
    if not 1 <= args.start_repeat <= args.repeats:
        parser.error("--start-repeat must be between 1 and --repeats")

    observations = base._read_paired_observations(base.DEFAULT_INPUTS)
    players = tuple(
        sorted(
            {
                player
                for observation in observations
                for player in (observation.black, observation.white)
            }
        )
    )
    sources = tuple(sorted({observation.source for observation in observations}))
    full_dataset = base._dataset_from_observations(
        observations,
        base.ROOT / "log/current_bot_pool/results.csv",
        players=players,
        sources=sources,
    )
    baseline, _covariates, _rating_positions, anchor = _baseline_fit(full_dataset)
    sample_size = (len(players) + 1) // 2
    rng = random.Random(args.seed)
    result_rows: list[dict[str, object]] = []
    for repeat in range(1, args.repeats + 1):
        selected = frozenset(rng.sample(players, sample_size))
        if repeat < args.start_repeat:
            continue
        train_observations = tuple(
            observation
            for observation in observations
            if observation.black in selected and observation.white in selected
        )
        test_observations = tuple(
            observation
            for observation in observations
            if not (
                observation.black in selected and observation.white in selected
            )
        )
        train = base._dataset_from_observations(
            train_observations,
            base.ROOT / f"untracked_log/all-models-half-{repeat}-train.csv",
            players=players,
            sources=sources,
        )
        test = base._dataset_from_observations(
            test_observations,
            base.ROOT / f"untracked_log/all-models-half-{repeat}-test.csv",
            players=players,
            sources=sources,
        )
        train_offset, train_average = _rating_features(train, baseline, anchor)
        test_offset, test_average = _rating_features(test, baseline, anchor)
        train_successes, train_totals = base._scores(train)
        test_successes, test_totals = base._scores(test)
        print(
            f"Repeat {repeat}/{args.repeats}: {train.games:,} train, "
            f"{test.games:,} test",
            flush=True,
        )

        def record(
            model: str,
            parameter_count: int,
            train_predictor: np.ndarray,
            test_predictor: np.ndarray,
            converged: bool,
        ) -> None:
            train_loss = _log_loss(
                train_predictor, train_successes, train_totals, train.games
            )
            test_loss = _log_loss(
                test_predictor, test_successes, test_totals, test.games
            )
            result_rows.append(
                {
                    "repeat": repeat,
                    "model": model,
                    "color_parameters": parameter_count,
                    "train_games": train.games,
                    "test_games": test.games,
                    "train_log_loss": train_loss,
                    "test_log_loss": test_loss,
                    "converged": converged,
                }
            )
            print(
                f"  {model:<28} p={parameter_count:>4} "
                f"train={train_loss:.8f} test={test_loss:.8f}",
                flush=True,
            )

        record("no_color", 0, train_offset, test_offset, True)
        dense_features = _linear_features(
            train_average, test_average, train_totals
        )
        for model, (train_features, test_features) in dense_features.items():
            fit = _fit_dense_color(
                train_features, train_offset, train_successes, train_totals
            )
            record(
                model,
                train_features.shape[1],
                train_offset + train_features @ fit.coefficients,
                test_offset + test_features @ fit.coefficients,
                fit.converged,
            )

        lower = float(np.min(train_average))
        value_range = float(np.max(train_average) - lower)
        train_unit = (
            np.zeros_like(train_average)
            if value_range < 1e-12
            else (train_average - lower) / value_range
        )
        test_unit = (
            np.zeros_like(test_average)
            if value_range < 1e-12
            else (test_average - lower) / value_range
        )
        negative_fit = _fit_negative_exponential(
            train_unit,
            train_offset,
            train_successes,
            train_totals,
        )
        amplitude, decay = negative_fit.coefficients
        record(
            "negative_exponential",
            2,
            train_offset - amplitude * np.exp(-decay * train_unit),
            test_offset - amplitude * np.exp(-decay * test_unit),
            negative_fit.converged,
        )

        for knot_spacing in (1, 100, 250, 500, 1500):
            nodes = base._fixed_elo_nodes(train_average, float(knot_spacing))
            train_design = _sparse_design(train, anchor, {}, train_average, nodes)
            fit = _fit_sparse(
                train_design,
                train_successes,
                train_totals,
                np.empty(0),
                offset=train_offset,
            )
            test_design = _sparse_design(test, anchor, {}, test_average, nodes)
            record(
                f"piecewise_linear_{knot_spacing}",
                len(nodes),
                train_offset + train_design.product(fit.coefficients),
                test_offset + test_design.product(fit.coefficients),
                fit.converged,
            )

    models = tuple(dict.fromkeys(str(row["model"]) for row in result_rows))
    summary_rows: list[dict[str, object]] = []
    for model in models:
        rows = [row for row in result_rows if row["model"] == model]
        train_loss = float(
            np.average(
                [float(row["train_log_loss"]) for row in rows],
                weights=[int(row["train_games"]) for row in rows],
            )
        )
        test_loss = float(
            np.average(
                [float(row["test_log_loss"]) for row in rows],
                weights=[int(row["test_games"]) for row in rows],
            )
        )
        summary_rows.append(
            {
                "model": model,
                "color_parameters_max": max(
                    int(row["color_parameters"]) for row in rows
                ),
                "weighted_train_log_loss": train_loss,
                "weighted_test_log_loss": test_loss,
                "all_repeats_converged": all(
                    bool(row["converged"]) for row in rows
                ),
            }
        )
    summary_rows.sort(key=lambda row: float(row["weighted_test_log_loss"]))
    _write_csv(args.output, summary_rows)
    repeats_path = args.output.with_name(f"{args.output.stem}_repeats.csv")
    _write_csv(repeats_path, result_rows)
    print("\nSummary (lower test loss is better)")
    print(f"{'Model':<28} {'Color p':>8} {'Train':>12} {'Test':>12}")
    for row in summary_rows:
        print(
            f"{str(row['model']):<28} "
            f"{int(row['color_parameters_max']):>8} "
            f"{float(row['weighted_train_log_loss']):>12.8f} "
            f"{float(row['weighted_test_log_loss']):>12.8f}"
        )
    print(f"Wrote {args.output} and {repeats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
