from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from election_model_reproduce_ro_mahl.tse_data import (
    CatalogResource,
    TSEDataError,
    discover_resources,
    download_archive,
    normalize_archives,
)

DETAIL_FIELDS = (
    "ANO_ELEICAO",
    "NR_TURNO",
    "CD_CARGO",
    "DS_CARGO",
    "CD_ELEICAO",
    "SG_UF",
    "CD_MUNICIPIO",
    "NR_ZONA",
    "NR_SECAO",
    "QT_APTOS",
    "QT_COMPARECIMENTO",
    "QT_ABSTENCOES",
    "QT_VOTOS_NOMINAIS",
    "QT_VOTOS_BRANCOS",
    "QT_VOTOS_NULOS",
)
CANDIDATE_FIELDS = (
    "ANO_ELEICAO",
    "NR_TURNO",
    "CD_CARGO",
    "DS_CARGO",
    "CD_ELEICAO",
    "SG_UF",
    "CD_MUNICIPIO",
    "NR_ZONA",
    "NR_SECAO",
    "NR_VOTAVEL",
    "NM_VOTAVEL",
    "QT_VOTOS",
    "SQ_CANDIDATO",
)


def _csv_bytes(fields: tuple[str, ...], rows: list[dict[str, str]]) -> bytes:
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=fields, delimiter=";")
    writer.writeheader()
    writer.writerows(rows)
    return text.getvalue().encode("latin-1")


def _detail_row(
    state: str,
    municipality: str,
    section: int,
    *,
    valid: int,
    turn: int = 1,
    cargo: str = "1",
    office: str = "Presidente",
) -> dict[str, str]:
    return {
        "ANO_ELEICAO": "2022",
        "NR_TURNO": str(turn),
        "CD_CARGO": cargo,
        "DS_CARGO": office,
        "CD_ELEICAO": "544",
        "SG_UF": state,
        "CD_MUNICIPIO": municipality,
        "NR_ZONA": "1",
        "NR_SECAO": str(section),
        "QT_APTOS": "100",
        "QT_COMPARECIMENTO": "80",
        "QT_ABSTENCOES": "20",
        "QT_VOTOS_NOMINAIS": str(valid),
        "QT_VOTOS_BRANCOS": "5",
        "QT_VOTOS_NULOS": str(75 - valid),
    }


def _candidate_row(
    state: str,
    municipality: str,
    section: int,
    *,
    candidate_id: str,
    ballot_number: str,
    name: str,
    votes: int,
    turn: int = 1,
    cargo: str = "1",
    office: str = "Presidente",
) -> dict[str, str]:
    return {
        "ANO_ELEICAO": "2022",
        "NR_TURNO": str(turn),
        "CD_CARGO": cargo,
        "DS_CARGO": office,
        "CD_ELEICAO": "544",
        "SG_UF": state,
        "CD_MUNICIPIO": municipality,
        "NR_ZONA": "1",
        "NR_SECAO": str(section),
        "NR_VOTAVEL": ballot_number,
        "NM_VOTAVEL": name,
        "QT_VOTOS": str(votes),
        "SQ_CANDIDATO": candidate_id,
    }


