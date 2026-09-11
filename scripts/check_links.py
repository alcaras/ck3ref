#!/usr/bin/env python3
"""Post-build check: no broken internal hrefs, no unresolved-term markers."""

import html
import re
import sys
from pathlib import Path

DIST = Path(__file__).resolve().parents[1] / "dist"

# strip the GH Pages base path before matching against dist routes
_conf = (Path(__file__).resolve().parents[1] / "astro.config.mjs").read_text(encoding="utf-8")
_m = re.search(r"base:\s*'([^']*)'", _conf)
BASE = (_m.group(1) if _m else "/").rstrip("/")


def main():
    if not DIST.exists():
        print("✗ dist/ missing — run make build first")
        sys.exit(1)
    pages = {p.relative_to(DIST).as_posix() for p in DIST.rglob("*.html")}
    routes = {"/" + p.removesuffix("index.html").removesuffix(".html").rstrip("/") or "/"
              for p in pages}
    bad = []
    for p in DIST.rglob("*.html"):
        page = p.read_text(encoding="utf-8", errors="replace")
        # Unescape before matching: three region routes contain a literal
        # `&`, which the HTML carries as `&#38;`.
        for m in re.finditer(r'href="([^"]*)"', page):
            href = html.unescape(m.group(1)).split("#", 1)[0]
            if not href.startswith("/"):
                continue
            if BASE and href.startswith(BASE):
                href = href[len(BASE):] or "/"
            href = href.rstrip("/") or "/"
            if href.startswith("//") or "." in href.split("/")[-1]:
                continue
            if href not in routes:
                bad.append(f"{p.relative_to(DIST)} → {m.group(1)}")
        if "term--unknown" in page:
            bad.append(f"{p.relative_to(DIST)}: unresolved <Term>")
    if bad:
        for b in bad[:30]:
            print(f"✗ {b}")
        sys.exit(1)
    print(f"✓ check passed — {len(pages)} pages, no broken links")


if __name__ == "__main__":
    main()
