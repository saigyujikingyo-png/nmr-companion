# Third-party dependencies
The project's own source is MIT licensed. Dependency code retains its own licence.
The exact transitive versions are pinned in uv.lock; package distributions include
their upstream notices. This preview does not vendor proprietary binaries or
private datasets.

| Direct dependency | Use | Upstream |
| --- | --- | --- |
| NumPy | float64 arrays, transforms | https://github.com/numpy/numpy (BSD-3-Clause) |
| SciPy | optimization, diagnostics, peak finding | https://github.com/scipy/scipy (BSD-3-Clause) |
| nmrglue 0.12 | qualified Bruker binary readers and filter correction | https://github.com/jjhelmus/nmrglue (New BSD) |
| Pydantic | validated command/project/output contracts | https://github.com/pydantic/pydantic (MIT) |
| MCP Python SDK | protocol transport | https://github.com/modelcontextprotocol/python-sdk (MIT) |

The complete NMRium dependency stack is not included. Mnova remains an optional
external comparison or interoperability target with its own licence and gates.

## Native Windows interface
PySide6 Essentials and shiboken6 6.11.2 supply the dynamic Qt Widgets interface;
pyqtgraph 0.14.0 supplies numerical plotting. Their exact wheels are pinned in
`uv.lock`. Qt WebEngine and PySide Addons are not dependencies. The Windows
bundle preserves upstream Qt/PySide/shiboken license texts, source references and
pyqtgraph's MIT notice under `THIRD-PARTY-NATIVE-NOTICES`, alongside the original
wheel metadata. These upstream components retain their own licenses; the
application's MIT license does not replace them. See the included native notices
for library replacement and corresponding source information.

The native application uses the installed system UI font. System fonts are not
redistributed. Offscreen Windows checks load the existing Segoe UI font into that
isolated process only when the headless plugin cannot enumerate system fonts.

## Legacy web interface font
Inter Variable is bundled for offline rendering under the SIL Open Font License 1.1. Copyright 2016 The Inter Project Authors. The full licence is distributed at `src/nmr_companion/static/Inter-LICENSE.txt`.
Source: https://github.com/rsms/inter/tree/master/docs/font-files
Font SHA-256: `693b77d4f32ee9b8bfc995589b5fad5e99adf2832738661f5402f9978429a8e3`.


## Reference rendering
Pillow 12.3 uses MIT-CMU; its installed distribution licence is retained.
[Upstream licence](https://github.com/python-pillow/Pillow/blob/main/LICENSE).
pypdfium2 5.13 metadata declares BSD-3-Clause, Apache-2.0 and dependency licences.
[Upstream licensing](https://github.com/pypdfium2-team/pypdfium2#licensing).
PDFium and third-party notices are retained in the packaged distribution.
PDFium calls are serialized because the library is not thread-safe.
The Windows runtime pin and preserved notices are described in docs/INSTALLATION.md.
Private laboratory inputs are not distributed.
