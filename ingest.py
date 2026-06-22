"""
ingest.py - ERGO ingest module.

One job: pull new note files out of the iCloud capture folder (where the iOS
Shortcut drops them) and move them into the local inbox. After this runs the
local inbox holds everything, and triage reads a plain local folder - no iCloud
paths, no placeholder quirks downstream.

Zero dependencies - pure standard library.

Contract
--------
Source: <INGEST_SRC>  - searched recursively for *.md and *.txt
Dest:   <ERGO>/inbox  - each file is MOVED here (the source drains to empty)
        A file already present in the dest (by name) is left untouched.
iCloud placeholders (.name.icloud stubs) are downloaded best-effort; any that
won't materialize are reported so you can download them once in Finder.

Run
---
    ERGO=~/ergo INGEST_SRC="<iCloud capture folder>" python3 ingest.py
"""

import os
import shutil
import sys
import time
from pathlib import Path

ERGO = Path(os.path.expanduser(os.getenv("ERGO", "~/ergo")))
DEST = ERGO / "inbox"
SRC = Path(os.path.expanduser(os.getenv(
    "INGEST_SRC",
    "~/Library/Mobile Documents/iCloud~is~workflow~my~workflows/Documents/ergo",
)))
EXTS = {".md", ".txt"}


def materialize(stub: Path, timeout=8.0):
    """Best-effort download of an iCloud placeholder. Returns the real path or None."""
    real = stub.with_name(stub.name[1:-len(".icloud")])  # ".x.txt.icloud" -> "x.txt"
    try:
        with open(real, "rb") as f:  # touching the real path asks iCloud to fetch it
            f.read(1)
    except Exception:
        pass
    deadline = time.time() + timeout
    while time.time() < deadline:
        if real.exists():
            return real
        time.sleep(0.4)
    return real if real.exists() else None


def main():
    if not SRC.exists():
        print(f"Source folder not found:\n  {SRC}\nSet INGEST_SRC to your iCloud capture folder.")
        sys.exit(1)
    DEST.mkdir(parents=True, exist_ok=True)

    moved = skipped = pending = 0

    # 1) try to pull down any placeholders first
    for stub in list(SRC.rglob(".*.icloud")):
        if materialize(stub) is None:
            pending += 1

    # 2) move real note files into the local inbox
    for src in sorted(SRC.rglob("*")):
        if src.is_file() and src.suffix.lower() in EXTS and not src.name.startswith("."):
            dest = DEST / src.name
            if dest.exists():
                skipped += 1
                continue
            shutil.move(str(src), str(dest))
            moved += 1

    msg = f"Ingested {moved} note(s) into {DEST}."
    if skipped:
        msg += f" {skipped} already there, left alone."
    if pending:
        msg += f" {pending} still in iCloud (not downloaded) - open them once in Finder."
    print(msg)


if __name__ == "__main__":
    main()
