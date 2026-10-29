from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import unittest

from election_model_reproduce_ro_mahl.cli import main
from election_model_reproduce_ro_mahl.data import (
    SectionKey,
    SectionOutcome,
    create_synthetic_election,
)
from election_model_reproduce_ro_mahl.model import estimate_election


class SyntheticElectionTests(unittest.TestCase):
    def test_data_generation_is_reproducible(self) -> None:
        first = create_synthetic_election(seed=17)
        second = create_synthetic_election(seed=17)

        self.assertEqual(first.baseline, second.baseline)
        self.assertEqual(first.outcomes, second.outcomes)
        self.assertEqual(first.reported_keys, second.reported_keys)

    def test_data_generation_rejects_invalid_report_fraction(self) -> None:
        for value in (0, -0.1, 1.1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                create_synthetic_election(reported_fraction=value)

    def test_projection_is_finite_and_uses_reported_sections(self) -> None:
        election = create_synthetic_election()
        projection = estimate_election(election.baseline, election.reported_results)

        self.assertEqual(projection.total_sections, len(election.baseline))
        self.assertEqual(projection.reported_sections, len(election.reported_keys))
        self.assertGreater(projection.projected_valid_votes, 0)
        self.assertTrue(0 <= projection.projected_share <= 1)
        self.assertTrue(0 <= projection.naive_share <= 1)
        self.assertTrue(projection.coefficients)

    def test_projection_is_closer_than_naive_count_for_default_fixture(self) -> None:
        election = create_synthetic_election()
        projection = estimate_election(election.baseline, election.reported_results)

        projected_error = abs(projection.projected_share - election.actual_share)
        naive_error = abs(projection.naive_share - election.actual_share)
        self.assertLess(projected_error, naive_error)

    def test_projection_rejects_duplicate_reported_sections(self) -> None:
        election = create_synthetic_election()
        reported = election.reported_results

        with self.assertRaisesRegex(ValueError, "duplicate reported section"):
            estimate_election(election.baseline, (*reported, reported[0]))

    def test_projection_rejects_unknown_reported_sections(self) -> None:
        election = create_synthetic_election()
        reported = election.reported_results[0]
        unknown = SectionOutcome(
            key=SectionKey("SP", "999999", 1, 1),
            election_year=reported.election_year,
            election_round=reported.election_round,
            valid_votes=100,
            candidate_votes=50,
        )

        with self.assertRaisesRegex(ValueError, "missing a baseline"):
            estimate_election(election.baseline, (unknown,))

    def test_projection_requires_reported_data(self) -> None:
        election = create_synthetic_election()

        with self.assertRaisesRegex(ValueError, "at least one reported result"):
            estimate_election(election.baseline, ())

    def test_cli_labels_output_as_synthetic(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(["--seed", "42"])

        self.assertEqual(exit_code, 0)
        self.assertIn("SYNTHETIC DEMO ONLY", output.getvalue())
        self.assertIn("Swing-model projection:", output.getvalue())
        self.assertIn("evaluation only", output.getvalue())


if __name__ == "__main__":
    unittest.main()
