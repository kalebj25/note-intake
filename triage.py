"""
triage.py - ERGO inbox triage module.

One job: walk untriaged notes (status: inbox) and route each one - to an active
project, the Vault, reference, or archive - by updating its frontmatter and
moving the file out of the inbox. The inbox drains to zero.

This is the human-in-the-loop step. It does NOT decide for you; it makes
deciding fast. Every decision is appended to triage_log.jsonl, so when you
later want an automated classifier, you'll have a labeled record of your own
judgment to build it from.

Zero dependencies - pure standard library.

Contract
--------
Reads:   <ERGO>/inbox/*.md and *.txt  whose frontmatter has status: inbox
Writes:  updates 'status' and 'project' in frontmatter, then moves the file to
             <ERGO>/projects/<slug>/   (status: linked,   project: <slug>)
             <ERGO>/vault/             (status: triaged,  project: null)
             <ERGO>/reference/         (status: triaged,  project: null)
             <ERGO>/archive/           (status: archived, project: null)
Logs:    appends one JSON line per decision to <ERGO>/triage_log.jsonl
Reads (optional): <ERGO>/active.txt - one project slug per line. This is the
         board's Active list (the <=3 cap). Shown as quick-pick during triage.

Run
---
    ERGO=~/ergo python3 triage.py
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ERGO = Path(os.path.expanduser(os.getenv("ERGO", "~/ergo")))
INBOX = Path(os.path.expanduser(os.getenv("INBOX", str(ERGO / "inbox"))))
LOG = ERGO / "triage_log.jsonl"

# decision -> (destination dir, new status, new project)
DEST = {
    "vault": (ERGO / "vault", "triaged", "null"),
    "reference": (ERGO / "reference", "triaged", "null"),
    "archive": (ERGO / "archive", "archived", "null"),
}


def parse_frontmatter(text):
    """Return (meta dict in file order, body str). Splits on the first --- block only."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta, i = {}, 1
    while i < len(lines) and lines[i].strip() != "---":
        if ":" in lines[i]:
            key, _, val = lines[i].partition(":")
            meta[key.strip()] = val.strip()
        i += 1
    body = "\n".join(lines[i + 1:]) if i < len(lines) else ""
    return meta, body.lstrip("\n")


def serialize(meta, body):
    out = ["---"] + [f"{k}: {v}" for k, v in meta.items()] + ["---", "", ""]
    return "\n".join(out) + body.rstrip("\n") + "\n"


def slugify(name):
    return "".join(c if c.isalnum() else "-" for c in name.strip().lower()).strip("-")


def _log(note_id, decision, project):
    rec = {
        "ts": datetime.now().astimezone().isoformat(),
        "id": note_id,
        "decision": decision,
        "project": project,
    }
    with open(LOG, "a") as f:
        f.write(json.dumps(rec) + "\n")


def route_note(path, decision, project=None, tags=None, cites=None):
    """Apply a triage decision: mutate frontmatter (tags/cites if given), move the file, log it."""
    path = Path(path)
    meta, body = parse_frontmatter(path.read_text())
    if tags is not None:
        meta["tags"] = "[" + ", ".join(t.strip() for t in tags if t.strip()) + "]"
    if cites is not None and (any(c.strip() for c in cites) or "cites" in meta):
        meta["cites"] = "[" + ", ".join(c.strip() for c in cites if c.strip()) + "]"
    if decision == "project":
        slug = slugify(project)
        dest_dir, meta["status"], meta["project"] = ERGO / "projects" / slug, "linked", slug
    else:
        dest_dir, meta["status"], meta["project"] = DEST[decision]
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    dest.write_text(serialize(meta, body))
    path.unlink()
    _log(meta.get("id", path.name), decision, meta.get("project"))
    return dest


def untriaged():
    if not INBOX.exists():
        return []
    out = []
    for p in sorted(INBOX.iterdir()):
        if p.suffix.lower() in (".md", ".txt"):
            meta, _ = parse_frontmatter(p.read_text())
            if meta.get("status", "inbox") == "inbox":
                out.append(p)
    return out


def load_active():
    f = ERGO / "active.txt"
    return [s.strip() for s in f.read_text().splitlines() if s.strip()] if f.exists() else []


def main():
    notes = untriaged()
    if not notes:
        print("Inbox is empty. Nothing to triage.")
        return
    active = load_active()
    total = len(notes)
    print(f"{total} note(s) to triage.\n")
    for idx, path in enumerate(notes, 1):
        meta, body = parse_frontmatter(path.read_text())
        print("=" * 56)
        print(f"[{idx}/{total}]  {meta.get('created','?')}  |  "
              f"{meta.get('source','?')}  |  {meta.get('tags','[]')}")
        print("-" * 56)
        print(body.strip()[:800] or "(empty)")
        print("-" * 56)
        print("  [a] active project   [v] vault   [r] reference")
        print("  [x] archive          [s] skip     [q] quit")
        choice = input("> ").strip().lower()
        if choice == "q":
            print("Stopped.")
            break
        if choice == "s":
            continue
        if choice == "a":
            for i, slug in enumerate(active, 1):
                print(f"   {i}. {slug}")
            pick = input("   project number or new name: ").strip()
            proj = active[int(pick) - 1] if pick.isdigit() and 1 <= int(pick) <= len(active) else pick
            route_note(path, "project", proj)
        elif choice in ("v", "r", "x"):
            route_note(path, {"v": "vault", "r": "reference", "x": "archive"}[choice])
        else:
            print("   (unrecognized - skipping)")
    print(f"\nDone. Inbox now at {len(untriaged())}.")


if __name__ == "__main__":
    main()
