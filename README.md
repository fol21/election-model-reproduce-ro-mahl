# Synthetic TSE-Inspired Election Model

This repository contains a **synthetic election-estimation demo** and an
explicit TSE data downloader. The estimator still runs only on synthetic data;
the separate downloader retrieves official presidential section result
archives and writes normalized files. Downloaded data is not yet wired into
the estimator, and the synthetic output is not an election forecast.

The background description supplied for this project cited the following
reporting and official data portal. They informed the high-level motivation and
future integration boundary; they are not sources for the prototype's
synthetic numbers or a complete specification of its code.


   > Estadão, “[Modelo estatístico usado pelo Estadão antecipou resultado com apenas 2,42% das urnas apuradas](https://www.estadao.com.br/politica/eleicoes/modelo-estatistico-usado-pelo-estadao-antecipou-resultado-com-apenas-242-das-urnas-apuradas/).”
   >Reporting on the projection, prior-election comparison, systematic voting changes, and geographic/municipality-size factors.

## Requirements

- Python 3.14 or newer
- NumPy 2.3 or newer and below 3 (installed with the project)

The current implementation is sequential. It does not require the free-threaded
Python build and does not attempt parallel execution.

## Install

From the project directory in PowerShell:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

## Run the synthetic demo

```powershell
python -m election_model_reproduce_ro_mahl
```

Or, after installation:

```powershell
election-model --seed 42 --reported-fraction 0.30
```

`--reported-fraction` is the share sampled within the synthetic early-reporting
strata (small municipalities and municipalities in RJ); it is not the share of
all sections. Use `--help` to see the available options. The program labels all
output as synthetic and prints the simulated final result only to evaluate the
projection.

## Download official TSE section results

The TSE downloader is a separate, explicit command. It looks up the selected
year in the TSE Open Data CKAN catalog, downloads the presidential
“Votação por seção eleitoral” archive and “Detalhe da apuração por seção
eleitoral” archive, then writes normalized CSV files and a provenance manifest.
For example:

```powershell
tse-fetch --year 2022 --round 1
tse-fetch --year 2022 --round 2
```

Or run it from the source tree after installing the project:

```powershell
python -m election_model_reproduce_ro_mahl.tse_cli --year 2022 --round 1
```

For another election year (for example 2026), change `--year`. The catalog must
publish both required resources for that year and round. Files are stored under
`data/tse/` (ignored by Git):

- `raw/<year>/` contains the original TSE ZIP archives.
- `processed/president_<year>_round_<round>_sections.csv` contains one row per
  section with eligible voters, attendance, abstentions, and valid/blank/null
  vote counts.
- `processed/president_<year>_round_<round>_candidate_votes.csv` contains
  candidate vote counts by section.
- `processed/president_<year>_round_<round>_manifest.json` records catalog
  resource IDs and URLs, retrieval time, file sizes, and SHA-256 checksums.

The source archives are large (hundreds of megabytes each). Existing valid
archives are reused; pass `--refresh` to download the current catalog files
again. The downloader streams ZIP members without extracting the full
uncompressed archives. It performs network access only when explicitly run.
This fetches catalog archives, not a live polling feed; the estimator is not yet
connected to the downloaded CSVs.

See [docs/tse-data.md](docs/tse-data.md) for field mappings, validation, and
limitations.

## Run tests

```powershell
python -m unittest discover -s tests -v
```

## What the model does

1. Generates a deterministic synthetic 2022 first-round baseline with
   section-level keys and municipality-size categories.
2. Generates synthetic 2026 first-round outcomes with known state and
   municipality-size swings.
3. Marks a biased subset as reported, favoring small municipalities and RJ.
4. Fits a valid-vote-weighted least-squares regression to reported changes in
   candidate vote share.
5. Applies predicted swings to unreported historical shares and aggregates the
   observed plus projected vote totals.

See [docs/methodology.md](docs/methodology.md) for field definitions, estimator
details, limitations, and the planned real-data boundary.

## Repository status

The synthetic estimation demo, TSE archive downloader, and normalized files are
separate. No live polling, dashboards, real candidate mappings for the model,
turnout-change model, or concurrency are implemented. Read the limitations
before interpreting any numerical output.
