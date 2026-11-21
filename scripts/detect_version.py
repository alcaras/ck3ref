#!/usr/bin/env python3
"""Record the game version + sync time in data/patch.json.

The version comes from the launcher's `rawVersion` (sync.sh copies
launcher/launcher-settings.json into reference/); CK3_VERSION overrides it.
buildId is a hash of 00_defines.txt + dlc_metadata, which changes across
patches even when the launcher file is missing.

Deliberately records NO install paths or machine-identifying data.
"""

import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3

OUT = ck3.ROOT / "data" / "patch.json"


def main():
    version = os.environ.get("CK3_VERSION")
    h = hashlib.sha256()
    for p in (ck3.COMMON / "defines" / "00_defines.txt",
              ck3.REF / "game" / "dlc_metadata" / "00_dlc_metadata.txt"):
        if p.exists():
            h.update(p.read_bytes())
    build_id = h.hexdigest()[:10]
    prev = {}
    if OUT.exists():
        prev = json.loads(OUT.read_text(encoding="utf-8"))
    launcher = ck3.REF / "launcher-settings.json"
    if not version and launcher.exists():
        version = json.loads(launcher.read_text(encoding="utf-8-sig")).get("rawVersion")
    if not version:
        version = prev.get("version") if prev.get("buildId") == build_id else f"build-{build_id}"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "version": version,
        "buildId": build_id,
        "syncedAt": (ck3.REF / ".synced-at").read_text().strip() if (ck3.REF / ".synced-at").exists() else None,
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }, indent=2) + "\n", encoding="utf-8")
    print(f"✓ patch.json — version {version} (build {build_id})")


if __name__ == "__main__":
    main()
