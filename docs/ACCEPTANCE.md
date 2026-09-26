# First-batch implementation and acceptance

Checkpoint: 2026-09-26. Organic cases ORG-01 through ORG-12 and relaxation cases
REL-01 through REL-14 remain one joint first batch. This document records
implemented behavior, bounded verification and outstanding acceptance separately;
it does not declare the whole batch scientifically accepted or delivered through
every host. Private course references and real input files are not public fixtures.

## Evidence layers

| Layer | Evidence and boundary |
| --- | --- |
| Numerical core | Analytic integration, FFT, phase and baseline fixtures; explicit yield bookkeeping; signed T1/T2 recovery, independently profiled weighted fitting, covariance and identifiability diagnostics in [test_numerics.py](../tests/test_numerics.py). These are controlled numerical tests. |
| Shared project | Atomic revisions, request reconciliation, conflicts, rollback, transitive stale state, undo, named-revision export and reopening in [test_project.py](../tests/test_project.py), [test_batch_evidence.py](../tests/test_batch_evidence.py) and [test_migration.py](../tests/test_migration.py). |
| Evidence workflows | Samples, candidate structures, normalization, recovered material, supplied uncertainty, DEPT matching, reference annotations and condition comparison have focused coverage in [test_batch_science.py](../tests/test_batch_science.py) and [test_batch_evidence.py](../tests/test_batch_evidence.py). These fixtures validate data handling and specified calculations, not a real structure determination. |
| Import | Qualified 1D and processed 2D fixtures, original-byte preservation and explicit unsupported/unsafe-input rejection in [test_formats.py](../tests/test_formats.py), [test_processed_2d.py](../tests/test_processed_2d.py) and [test_joint_import.py](../tests/test_joint_import.py). Real-input evidence below has a narrower scope than general instrument support. |
| Export | Named-revision JSON, CSV, PNG/SVG figures, preserved originals and a reopenable database with prior history. [Review regressions](../tests/test_review_regressions.py) cover stale analysis provenance, reserved source-column collisions and sample roles in fit figures. Archive construction/readback is separate from a host delivering the files. |
| Protocol and HTTP | A real Windows MCP subprocess exercises discovery, calls, structured failures, resource bytes and EOF. Loopback HTTP tests cover authentication, Host/Origin checks, shared state, reference preview bounds and explicit shutdown: [protocol](../tests/test_protocol.py), [reference HTTP](../tests/test_reference_http.py). This is protocol evidence, not installation in every named host. |
| Workbench | Labelled forms and editable spectrum, structure, correlation and annotation views are implemented. [Frontend checks](../tests/frontend/) cover geometry, signed display extrema and explicit import selection. Actual browser checkpoints are recorded separately below. |
| Package lifecycle | [Packaging tests](../tests/test_packaging.py) cover integrity, upgrade, rollback, recovery, launcher locks, preserved user data and guarded removal. Test fixtures and source builds do not establish a fresh installed runtime, clean-device acceptance or a published release. |
| Native software | The independent core does not require native Mnova. No native Mnova acceptance is inferred here. |

The complete local science, UI and delivery checkpoint completed Ruff, **259
passing Python tests and 3 platform skips** (82.31 seconds), 12 passing Node tests,
and wheel/sdist builds. A subsequent packaging-only correction adds the SQLite
notice to tracked source and rejects ignored or untracked build inputs before
downloading the runtime; its six focused checks pass. Exact release-commit CI
results are recorded separately in the release evidence.
The three skipped cases require creating Windows file symlinks without the
necessary privilege. A separate actual Windows directory-junction check rejected
reparse delivery before writing; it does not substitute for those three cases.
[Delivery tests](../tests/test_export_delivery.py) verify explicit historical
revision export, original-byte/hash readback, database reopening, non-overwrite
behavior and structured path errors. Empty-result export provenance is covered by
[review regressions](../tests/test_review_regressions.py).

