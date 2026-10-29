"""Download and normalize official TSE presidential section-result archives."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, TextIO

CKAN_API = "https://dadosabertos.tse.jus.br/api/3/action/package_show"
MAX_ARCHIVE_BYTES = 2_000_000_000
MAX_UNCOMPRESSED_BYTES = 8_000_000_000
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
ALLOWED_HOSTS = {"dadosabertos.tse.jus.br", "cdn.tse.jus.br"}

SECTION_KEY_FIELDS = (
    "SG_UF",
    "CD_MUNICIPIO",
    "NR_ZONA",
    "NR_SECAO",
)
DETAIL_FIELDS = (
    "ANO_ELEICAO",
    "NR_TURNO",
    "CD_CARGO",
    "DS_CARGO",
    "CD_ELEICAO",
    *SECTION_KEY_FIELDS,
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
    *SECTION_KEY_FIELDS,
    "NR_VOTAVEL",
    "NM_VOTAVEL",
    "QT_VOTOS",
    "SQ_CANDIDATO",
)
SECTION_OUTPUT_FIELDS = (
    "election_year",
    "election_round",
    "state",
    "municipality_code",
    "zone_number",
    "section_number",
    "eligible_voters",
    "voters_present",
    "abstentions",
    "valid_votes",
    "blank_votes",
    "null_votes",
)
CANDIDATE_OUTPUT_FIELDS = (
    "election_year",
    "election_round",
    "state",
    "municipality_code",
    "zone_number",
    "section_number",
    "candidate_id",
    "ballot_number",
    "candidate_name",
    "candidate_votes",
)


class TSEDataError(RuntimeError):
    """Raised when an official dataset cannot be downloaded or normalized."""


@dataclass(frozen=True, slots=True)
class CatalogResource:
    package_name: str
    package_id: str
    resource_id: str
    name: str
    url: str


@dataclass(frozen=True, slots=True)
class DownloadInfo:
    path: Path
    size_bytes: int
    sha256: str
    reused: bool


@dataclass(frozen=True, slots=True)
class NormalizationInfo:
    sections_path: Path
    candidates_path: Path
    section_rows: int
    candidate_rows: int


@dataclass(frozen=True, slots=True)
class FetchInfo:
    year: int
    election_round: int
    sections_path: Path
    candidates_path: Path
    manifest_path: Path
    section_rows: int
    candidate_rows: int
    reused_archives: int


@dataclass(frozen=True, slots=True)
class _SectionTotals:
    state: str
    municipality_code: str
    zone_number: int
    section_number: int
    eligible_voters: int
    voters_present: int
    abstentions: int
    valid_votes: int
    blank_votes: int
    null_votes: int

    @property
    def key(self) -> tuple[str, str, int, int]:
        return (
            self.state,
            self.municipality_code,
            self.zone_number,
            self.section_number,
        )


def _official_https_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise TSEDataError(f"refusing non-official or insecure TSE URL: {value}")
    return value


def _read_json_url(url: str) -> dict[str, object]:
    request = urllib.request.Request(
        _official_https_url(url),
        headers={"User-Agent": "election-model-reproduction/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise TSEDataError(f"failed to retrieve TSE catalog ({url}): {error}") from error
    if not isinstance(data, dict):
        raise TSEDataError("TSE catalog returned an unexpected JSON document")
    return data


def discover_resources(year: int) -> tuple[CatalogResource, CatalogResource]:
    """Find the official presidential-results and section-detail resources."""
    if year < 1990 or year > 2100:
        raise ValueError("year must be between 1990 and 2100")

    package_name = f"resultados-{year}"
    catalog = _read_json_url(f"{CKAN_API}?id={package_name}")
    if catalog.get("success") is not True:
        error = catalog.get("error", "unknown CKAN error")
        raise TSEDataError(f"TSE catalog has no successful package {package_name}: {error}")
    result = catalog.get("result")
    if not isinstance(result, dict):
        raise TSEDataError(f"TSE catalog package {package_name} has no result metadata")
    resources = result.get("resources")
    if not isinstance(resources, list):
        raise TSEDataError(f"TSE catalog package {package_name} has no resource list")

    election_title = f"Presidente - Votação por seção eleitoral - {year}"
    detail_title = "Detalhe da apuração por seção eleitoral"
    found: dict[str, CatalogResource] = {}
    package_id = str(result.get("id", ""))
    for raw in resources:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name", "")).strip()
        if name not in {election_title, detail_title}:
            continue
        url = str(raw.get("url", ""))
        resource_id = str(raw.get("id", ""))
        if not url or not resource_id:
            raise TSEDataError(f"TSE resource {name!r} is missing its URL or resource ID")
        found[name] = CatalogResource(
            package_name=package_name,
            package_id=package_id,
            resource_id=resource_id,
            name=name,
            url=_official_https_url(url),
        )

    missing = [title for title in (election_title, detail_title) if title not in found]
    if missing:
        raise TSEDataError(
            f"TSE package {package_name} does not expose required resource(s): "
            + ", ".join(missing)
        )
    return found[election_title], found[detail_title]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(DOWNLOAD_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_archive(
    resource: CatalogResource,
    destination: Path,
    *,
    refresh: bool = False,
    max_bytes: int = MAX_ARCHIVE_BYTES,
    progress_callback: Callable[[int, int | None], None] | None = None,
) -> DownloadInfo:
    """Download an official ZIP atomically, or reuse a valid cached archive."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if destination.exists() and not refresh:
        if not zipfile.is_zipfile(destination):
            raise TSEDataError(
                f"cached archive is not a valid ZIP: {destination}; "
                "remove it or use --refresh"
            )
        cached_size = destination.stat().st_size
        if cached_size > max_bytes:
            raise TSEDataError(
                f"cached archive {destination} exceeds the "
                f"{max_bytes:,}-byte limit"
            )
        try:
            with zipfile.ZipFile(destination) as archive:
                expanded_size = sum(item.file_size for item in archive.infolist())
        except zipfile.BadZipFile as error:
            raise TSEDataError(
                f"cached archive is not a valid ZIP: {destination}"
            ) from error
        if expanded_size > MAX_UNCOMPRESSED_BYTES:
            raise TSEDataError(
                f"cached archive {destination} expands beyond the "
                f"{MAX_UNCOMPRESSED_BYTES:,}-byte safety limit"
            )
        return DownloadInfo(
            path=destination,
            size_bytes=cached_size,
            sha256=_sha256_file(destination),
            reused=True,
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_name(destination.name + ".part")
    request = urllib.request.Request(
        _official_https_url(resource.url),
        headers={"User-Agent": "election-model-reproduction/0.1"},
    )
    digest = hashlib.sha256()
    byte_count = 0
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    expected_bytes = int(content_length)
                except ValueError as error:
                    raise TSEDataError(
                        f"TSE returned an invalid Content-Length for {resource.name}"
                    ) from error
                if expected_bytes > max_bytes:
                    raise TSEDataError(
                        f"{resource.name} is {expected_bytes:,} bytes, above the "
                        f"configured {max_bytes:,}-byte limit"
                    )
            else:
                expected_bytes = None
            if progress_callback is not None:
                progress_callback(0, expected_bytes)

            with temporary_path.open("wb") as target:
                next_progress = 32 * DOWNLOAD_CHUNK_BYTES
                while chunk := response.read(DOWNLOAD_CHUNK_BYTES):
                    byte_count += len(chunk)
                    if byte_count > max_bytes:
                        raise TSEDataError(
                            f"{resource.name} exceeded the {max_bytes:,}-byte limit"
                        )
                    digest.update(chunk)
                    target.write(chunk)
                    if progress_callback is not None and byte_count >= next_progress:
                        progress_callback(byte_count, expected_bytes)
                        next_progress += 32 * DOWNLOAD_CHUNK_BYTES
                target.flush()
                os.fsync(target.fileno())

        if content_length and byte_count != expected_bytes:
            raise TSEDataError(
                f"incomplete download for {resource.name}: expected "
                f"{expected_bytes:,} bytes, received {byte_count:,}"
            )
        if not zipfile.is_zipfile(temporary_path):
            raise TSEDataError(f"TSE resource is not a valid ZIP archive: {resource.name}")
        with zipfile.ZipFile(temporary_path) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
                raise TSEDataError(
                    f"{resource.name} expands beyond the "
                    f"{MAX_UNCOMPRESSED_BYTES:,}-byte safety limit"
                )
        if progress_callback is not None:
            progress_callback(byte_count, expected_bytes)
        temporary_path.replace(destination)
        return DownloadInfo(
            path=destination,
            size_bytes=byte_count,
            sha256=digest.hexdigest(),
            reused=False,
        )
    except (urllib.error.URLError, TimeoutError, OSError, zipfile.BadZipFile) as error:
        raise TSEDataError(f"failed downloading TSE resource {resource.name}: {error}") from error
    finally:
        temporary_path.unlink(missing_ok=True)


def _normalize_header(value: str) -> str:
    return value.strip().lstrip("\ufeff").upper()


def _required_columns(
    reader: csv.DictReader[str],
    required: tuple[str, ...],
    source_name: str,
) -> None:
    fieldnames = reader.fieldnames or []
    normalized = {_normalize_header(name) for name in fieldnames}
    missing = [name for name in required if name not in normalized]
    if missing:
        raise TSEDataError(
            f"{source_name} is missing required TSE CSV column(s): "
            + ", ".join(missing)
        )
    reader.fieldnames = [_normalize_header(name) for name in fieldnames]


def _value(row: dict[str, str | None], name: str, source: str) -> str:
    raw = row.get(name)
    if raw is None or not raw.strip():
        raise TSEDataError(f"{source} has an empty required value in {name}")
    return raw.strip()


def _integer(row: dict[str, str | None], name: str, source: str) -> int:
    value = _value(row, name, source)
    try:
        return int(value)
    except ValueError as error:
        raise TSEDataError(
            f"{source} has a non-integer value for {name}: {value!r}"
        ) from error


def _is_presidential_row(
    row: dict[str, str | None],
    *,
    year: int,
    election_round: int,
) -> bool:
    if _integer(row, "ANO_ELEICAO", "TSE CSV row") != year:
        return False
    if _integer(row, "NR_TURNO", "TSE CSV row") != election_round:
        return False
    if _value(row, "CD_CARGO", "TSE CSV row") != "1":
        return False
    office = unicodedata.normalize(
        "NFKD", _value(row, "DS_CARGO", "TSE CSV row")
    )
    office = "".join(char for char in office if not unicodedata.combining(char))
    return office.casefold() == "presidente"


def _section_key(
    row: dict[str, str | None],
    source: str,
) -> tuple[str, str, int, int]:
    state = _value(row, "SG_UF", source)
    municipality_code = _value(row, "CD_MUNICIPIO", source)
    if not re.fullmatch(r"[A-Z]{2}", state):
        raise TSEDataError(f"{source} has invalid state code: {state!r}")
    try:
        zone_number = int(_value(row, "NR_ZONA", source))
        section_number = int(_value(row, "NR_SECAO", source))
    except ValueError as error:
        raise TSEDataError(f"{source} has a non-integer zone or section number") from error
    if zone_number < 0 or section_number < 0:
        raise TSEDataError(f"{source} has a negative zone or section number")
    return state, municipality_code, zone_number, section_number


def _csv_reader(archive: zipfile.ZipFile, member: zipfile.ZipInfo) -> tuple[TextIO, csv.DictReader[str]]:
    source = archive.open(member, "r")
    text = io.TextIOWrapper(source, encoding="latin-1", newline="")
    return text, csv.DictReader(text, delimiter=";")


def _csv_members(archive: zipfile.ZipFile, archive_path: Path) -> list[zipfile.ZipInfo]:
    members = [
        item
        for item in archive.infolist()
        if not item.is_dir() and item.filename.casefold().endswith(".csv")
    ]
    if not members:
        raise TSEDataError(f"archive contains no CSV files: {archive_path}")
    return members


def _read_section_totals(
    detail_archive_path: Path,
    year: int,
    election_round: int,
) -> dict[tuple[str, str, int, int], _SectionTotals]:
    totals: dict[tuple[str, str, int, int], _SectionTotals] = {}
    with zipfile.ZipFile(detail_archive_path) as archive:
        for member in _csv_members(archive, detail_archive_path):
            text, reader = _csv_reader(archive, member)
            try:
                _required_columns(reader, DETAIL_FIELDS, member.filename)
                for row_number, row in enumerate(reader, start=2):
                    if not _is_presidential_row(
                        row, year=year, election_round=election_round
                    ):
                        continue
                    source = f"{member.filename}:{row_number}"
                    key = _section_key(row, source)
                    eligible = _integer(row, "QT_APTOS", source)
                    present = _integer(row, "QT_COMPARECIMENTO", source)
                    abstentions = _integer(row, "QT_ABSTENCOES", source)
                    valid = _integer(row, "QT_VOTOS_NOMINAIS", source)
                    blank = _integer(row, "QT_VOTOS_BRANCOS", source)
                    null = _integer(row, "QT_VOTOS_NULOS", source)
                    if min(eligible, present, abstentions, valid, blank, null) < 0:
                        raise TSEDataError(f"{source} contains a negative vote total")
                    if present > eligible or valid > present:
                        raise TSEDataError(
                            f"{source} has impossible eligible/present/valid totals"
                        )
                    if key in totals:
                        raise TSEDataError(
                            f"duplicate presidential section in detail files: {key}"
                        )
                    totals[key] = _SectionTotals(
                        state=key[0],
                        municipality_code=key[1],
                        zone_number=key[2],
                        section_number=key[3],
                        eligible_voters=eligible,
                        voters_present=present,
                        abstentions=abstentions,
                        valid_votes=valid,
                        blank_votes=blank,
                        null_votes=null,
                    )
            finally:
                text.close()

    if not totals:
        raise TSEDataError(
            f"no presidential detail rows found for {year}, round {election_round}"
        )
    return totals


def _write_section_totals(
    path: Path,
    totals: dict[tuple[str, str, int, int], _SectionTotals],
    year: int,
    election_round: int,
) -> int:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=SECTION_OUTPUT_FIELDS)
        writer.writeheader()
        for key in sorted(totals):
            section = totals[key]
            writer.writerow(
                {
                    "election_year": year,
                    "election_round": election_round,
                    "state": section.state,
                    "municipality_code": section.municipality_code,
                    "zone_number": section.zone_number,
                    "section_number": section.section_number,
                    "eligible_voters": section.eligible_voters,
                    "voters_present": section.voters_present,
                    "abstentions": section.abstentions,
                    "valid_votes": section.valid_votes,
                    "blank_votes": section.blank_votes,
                    "null_votes": section.null_votes,
                }
            )
    return len(totals)


