# Joint first-batch evidence contract

The organic and relaxation workflows share one editable project, revision history
and command surface. Project schema 2 contains the existing spectra, grids,
tables, integrals, analyses, assignments and source manifests together with the
evidence collections below. GUI and MCP use the same objects and validation.
Discover operation schemas through `nmr_help`; the six public MCP tools remain
compact. Scientific and delivery acceptance is recorded in [ACCEPTANCE.md](ACCEPTANCE.md).

## Revision and compatibility rules

Every edit supplies `expected_revision` and a unique `request_id`. An identical
committed request returns its stored receipt; changed reuse and stale revision
writes fail without applying a new edit. Undo creates a new revision from a
retained snapshot. Source changes invalidate dependent interpretations
transitively. Dependencies retain the versions used for a result; a stale result
is not silently recomputed or labelled current.

Schema-1 projects remain readable without migration, and replay of an existing
committed request does not upgrade them. The first successful schema-2 mutation
prepares a closed, integrity-checked pre-upgrade backup and preserves the old
snapshots. Failed mutations leave neither a newly published backup nor a partial
backup. Existing backups are retained. Software rollback does not downgrade data;
old software can use the retained old-schema backup. Unknown schema versions fail.

Original source blobs are immutable and identified by SHA-256. Import and reference
attachment preserve original bytes separately from editable numerical objects and
derived interpretations. Removing an editable object does not erase the original
bytes or historical revisions.

## Collections

All collection objects have stable `id` and positive `version` fields. Derived
evidence objects also have `source_versions` and `state` (`current` or `stale`).
Sample `role` describes provenance; structure/assignment `status` describes the
user's review decision. Neither field substitutes for current/stale state.

| Collection | Fields and semantics |
| --- | --- |
| `samples` | `name`, `role` (`own`, `reference`, `synthetic`, `unknown`), `object_ids` referring to spectra/grids/tables, `stage`, `parent_ids`, `transformation`, `conditions`, `reference`, `notes`. Parent associations must be acyclic and require transformation context. |
| `structures` | `name`, `sample_id`, `atoms`, `bonds`, `description`, `alternative_group`, `evidence_ids`, `status` (`proposed` or `confirmed`), `source_versions`, `state`. At least one atom is required; confirmed interpretations require explicit evidence. |
| `crosspeaks` | `grid_id`, `x_ppm`, `y_ppm`, `label`, `intensity`, `observation_method`, `source_versions`, `state`. Coordinates must be within the grid. Intensity is the nearest original grid point, not a value inferred from its image. |
| `peaklabels` | `spectrum_id`, `ppm`, `label`, `intensity`, nullable `multiplicity` and `protons` (positive when supplied), `observation_method`, `source_versions`, `state`. A manual position is interpolated from the original numerical array. |
| `attachments` | `name`, `sample_id`, `source_role` (`own` or `reference`), `category` (`nmr_reference`, `IR`, `HRMS`, `optical_rotation`, `other`), `source_id`, `media_type`, `pages`, `width`, `height`, `notes`, `source_versions`, `state`. |
| `annotations` | `attachment_id`, one-based `page`, normalized `x`, `y`, `width`, `height`, `label`, `observation`, nullable `approximate_ppm` and `reading_uncertainty_ppm`, `origin`, `source_versions`, `state`. Coordinates have a top-left origin and must stay within the page; reading uncertainty requires a reading. `origin` is `image_annotation_not_numeric_spectrum`. |

`conditions` contains nullable `solvent` and `temperature_k` (positive when supplied), plus
`additives: [{name, concentration_mol_l, notes}]`. Additive concentration is
nullable and nonnegative, in mol/L. Unknown temperature or concentration remains
null rather than a guessed laboratory default.

An atom contains `id`, `label`, `element`, finite drawing coordinates `x` and `y`,
and optional `stereo` text. Atom IDs are unique within a candidate. A bond contains
stable endpoints `a` and `b`, `order` in `1`, `1.5`, `2`, `3`, and `stereo` in
`none`, `wedge`, `hash`, `either`. Endpoints must exist and be distinct; duplicate
bond pairs fail. Drawing coordinates and stereochemical labels are editable
context, without automatic CIP assignment or chemical proof.

The `analyses` collection includes `normalization`, `comparison` and `dept` in
addition to existing analysis kinds. Assignments retain their text fields and
add nullable `sample_id`, `candidate_id` and an `atom_ids` list. Linked atoms must
belong to the specified saved candidate. Evidence cycles are rejected. Automatic
structure elucidation or confirmation is not part of this contract.

