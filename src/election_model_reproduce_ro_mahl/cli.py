"""Command-line entry point for the synthetic estimation demo."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from election_model_reproduce_ro_mahl.data import create_synthetic_election
from election_model_reproduce_ro_mahl.model import estimate_election


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a synthetic, TSE-inspired election swing-model demo."
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="random seed for reproducible synthetic data (default: 42)",
    )
    parser.add_argument(
        "--reported-fraction",
        type=float,
        default=0.30,
        help=(
            "fraction sampled from early-reporting-prone sections; this is not "
            "the fraction of all sections (default: 0.30)"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        election = create_synthetic_election(
            seed=args.seed,
            reported_fraction=args.reported_fraction,
        )
        projection = estimate_election(
            election.baseline,
            election.reported_results,
        )
    except ValueError as error:
        _build_parser().error(str(error))

    reported_percent = (
        projection.reported_sections / projection.total_sections * 100
    )
    print("SYNTHETIC DEMO ONLY - no TSE data is downloaded or used.")
    print("Election: simulated 2026 first round; baseline: simulated 2022 first round")
    print(
        f"Reported sections: {projection.reported_sections} / "
        f"{projection.total_sections} ({reported_percent:.1f}%)"
    )
    print(f"Naive reported-only share:       {projection.naive_share * 100:.2f}%")
    print(f"Swing-model projection:          {projection.projected_share * 100:.2f}%")
    print(
        f"Simulated final truth (evaluation only): "
        f"{election.actual_share * 100:.2f}%"
    )
    return 0
