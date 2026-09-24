# Developer alpha acceptance
This records implemented scope, not a completed first-batch release.
Both organic (ORG01–12) and physical (REL01–14) workflows remain in the first batch.
The private course mapping is maintained separately; private manuals are not source fixtures.

## Evidence layers
| Layer | Current evidence |
| --- | --- |
| Numeric core | Analytic integration, FFT/phase, baseline, yield, T1/T2 recovery, independently profiled weighted fit, covariance, unit/sign and identifiability regressions |
| Shared project | Atomic revision edits, two frontends/conflict, request replay, rollback, transitive stale marking, undo and reopen |
| Export | Named-revision JSON/CSV/SVG/original hashes and actual reopenable database including prior history; later changes excluded; in-app browser download event unconfirmed |
| Protocol | Real Windows MCP subprocess initialize/catalog/calls/errors/resource bytes/EOF; JSON output contracts validated |
| HTTP | Session/origin checks and actual shared-state edits through loopback HTTP |
| Format | Qualified synthetic fixtures and explicit unsupported-format/unsafe-input rejection; see reader tests |
| User workbench | Actual organic/T1 controls, MCP-versus-browser conflict, stale state, undo and saved-recipe reopen exercised; see DEVELOPMENT_RECEIPT.md |
| Native Mnova | Not used or accepted by this product; prior Mnova gates remain independent |
| Installed hosts/models | Pending: ChatGPT Chat/Work, Codex, Claude, WorkBuddy and Terra max benchmark |
| Packaging/cloud | Source build and CI definitions do not establish bundled installer, saved cloud environment or cloud-run success |

## First-batch traceability
| Cases | Implemented increment | Remaining acceptance or capability |
| --- | --- | --- |
| ORG01 | Qualified 1D raw/processed Bruker; nucleus/axis/stage; no double FFT | Wider instrument/build corpus and quantitative reference qualification |
| ORG02 | Signed peaks, editable integrals and shared identities | Integration normalization objects and interactive peak labels |
| ORG03–04 | Explicit inputs, overlap checks, internal-standard yield and assumptions | Preparation/acquisition uncertainty propagation and real quantitative standards |
| ORG05–06 | Sample/candidate/atom evidence assignments with provenance and review status | Structure canvas, own/reference workflows and stereochemical evidence qualification |
| ORG07 | Signed extrema retained for DEPT observations | Automated DEPT/13C matching and interpretation workflow |
| ORG08 | Reserved validated grid model | Processed COSY/HSQC import, matrix display and correlation editing |
| ORG09 | No image-to-number inference | Image/PDF reference attachment and annotation UI |
| ORG10 | Create/revise/remove evidence assignments | Atom/peak/crosspeak graphical mapping |
| ORG11 | Named spectra and sample assignments | Explicit reaction-stage records and IR/HRMS/rotation attachments |
| ORG12 | Source edits invalidate analyses/assignments; undo/reopen/revision exports | Full graphical assignment roundtrip |
| REL01–02 | Qualified numeric 1D DX plus CSV; original bytes; explicit row mapping | Real paired benchtop export and its actual encoding |
| REL03–06 | Unit conversion, unsorted/replicated delays, explicit echo mapping, signed T1 areas | Instrument-specific delay semantics |
| REL07 | Raw vs processed stage and FFT guard | Full instrument profile qualification |
| REL08–09 | Three-parameter T1/T2 fits, uncertainty and residual/identifiability screens | Experimental model adequacy; heuristics cannot certify all mixtures |
| REL10–11 | Revision conflict, stored mappings/parameters/exclusions/results, reopen | UI and host-specific workflow evidence |
| REL12 | Results carry units and source versions | Condition-comparison objects, reference records and comparison UI |
| REL13 | Explicit analysis/quick_check purpose and visible warning | Acquired metadata profile for automatic preliminary labeling |
| REL14 | Same-revision export with hashes and reopenable database | Actual delivery through each advertised host |

## Public tool contracts
| Tool | Success/error contract and validation |
| --- | --- |
| nmr_project | Typed project summary; existing/missing project and invalid create |
| nmr_read | Object identity/type/version plus bounded validated object fields; missing object |
| nmr_edit | Operation schema validated on dispatch; atomic typed receipt or structured failure |
| nmr_request | Original committed receipt; unknown request |
| nmr_export | Artifact revision/media/size/hash/URI; unavailable revision or integrity error |
| nmr_help | Operation schema and receipt schema; unsupported operation |

Detailed scientific object contents are validated by project models and finite JSON
serialization; normal MCP reads omit full spectrum/grid arrays. Mutation payloads
are validated per operation from commands.py. Malformed output is rejected before
commit. Unexpected execution failures produce a bounded error and reconciliation
instruction, rather than an automatic retry.

## Known implementation limits
Snapshots keep complete arrays for transparent undo; disk use grows with edit
history. The alpha bounds input sizes and snapshots but has no history compaction.
Computation is synchronous and bounded; cancellation/durable background jobs are
not promised. Multiple frontends share SQLite transactions rather than a daemon.
Standard analysis result covariance excludes systematic uncertainty.
