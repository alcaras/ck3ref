# ck3reference

A static reference site for Crusader Kings III. Every number is read from the
game's own data files and regenerated each patch — the site is a deterministic
projection of the game's script, in the spirit of
[owreference](https://github.com/alcaras/owreference) for Old World.

## How it works

```
make patch   # sync → version → data → art → audit → changelog → build → check
```

- `scripts/sync.sh` copies the needed game subtrees from a local CK3 data
  mirror (`CK3REF_DIR`) into `reference/` with integrity verification.
- `scripts/build_*.py` parse the Jomini script via `scripts/lib/ck3.py` and
  emit deterministic JSON into `src/data/`.
- `scripts/audit.py` fails the build when a patch adds content the site
  silently ignores.
- Astro renders `src/pages/` from the JSON; no client-side framework.

## Requirements

- A CK3 install (or mirror of its `game/` folder) — set `CK3REF_DIR`
- Python 3.12+, Pillow (icon conversion), Node 20+

CK3 game data and art are © Paradox Interactive; this project renders them for
reference, as the community wikis do.
