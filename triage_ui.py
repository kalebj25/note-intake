"""
triage_ui.py - a local web front-end for the triage module.

Same job as triage.py, friendlier surface: serves one page that lists your
untriaged notes and lets you classify each with dropdowns (valid values) plus
free text where you need it - a new project name, tags. It reuses triage.py's
routing logic verbatim, so this is just a second front-end on the same core and
the file contract never forks.

Runs locally because it has to touch your actual files; a browser tab inside a
chat cannot reach your disk. Binds to localhost only.

Run
---
    pip install fastapi uvicorn        # already there if you ran note_capture
    ERGO=~/ergo INBOX="<your iCloud inbox path>" python3 triage_ui.py
    # then open http://localhost:8788
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import triage  # reuse the core: untriaged(), route_note(), load_active(), parse_frontmatter(), INBOX

app = FastAPI(title="ERGO triage")
VALID = ("project", "vault", "reference", "archive")
SOURCES = Path(os.path.expanduser(os.getenv("SOURCES", str(triage.ERGO / "sources"))))


def _parse_list(raw):
    s = (raw or "").strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    return [x.strip().strip('"') for x in s.split(",") if x.strip()]


class Decision(BaseModel):
    path: str
    decision: str
    project: str | None = None
    tags: list[str] = []
    cites: list[str] = []


def _safe(path_str: str) -> Path:
    p = Path(path_str).resolve()
    if p.parent != triage.INBOX.resolve():
        raise HTTPException(400, "path is outside the inbox")
    return p


@app.get("/api/inbox")
def inbox():
    notes = []
    for p in triage.untriaged():
        meta, body = triage.parse_frontmatter(p.read_text())
        notes.append({
            "path": str(p),
            "id": meta.get("id", p.name),
            "created": meta.get("created", ""),
            "source": meta.get("source", ""),
            "tags": meta.get("tags", "[]"),
            "cites": _parse_list(meta.get("cites")),
            "body": body.strip(),
        })
    return {"notes": notes, "total": len(notes)}


@app.get("/api/projects")
def projects():
    active = triage.load_active()
    seen = set(active)
    others = []
    pdir = triage.ERGO / "projects"
    if pdir.exists():
        for d in sorted(pdir.iterdir()):
            if d.is_dir() and d.name not in seen:
                others.append(d.name)
    return {"active": active, "others": others}


@app.get("/api/sources")
def sources():
    out = []
    if SOURCES.exists():
        for p in sorted(SOURCES.glob("*.md")):
            meta, _ = triage.parse_frontmatter(p.read_text())
            out.append({"id": meta.get("id", p.stem), "title": (meta.get("title", "") or "").strip('"')})
    return {"sources": out}


@app.post("/api/triage")
def do_triage(d: Decision):
    if d.decision not in VALID:
        raise HTTPException(400, f"decision must be one of {VALID}")
    if d.decision == "project" and not (d.project or "").strip():
        raise HTTPException(400, "a project name is required")
    p = _safe(d.path)
    if not p.exists():
        raise HTTPException(404, "that note is no longer in the inbox")
    dest = triage.route_note(p, d.decision, (d.project or None), (d.tags or None), d.cites)
    return {"ok": True, "dest": str(dest), "remaining": len(triage.untriaged())}


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ERGO Triage</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Manrope:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --ground:#1a1612; --surface-1:#221d18; --surface-2:#2a241e; --surface-3:#332b23;
    --text-primary:#f5f1ea; --text-secondary:#a39c8f; --text-tertiary:#6b6558; --text-quaternary:#4a4538;
    --border-subtle:rgba(245,241,234,.06); --border-medium:rgba(245,241,234,.12);
    --amber:#EF9F27; --amber-text:#FAC775; --amber-dim:rgba(239,159,39,.12);
    --font-display:'Fraunces',Georgia,serif;
    --font-body:'Manrope',-apple-system,BlinkMacSystemFont,sans-serif;
    --font-mono:'Commit Mono','JetBrains Mono',ui-monospace,'SF Mono',Menlo,monospace;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--ground);color:var(--text-primary);font-family:var(--font-body);
       line-height:1.6;-webkit-font-smoothing:antialiased;display:flex;justify-content:center;
       padding:48px 20px 80px;min-height:100vh}
  .wrap{width:100%;max-width:600px}
  .brand-mark{font-family:var(--font-display);font-weight:500;font-size:26px;letter-spacing:-.02em;
              display:flex;align-items:baseline;gap:8px}
  .brand-dots{display:inline-flex;gap:3px;transform:translateY(-2px)}
  .brand-dots span{width:5px;height:5px;border-radius:50%;background:var(--amber);display:block}
  .brand-tag{font-family:var(--font-mono);font-size:10.5px;color:var(--text-tertiary);
             letter-spacing:.12em;text-transform:uppercase;margin:9px 0 30px}
  .brand-tag .count{color:var(--amber-text)}
  .card{background:var(--surface-1);border:.5px solid var(--border-subtle);border-radius:14px;padding:24px;
        transition:opacity .18s ease, transform .18s ease}
  .card.swap{opacity:0;transform:translateY(6px)}
  .meta{font-family:var(--font-mono);font-size:11px;color:var(--text-tertiary);
        padding-bottom:14px;border-bottom:.5px solid var(--border-subtle);display:flex;gap:14px;flex-wrap:wrap}
  .body{font-size:16px;line-height:1.7;white-space:pre-wrap;margin:16px 0 4px;
        word-break:break-word;color:var(--text-primary)}
  .controls{margin-top:24px;display:flex;flex-direction:column;gap:16px}
  label{font-family:var(--font-mono);font-size:10px;letter-spacing:.14em;
        text-transform:uppercase;color:var(--text-tertiary);display:block;margin-bottom:7px}
  select,input{width:100%;font-family:var(--font-body);font-size:15px;color:var(--text-primary);
        background:var(--surface-1);border:.5px solid var(--border-subtle);border-radius:9px;
        padding:12px 13px;appearance:none}
  select:focus,input:focus{outline:none;border-color:var(--border-medium)}
  input::placeholder{color:var(--text-tertiary)}
  .row.hide{display:none}
  .actions{display:flex;gap:10px;margin-top:6px}
  button{font-family:var(--font-body);font-size:15px;font-weight:500;border-radius:9px;
        padding:12px 18px;cursor:pointer;border:.5px solid transparent}
  .route{background:var(--amber-dim);color:var(--amber-text);border-color:rgba(239,159,39,.25);flex:1}
  .route:hover{background:rgba(239,159,39,.18)}
  .skip{background:transparent;color:var(--text-tertiary);border-color:var(--border-subtle)}
  .skip:hover{color:var(--text-secondary);border-color:var(--border-medium)}
  button:focus-visible{outline:2px solid var(--amber);outline-offset:2px}
  .err{color:#d68a63;font-size:12px;font-family:var(--font-mono);min-height:16px;margin-top:2px}
  .empty{text-align:center;padding:64px 16px;color:var(--text-tertiary);
         font-family:var(--font-display);font-style:italic;font-size:18px}
  .empty .big{font-size:22px;color:var(--text-primary);margin-bottom:6px;font-style:normal}
  .chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:6px}
  .chip{display:inline-flex;align-items:center;gap:6px;background:var(--amber-dim);border:.5px solid var(--border-subtle);
        border-radius:14px;padding:3px 10px;font-size:12px;color:var(--amber-text);font-family:var(--font-mono)}
  .chip button{background:none;border:none;color:var(--amber-text);cursor:pointer;font-size:14px;padding:0;line-height:1;font-weight:400}
  .cite-results{border:.5px solid var(--border-subtle);border-radius:9px;margin-top:6px;max-height:170px;overflow:auto;background:var(--surface-2)}
  .cite-results.hide{display:none}
  .cite-results .r{padding:9px 11px;cursor:pointer;border-bottom:.5px solid var(--border-subtle)}
  .cite-results .r:last-child{border-bottom:none}
  .cite-results .r:hover{background:var(--surface-3)}
  .cite-results .r .k{font-family:var(--font-mono);font-size:11px;color:var(--text-tertiary);margin-top:2px}
  @media (prefers-reduced-motion:reduce){.card{transition:none}}
</style>
</head>
<body>
<div class="wrap">
  <div class="brand-mark">ERGO <span class="brand-dots"><span></span><span></span><span></span></span></div>
  <div class="brand-tag">Triage &middot; <span class="count" id="count">&hellip;</span> to clear</div>

  <div id="card" class="card" hidden>
    <div class="meta" id="meta"></div>
    <div class="body" id="body"></div>
    <div class="controls">
      <div>
        <label for="dest">Send to</label>
        <select id="dest">
          <option value="project">Active project</option>
          <option value="vault">Vault</option>
          <option value="reference">Reference</option>
          <option value="archive">Archive</option>
        </select>
      </div>
      <div class="row" id="projectRow">
        <label for="project">Project</label>
        <select id="project"></select>
      </div>
      <div class="row hide" id="newRow">
        <label for="newProject">New project name</label>
        <input id="newProject" placeholder="e.g. ground-up" autocomplete="off">
      </div>
      <div>
        <label for="tags">Tags <span style="text-transform:none;letter-spacing:0">(comma separated, optional)</span></label>
        <input id="tags" placeholder="render, idea" autocomplete="off">
      </div>
      <div>
        <label for="citeSearch">Link sources <span style="text-transform:none;letter-spacing:0">(cites, optional)</span></label>
        <div id="citeChips" class="chips"></div>
        <input id="citeSearch" placeholder="search your sources" autocomplete="off">
        <div id="citeResults" class="cite-results hide"></div>
      </div>
      <div class="err" id="err"></div>
      <div class="actions">
        <button class="route" id="route">Route note</button>
        <button class="skip" id="skip">Skip</button>
      </div>
    </div>
  </div>

  <div id="empty" class="empty" hidden>
    <div class="big">Inbox at zero.</div>
    <div>Nothing left to clear. Capture more and come back.</div>
  </div>
</div>

<script>
let notes = [], idx = 0, projData = {active:[], others:[]}, allSources = [], selectedCites = [];
const $ = id => document.getElementById(id);
const NEW = "__new__";

async function load(){
  projData = await (await fetch("/api/projects")).json();
  allSources = (await (await fetch("/api/sources")).json()).sources;
  notes = (await (await fetch("/api/inbox")).json()).notes;
  fillProjects();
  idx = 0; render();
}

function fillProjects(){
  const sel = $("project");
  sel.innerHTML = "";
  if (projData.active.length){
    const g = document.createElement("optgroup"); g.label = "Active";
    projData.active.forEach(p => g.appendChild(new Option(p, p)));
    sel.add(g);
  }
  if (projData.others.length){
    const g = document.createElement("optgroup"); g.label = "Other projects";
    projData.others.forEach(p => g.appendChild(new Option(p, p)));
    sel.add(g);
  }
  sel.add(new Option("+ New project\u2026", NEW));
}

function stripTags(raw){
  return (raw || "[]").replace(/^\\[|\\]$/g, "").trim();
}

function render(){
  const remaining = notes.length - idx;
  $("count").textContent = remaining;
  if (idx >= notes.length){
    $("card").hidden = true; $("empty").hidden = false; return;
  }
  $("empty").hidden = true;
  const n = notes[idx];
  const card = $("card");
  card.hidden = false; card.classList.add("swap");
  requestAnimationFrame(() => card.classList.remove("swap"));
  $("meta").innerHTML =
    `<span>${n.created || "no date"}</span><span>${n.source || "unknown"}</span><span>${n.tags}</span>`;
  $("body").textContent = n.body || "(empty)";
  $("dest").value = "project";
  $("tags").value = stripTags(n.tags);
  $("newProject").value = "";
  $("err").textContent = "";
  selectedCites = (n.cites || []).slice();
  renderChips();
  $("citeSearch").value = ""; $("citeResults").classList.add("hide");
  syncRows();
}

function syncRows(){
  const dest = $("dest").value;
  $("projectRow").classList.toggle("hide", dest !== "project");
  const isNew = dest === "project" && $("project").value === NEW;
  $("newRow").classList.toggle("hide", !isNew);
}

function esc(s){ return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function citeTitle(id){
  const s = allSources.find(x => x.id === id);
  return s && s.title ? s.title : id;
}

function renderChips(){
  const box = $("citeChips"); box.innerHTML = "";
  selectedCites.forEach(id => {
    const c = document.createElement("span"); c.className = "chip"; c.textContent = citeTitle(id);
    const b = document.createElement("button"); b.type = "button"; b.textContent = "\u00d7"; b.setAttribute("aria-label", "remove");
    b.onclick = () => { selectedCites = selectedCites.filter(x => x !== id); renderChips(); };
    c.appendChild(b); box.appendChild(c);
  });
}

function searchCites(){
  const q = $("citeSearch").value.trim().toLowerCase();
  const res = $("citeResults");
  const hits = !q ? [] : allSources.filter(s =>
    !selectedCites.includes(s.id) &&
    ((s.title || "").toLowerCase().includes(q) || s.id.toLowerCase().includes(q))
  ).slice(0, 8);
  if (!hits.length){ res.classList.add("hide"); res.innerHTML = ""; return; }
  res.innerHTML = ""; res.classList.remove("hide");
  hits.forEach(s => {
    const r = document.createElement("div"); r.className = "r";
    r.innerHTML = esc(s.title || s.id) + '<div class="k">' + esc(s.id) + '</div>';
    r.onclick = () => { selectedCites.push(s.id); renderChips(); $("citeSearch").value = ""; res.classList.add("hide"); res.innerHTML = ""; };
    res.appendChild(r);
  });
}

async function route(){
  const n = notes[idx], dest = $("dest").value;
  let project = null;
  if (dest === "project"){
    project = $("project").value === NEW ? $("newProject").value.trim() : $("project").value;
    if (!project){ $("err").textContent = "Name the project first."; return; }
  }
  const tags = $("tags").value.split(",").map(t => t.trim()).filter(Boolean);
  const res = await fetch("/api/triage", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ path:n.path, decision:dest, project, tags, cites:selectedCites })
  });
  if (!res.ok){ $("err").textContent = (await res.json()).detail || "Couldn't route that one."; return; }
  const known = [...projData.active, ...projData.others];
  if (dest === "project" && project && !known.includes(project)){
    projData = await (await fetch("/api/projects")).json(); fillProjects();
  }
  idx++; render();
}

$("citeSearch").addEventListener("input", searchCites);
$("dest").addEventListener("change", syncRows);
$("project").addEventListener("change", syncRows);
$("route").addEventListener("click", route);
$("skip").addEventListener("click", () => { idx++; render(); });
load();
</script>
</body>
</html>"""

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8788)
