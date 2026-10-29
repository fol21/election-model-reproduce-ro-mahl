# Methodology and Data Boundary

## Purpose and limits

The estimator demo demonstrates one possible section-level swing-estimation
workflow, motivated by public reporting about Rodrigo Mahlmeister's election
projection model [1][2][3]. Its records and outcomes are generated locally from
a pseudorandom seed. A separate, explicit downloader retrieves official TSE
presidential section-result archives and normalizes them, but those downloaded
files are not yet connected to the estimator. Do not treat synthetic output as
real election results or as a forecast.

The cited articles describe the approach at a high level; they do not provide
the original source code or a complete specification. The regression,
synthetic effects, and data generator below are this prototype's illustrative
choices, not a reconstruction of Mahlmeister's exact model. The normalized
data fields are derived from TSE's current CSV columns; they are not claimed to
be a complete or canonical TSE schema.

The synthetic 2022 baseline and 2026 first-round outcome are deliberately
constructed with known state and municipality-size effects. This gives tests a
known answer, but it does not demonstrate that the same model would be accurate
on real election data.

## Record shape

Each section is keyed by:

- `state`
- `municipality_code`
- `zone_number`
- `section_number`

Baseline and outcome records also include election year and round, candidate
identifier, and vote totals. Baseline records include eligible voters and
historical valid votes so the generator can derive a simple historical turnout
rate. The current simulated outcome stores valid and candidate votes. The
simulation keeps complete outcomes for scoring tests; the estimator receives
only the subset marked reported.

## Estimation steps

For each reported section \(i\), compute its candidate share change:

\[
\Delta_i =
\frac{\text{candidate votes}_{i,\text{current}}}
     {\text{valid votes}_{i,\text{current}}}
-
\frac{\text{candidate votes}_{i,\text{baseline}}}
     {\text{valid votes}_{i,\text{baseline}}}
\]

The cited descriptions compare results with the same location in a prior
election and use systematic changes, location, and municipality size to project
unreported sections [1][2]. This prototype illustrates that idea by fitting a
weighted additive linear model with an intercept and indicator variables for
state and municipality-size category. The least-squares fit weights each
reported section by its observed current valid-vote count. Apply each predicted
swing to the section's historical candidate share, clipping the result to
\([0,1]\). This specific formula and weighting choice are not claimed to be
the source model's implementation.

Reported candidate and valid votes are included as observed. For unreported
sections, this prototype carries forward the section's historical turnout rate
and multiplies it by the baseline eligible-voter count to get an expected valid
vote weight. Predicted candidate votes are the projected candidate share times
that expected valid-vote weight. The final national share is the sum of observed
and projected candidate votes divided by the corresponding total valid-vote
weight.

The synthetic simulation also prints the known complete-election share as
evaluation-only information. A real election feed would not provide that truth
for unreported sections.

## Assumptions and limitations

- The additive state and municipality-size effects are known to be simplistic;
  interactions, section-level heterogeneity, and temporal changes are omitted.
- Reported sections are selected with intentional bias. The model attempts to
  account for differences represented in its covariates, but cannot correct
  selection patterns it does not observe.
- The candidate identifier is held constant across baseline and simulated
  election. Real elections require explicit candidate/party mapping across
  years.
- Unreported turnout is assumed to match the historical section turnout rate.
  No turnout-change model is fit.
- Small section counts, unseen categories, data corrections, new/renumbered
  sections, invalid result rows, and operational feed delays require additional
  handling before real-data use.
- Linear predictions are clipped to valid share bounds; this does not make the
  statistical model probabilistically calibrated.
- The simulation is deterministic for a fixed seed, not a forecast or
  validation against actual elections.

## TSE data retrieval and remaining integration boundary

A separate command now retrieves the official resources listed in the TSE
CKAN package `resultados-{year}` [4]:

- `Presidente - Votação por seção eleitoral - {year}` contains presidential
  candidate vote counts, identified by section and candidate.
- `Detalhe da apuração por seção eleitoral` contains section-level eligible
  voters, attendance, abstentions, and vote totals. The archive is split among
  CSV members by geographic unit.

The downloader saves the ZIP files under `data/tse/raw/{year}/` and streams
their CSV members to avoid extracting the multi-gigabyte uncompressed archives.
It writes separate normalized section-total and candidate-vote CSVs, plus a
manifest with source URLs/resource IDs, retrieval time, archive sizes, and
SHA-256 checksums. Candidate nominal-vote sums are checked against the
section-level `QT_VOTOS_NOMINAIS`; malformed data, missing sections, or
mismatches stop processing rather than producing a success-shaped output.
Downloads are cached; `--refresh` requests the current catalog files again.

The downloadable archives are periodic snapshots, not a live polling feed.
The estimator still uses synthetic records. Before connecting real data, the
project still needs explicit candidate mapping across elections, municipality
size categories, missing/renumbered section reconciliation, identification of
partial/unreported sections, and tests comparing the adapter with the model's
input contract. Historical turnout modeling, uncertainty intervals, robust or
hierarchical regressions, monitoring, and concurrency also need separate
design and validation before use.

## References and provenance

The background description supplied for this project cited the following
reporting and official data portal. They informed the high-level motivation and
future integration boundary; they are not sources for the prototype's
synthetic numbers or a complete specification of its code.

1. Estadão, “[Modelo estatístico usado pelo Estadão antecipou resultado com
   apenas 2,42% das urnas apuradas](https://www.estadao.com.br/politica/eleicoes/modelo-estatistico-usado-pelo-estadao-antecipou-resultado-com-apenas-242-das-urnas-apuradas/).”
   Reporting on the projection, prior-election comparison, systematic voting
   changes, and geographic/municipality-size factors.
2. GZH, “[Essa eleição marca um novo jeito de acompanhar a apuração, diz
   criador de modelo que cravou vitória de Lula](https://gauchazh.clicrbs.com.br/politica/eleicoes/noticia/2026/10/essa-eleicao-marca-um-novo-jeito-de-acompanhar-a-apuracao-diz-criador-de-modelo-que-cravou-vitoria-de-lula-cmvpo0qhu004301ed1sak345o.html).”
   Interview describing comparisons with previous elections and applying
   learned patterns to pending sections.
3. NeoFeed, “[Como um pesquisador brasileiro criou um algoritmo que simulou e
   acertou o resultado do 1º turno](https://neofeed.com.br/finde/como-um-pesquisador-brasileiro-criou-um-algoritmo-que-simulou-e-acertou-o-resultado-do-1o-turno/).”
   Reporting on the distinction from opinion polling, use of historical
   results, and swing/regression concepts.
4. Tribunal Superior Eleitoral (TSE), [Dados Abertos — Resultados
   eleitorais](https://dadosabertos.tse.jus.br/). Official portal listing
   election-results datasets, including results by electoral section. Listed
   as a future data source only; this prototype did not download or use its
   data.

Links consulted on 2026-10-28.
