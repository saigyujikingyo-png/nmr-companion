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
  select.replaceChildren();
  if (blank) select.add(new Option("Select…", ""));
  for (const [id, label] of items) select.add(new Option(label, id));
  if ([...select.options].some((o) => o.value === old)) select.value = old;
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
  $("spectrumCount").textContent = spectra.length + " spectra";
  options(
    $("spectrumSelect"),
    spectra.map((s) => [s.id, s.name]),
  );
  $("spectrumSelect").value = selected || "";
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
  for (const key of ["spectra", "grids", "integrals", "analyses"])
    for (const item of Object.values(project?.[key] || {}))
      evidence.push([
        item.id,
        (item.name || item.id) + (item.state === "stale" ? " [stale]" : ""),
      ]);
  options($("evidenceIds"), evidence);
  $("undoRevision").max = Math.max(0, (project?.revision || 1) - 1);
}
function plot(
  canvas,
  x,
  y,
  { unit = "ppm", title = "", regions = [], zero = true } = {},
) {
  const rect = canvas.getBoundingClientRect(),
    w = Math.max(300, rect.width),
    h = rect.height || 300,
    dpr = devicePixelRatio || 1;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const c = canvas.getContext("2d");
  c.scale(dpr, dpr);
  c.clearRect(0, 0, w, h);
  if (!x?.length) {
    c.fillStyle = "#7c909b";
    c.font = "14px Segoe UI";
    c.fillText("Import a spectrum to begin.", 35, h / 2);
    return;
  }
  let xmin = Infinity,
    xmax = -Infinity,
    ymin = zero ? 0 : Infinity,
    ymax = zero ? 0 : -Infinity;
  for (let i = 0; i < x.length; i++) {
    xmin = Math.min(xmin, x[i]);
    xmax = Math.max(xmax, x[i]);
    ymin = Math.min(ymin, y[i]);
    ymax = Math.max(ymax, y[i]);
  }
  if (xmin === xmax) xmax = xmin + 1;
  const span = ymax - ymin || 1;
  ymin -= span * 0.08;
  ymax += span * 0.12;
  const left = 55,
    right = 24,
    top = 20,
    bottom = 42,
    px = (v) =>
      left +
      ((unit === "ppm" ? xmax - v : v - xmin) / (xmax - xmin)) *
        (w - left - right),
    py = (v) => h - bottom - ((v - ymin) / (ymax - ymin)) * (h - top - bottom);
  c.font = "11px Segoe UI";
  c.lineWidth = 1;
  c.textAlign = "center";
  for (let j = 0; j <= 8; j++) {
    const v = xmin + ((xmax - xmin) * j) / 8;
    c.strokeStyle = "#ecf1f3";
    c.beginPath();
    c.moveTo(px(v), top);
    c.lineTo(px(v), h - bottom);
    c.stroke();
    c.fillStyle = "#758995";
    c.fillText(fmt(v, 4), px(v), h - bottom + 21);
  }
  for (let j = 0; j < 4; j++) {
    const v = ymin + ((ymax - ymin) * j) / 3;
    c.textAlign = "right";
    c.fillStyle = "#91a1aa";
    c.fillText(fmt(v, 3), left - 9, py(v) + 4);
  }
  for (const r of regions) {
    const a = px(r.lower),
      b = px(r.upper);
    c.fillStyle = "rgba(222,165,56,.15)";
    c.fillRect(Math.min(a, b), top, Math.abs(a - b), h - top - bottom);
    c.fillStyle = "#a17423";
    c.textAlign = "center";
    c.fillText(fmt(r.area, 4), (a + b) / 2, top + 13);
  }
  c.strokeStyle = "#b5c7cc";
  c.beginPath();
  c.moveTo(left, py(0));
  c.lineTo(w - right, py(0));
  c.stroke();
  // Display-only min/max buckets retain narrow positive and negative features.
  const indices = new Set([0, x.length - 1]),
    step = Math.max(1, Math.ceil(x.length / (w * 1.5)));
  for (let i = 0; i < x.length; i += step) {
    let lo = i,
      hi = i;
    for (let j = i; j < Math.min(i + step, x.length); j++) {
      if (y[j] < y[lo]) lo = j;
      if (y[j] > y[hi]) hi = j;
    }
    indices.add(lo);
    indices.add(hi);
  }
  c.strokeStyle = "#087d80";
  c.lineWidth = 1.35;
  c.beginPath();
  let first = true;
  for (const i of [...indices].sort((a, b) => a - b)) {
    if (first) c.moveTo(px(x[i]), py(y[i]));
    else c.lineTo(px(x[i]), py(y[i]));
    first = false;
  }
  c.stroke();
  c.textAlign = "center";
  c.fillStyle = "#506e7b";
  c.fillText(title || unit, w / 2, h - 7);
}
function drawSpectrum() {
  const s = project?.spectra[selected];
  plot($("spectrumPlot"), s?.axis, s?.real, {
    unit: s?.axis_unit || "ppm",
    regions: Object.values(project?.integrals || {}).filter(
      (i) => i.spectrum_id === selected,
    ),
  });
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
    } else
      card.append(
        node(
          "p",
          (r.peaks?.length || 0) + " signed peak candidates",
          "result-value",
        ),
      );
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
    const editButton = node("button", "Revise"),
      remove = node("button", "Remove");
    editButton.onclick = () => {
      $("assignmentId").value = a.id;
      for (const key of ["sample", "atom", "candidate", "observation"])
        $(key).value = a[key];
      $("assignmentStatus").value = a.status;
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
document.querySelectorAll("[data-tab]").forEach(
  (button) =>
    (button.onclick = () => {
      document
        .querySelectorAll("[data-tab]")
        .forEach((b) => b.classList.toggle("active", b === button));
      document
        .querySelectorAll(".panel")
        .forEach((p) => (p.hidden = p.id !== button.dataset.tab));
    }),
);
$("refresh").onclick = () => act(refresh);
$("spectrumSelect").onchange = () => {
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
form("importForm", () => edit({ op: "import", path: $("importPath").value }));
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
form("integralForm", () =>
  edit({
    op: "integrate",
    spectrum_id: active().id,
    name: $("integralName").value,
    lower: value("lower"),
    upper: value("upper"),
    integral_id: $("integralId").value || null,
  }),
);
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
  }),
);
form("fitForm", () => {
  const rows = [...document.querySelectorAll(".mapping-row")];
  return edit({
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
  });
window.addEventListener("resize", drawSpectrum);
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