def _publish_normalized_pair(
    temporary_sections: Path,
    sections_path: Path,
    temporary_candidates: Path,
    candidates_path: Path,
) -> None:
    targets = (sections_path, candidates_path)
    backups: dict[Path, Path] = {}
    published: set[Path] = set()
    try:
        for target in targets:
            if target.exists():
                backup = target.with_name(
                    f"{target.name}.{uuid.uuid4().hex}.bak"
                )
                try:
                    shutil.copy2(target, backup)
                except OSError:
                    backup.unlink(missing_ok=True)
                    raise
                backups[target] = backup

        for source, target in (
            (temporary_sections, sections_path),
            (temporary_candidates, candidates_path),
        ):
            source.replace(target)
            published.add(target)
    except OSError as error:
        rollback_errors: list[str] = []
        for target in reversed(targets):
            backup = backups.get(target)
            try:
                if backup is not None:
                    os.replace(backup, target)
                elif target in published:
                    target.unlink(missing_ok=True)
            except OSError as rollback_error:
                rollback_errors.append(f"{target}: {rollback_error}")
        if rollback_errors:
            preserved = [
                str(path) for path in backups.values() if path.exists()
            ]
            raise TSEDataError(
                "failed to publish normalized outputs and rollback was incomplete: "
                + "; ".join(rollback_errors)
                + (f"; preserved backup(s): {', '.join(preserved)}" if preserved else "")
            ) from error
        raise TSEDataError(
            "failed to publish normalized outputs; previous files were restored"
        ) from error
    else:
        for backup in backups.values():
            backup.unlink(missing_ok=True)


