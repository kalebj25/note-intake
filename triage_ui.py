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

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import triage  # reuse the core: untriaged(), route_note(), load_active(), parse_frontmatter(), INBOX

app = FastAPI(title="ERGO triage")
VALID = ("project", "vault", "reference", "archive")


class Decision(BaseModel):
    path: str
    decision: str
    project: str | None = None
    tags: list[str] = []


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
            "body": body.strip(),
        })
    return {"notes": notes, "total": len(notes)}


@app.get("/api/projects")
def projects():
    return {"projects": triage.load_active()}


@app.post("/api/triage")
def do_triage(d: Decision):
    if d.decision not in VALID:
        raise HTTPException(400, f"decision must be one of {VALID}")
    if d.decision == "project" and not (d.project or "").strip():
        raise HTTPException(400, "a project name is required")
    p = _safe(d.path)
    if not p.exists():
        raise HTTPException(404, "that note is no longer in the inbox")
    dest = triage.route_note(p, d.decision, (d.project or None), (d.tags or None))
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
<style>
  :root{
    --paper:#f1f3f1; --card:#ffffff; --ink:#1b211e; --muted:#767c77;
    --line:#e2e5e1; --accent:#1f5e4f; --accent-press:#184d41; --warn:#9a3b2f;
    --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
    --sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);
       display:flex;justify-content:center;padding:40px 20px;min-height:100vh}
  .wrap{width:100%;max-width:560px}
  .eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.18em;
           text-transform:uppercase;color:var(--muted)}
  h1{font-size:26px;font-weight:600;margin:4px 0 28px;letter-spacing:-.01em}
  h1 .count{color:var(--accent)}
  .card{background:var(--card);border:1px solid var(--line);border-radius:13px;
        padding:22px;box-shadow:0 1px 2px rgba(0,0,0,.04);
        transition:opacity .18s ease, transform .18s ease}
  .card.swap{opacity:0;transform:translateY(6px)}
  .meta{font-family:var(--mono);font-size:12px;color:var(--muted);
        padding-bottom:14px;border-bottom:1px solid var(--line);
        display:flex;gap:12px;flex-wrap:wrap}
  .body{font-size:17px;line-height:1.6;white-space:pre-wrap;margin:16px 0 4px;
        word-break:break-word}
  .controls{margin-top:22px;display:flex;flex-direction:column;gap:16px}
  label{font-family:var(--mono);font-size:11px;letter-spacing:.12em;
        text-transform:uppercase;color:var(--muted);display:block;margin-bottom:6px}
  select,input{width:100%;font-family:var(--sans);font-size:15px;color:var(--ink);
        background:var(--card);border:1px solid var(--line);border-radius:9px;
        padding:11px 12px;appearance:none}
  select:focus,input:focus{outline:2px solid var(--accent);outline-offset:1px;border-color:transparent}
  .row.hide{display:none}
  .actions{display:flex;gap:10px;margin-top:6px}
  button{font-family:var(--sans);font-size:15px;font-weight:550;border-radius:9px;
        padding:12px 18px;cursor:pointer;border:1px solid transparent}
  .route{background:var(--accent);color:#fff;flex:1}
  .route:hover{background:var(--accent-press)}
  .skip{background:transparent;color:var(--muted);border-color:var(--line)}
  .skip:hover{color:var(--ink)}
  button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  .err{color:var(--warn);font-size:13px;font-family:var(--mono);min-height:16px;margin-top:2px}
  .empty{text-align:center;padding:48px 16px;color:var(--muted)}
  .empty .big{font-size:20px;color:var(--ink);margin-bottom:6px}
  @media (prefers-reduced-motion:reduce){.card{transition:none}}
</style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">ERGO &middot; Triage</div>
  <h1><span class="count" id="count">&hellip;</span> to clear</h1>

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
let notes = [], idx = 0, projects = [];
const $ = id => document.getElementById(id);
const NEW = "__new__";

async function load(){
  projects = (await (await fetch("/api/projects")).json()).projects;
  notes = (await (await fetch("/api/inbox")).json()).notes;
  fillProjects();
  idx = 0; render();
}

function fillProjects(){
  const sel = $("project");
  sel.innerHTML = "";
  projects.forEach(p => sel.add(new Option(p, p)));
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
  syncRows();
}

function syncRows(){
  const dest = $("dest").value;
  $("projectRow").classList.toggle("hide", dest !== "project");
  const isNew = dest === "project" && $("project").value === NEW;
  $("newRow").classList.toggle("hide", !isNew);
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
    body: JSON.stringify({ path:n.path, decision:dest, project, tags })
  });
  if (!res.ok){ $("err").textContent = (await res.json()).detail || "Couldn't route that one."; return; }
  if (dest === "project" && project && !projects.includes(project)){
    projects.push(project); fillProjects();
  }
  idx++; render();
}

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
