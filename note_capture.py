"""
note_capture.py - ERGO note-capture module.

One job: accept a piece of text and write it as a timestamped markdown file
with frontmatter into an inbox folder. Nothing else.

The reusable asset here is NOT this server - it's the file contract below.
Any producer (iOS Shortcut, voice + Whisper, a CLI, a future app) can honor
the same contract and drop notes into the same inbox. The backend is swappable;
the contract is the interface.

File contract
-------------
path: <INBOX>/YYYY-MM-DD_HHMMSS_<short>.md
body: the raw note text
frontmatter (YAML):
    id       unique id (timestamp + short suffix)
    created  ISO 8601 with timezone
    source   where it came from ("ios-shortcut", "voice", "cli", ...)
    project  project slug, or null  (left null at capture; assigned later)
    tags     list of strings (may be empty)
    status   "inbox" | "triaged" | "linked"  (starts as inbox)

The weekly cadence processes everything with status: inbox - that's the
triage step that moves a raw thought toward a project (or the Vault).

Run
---
    pip install fastapi uvicorn
    INBOX=~/ERGO/inbox python note_capture.py
"""

import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

INBOX = Path(os.path.expanduser(os.getenv("INBOX", "./inbox")))
INBOX.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="ERGO note-capture")


class Note(BaseModel):
    text: str
    source: str = "unknown"
    project: str | None = None
    tags: list[str] = []


def _frontmatter(note_id: str, created: str, note: Note) -> str:
    tags = "[" + ", ".join(note.tags) + "]" if note.tags else "[]"
    project = note.project if note.project else "null"
    return (
        "---\n"
        f"id: {note_id}\n"
        f"created: {created}\n"
        f"source: {note.source}\n"
        f"project: {project}\n"
        f"tags: {tags}\n"
        "status: inbox\n"
        "---\n\n"
    )


@app.post("/note")
def capture(note: Note):
    now = datetime.now().astimezone()
    note_id = f"{now.strftime('%Y-%m-%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
    path = INBOX / f"{note_id}.md"
    path.write_text(_frontmatter(note_id, now.isoformat(), note) + note.text.strip() + "\n")
    return {"id": note_id, "path": str(path)}


@app.get("/health")
def health():
    return {"status": "ok", "inbox": str(INBOX)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8787)
