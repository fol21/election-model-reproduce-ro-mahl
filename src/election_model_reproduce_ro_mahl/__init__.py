"""Synthetic, TSE-inspired election-estimation prototype."""

from election_model_reproduce_ro_mahl.data import (
    BaselineSection,
    SectionKey,
    SectionOutcome,
    SyntheticElection,
    create_synthetic_election,
)
from election_model_reproduce_ro_mahl.model import (
    ProjectionResult,
    estimate_election,
)

__all__ = [
    "BaselineSection",
    "ProjectionResult",
    "SectionKey",
    "SectionOutcome",
    "SyntheticElection",
    "create_synthetic_election",
    "estimate_election",
]