These are source and current-device checkpoints. The immutable source cannot
record tests that occur after its package is built. The versioned
[0.2.0-alpha.1 release](https://github.com/saigyujikingyo-png/nmr-companion/releases/tag/v0.2.0-alpha.1)
provides the subsequent `release-evidence.json` for actual package, installation,
host/model and file-delivery results. Earlier dated evidence remains in the
[development receipt](DEVELOPMENT_RECEIPT.md) and [workbench record](WORKBENCH_UI.md).

## Organic cases

| Case | Implemented behavior | Bounded evidence | Remaining acceptance |
| --- | --- | --- | --- |
| ORG-01 | Import qualified raw and processed 1H/13C data with nucleus, axis, units, processing stage and originals; reject double FFT and unsupported representations. Explicit Bruker processing selection preserves unselected originals. | [Format fixtures](../tests/test_formats.py), [processing-selection fixtures](../tests/test_processed_2d.py), [stage guards](../tests/test_project.py); the real 1H Bruker checkpoint below. | Wider real instrument/processing corpus, including 13C, and quantitative/reference qualification. The single archive does not qualify every captured processing profile. |
| ORG-02 | Edit signed full-resolution integrals and manual peak labels with stable identities; calculate relative proton counts from an explicit positive reference on the same 1H spectrum without rescaling spectra. | [Numerical integration](../tests/test_numerics.py), [normalization and label edits](../tests/test_batch_evidence.py), [frontend geometry](../tests/frontend/); a peak-label save occurred in the current browser checkpoint. | Complete the current human/agent roundtrip for normalization and edits on accepted data; display checks alone do not establish quantitative accuracy. |
| ORG-03 | Require explicit standard and limiting-reactant amounts, proton counts and usable product/standard regions; reject missing inputs, invalid amounts, incompatible spectra and overlapping selected regions. | [Invalid yield inputs](../tests/test_numerics.py), [atomic failure checks](../tests/test_project.py); operation schemas retain required inputs. | User review of signal separation and usable regions on real quantitative spectra. No automatic deconvolution or assumed equimolarity. |
| ORG-04 | Calculate yield, recovered starting material and combined material balance from explicit amounts, proton counts and stoichiometry; propagate supplied standard uncertainties, including shared-standard covariance. | [Yield/recovery fixture](../tests/test_batch_science.py), [independent yield bookkeeping](../tests/test_numerics.py); missing uncertainty remains unavailable. | Real standards, acquisition adequacy and preparation/systematic uncertainty assessment; synthetic values are not experimental results. |
| ORG-05 | Keep own/reference/synthetic/unknown sample roles, dataset associations and candidate evidence distinct; carry associated sample roles into exports. | [Sample/candidate links](../tests/test_batch_evidence.py), [reference preservation](../tests/test_batch_science.py), [fit-figure provenance](../tests/test_review_regressions.py). | Curated review of a real product/reference comparison and whether the observations support each proposed structure. |
| ORG-06 | Retain parent samples, transformation and stage context; edit atoms, bonds, stereochemical labels and alternative candidates with explicit proposed/confirmed status. | [Diol/acetal context and alternative-candidate fixture](../tests/test_batch_science.py), [atom-selection geometry](../tests/frontend/batch.test.cjs); a candidate was saved in the browser checkpoint. | Curated stereochemical interpretation. Stored R/S labels and wedge/hash drawings do not establish stereochemistry or perform automatic CIP assignment. |
| ORG-07 | Match signed DEPT-135 observations to 13C peaks using explicit prominence, tolerance and phase convention; retain proposed interpretations and flag ambiguity in either matching direction. | [Signed DEPT fixture](../tests/test_batch_science.py), [two carbon peaks competing for one DEPT peak](../tests/test_review_regressions.py). | Verify the real acquisition, phase and reference convention and review applicability. Absence of a matched DEPT signal alone does not prove a quaternary carbon. |
| ORG-08 | Import qualified processed COSY/HSQC grids, including 13C and 15N HSQC; retain explicit x/y nuclei, signed intensities and row/column identity; view and edit crosspeaks linked to original points. | [Processed-grid fixtures](../tests/test_processed_2d.py), [reversed-axis and signed-rendering geometry](../tests/frontend/batch.test.cjs); two signed HSQC crosspeaks were saved in the live browser and independently read back. | Real processed 2D profiles, reference accuracy and chemical correlation review. Raw multidimensional processing is outside this profile. |
| ORG-09 | Preserve PDF/image originals and own/reference/category provenance; preview pages and save normalized rectangles, observations and explicitly approximate ppm readings with optional reading uncertainty. | [Reference and export fixture](../tests/test_batch_science.py), [authenticated page checks](../tests/test_reference_http.py), [rectangle geometry](../tests/frontend/batch.test.cjs); PDF annotation saved in the current browser checkpoint. | Review readings against actual reference pages and verify delivered previews. Images are never converted into invented numeric spectra or quantitative integrals. |
| ORG-10 | Create, revise and remove assignments linking saved samples, candidates, stable atoms, peaks, crosspeaks and annotations; retain alternatives and separate review status from current/stale state. | [Assignment/candidate dependencies](../tests/test_batch_evidence.py), [cycle rejection, alternatives, removal and undo](../tests/test_batch_science.py); a proposed atom assignment was saved and independently read back after the browser session. | Complete the graphical revision/removal lifecycle and curated chemical review; a user-confirmed label records review, not independent chemical proof. |
| ORG-11 | Associate product and intermediate samples with stages and transformations; retain labelled NMR observations and separately supplied IR, HRMS, optical-rotation or other reference attachments. | [Stage/parent and attachment fixtures](../tests/test_batch_science.py), [sample and table export/reopen](../tests/test_batch_evidence.py). | Review representative multistep product workflows and external characterization provenance. Supplied measurements are not relabelled as NMR-derived results. |
| ORG-12 | Mark dependent interpretations and calculations stale after source edits; retain undo, own/reference provenance and one-revision exports with exact originals and editable history. | [Project roundtrips](../tests/test_project.py), [transitive stale state](../tests/test_batch_evidence.py), [stale CSV provenance](../tests/test_review_regressions.py), [migration](../tests/test_migration.py); current browser state independently read back at revision 12. | Complete the extended graphical revision/undo/export roundtrip and verify received files through each supported host. |

## Relaxation cases

| Case | Implemented behavior | Bounded evidence | Remaining acceptance |
| --- | --- | --- | --- |
| REL-01 | Import qualified numeric 1D DX and CSV, preserve original bytes and identities, and bind each trace to an explicitly selected table row, delay column and time unit. | [DX/CSV reader fixtures](../tests/test_formats.py), [independent synthetic paired-series workflow](../tests/test_joint_import.py). | An authorized real benchtop DX/CSV pair with verified encoding, trace identity and actual delay semantics. The real Bruker archive below does not close this gate. |
| REL-02 | Keep import separate from fitting; reject missing tables, invalid row mappings, nonnumeric delays and unknown units instead of inferring delays or truncating a mapping. Extra source rows remain preserved and selection is explicit. | [Mapping rejection](../tests/test_project.py), [malformed CSV/DX fixtures](../tests/test_formats.py), [ambiguous-time checks](../tests/test_numerics.py). | Qualify missing, truncated and excess-row variants from the real benchtop export and their user-visible diagnostics. |
| REL-03 | Convert explicit s/ms/us delays to physical seconds while retaining original units and mapping provenance. | [T1 unit-equivalence fixture](../tests/test_numerics.py), [stored original ms delays](../tests/test_joint_import.py); explicit ms mappings were used in the current live T1 fit. | Verify the real source's unit declaration; no units are inferred from a column name or course example. |
| REL-04 | Preserve input pairing and repeated delays as separate mapped rows; store exclusions without deduplicating replicas. | [Order/replicate numerical fixture](../tests/test_numerics.py), [unsorted imported series with a replicate](../tests/test_joint_import.py). | Review real trace pairing and replicate meaning; display order is not a substitute for recorded identities. |
| REL-05 | Require an explicit elapsed-time or echo-interval convention; echo intervals require a positive declared multiplier before a physical T2 is reported. | [Independent echo conversion](../tests/test_numerics.py), [ambiguous-time rejection](../tests/test_project.py), [imported echo-interval fixture](../tests/test_joint_import.py). | Establish the real CSV variable's acquisition meaning and conversion. No vendor parameter-letter or pulse-diagram inference. |
| REL-06 | Preserve negative, near-zero and positive T1 integrals through full-resolution signed integration and explicit phase/region operations; retain comparable trace amplitudes. | [Signed T1 and processing fixtures](../tests/test_numerics.py), [dependent-fit invalidation](../tests/test_project.py); earlier actual negative-trace/region controls are in the workbench record. | Real common-phase, gain/scan and region comparability. Relative proton normalization is separate and does not normalize relaxation traces. |
| REL-07 | Apply supported FFT/zero-fill/apodization operations only to qualified time-domain input; require complex data for phase correction and retain processing provenance. | [Analytic processing fixtures](../tests/test_numerics.py), [real-only/raw capabilities](../tests/test_formats.py), [processed FFT rejection](../tests/test_project.py). | Real benchtop representation and processing-profile qualification; real-only or unsupported input cannot acquire missing quadrature by inference. |
| REL-08 | Fit explicit three-parameter T1 and T2 models with positive rate, offsets, residuals, weighting, covariance and documented conversion to T and standard uncertainty. | [Controlled-noise, independently profiled rate and covariance tests](../tests/test_numerics.py), [synthetic imported T2 workflow](../tests/test_joint_import.py); current live T1 fit and independent readback gave 0.5 s. | Experimental model adequacy, acquisition comparability and systematic uncertainty; covariance is conditional on the declared model and weights. |
| REL-09 | Report weak identifiability or unavailable T for uninformative data; flag controlled model mismatch and structured residuals. | [Flat/undersampled/short-window and multicomponent fixtures](../tests/test_numerics.py). | Review real overlap, mixtures and sampling. Successful optimization or a high fit statistic does not establish a single-component mechanism. |
| REL-10 | Reject stale revision writes, reconcile request IDs and invalidate source-dependent results without overwriting a newer human edit. Computation is bounded and synchronous. | [Two-frontends/conflict/replay tests](../tests/test_project.py), [HTTP/MCP shared-state tests](../tests/test_protocol.py); earlier actual browser/MCP conflict is recorded separately. | Repeat the relevant live human/agent workflow in each installed host. There is no asynchronous fit-proposal or durable job service. |
| REL-11 | Save mappings, original delays, signs, processing metadata, regions, model parameters, exclusions and result state; reopen the project and exported database with history. | [Project/archive reopen](../tests/test_project.py), [imported series reopen](../tests/test_joint_import.py), [legacy migration](../tests/test_migration.py), [Windows immediate handle-release regressions](../tests/test_review_regressions.py); a second service independently read the live revision-12 project. | Installed-runtime restart and OS-event acceptance, plus the real paired-data roundtrip. |
| REL-12 | Compare explicitly corresponding signals or fit results from declared sample conditions; retain solvent, temperature, additives, reference conventions, units, missing uncertainty and source versions. | [Two-condition T1 fixture, explicit sample association and stale propagation](../tests/test_batch_science.py); labelled comparison controls are implemented. | Curated real condition/signal correspondence, justified uncertainty independence and the live comparison workflow. Automatic cross-sample matching is not claimed. |
| REL-13 | Persist explicit analysis/quick_check purpose and warn on preliminary fits and comparisons that include them. | [Imported quick-check mapping](../tests/test_joint_import.py), [comparison warning](../tests/test_batch_science.py). | An acquisition-metadata profile for automatic preliminary identification remains unqualified. The default analysis label does not certify acquisition quality. |
| REL-14 | Export curves, numerical/mapping tables, original files and an editable project from one named revision, with artifact size/hash and source provenance. | [Archive integrity and history](../tests/test_project.py), [CSV/figure provenance regressions](../tests/test_review_regressions.py), [MCP resource bytes](../tests/test_protocol.py); revision-12 ZIP generation and a separate browser download request occurred. | Actual host file receipt, readable figure/table checks and reopening the delivered archive. The current browser download event timed out and no received file was verified. |

## Real input and browser checkpoints

An authorized private NOMAD 1H Bruker ZIP was imported with an explicit
`bruker_processing_numbers: [1]` selection. The result contained two objects, a
raw FID and a processed 1r spectrum, with 39 originals preserved. The revision-1
archive was exported; its project reopened equal to the saved project, and the
preserved original ZIP was byte-for-byte equal to the input.

Strict default import failed on another captured processing directory, number
700, because its `SW_p` was invalid. Explicitly selecting number 1 retained that
unselected directory's original bytes without decoding or qualifying it. This is
real-data evidence for the selected 1H Bruker import, preservation and project
roundtrip only. It is not a benchtop DX/CSV pair, quantitative yield validation,
relaxation acquisition, processed 2D qualification or chemical interpretation.
Private filenames, accounts, paths and hashes remain outside public source.

The current live in-app browser session used a separate synthetic project. It
saved samples, a candidate structure, peak labels and a PDF annotation through
revision 7, then imported a 129-column by 81-row HSQC grid and saved crosspeaks at
(2, 30) ppm and (7, 60) ppm, with original-point intensities approximately 9.6666
and -7.82826. A C1/H-a assignment remained proposed. Eight explicit ms delay
mappings and a shared integral region produced T1 = 0.5 s.

A second service instance independently read revision 12 with nine spectra, one
grid, one fit, one sample, one structure, two crosspeaks, one assignment, one PDF
attachment and one annotation. This is saved-state and numerical readback evidence
for the synthetic workflow. Earlier live 1D/relaxation checks appear in the dated
[workbench record](WORKBENCH_UI.md); frontend unit tests are separate evidence.

The UI generated the revision-12 ZIP, and a separate click requested its download.
The in-app browser download event timed out after ten seconds, and no matching
file was found in the standard Downloads location. Actual browser file delivery
and reopening of that received file remain unconfirmed. Archive generation is
not recorded as delivery success.

## Independent completion gates

| Gate | Status at this checkpoint |
| --- | --- |
| Real benchtop DX/CSV | Open. Obtain an authorized representative pair and verify actual encoding, trace pairing, units, echo semantics, comparable amplitudes, processing and scientific results. |
| Curated chemistry review | Open. Review real own/reference evidence, assignments, alternatives, stereochemical context, DEPT applicability, 2D correlations and quantitative signal selection. Schema and synthetic fixtures do not close this gate. |
| Experimental relaxation review | Open. Establish real acquisition purpose, referencing/scaling, region correspondence, model adequacy and uncertainty limits. |
| Windows package/runtime | Source checks and wheel/sdist builds are complete at this checkpoint. Installed execution, bundled-package integrity, install/upgrade/rollback/reopen and clean-device/OS-event evidence need their own versioned record. No installed-package PASS is asserted here. |
| Cloud | Templates and local checks do not establish a saved cloud environment. Actual environment creation/setup, container checks, execution model/effort and cloud artifact delivery remain separate gates. |

Installed-host compatibility requires both an actual tool workflow and a received,
readable artifact. A configured adapter, protocol test or download initiation is
insufficient. At this checkpoint the following host-specific claims are not yet
established for the completed batch:

| Host | Installed integration | Actual model/effort | File delivery and reopen |
| --- | --- | --- | --- |
| ChatGPT Chat | Not established | Not recorded | Not established |
| ChatGPT local Work | Not established | Not recorded | Not established |
| ChatGPT cloud Work | Saved environment and integration not established | Not recorded | Not established |
| Codex | Generic MCP and in-app browser evidence do not establish installed product integration | Product-use model/effort not recorded | Not established |
| Claude | Not established | Not recorded | Not established |
| WorkBuddy | Not established | Not recorded | Not established |

The GPT-5.6 Terra/max benchmark needs its own availability and execution evidence;
no other model or task title substitutes for that claim. Existing native-software
and unrelated host incidents retain their separate gates.

## Public tool contracts

| Tool | Success/error contract and validation |
| --- | --- |
| nmr_project | Typed project summary; existing/missing project and invalid create. |
| nmr_read | Object identity/type/version and bounded validated fields; missing-object error. Numeric arrays are omitted and long analysis tables explicitly truncated. |
| nmr_edit | Operation-specific input validation; atomic typed receipt or structured failure. |
| nmr_request | Original committed receipt or unknown-request result; no automatic scientific replay. |
| nmr_export | Named revision, media type, size, hash, artifact URI and optional verified local_path; explicit destination uses atomic non-overwriting publication. Structured errors preserve existing files. |
| nmr_help | Operation input schema and receipt schema; unsupported-operation error. |

[API and project tests](../tests/test_project.py) validate typed success and error
branches and reject malformed scientific output before commit. Objects use finite
JSON values. Unexpected execution failures return a bounded reconciliation
instruction. See the [batch contract](BATCH_ONE_CONTRACT.md) for evidence objects,
commands and export provenance.

## Implementation limits

Snapshots retain complete arrays for undo; history increases disk use and has no
compaction. Computation is synchronous and bounded, without cancellation or
durable background jobs. SQLite transactions coordinate frontends without a
hidden numerical daemon. Raw multidimensional processing remains outside the
qualified processed-2D profile. Reference export previews are limited to 32
selected pages with explicit coverage; every original is retained. Statistical
fit uncertainty excludes acquisition/preparation systematics, and missing supplied
uncertainty never means zero.