def normalize_archives(
    presidential_archive_path: Path,
    detail_archive_path: Path,
    *,
    year: int,
    election_round: int,
    output_dir: Path,
) -> NormalizationInfo:
    """Normalize TSE ZIP data into section totals and candidate votes CSVs."""
    if election_round not in (1, 2):
        raise ValueError("election_round must be 1 or 2")
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"president_{year}_round_{election_round}"
    sections_path = output_dir / f"{stem}_sections.csv"
    candidates_path = output_dir / f"{stem}_candidate_votes.csv"
    temporary_sections = sections_path.with_name(sections_path.name + ".part")
    temporary_candidates = candidates_path.with_name(candidates_path.name + ".part")
    candidate_vote_sums: dict[tuple[str, str, int, int], int] = {}
    candidate_rows = 0
    election_codes: set[str] = set()

    try:
        totals = _read_section_totals(detail_archive_path, year, election_round)
        section_rows = _write_section_totals(
            temporary_sections, totals, year, election_round
        )
        with zipfile.ZipFile(presidential_archive_path) as archive:
            members = _csv_members(archive, presidential_archive_path)
            with temporary_candidates.open(
                "w", encoding="utf-8", newline=""
            ) as output:
                writer = csv.DictWriter(output, fieldnames=CANDIDATE_OUTPUT_FIELDS)
                writer.writeheader()
                for member in members:
                    text, reader = _csv_reader(archive, member)
                    try:
                        _required_columns(reader, CANDIDATE_FIELDS, member.filename)
                        for row_number, row in enumerate(reader, start=2):
                            if not _is_presidential_row(
                                row, year=year, election_round=election_round
                            ):
                                continue
                            source = f"{member.filename}:{row_number}"
                            election_codes.add(_value(row, "CD_ELEICAO", source))
                            candidate_id = (row.get("SQ_CANDIDATO") or "").strip()
                            if not candidate_id.isdecimal() or int(candidate_id) == 0:
                                continue
                            key = _section_key(row, source)
                            section = totals.get(key)
                            if section is None:
                                raise TSEDataError(
                                    f"candidate result has no section-detail row "
                                    f"for {key} at {source}"
                                )
                            ballot_number = _value(row, "NR_VOTAVEL", source)
                            if not ballot_number.isdecimal():
                                raise TSEDataError(
                                    f"{source} has invalid candidate ballot number "
                                    f"{ballot_number!r}"
                                )
                            votes = _integer(row, "QT_VOTOS", source)
                            if votes < 0 or votes > section.valid_votes:
                                raise TSEDataError(
                                    f"{source} has candidate votes outside the "
                                    "section valid-vote total"
                                )
                            writer.writerow(
                                {
                                    "election_year": year,
                                    "election_round": election_round,
                                    "state": key[0],
                                    "municipality_code": key[1],
                                    "zone_number": key[2],
                                    "section_number": key[3],
                                    "candidate_id": candidate_id,
                                    "ballot_number": ballot_number,
                                    "candidate_name": _value(
                                        row, "NM_VOTAVEL", source
                                    ),
                                    "candidate_votes": votes,
                                }
                            )
                            candidate_vote_sums[key] = (
                                candidate_vote_sums.get(key, 0) + votes
                            )
                            candidate_rows += 1
                    finally:
                        text.close()

        if not election_codes:
            raise TSEDataError(
                f"no presidential candidate rows found for {year}, round {election_round}"
            )
        if len(election_codes) != 1:
            raise TSEDataError(
                "presidential archive contains multiple election codes for the "
                f"selected year/round: {', '.join(sorted(election_codes))}"
            )
        mismatches = [
            (key, section.valid_votes, candidate_vote_sums.get(key, 0))
            for key, section in totals.items()
            if section.valid_votes != candidate_vote_sums.get(key, 0)
        ]
        if mismatches:
            sample = mismatches[0]
            raise TSEDataError(
                "candidate vote sums do not match QT_VOTOS_NOMINAIS for "
                f"{len(mismatches)} section(s); first mismatch {sample[0]}: "
                f"detail={sample[1]}, candidates={sample[2]}"
            )

        _publish_normalized_pair(
            temporary_sections,
            sections_path,
            temporary_candidates,
            candidates_path,
        )
    except (OSError, zipfile.BadZipFile, csv.Error) as error:
        raise TSEDataError(f"failed normalizing TSE section archives: {error}") from error
    finally:
        temporary_sections.unlink(missing_ok=True)
        temporary_candidates.unlink(missing_ok=True)

    return NormalizationInfo(
        sections_path=sections_path,
        candidates_path=candidates_path,
        section_rows=section_rows,
        candidate_rows=candidate_rows,
    )


