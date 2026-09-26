# Processed two-dimensional input profiles

NMR Companion imports the bounded processed profiles below into editable project
objects. They contain frequency-domain numeric data; import does not run an FFT,
remove a digital filter, normalize traces, change signs, or infer assignments.
This is a qualified reader profile, not universal Bruker or instrument support.
Actual instrument, referencing and scientific interpretation acceptance remain
separate from the synthetic fixtures in `tests/test_processed_2d.py`.

## Shared grid contract

`load_input` returns `grids` entries with `name`, `x`, `y`, `z`, `nuclei`,
`metadata`, and `source_names`. `x` is the column axis, `y` is the row axis, and
`z[row][column]` corresponds to `(x[column], y[row])`. `nuclei` is ordered
`[x nucleus, y nucleus]`. Both axes use ppm, have at least two points and are
strictly monotonic. Ascending and descending explicit JSON axes are accepted
without sorting or transposing the data. All numeric values must be finite.

The reader preserves captured bytes in `originals`. `source_names` identifies
all original files used to interpret the grid; the project service resolves
those names to immutable source hashes. Directory names are relative to the
selected input. For ZIP input, source references use the `members/` prefix and
the untouched ZIP is retained separately under `archive/`.

Limits remain 32 MiB per captured file, 128 MiB total captured input (including
the ZIP container), 1024 directory/archive entries, 64 supported data objects,
262144 points per axis, and 1000000 cells per grid. Unsafe names, aliased names,
links, nested ZIPs and excessive compression ratios retain the existing rejection
rules. A failed import does not return a partially accepted bundle.

## Portable JSON, schema 1

Use UTF-8 and the suffix `.nmr2d.json`. A standalone `.json` also works. In a
mixed directory or ZIP, a `.json` file with the explicit format marker below is
recognized; unrelated JSON sidecars remain preserved without being interpreted.
The dedicated `.nmr2d.json` suffix requires strict parsing even when the file is
malformed or its format marker is missing. An unrecognizable malformed generic
JSON sidecar in a mixed bundle remains ignored, preserving earlier 1D behavior.

```json
{
  "format": "nmr-companion-processed-2d",
  "schema_version": 1,
  "name": "Synthetic HSQC reference",
  "experiment": "HSQC",
  "x": {"unit": "ppm", "nucleus": "1H", "values": [8.0, 6.0, 4.0, 2.0]},
  "y": {"unit": "ppm", "nucleus": "13C", "values": [120.0, 100.0, 80.0]},
  "z": [[1.0, -2.0, 3.0, 4.0], [5.0, 6.0, -7.0, 8.0], [9.0, 10.0, 11.0, -12.0]]
}
```

Only `name` is optional; it defaults to the input's relative name. If supplied,
it contains 1 to 200 printable characters. Unknown fields and duplicate fields
at any object level are rejected. `schema_version` must be integer `1`, not a
boolean. Axes contain exactly `unit`, `nucleus` and `values`. Numeric strings,
booleans, NaN and Infinity are rejected as numeric data. A ragged or differently
sized matrix is rejected instead of being padded, cropped or transposed.

The experiment and nuclei are explicit semantic declarations:

| Experiment | Qualified axis nuclei |
| --- | --- |
| `COSY` | `1H`, `1H` |
| `HSQC` | `1H`, `13C` or `13C`, `1H` |
| `HSQC` | `1H`, `15N` or `15N`, `1H` |

Labels are case-sensitive. Missing labels, ambiguous labels such as
`HSQC/COSY`, unsupported experiments, and mismatches such as HSQC with two proton
axes fail. Both HSQC orientations are valid when explicitly declared; the
reader preserves that declaration and does not decide which nucleus belongs on
x from array dimensions. The schema does not validate the truth of a supplied
experiment label or certify that a correlation is chemically meaningful.

Metadata records the declared experiment, ppm units, axis order, reader profile,
processing stage, absence of import processing, and preserved signed intensity.
The JSON supplies numeric intensities directly; no scaling factor is applied.

