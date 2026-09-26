/* Shared first-batch workbench. Canvas gestures edit drafts; only Save commits. */
(function (root) {
  "use strict";
  const clamp = (n) => Math.max(0, Math.min(1, n));
  function bounds(axis) {
    return [Math.min(axis[0], axis.at(-1)), Math.max(axis[0], axis.at(-1))];
  }
  function axisAt(f, axis, reverse = false) {
    const [lo, hi] = bounds(axis);
    return reverse ? hi - clamp(f) * (hi - lo) : lo + clamp(f) * (hi - lo);
  }
  function fraction(value, axis, reverse = false) {
    const [lo, hi] = bounds(axis);
    return reverse ? (hi - value) / (hi - lo || 1) : (value - lo) / (hi - lo || 1);
  }
  function nearest(axis, value) {
    let best = 0;
    for (let i = 1; i < axis.length; i++)
      if (Math.abs(axis[i] - value) < Math.abs(axis[best] - value)) best = i;
    return best;
  }
  function gridPoint(grid, x, y) {
    const column = nearest(grid.x, x), row = nearest(grid.y, y);
    return {column, row, x: grid.x[column], y: grid.y[row], intensity: grid.z[row][column]};
  }
  function signedBins(grid, width, height) {
    const positive = new Float64Array(width * height), negative = new Float64Array(width * height);
    const columns = grid.x.map((x) => Math.min(width - 1, Math.floor(clamp(fraction(x, grid.x, true)) * width)));
    let maximum = 0;
    for (let y = 0; y < grid.y.length; y++) {
      const row = Math.min(height - 1, Math.floor(clamp(fraction(grid.y[y], grid.y)) * height));
      for (let x = 0; x < grid.x.length; x++) {
        const value = grid.z[y][x], i = row * width + columns[x];
        positive[i] = Math.max(positive[i], value);
        negative[i] = Math.min(negative[i], value);
        maximum = Math.max(maximum, Math.abs(value));
      }
    }
    return {positive, negative, maximum};
  }
  function rectangle(a, b) {
    const x = Math.min(clamp(a.x), clamp(b.x)), y = Math.min(clamp(a.y), clamp(b.y));
    const width = Math.abs(clamp(a.x) - clamp(b.x)), height = Math.abs(clamp(a.y) - clamp(b.y));
    return width > 0 && height > 0 ? {x, y, width, height} : null;
  }
  function hitAtom(atoms, point, tolerance) {
    let hit = null, distance = tolerance;
    for (const atom of atoms) {
      const d = Math.hypot(atom.x - point.x, atom.y - point.y);
      if (d <= distance) { hit = atom; distance = d; }
    }
    return hit;
  }
  function processingNumbers(text) {
    if (!text.trim()) return null;
    const parts = text.split(",").map((part) => part.trim());
    if (parts.some((part) => !/^[0-9]+$/.test(part) || !Number.isSafeInteger(Number(part)) || Number(part) < 1))
      throw Error("Processing numbers must be comma-separated positive integers.");
    const numbers = parts.map(Number);
    if (new Set(numbers).size !== numbers.length) throw Error("Select each processing number only once.");
    return numbers;
  }
  const geometry = {axisAt, fraction, gridPoint, signedBins, rectangle, hitAtom, processingNumbers};
  if (typeof module === "object" && module.exports) module.exports = geometry;
  if (typeof document === "undefined") return;

  const api = root.NMRWorkbench, $ = (id) => document.getElementById(id);
  const n = api.node, fmt = api.fmt, p = () => api.project;
  const items = (key) => Object.values(p()?.[key] || {});
  const collections = ["spectra", "grids", "tables", "integrals", "analyses", "samples", "structures", "peaklabels", "crosspeaks", "attachments", "annotations", "assignments"];
  const batchTabs = new Set(["samples", "correlations", "structures", "references", "comparison"]);
  let activeWorkflow = "organic", lastProject = null, saving = false, drawQueued = false;
  let sampleVersion = null, structureVersion = null, crosspeakVersion = null, peakVersion = null, annotationVersion = null, assignmentVersion = null;
  let structure = {atoms: [], bonds: []}, chosenAtom = null, structureMode = "select", bondStart = null;
  let structureGesture = null, structureFrame = null, gridFrame = null, gridDraftSource = null;
  let referenceImage = null, previewUrl = null, previewKey = "", previewRequest = 0, annotationGesture = null, annotationDraftSource = null;

  function name(object) { return object?.name || object?.label || object?.id || "Unknown object"; }
  function findObject(id) {
    for (const key of collections) if (p()?.[key]?.[id]) return p()[key][id];
    return null;
  }
  function objectLabel(id) { const object = findObject(id); return object ? name(object) : id; }
  function state(object) { return "v" + object.version + " · " + (object.state || "current"); }
  function selectedIds(id) { return [...$(id).selectedOptions].map((option) => option.value).filter(Boolean); }
  function choose(id, entries, blank = true) {
    const select = $(id), previous = new Set([...select.selectedOptions].map((option) => option.value));
    select.replaceChildren();
    if (blank && !select.multiple) select.add(new Option("Select…", ""));
    for (const [value, text] of entries) {
      const option = new Option(text, value);
      option.selected = previous.has(value);
      select.add(option);
    }
    if (!select.multiple && ![...select.options].some((option) => previous.has(option.value))) select.value = "";
  }
  function markSelected(id, ids) { for (const option of $(id).options) option.selected = ids.includes(option.value); }
  function entries(key, filter = () => true) { return items(key).filter(filter).map((item) => [item.id, name(item) + " · " + state(item)]); }
  function evidenceEntries() {
    return ["spectra", "grids", "integrals", "analyses", "peaklabels", "crosspeaks", "attachments", "annotations"]
      .flatMap((key) => entries(key));
  }
  function numeric(id, optional = false) {
    if (optional && $(id).value.trim() === "") return null;
    const value = $(id).valueAsNumber;
    if (!Number.isFinite(value)) throw Error("Enter a finite number for " + ($(id).labels?.[0]?.textContent || id) + ".");
    return value;
  }
  function field(parent, id, label, config = {}) {
    const labelNode = n("label", label), tag = config.type === "select" ? "select" : config.type === "textarea" ? "textarea" : "input";
    const control = n(tag);
    control.id = id;
    if (tag === "input") control.type = config.type || "text";
    if (config.required) control.required = true;
    if (config.multiple) { control.multiple = true; control.size = config.size || 5; }
    if (config.rows) control.rows = config.rows;
    if (config.min !== undefined) control.min = config.min;
    if (config.max !== undefined) control.max = config.max;
    if (control.type === "number") control.step = config.step || "any";
    if (config.placeholder) control.placeholder = config.placeholder;
    if (config.items) for (const [value, text] of config.items) control.add(new Option(text, value));
    if (config.value !== undefined) control.value = config.value;
    labelNode.append(control); parent.append(labelNode);
    return control;
  }
  function button(parent, text, fn, cls = "") {
    const b = n("button", text, cls); b.type = "button"; b.onclick = fn; parent.append(b); return b;
  }
  function submit(parent, text) { const b = n("button", text, "primary"); b.type = "submit"; parent.append(b); return b; }
  function form(parent, id, fn) {
    const f = n("form"); f.id = id;
    f.addEventListener("submit", (event) => { event.preventDefault(); api.act(fn); });
    parent.append(f); return f;
  }
  function group(parent, cls = "two-col") { const out = n("div", undefined, cls); parent.append(out); return out; }
  function hint(parent, text) { parent.append(n("p", text, "hint")); }
  function title(parent, heading, text) { parent.append(n("h2", heading)); if (text) hint(parent, text); }
  function hidden(parent, id) { const input = n("input"); input.type = "hidden"; input.id = id; parent.append(input); }
  function table(headers) {
    const t = n("table"), head = n("thead"), tr = n("tr"), body = n("tbody");
    for (const text of headers) { const th = n("th", text); th.scope = "col"; tr.append(th); }
    head.append(tr); t.append(head, body); return {table:t, body};
  }
  function dataTable(parent, headers, rows) {
    const t = table(headers);
    for (const row of rows) { const tr = n("tr"); row.forEach((value) => tr.append(n("td", value === null || value === undefined ? "Unavailable" : String(value)))); t.body.append(tr); }
    const wrap = n("div", undefined, "batch-table-wrap"); wrap.append(t.table); parent.append(wrap);
  }
  function collectionCards(parent, objects, renderCard, empty) {
    parent.replaceChildren();
    if (!objects.length) { hint(parent, empty); return; }
    for (const object of objects) {
      const card = n("article", undefined, "batch-card"), head = n("div", undefined, "analysis-head");
      head.append(n("h3", name(object)), n("span", state(object), "pill " + (object.state || "current")));
      card.append(head); renderCard(object, card); parent.append(card);
    }
  }
  async function save(command, afterward = () => {}) {
    saving = true;
    try { const receipt = await api.edit(command); afterward(receipt); render(); return receipt; }
    finally { saving = false; }
  }
  function remove(id) { api.act(() => save({op:"remove", object_id:id})); }
  function fieldset(parent, summary) { const detail = n("details"); detail.append(n("summary", summary)); parent.append(detail); return detail; }
  function workspace(name, heading, subtitle) {
    const section = n("section", undefined, "batch-view"); section.id = "view-" + name; section.hidden = true;
    const head = n("div", undefined, "batch-heading"); title(head, heading, subtitle); section.append(head);
    $("batchWorkspace").append(section); return section;
  }

  function buildSamples() {
    const panel = $("samples"); title(panel, "Sample provenance", "Own and reference evidence keep separate identities. Conditions belong to the named sample.");
    field(panel,"sampleEditor","Load saved sample",{type:"select"}).onchange = () => loadSample(p()?.samples[$("sampleEditor").value]);
    button(panel,"New sample",()=>loadSample(null));
    const f = form(panel,"sampleForm",async()=> {
      const additives = [...$("additiveRows").children].map((row)=>({name:row.querySelector(".additive-name").value,
        concentration_mol_l:row.querySelector(".additive-concentration").value === "" ? null : row.querySelector(".additive-concentration").valueAsNumber,
        notes:row.querySelector(".additive-notes").value}));
      await save({op:"sample", ...($("sampleId").value ? {sample_id:$("sampleId").value}:{}), name:$("sampleName").value,
        role:$("sampleRole").value, object_ids:selectedIds("sampleObjects"), stage:$("sampleStage").value, parent_ids:selectedIds("sampleParents"),
        transformation:$("sampleTransformation").value, conditions:{solvent:$("sampleSolvent").value || null,temperature_k:numeric("sampleTemperature",true),additives},
        reference:$("sampleReference").value,notes:$("sampleNotes").value},()=>loadSample(null));
    });
    hidden(f,"sampleId"); field(f,"sampleName","Sample name",{required:true});
    field(f,"sampleRole","Evidence role",{type:"select",items:[["unknown","Unknown — classify explicitly"],["own","Own experimental sample"],["reference","Reference sample"],["synthetic","Synthetic software fixture"]]});
    field(f,"sampleObjects","Owned spectra / grids / delay tables",{type:"select",multiple:true});
    field(f,"sampleStage","Stage / material identity",{placeholder:"Starting material, product, recovered material…"});
    field(f,"sampleParents","Parent sample(s)",{type:"select",multiple:true,size:3});
    field(f,"sampleTransformation","Transformation / relationship",{type:"textarea",rows:2});
    const conditionFields=group(f); field(conditionFields,"sampleSolvent","Solvent"); field(conditionFields,"sampleTemperature","Temperature · K",{type:"number",min:0});
    const additives=n("div");additives.id="additiveRows";f.append(n("h3","Additives"),additives);
    button(f,"Add additive",()=>addAdditive());
    field(f,"sampleReference","Reference / source citation",{type:"textarea",rows:2});field(f,"sampleNotes","Notes",{type:"textarea",rows:2});submit(f,"Save sample");
    const view=workspace("samples","Samples & their conditions","Shared sample identities connect numerical data, structures and reference evidence.");
    const cards=n("div",undefined,"batch-cards");cards.id="sampleCards";view.append(cards);
  }
  function addAdditive(additive={}) {
    const row=n("div",undefined,"additive-row");
    for (const [key,label,type] of [["name","Additive name","text"],["concentration","Concentration · mol L⁻¹","number"],["notes","Additive notes","text"]]) {
      const l=n("label",label),i=n("input");i.type=type;i.className="additive-"+key;
      if (type==="number") {i.step="any";i.min=0;} if(key==="name")i.required=true;
      i.value=key==="concentration"?additive.concentration_mol_l??"":additive[key]||"";l.append(i);row.append(l);
    }
    button(row,"Remove additive",()=>row.remove());$("additiveRows").append(row);
  }
  function loadSample(sample) {
    $("sampleForm").reset();$("sampleId").value=sample?.id||"";sampleVersion=sample?.version??null;
    $("sampleEditor").value=sample?.id||"";$("additiveRows").replaceChildren();
    for(const [id,key] of [["sampleName","name"],["sampleRole","role"],["sampleStage","stage"],["sampleTransformation","transformation"],["sampleReference","reference"],["sampleNotes","notes"]]) $(id).value=sample?.[key]??(key==="role"?"unknown":"");
    $("sampleSolvent").value=sample?.conditions?.solvent||"";$("sampleTemperature").value=sample?.conditions?.temperature_k??"";
    markSelected("sampleObjects",sample?.object_ids||[]);markSelected("sampleParents",sample?.parent_ids||[]);
    for(const additive of sample?.conditions?.additives||[])addAdditive(additive);
  }
  function conditionText(sample) {
    const c=sample?.conditions||{},additives=(c.additives||[]).map((a)=>a.name+(a.concentration_mol_l!==null&&a.concentration_mol_l!==undefined?" "+fmt(a.concentration_mol_l)+" mol L⁻¹":" (concentration unavailable)")).join("; ");
    return ["Solvent: "+(c.solvent||"unavailable"),"Temperature: "+(c.temperature_k===null||c.temperature_k===undefined?"unavailable":fmt(c.temperature_k)+" K"),"Additives: "+(additives||"none recorded")].join(" · ");
  }
  function renderSamples() {
    choose("sampleEditor",entries("samples"));choose("sampleObjects",["spectra","grids","tables"].flatMap((key)=>entries(key)),false);
    choose("sampleParents",entries("samples",(s)=>s.id!==$("sampleId").value),false);
    collectionCards($("sampleCards"),items("samples"),(sample,card)=>{
      card.append(n("p",sample.role.toUpperCase()+" · "+(sample.stage||"Stage unspecified"),"sample-role"));hint(card,conditionText(sample));
      if(sample.parent_ids.length)hint(card,"From: "+sample.parent_ids.map(objectLabel).join(", "));
      if(sample.transformation)card.append(n("p",sample.transformation));
      hint(card,"Owned data: "+(sample.object_ids.map(objectLabel).join(", ")||"None linked"));
      if(sample.reference)hint(card,"Reference: "+sample.reference);if(sample.notes)card.append(n("p",sample.notes));
      button(card,"Edit sample",()=>loadSample(sample));
    },"Create a sample to declare data ownership, material stage and conditions.");
  }

  function buildStructures() {
    const panel=$("structures");title(panel,"Editable structure candidates","Drawings store your interpretation. Stereochemical labels are reviewer-entered; no automatic CIP or structure confirmation is implied.");
    field(panel,"structureEditor","Load candidate",{type:"select"}).onchange=()=>loadStructure(p()?.structures[$("structureEditor").value]);
    const actions=group(panel,"actions");button(actions,"New candidate",()=>loadStructure(null));button(actions,"Duplicate as alternative",()=>{
      const old=p()?.structures[$("structureId").value];if(!old){api.notice("Load a saved candidate first.",true);return;}
      const copy=structuredClone(old);copy.id="";copy.name=old.name+" alternative";copy.status="proposed";copy.alternative_group=old.alternative_group||old.name;loadStructure(copy);
    });
    const f=form(panel,"structureForm",async()=>{
      if(!structure.atoms.length)throw Error("Add at least one atom to the candidate.");
      await save({op:"structure",...($("structureId").value?{structure_id:$("structureId").value}:{}),name:$("structureName").value,sample_id:$("structureSample").value,
        atoms:structure.atoms,bonds:structure.bonds,description:$("structureDescription").value,alternative_group:$("alternativeGroup").value,
        evidence_ids:selectedIds("structureEvidence"),status:$("structureStatus").value},()=>loadStructure(null));
    });
    hidden(f,"structureId");field(f,"structureName","Candidate name",{required:true});field(f,"structureSample","Sample",{type:"select",required:true});
    field(f,"alternativeGroup","Alternative group",{placeholder:"Shared label for competing interpretations"});
    field(f,"structureDescription","Structural and stereochemical reasoning",{type:"textarea",rows:3});
    field(f,"structureEvidence","Supporting evidence",{type:"select",multiple:true});
    field(f,"structureStatus","Review state",{type:"select",items:[["proposed","Proposed"],["confirmed","Confirmed by reviewer — evidence required"]]});submit(f,"Save candidate");
    title(panel,"Drawing tools");field(panel,"newAtomElement","New atom element",{value:"C"});field(panel,"newAtomLabel","New atom label · optional",{placeholder:"Auto-numbered when empty"});field(panel,"newAtomStereo","New atom stereochemical context",{placeholder:"R, S, pro-R, relative configuration…"});
    const atomPosition=group(panel);field(atomPosition,"newAtomX","New atom x · drawing coordinate",{type:"number",value:0.5,min:-10000,max:10000});field(atomPosition,"newAtomY","New atom y · drawing coordinate",{type:"number",value:0.5,min:-10000,max:10000});
    button(panel,"Add atom from fields",()=>api.act(()=>createAtomAt({x:numeric("newAtomX"),y:numeric("newAtomY")})));

    const bonds=fieldset(panel,"Add a bond using labelled fields");field(bonds,"bondFrom","Bond from atom",{type:"select"});field(bonds,"bondTo","Bond to atom",{type:"select"});
    field(bonds,"bondOrder","Bond order",{type:"select",items:[["1","Single"],["2","Double"],["3","Triple"],["1.5","Aromatic (1.5)"]]});
    field(bonds,"bondStereo","Bond stereochemistry · from A to B",{type:"select",items:[["none","None"],["wedge","Solid wedge"],["hash","Hashed wedge"],["either","Unknown / either"]]});button(bonds,"Add bond",()=>addBond($("bondFrom").value,$("bondTo").value));
    const view=workspace("structures","Structure & assignment canvas","Drag atoms to edit a draft. Save candidate commits one revision. Atom labels and bond endpoints remain editable below.");
    const toolbar=group(view,"batch-toolbar");
    for(const [mode,text] of [["select","Select / move"],["atom","Add atom"],["bond","Connect atoms"]]){const b=button(toolbar,text,()=>{structureMode=mode;bondStart=null;syncStructureMode();});b.dataset.structureMode=mode;b.setAttribute("aria-pressed",String(mode==="select"));}
    button(toolbar,"Remove selected atom",()=>{if(chosenAtom)deleteAtom(chosenAtom);});
    button(toolbar,"Assign selected atom",()=>{
      const candidate=p()?.structures[$("structureId").value];
      if(!candidate||!chosenAtom||!candidate.atoms.some((atom)=>atom.id===chosenAtom)){api.notice("Save this candidate and select a saved atom before assigning it.",true);return;}
      if(JSON.stringify(candidate.atoms)!==JSON.stringify(structure.atoms)||JSON.stringify(candidate.bonds)!==JSON.stringify(structure.bonds)){api.notice("Save the drawing changes before linking an assignment to this atom.",true);return;}
      $("assignmentForm").reset();$("assignmentId").value="";$("assignmentSampleId").value=candidate.sample_id;renderAssignmentLinks();$("assignmentCandidateId").value=candidate.id;renderAssignmentAtoms();markSelected("assignmentAtomIds",[chosenAtom]);
      $("sample").value=objectLabel(candidate.sample_id);$("candidate").value=candidate.name;$("atom").value=candidate.atoms.find((atom)=>atom.id===chosenAtom).label;api.switchWorkflow("evidence");$("observation").focus();api.notice("Saved atom selected. Choose supporting evidence and explain the observation before saving the assignment.");
    });
    const c=n("canvas");c.id="structureCanvas";c.tabIndex=0;c.setAttribute("role","img");c.setAttribute("aria-label","Editable structure draft. Equivalent atom and bond fields follow the canvas.");view.append(c);
    const status=n("p","No candidate loaded. Add atoms to a new draft.","batch-draft-status");status.id="structureDraftStatus";status.setAttribute("aria-live","polite");view.append(status);
    for(const [id,label] of [["atomTable","Atoms · stable identities"],["bondTable","Bonds · order and stereochemistry"]]){const wrap=n("div",undefined,"batch-table-wrap");wrap.id=id;view.append(n("h3",label),wrap);}
    const cards=n("div",undefined,"batch-cards");cards.id="structureCards";view.append(n("h3","Saved candidates and alternatives"),cards);
    c.addEventListener("pointerdown",(event)=>{
      if(api.busy||event.button!==0||!structureFrame)return;const point=structurePoint(event),f=structureFrame;
      const screen=(a)=>({id:a.id,x:(a.x-f.xlo)/(f.xhi-f.xlo)*(f.width-2*f.pad),y:(a.y-f.ylo)/(f.yhi-f.ylo)*(f.height-2*f.pad)});
      const hit=hitAtom(structure.atoms.map(screen),screen(point),18),atom=structure.atoms.find((a)=>a.id===hit?.id);c.focus();event.preventDefault();
      if(structureMode==="atom"){
        createAtomAt(point);
      }else if(structureMode==="bond"){
        if(!atom)return;if(bondStart){addBond(bondStart,atom.id);bondStart=null;}else{bondStart=atom.id;chosenAtom=atom.id;drawStructure();$("structureDraftStatus").textContent="Choose the second atom to add a bond.";}
      }else{chosenAtom=atom?.id||null;if(atom){structureGesture={pointerId:event.pointerId,atomId:atom.id,frame:{...structureFrame},start:{x:atom.x,y:atom.y}};c.setPointerCapture(event.pointerId);}drawStructure();}
    });
    c.addEventListener("pointermove",(event)=>{if(structureGesture?.pointerId!==event.pointerId)return;const atom=structure.atoms.find((a)=>a.id===structureGesture.atomId);if(!atom)return;Object.assign(atom,structurePoint(event));drawStructure();});
    c.addEventListener("pointerup",(event)=>{if(structureGesture?.pointerId!==event.pointerId)return;structureGesture=null;if(c.hasPointerCapture(event.pointerId))c.releasePointerCapture(event.pointerId);structureChanged();});
    c.addEventListener("pointercancel",cancelStructureDrag);
    c.addEventListener("keydown",(event)=>{if(event.key==="Escape"){event.stopPropagation();cancelStructureDrag();bondStart=null;structureMode="select";syncStructureMode();}if(event.key==="Delete"&&chosenAtom){event.preventDefault();deleteAtom(chosenAtom);}});
  }
  function cancelStructureDrag(){if(structureGesture){const atom=structure.atoms.find((a)=>a.id===structureGesture.atomId);if(atom)Object.assign(atom,structureGesture.start);structureGesture=null;drawStructure();}}
  function syncStructureMode(){
    document.querySelectorAll("[data-structure-mode]").forEach((b)=>b.setAttribute("aria-pressed",String(b.dataset.structureMode===structureMode)));
    $("structureDraftStatus").textContent={select:"Select an atom and drag to move it. Save candidate commits the draft.",atom:"Click to add an atom using the element and stereo context in the inspector.",bond:"Select two atoms to connect using the explicit bond order and stereochemistry."}[structureMode];drawStructure();
  }
  function createAtomAt(point){
    const element=$("newAtomElement").value.trim();
    if(!/^[A-Z][a-z]?$/.test(element)){api.notice("Enter a chemical element symbol before adding an atom.",true);return;}
    if(![point.x,point.y].every((value)=>Number.isFinite(value)&&Math.abs(value)<=10000)){api.notice("Enter finite drawing coordinates from -10000 to 10000.",true);return;}
    if(structure.atoms.length>=256){api.notice("A candidate supports at most 256 atoms.",true);return;}
    const id="atom_"+crypto.randomUUID().replaceAll("-","");let number=1;while(structure.atoms.some((atom)=>atom.label===element+number))number++;
    structure.atoms.push({id,label:$("newAtomLabel").value.trim()||element+number,element,x:point.x,y:point.y,stereo:$("newAtomStereo").value});chosenAtom=id;$("newAtomLabel").value="";structureChanged();
  }
  function addBond(a,b){
    if(!a||!b||a===b){api.notice("Choose two different atoms.",true);return;}
    if(structure.bonds.some((bond)=>[bond.a,bond.b].includes(a)&&[bond.a,bond.b].includes(b))){api.notice("This pair already has a bond. Edit its row below.",true);return;}
    structure.bonds.push({a,b,order:Number($("bondOrder").value),stereo:$("bondStereo").value});structureChanged();
  }
  function deleteAtom(id){structure.atoms=structure.atoms.filter((a)=>a.id!==id);structure.bonds=structure.bonds.filter((b)=>b.a!==id&&b.b!==id);chosenAtom=null;bondStart=null;structureChanged();}
  function structureChanged(){renderAtomTables();drawStructure();$("structureDraftStatus").textContent="Unsaved candidate draft · "+structure.atoms.length+" atoms / "+structure.bonds.length+" bonds. Save candidate to commit.";}
  function loadStructure(candidate){
    cancelStructureDrag();$("structureForm").reset();$("structureId").value=candidate?.id||"";$("structureEditor").value=candidate?.id||"";structureVersion=candidate?.id?candidate.version:null;
    for(const [id,key] of [["structureName","name"],["structureSample","sample_id"],["alternativeGroup","alternative_group"],["structureDescription","description"],["structureStatus","status"]])$(id).value=candidate?.[key]??(key==="status"?"proposed":"");
    markSelected("structureEvidence",candidate?.evidence_ids||[]);structure={atoms:structuredClone(candidate?.atoms||[]),bonds:structuredClone(candidate?.bonds||[])};chosenAtom=null;bondStart=null;renderAtomTables();drawStructure();
    $("structureDraftStatus").textContent=candidate?.id?"Loaded "+name(candidate)+" · "+state(candidate)+". Edits are unsaved until Save candidate.":"New candidate draft. Add atoms or duplicate a saved alternative.";
  }
  function editableCell(row,value,label,change,{type="text",choices=null}={}){
    const td=n("td"),input=n(choices?"select":"input");input.setAttribute("aria-label",label);
    if(choices)for(const [v,t] of choices)input.add(new Option(t,v));else{input.type=type;if(type==="number")input.step="any";}
    input.value=value;input.onchange=()=>{const v=type==="number"?input.valueAsNumber:input.value;if(type==="number"&&!Number.isFinite(v)){api.notice("Enter a finite coordinate.",true);input.value=value;return;}change(v);$("structureDraftStatus").textContent="Unsaved table edit · Save candidate to commit.";};td.append(input);row.append(td);return input;
  }
  function renderAtomTables(){
    const atoms=table(["Select","Label","Element","x","y","Stereo context","Remove"]);
    for(const atom of structure.atoms){const row=n("tr"),pick=n("td");button(pick,"Select",()=>{chosenAtom=atom.id;drawStructure();});row.append(pick);
      for(const key of ["label","element","x","y","stereo"])editableCell(row,atom[key]??"","Atom "+atom.label+" "+key,(value)=>{atom[key]=value;drawStructure();updateBondChoices();},{type:["x","y"].includes(key)?"number":"text"});
      const action=n("td");button(action,"Remove",()=>deleteAtom(atom.id));row.append(action);atoms.body.append(row);}
    $("atomTable").replaceChildren(atoms.table);updateBondChoices();
    const bonds=table(["From","To","Order","Stereochemistry","Remove"]);
    for(const [index,bond] of structure.bonds.entries()){const row=n("tr"),atomChoices=structure.atoms.map((a)=>[a.id,a.label]);
      for(const key of ["a","b"])editableCell(row,bond[key],"Bond "+(index+1)+" endpoint "+key,(v)=>{bond[key]=v;drawStructure();},{choices:atomChoices});
      editableCell(row,bond.order,"Bond "+(index+1)+" order",(v)=>{bond.order=Number(v);drawStructure();},{choices:[[1,"Single"],[2,"Double"],[3,"Triple"],[1.5,"Aromatic"]]});
      editableCell(row,bond.stereo,"Bond "+(index+1)+" stereochemistry",(v)=>{bond.stereo=v;drawStructure();},{choices:[["none","None"],["wedge","Wedge"],["hash","Hashed wedge"],["either","Either"]]});
      const action=n("td");button(action,"Remove",()=>{structure.bonds.splice(index,1);structureChanged();});row.append(action);bonds.body.append(row);}
    $("bondTable").replaceChildren(bonds.table);
  }
  function updateBondChoices(){const choices=structure.atoms.map((atom)=>[atom.id,atom.label+" ("+atom.element+")"]);choose("bondFrom",choices);choose("bondTo",choices);}
  function setupCanvas(canvas){
    const rect=canvas.getBoundingClientRect();if(!rect.width||!rect.height)return null;const ratio=devicePixelRatio||1;canvas.width=Math.round(rect.width*ratio);canvas.height=Math.round(rect.height*ratio);
    const context=canvas.getContext("2d");context.scale(ratio,ratio);context.clearRect(0,0,rect.width,rect.height);return {context,width:rect.width,height:rect.height};
  }
  function structurePoint(event){const rect=$("structureCanvas").getBoundingClientRect(),f=structureGesture?.frame||structureFrame;
    return {x:Math.max(-10000,Math.min(10000,f.xlo+(event.clientX-rect.left-f.pad)/(f.width-2*f.pad)*(f.xhi-f.xlo))),y:Math.max(-10000,Math.min(10000,f.ylo+(event.clientY-rect.top-f.pad)/(f.height-2*f.pad)*(f.yhi-f.ylo)))};}
  function drawStructure(){
    const drawing=setupCanvas($("structureCanvas"));if(!drawing)return;const {context:c,width:w,height:h}=drawing,pad=40;
    let xlo=0,xhi=1,ylo=0,yhi=1;for(const atom of structure.atoms){xlo=Math.min(xlo,atom.x);xhi=Math.max(xhi,atom.x);ylo=Math.min(ylo,atom.y);yhi=Math.max(yhi,atom.y);}
    structureFrame=structureGesture?.frame||{xlo,xhi,ylo,yhi,pad,width:w,height:h,tolerance:Math.max((xhi-xlo)/(w-2*pad),(yhi-ylo)/(h-2*pad))*18};
    const f=structureFrame,px=(x)=>pad+(x-f.xlo)/(f.xhi-f.xlo)*(w-2*pad),py=(y)=>pad+(y-f.ylo)/(f.yhi-f.ylo)*(h-2*pad);
    c.fillStyle="#fcfdff";c.fillRect(0,0,w,h);c.fillStyle="#e5eaf2";for(let x=20;x<w;x+=24)for(let y=20;y<h;y+=24)c.fillRect(x,y,1,1);
    for(const bond of structure.bonds){const a=structure.atoms.find((atom)=>atom.id===bond.a),b=structure.atoms.find((atom)=>atom.id===bond.b);if(!a||!b)continue;
      const ax=px(a.x),ay=py(a.y),bx=px(b.x),by=py(b.y),length=Math.hypot(bx-ax,by-ay)||1,nx=-(by-ay)/length,ny=(bx-ax)/length;c.strokeStyle="#3b4d68";c.fillStyle="#3b4d68";c.lineWidth=1.7;c.setLineDash([]);
      if(bond.stereo==="wedge"){c.beginPath();c.moveTo(ax,ay);c.lineTo(bx+nx*6,by+ny*6);c.lineTo(bx-nx*6,by-ny*6);c.closePath();c.fill();}
      else if(bond.stereo==="hash"){for(let i=1;i<=8;i++){const t=i/9,half=t*6;c.beginPath();c.moveTo(ax+(bx-ax)*t+nx*half,ay+(by-ay)*t+ny*half);c.lineTo(ax+(bx-ax)*t-nx*half,ay+(by-ay)*t-ny*half);c.stroke();}}
      else{const offsets=bond.order===3?[-5,0,5]:bond.order===2||bond.order===1.5?[-2.8,2.8]:[0];for(const [index,offset] of offsets.entries()){c.setLineDash(bond.stereo==="either"||bond.order===1.5&&index===1?[4,3]:[]);c.beginPath();c.moveTo(ax+nx*offset,ay+ny*offset);c.lineTo(bx+nx*offset,by+ny*offset);c.stroke();}}
    }
    c.setLineDash([]);c.textAlign="center";c.textBaseline="middle";c.font="12px Inter, sans-serif";
    for(const atom of structure.atoms){const x=px(atom.x),y=py(atom.y);c.fillStyle=chosenAtom===atom.id?"#dce7ff":"#ffffff";c.strokeStyle=chosenAtom===atom.id?"#3158cf":"#c5cfdf";c.beginPath();c.arc(x,y,17,0,2*Math.PI);c.fill();c.stroke();c.fillStyle="#263447";c.fillText(atom.element,x,y);c.font="10px Inter, sans-serif";c.fillText(atom.label+(atom.stereo?" · "+atom.stereo:""),x,y+28);c.font="12px Inter, sans-serif";}
    if(!structure.atoms.length){c.fillStyle="#73849b";c.fillText("Add an atom using Drawing tools.",w/2,h/2-10);c.fillText("Or choose Add atom and click the canvas.",w/2,h/2+10);}
  }
  function renderStructures(){
    choose("structureEditor",entries("structures"));choose("structureSample",entries("samples"));choose("structureEvidence",evidenceEntries(),false);
    collectionCards($("structureCards"),items("structures"),(candidate,card)=>{hint(card,objectLabel(candidate.sample_id)+" · "+candidate.status+" · "+candidate.atoms.length+" atoms");
      if(candidate.alternative_group)hint(card,"Alternative group: "+candidate.alternative_group);if(candidate.description)card.append(n("p",candidate.description));hint(card,"Evidence: "+(candidate.evidence_ids.map(objectLabel).join(", ")||"None linked"));
      const actions=group(card,"actions");button(actions,"Edit drawing",()=>loadStructure(candidate));button(actions,"Remove candidate",()=>remove(candidate.id));
    },"No structure candidates saved. Draw alternatives without replacing the original evidence.");queueDraw();
  }


  let gridCache=null;
  function buildCorrelations(){
    const panel=$("correlations");title(panel,"Processed COSY / HSQC","Import processed numerical data through Import local data. Confirm experiment and axis nuclei before saving crosspeaks.");
    field(panel,"gridSelect","Processed 2D grid",{type:"select"}).onchange=()=>{loadCrosspeak(null);loadGridMetadata();renderCrosspeaks();drawGrid();};
    const metadata=fieldset(panel,"Confirm axis / experiment metadata");
    const mf=form(metadata,"gridMetadataForm",()=>save({op:"grid_metadata",grid_id:$("gridSelect").value,experiment:$("gridExperiment").value,nuclei:[$("gridNucleusX").value,$("gridNucleusY").value],reference:$("gridReference").value},()=>loadGridMetadata()));
    field(mf,"gridExperiment","Experiment",{type:"select",required:true,items:[["","Choose explicitly"],["COSY","COSY"],["HSQC","HSQC"]]});
    for(const [id,label]of [["gridNucleusX","x axis nucleus · columns"],["gridNucleusY","y axis nucleus · rows"]])field(mf,id,label,{type:"select",required:true,items:[["","Choose explicitly"],["1H","¹H"],["13C","¹³C"],["15N","¹⁵N"]]});
    field(mf,"gridReference","Axis identification / reference source",{required:true});submit(mf,"Confirm grid metadata");
    const f=form(panel,"crosspeakForm",async()=>{
      const grid=p()?.grids[$("gridSelect").value];if(!grid)throw Error("Select a processed 2D grid.");
      if(gridDraftSource&&(gridDraftSource.id!==grid.id||gridDraftSource.version!==grid.version))throw Error("The grid changed. Select the crosspeak again.");
      await save({op:"crosspeak",...($("crosspeakId").value?{crosspeak_id:$("crosspeakId").value}:{}),grid_id:grid.id,x_ppm:numeric("crosspeakX"),y_ppm:numeric("crosspeakY"),label:$("crosspeakLabel").value},()=>loadCrosspeak(null));
    });hidden(f,"crosspeakId");field(f,"crosspeakLabel","Crosspeak label",{required:true});const xy=group(f);
    field(xy,"crosspeakX","x · ppm",{type:"number",required:true});field(xy,"crosspeakY","y · ppm",{type:"number",required:true});submit(f,"Save crosspeak");button(f,"New crosspeak",()=>loadCrosspeak(null));
    hint(panel,"Click a saved crosspeak to edit it; click elsewhere to populate a new draft. Numerical intensity is read from the nearest original grid point.");
    const view=workspace("correlations","Processed 2D correlation map","x decreases left → right; y increases top → bottom. Columns map to x and rows to y, irrespective of original storage order.");
    const controls=group(view,"batch-toolbar");field(controls,"gridCutoff","Display cutoff · % maximum |intensity|",{type:"number",value:0,min:0,max:100}).oninput=drawGrid;
    const legend=n("p",undefined,"grid-legend");legend.append(n("span","Positive signal","positive-key"),n("span","Negative signal","negative-key"));controls.append(legend);
    const info=n("p","No grid selected.","hint");info.id="gridInfo";view.append(info);
    const canvas=n("canvas");canvas.id="gridCanvas";canvas.tabIndex=0;canvas.setAttribute("role","img");canvas.setAttribute("aria-label","Signed processed 2D heatmap with editable crosspeaks; coordinate fields provide a pointer-free route.");view.append(canvas);
    const status=n("p","Move over the map to inspect original-point coordinates and intensity.","batch-draft-status");status.id="gridReadout";status.setAttribute("aria-live","polite");view.append(status);
    hint(view,"Display uses square-root colour scaling and retains positive and negative extrema in separate halves when signals share a display bin. Display cutoff and pixel aggregation never change numerical analysis.");
    const cards=n("div",undefined,"batch-cards");cards.id="crosspeakCards";view.append(cards);
    canvas.addEventListener("pointermove",(e)=>{const point=gridEvent(e);if(!point)return;const source=gridPoint(point.grid,point.x,point.y);$("gridReadout").textContent="Cursor: x "+fmt(point.x)+" / y "+fmt(point.y)+" ppm · nearest original: x "+fmt(source.x)+" / y "+fmt(source.y)+" ppm · intensity "+fmt(source.intensity);});
    canvas.addEventListener("pointerdown",(e)=>{
      if(api.busy||e.button!==0)return;const point=gridEvent(e);if(!point)return;e.preventDefault();canvas.focus();
      const match=items("crosspeaks").filter((peak)=>peak.grid_id===point.grid.id).find((peak)=>Math.hypot((fraction(peak.x_ppm,point.grid.x,true)-fraction(point.x,point.grid.x,true))*gridFrame.plotWidth,(fraction(peak.y_ppm,point.grid.y)-fraction(point.y,point.grid.y))*gridFrame.plotHeight)<12);
      if(match)loadCrosspeak(match);else{loadCrosspeak(null);$("crosspeakX").value=point.x;$("crosspeakY").value=point.y;gridDraftSource={id:point.grid.id,version:point.grid.version};$("crosspeakLabel").focus();drawGrid();}
    });for(const id of ["crosspeakX","crosspeakY"])$(id).oninput=drawGrid;
  }
  function loadGridMetadata(){const grid=p()?.grids[$("gridSelect").value];$("gridExperiment").value=grid?.metadata?.experiment||"";$("gridNucleusX").value=grid?.nuclei?.[0]||"";$("gridNucleusY").value=grid?.nuclei?.[1]||"";$("gridReference").value=grid?.metadata?.axis_confirmations?.at(-1)?.reference||"";}
  function loadCrosspeak(peak){
    $("crosspeakForm").reset();$("crosspeakId").value=peak?.id||"";crosspeakVersion=peak?.version??null;
    if(peak){$("gridSelect").value=peak.grid_id;$("crosspeakX").value=peak.x_ppm;$("crosspeakY").value=peak.y_ppm;$("crosspeakLabel").value=peak.label;loadGridMetadata();}
    const grid=p()?.grids[$("gridSelect").value];gridDraftSource=grid?{id:grid.id,version:grid.version}:null;drawGrid();
  }
  function gridEvent(event){
    const grid=p()?.grids[$("gridSelect").value],f=gridFrame;if(!grid||!f)return null;const r=$("gridCanvas").getBoundingClientRect(),x=event.clientX-r.left,y=event.clientY-r.top;
    if(x<f.left||x>f.left+f.plotWidth||y<f.top||y>f.top+f.plotHeight)return null;
    return {grid,x:axisAt((x-f.left)/f.plotWidth,grid.x,true),y:axisAt((y-f.top)/f.plotHeight,grid.y)};
  }
  function drawGrid(){
    const drawing=setupCanvas($("gridCanvas"));if(!drawing)return;const {context:c,width:w,height:h}=drawing,grid=p()?.grids[$("gridSelect").value];
    gridFrame=null;c.font="11px Inter, sans-serif";c.fillStyle="#6b7d95";if(!grid){c.fillText("Import or select a processed COSY / HSQC grid.",25,h/2);return;}
    const left=62,top=24,plotWidth=Math.max(20,w-left-26),plotHeight=Math.max(20,h-top-58);gridFrame={left,top,plotWidth,plotHeight};
    const cutoff=Math.max(0,Math.min(100,$("gridCutoff").valueAsNumber||0))/100,bw=Math.max(1,Math.floor(plotWidth/2)),bh=Math.max(1,Math.floor(plotHeight)),key=[grid.id,grid.version,bw,bh,cutoff].join(":");
    if(gridCache?.key!==key){
      const bins=signedBins(grid,bw,bh),off=document.createElement("canvas");off.width=bw*2;off.height=bh;const oc=off.getContext("2d"),image=oc.createImageData(off.width,off.height);
      for(let i=0;i<bins.positive.length;i++)for(let half=0;half<2;half++){
        const positive=bins.positive[i],negative=bins.negative[i],both=positive>0&&negative<0,value=both?(half?negative:positive):(positive||negative),strength=Math.abs(value)/(bins.maximum||1);
        const rgba=(Math.floor(i/bw)*off.width+(i%bw)*2+half)*4,colour=value<0?[204,67,83]:[49,88,207],alpha=strength>=cutoff?Math.sqrt(strength):0;
        for(let k=0;k<3;k++)image.data[rgba+k]=Math.round(255*(1-alpha)+colour[k]*alpha);image.data[rgba+3]=255;
      }oc.putImageData(image,0,0);gridCache={key,canvas:off};
    }
    c.imageSmoothingEnabled=false;c.drawImage(gridCache.canvas,left,top,plotWidth,plotHeight);c.strokeStyle="#ccd6e6";c.strokeRect(left,top,plotWidth,plotHeight);c.textAlign="center";
    for(let tick=0;tick<=5;tick++){const f=tick/5;c.fillStyle="#63758d";c.fillText(fmt(axisAt(f,grid.x,true),5),left+f*plotWidth,h-33);c.textAlign="right";c.fillText(fmt(axisAt(f,grid.y),5),left-8,top+f*plotHeight+4);c.textAlign="center";}
    c.fillText("x · "+(grid.nuclei[0]||"nucleus unconfirmed")+" / ppm → decreasing",left+plotWidth/2,h-10);
    c.save();c.translate(13,top+plotHeight/2);c.rotate(-Math.PI/2);c.fillText("y · "+(grid.nuclei[1]||"?")+" / ppm",0,0);c.restore();
    const points=items("crosspeaks").filter((peak)=>peak.grid_id===grid.id).map((peak)=>({...peak,draft:false}));
    const dx=$("crosspeakX").valueAsNumber,dy=$("crosspeakY").valueAsNumber;if(Number.isFinite(dx)&&Number.isFinite(dy))points.push({x_ppm:dx,y_ppm:dy,label:$("crosspeakLabel").value||"Draft",draft:true});
    c.save();c.beginPath();c.rect(left,top,plotWidth,plotHeight);c.clip();
    for(const peak of points){const x=left+fraction(peak.x_ppm,grid.x,true)*plotWidth,y=top+fraction(peak.y_ppm,grid.y)*plotHeight;c.strokeStyle=peak.draft?"#98670f":"#2c465f";c.lineWidth=1.2;c.setLineDash(peak.draft?[3,3]:[]);c.beginPath();c.arc(x,y,7,0,2*Math.PI);c.moveTo(x-11,y);c.lineTo(x+11,y);c.moveTo(x,y-11);c.lineTo(x,y+11);c.stroke();c.setLineDash([]);c.fillStyle="#ffffffdd";c.fillRect(x+9,y-15,c.measureText(peak.label).width+8,15);c.fillStyle="#344963";c.textAlign="left";c.fillText(peak.label,x+13,y-4);}
    c.restore();
  }
  function renderCrosspeaks(){
    const grid=p()?.grids[$("gridSelect").value];$("gridInfo").textContent=grid?name(grid)+" · "+grid.x.length+" columns × "+grid.y.length+" rows · v"+grid.version+" · "+(grid.metadata.experiment||"experiment unconfirmed"):"No grid selected.";
    collectionCards($("crosspeakCards"),items("crosspeaks").filter((peak)=>peak.grid_id===grid?.id),(peak,card)=>{hint(card,"x "+fmt(peak.x_ppm)+" / y "+fmt(peak.y_ppm)+" ppm · original intensity "+fmt(peak.intensity));const actions=group(card,"actions");button(actions,"Edit crosspeak",()=>loadCrosspeak(peak));button(actions,"Assign",()=>prefillAssignment(peak.id));button(actions,"Remove",()=>remove(peak.id));},"No crosspeaks saved for this grid.");
  }
  function renderCorrelations(){const previous=$("gridSelect").value;choose("gridSelect",entries("grids"));if(!$("gridSelect").value&&items("grids").length)$("gridSelect").value=items("grids")[0].id;if(previous!==$("gridSelect").value)loadGridMetadata();renderCrosspeaks();queueDraw();}


  let referenceFrame=null;
  function buildReferences(){
    const panel=$("references");title(panel,"Preserved image / PDF evidence","Attach an authorized original. Image readings remain approximate observations with their own uncertainty, not imported numerical spectra.");
    const af=form(panel,"attachmentForm",async()=>{await save({op:"attach",path:$("attachmentPath").value,name:$("attachmentName").value||null,sample_id:$("attachmentSample").value,source_role:$("attachmentRole").value,category:$("attachmentCategory").value,notes:$("attachmentNotes").value},()=>{$("attachmentPath").value="";$("attachmentName").value="";});});
    field(af,"attachmentPath","Original file path · PDF / PNG / JPEG / WebP",{required:true,placeholder:"Absolute local path"});field(af,"attachmentName","Display name · optional");field(af,"attachmentSample","Sample",{type:"select",required:true});
    field(af,"attachmentRole","Source role",{type:"select",required:true,items:[["","Choose explicitly"],["own","Own evidence"],["reference","Reference evidence"]]});
    field(af,"attachmentCategory","Evidence type",{type:"select",items:[["nmr_reference","NMR reference"],["IR","IR"],["HRMS","HRMS"],["optical_rotation","Optical rotation"],["other","Other"]]});field(af,"attachmentNotes","Source / method notes",{type:"textarea",rows:2});submit(af,"Attach & preserve original");
    const annotation=form(panel,"annotationForm",async()=>{
      const attachment=p()?.attachments[$("referenceSelect").value],page=numeric("referencePage");if(!attachment)throw Error("Select an attachment.");
      if(annotationDraftSource&&(annotationDraftSource.id!==attachment.id||annotationDraftSource.version!==attachment.version||annotationDraftSource.page!==page))throw Error("The reference page changed. Select the rectangle again.");
      await save({op:"annotate",...($("annotationId").value?{annotation_id:$("annotationId").value}:{}),attachment_id:attachment.id,page,
        x:numeric("annotationX"),y:numeric("annotationY"),width:numeric("annotationWidth"),height:numeric("annotationHeight"),label:$("annotationLabel").value,
        observation:$("annotationObservation").value,approximate_ppm:numeric("annotationPpm",true),reading_uncertainty_ppm:numeric("annotationUncertainty",true)},()=>loadAnnotation(null));
    });title(annotation,"Page annotation");hidden(annotation,"annotationId");field(annotation,"annotationLabel","Annotation label",{required:true});
    const rectangleFields=group(annotation);for(const [id,label] of [["annotationX","Left · 0 to 1"],["annotationY","Top · 0 to 1"],["annotationWidth","Width · 0 to 1"],["annotationHeight","Height · 0 to 1"]])field(rectangleFields,id,label,{type:"number",min:0,max:1,required:true}).oninput=drawReference;
    field(annotation,"annotationObservation","Observation / interpretation",{type:"textarea",rows:3});field(annotation,"annotationPpm","Approximate reading · ppm, optional",{type:"number"});field(annotation,"annotationUncertainty","Reading standard uncertainty · ppm, optional",{type:"number",min:0});
    submit(annotation,"Save annotation");button(annotation,"New annotation",()=>loadAnnotation(null));
    const view=workspace("references","Image & PDF evidence","Select a page, then drag a rectangle. Click a saved rectangle to edit it. The preserved original remains available for download.");
    const toolbar=group(view,"reference-toolbar");field(toolbar,"referenceSelect","Attachment",{type:"select"}).onchange=()=>{$("referencePage").value=1;loadAnnotation(null);renderReferenceInfo();loadPreview();};
    field(toolbar,"referencePage","Page · one-based",{type:"number",min:1,step:1,value:1}).onchange=()=>{loadAnnotation(null);renderReferenceInfo();loadPreview();};
    button(toolbar,"Download original",()=>api.act(async()=>{const attachment=p()?.attachments[$("referenceSelect").value];if(!attachment)throw Error("Select an attachment.");const blob=await api.privateBlob("/api/source/"+encodeURIComponent(attachment.source_id));downloadBlob(blob,p()?.sources[attachment.source_id]?.name||attachment.name);api.notice("Original download requested. Verify the saved file in your browser.");}));
    const info=n("p","No attachment selected.","hint");info.id="referenceInfo";view.append(info);
    const canvas=n("canvas");canvas.id="referenceCanvas";canvas.tabIndex=0;canvas.setAttribute("role","img");canvas.setAttribute("aria-label","Reference page with annotation rectangles. Labelled normalized coordinate fields are available in the inspector.");view.append(canvas);
    const status=n("p","Select a preserved reference to preview.","batch-draft-status");status.id="referenceStatus";status.setAttribute("aria-live","polite");view.append(status);
    const cards=n("div",undefined,"batch-cards");cards.id="annotationCards";view.append(cards);
    canvas.addEventListener("pointerdown",(event)=>{
      if(api.busy||event.button!==0||!referenceImage)return;const point=referencePoint(event);if(!point)return;event.preventDefault();canvas.focus();annotationGesture={pointerId:event.pointerId,start:point,end:point};canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener("pointermove",(event)=>{if(annotationGesture?.pointerId!==event.pointerId)return;annotationGesture.end=referencePoint(event,true);drawReference();});
    canvas.addEventListener("pointerup",(event)=>{
      if(annotationGesture?.pointerId!==event.pointerId)return;const gesture=annotationGesture;annotationGesture=null;if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);
      const end=referencePoint(event,true),rect=rectangle(gesture.start,end),attachment=p()?.attachments[$("referenceSelect").value];
      if(rect&&rect.width*referenceFrame.width>=4&&rect.height*referenceFrame.height>=4){loadAnnotation(null);for(const [id,key]of [["annotationX","x"],["annotationY","y"],["annotationWidth","width"],["annotationHeight","height"]])$(id).value=rect[key];annotationDraftSource={id:attachment.id,version:attachment.version,page:Number($("referencePage").value)};$("referenceStatus").textContent="Unsaved rectangle. Add a label and observation, then Save annotation.";}
      else{const hit=visibleAnnotations().toReversed().find((a)=>end.x>=a.x&&end.x<=a.x+a.width&&end.y>=a.y&&end.y<=a.y+a.height);if(hit)loadAnnotation(hit);}drawReference();
    });
    canvas.addEventListener("pointercancel",()=>{annotationGesture=null;drawReference();});canvas.addEventListener("keydown",(event)=>{if(event.key==="Escape"){event.stopPropagation();annotationGesture=null;drawReference();}});
  }
  function downloadBlob(blob,name){const url=URL.createObjectURL(blob),a=n("a");a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);}
  function visibleAnnotations(){return items("annotations").filter((a)=>a.attachment_id===$("referenceSelect").value&&a.page===Number($("referencePage").value));}
  function loadAnnotation(annotation){
    $("annotationForm").reset();$("annotationId").value=annotation?.id||"";annotationVersion=annotation?.version??null;
    if(annotation){$("referenceSelect").value=annotation.attachment_id;$("referencePage").value=annotation.page;for(const [id,key]of [["annotationLabel","label"],["annotationX","x"],["annotationY","y"],["annotationWidth","width"],["annotationHeight","height"],["annotationObservation","observation"],["annotationPpm","approximate_ppm"],["annotationUncertainty","reading_uncertainty_ppm"]])$(id).value=annotation[key]??"";}
    const attachment=p()?.attachments[$("referenceSelect").value];annotationDraftSource=attachment?{id:attachment.id,version:attachment.version,page:Number($("referencePage").value)}:null;
    if(annotation){renderReferenceInfo();loadPreview();}drawReference();
  }
  async function loadPreview(){
    const attachment=p()?.attachments[$("referenceSelect").value],page=Number($("referencePage").value),key=attachment?[p()?.id,attachment.id,attachment.version,page].join(":"):"";
    if(key&&key===previewKey)return;const request=++previewRequest;previewKey=key;referenceImage=null;referenceFrame=null;
    if(previewUrl){URL.revokeObjectURL(previewUrl);previewUrl=null;}drawReference();
    if(!attachment){$("referenceStatus").textContent="Select an attachment to preview.";return;}
    if(!Number.isInteger(page)||page<1||page>attachment.pages){$("referenceStatus").textContent="Enter a page from 1 to "+attachment.pages+".";previewKey="";return;}
    $("referenceStatus").textContent="Loading preserved page…";
    let url=null;
    try{
      const blob=await api.privateBlob("/api/reference/"+encodeURIComponent(attachment.id)+"/page/"+page);url=URL.createObjectURL(blob);const img=new Image();img.src=url;await img.decode();
      if(request!==previewRequest){URL.revokeObjectURL(url);return;}referenceImage=img;previewUrl=url;$("referenceStatus").textContent="Page "+page+" of "+attachment.pages+" · drag to draft an annotation. Approximate readings are separate from numerical spectra.";drawReference();
    }catch(error){if(url)URL.revokeObjectURL(url);if(request===previewRequest){previewKey="";$("referenceStatus").textContent="Preview unavailable: "+error.message;}}
  }
  function referencePoint(event,clipped=false){
    const f=referenceFrame;if(!f)return null;const r=$("referenceCanvas").getBoundingClientRect(),x=(event.clientX-r.left-f.x)/f.width,y=(event.clientY-r.top-f.y)/f.height;
    if(!clipped&&(x<0||x>1||y<0||y>1))return null;return {x:clamp(x),y:clamp(y)};
  }
  function drawReference(){
    const canvas=$("referenceCanvas");if(referenceImage&&canvas.getBoundingClientRect().width)canvas.style.height=Math.max(200,Math.min(720,canvas.getBoundingClientRect().width*referenceImage.height/referenceImage.width))+"px";
    const drawing=setupCanvas(canvas);if(!drawing)return;const {context:c,width:w,height:h}=drawing;c.fillStyle="#f1f3f8";c.fillRect(0,0,w,h);c.font="11px Inter, sans-serif";c.fillStyle="#63758d";
    if(!referenceImage){referenceFrame=null;c.fillText("Select an attachment and a valid page to preview.",20,h/2);return;}
    const scale=Math.min((w-16)/referenceImage.width,(h-16)/referenceImage.height),width=referenceImage.width*scale,height=referenceImage.height*scale,x=(w-width)/2,y=(h-height)/2;referenceFrame={x,y,width,height};c.drawImage(referenceImage,x,y,width,height);
    const boxes=visibleAnnotations().map((a)=>({...a,draft:false}));
    const dx=$("annotationX").valueAsNumber,dy=$("annotationY").valueAsNumber,dw=$("annotationWidth").valueAsNumber,dh=$("annotationHeight").valueAsNumber;if([dx,dy,dw,dh].every(Number.isFinite))boxes.push({x:dx,y:dy,width:dw,height:dh,label:$("annotationLabel").value||"Draft",draft:true});
    if(annotationGesture){const rect=rectangle(annotationGesture.start,annotationGesture.end);if(rect)boxes.push({...rect,label:"Drawing…",draft:true});}
    c.save();c.beginPath();c.rect(x,y,width,height);c.clip();
    for(const box of boxes){const bx=x+box.x*width,by=y+box.y*height;c.lineWidth=1.5;c.strokeStyle=box.draft?"#ac720e":"#3158cf";c.fillStyle=box.draft?"#d9a3231a":"#3158cf16";c.setLineDash(box.draft?[5,3]:[]);c.fillRect(bx,by,box.width*width,box.height*height);c.strokeRect(bx,by,box.width*width,box.height*height);c.setLineDash([]);c.fillStyle="#ffffffef";c.fillRect(bx,Math.max(y,by-17),c.measureText(box.label).width+8,16);c.fillStyle=box.draft?"#865e13":"#244bb5";c.fillText(box.label,bx+4,Math.max(y+12,by-5));}c.restore();
  }
  function renderReferenceInfo(){
    const a=p()?.attachments[$("referenceSelect").value];$("referencePage").max=a?.pages||1;$("referenceInfo").textContent=a?name(a)+" · "+a.source_role.toUpperCase()+" / "+a.category+" · sample "+objectLabel(a.sample_id)+" · "+state(a)+" · "+a.pages+" page(s)":"No attachment selected.";
    collectionCards($("annotationCards"),visibleAnnotations(),(annotation,card)=>{card.append(n("p",annotation.observation||"No observation entered."));hint(card,"Page "+annotation.page+" · approximate reading "+(annotation.approximate_ppm===null?"unavailable":fmt(annotation.approximate_ppm)+" ppm")+" · u(reading) "+(annotation.reading_uncertainty_ppm===null?"unavailable":fmt(annotation.reading_uncertainty_ppm)+" ppm"));const actions=group(card,"actions");button(actions,"Edit rectangle",()=>loadAnnotation(annotation));button(actions,"Assign",()=>prefillAssignment(annotation.id));button(actions,"Remove",()=>remove(annotation.id));},"No annotations on this page. Drag a rectangle or enter normalized bounds.");
  }
  function renderReferences(){choose("attachmentSample",entries("samples"));choose("referenceSelect",entries("attachments"));renderReferenceInfo();if(activeWorkflow==="references")loadPreview();queueDraw();}


  let peakDraftSource=null;
  function buildOrganicExtensions(){
    const organic=$("organic"),labels=n("article",undefined,"batch-subpanel");organic.append(labels);title(labels,"Signal labels & proton counts","Enter a position and a reviewable multiplicity. Intensity comes from the original numerical spectrum; proton counts are explicit interpretations.");
    const f=form(labels,"peakLabelForm",async()=>{const spectrum=p()?.spectra[$("peakSpectrum").value];if(!spectrum)throw Error("Select a frequency spectrum.");if(peakDraftSource&&(peakDraftSource.id!==spectrum.id||peakDraftSource.version!==spectrum.version))throw Error("The label source changed. Review its position again.");
      await save({op:"peak_label",...($("peakLabelId").value?{peaklabel_id:$("peakLabelId").value}:{}),spectrum_id:spectrum.id,ppm:numeric("peakPpm"),label:$("peakLabelName").value,multiplicity:$("peakMultiplicity").value||null,protons:numeric("peakProtons",true)},()=>loadPeakLabel(null));
    });hidden(f,"peakLabelId");field(f,"peakSpectrum","Label spectrum",{type:"select",required:true}).onchange=()=>{loadPeakLabel(null);renderPeakLabels();};
    field(f,"peakLabelName","Signal / atom label",{required:true});const signalFields=group(f);field(signalFields,"peakPpm","Chemical shift · ppm",{type:"number",required:true});field(signalFields,"peakMultiplicity","Multiplicity · optional",{placeholder:"s, d, t, m…"});field(signalFields,"peakProtons","Protons · optional",{type:"number",min:0});submit(f,"Save signal label");button(f,"New label",()=>loadPeakLabel(null));
    const cards=n("div");cards.id="peakLabelCards";labels.append(cards);
    const normal=n("article",undefined,"batch-subpanel");organic.append(normal);title(normal,"Relative proton integration","Normalize identified integrals against an explicit positive proton reference from the same ¹H spectrum. Saved numerical data is unchanged.");
    const nf=form(normal,"normalizationForm",()=>save({op:"normalize",name:$("normalizationName").value,reference_integral_id:$("normalizationReference").value,reference_protons:numeric("normalizationProtons"),integral_ids:selectedIds("normalizationIntegrals")}));
    field(nf,"normalizationName","Analysis name",{required:true,value:"Relative proton integration"});field(nf,"normalizationReference","Reference integral",{type:"select",required:true}).onchange=renderNormalization;
    field(nf,"normalizationProtons","Reference proton count",{type:"number",required:true,min:0});field(nf,"normalizationIntegrals","Integrals to normalize · same spectrum",{type:"select",multiple:true,required:true});submit(nf,"Calculate relative proton counts");
    const yieldForm=$("yieldForm"),extra=n("details");extra.append(n("summary","Recovered starting material & supplied uncertainties"));yieldForm.insertBefore(extra,yieldForm.querySelector('button[type="submit"], button.primary'));
    field(extra,"recoveredIntegral","Recovered starting-material integral · optional",{type:"select"});field(extra,"recoveredProtons","Recovered material proton count",{type:"number",min:0});hint(extra,"Leave unknown uncertainties blank. Supplied values are standard uncertainties; blank is unavailable, not zero.");
    for(const [id,label]of [["uProductArea","u(product area) · intensity·ppm"],["uStandardArea","u(standard area) · intensity·ppm"],["uRecoveredArea","u(recovered area) · intensity·ppm"],["uStandardMol","u(standard amount) · mol"],["uLimitingMol","u(limiting amount) · mol"]])field(extra,id,label,{type:"number",min:0});
  }
  function loadPeakLabel(label){const previous=$("peakSpectrum").value;$("peakLabelForm").reset();$("peakSpectrum").value=previous;$("peakLabelId").value=label?.id||"";peakVersion=label?.version??null;
    if(label){$("peakSpectrum").value=label.spectrum_id;$("peakLabelName").value=label.label;$("peakPpm").value=label.ppm;$("peakMultiplicity").value=label.multiplicity||"";$("peakProtons").value=label.protons??"";}
    if(!$("peakSpectrum").value)$("peakSpectrum").value=api.activeSpectrumId||"";const spectrum=p()?.spectra[$("peakSpectrum").value];peakDraftSource=spectrum?{id:spectrum.id,version:spectrum.version}:null;
  }
  function renderPeakLabels(){collectionCards($("peakLabelCards"),items("peaklabels").filter((label)=>label.spectrum_id===$("peakSpectrum").value),(label,card)=>{
    hint(card,fmt(label.ppm)+" ppm · "+(label.multiplicity||"Multiplicity unspecified")+" · protons "+fmt(label.protons)+" · intensity "+fmt(label.intensity));const actions=group(card,"actions");button(actions,"Edit label",()=>loadPeakLabel(label));button(actions,"Assign",()=>prefillAssignment(label.id));button(actions,"Remove",()=>remove(label.id));},"No signal labels saved for this spectrum.");}
  function renderNormalization(){const reference=p()?.integrals[$("normalizationReference").value];choose("normalizationIntegrals",entries("integrals",(integral)=>integral.spectrum_id===reference?.spectrum_id),false);}
  function renderOrganicExtensions(){
    choose("peakSpectrum",entries("spectra",(s)=>s.domain==="frequency"));if(!$("peakSpectrum").value&&p()?.spectra[api.activeSpectrumId]?.domain==="frequency")$("peakSpectrum").value=api.activeSpectrumId;
    choose("normalizationReference",entries("integrals",(integral)=>p()?.spectra[integral.spectrum_id]?.nucleus==="1H"));choose("recoveredIntegral",entries("integrals"));renderNormalization();renderPeakLabels();
  }
  function yieldCommand(){return {recovered_integral_id:$("recoveredIntegral").value||null,recovered_protons:numeric("recoveredProtons",true),u_product_area:numeric("uProductArea",true),u_standard_area:numeric("uStandardArea",true),u_recovered_area:numeric("uRecoveredArea",true),u_standard_mol:numeric("uStandardMol",true),u_limiting_mol:numeric("uLimitingMol",true)};}
  function loadYield(command){for(const [id,key]of [["recoveredIntegral","recovered_integral_id"],["recoveredProtons","recovered_protons"],["uProductArea","u_product_area"],["uStandardArea","u_standard_area"],["uRecoveredArea","u_recovered_area"],["uStandardMol","u_standard_mol"],["uLimitingMol","u_limiting_mol"]])$(id).value=command[key]??"";}
  function drawPeakLabels(canvas,frame,spectrumId){
    const c=canvas.getContext("2d"),labels=items("peaklabels").filter((label)=>label.spectrum_id===spectrumId),span=frame.range[1]-frame.range[0];
    c.save();c.font="10px Inter, sans-serif";c.textAlign="center";let index=0;
    for(const label of labels){if(label.ppm<frame.range[0]||label.ppm>frame.range[1])continue;const x=frame.left+(frame.range[1]-label.ppm)/span*(frame.width-frame.left-frame.right),y=frame.top+30+(index++%3)*16;c.fillStyle=label.state==="stale"?"#936123":"#314b75";c.fillText(label.label+(label.multiplicity?" ("+label.multiplicity+")":""),x,y);c.strokeStyle="#a9bad5";c.setLineDash([2,3]);c.beginPath();c.moveTo(x,y+4);c.lineTo(x,y+14);c.stroke();}c.restore();
  }
  function buildDept(){const panel=n("article",undefined,"batch-subpanel");$("processing").append(panel);title(panel,"DEPT-135 / ¹³C evidence","Match signed peak candidates within an explicit tolerance. The phase convention needs a reference; absence of a DEPT signal is not an automatic quaternary-carbon assignment.");
    const f=form(panel,"deptForm",()=>save({op:"dept",name:$("deptName").value,carbon_spectrum_id:$("carbonSpectrum").value,dept_spectrum_id:$("deptSpectrum").value,carbon_prominence:numeric("carbonProminence"),dept_prominence:numeric("deptProminence"),tolerance_ppm:numeric("deptTolerance"),reference_convention:$("deptConvention").value,reference:$("deptReference").value}));
    field(f,"deptName","Analysis name",{required:true,value:"DEPT-135 / carbon evidence"});field(f,"carbonSpectrum","Broadband ¹³C spectrum",{type:"select",required:true});field(f,"deptSpectrum","DEPT-135 spectrum",{type:"select",required:true});
    field(f,"carbonProminence","¹³C peak prominence · intensity",{type:"number",required:true,min:0});field(f,"deptProminence","DEPT peak prominence · intensity",{type:"number",required:true,min:0});field(f,"deptTolerance","Matching tolerance · ppm",{type:"number",required:true,min:0,max:5,value:0.1});
    field(f,"deptConvention","Phase / sign convention",{type:"select",required:true,items:[["","Choose using the reference"],["positive_ch_ch3","Positive CH / CH₃; negative CH₂"],["negative_ch_ch3","Negative CH / CH₃; positive CH₂"]]});field(f,"deptReference","Phase / sample correspondence reference",{required:true});submit(f,"Match DEPT / carbon evidence");
  }
  function buildAssignments(){
    const f=$("assignmentForm"),fields=n("div",undefined,"linked-assignment-fields");f.insertBefore(fields,f.firstElementChild);hint(fields,"Link stable sample, candidate and atom identities when available. Text labels remain editable for older projects.");
    field(fields,"assignmentSampleId","Linked sample · optional",{type:"select"}).onchange=()=>{const sample=p()?.samples[$("assignmentSampleId").value];if(sample)$("sample").value=sample.name;renderAssignmentLinks();};
    field(fields,"assignmentCandidateId","Linked structure candidate · optional",{type:"select"}).onchange=()=>{const candidate=p()?.structures[$("assignmentCandidateId").value];if(candidate){$("candidate").value=candidate.name;$("assignmentSampleId").value=candidate.sample_id;$("sample").value=objectLabel(candidate.sample_id);}renderAssignmentAtoms();};
    field(fields,"assignmentAtomIds","Linked atoms · optional",{type:"select",multiple:true,size:4}).onchange=()=>{const candidate=p()?.structures[$("assignmentCandidateId").value];if(candidate)$("atom").value=candidate.atoms.filter((a)=>selectedIds("assignmentAtomIds").includes(a.id)).map((a)=>a.label).join(", ");};
    const newButton=button(f,"New assignment",()=>{f.reset();$("assignmentId").value="";renderAssignmentAtoms();});newButton.className="secondary";
  }
  function renderAssignmentAtoms(){const candidate=p()?.structures[$("assignmentCandidateId").value];choose("assignmentAtomIds",(candidate?.atoms||[]).map((a)=>[a.id,a.label+" · "+a.element+(a.stereo?" · "+a.stereo:"")]),false);}
  function renderAssignmentLinks(){choose("assignmentSampleId",entries("samples"));const sid=$("assignmentSampleId").value;choose("assignmentCandidateId",entries("structures",(candidate)=>!sid||candidate.sample_id===sid));renderAssignmentAtoms();}
  function assignmentCommand(){return {sample_id:$("assignmentSampleId").value||null,candidate_id:$("assignmentCandidateId").value||null,atom_ids:selectedIds("assignmentAtomIds")};}
  function loadAssignment(assignment){assignmentVersion=assignment.version;$("assignmentSampleId").value=assignment.sample_id||"";renderAssignmentLinks();$("assignmentCandidateId").value=assignment.candidate_id||"";renderAssignmentAtoms();markSelected("assignmentAtomIds",assignment.atom_ids||[]);}
  function prefillAssignment(evidenceId){$("assignmentForm").reset();$("assignmentId").value="";renderAssignmentLinks();api.switchWorkflow("evidence");markSelected("evidenceIds",[evidenceId]);$("observation").focus();api.notice("Evidence selected for a new assignment. Choose the sample / candidate / atoms and explain the observation before saving.");}
  function buildComparison(){
    const panel=$("comparison");title(panel,"Explicit condition comparison","Choose the same signal or relaxation quantity in two samples. Each sample must own the corresponding data; reference conventions and conditions are retained with the result.");
    const f=form(panel,"comparisonForm",()=>save({op:"compare",name:$("comparisonName").value,metric:$("comparisonMetric").value,left_id:$("comparisonLeft").value,right_id:$("comparisonRight").value,left_sample_id:$("comparisonLeftSample").value,right_sample_id:$("comparisonRightSample").value,signal_label:$("comparisonSignal").value,correspondence:$("comparisonCorrespondence").value,independent_uncertainties:$("comparisonIndependent").checked}));
    field(f,"comparisonName","Analysis name",{required:true,value:"Condition comparison"});field(f,"comparisonMetric","Quantity",{type:"select",items:[["T_s","Relaxation time · s"],["chemical_shift_ppm","Chemical shift · ppm"]]}).onchange=()=>{chooseComparisonSources();renderComparisonPreview();};
    field(f,"comparisonLeftSample","Left sample",{type:"select",required:true}).onchange=renderComparisonPreview;field(f,"comparisonLeft","Left result / signal",{type:"select",required:true}).onchange=renderComparisonPreview;
    field(f,"comparisonRightSample","Right sample",{type:"select",required:true}).onchange=renderComparisonPreview;field(f,"comparisonRight","Right result / signal",{type:"select",required:true}).onchange=renderComparisonPreview;
    field(f,"comparisonSignal","Shared signal / quantity label",{required:true});field(f,"comparisonCorrespondence","How the signals correspond",{required:true,placeholder:"Explicit atom, signal, assignment or fit-region match"});
    const check=field(f,"comparisonIndependent","Treat supplied uncertainties as independent",{type:"checkbox"});check.parentElement.classList.add("batch-checkbox");hint(f,"Enable independence only when justified. Missing uncertainty stays unavailable; no uncertainty is inferred from a drawn peak or image.");submit(f,"Compare conditions");
    const view=workspace("comparison","Condition correspondence & comparison","Differences and ratios appear only after the shared scientific service calculates them. Draft selections below show the evidence you are about to compare.");const preview=n("div",undefined,"comparison-pair");preview.id="comparisonPreview";view.append(preview);const cards=n("div");cards.id="comparisonCards";view.append(n("h3","Saved comparisons"),cards);
  }
  function chooseComparisonSources(){const metric=$("comparisonMetric").value,rows=metric==="T_s"?entries("analyses",(a)=>a.kind==="relaxation"):entries("peaklabels");choose("comparisonLeft",rows);choose("comparisonRight",rows);}
  function renderComparisonPreview(){const out=$("comparisonPreview");out.replaceChildren();for(const side of ["Left","Right"]){const sample=p()?.samples[$("comparison"+side+"Sample").value],source=findObject($("comparison"+side).value),card=n("article",undefined,"batch-card");card.append(n("h3",side+" · "+(sample?name(sample):"Choose a sample")));if(sample){hint(card,sample.role.toUpperCase()+" · "+(sample.stage||"Stage unspecified"));hint(card,conditionText(sample));hint(card,"Reference: "+(sample.reference||"unspecified"));}hint(card,source?name(source)+" · "+state(source):"Choose a result / signal");if(source)hint(card,$("comparisonMetric").value==="T_s"?"T = "+fmt(source.result?.T_s)+" s · u(T) = "+fmt(source.result?.u_T_s)+" s":"δ = "+fmt(source.ppm)+" ppm");out.append(card);}}
  function renderComparison(){choose("comparisonLeftSample",entries("samples"));choose("comparisonRightSample",entries("samples"));chooseComparisonSources();renderComparisonPreview();collectionCards($("comparisonCards"),items("analyses").filter((a)=>a.kind==="comparison"),(a,card)=>appendAnalysis(a,card),"No condition comparisons saved.");}
  function appendAnalysis(analysis,card){const r=analysis.result;
    if(analysis.kind==="normalization"){hint(card,"Reference: "+objectLabel(r.reference_integral_id)+" = "+fmt(r.reference_protons)+" protons");dataTable(card,["Integral","Signed area","Relative protons"],(r.integrals||[]).map((i)=>[objectLabel(i.integral_id),fmt(i.signed_area),fmt(i.relative_protons)]));}
    else if(analysis.kind==="dept"){hint(card,"Proposed DEPT evidence · tolerance "+fmt(r.tolerance_ppm)+" ppm · "+r.reference_convention);dataTable(card,["¹³C / ppm","DEPT / ppm","Signed intensity","Interpretation","Matches"],(r.rows||[]).map((row)=>[fmt(row.carbon_ppm),fmt(row.dept_ppm),fmt(row.dept_intensity),row.interpretation,row.matched_candidates]));}
    else if(analysis.kind==="comparison"){
      card.append(n("div",fmt(r.difference)+" "+r.unit+" difference", "result-value"));hint(card,r.signal_label+" · "+r.correspondence);dataTable(card,["Quantity","Value","Standard uncertainty"],[["Left / "+r.unit,fmt(r.left),fmt(r.u_left)],["Right / "+r.unit,fmt(r.right),fmt(r.u_right)],["Right − left / "+r.unit,fmt(r.difference),fmt(r.u_difference)],["Right / left ratio",fmt(r.ratio),fmt(r.u_ratio)]]);
      hint(card,"Recorded left conditions: "+conditionText({conditions:r.left_conditions}));hint(card,"Recorded right conditions: "+conditionText({conditions:r.right_conditions}));hint(card,r.uncertainty_method||"Uncertainty unavailable");
    }else if(analysis.kind==="yield"){
      dataTable(card,["Quantity","Percent","Standard uncertainty / percentage points"],[["Product yield",fmt(r.yield_percent),fmt(r.u_yield_percent)],["Recovered starting material",fmt(r.recovered_percent),fmt(r.u_recovered_percent)],["Product + recovered",fmt(r.mass_balance_percent),fmt(r.u_mass_balance_percent)]]);
    }
  }


  let closed=false;
  function invalidateDrafts(){
    if(saving)return;
    if($("assignmentId").value && p()?.assignments[$("assignmentId").value]?.version!==assignmentVersion){$("assignmentForm").reset();$("assignmentId").value="";draftAlert("The saved assignment changed. Reload it before revising the observation.");}
    const checks=[["sampleId","samples",sampleVersion,loadSample],["structureId","structures",structureVersion,loadStructure],["crosspeakId","crosspeaks",crosspeakVersion,loadCrosspeak],["peakLabelId","peaklabels",peakVersion,loadPeakLabel],["annotationId","annotations",annotationVersion,loadAnnotation]];
    for(const [id,collection,version,reset]of checks){const oid=$(id).value;if(oid&&p()?.[collection]?.[oid]?.version!==version){reset(null);draftAlert("A saved object changed or was removed by another revision. Its editor draft was cleared; reload it before editing.");}}
    for(const [source,collection,reset]of [[gridDraftSource,"grids",()=>loadCrosspeak(null)],[peakDraftSource,"spectra",()=>loadPeakLabel(null)],[annotationDraftSource,"attachments",()=>loadAnnotation(null)]]){
      if(source&&p()?.[collection]?.[source.id]?.version!==source.version){reset();draftAlert("Draft evidence changed. Coordinates were cleared so an old observation cannot overwrite the new source.");}
    }
  }
  function draftAlert(message){$("batchDraftAlert").textContent=message;$("batchDraftAlert").hidden=false;}
  function render(){
    if(lastProject!==null&&lastProject!==p()?.id){
      for(const reset of [loadSample,loadStructure,loadCrosspeak,loadPeakLabel,loadAnnotation])reset(null);
      for(const id of ["attachmentForm","normalizationForm","comparisonForm","deptForm"] )$(id).reset();$("referenceSelect").value="";$("gridSelect").value="";previewKey="";previewRequest++;referenceImage=null;annotationGesture=null;structureGesture=null;gridCache=null;loadYield({});
      draftAlert("Project changed. Previous project drafts were cleared.");
    }
    lastProject=p()?.id??null;invalidateDrafts();
    renderSamples();renderStructures();renderCorrelations();renderReferences();renderOrganicExtensions();renderAssignmentLinks();renderComparison();
    for(const id of ["carbonSpectrum","deptSpectrum"])choose(id,entries("spectra",(s)=>s.domain==="frequency"&&s.nucleus==="13C"));
    sync();queueDraw();
  }
  function workflow(name){
    activeWorkflow=name;const isBatch=batchTabs.has(name);$("batchWorkspace").hidden=!isBatch;document.querySelector(".workspace").classList.toggle("batch-mode",isBatch);document.querySelector(".plot-card").hidden=isBatch;
    document.querySelectorAll(".batch-view").forEach((view)=>view.hidden=view.id!=="view-"+name);annotationGesture=null;cancelStructureDrag();
    if(name==="references")loadPreview();queueDraw();
  }
  function queueDraw(){if(drawQueued)return;drawQueued=true;requestAnimationFrame(()=>{drawQueued=false;if(activeWorkflow==="structures")drawStructure();if(activeWorkflow==="correlations")drawGrid();if(activeWorkflow==="references")drawReference();});}
  function sync(){
    if(closed){document.querySelectorAll("button,input,select,textarea").forEach((control)=>control.disabled=true);return;}
    document.querySelectorAll(".batch-panel button, #batchWorkspace button, .batch-subpanel button").forEach((b)=>b.disabled=api.busy||!p());
  }
  function assignmentInfo(assignment,card){
    if(assignment.sample_id)hint(card,"Linked sample: "+objectLabel(assignment.sample_id));
    const candidate=p()?.structures[assignment.candidate_id];
    if(candidate)hint(card,"Candidate: "+name(candidate)+" · atoms: "+(assignment.atom_ids||[]).map((id)=>candidate.atoms.find((atom)=>atom.id===id)?.label||id).join(", "));
    hint(card,"Evidence: "+assignment.evidence_ids.map(objectLabel).join(", "));
  }
  buildSamples();buildStructures();buildCorrelations();buildReferences();buildOrganicExtensions();buildDept();buildAssignments();buildComparison();
  const alert=n("p",undefined,"warning batch-draft-alert");alert.id="batchDraftAlert";alert.hidden=true;alert.setAttribute("role","alert");$("batchWorkspace").before(alert);
  const close=button(document.querySelector(".header-actions"),"Close workbench",()=>api.act(async()=>{await api.closeWorkbench();closed=true;api.notice("Workbench close requested. Saved project revisions are retained. Reopen the launcher to continue.");}));close.id="closeWorkbench";close.title="Stop this local workbench server; retain saved project revisions";
  const bindSource=(collection,select)=>{const object=p()?.[collection]?.[$(select).value];return object?{id:object.id,version:object.version}:null;};
  for(const id of ["crosspeakX","crosspeakY","crosspeakLabel"])$(id).addEventListener("input",()=>{if(!gridDraftSource)gridDraftSource=bindSource("grids","gridSelect");drawGrid();});
  for(const id of ["peakLabelName","peakPpm","peakMultiplicity","peakProtons"])$(id).addEventListener("input",()=>{if(!peakDraftSource)peakDraftSource=bindSource("spectra","peakSpectrum");});
  for(const id of ["annotationLabel","annotationX","annotationY","annotationWidth","annotationHeight","annotationObservation","annotationPpm","annotationUncertainty"])$(id).addEventListener("input",()=>{
    if(!annotationDraftSource){const source=bindSource("attachments","referenceSelect");annotationDraftSource=source?{...source,page:Number($("referencePage").value)}:null;}
  });
  root.NMRBatch={render,workflow,sync,drawPeakLabels,appendAnalysis,yieldCommand,loadYield,assignmentCommand,loadAssignment,assignmentInfo,importCommand(){return {bruker_processing_numbers:processingNumbers($("brukerProcessingNumbers").value)};},get isBatch(){return batchTabs.has(activeWorkflow);}};
  window.addEventListener("resize",queueDraw);new ResizeObserver(queueDraw).observe($("batchWorkspace"));document.fonts.ready.then(queueDraw);
  api.renderProject();workflow(document.querySelector('[data-tab][aria-selected="true"]')?.dataset.tab||"organic");

})(globalThis);
