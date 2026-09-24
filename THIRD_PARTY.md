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