def _create_archives(
    directory: Path,
    *,
    candidate_rows: list[dict[str, str]] | None = None,
) -> tuple[Path, Path]:
    presidential_path = directory / "votes.zip"
    details_path = directory / "details.zip"
    details_rows = [
        _detail_row("SP", "3550308", 1, valid=70),
        _detail_row("BA", "2927408", 2, valid=50),
        _detail_row("SP", "3550308", 1, valid=70, turn=2),
        _detail_row("SP", "3550308", 1, valid=70, cargo="3", office="Governador"),
    ]
    if candidate_rows is None:
        candidate_rows = [
            _candidate_row(
                "SP", "3550308", 1, candidate_id="280001", ballot_number="13",
                name="Candidata Um", votes=40,
            ),
            _candidate_row(
                "SP", "3550308", 1, candidate_id="280002", ballot_number="22",
                name="Candidato Dois", votes=30,
            ),
            _candidate_row(
                "BA", "2927408", 2, candidate_id="280001", ballot_number="13",
                name="Candidata Um", votes=20,
            ),
            _candidate_row(
                "BA", "2927408", 2, candidate_id="280002", ballot_number="22",
                name="Candidato Dois", votes=30,
            ),
            _candidate_row(
                "SP", "3550308", 1, candidate_id="", ballot_number="95",
                name="VOTO EM BRANCO", votes=5,
            ),
            _candidate_row(
                "SP", "3550308", 1, candidate_id="0", ballot_number="96",
                name="VOTO NULO", votes=5,
            ),
            _candidate_row(
                "SP", "3550308", 1, candidate_id="280003", ballot_number="13",
                name="Candidata Um", votes=40, turn=2,
            ),
        ]
    with zipfile.ZipFile(details_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "detalhe_votacao_secao_2022_SP.csv",
            _csv_bytes(DETAIL_FIELDS, details_rows),
        )
        archive.writestr(
            "detalhe_votacao_secao_2022_BA.csv",
            _csv_bytes(DETAIL_FIELDS, []),
        )
    with zipfile.ZipFile(presidential_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "votacao_secao_2022_BR.csv",
            _csv_bytes(CANDIDATE_FIELDS, candidate_rows),
        )
    return presidential_path, details_path


class _FakeResponse(io.BytesIO):
    def __init__(self, content: bytes, headers: dict[str, str] | None = None) -> None:
        super().__init__(content)
        self.headers = headers or {}