## Commands

Every command includes its `op`. A `?` below denotes an optional field. Each
create/edit operation has its own optional identity field: `sample.sample_id`,
`structure.structure_id`, `crosspeak.crosspeak_id`, `peak_label.peaklabel_id`,
`annotate.annotation_id` or `assign.assignment_id`. Supplying that field edits the
existing object; omitting it creates an object. Other identity fields link existing
objects. Analysis commands create analyses; `attach` preserves a new supplied
reference. All commands remain revision checked.

| Operation | Input |
| --- | --- |
| `sample` | `sample_id?`, `name`, `role`, `object_ids=[]`, `stage=""`, `parent_ids=[]`, `transformation=""`, `conditions={}`, `reference=""`, `notes=""`. |
| `structure` | `structure_id?`, `name`, `sample_id`, `atoms`, `bonds=[]`, `description=""`, `alternative_group=""`, `evidence_ids=[]`, `status="proposed"`. |
| `crosspeak` | `crosspeak_id?`, `grid_id`, `x_ppm`, `y_ppm`, `label`. |
| `grid_metadata` | `grid_id`, `experiment` (`COSY` or `HSQC`), `nuclei` ordered `[x,y]`, `reference`. Records explicit user confirmation and retains imported metadata and confirmation history. |
| `peak_label` | `peaklabel_id?`, `spectrum_id`, `ppm`, `label`, `multiplicity?`, `protons?`. |
| `normalize` | `name="Relative proton integration"`, `reference_integral_id`, positive `reference_protons`, `integral_ids`. All selected integrals belong to the same 1H spectrum; the reference area must be positive. |
| `attach` | `path`, `name?`, `sample_id`, `source_role`, `category`, `notes=""`. Supports PDF, PNG, JPEG and WebP originals with bounded decoding; no SVG/script execution. |
| `annotate` | `annotation_id?`, `attachment_id`, `page=1`, `x`, `y`, `width`, `height`, `label`, `observation=""`, `approximate_ppm?`, `reading_uncertainty_ppm?`. |
| `compare` | `name`, `metric` (`T_s` or `chemical_shift_ppm`), `left_id`, `right_id`, `left_sample_id`, `right_sample_id`, `signal_label`, `correspondence`, `independent_uncertainties=false`. |
| `dept` | `carbon_spectrum_id`, `dept_spectrum_id`, positive `carbon_prominence`, `dept_prominence`, `tolerance_ppm` (at most 5), `reference_convention` (`positive_ch_ch3` or `negative_ch_ch3`), `reference`, `name="DEPT-135 / carbon evidence"`. |
| `yield` | Existing required product/standard integral IDs, proton counts and amounts in mol; `stoichiometric_factor=1.0`; optional `recovered_integral_id`, `recovered_protons`, `u_product_area`, `u_standard_area`, `u_recovered_area`, `u_standard_mol`, `u_limiting_mol`. Recovered integral and proton count must be supplied together. |
| `assign` | `assignment_id?`, required text `sample`, `atom`, `candidate`, `observation`, and `evidence_ids`; `status="proposed"`; optional `sample_id`, `candidate_id`, `atom_ids=[]`. |
| `remove` | `object_id`. Supports removable derived objects, including evidence observations and candidates; imported numerical objects and original blobs remain protected. |

Normalization reports signed relative proton counts and never changes spectral
arrays or relaxation amplitudes. Yield/recovery uses the same acquired spectrum
and separated selected regions. Its uncertainty calculation uses explicitly
supplied nonnegative standard uncertainties and retains shared-standard covariance
in material balance. Missing uncertainty stays unavailable; the calculation does
not infer preparation or acquisition uncertainty.

Comparison requires relaxation analyses for `T_s` and peak labels for chemical
shifts. Both samples must be explicitly associated with the corresponding
acquired datasets. The result retains conditions, reference conventions, signal
correspondence, right-minus-left difference and right/left ratio where defined.
Missing uncertainty stays null; propagation requires the declared independence
assumption. Quick-check inputs retain a warning.

DEPT matching keeps signed observations and the supplied phase/reference
convention. A unique match is required in both directions: several DEPT peaks
near one carbon peak, or several carbon peaks competing for one DEPT peak, produce
`ambiguous` interpretations. Rows retain candidate counts. Results remain
`proposed`; `no_DEPT_signal` is not an automatic quaternary-carbon assignment.

## Import and processed grids