## Bruker real-real processed 2D

Select a processed directory containing `2rr`, `procs` and `proc2s`, or a safe ZIP
containing that profile. Only the `2rr` real-real component is interpreted.
Other captured files remain original bytes; `2ri`, `2ir` and `2ii` are not
combined into a complex or hypercomplex grid.

| Role | Required parameters |
| --- | --- |
| x / direct F2 / `procs` | `SI`, `XDIM`, `SF`, `SW_p`, `OFFSET`; an evidenced nucleus |
| y / indirect F1 / `proc2s` | `SI`, `XDIM`, `SF`, `SW_p`, `OFFSET`; an evidenced nucleus |
| Binary storage and amplitude / `procs` | `BYTORDP`, `DTYPP`, `NC_proc` |

`SI` is the number of points along its axis; `XDIM` is its tile width or height.
Both are positive bounded integers, each SI is at least two, and each SI must be
divisible by its XDIM. The binary byte count must exactly match
`procs.SI * proc2s.SI * element_size`. This profile accepts full-width axes only:
`STSR` must be absent or zero, and `STSI` must be absent, zero or equal to SI.
Cropped axes and partial padded tiles require separate qualification.

`BYTORDP=0` selects little-endian and `BYTORDP=1` selects big-endian storage.
`DTYPP=0` selects signed int32 and `DTYPP=2` selects float64. The complete 2rr
component is scaled once by `2**procs.NC_proc`; NC_proc is a bounded integer from
-256 to 256. `proc2s.NC_proc` is not a second scaling factor. Non-finite stored or
scaled values fail. Output has shape `(proc2s.SI, procs.SI)`. Tiles are ordered
row-major, with values row-major within each tile. The reader records the actual
shape, tile shape, storage flags and scaling convention in provenance.

The axis calculation for each processing dimension is:

```text
ppm[i] = OFFSET - i * SW_p / (SI * SF), i = 0 ... SI-1
```

SF is in MHz, SW_p is in Hz, and OFFSET is in ppm. SF and SW_p must be positive
and finite; OFFSET must be finite. This follows the processed reference encoded
by the supplied parameters and does not independently calibrate the instrument
or recover additional SR precision from acquisition frequencies.

Each nucleus must be present in `AXNUC` or in the corresponding acquisition
`NUC1`: x uses `acqus`, y uses `acqu2s`. Acquisition fallback is accepted for a
conventional `experiment/pdata/procno` layout captured with its experiment root,
or for a deliberately flattened export with acquisition files beside `2rr`.
No acquisition files are read outside the captured bundle. Invalid nucleus
labels or conflicting processing/acquisition labels fail. Unknown axes are
never filled from spectral widths, matrix dimensions or typical experiments.

An exact `acqus.EXP` value of `COSY` or `HSQC` is treated as an explicit experiment
declaration and must agree with the qualified nuclei table above. Other or
missing EXP values produce `metadata.experiment = null` and a warning. Pulse
program names are not translated into guessed experiment types. A later explicit
user confirmation can supply an interpretation through the shared grid metadata
workflow without rewriting the imported original files.

