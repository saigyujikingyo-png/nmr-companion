# Static workbench interface
The coordinator owns api.py, service.py, web.py and cli.py.
Frontend contributor owns only src/nmr_companion/static/index.html, app.js, app.css.
Use plain local HTML/CSS/JS (no CDN, telemetry or external model). CSP disallows inline
scripts/styles and external resources. Responsive accessible labels and readable
scientific tables, never innerHTML with user values.

CLI launches http://127.0.0.1:PORT/#token=VALUE. Read token from fragment once,
store in sessionStorage, remove fragment using history.replaceState.
All API requests include Authorization: Bearer TOKEN. Token stays local.
GET /api/project -> full Project JSON (see models.py); unavailable -> error.
POST /api/tool body {"name": TOOL, "arguments": {...}} -> {ok,data,error}.
Tool schemas in api.py; commands in commands.py. All edits go through nmr_edit:
{expected_revision: current.revision, request_id: crypto.randomUUID(),
 command: {op:..., ...}}. On success reload project. On conflict show error,
refresh and require deliberate user action; never replay stale writes.
nmr_project create with name, status; nmr_help operation; nmr_read object_id;
nmr_export revision -> artifact. Fetch /api/artifact/ID with the Authorization header and download a local blob.
The session token never needs to appear in a download URL. Show SHA-256, revision, byte size; don't claim host delivery.

Required first-alpha controls:
- Empty project name/create and synthetic demonstration (demo command).
- Local source path import; explain data stays local, supported formats qualified.
- Spectrum list, render signed real data with descending ppm axis; time axis normal.
  Bucket min/max if sampling for display, never alter scientific arrays.
- Add/edit integral region via numeric bounds and selected spectrum. List areas.
- Select product/standard integrals with explicit protons and mol amounts for yield.
- Explicit table mapping for T1/T2: pick spectra in ordered rows and enter delay row
  indices; select CSV delay column and unit; input shared region and T2 time basis/
  multiplier. Preserve signed traces. Read-only result table and residual display.
- Processing: FFT/phase/baseline/reference with clearly labelled units/parameters.
- Evidence assignments: atom, sample, candidate, observation, status, evidence IDs.
- Show current/stale analyses and assumptions, undo target revision, export.
UI can expose JSON operation editor for advanced operations but normal first
organic and relaxation workflows need labelled controls. Read actual scientific
result objects from project. Demo values must say synthetic, not experimental.
