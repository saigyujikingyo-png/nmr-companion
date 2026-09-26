"use strict";
const $ = (id) => document.getElementById(id);
const node = (tag, text, cls) => {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
};
const fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.has("token")) {
  sessionStorage.setItem("nmr-session", fragment.get("token"));
  history.replaceState(null, "", location.pathname);
}
const token = sessionStorage.getItem("nmr-session") || "";
let project = null,
  selected = null,
  busy = false;
const views = new Map();
let geometry = null,
  gesture = null,
  draft = null,
  hoverAxis = null;
let plotMode = "inspect",
  workflow = "organic",
  drawPending = false;
const headers = {
  Authorization: "Bearer " + token,
  "Content-Type": "application/json",
};
const fmt = (value, digits = 6) =>
  typeof value === "number" && Number.isFinite(value)
    ? Number(value.toPrecision(digits)).toString()
    : "Unavailable";
function notice(text, error = false) {
  $("notice").textContent = text;
  $("notice").classList.toggle("error", error);
}
function value(id) {
  const v = $(id).valueAsNumber;
  if (!Number.isFinite(v)) throw Error("Enter a finite number for " + id + ".");
  return v;
}
async function tool(name, args) {
  const response = await fetch("/api/tool", {
    method: "POST",
    headers,
    body: JSON.stringify({ name, arguments: args }),
  });
  const result = await response.json();
  if (!response.ok || !result.ok) {
    const failure = result.error || {};
    const e = Error(
      failure.message || "Local session unavailable. Reopen the workbench URL.",
    );
    e.code = failure.code;
    throw e;
  }
  return result.data;
}
async function refresh() {
  const response = await fetch("/api/project", { headers });
  const result = await response.json();
  if (!response.ok) {
    project = null;
    render();
    if (result.error?.code === "NO_PROJECT")
      notice(
        "Create an empty project, then import local data or try the synthetic demonstration.",
      );
    else
      throw Error(
        result.error?.message || "Session unavailable. Reopen the launch URL.",
      );
    return;
  }
  project = result;
  render();
  notice(
    "Project loaded · revision " +
      project.revision +
      ". Human and agent edits share this state.",
  );
}
async function act(fn) {
  if (busy) return;
  busy = true;
  document.querySelectorAll("button").forEach((b) => (b.disabled = true));
  try {
    await fn();
  } catch (e) {
    if (e.code === "REVISION_CONFLICT") {
      await refresh();
      notice(
        "Another editor changed this project. Review the refreshed state before submitting again.",
        true,
      );
    } else notice(e.message, true);
  } finally {
    busy = false;
    document.querySelectorAll("button").forEach((b) => (b.disabled = false));
    syncPlotTools();
    globalThis.NMRBatch?.sync();
  }
}
async function edit(command) {
  if (!project) throw Error("Create a project first.");
  const receipt = await tool("nmr_edit", {
    expected_revision: project.revision,
    request_id: crypto.randomUUID(),
    command,
  });
  $("receipt").textContent = JSON.stringify(receipt, null, 2);
  await refresh();
  notice(
    "Saved revision " +
      receipt.revision +
      (receipt.warnings.length ? " · " + receipt.warnings.join(" ") : ""),
  );
  return receipt;
}
function options(select, items, { blank = false } = {}) {
  const old = select.value;
  const selectedValues = new Set([...select.selectedOptions].map((option) => option.value));
  select.replaceChildren();
  if (blank) select.add(new Option("Select…", ""));
  for (const [id, label] of items) {
    const option = new Option(label, id);
    if (select.multiple) option.selected = selectedValues.has(id);
    select.add(option);
  }
  if (!select.multiple && [...select.options].some((o) => o.value === old)) select.value = old;
}
function active() {
  if (!project || !project.spectra[selected]) throw Error("Select a spectrum.");
  return project.spectra[selected];
}
function render() {
  const spectra = Object.values(project?.spectra || {}),
    integrals = Object.values(project?.integrals || {});
  if (!spectra.some((s) => s.id === selected))
    selected = spectra[0]?.id || null;
  $("projectName").textContent = project?.name || "Open a project";
  $("revision").textContent = project
    ? "Revision " + project.revision + " · saved locally"
    : "No project loaded";
  renderLibrary();
  $("spectrumName").textContent = selected
    ? active().name
    : "A shared place to work with spectra.";
  $("domainBadge").textContent = selected
    ? active().domain === "time"
      ? "RAW FID"
      : "FREQUENCY · " + (active().nucleus || "nucleus unknown")
    : "No spectrum";
  $("pointCount").textContent = selected
    ? active().real.length.toLocaleString() + " points"
    : "";
  $("sourceInfo").textContent = selected
    ? (active().metadata.synthetic
        ? "SYNTHETIC · software demonstration"
        : active().metadata.stage || active().domain) +
      " · object version " +
      active().version
    : "Import data or load the synthetic demonstration.";
  if (
    draft &&
    (draft.spectrumId !== selected || draft.version !== active().version)
  ) {
    resetIntegral();
    $("draftStatus").textContent =
      "Draft cleared because its source changed. Select the region again.";
  }
  drawSpectrum();
  renderIntegrals();
  renderAnalyses();
  renderAssignments();
  for (const id of ["productIntegral", "standardIntegral"])
    options(
      $(id),
      integrals.map((i) => [i.id, i.name + " · " + fmt(i.area)]),
      { blank: true },
    );
  options(
    $("delayTable"),
    Object.values(project?.tables || {}).map((t) => [t.id, t.name]),
    { blank: true },
  );
  renderTable();
  const evidence = [];
  for (const key of ["spectra", "grids", "integrals", "analyses", "crosspeaks", "peaklabels", "attachments", "annotations", "structures"])
    for (const item of Object.values(project?.[key] || {}))
      evidence.push([
        item.id,
        (item.name || item.label || item.id) + (item.state === "stale" ? " [stale]" : ""),
      ]);
  options($("evidenceIds"), evidence);
  $("undoRevision").max = Math.max(0, (project?.revision || 1) - 1);
  globalThis.NMRBatch?.render();
}
function renderLibrary() {
  const spectra = Object.values(project?.spectra || {});
  const query = $("spectrumSearch").value.trim().toLocaleLowerCase();
  const shown = spectra.filter((s) =>
    (s.name + " " + (s.nucleus || "")).toLocaleLowerCase().includes(query),
  );
  $("spectrumCount").textContent = spectra.length + " spectra";
  options(
    $("spectrumSelect"),
    shown.map((s) => [s.id, s.name]),
  );
  $("spectrumSelect").value = selected || "";
}
function currentView() {
  const s = project?.spectra[selected];
  if (!s) return null;
  let view = views.get(s.id);
  if (!view || view.version !== s.version) {
    const extent = NMRView.bounds(s.axis);
    view = {
      version: s.version,
      extent,
      range: [...extent],
      history: [],
      gain: 1,
    };
    views.set(s.id, view);
    gesture = null;
    hoverAxis = null;
    $("cursorReadout").textContent = "Move over the spectrum";
  }
  return view;
}
function plot(
  canvas,
  x,
  y,
  {
    unit = "ppm",
    title = "",
    regions = [],
    zero = true,
    range = null,
    gain = 1,
    crosshair = null,
  } = {},
) {
  const rect = canvas.getBoundingClientRect(),
    w = Math.max(100, rect.width),
    h = rect.height || 280,
    dpr = devicePixelRatio || 1;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  const c = canvas.getContext("2d");
  c.scale(dpr, dpr);
  c.clearRect(0, 0, w, h);
  if (!x?.length) {
    c.fillStyle = "#7a899d";
    c.font = "13px Inter, sans-serif";
    c.fillText(
      "Import local data or load the synthetic demonstration.",
      28,
      h / 2,
    );
    return null;
  }
  const extent = NMRView.bounds(x);
  let [xmin, xmax] = range || extent;
  if (xmin === xmax) xmax = xmin + 1;
  let ymin = zero ? 0 : Infinity,
    ymax = zero ? 0 : -Infinity;
  for (const value of y) {
    ymin = Math.min(ymin, value);
    ymax = Math.max(ymax, value);
  }
  const span = ymax - ymin || 1;
  ymin = (ymin - span * 0.08) / gain;
  ymax = (ymax + span * 0.15) / gain;
  const left = 55,
    right = 24,
    top = 24,
    bottom = 42;
  const px = (v) =>
    left +
    ((unit === "ppm" ? xmax - v : v - xmin) / (xmax - xmin)) *
      (w - left - right);
  const py = (v) =>
    h - bottom - ((v - ymin) / (ymax - ymin)) * (h - top - bottom);
  c.font = "10px Inter, sans-serif";
  c.lineWidth = 1;
  c.textAlign = "center";
  const ticks = w < 500 ? 4 : 8;
  for (let j = 0; j <= ticks; j++) {
    const v = xmin + ((xmax - xmin) * j) / ticks;
    c.strokeStyle = "#edf0f6";
    c.beginPath();
    c.moveTo(px(v), top);
    c.lineTo(px(v), h - bottom);
    c.stroke();
    c.fillStyle = "#6d7d94";
    c.fillText(fmt(v, 5), px(v), h - bottom + 20);
  }
  for (let j = 0; j < 4; j++) {
    const v = ymin + ((ymax - ymin) * j) / 3;
    c.textAlign = "right";
    c.fillStyle = "#99a5b5";
    c.fillText(fmt(v, 3), left - 8, py(v) + 3);
  }
  c.save();
  c.beginPath();
  c.rect(left, top, w - left - right, h - top - bottom);
  c.clip();
  for (const r of regions) {
    const a = px(r.lower),
      b = px(r.upper);
    c.fillStyle = r.draft ? "rgba(49,88,207,.10)" : "rgba(217,173,76,.10)";
    c.fillRect(Math.min(a, b), top, Math.abs(a - b), h - top - bottom);
    c.strokeStyle = r.draft ? "#6a87dd" : "#cfad63";
    c.setLineDash(r.draft ? [4, 3] : []);
    c.strokeRect(Math.min(a, b), top, Math.abs(a - b), h - top - bottom);
    c.setLineDash([]);
    c.fillStyle = r.draft ? "#3158cf" : "#9c7a36";
    c.textAlign = "center";
    const labelX =
      (Math.max(left, Math.min(a, b)) + Math.min(w - right, Math.max(a, b))) /
      2;
    if (Math.max(a, b) >= left && Math.min(a, b) <= w - right)
      c.fillText(r.draft ? "Draft region" : fmt(r.area, 4), labelX, top + 14);
  }
  c.strokeStyle = "#c1ccdb";
  c.beginPath();
  c.moveTo(left, py(0));
  c.lineTo(w - right, py(0));
  c.stroke();
  c.strokeStyle = "#3158cf";
  c.lineWidth = 1.25;
  c.beginPath();
  const visible = NMRView.indices(x, y, [xmin, xmax], w * 1.5);
  visible.forEach((i, j) =>
    j ? c.lineTo(px(x[i]), py(y[i])) : c.moveTo(px(x[i]), py(y[i])),
  );
  c.stroke();
  if (crosshair !== null && crosshair >= xmin && crosshair <= xmax) {
    c.strokeStyle = "#8c9dbb";
    c.lineWidth = 1;
    c.setLineDash([3, 4]);
    c.beginPath();
    c.moveTo(px(crosshair), top);
    c.lineTo(px(crosshair), h - bottom);
    c.stroke();
    c.setLineDash([]);
  }
  c.restore();
  c.textAlign = "center";
  c.fillStyle = "#697d9a";
  c.fillText(title || unit, w / 2, h - 7);
  return { left, right, top, bottom, width: w, height: h, range: [xmin, xmax] };
}
function drawSpectrum() {
  const s = project?.spectra[selected],
    view = currentView();
  const regions = Object.values(project?.integrals || {}).filter(
    (i) => i.spectrum_id === selected,
  );
  if (draft && draft.spectrumId === selected && draftIsVisible())
    regions.push({ ...draft, draft: true });
  if (gesture && gesture.mode !== "pan" && gesture.end !== null)
    regions.push({
      lower: Math.min(gesture.start, gesture.end),
      upper: Math.max(gesture.start, gesture.end),
      draft: true,
    });
  geometry = plot($("spectrumPlot"), s?.axis, s?.real, {
    unit: s?.axis_unit || "ppm",
    regions,
    range: view?.range,
    gain: view?.gain || 1,
    crosshair: hoverAxis,
  });
  if (view) {
    $("axisUnit").textContent = s.axis_unit;
    if (!["viewLower", "viewUpper"].includes(document.activeElement?.id)) {
      $("viewLower").value = Number(view.range[0].toPrecision(9));
      $("viewUpper").value = Number(view.range[1].toPrecision(9));
    }
    $("viewReadout").textContent =
      fmt(view.range[1], 5) +
      " → " +
      fmt(view.range[0], 5) +
      " " +
      s.axis_unit +
      " · " +
      fmt(view.gain, 3) +
      "× display";
    if (s.axis_unit !== "ppm")
      $("viewReadout").textContent =
        fmt(view.range[0], 5) +
        " → " +
        fmt(view.range[1], 5) +
        " " +
        s.axis_unit +
        " · " +
        fmt(view.gain, 3) +
        "× display";
  }
  if (geometry) globalThis.NMRBatch?.drawPeakLabels($("spectrumPlot"), geometry, selected);
  syncPlotTools();
}
function scheduleDraw() {
  if (drawPending) return;
  drawPending = true;
  requestAnimationFrame(() => {
    drawPending = false;
    drawSpectrum();
  });
}
function syncPlotTools() {
  const view = currentView(),
    spectrum = project?.spectra[selected];
  document.querySelectorAll("[data-plot-mode]").forEach((b) => {
    b.setAttribute("aria-pressed", String(b.dataset.plotMode === plotMode));
    b.disabled =
      busy ||
      !spectrum ||
      (b.dataset.plotMode === "integrate" && spectrum.axis_unit !== "ppm");
  });
  $("zoomBack").disabled = busy || !view?.history.length;
  for (const id of ["fitView", "gainUp", "gainDown"])
    $(id).disabled = busy || !view;
}
function changeView(next, remember = true) {
  const view = currentView();
  if (!view || !next) return;
  if (remember && next.some((v, i) => v !== view.range[i])) {
    view.history.push([...view.range]);
    if (view.history.length > 24) view.history.shift();
  }
  view.range = [...next];
  hoverAxis = null;
  drawSpectrum();
}
function cancelGesture() {
  if (gesture?.mode === "pan") currentView().range = [...gesture.original];
  gesture = null;
  $("spectrumPlot").dataset.dragging = "false";
  scheduleDraw();
}
function setPlotMode(mode) {
  if (busy) return;
  if (mode === "integrate" && project?.spectra[selected]?.axis_unit !== "ppm")
    return;
  cancelGesture();
  plotMode = mode;
  $("spectrumPlot").dataset.mode = mode;
  const regionTarget =
    workflow === "relaxation"
      ? "the shared relaxation region"
      : "a new integral";
  $("plotHelp").textContent = {
    inspect:
      "Move over the spectrum to read coordinates. Z: zoom · H: pan · I: region · F: full view.",
    zoom: "Drag across the region to magnify. Back restores the previous view. F shows the full spectrum.",
    pan: "Drag to move the visible range. Display changes never modify the data.",
    integrate:
      "Drag to select " +
      regionTarget +
      ". Review the bounds in the inspector, then save or fit. Esc cancels a drag.",
  }[mode];
  syncPlotTools();
}
function switchWorkflow(name) {
  workflow = name;
  document.querySelectorAll("[data-tab]").forEach((b) => {
    const current = b.dataset.tab === name;
    b.classList.toggle("active", current);
    b.setAttribute("aria-selected", String(current));
    b.tabIndex = current ? 0 : -1;
  });
  document
    .querySelectorAll(".panel")
    .forEach((p) => (p.hidden = p.id !== name));
  $("inspectorTitle").textContent = {
    organic: "Organic analysis",
    relaxation: "T₁ / T₂ relaxation",
    processing: "Spectrum processing",
    evidence: "Evidence & assignments",
    advanced: "Advanced operations",
    samples: "Samples & conditions",
    correlations: "Processed 2D correlations",
    structures: "Structure candidates",
    references: "Reference evidence",
    comparison: "Compare conditions",
  }[name];
  $("regionToolLabel").textContent =
    name === "relaxation" ? "Fit region" : "Integrate";
  setPlotMode(plotMode);
  syncDraftStatus();
  globalThis.NMRBatch?.workflow(name);
  scheduleDraw();
}
function eventAxis(e, limits = currentView()?.range) {
  if (!geometry || !limits) return null;
  const rect = $("spectrumPlot").getBoundingClientRect();
  return NMRView.at(
    (e.clientX - rect.left - geometry.left) /
      (geometry.width - geometry.left - geometry.right),
    limits,
    active().axis_unit === "ppm",
  );
}
function draftIsVisible() {
  return (
    draft &&
    (draft.kind === "fit" ? workflow === "relaxation" : workflow === "organic")
  );
}
function syncDraftStatus() {
  $("draftStatus").textContent = draftIsVisible()
    ? draft.kind === "fit"
      ? "Shared fit region selected · review the trace mappings before fitting."
      : "Unsaved integral region · review bounds, then Save integral"
    : "Saved results retain their evidence and revision.";
}
function draftFromFields(kind = "integral") {
  const s = project?.spectra[selected];
  if (!s) return;
  const lower = $(kind === "fit" ? "fitLower" : "lower").valueAsNumber,
    upper = $(kind === "fit" ? "fitUpper" : "upper").valueAsNumber;
  draft =
    Number.isFinite(lower) && Number.isFinite(upper) && lower < upper
      ? { spectrumId: s.id, version: s.version, kind, lower, upper }
      : null;
  syncDraftStatus();
  scheduleDraw();
}
function renderIntegrals() {
  const out = $("integralList");
  out.replaceChildren();
  for (const i of Object.values(project?.integrals || {}).filter(
    (i) => i.spectrum_id === selected,
  )) {
    const row = node("div", undefined, "region-row"),
      label = node("div");
    label.append(
      node("strong", i.name),
      node("small", fmt(i.lower) + "–" + fmt(i.upper) + " ppm · v" + i.version),
      node("b", fmt(i.area) + " intensity·ppm"),
    );
    const actions = node("div");
    const editButton = node("button", "Edit"),
      remove = node("button", "Remove");
    editButton.type = remove.type = "button";
    editButton.onclick = () => {
      $("integralId").value = i.id;
      $("integralName").value = i.name;
      $("lower").value = i.lower;
      $("upper").value = i.upper;
      $("saveIntegral").textContent = "Update integral";
      switchWorkflow("organic");
      draftFromFields();
    };
    remove.onclick = () => act(() => edit({ op: "remove", object_id: i.id }));
    actions.append(editButton, remove);
    row.append(label, actions);
    out.append(row);
  }
}
function resetIntegral() {
  $("integralId").value = "";
  $("saveIntegral").textContent = "Save integral";
  $("lower").value = "";
  $("upper").value = "";
  draft = null;
  $("draftStatus").textContent =
    "Saved results retain their evidence and revision.";
  scheduleDraw();
}
function table(headers, rows) {
  const t = node("table"),
    head = node("tr");
  for (const h of headers) head.append(node("th", h));
  const thead = node("thead");
  thead.append(head);
  t.append(thead);
  const body = node("tbody");
  for (const row of rows) {
    const tr = node("tr");
    for (const cell of row) tr.append(node("td", String(cell)));
    body.append(tr);
  }
  t.append(body);
  return t;
}
function renderTable() {
  const t = project?.tables[$("delayTable").value];
  options(
    $("delayColumn"),
    (t?.columns || []).map((c) => [c, c]),
    { blank: true },
  );
  options(
    $("sigmaColumn"),
    (t?.columns || []).map((c) => [c, c]),
    { blank: true },
  );
  $("tablePreview").replaceChildren();
  if (t)
    $("tablePreview").append(
      table(
        ["Row", ...t.columns],
        t.rows.slice(0, 64).map((r, i) => [i, ...t.columns.map((c) => r[c])]),
      ),
    );
}
function addMapping(sid = "", rowIndex = "") {
  const row = node("div", undefined, "mapping-row"),
    label = node("label", "Spectrum"),
    select = node("select");
  select.className = "map-spectrum";
  options(
    select,
    Object.values(project?.spectra || {})
      .filter((s) => s.domain === "frequency")
      .map((s) => [s.id, s.name]),
    { blank: true },
  );
  select.value = sid;
  label.append(select);
  const rl = node("label", "CSV row"),
    input = node("input");
  input.type = "number";
  input.min = "0";
  input.step = "1";
  input.required = true;
  input.className = "map-row";
  input.value = rowIndex;
  rl.append(input);
  const ex = node("label", "Exclude", "exclude"),
    cb = node("input");
  cb.type = "checkbox";
  cb.className = "map-exclude";
  ex.prepend(cb);
  const del = node("button", "Remove");
  del.type = "button";
  del.onclick = () => row.remove();
  row.append(label, rl, ex, del);
  $("mappings").append(row);
}
function renderAnalyses() {
  const out = $("analyses"),
    items = Object.values(project?.analyses || {});
  out.replaceChildren();
  $("resultCount").textContent = items.length + " analyses";
  if (!items.length) {
    out.append(
      node(
        "p",
        "Results will appear here with methods, assumptions and revision status.",
        "muted",
      ),
    );
    return;
  }
  for (const a of items.reverse()) {
    const card = node("article", undefined, "analysis " + a.state),
      head = node("div", undefined, "analysis-head");
    head.append(
      node("h3", a.name),
      node("span", a.state.toUpperCase(), "pill " + a.state),
    );
    if (["yield", "relaxation"].includes(a.kind)) {
      const load = node("button", "Load settings");
      load.onclick = () => loadAnalysisSettings(a);
      head.append(load);
    }
    card.append(head);
    const r = a.result;
    if (a.kind === "yield") {
      card.append(node("div", fmt(r.yield_percent, 6) + " %", "result-value"));
    } else if (a.kind === "relaxation") {
      const headline = node(
        "div",
        (r.model === "T1" ? "T₁" : "T₂") + " = " + fmt(r.T_s) + " s",
        "result-value",
      );
      headline.append(node("small", "  u(T) = " + fmt(r.u_T_s) + " s"));
      card.append(
        headline,
        node(
          "p",
          "Fit status: " + r.status + " · " + r.uncertainty_method,
          "hint",
        ),
      );
      if (r.residuals?.length) {
        const canvas = node("canvas");
        canvas.setAttribute("aria-label", "Fit residuals against elapsed time");
        card.append(canvas);
        requestAnimationFrame(() =>
          plot(canvas, r.time_s, r.residuals, {
            unit: "s",
            title: "Elapsed time / s · residual intensity",
          }),
        );
      }
      const rows = (r.time_s || []).map((t, i) => [
        fmt(t),
        fmt(r.signals[i]),
        fmt(r.predicted[i]),
        fmt(r.residuals[i]),
      ]);
      const wrap = node("div", undefined, "table-wrap");
      wrap.append(table(["Time / s", "Area", "Predicted", "Residual"], rows));
      card.append(wrap);
    } else if (a.kind === "peaks")
      card.append(
        node(
          "p",
          (r.peaks?.length || 0) + " signed peak candidates",
          "result-value",
        ),
      );
    globalThis.NMRBatch?.appendAnalysis(a, card);
    for (const warning of r.warnings || [])
      card.append(node("p", warning, "warning"));
    for (const assumption of r.assumptions || [])
      card.append(node("p", assumption, "hint"));
    if (a.state === "stale")
      card.append(
        node(
          "p",
          "Source evidence has changed. Review or recompute before reporting this result.",
          "warning",
        ),
      );
    const details = node("details");
    details.append(
      node("summary", "Method, mapping and source versions"),
      node(
        "pre",
        JSON.stringify(
          {
            id: a.id,
            parameters: a.parameters,
            source_versions: a.source_versions,
            result: r,
          },
          null,
          2,
        ),
      ),
    );
    card.append(details);
    out.append(card);
  }
}
function loadAnalysisSettings(analysis) {
  const c = analysis.parameters;
  if (analysis.kind === "yield") {
    const ids = {
      productIntegral: "product_integral_id",
      standardIntegral: "standard_integral_id",
      productProtons: "product_protons",
      standardProtons: "standard_protons",
      standardMol: "standard_mol",
      limitingMol: "limiting_mol",
      stoichiometry: "stoichiometric_factor",
    };
    for (const [id, key] of Object.entries(ids)) $(id).value = c[key];
    globalThis.NMRBatch?.loadYield(c);
    document.querySelector('[data-tab="organic"]').click();
  } else {
    $("delayTable").value = c.table_id;
    renderTable();
    $("delayColumn").value = c.delay_column;
    $("sigmaColumn").value = c.sigma_column || "";
    $("timeUnit").value = c.time_unit;
    $("fitModel").value = c.model;
    $("timeBasis").value = c.time_basis;
    $("delayMultiplier").value = c.delay_multiplier || "";
    $("fitLower").value = c.lower;
    $("fitUpper").value = c.upper;
    $("purpose").value = c.purpose;
    $("mappings").replaceChildren();
    c.spectrum_ids.forEach((id, i) => {
      addMapping(id, c.row_indices[i]);
      $("mappings").lastElementChild.querySelector(".map-exclude").checked =
        c.excluded_indices.includes(i);
    });
    document.querySelector('[data-tab="relaxation"]').click();
  }
  notice(
    "Saved settings loaded. Review current evidence before creating a new analysis.",
  );
}
function renderAssignments() {
  const out = $("assignmentList");
  out.replaceChildren();
  for (const a of Object.values(project?.assignments || {})) {
    const card = node("div", undefined, "assignment-card");
    card.append(
      node("strong", a.sample + " · " + a.atom + " · " + a.candidate),
      node("p", a.observation),
      node("span", a.status + " / " + a.state, "pill"),
    );
    globalThis.NMRBatch?.assignmentInfo(a, card);
    const editButton = node("button", "Revise"),
      remove = node("button", "Remove");
    editButton.onclick = () => {
      $("assignmentId").value = a.id;
      for (const key of ["sample", "atom", "candidate", "observation"])
        $(key).value = a[key];
      $("assignmentStatus").value = a.status;
      globalThis.NMRBatch?.loadAssignment(a);
      for (const option of $("evidenceIds").options)
        option.selected = a.evidence_ids.includes(option.value);
    };
    remove.onclick = () => act(() => edit({ op: "remove", object_id: a.id }));
    card.append(editButton, remove);
    out.append(card);
  }
}
function form(id, fn) {
  $(id).addEventListener("submit", (e) => {
    e.preventDefault();
    act(fn);
  });
}
document.querySelectorAll("[data-tab]").forEach((button) => {
  button.onclick = () => switchWorkflow(button.dataset.tab);
  button.onkeydown = (e) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    const tabs = [...document.querySelectorAll("[data-tab]")],
      index = tabs.indexOf(button);
    const next =
      e.key === "Home"
        ? 0
        : e.key === "End"
          ? tabs.length - 1
          : (index + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) %
            tabs.length;
    tabs[next].focus();
    switchWorkflow(tabs[next].dataset.tab);
  };
});
document
  .querySelectorAll("[data-plot-mode]")
  .forEach((b) => (b.onclick = () => setPlotMode(b.dataset.plotMode)));