def _write_manifest(
    manifest_path: Path,
    *,
    year: int,
    election_round: int,
    resources: tuple[CatalogResource, CatalogResource],
    downloads: tuple[DownloadInfo, DownloadInfo],
    normalized: NormalizationInfo,
) -> None:
    manifest = {
        "schema_version": 1,
        "source": "Tribunal Superior Eleitoral (TSE) Dados Abertos CKAN",
        "catalog_api": CKAN_API,
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
        "election_year": year,
        "election_round": election_round,
        "normalized_files": {
            "sections": {
                "path": str(normalized.sections_path),
                "rows": normalized.section_rows,
            },
            "candidate_votes": {
                "path": str(normalized.candidates_path),
                "rows": normalized.candidate_rows,
            },
        },
        "resources": [
            {
                "package_name": resource.package_name,
                "package_id": resource.package_id,
                "resource_id": resource.resource_id,
                "name": resource.name,
                "url": resource.url,
                "archive_path": str(download.path),
                "archive_size_bytes": download.size_bytes,
                "archive_sha256": download.sha256,
                "reused_cached_archive": download.reused,
            }
            for resource, download in zip(resources, downloads, strict=True)
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_name(manifest_path.name + ".part")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            json.dump(manifest, output, ensure_ascii=False, indent=2)
            output.write("\n")
        temporary.replace(manifest_path)
    finally:
        temporary.unlink(missing_ok=True)


def fetch_tse_section_results(
    year: int,
    election_round: int,
    *,
    output_dir: Path,
    refresh: bool = False,
    max_archive_bytes: int = MAX_ARCHIVE_BYTES,
    progress_callback: (
        Callable[[CatalogResource, int, int | None], None] | None
    ) = None,
) -> FetchInfo:
    """Download official TSE archives and produce normalized CSVs and manifest."""
    if election_round not in (1, 2):
        raise ValueError("election_round must be 1 or 2")
    presidential_resource, detail_resource = discover_resources(year)
    raw_dir = output_dir / "raw" / str(year)
    presidential_path = raw_dir / f"votacao_secao_{year}_BR.zip"
    detail_path = raw_dir / f"detalhe_votacao_secao_{year}.zip"
    downloads_list: list[DownloadInfo] = []
    for resource, path in (
        (presidential_resource, presidential_path),
        (detail_resource, detail_path),
    ):
        callback = None
        if progress_callback is not None:
            callback = lambda downloaded, total, selected=resource: progress_callback(
                selected, downloaded, total
            )
        downloads_list.append(
            download_archive(
                resource,
                path,
                refresh=refresh,
                max_bytes=max_archive_bytes,
                progress_callback=callback,
            )
        )
    downloads = (downloads_list[0], downloads_list[1])
    normalized = normalize_archives(
        presidential_path,
        detail_path,
        year=year,
        election_round=election_round,
        output_dir=output_dir / "processed",
    )
    manifest_path = (
        output_dir / "processed" / f"president_{year}_round_{election_round}_manifest.json"
    )
    _write_manifest(
        manifest_path,
        year=year,
        election_round=election_round,
        resources=(presidential_resource, detail_resource),
        downloads=downloads,
        normalized=normalized,
    )
    return FetchInfo(
        year=year,
        election_round=election_round,
        sections_path=normalized.sections_path,
        candidates_path=normalized.candidates_path,
        manifest_path=manifest_path,
        section_rows=normalized.section_rows,
        candidate_rows=normalized.candidate_rows,
        reused_archives=sum(download.reused for download in downloads),
    )
