#!/usr/bin/env python3
"""Verify the pinned upstream snapshot without Git or network access."""
import hashlib
import json
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parent / "vendor"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    failures = []
    for entry in manifest["files"]:
        path = root / entry["path"]
        if not path.is_file():
            failures.append(f"Missing: {entry['path']}")
            continue
        data = path.read_bytes()
        sha256 = hashlib.sha256(data).hexdigest()
        blob_sha = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if sha256 != entry["sha256"] or blob_sha != entry["git_blob_sha1"]:
            failures.append(f"Modified upstream file: {entry['path']}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"Verified {len(manifest['files'])} pinned upstream files")
    for name, repository in manifest["repositories"].items():
        print(f"  {name}: {repository['commit']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