$("spectrumSearch").oninput = renderLibrary;
$("lower").oninput = $("upper").oninput = () => draftFromFields();
$("fitLower").oninput = $("fitUpper").oninput = () => draftFromFields("fit");
$("fitView").onclick = () => {
  const v = currentView();
  if (v) {
    v.gain = 1;
    changeView(v.extent);
  }
};
$("zoomBack").onclick = () => {
  const v = currentView();
  if (v?.history.length) changeView(v.history.pop(), false);
};
for (const [id, multiplier] of [
  ["gainUp", 1.5],
  ["gainDown", 1 / 1.5],
])
  $(id).onclick = () => {
    const v = currentView();
    if (v) {
      v.gain = Math.max(0.1, Math.min(30, v.gain * multiplier));
      drawSpectrum();
    }
  };
form("viewForm", () => {
  const v = currentView();
  if (!v) throw Error("Select a spectrum.");
  const limits = NMRView.range(
    value("viewLower"),
    value("viewUpper"),
    v.extent,
  );
  if (!limits) throw Error("Enter two distinct bounds within the spectrum.");
  changeView(limits);
});
const spectrumCanvas = $("spectrumPlot");
spectrumCanvas.addEventListener("pointerdown", (e) => {
  if (busy || !geometry || e.button !== 0 || gesture) return;
  const rect = spectrumCanvas.getBoundingClientRect(),
    x = e.clientX - rect.left,
    y = e.clientY - rect.top;
  if (
    x < geometry.left ||
    x > geometry.width - geometry.right ||
    y < geometry.top ||
    y > geometry.height - geometry.bottom
  )
    return;
  spectrumCanvas.focus();
  if (plotMode === "inspect") return;
  e.preventDefault();
  gesture = {
    pointerId: e.pointerId,
    mode: plotMode,
    spectrumId: selected,
    version: active().version,
    start: eventAxis(e),
    end: null,
    startPixel: e.clientX,
    original: [...currentView().range],
  };
  spectrumCanvas.setPointerCapture(e.pointerId);
  spectrumCanvas.dataset.dragging = "true";
});
spectrumCanvas.addEventListener("pointermove", (e) => {
  if (!geometry || !selected) return;
  hoverAxis = eventAxis(e);
  $("cursorReadout").textContent =
    (active().axis_unit === "ppm" ? "δ " : "Time ") +
    fmt(hoverAxis, 7) +
    " " +
    active().axis_unit;
  if (gesture?.pointerId === e.pointerId) {
    if (
      gesture.spectrumId !== selected ||
      gesture.version !== active().version
    ) {
      cancelGesture();
      return;
    }
    gesture.end = eventAxis(e, gesture.original);
    if (gesture.mode === "pan")
      currentView().range = NMRView.pan(
        gesture.original,
        gesture.start - gesture.end,
        currentView().extent,
      );
  }
  scheduleDraw();
});
spectrumCanvas.addEventListener("pointerup", (e) => {
  if (!gesture || gesture.pointerId !== e.pointerId) return;
  const g = gesture;
  gesture = null;
  spectrumCanvas.dataset.dragging = "false";
  if (spectrumCanvas.hasPointerCapture(e.pointerId))
    spectrumCanvas.releasePointerCapture(e.pointerId);
  if (g.spectrumId !== selected || g.version !== active().version) {
    drawSpectrum();
    return;
  }
  if (g.mode === "pan") {
    if (currentView().range.some((v, i) => v !== g.original[i])) {
      currentView().history.push(g.original);
      if (currentView().history.length > 24) currentView().history.shift();
    }
  } else if (Math.abs(e.clientX - g.startPixel) >= 4) {
    const limits = NMRView.range(
      g.start,
      eventAxis(e, g.original),
      currentView().extent,
    );
    if (limits && g.mode === "zoom") changeView(limits);
    else if (limits && g.mode === "integrate") {
      if (workflow === "relaxation") {
        $("fitLower").value = Number(limits[0].toPrecision(9));
        $("fitUpper").value = Number(limits[1].toPrecision(9));
        draft = {
          spectrumId: selected,
          version: active().version,
          kind: "fit",
          lower: limits[0],
          upper: limits[1],
        };
        $("draftStatus").textContent =
          "Shared fit region selected · review the trace mappings before fitting.";
        notice("Shared relaxation bounds selected. No fit has been run.");
      } else {
        switchWorkflow("organic");
        resetIntegral();
        $("lower").value = Number(limits[0].toPrecision(9));
        $("upper").value = Number(limits[1].toPrecision(9));
        draftFromFields();
        notice(
          "Integral region selected. Review its name and bounds, then Save integral.",
        );
      }
    }
  }
  drawSpectrum();
});
spectrumCanvas.addEventListener("pointercancel", cancelGesture);
spectrumCanvas.addEventListener("lostpointercapture", () => {
  if (gesture) cancelGesture();
});
spectrumCanvas.addEventListener("pointerleave", () => {
  if (!gesture) {
    hoverAxis = null;
    scheduleDraw();
  }
});
document.addEventListener("keydown", (e) => {
  if (
    e.ctrlKey ||
    e.metaKey ||
    e.altKey ||
    busy ||
    globalThis.NMRBatch?.isBatch ||
    e.target.closest("input,select,textarea,[contenteditable=true]")
  )
    return;
  const key = e.key.toLowerCase();
  const modes = { v: "inspect", z: "zoom", h: "pan", i: "integrate" };
  if (modes[key]) {
    e.preventDefault();
    setPlotMode(modes[key]);
  } else if (key === "f") {
    e.preventDefault();
    $("fitView").click();
  } else if (key === "escape") {
    cancelGesture();
    setPlotMode("inspect");
  }
});
$("refresh").onclick = () => act(refresh);
$("spectrumSelect").onchange = () => {
  cancelGesture();
  selected = $("spectrumSelect").value;
  resetIntegral();
  render();
};
$("newIntegral").onclick = resetIntegral;
$("delayTable").onchange = renderTable;
$("addMapping").onclick = () => addMapping();
form("createForm", async () => {
  await tool("nmr_project", { action: "create", name: $("newName").value });
  await refresh();
});
form("importForm", () => edit({ op: "import", path: $("importPath").value, ...(globalThis.NMRBatch?.importCommand() || {}) }));
$("demo").onclick = () =>
  act(async () => {
    await edit({ op: "demo" });
    $("lower").value = "1.7";
    $("upper").value = "2.3";
    $("productProtons").value = "3";
    $("standardProtons").value = "6";
    $("standardMol").value = "0.001";
    $("limitingMol").value = "0.001";
    $("fitLower").value = "3.7";
    $("fitUpper").value = "4.3";
    $("timeUnit").value = "ms";
    $("delayTable").value = Object.keys(project.tables)[0];
    renderTable();
    $("delayColumn").value = "delay_ms";
    $("mappings").replaceChildren();
    Object.values(project.spectra)
      .filter(
        (s) => s.metadata.synthetic && typeof s.metadata.delay_s === "number",
      )
      .forEach((s, i) => addMapping(s.id, i));
  });
