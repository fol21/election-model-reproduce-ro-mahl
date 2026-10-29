# TSE Data Downloader

## What it downloads

The command queries the official TSE Open Data CKAN API at
`https://dadosabertos.tse.jus.br/api/3/action/package_show` for the
`resultados-{year}` dataset. It selects two resources:

1. `Presidente - Votação por seção eleitoral - {year}` — candidate voting
   results for the presidential election, including all UFs and `ZZ`.
2. `Detalhe da apuração por seção eleitoral` — section-level electorate,
   attendance, abstention, and vote totals. The ZIP contains multiple CSV
   members.

The downloader accepts only HTTPS catalog/CDN URLs hosted at
`dadosabertos.tse.jus.br` or `cdn.tse.jus.br`. It never runs automatically as
part of the synthetic demo.

## Usage

Install the project first, then choose the election year and round:

```powershell
tse-fetch --year 2022 --round 1
tse-fetch --year 2022 --round 2
```

The source-tree equivalent is:

```powershell
python -m election_model_reproduce_ro_mahl.tse_cli --year 2022 --round 1
```

The downloader creates `data/tse/raw/{year}/` for original ZIP archives and
`data/tse/processed/` for normalized outputs. It reuses existing valid ZIP
archives. Use `--refresh` to download the current archive versions again, or
`--output-dir` to choose another data directory. `--max-archive-mb` limits the
size accepted for each ZIP; the default is 2,000 MB.

The archives are large. At inspection on 2026-10-28, the TSE presidential
section-voting ZIP was approximately 271 MB for 2022 and 242 MB for 2026; the
section-detail ZIPs were approximately 244 MB and 234 MB, respectively. Sizes
may change when the TSE updates a resource. CSV members are streamed directly
from the ZIP without extracting the uncompressed archives.

## Output files

- `president_{year}_round_{round}_sections.csv`: one row per TSE section
  present in the presidential detail data.
- `president_{year}_round_{round}_candidate_votes.csv`: one row for each
  candidate result in a section.
- `president_{year}_round_{round}_manifest.json`: catalog/package and resource
  IDs, source URLs, retrieval timestamp, archive sizes, SHA-256 checksums,
  normalized output paths, and row counts.

The section file maps TSE columns as follows:

| Normalized field | TSE source column |
|---|---|
| `election_year` | `ANO_ELEICAO` |
| `election_round` | `NR_TURNO` |
| `state` | `SG_UF` |
| `municipality_code` | `CD_MUNICIPIO` |
| `zone_number` | `NR_ZONA` |
| `section_number` | `NR_SECAO` |
| `eligible_voters` | `QT_APTOS` |
| `voters_present` | `QT_COMPARECIMENTO` |
| `abstentions` | `QT_ABSTENCOES` |
| `valid_votes` | `QT_VOTOS_NOMINAIS` |
| `blank_votes` | `QT_VOTOS_BRANCOS` |
| `null_votes` | `QT_VOTOS_NULOS` |

The candidate-vote file maps `SQ_CANDIDATO`, `NR_VOTAVEL`, `NM_VOTAVEL`, and
`QT_VOTOS` to `candidate_id`, `ballot_number`, `candidate_name`, and
`candidate_votes`. Candidate IDs remain strings to preserve source identity.

## Validation and limitations

The importer filters on the requested year and round and the presidential
office. It rejects missing required columns, invalid numeric totals, duplicate
section-detail records, candidate results without matching section details,
and per-section candidate vote sums that do not equal TSE's nominal-vote
totals. It does not fetch results by polling the live TSE system; it fetches
the current catalog archives, which are snapshots and may only be updated
periodically.

The normalized files are **not yet wired into the synthetic estimator**.
Candidate cross-election mapping, municipality-size covariates, and handling
for partial, newly created, or renumbered sections remain future work.

