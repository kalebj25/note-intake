"""
notes_ui.py - ERGO notes viewer/editor.

One job: see the whole note corpus and work it. Lists every note grouped by its
home (active projects first, then other projects, then vault / reference /
archive / inbox), and lets you read a note, edit its body and tags, and delete
it. Routing a note to a different project stays in triage - this module only
edits content, so the two never overlap.

Reads and writes the same note files via triage.py's parse/serialize, so the
file contract never forks. Skips _project.md and other underscore files.

Run
---
    ERGO=~/ergo/note_intake python3 notes_ui.py
    # then open http://localhost:8790
"""

import os
import uuid
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import triage  # reuse parse_frontmatter(), serialize(), ERGO, load_active()

app = FastAPI(title="ERGO notes")
ERGO = triage.ERGO
PROJECTS = ERGO / "projects"
SPECIAL = ("vault", "reference", "archive", "inbox")
EXTS = (".md", ".txt")


def _parse_list(raw):
    s = (raw or "").strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    return [x.strip().strip('"') for x in s.split(",") if x.strip()]


def _title(body, fallback):
    for line in body.splitlines():
        if line.strip():
            return line.strip()[:80]
    return fallback


def _preview(body):
    text = " ".join(body.split())
    return text[:140]


def _safe(rel) -> Path:
    p = (ERGO / rel).resolve()
    root = ERGO.resolve()
    if root != p and root not in p.parents:
        raise HTTPException(400, "path is outside ERGO")
    if not p.is_file() or p.suffix.lower() not in EXTS or p.name.startswith("_"):
        raise HTTPException(404, "not a note")
    return p


def _summary(p: Path, bucket: str):
    meta, body = triage.parse_frontmatter(p.read_text())
    return {
        "path": str(p.relative_to(ERGO)),
        "bucket": bucket,
        "id": meta.get("id", p.name),
        "title": _title(body, meta.get("id", p.name)),
        "preview": _preview(body),
        "created": meta.get("created", ""),
        "source": meta.get("source", ""),
        "tags": _parse_list(meta.get("tags")),
    }


def _bucket_notes(dirpath: Path, bucket: str):
    out = []
    if dirpath.exists():
        for p in sorted(dirpath.iterdir()):
            if p.is_file() and p.suffix.lower() in EXTS and not p.name.startswith("_"):
                out.append(_summary(p, bucket))
    return out


@app.get("/api/notes")
def notes():
    groups, seen = [], set()
    projects_dir = ERGO / "projects"
    for slug in triage.load_active():
        groups.append({"bucket": slug, "label": slug, "notes": _bucket_notes(projects_dir / slug, slug)})
        seen.add(slug)
    if projects_dir.exists():
        for d in sorted(projects_dir.iterdir()):
            if d.is_dir() and d.name not in seen:
                groups.append({"bucket": d.name, "label": d.name, "notes": _bucket_notes(d, d.name)})
    for special in SPECIAL:
        groups.append({"bucket": special, "label": special, "notes": _bucket_notes(ERGO / special, special)})
    groups = [g for g in groups if g["notes"]]
    total = sum(len(g["notes"]) for g in groups)
    return {"groups": groups, "total": total}


@app.get("/api/note")
def get_note(path: str):
    p = _safe(path)
    meta, body = triage.parse_frontmatter(p.read_text())
    return {
        "path": path,
        "id": meta.get("id", p.name),
        "created": meta.get("created", ""),
        "source": meta.get("source", ""),
        "project": meta.get("project", ""),
        "status": meta.get("status", ""),
        "cites": _parse_list(meta.get("cites")),
        "tags": _parse_list(meta.get("tags")),
        "body": body,
    }


class Edit(BaseModel):
    path: str
    body: str = ""
    tags: list[str] = []


@app.post("/api/note")
def save_note(e: Edit):
    p = _safe(e.path)
    meta, _ = triage.parse_frontmatter(p.read_text())
    meta["tags"] = "[" + ", ".join(t.strip() for t in e.tags if t.strip()) + "]"
    p.write_text(triage.serialize(meta, e.body))
    return {"ok": True, "title": _title(e.body, meta.get("id", p.name)), "preview": _preview(e.body)}


class Ref(BaseModel):
    path: str