form("integralForm", async () => {
  if (
    draft &&
    (draft.spectrumId !== active().id || draft.version !== active().version)
  )
    throw Error("The draft source changed. Select the region again.");
  await edit({
    op: "integrate",
    spectrum_id: active().id,
    name: $("integralName").value,
    lower: value("lower"),
    upper: value("upper"),
    integral_id: $("integralId").value || null,
  });
  resetIntegral();
});
form("yieldForm", () =>
  edit({
    op: "yield",
    product_integral_id: $("productIntegral").value,
    standard_integral_id: $("standardIntegral").value,
    product_protons: value("productProtons"),
    standard_protons: value("standardProtons"),
    standard_mol: value("standardMol"),
    limiting_mol: value("limitingMol"),
    stoichiometric_factor: value("stoichiometry"),
    ...(globalThis.NMRBatch?.yieldCommand() || {}),
  }),
);
form("fitForm", async () => {
  const rows = [...document.querySelectorAll(".mapping-row")];
  await edit({
    op: "fit",
    spectrum_ids: rows.map((r) => r.querySelector(".map-spectrum").value),
    table_id: $("delayTable").value,
    row_indices: rows.map((r) => r.querySelector(".map-row").valueAsNumber),
    delay_column: $("delayColumn").value,
    sigma_column: $("sigmaColumn").value || null,
    time_unit: $("timeUnit").value,
    model: $("fitModel").value,
    time_basis: $("timeBasis").value,
    delay_multiplier:
      $("timeBasis").value === "echo_interval"
        ? value("delayMultiplier")
        : null,
    lower: value("fitLower"),
    upper: value("fitUpper"),
    excluded_indices: rows.flatMap((r, i) =>
      r.querySelector(".map-exclude").checked ? [i] : [],
    ),
    purpose: $("purpose").value,
  });
  if (draft?.kind === "fit") {
    draft = null;
    syncDraftStatus();
    scheduleDraw();
  }
});
form("processForm", () =>
  edit({
    op: "process",
    spectrum_id: active().id,
    method: $("processMethod").value,
    ph0_deg: value("ph0"),
    ph1_deg: value("ph1"),
    pivot_ppm: value("pivot"),
    reference_shift_ppm: value("referenceShift"),
    zero_fill_factor: Number($("zeroFill").value),
    line_broadening_hz: value("lb"),
    regions: JSON.parse($("baselineRegions").value),
  }),
);
form("peakForm", () =>
  edit({
    op: "peaks",
    spectrum_id: active().id,
    prominence: value("prominence"),
  }),
);
form("assignmentForm", async () => {
  await edit({
    op: "assign",
    assignment_id: $("assignmentId").value || null,
    sample: $("sample").value,
    atom: $("atom").value,
    candidate: $("candidate").value,
    observation: $("observation").value,
    evidence_ids: [...$("evidenceIds").selectedOptions].map((o) => o.value),
    status: $("assignmentStatus").value,
    ...(globalThis.NMRBatch?.assignmentCommand() || {}),
  });
  $("assignmentId").value = "";
});
form("undoForm", () =>
  edit({ op: "undo", target_revision: value("undoRevision") }),
);
form("advancedForm", () => edit(JSON.parse($("commandJson").value)));
$("loadHelp").onclick = () =>
  act(async () => {
    const help = await tool("nmr_help", {
      operation: $("helpOperation").value,
    });
    $("helpSchema").textContent = JSON.stringify(help.input_schema, null, 2);
  });
