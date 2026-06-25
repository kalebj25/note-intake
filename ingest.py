"""
ingest.py - ERGO ingest module.

Pulls new note files out of the iCloud capture folder (where the iOS Shortcut
drops them) and moves them into the local inbox. iCloud files often arrive
"dataless" - metadata present (non-zero size in ls) but content not yet on
local disk. Copying those with shutil.move hits fcopyfile and fails with
EDEADLK, leaving empty files. So we force-download each file (brctl) and copy
via read/write bytes, deleting the source only after a verified non-empty write.

Zero dependencies - pure standard library + the `brctl` CLI (ships with macOS).
"""

import os
import subprocess
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


def materialize(path: Path, timeout=15.0) -> bool:
    """Force iCloud to pull a file's content to local disk. Returns True if readable."""
    subprocess.run(["brctl", "download", str(path)],
                   capture_output=True, check=False)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open(path, "rb") as f:
                f.read(1)          # a real read; raises EDEADLK if still dataless
            return True
        except OSError:
            time.sleep(0.5)
    return False


def main():
    if not SRC.exists():
        print(f"Source folder not found:\n  {SRC}\nSet INGEST_SRC to your iCloud capture folder.")
        sys.exit(1)
    DEST.mkdir(parents=True, exist_ok=True)

    moved = skipped = pending = 0

    for src in sorted(SRC.rglob("*")):
        if not (src.is_file() and src.suffix.lower() in EXTS and not src.name.startswith(".")):
            continue
        dest = DEST / src.name
        if dest.exists():
            skipped += 1
            continue

        if not materialize(src):
            pending += 1
            print(f"  still dataless, skipped: {src.name}")
            continue

        try:
            data = src.read_bytes()
        except OSError as e:
            pending += 1
            print(f"  could not read, skipped: {src.name} ({e})")
            continue

        if not data:
            pending += 1
            print(f"  downloaded but empty, skipped: {src.name}")
            continue

        dest.write_bytes(data)
        if dest.stat().st_size == len(data):   # verified write before removing source
            src.unlink()
            moved += 1
        else:
            pending += 1
            print(f"  write mismatch, source kept: {src.name}")

    msg = f"Ingested {moved} note(s) into {DEST}."
    if skipped:
        msg += f" {skipped} already there, left alone."
    if pending:
        msg += f" {pending} could not be pulled down - try again shortly."
    print(msg)


if __name__ == "__main__":
    main()
