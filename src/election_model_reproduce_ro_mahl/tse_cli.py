"""Explicit command-line interface for downloading TSE section results."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import sys

from election_model_reproduce_ro_mahl.tse_data import (
    MAX_ARCHIVE_BYTES,
    CatalogResource,
    TSEDataError,
    fetch_tse_section_results,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download official TSE presidential section results and normalize "
            "them to CSV. Downloads are large and use network access."
        )
    )
    parser.add_argument("--year", type=int, required=True, help="election year, e.g. 2022")
    parser.add_argument(
        "--round",
        dest="election_round",
        type=int,
        choices=(1, 2),
        required=True,
        help="presidential election round",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/tse"),
        help="data directory for raw archives, normalized CSVs, and manifest",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="download archives again even if cached ZIPs already exist",
    )
    parser.add_argument(
        "--max-archive-mb",
        type=int,
        default=MAX_ARCHIVE_BYTES // 1_000_000,
        help=(
            "maximum accepted size for each archive in decimal MB "
            f"(default: {MAX_ARCHIVE_BYTES // 1_000_000})"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.max_archive_mb <= 0:
        parser.error("--max-archive-mb must be positive")

    print(
        f"Looking up official TSE section-result resources for "
        f"{args.year}, round {args.election_round}..."
    )

    def show_progress(
        resource: CatalogResource,
        downloaded_bytes: int,
        total_bytes: int | None,
    ) -> None:
        if downloaded_bytes == 0:
            print(f"Downloading {resource.name}...", file=sys.stderr, flush=True)
            return
        downloaded_mb = downloaded_bytes / 1_000_000
        if total_bytes is None:
            detail = f"{downloaded_mb:.0f} MB received"
        else:
            total_mb = total_bytes / 1_000_000
            detail = f"{downloaded_mb:.0f}/{total_mb:.0f} MB"
        print(f"  {resource.name}: {detail}", file=sys.stderr, flush=True)

    try:
        result = fetch_tse_section_results(
            args.year,
            args.election_round,
            output_dir=args.output_dir,
            refresh=args.refresh,
            max_archive_bytes=args.max_archive_mb * 1_000_000,
            progress_callback=show_progress,
        )
    except (TSEDataError, ValueError) as error:
        parser.error(str(error))

    print(
        f"Normalized {result.section_rows:,} section rows and "
        f"{result.candidate_rows:,} candidate-vote rows."
    )
    print(f"Sections:       {result.sections_path}")
    print(f"Candidate votes:{result.candidates_path}")
    print(f"Provenance:     {result.manifest_path}")
    print(
        f"Reused cached archives: {result.reused_archives}/2 "
        "(use --refresh to fetch the latest catalog files)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