@app.post("/api/delete")
def delete_note(r: Ref):
    _safe(r.path).unlink()
    return {"ok": True}


@app.get("/api/projects")
def projects():
    active = triage.load_active()
    seen = set(active)
    others = [d.name for d in sorted(PROJECTS.iterdir())
              if d.is_dir() and d.name not in seen] if PROJECTS.exists() else []
    return {"active": active, "others": others}


class Refile(BaseModel):
    path: str
    decision: str
    project: str | None = None


@app.post("/api/refile")
def refile(r: Refile):
    p = _safe(r.path)
    if r.decision not in ("project", "vault", "reference", "archive"):
        raise HTTPException(400, "bad destination")
    if r.decision == "project" and not (r.project or "").strip():
        raise HTTPException(400, "project required")
    dest = triage.route_note(p, r.decision, (r.project or None))
    return {"ok": True, "path": str(dest.relative_to(ERGO))}


class NewNote(BaseModel):
    decision: str
    project: str | None = None
    body: str = ""
    tags: list[str] = []


@app.post("/api/new")
def new_note(n: NewNote):
    if n.decision == "project":
        slug = triage.slugify(n.project or "")
        if not slug:
            raise HTTPException(400, "project required")
        dest_dir, project, status = PROJECTS / slug, slug, "linked"
    elif n.decision in ("inbox", "vault", "reference", "archive"):
        dest_dir, project = ERGO / n.decision, "null"
        status = {"inbox": "inbox", "vault": "triaged", "reference": "triaged", "archive": "archived"}[n.decision]
    else:
        raise HTTPException(400, "bad destination")
    dest_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    fn = dest_dir / (now.strftime("%Y-%m-%d_%H%M%S") + ".md")
    if fn.exists():
        fn = dest_dir / (now.strftime("%Y-%m-%d_%H%M%S") + "_" + uuid.uuid4().hex[:4] + ".md")
    meta = {
        "id": fn.stem,
        "created": now.isoformat(),
        "source": "viewer",
        "project": project,
        "tags": "[" + ", ".join(t.strip() for t in n.tags if t.strip()) + "]",
        "status": status,
    }
    fn.write_text(triage.serialize(meta, n.body))
    return {"ok": True, "path": str(fn.relative_to(ERGO))}


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ERGO Notes</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Manrope:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --ground:#1a1612; --surface-1:#221d18; --surface-2:#2a241e; --surface-3:#332b23;
    --surface-hover:rgba(245,241,234,.025);
    --text-primary:#f5f1ea; --text-secondary:#a39c8f; --text-tertiary:#6b6558; --text-quaternary:#4a4538;
    --border-subtle:rgba(245,241,234,.06); --border-medium:rgba(245,241,234,.12);
    --amber:#EF9F27; --amber-text:#FAC775; --amber-dim:rgba(239,159,39,.12);
    --font-display:'Fraunces',Georgia,serif;
    --font-body:'Manrope',-apple-system,BlinkMacSystemFont,sans-serif;
    --font-mono:'Commit Mono','JetBrains Mono',ui-monospace,'SF Mono',Menlo,monospace;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{height:100%}
  body{background:var(--ground);color:var(--text-primary);font-family:var(--font-body);
       font-weight:400;line-height:1.6;-webkit-font-smoothing:antialiased}
  .app{display:grid;grid-template-columns:280px 1fr;height:100vh}
  .sidebar{border-right:.5px solid var(--border-subtle);display:flex;flex-direction:column;min-height:0}
  .shead{padding:34px 24px 16px}
  .brand-mark{font-family:var(--font-display);font-weight:500;font-size:24px;letter-spacing:-.02em;
              display:flex;align-items:baseline;gap:7px;color:var(--text-primary)}
  .brand-dots{display:inline-flex;gap:3px;transform:translateY(-2px)}
  .brand-dots span{width:5px;height:5px;border-radius:50%;background:var(--amber);display:block}
  .brand-tag{font-family:var(--font-mono);font-size:10.5px;color:var(--text-tertiary);
             letter-spacing:.12em;text-transform:uppercase;margin-top:9px}
  .brand-tag .count{color:var(--amber-text)}
  #filter{width:100%;font-family:var(--font-body);font-size:14px;color:var(--text-primary);
          background:var(--surface-1);border:.5px solid var(--border-subtle);border-radius:9px;
          padding:10px 12px;margin-top:18px}
  #filter::placeholder{color:var(--text-tertiary)}
  #filter:focus{outline:none;border-color:var(--border-medium)}
  #list{overflow:auto;padding:4px 14px 28px;min-height:0;flex:1}
  .group{margin-top:18px}
  .ghead{font-family:var(--font-mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;
         color:var(--text-tertiary);padding:4px 10px;display:flex;justify-content:space-between}
  .row{padding:10px 11px;border-radius:8px;cursor:pointer;border-left:2px solid transparent;margin-bottom:1px}
  .row:hover{background:var(--surface-hover)}
  .row.sel{background:var(--surface-1);border-left-color:var(--amber)}
  .row .t{font-size:14px;line-height:1.4;margin-bottom:3px;color:var(--text-primary)}
  .row .s{font-family:var(--font-mono);font-size:10.5px;color:var(--text-tertiary);
          white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .editor{overflow:auto;padding:48px 56px;display:flex;justify-content:center}
  .pane{width:100%;max-width:680px}
  .meta{font-family:var(--font-mono);font-size:11px;color:var(--text-tertiary);display:flex;gap:16px;flex-wrap:wrap;
        padding-bottom:18px;margin-bottom:20px;border-bottom:.5px solid var(--border-subtle)}
  .cites{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:22px}
  .chip{font-family:var(--font-mono);font-size:11px;background:var(--amber-dim);border:.5px solid var(--border-subtle);
        border-radius:13px;padding:3px 10px;color:var(--amber-text)}
  label{font-family:var(--font-mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;
        color:var(--text-tertiary);display:block;margin-bottom:8px}
  input.f,textarea{width:100%;font-family:var(--font-body);color:var(--text-primary);background:var(--surface-1);
        border:.5px solid var(--border-subtle);border-radius:9px;padding:12px 13px}
  input.f{font-size:15px;margin-bottom:22px}
  textarea{font-size:16px;line-height:1.7;min-height:44vh;resize:vertical}
  input.f::placeholder,textarea::placeholder{color:var(--text-tertiary)}
  input.f:focus,textarea:focus{outline:none;border-color:var(--border-medium)}
  .actions{display:flex;gap:12px;margin-top:22px;align-items:center}
  button{font-family:var(--font-body);font-size:14px;font-weight:500;border-radius:9px;padding:11px 20px;cursor:pointer;border:.5px solid transparent}
  .save{background:var(--amber-dim);color:var(--amber-text);border-color:rgba(239,159,39,.25)}
  .save:hover{background:rgba(239,159,39,.18)}
  .del{background:transparent;color:var(--text-tertiary);border-color:var(--border-subtle);margin-left:auto}
  .del:hover{color:var(--text-secondary);border-color:var(--border-medium)}
  .msg{font-family:var(--font-mono);font-size:11px;color:var(--text-tertiary);min-height:14px}
  .msg.ok{color:var(--amber-text)}
  .empty{display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-tertiary);
         text-align:center;font-family:var(--font-display);font-style:italic;font-size:18px}
  [hidden]{display:none!important}
  .newbtn{margin-top:10px;width:100%;font-family:var(--font-body);font-size:13px;font-weight:500;
          background:var(--amber-dim);color:var(--amber-text);border:.5px solid rgba(239,159,39,.25);
          border-radius:9px;padding:9px;cursor:pointer}
  .newbtn:hover{background:rgba(239,159,39,.18)}
  select.f{appearance:none;background:var(--surface-1);color:var(--text-primary);
           border:.5px solid var(--border-subtle);border-radius:9px;padding:12px 13px;
           font-family:var(--font-body);font-size:15px;width:100%}
  select.f:focus{outline:none;border-color:var(--border-medium)}
  .destrow{margin-bottom:22px}
  .moverow{margin-top:28px;padding-top:20px;border-top:.5px solid var(--border-subtle)}
  .moveline{display:flex;gap:10px}
  .moveline select{flex:1}
  .moveline button{white-space:nowrap;background:var(--surface-2);color:var(--text-secondary);
                   border:.5px solid var(--border-subtle);border-radius:9px;padding:0 18px;cursor:pointer;
                   font-family:var(--font-body);font-size:14px}
  .moveline button:hover{background:var(--surface-3);color:var(--text-primary)}
  .create{background:var(--amber-dim);color:var(--amber-text);border:.5px solid rgba(239,159,39,.25);
          font-family:var(--font-body);font-size:14px;font-weight:500;border-radius:9px;padding:11px 20px;cursor:pointer}
  .create:hover{background:rgba(239,159,39,.18)}
  @media (max-width:760px){.app{grid-template-columns:1fr}.sidebar{max-height:42vh}.editor{padding:28px 24px}}
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar">
    <div class="shead">
      <div class="brand-mark">ERGO <span class="brand-dots"><span></span><span></span><span></span></span></div>
      <div class="brand-tag">Notes &middot; <span class="count" id="count"></span></div>
      <input id="filter" placeholder="filter by text or tag" autocomplete="off">
      <button id="newBtn" class="newbtn">+ New note</button>
    </div>
    <div id="list"></div>
  </aside>
  <main class="editor">
    <div id="empty" class="empty">Select a note to read or edit.</div>
    <div id="pane" class="pane" hidden>
      <div class="meta" id="meta"></div>
      <div class="cites" id="cites"></div>
      <div class="destrow" id="destRow" hidden>
        <label for="newDest">Destination</label>
        <select id="newDest" class="f"></select>
      </div>
      <label for="tags">Tags</label>
      <input id="tags" class="f" placeholder="comma separated" autocomplete="off">
      <label for="body">Note</label>
      <textarea id="body"></textarea>
      <div class="actions">
        <button class="save" id="save">Save</button>
        <button class="create" id="create" hidden>Create note</button>
        <span class="msg" id="msg"></span>
        <button class="del" id="del">Delete</button>
      </div>
      <div class="moverow" id="moveRow">
        <label for="moveDest">Move to</label>
        <div class="moveline">
          <select id="moveDest" class="f"></select>
          <button id="moveBtn">Move</button>
        </div>
      </div>
    </div>
  </main>
</div>
<script>
const $ = id => document.getElementById(id);
let groups = [], current = null, projects = {active:[], others:[]}, mode = "edit";

function esc(s){ return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

async function load(){
  const d = await (await fetch("/api/notes")).json();
  groups = d.groups;
  $("count").textContent = d.total;
  projects = await (await fetch("/api/projects")).json();
  render();
}

function fillDest(sel, includeInbox){
  sel.innerHTML = "";
  if (projects.active.length){
    const g = document.createElement("optgroup"); g.label = "Active";
    projects.active.forEach(s => g.appendChild(new Option(s, "project:" + s))); sel.add(g);
  }
  if (projects.others.length){
    const g = document.createElement("optgroup"); g.label = "Other projects";
    projects.others.forEach(s => g.appendChild(new Option(s, "project:" + s))); sel.add(g);
  }
  const gb = document.createElement("optgroup"); gb.label = "Buckets";
  if (includeInbox) gb.appendChild(new Option("Inbox", "inbox"));
  gb.appendChild(new Option("Vault", "vault"));
  gb.appendChild(new Option("Reference", "reference"));
  gb.appendChild(new Option("Archive", "archive"));
  sel.add(gb);
}

function destPayload(v){
  return v.startsWith("project:") ? {decision:"project", project:v.slice(8)} : {decision:v, project:null};
}

function startNew(){
  mode = "new"; current = null;
  $("empty").hidden = true; $("pane").hidden = false;
  $("meta").hidden = true; $("cites").hidden = true; $("moveRow").hidden = true;
  $("save").hidden = true; $("del").hidden = true;
  $("destRow").hidden = false; $("create").hidden = false;
  fillDest($("newDest"), true);
  $("tags").value = ""; $("body").value = "";
  $("msg").textContent = ""; $("msg").className = "msg";
  document.querySelectorAll(".row").forEach(r => r.classList.remove("sel"));
  $("body").focus();
}

async function createNote(){
  const res = await fetch("/api/new", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({...destPayload($("newDest").value), body:$("body").value,
      tags:$("tags").value.split(",").map(s=>s.trim()).filter(Boolean)})});
  if (!res.ok){ $("msg").className="msg"; $("msg").textContent="Create failed."; return; }
  const d = await res.json();
  await load(); select(d.path);
}

async function moveNote(){
  if (!current) return;
  const res = await fetch("/api/refile", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({path:current, ...destPayload($("moveDest").value)})});
  if (!res.ok){ $("msg").className="msg"; $("msg").textContent="Move failed."; return; }
  const d = await res.json();
  await load(); select(d.path);
}

function render(){
  const q = $("filter").value.trim().toLowerCase();
  const box = $("list"); box.innerHTML = "";
  groups.forEach(g => {
    const hits = !q ? g.notes : g.notes.filter(n =>
      (n.title + " " + n.preview + " " + (n.tags||[]).join(" ")).toLowerCase().includes(q));
    if (!hits.length) return;
    const gr = document.createElement("div"); gr.className = "group";
    const h = document.createElement("div"); h.className = "ghead";
    h.innerHTML = "<span>" + esc(g.label) + "</span><span>" + hits.length + "</span>";
    gr.appendChild(h);
    hits.forEach(n => {
      const r = document.createElement("div"); r.className = "row" + (current === n.path ? " sel" : "");
      r.dataset.path = n.path;
      r.innerHTML = '<div class="t">' + esc(n.title) + '</div><div class="s">' +
                    esc(n.created.slice(0,10) || n.source || "") + '</div>';
      r.onclick = () => select(n.path);
      gr.appendChild(r);
    });
    box.appendChild(gr);
  });
}

async function select(path){
  mode = "edit"; current = path;
  const n = await (await fetch("/api/note?path=" + encodeURIComponent(path))).json();
  $("empty").hidden = true; $("pane").hidden = false;
  $("meta").hidden = false; $("cites").hidden = false; $("moveRow").hidden = false;
  $("save").hidden = false; $("del").hidden = false;
  $("destRow").hidden = true; $("create").hidden = true;
  fillDest($("moveDest"), false);
  $("meta").innerHTML = [
    n.id && "id " + esc(n.id),
    n.created && esc(n.created.slice(0,16).replace("T"," ")),
    n.source && "via " + esc(n.source),
    n.project && n.project !== "null" && "project " + esc(n.project),
    n.status && esc(n.status),
  ].filter(Boolean).map(s => "<span>" + s + "</span>").join("");
  $("cites").innerHTML = (n.cites||[]).map(c => '<span class="chip">' + esc(c) + '</span>').join("");
  $("tags").value = (n.tags||[]).join(", ");
  $("body").value = n.body;
  $("msg").textContent = ""; $("msg").className = "msg";
  document.querySelectorAll(".row").forEach(r => r.classList.toggle("sel", r.dataset.path === path));
}

async function save(){
  if (!current) return;
  const tags = $("tags").value.split(",").map(s => s.trim()).filter(Boolean);
  const res = await fetch("/api/note", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({path: current, body: $("body").value, tags})});
  if (!res.ok){ $("msg").className = "msg"; $("msg").textContent = "Save failed."; return; }
  const d = await res.json();
  for (const g of groups){ const n = g.notes.find(x => x.path === current);
    if (n){ n.title = d.title; n.preview = d.preview; n.tags = tags; } }
  render();
  $("msg").className = "msg ok"; $("msg").textContent = "Saved";
}

async function del(){
  if (!current) return;
  if (!confirm("Delete this note? This removes the file.")) return;
  const res = await fetch("/api/delete", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({path: current})});
  if (!res.ok){ $("msg").className = "msg"; $("msg").textContent = "Delete failed."; return; }
  for (const g of groups) g.notes = g.notes.filter(x => x.path !== current);
  groups = groups.filter(g => g.notes.length);
  $("count").textContent = groups.reduce((a,g) => a + g.notes.length, 0);
  current = null; $("pane").hidden = true; $("empty").hidden = false;
  render();
}

$("filter").addEventListener("input", render);
$("save").addEventListener("click", save);
$("del").addEventListener("click", del);
$("newBtn").addEventListener("click", startNew);
$("create").addEventListener("click", createNote);
$("moveBtn").addEventListener("click", moveNote);
load();
</script>
</body>
</html>"""


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8790)
