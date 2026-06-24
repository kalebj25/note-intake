"""
board_ui.py - the ERGO project board.

One job: see every project by state and move projects between states. Reads each
projects/<slug>/_project.md, groups by state (active / frozen / vault / done,
plus any unfiled folders), and lets you change a project's state.

_project.md is the single source of truth for state. active.txt is regenerated
from it after every change, so you never hand-edit active.txt again - you set
states here, and triage's dropdown follows.

The three-active cap is enforced by swap: activating a fourth project returns a
409 with the current active list; the client asks which to freeze, then re-calls
with swap_out, and the board freezes one and activates the other in one move.

Run
---
    ERGO=~/ergo/note_intake python3 board_ui.py
    # then open http://localhost:8791
"""

import os
from datetime import date
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import triage  # reuse parse_frontmatter(), serialize(), ERGO

app = FastAPI(title="ERGO board")
ERGO = triage.ERGO
PROJECTS = ERGO / "projects"
STATES = ("active", "frozen", "vault", "done")
CAP = 3


def _unquote(s):
    s = (s or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _note_count(folder: Path):
    n = 0
    for p in folder.iterdir():
        if p.is_file() and p.suffix.lower() in (".md", ".txt") and not p.name.startswith("_"):
            n += 1
    return n


def _read_project(folder: Path):
    mf = folder / "_project.md"
    filed = mf.exists()
    meta, body = (triage.parse_frontmatter(mf.read_text()) if filed else ({}, ""))
    nxt = ""
    for line in body.splitlines():
        if line.strip().lower().startswith("next:"):
            nxt = line.split(":", 1)[1].strip()
            break
    state = meta.get("state", "") if filed else ""
    if state not in STATES:
        state = state if state in STATES else ("" if not filed else state)
    return {
        "slug": meta.get("slug", folder.name) or folder.name,
        "name": meta.get("name", folder.name) or folder.name,
        "state": meta.get("state", "") if filed else "",
        "kind": meta.get("kind", ""),
        "opened": meta.get("opened", ""),
        "done": _unquote(meta.get("done", "")),
        "frozen_reason": _unquote(meta.get("frozen_reason", "")),
        "next": nxt,
        "notes": _note_count(folder),
        "filed": filed,
    }


def _all_projects():
    out = []
    if PROJECTS.exists():
        for d in sorted(PROJECTS.iterdir()):
            if d.is_dir():
                out.append(_read_project(d))
    return out


def _project_folder(slug: str) -> Path:
    d = PROJECTS / Path(slug).name
    if not d.is_dir():
        raise HTTPException(404, "no such project")
    return d


def _set_state(folder: Path, state: str):
    mf = folder / "_project.md"
    if mf.exists():
        meta, body = triage.parse_frontmatter(mf.read_text())
    else:
        meta = {"slug": folder.name, "name": folder.name, "kind": "open-ended",
                "opened": date.today().isoformat(), "done": '""', "frozen_reason": '""'}
        body = "Next: "
    meta["state"] = state
    if state == "frozen" and not _unquote(meta.get("frozen_reason", "")):
        meta["frozen_reason"] = '"Frozen ' + date.today().isoformat() + '"'
    mf.write_text(triage.serialize(meta, body))


def _active_slugs():
    return [p["slug"] for p in _all_projects() if p["state"] == "active"]


def _regen_active_txt():
    new_active = _active_slugs()
    f = ERGO / "active.txt"
    prev = [s.strip() for s in f.read_text().splitlines() if s.strip()] if f.exists() else []
    filed = {p["slug"] for p in _all_projects() if p["filed"]}
    ordered = [s for s in prev if s in new_active]
    ordered += [s for s in new_active if s not in ordered]
    # keep any prev entries that have no manifest yet, so unfiled-active isn't dropped
    ordered += [s for s in prev if s not in ordered and s not in filed]
    f.write_text("\n".join(ordered) + ("\n" if ordered else ""))
    return ordered


@app.get("/api/board")
def board():
    projects = _all_projects()
    return {"projects": projects, "active_count": sum(1 for p in projects if p["state"] == "active"), "cap": CAP}


class StateReq(BaseModel):
    slug: str
    state: str
    swap_out: str | None = None


@app.post("/api/state")
def set_state(req: StateReq):
    if req.state not in STATES:
        raise HTTPException(400, "unknown state")
    folder = _project_folder(req.slug)
    if req.state == "active":
        active = _active_slugs()
        if req.slug not in active and len(active) >= CAP:
            if req.swap_out and req.swap_out in active:
                _set_state(_project_folder(req.swap_out), "frozen")
            else:
                names = [{"slug": s, "name": _read_project(_project_folder(s))["name"]} for s in active]
                raise HTTPException(status_code=409, detail={"reason": "cap", "active": names})
    _set_state(folder, req.state)
    return {"ok": True, "active": _regen_active_txt()}


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ERGO Board</title>
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
  body{background:var(--ground);color:var(--text-primary);font-family:var(--font-body);
       line-height:1.6;-webkit-font-smoothing:antialiased;min-height:100vh}
  .page{max-width:960px;margin:0 auto;padding:48px 40px 80px}
  .brand-mark{font-family:var(--font-display);font-weight:500;font-size:26px;letter-spacing:-.02em;
              display:flex;align-items:baseline;gap:8px}
  .brand-dots{display:inline-flex;gap:3px;transform:translateY(-2px)}
  .brand-dots span{width:5px;height:5px;border-radius:50%;background:var(--amber);display:block}
  .brand-tag{font-family:var(--font-mono);font-size:10.5px;color:var(--text-tertiary);
             letter-spacing:.12em;text-transform:uppercase;margin-top:9px}
  .summary{font-family:var(--font-mono);font-size:11px;color:var(--text-tertiary);margin:26px 0 8px;letter-spacing:.04em}
  .section{margin-top:34px}
  .shead{font-family:var(--font-mono);font-size:11px;letter-spacing:.16em;text-transform:uppercase;
         color:var(--text-secondary);display:flex;align-items:baseline;gap:10px;margin-bottom:14px;
         padding-bottom:10px;border-bottom:.5px solid var(--border-subtle)}
  .shead .n{color:var(--text-tertiary)}
  .shead .n.full{color:var(--amber-text)}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
  .card{background:var(--surface-1);border:.5px solid var(--border-subtle);border-radius:12px;padding:18px 20px}
  .cname{font-size:16px;font-weight:500;color:var(--text-primary)}
  .cmeta{font-family:var(--font-mono);font-size:10.5px;color:var(--text-tertiary);margin-top:5px;letter-spacing:.03em}
  .cdone{font-size:13.5px;color:var(--text-secondary);margin-top:13px;line-height:1.5}
  .cdone.none{color:var(--amber-text);font-style:italic}
  .creason{font-family:var(--font-mono);font-size:11px;color:var(--text-secondary);background:var(--amber-dim);
           border-radius:7px;padding:8px 10px;margin-top:12px;line-height:1.5}
  .cactions{display:flex;flex-wrap:wrap;gap:7px;margin-top:16px}
  button{font-family:var(--font-body);font-size:12.5px;font-weight:500;border-radius:8px;
         padding:7px 13px;cursor:pointer;border:.5px solid var(--border-subtle);
         background:var(--surface-2);color:var(--text-secondary)}
  button:hover{background:var(--surface-3);color:var(--text-primary)}
  button.activate{background:var(--amber-dim);color:var(--amber-text);border-color:rgba(239,159,39,.25)}
  button.activate:hover{background:rgba(239,159,39,.18);color:var(--amber-text)}
  .empty{color:var(--text-tertiary);font-family:var(--font-display);font-style:italic;font-size:17px;
         padding:40px 0}
  .overlay{position:fixed;inset:0;background:rgba(8,6,4,.62);display:flex;align-items:center;justify-content:center;padding:24px}
  .overlay[hidden]{display:none}
  .modal{background:var(--surface-2);border:.5px solid var(--border-medium);border-radius:14px;
         padding:26px 28px;max-width:440px;width:100%}
  .modal h2{font-family:var(--font-display);font-weight:500;font-size:20px;margin-bottom:6px}
  .modal p{font-size:13.5px;color:var(--text-secondary);margin-bottom:18px}
  .swap-list{display:flex;flex-direction:column;gap:8px}
  .swap-row{display:flex;align-items:center;justify-content:space-between;gap:12px;
            background:var(--surface-1);border:.5px solid var(--border-subtle);border-radius:9px;padding:11px 14px}
  .swap-row .sn{font-size:14px}
  .swap-row .ss{font-family:var(--font-mono);font-size:10.5px;color:var(--text-tertiary);margin-top:2px}
  .modal-cancel{margin-top:18px;width:100%;text-align:center}
</style>
</head>
<body>
<div class="page">
  <div class="brand-mark">ERGO <span class="brand-dots"><span></span><span></span><span></span></span></div>
  <div class="brand-tag">Board</div>
  <div class="summary" id="summary"></div>
  <div id="sections"></div>
</div>

<div class="overlay" id="overlay" hidden>
  <div class="modal">
    <h2>Three active already</h2>
    <p id="swapPrompt"></p>
    <div class="swap-list" id="swapList"></div>
    <button class="modal-cancel" id="swapCancel">Cancel</button>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
const ORDER = ["active","frozen","vault","done"];
const LABEL = {active:"Activate", frozen:"Freeze", vault:"Vault", done:"Mark done"};
const HEAD = {active:"Active", frozen:"Frozen", vault:"Vault", done:"Done", unfiled:"Unfiled"};
let data = {projects:[], active_count:0, cap:3};
let pending = null;

function esc(s){ return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

async function load(){
  data = await (await fetch("/api/board")).json();
  render();
}

function bucket(p){ return (p.filed && ORDER.includes(p.state)) ? p.state : "unfiled"; }

function render(){
  const groups = {active:[],frozen:[],vault:[],done:[],unfiled:[]};
  data.projects.forEach(p => groups[bucket(p)].push(p));
  const counts = ORDER.map(s => HEAD[s] + " " + groups[s].length).join("  ·  ");
  $("summary").textContent = counts + (groups.unfiled.length ? "  ·  Unfiled " + groups.unfiled.length : "");

  const secs = $("sections"); secs.innerHTML = "";
  if (!data.projects.length){
    secs.innerHTML = '<div class="empty">No projects yet.</div>'; return;
  }
  ["active","frozen","vault","done","unfiled"].forEach(state => {
    const items = groups[state];
    if (state !== "active" && !items.length) return;
    const sec = document.createElement("div"); sec.className = "section";
    const h = document.createElement("div"); h.className = "shead";
    let label = HEAD[state];
    if (state === "active"){
      const full = data.active_count >= data.cap ? " full" : "";
      label += ' <span class="n' + full + '">' + data.active_count + ' / ' + data.cap + '</span>';
    } else {
      label += ' <span class="n">' + items.length + '</span>';
    }
    h.innerHTML = label; sec.appendChild(h);
    const grid = document.createElement("div"); grid.className = "grid";
    items.forEach(p => grid.appendChild(card(p))); sec.appendChild(grid);
    secs.appendChild(sec);
  });
}

function card(p){
  const el = document.createElement("div"); el.className = "card";
  const meta = [p.slug, p.kind, p.opened && ("opened " + p.opened), p.notes + (p.notes === 1 ? " note" : " notes")]
    .filter(Boolean).join("  ·  ");
  let html = '<div class="cname">' + esc(p.name) + '</div>';
  html += '<div class="cmeta">' + esc(meta) + '</div>';
  if (p.done) html += '<div class="cdone">' + esc(p.done) + '</div>';
  else html += '<div class="cdone none">no finish line set</div>';
  if (p.state === "frozen" && p.frozen_reason) html += '<div class="creason">' + esc(p.frozen_reason) + '</div>';
  el.innerHTML = html;
  const acts = document.createElement("div"); acts.className = "cactions";
  const cur = bucket(p);
  ORDER.forEach(s => {
    if (s === cur) return;
    const b = document.createElement("button");
    if (s === "active") b.className = "activate";
    b.textContent = LABEL[s];
    b.onclick = () => setState(p.slug, s);
    acts.appendChild(b);
  });
  el.appendChild(acts);
  return el;
}

async function setState(slug, state, swapOut){
  const res = await fetch("/api/state", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({slug, state, swap_out: swapOut || null})});
  if (res.status === 409){
    const d = (await res.json()).detail;
    if (d && d.reason === "cap"){ openSwap(slug, d.active); return; }
  }
  if (!res.ok) return;
  closeSwap();
  await load();
}

function openSwap(targetSlug, activeList){
  pending = targetSlug;
  const target = data.projects.find(p => p.slug === targetSlug);
  $("swapPrompt").textContent = "Activating " + (target ? target.name : targetSlug) +
    " means freezing one of these. Which moves to the shelf?";
  const list = $("swapList"); list.innerHTML = "";
  activeList.forEach(a => {
    const row = document.createElement("div"); row.className = "swap-row";
    row.innerHTML = '<div><div class="sn">' + esc(a.name) + '</div><div class="ss">' + esc(a.slug) + '</div></div>';
    const b = document.createElement("button"); b.textContent = "Freeze this";
    b.onclick = () => setState(pending, "active", a.slug);
    row.appendChild(b); list.appendChild(row);
  });
  $("overlay").hidden = false;
}

function closeSwap(){ $("overlay").hidden = true; pending = null; }

$("swapCancel").addEventListener("click", closeSwap);
$("overlay").addEventListener("click", e => { if (e.target === $("overlay")) closeSwap(); });
load();
</script>
</body>
</html>"""


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8791)
