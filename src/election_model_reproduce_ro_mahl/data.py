"""TSE-inspired records and a deterministic synthetic election generator."""

from __future__ import annotations

import random
from dataclasses import dataclass

CITY_SIZES = ("Small", "Medium", "Large")
STATES = ("BA", "MG", "RJ", "SP")
CANDIDATE_ID = "candidate_a"


@dataclass(frozen=True, order=True, slots=True)
class SectionKey:
    """Synthetic section identity using TSE-inspired geographic fields."""

    state: str
    municipality_code: str
    zone_number: int
    section_number: int


@dataclass(frozen=True, slots=True)
class BaselineSection:
    """Historical section result and the turnout baseline used for weighting."""

    key: SectionKey
    election_year: int
    election_round: int
    city_size: str
    eligible_voters: int
    valid_votes: int
    candidate_votes: int
    candidate_id: str = CANDIDATE_ID

    @property
    def vote_share(self) -> float:
        return self.candidate_votes / self.valid_votes


@dataclass(frozen=True, slots=True)
class SectionOutcome:
    """Complete synthetic result for one section in the simulated election."""

    key: SectionKey
    election_year: int
    election_round: int
    valid_votes: int
    candidate_votes: int
    candidate_id: str = CANDIDATE_ID

    @property
    def vote_share(self) -> float:
        return self.candidate_votes / self.valid_votes


@dataclass(frozen=True, slots=True)
class SyntheticElection:
    """A synthetic election, including hidden outcomes for evaluation only."""

    baseline: tuple[BaselineSection, ...]
    outcomes: tuple[SectionOutcome, ...]
    reported_keys: frozenset[SectionKey]

    @property
    def reported_results(self) -> tuple[SectionOutcome, ...]:
        return tuple(
            result for result in self.outcomes if result.key in self.reported_keys
        )

    @property
    def actual_share(self) -> float:
        total_valid_votes = sum(result.valid_votes for result in self.outcomes)
        total_candidate_votes = sum(
            result.candidate_votes for result in self.outcomes
        )
        return total_candidate_votes / total_valid_votes


def create_synthetic_election(
    seed: int = 42,
    reported_fraction: float = 0.30,
) -> SyntheticElection:
    """Create reproducible section-level data without network access.

    ``reported_fraction`` is the fraction sampled from early-reporting-prone
    sections (small municipalities and all municipalities in RJ), not the
    fraction of all sections expected to be reported.
    """
    if not 0 < reported_fraction <= 1:
        raise ValueError("reported_fraction must be greater than 0 and at most 1")

    rng = random.Random(seed)
    baseline: list[BaselineSection] = []
    outcomes: list[SectionOutcome] = []
    early_reporting_keys: list[SectionKey] = []
    state_swing = {"BA": -0.040, "MG": -0.005, "RJ": 0.015, "SP": 0.035}
    city_swing = {"Small": 0.005, "Medium": 0.010, "Large": -0.025}
    state_lean = {"BA": 0.055, "MG": 0.015, "RJ": -0.025, "SP": -0.045}
    city_lean = {"Small": 0.025, "Medium": 0.000, "Large": -0.020}

    for state_index, state in enumerate(STATES):
        for municipality_index in range(6):
            city_size = CITY_SIZES[municipality_index % len(CITY_SIZES)]
            municipality_code = f"{state_index + 1:02d}{municipality_index + 1:04d}"

            for section_number in range(1, 9):
                key = SectionKey(
                    state=state,
                    municipality_code=municipality_code,
                    zone_number=municipality_index + 1,
                    section_number=section_number,
                )
                eligible_voters = rng.randint(250, 850)
                historical_turnout = rng.uniform(0.65, 0.82)
                historical_valid_votes = max(
                    1, round(eligible_voters * historical_turnout)
                )
                historical_share = min(
                    0.85,
                    max(
                        0.15,
                        0.50
                        + state_lean[state]
                        + city_lean[city_size]
                        + rng.uniform(-0.15, 0.15),
                    ),
                )
                historical_candidate_votes = round(
                    historical_valid_votes * historical_share
                )
                baseline.append(
                    BaselineSection(
                        key=key,
                        election_year=2022,
                        election_round=1,
                        city_size=city_size,
                        eligible_voters=eligible_voters,
                        valid_votes=historical_valid_votes,
                        candidate_votes=historical_candidate_votes,
                    )
                )

                current_turnout = min(
                    0.90,
                    max(0.55, historical_turnout + rng.uniform(-0.04, 0.04)),
                )
                current_valid_votes = max(1, round(eligible_voters * current_turnout))
                current_share = min(
                    0.97,
                    max(
                        0.03,
                        historical_share
                        + state_swing[state]
                        + city_swing[city_size]
                        + rng.uniform(-0.015, 0.015),
                    ),
                )
                outcomes.append(
                    SectionOutcome(
                        key=key,
                        election_year=2026,
                        election_round=1,
                        valid_votes=current_valid_votes,
                        candidate_votes=round(current_valid_votes * current_share),
                    )
                )
                if city_size == "Small" or state == "RJ":
                    early_reporting_keys.append(key)

    reported_count = max(1, round(len(early_reporting_keys) * reported_fraction))
    reported_keys = frozenset(rng.sample(early_reporting_keys, reported_count))
    return SyntheticElection(
        baseline=tuple(baseline),
        outcomes=tuple(outcomes),
        reported_keys=reported_keys,
    )