$("export").onclick = () =>
  act(async () => {
    if (!project) throw Error("Open a project first.");
    const a = await tool("nmr_export", { revision: project.revision });
    const out = $("artifact");
    out.replaceChildren(
      node("strong", "Revision " + a.revision + " export is ready"),
      node("div", a.name + " · " + a.size.toLocaleString() + " bytes"),
      node("div", "SHA-256 " + a.sha256),
    );
    const button = node("button", "Download reopenable project bundle");
    button.onclick = () =>
      act(async () => {
        const response = await fetch("/api/artifact/" + a.id, { headers });
        if (!response.ok) throw Error("Artifact could not be read.");
        const blob = await response.blob(),
          url = URL.createObjectURL(blob),
          link = node("a");
        link.href = url;
        link.download = a.name;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 60000);
        notice(
          "Download requested for revision " +
            a.revision +
            ". Verify the saved file in your browser.",
        );
      });
    out.append(button);
    out.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });
globalThis.NMRWorkbench = {
  get project() { return project; },
  get activeSpectrumId() { return selected; },
  get busy() { return busy; },
  node, fmt, act, edit, notice, switchWorkflow, renderProject: render,
  async closeWorkbench() {
    const response = await fetch("/api/quit", { method: "POST", headers });
    if (!response.ok) throw Error("The workbench did not confirm the close request.");
    return response.json();
  },
  async privateBlob(path) {
    const response = await fetch(path, { headers });
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}));
      throw Error(problem.error?.message || "The preserved source could not be read.");
    }
    return response.blob();
  },
};
window.addEventListener("resize", scheduleDraw);
new ResizeObserver(scheduleDraw).observe($("spectrumPlot"));
document.fonts.ready.then(scheduleDraw);
switchWorkflow("organic");
act(async () => {
  if (!token)
    throw Error(
      "Open the workbench using the complete URL printed by its launcher.",
    );
  await refresh();
  const help = await tool("nmr_help", {});
  options(
    $("helpOperation"),
    help.operations.map((op) => [op, op]),
  );
});
