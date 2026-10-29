"""Weighted swing regression and poststratified national projection."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

import numpy as np

from election_model_reproduce_ro_mahl.data import (
    BaselineSection,
    SectionKey,
    SectionOutcome,
)


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    """National estimate based on observed sections and modeled remainder."""

    total_sections: int
    reported_sections: int
    naive_share: float
    projected_share: float
    projected_candidate_votes: float
    projected_valid_votes: float
    reference_state: str
    reference_city_size: str
    coefficients: tuple[tuple[str, float], ...]


def _validate_baseline(
    sections: Sequence[BaselineSection],
) -> dict[SectionKey, BaselineSection]:
    if not sections:
        raise ValueError("baseline must contain at least one section")

    by_key: dict[SectionKey, BaselineSection] = {}
    election_periods = {(row.election_year, row.election_round) for row in sections}
    candidates = {row.candidate_id for row in sections}
    for row in sections:
        if row.key in by_key:
            raise ValueError(f"duplicate baseline section: {row.key}")
        if row.eligible_voters <= 0 or row.valid_votes <= 0:
            raise ValueError(f"baseline voter totals must be positive: {row.key}")
        if row.valid_votes > row.eligible_voters:
            raise ValueError(f"baseline valid votes exceed eligible voters: {row.key}")
        if not 0 <= row.candidate_votes <= row.valid_votes:
            raise ValueError(f"invalid baseline candidate votes: {row.key}")
        if not row.key.state or not row.city_size:
            raise ValueError(f"state and city_size are required: {row.key}")
        by_key[row.key] = row

    if len(election_periods) != 1:
        raise ValueError("baseline rows must belong to one election and round")
    if len(candidates) != 1:
        raise ValueError("baseline rows must use one candidate_id")
    return by_key


def _validate_reported_results(
    results: Sequence[SectionOutcome],
    baseline_by_key: dict[SectionKey, BaselineSection],
) -> dict[SectionKey, SectionOutcome]:
    if not results:
        raise ValueError("at least one reported result is required")

    by_key: dict[SectionKey, SectionOutcome] = {}
    election_periods = {(row.election_year, row.election_round) for row in results}
    baseline_sections = tuple(baseline_by_key.values())
    baseline_candidate = baseline_sections[0].candidate_id
    baseline_year = baseline_sections[0].election_year
    for row in results:
        if row.key in by_key:
            raise ValueError(f"duplicate reported section: {row.key}")
        if row.key not in baseline_by_key:
            raise ValueError(f"reported section is missing a baseline: {row.key}")
        if row.valid_votes <= 0:
            raise ValueError(f"reported valid votes must be positive: {row.key}")
        if row.valid_votes > baseline_by_key[row.key].eligible_voters:
            raise ValueError(f"reported valid votes exceed eligible voters: {row.key}")
        if not 0 <= row.candidate_votes <= row.valid_votes:
            raise ValueError(f"invalid reported candidate votes: {row.key}")
        if row.candidate_id != baseline_candidate:
            raise ValueError("baseline and reported rows must use the same candidate_id")
        by_key[row.key] = row

    if len(election_periods) != 1:
        raise ValueError("reported rows must belong to one election and round")
    if next(iter(election_periods))[0] <= baseline_year:
        raise ValueError("reported election year must be later than the baseline")
    return by_key


def _design_row(
    state: str,
    city_size: str,
    state_levels: tuple[str, ...],
    city_size_levels: tuple[str, ...],
) -> list[float]:
    return [
        1.0,
        *(float(state == level) for level in state_levels[1:]),
        *(float(city_size == level) for level in city_size_levels[1:]),
    ]


def estimate_election(
    baseline: Sequence[BaselineSection],
    reported_results: Sequence[SectionOutcome],
) -> ProjectionResult:
    """Estimate national candidate share using a weighted additive swing model.

    Reported sections are weighted by their observed valid-vote counts. For
    unreported sections, expected valid votes are carried forward from the
    historical turnout rate and scaled to the current eligible-voter count.
    """
    baseline_rows = tuple(baseline)
    result_rows = tuple(reported_results)
    baseline_by_key = _validate_baseline(baseline_rows)
    reported_by_key = _validate_reported_results(result_rows, baseline_by_key)

    state_levels = tuple(sorted({row.key.state for row in baseline_rows}))
    city_size_levels = tuple(sorted({row.city_size for row in baseline_rows}))
    if not state_levels or not city_size_levels:
        raise ValueError("baseline must include state and city-size categories")
    observed_states = {row.key.state for row in result_rows}
    observed_city_sizes = {
        baseline_by_key[row.key].city_size for row in result_rows
    }
    missing_states = sorted(set(state_levels) - observed_states)
    missing_city_sizes = sorted(set(city_size_levels) - observed_city_sizes)
    if missing_states:
        raise ValueError(
            "reported results do not cover baseline states: "
            + ", ".join(missing_states)
        )
    if missing_city_sizes:
        raise ValueError(
            "reported results do not cover baseline city sizes: "
            + ", ".join(missing_city_sizes)
        )

    design = np.asarray(
        [
            _design_row(
                baseline_by_key[result.key].key.state,
                baseline_by_key[result.key].city_size,
                state_levels,
                city_size_levels,
            )
            for result in result_rows
        ],
        dtype=float,
    )
    deltas = np.asarray(
        [
            result.vote_share - baseline_by_key[result.key].vote_share
            for result in result_rows
        ],
        dtype=float,
    )
    weights = np.asarray([result.valid_votes for result in result_rows], dtype=float)
    sqrt_weights = np.sqrt(weights)
    coefficients, _, _, _ = np.linalg.lstsq(
        design * sqrt_weights[:, np.newaxis],
        deltas * sqrt_weights,
        rcond=None,
    )
    if not np.all(np.isfinite(coefficients)):
        raise ValueError("regression produced non-finite coefficients")

    reported_candidate_votes = sum(row.candidate_votes for row in result_rows)
    reported_valid_votes = sum(row.valid_votes for row in result_rows)
    projected_candidate_votes = float(reported_candidate_votes)
    projected_valid_votes = float(reported_valid_votes)
    unreported_count = 0

    for section in baseline_rows:
        if section.key in reported_by_key:
            continue

        row = np.asarray(
            _design_row(
                section.key.state,
                section.city_size,
                state_levels,
                city_size_levels,
            ),
            dtype=float,
        )
        predicted_swing = float(row @ coefficients)
        predicted_share = min(1.0, max(0.0, section.vote_share + predicted_swing))
        expected_valid_votes = float(section.valid_votes)
        projected_candidate_votes += predicted_share * expected_valid_votes
        projected_valid_votes += expected_valid_votes
        unreported_count += 1

    if projected_valid_votes <= 0 or not isfinite(projected_candidate_votes):
        raise ValueError("projection produced invalid national vote totals")

    coefficient_names = (
        "intercept",
        *(f"state[{level}]" for level in state_levels[1:]),
        *(f"city_size[{level}]" for level in city_size_levels[1:]),
    )
    return ProjectionResult(
        total_sections=len(baseline_rows),
        reported_sections=len(result_rows),
        naive_share=reported_candidate_votes / reported_valid_votes,
        projected_share=projected_candidate_votes / projected_valid_votes,
        projected_candidate_votes=projected_candidate_votes,
        projected_valid_votes=projected_valid_votes,
        reference_state=state_levels[0],
        reference_city_size=city_size_levels[0],
        coefficients=tuple(
            (name, float(value))
            for name, value in zip(coefficient_names, coefficients)
        ),
    )
