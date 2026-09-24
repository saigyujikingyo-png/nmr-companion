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

## Bundled interface font
Inter Variable is bundled for offline rendering under the SIL Open Font License 1.1. Copyright 2016 The Inter Project Authors. The full licence is distributed at `src/nmr_companion/static/Inter-LICENSE.txt`.
Source: https://github.com/rsms/inter/tree/master/docs/font-files
Font SHA-256: `693b77d4f32ee9b8bfc995589b5fad5e99adf2832738661f5402f9978429a8e3`.