`import` accepts `path` and optional `bruker_processing_numbers`, default null.
Null means strict decoding of every discovered supported data object; an invalid
profile fails the import. A supplied selection must be a nonempty list of unique
positive integers from 1 through 999999, with at most 64 entries. No preferred
processing number is chosen automatically.

An explicit selection controls which numbered Bruker `pdata` directories are
decoded across all captured experiments. Raw FIDs still undergo normal validation.
All captured originals, including unselected processing files and the untouched
ZIP container, remain preserved. Unselected profiles are recorded as
`preserved_not_decoded_or_qualified`; discovering a number does not qualify its
contents. Selection never bypasses capture limits, unsafe-input rejection or the
raw multidimensional `ser` rejection. See [processed profiles](PROCESSED_2D_FORMATS.md)
for path identity, selection diagnostics and exact binary/JSON qualification.

For processed grids, `z[row][column]` corresponds to `(x[column], y[row])` and
`nuclei` is `[x nucleus, y nucleus]`. Axes are finite, strictly monotonic ppm arrays;
stored order is preserved. COSY requires `1H/1H`; HSQC accepts `1H/13C`, `13C/1H`,
`1H/15N` or `15N/1H`. Missing or conflicting semantics are not inferred from array
shape. Explicit later confirmation does not rewrite original parameters.

The workbench displays x decreasing left to right and y increasing top to bottom.
Rendering preserves positive and negative extrema separately. Display sampling,
cutoff and colour scale do not alter stored arrays; numerical work uses full
resolution. Crosspeak coordinates refer to those original axes.

## Local HTTP and human editing

| Route | Contract |
| --- | --- |
| `GET /api/project` | Full locally held project for rendering. Normal MCP `nmr_read` omits spectrum/grid arrays and explicitly truncates long analysis tables at 64 rows. |
| `GET /api/reference/{attachment_id}/page/{page}` | Bounded PNG preview of a validated one-based reference page, verified against its preserved source bytes. |
| `GET /api/source/{sha256}` | Verified original bytes belonging to the current project revision. |
| `POST /api/quit` | Authenticated request with no body; acknowledges `state: "stopping"` and shuts down this web listener. Closing a browser tab alone does not stop it. |

These routes use the session's Bearer authentication and Host/Origin checks.
Reference images are fetched with Authorization and displayed through local Blob
URLs; tokens do not appear in preview URLs. The content policy permits
`img-src blob:` and assets are served offline without a CDN. The numerical project
and lifecycle remain independent of the browser presentation.

Human workflows use labelled fields, editable tables and canvases. Atom creation
and annotation bounds have keyboard-editable fields; drawing and correlation
selection have explicit save actions. Drafts are separate from saved objects and
are cleared when their bound project/object versions change. Existing 1D,
relaxation, revision, undo and export controls use the same service. A conflict
refreshes the view without automatically replaying the rejected mutation.

## Export and acceptance boundaries

An export binds JSON, CSV, PNG/SVG figures, original files and the editable
project database to one named revision. Stale interpretations remain visible and
labelled. Generated analysis CSV records include `analysis_id`, `state`,
`source_versions`, `project_id`, `revision` and sample provenance. Figure sample
roles are resolved through actual source dependencies, including fitted traces.
Unassociated objects retain an explicit unspecified role.

All imported table column names receive a `source.` prefix in exported CSVs, so
source columns cannot replace generated project/revision provenance. An original
column already named `source.project_id` becomes `source.source.project_id`.
Exact source column names and bytes remain in the project and original blobs.
Spreadsheet-formula-like text is escaped in CSV; exact text remains in JSON.

Reference exports render the first page and annotated pages up to a total of 32
preview pages. `reference-preview-coverage.json` identifies rendered and omitted
previews; every original reference file is still included. Image observations
remain distinct from numerical spectra. Export generation and download initiation
do not establish host receipt or successful reopening.

Full arrays remain in revision snapshots, without history compaction. Computation
is bounded and synchronous, with no durable job queue or cancellation promise.
General raw multidimensional processing, automatic chemical interpretation,
experimental adequacy and universal instrument support are outside the qualified
profile. Real benchtop pairing, curated chemistry review, installed hosts/models,
file delivery and cloud execution require separate evidence in the acceptance
record.

`nmr_export` also accepts an optional absolute `destination` for a new `.zip` file
in an existing directory. It refuses existing files and symlink/reparse paths,
publishes without replacement, and returns a verified `local_path` with size and
hash. Hosts can use that local file link without decoding archive bytes in the
model context. A zero-row analysis CSV retains a provenance-only row marked
`result_count=0`; the exact empty array remains in JSON.