class TSEDataTests(unittest.TestCase):
    def test_catalog_discovery_uses_the_two_named_official_resources(self) -> None:
        payload = {
            "success": True,
            "result": {
                "id": "package-id",
                "resources": [
                    {
                        "id": "votes-id",
                        "name": "Presidente - Votação por seção eleitoral - 2022",
                        "url": "https://cdn.tse.jus.br/votes.zip",
                    },
                    {
                        "id": "details-id",
                        "name": "Detalhe da apuração por seção eleitoral",
                        "url": "https://cdn.tse.jus.br/details.zip",
                    },
                ],
            },
        }
        with patch(
            "election_model_reproduce_ro_mahl.tse_data.urllib.request.urlopen",
            return_value=_FakeResponse(json.dumps(payload).encode()),
        ):
            votes, details = discover_resources(2022)

        self.assertEqual(votes.resource_id, "votes-id")
        self.assertEqual(details.resource_id, "details-id")
        self.assertEqual(votes.package_id, "package-id")

    def test_catalog_rejects_non_official_resource_hosts(self) -> None:
        payload = {
            "success": True,
            "result": {
                "id": "package-id",
                "resources": [
                    {
                        "id": "votes-id",
                        "name": "Presidente - Votação por seção eleitoral - 2022",
                        "url": "https://example.invalid/votes.zip",
                    },
                    {
                        "id": "details-id",
                        "name": "Detalhe da apuração por seção eleitoral",
                        "url": "https://cdn.tse.jus.br/details.zip",
                    },
                ],
            },
        }
        with patch(
            "election_model_reproduce_ro_mahl.tse_data.urllib.request.urlopen",
            return_value=_FakeResponse(json.dumps(payload).encode()),
        ), self.assertRaisesRegex(TSEDataError, "non-official or insecure"):
            discover_resources(2022)

    def test_download_is_atomic_and_reuses_cached_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            votes_zip, _ = _create_archives(directory)
            content = votes_zip.read_bytes()
            destination = directory / "downloaded.zip"
            resource = CatalogResource(
                package_name="resultados-2022",
                package_id="package",
                resource_id="resource",
                name="test archive",
                url="https://cdn.tse.jus.br/archive.zip",
            )
            with patch(
                "election_model_reproduce_ro_mahl.tse_data.urllib.request.urlopen",
                return_value=_FakeResponse(
                    content, {"Content-Length": str(len(content))}
                ),
            ):
                first = download_archive(resource, destination)

            with patch(
                "election_model_reproduce_ro_mahl.tse_data.urllib.request.urlopen",
                side_effect=AssertionError("cache should avoid a second download"),
            ):
                second = download_archive(resource, destination)

        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertEqual(first.sha256, second.sha256)

    def test_normalization_filters_rounds_and_joins_section_totals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            votes_zip, details_zip = _create_archives(directory)
            result = normalize_archives(
                votes_zip,
                details_zip,
                year=2022,
                election_round=1,
                output_dir=directory / "processed",
            )

            with result.sections_path.open(encoding="utf-8", newline="") as source:
                sections = list(csv.DictReader(source))
            with result.candidates_path.open(encoding="utf-8", newline="") as source:
                candidates = list(csv.DictReader(source))

        self.assertEqual(result.section_rows, 2)
        self.assertEqual(result.candidate_rows, 4)
        self.assertEqual(len(sections), 2)
        self.assertEqual(len(candidates), 4)
        self.assertEqual(sections[0]["valid_votes"], "50")
        self.assertEqual(sections[1]["eligible_voters"], "100")
        self.assertEqual(candidates[0]["candidate_id"], "280001")
        self.assertEqual(
            next(
                row["candidate_votes"]
                for row in candidates
                if row["state"] == "BA" and row["candidate_id"] == "280001"
            ),
            "20",
        )

    def test_normalization_fails_when_candidate_sum_disagrees_with_detail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            candidate_rows = [
                _candidate_row(
                    "SP", "3550308", 1, candidate_id="280001", ballot_number="13",
                    name="Candidata Um", votes=40,
                ),
                _candidate_row(
                    "SP", "3550308", 1, candidate_id="280002", ballot_number="22",
                    name="Candidato Dois", votes=29,
                ),
            ]
            votes_zip, details_zip = _create_archives(
                directory, candidate_rows=candidate_rows
            )
            with self.assertRaisesRegex(TSEDataError, "do not match QT_VOTOS_NOMINAIS"):
                normalize_archives(
                    votes_zip,
                    details_zip,
                    year=2022,
                    election_round=1,
                    output_dir=directory / "processed",
                )

            self.assertFalse(
                (directory / "processed" / "president_2022_round_1_sections.csv.part").exists()
            )
            self.assertFalse(
                (directory / "processed" / "president_2022_round_1_candidate_votes.csv.part").exists()
            )

    def test_normalization_restores_previous_outputs_if_pair_publish_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            votes_zip, details_zip = _create_archives(directory)
            output_dir = directory / "processed"
            output_dir.mkdir()
            sections_path = output_dir / "president_2022_round_1_sections.csv"
            candidates_path = (
                output_dir / "president_2022_round_1_candidate_votes.csv"
            )
            sections_path.write_text("previous sections\n", encoding="utf-8")
            candidates_path.write_text("previous candidates\n", encoding="utf-8")
            original_replace = Path.replace

            def replace_with_candidate_failure(
                source: Path, target: str | Path
            ) -> Path:
                if Path(target) == candidates_path and str(source).endswith(".part"):
                    raise PermissionError("simulated locked candidate output")
                return original_replace(source, target)

            with patch.object(Path, "replace", replace_with_candidate_failure):
                with self.assertRaisesRegex(TSEDataError, "previous files were restored"):
                    normalize_archives(
                        votes_zip,
                        details_zip,
                        year=2022,
                        election_round=1,
                        output_dir=output_dir,
                    )

            self.assertEqual(
                sections_path.read_text(encoding="utf-8"), "previous sections\n"
            )
            self.assertEqual(
                candidates_path.read_text(encoding="utf-8"), "previous candidates\n"
            )
            self.assertEqual(list(output_dir.glob("*.bak")), [])


if __name__ == "__main__":
    unittest.main()