The installed nmrglue 0.12 implementations of `read_pdata_binary`,
`reorder_submatrix`, `scale_pdata` and `guess_shape_and_submatrix_shape` were
inspected for storage conventions. The profile uses bounded scalar metadata
parsing and explicit shape checks around the binary reader, rather than the
upstream general parameter reader. See the upstream
[nmrglue Bruker API](https://nmrglue.readthedocs.io/en/latest/reference/bruker.html)
for the corresponding APIs. The actual reader version is retained on import.

## Explicit Bruker processing-number selection

The public reader accepts `load_input(path, *, bruker_processing_numbers=None)`.
The import command exposes the same optional `bruker_processing_numbers` field:

```json
{"op": "import", "path": "selected-input.zip", "bruker_processing_numbers": [1]}
```

`None` retains strict processing of every discovered supported data object. A
malformed processing profile fails the whole import. A non-null selection must
be a nonempty list of unique positive integers (not booleans, strings or floats),
with at most 64 entries and each number between 1 and 999999. There is no
automatic preferred processing number and no special meaning assigned to a
number such as 700.

An explicit list selects the matching `pdata/<positive decimal integer>`
directories across **all** experiments in the captured input, for both 1D and
2D processed spectra. Each file uses its nearest containing numbered `pdata`
directory, so a nested differently numbered profile does not inherit the outer
number. Leading zeros identify the same integer; original paths remain unchanged. Other files inside unselected processing directories are also
preserved without interpretation. Data outside those directories, including CSV
mapping tables, retains its normal reader behavior. Raw `fid` files are always
read and validated, irrespective of the processed selection. A captured `ser`
still fails the import, including when stored below an unselected directory.

Selecting an input directory named `pdata` or directly selecting `pdata/1`
retains that explicit path context for numbering. The corresponding profile
paths in metadata are relative to that input (`1` or `.` respectively). No
files outside the input are accessed. A flattened directory or ZIP with no
numbered identity cannot satisfy an explicit selection. Mixed numbered and
unnumbered Bruker processed components require a conventional directory layout
before selection can be applied. Every requested number must have a captured
processed binary component; an empty list, missing number, or parameter-only
profile cannot silently produce a successful selection. Errors report
`INVALID_ARGUMENT` or `NOT_FOUND` and, where available, the discovered numbers.
A failure while decoding a selected Bruker component identifies its relative
source and discovered numbers; it is never skipped automatically.

When selection is explicit, each imported Bruker spectrum or grid records
`metadata.bruker_processing_selection` with:

- `requested`: the explicit list, in supplied order;
- `discovered`: sorted numbers found in captured `pdata` paths, without a claim
  that those profiles contain valid or qualified data;
- `decoded_profiles`: relative processing directories actually decoded;
- `skipped_profiles`: captured processing directories not decoded;
- `skipped_status`: `preserved_not_decoded_or_qualified`;
- `input_directory_context`: `pdata`, `pdata/1` or null, as applicable.

Warnings repeat the selection and identify the unexamined profiles. All captured
bytes remain in `originals`, including unselected processing parameters and
components. ZIP imports retain the entire original ZIP and every member;
metadata profile paths use `members/` consistently. An excluded malformed or
unsupported profile has **not** passed format or scientific qualification.
Explicitly excluding a processed 3D/4D profile preserves its bytes without
making that profile supported; selecting it, or using the strict default, fails.

All file capture, size, entry-count, path, link and ZIP safety checks run before
selection. The 64-object interpretation limit applies to the selected processed
objects plus other decoded inputs. Selection changes the decoding scope only;
it does not weaken preservation, raw-data validation or input safety limits.

## Qualification boundary

Independent synthetic binary fixtures cover both byte orders, both supported
storage types, signed scaling, rectangular submatrices, separate proton/carbon
axes, acquisition fallback and original identities. JSON fixtures cover COSY,
carbon and nitrogen HSQC in both explicit orientations, invalid axes, semantic
mismatches, non-finite data, the cell boundary and archive binding. Existing 1D
and ZIP-safety checks remain applicable. Processing-selection fixtures also
cover invalid and missing numbers, multiple experiments, original FIDs, skipped
profile bytes, directory context and full ZIP/capture safety checks.

Raw multidimensional acquisition (`ser`), processed 3D/4D, cropped or unqualified
tile layouts, unsupported numeric encodings and automatic structure assignment
remain outside this profile. A bundle containing `ser` is rejected even if it
also contains processed data; select or export the processed-only input without
modifying original acquisition files. Representative real instrument datasets,
reference accuracy, acquisition/processing adequacy, installed-host workflows
and scientific interpretation still require separate acceptance evidence.
