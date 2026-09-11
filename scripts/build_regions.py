#!/usr/bin/env python3
"""Build src/data/regions.json — CK3's geographical regions.

612 named province sets declared across four files. They gate traditions,
casus belli, activities, situations, decisions, events, disasters, trade,
hunting animals and Chinese title naming, and the game has no UI that shows
what any of them covers.

What is emitted per region:
  * the membership the game DECLARES (duchies / counties / kingdoms /
    provinces / sub-regions), at that granularity — resolved province lists
    total 320k ids across all regions and belong in the browser, built from
    public/map/geo-tree.json, not in this file;
  * resolved counts, so the page can state size without shipping the sets;
  * the flags, including the two modifiers `generate_modifiers` creates;
  * `parents` — the regions that include this one;
  * `bbox` in raster pixel coordinates, for zoom-to-region;
  * `usedBy` — every file under common/ and events/ that names the region,
    grouped by category.

Runs after build_map.py: geo-tree.json and .cache/province-bbox.json are its
inputs.
"""

import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

MAP = ck3.REF / "game" / "map_data"

FILES = [
    MAP / "geographical_regions" / "geographical_region.txt",
    MAP / "geographical_regions" / "10_natural_disaster_regions.txt",
    MAP / "geographical_regions" / "tgp_chinesenaming_regions.txt",
    MAP / "island_region.txt",
]

# The file header documents every field a region may declare. Anything here
# that is not in DECLARED is a field we resolve but do not treat as membership.
DECLARED = ["hegemonies", "empires", "kingdoms", "duchies", "counties",
            "provinces", "regions"]
FLAGS = ["generate_modifiers", "graphical", "should_remember_counties_order"]

# ---------------------------------------------------------------------------
# Families — our grouping, not the game's. The game ships no taxonomy of
# regions, so the page groups them by key prefix, which is how the files
# themselves are organised. Every key must match a rule: an unmapped prefix
# fails the audit, so a patch that adds a new family is noticed rather than
# silently filed under "other".
# ---------------------------------------------------------------------------
FAMILY_BY_FILE = {
    "island_region.txt": "Island",
    "10_natural_disaster_regions.txt": "Natural disaster",
}
FAMILY_BY_PREFIX = [  # longest first
    ("tgp_silk_road_", "Silk Road"),
    ("seasonal_region_", "Seasonal"),
    ("graphical_", "Graphical"),
    ("heritage_", "Heritage"),
    ("material_", "Material"),
    ("special_", "Special"),
    ("custom_", "Custom"),
    ("world_", "World"),
    ("hunt_", "Hunt"),
    ("sea_", "Sea"),
    ("ghw_", "GHW"),
    ("dlc_", "DLC"),
    ("tgp_", "Chinese naming"),
]
FAMILY_BY_SUFFIX = [
    ("_de_jure_region", "Special"),   # the Mongol khanate de jure claims
    ("_nomad_area", "Nomad"),
]
# One-offs, listed individually on purpose: a catch-all would defeat the
# tripwire above.
FAMILY_BY_KEY = {
    "islamic_heartlands": "Other",
    "kirghiz_homelands": "Other",
    "divergence_island_regions": "Other",
    "board_game_fidchell_region": "Other",
    "troy_region": "Other",
    "israel_region": "Other",
    "mediteranean_coast": "Other",
    "greek_backwater_modifier_region": "Other",
    "black_sea_coast_region": "Other",
    "paddy_fields_region": "Other",
    # the game's own key is missing an underscore, so the _de_jure_region
    # suffix rule does not reach it
    "togskol_khanatede_jure_region": "Special",
    "tgp_china_tributary_region": "Chinese naming",
    "mpo_region_permafrost": "Other",
    "cp4_music_area": "Other",
}
FAMILY_ORDER = ["World", "Custom", "GHW", "DLC", "Sea", "Material", "Hunt",
                "Special", "Heritage", "Silk Road", "Nomad", "Seasonal",
                "Natural disaster", "Chinese naming", "Island", "Graphical",
                "Other"]

# `generate_modifiers = yes` makes the engine create these two modifiers per
# region (documented in geographical_region.txt's own header). Their magnitude
# comes from whatever applies them, so only the name is stated here.
GENERATED_MODIFIERS = ["development_growth", "development_growth_factor"]

SCAN_ROOTS = [ck3.REF / "game" / "common", ck3.REF / "game" / "events"]


def family_of(key, filename):
    fam = FAMILY_BY_FILE.get(filename)
    if fam:
        return fam
    if key in FAMILY_BY_KEY:
        return FAMILY_BY_KEY[key]
    for suffix, fam in FAMILY_BY_SUFFIX:
        if key.endswith(suffix):
            return fam
    for prefix, fam in FAMILY_BY_PREFIX:
        if key.startswith(prefix):
            return fam
    return None


def slug_of(key):
    """URL-safe route segment. Three region keys contain a literal `&`
    (`ghw_region_finland_&_estonia` and friends); everything else is already
    [a-z0-9_]. The pages still show the real key — this is only the URL."""
    return key.replace("&", "and")


def pretty_key(key):
    """A readable stand-in for the 365 regions with no localized name.

    Deliberately NOT presented as a name: the page labels these as internal
    keys, because title-casing `ghw_region_the_sahel` into "The Sahel" would
    put a name in the reader's mouth that the game never gives.
    """
    return key.replace("_", " ").strip()


def load_regions():
    regions, order = {}, []
    unknown_fields = Counter()
    for path in FILES:
        blk = ck3.parse_file(path)
        for key, _op, val in blk:
            if key is None:
                continue
            if not isinstance(val, (Block, Tagged)):
                print(f"⚠ {path.name}: {key} is not a block — skipped")
                continue
            body = val.block if isinstance(val, Tagged) else val
            if key in regions:
                print(f"⚠ duplicate region key {key} ({path.name}) — last wins")
            rec = {"id": key, "file": path.name}
            for field in DECLARED:
                vals = []
                for v in body.get_all(field):
                    if isinstance(v, (Block, Tagged)):
                        b = v.block if isinstance(v, Tagged) else v
                        vals += [x for x in b.values() if isinstance(x, (str, int))]
                if vals:
                    rec[field] = vals
            for flag in FLAGS:
                if body.get(flag) is True:
                    rec[flag] = True
            col = body.get("color")
            if col is not None:
                from build_map import color_hex
                rec["color"] = color_hex(col)
            for k, _o, _v in body:
                if k is not None and k not in DECLARED and k not in FLAGS and k != "color":
                    unknown_fields[k] += 1
            regions[key] = rec
            order.append(key)
    if unknown_fields:
        print("⚠ unhandled region fields (not rendered):")
        for k, n in unknown_fields.most_common():
            print(f"    {k} ×{n}")
    return regions, order, unknown_fields


class Geo:
    """The de jure tree as geo-tree.json ships it: n/c/ch/p, children only."""

    def __init__(self, tree):
        self.tree = tree
        self.county_provinces = {k: v.get("p", []) for k, v in tree["county"].items()}
        self.duchy_of = {c: d for d, rec in tree["duchy"].items()
                         for c in rec.get("ch", [])}
        self.kingdom_of = {d: k for k, rec in tree["kingdom"].items()
                           for d in rec.get("ch", [])}
        self.county_of = {p: c for c, ps in self.county_provinces.items() for p in ps}

    def provinces_of(self, tier, key):
        rec = self.tree[tier].get(key)
        if rec is None:
            return None
        if tier == "county":
            return rec.get("p", [])
        child = {"duchy": "county", "kingdom": "duchy", "empire": "kingdom"}[tier]
        out = []
        for k in rec.get("ch", []):
            out += self.provinces_of(child, k) or []
        return out

    def touched(self, provinces):
        """The counties/duchies/kingdoms a set of provinces actually sits in.

        Derived upward from the provinces rather than from what the region
        declares, so a region that lists bare province ids still reports the
        counties it covers, and one that lists duchies still reports the
        kingdoms it reaches into.
        """
        counties = {self.county_of[p] for p in provinces if p in self.county_of}
        duchies = {self.duchy_of[c] for c in counties if c in self.duchy_of}
        kingdoms = {self.kingdom_of[d] for d in duchies if d in self.kingdom_of}
        return counties, duchies, kingdoms


def scan_usage(keys):
    """Every file under common/ and events/ that names a region key.

    One compiled alternation over all 612 keys: 612 separate passes over 3k
    files would take minutes. Word boundaries keep `world_europe` from
    matching inside `world_europe_west` (underscore is a word character).
    """
    pattern = re.compile(r"\b(" + "|".join(sorted(map(re.escape, keys), key=len,
                                                  reverse=True)) + r")\b")
    hits = defaultdict(lambda: defaultdict(set))
    region_files = {f.resolve() for f in FILES}
    n_files = 0
    t0 = time.time()
    for root in SCAN_ROOTS:
        for path in sorted(root.rglob("*.txt")):
            if path.resolve() in region_files or path.name.startswith("_"):
                continue
            n_files += 1
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            found = set(pattern.findall(text))
            if not found:
                continue
            rel = path.relative_to(ck3.REF / "game")
            category = rel.parts[1] if rel.parts[0] == "common" and len(rel.parts) > 2 \
                else ("events" if rel.parts[0] == "events" else rel.parts[0])
            for key in found:
                hits[key][category].add(rel.as_posix())
    print(f"  cross-reference scan: {n_files} files in {time.time() - t0:.1f}s")
    return hits


def main():
    regions, order, _unhandled = load_regions()
    print(f"  {len(regions)} regions across {len(FILES)} files")

    # families
    fams = {}
    unmapped = []
    for key, rec in regions.items():
        fam = family_of(key, rec["file"])
        if fam is None:
            unmapped.append(key)
        fams[key] = fam
    if unmapped:
        raise SystemExit(
            "✗ region keys match no family rule — add them to build_regions.py's "
            f"family map: {sorted(unmapped)}")
    fam_counts = Counter(fams.values())
    print("  families: " + ", ".join(f"{f} {fam_counts[f]}"
                                     for f in FAMILY_ORDER if fam_counts[f]))

    # the two fields the file header documents but nothing uses today
    for field in ("empires", "hegemonies"):
        users = [k for k, r in regions.items() if field in r]
        if users:
            print(f"⚠ {field} is now used by {len(users)} region(s) — the page renders "
                  f"it, but check the resolver: {users[:6]}")

    inputs = {
        "geo-tree": ck3.ROOT / "public" / "map" / "geo-tree.json",
        "map-meta": ck3.ROOT / "public" / "map" / "map-meta.json",
        # not committed (.cache is gitignored) — build_map.py regenerates it
        "province-bbox": ck3.ROOT / ".cache" / "province-bbox.json",
    }
    missing = [str(v.relative_to(ck3.ROOT)) for v in inputs.values() if not v.exists()]
    if missing:
        raise SystemExit(f"✗ {', '.join(missing)} missing — run build_map.py first "
                         "(the Makefile data: target already orders them)")
    tree = json.loads(inputs["geo-tree"].read_text(encoding="utf-8"))
    meta = json.loads(inputs["map-meta"].read_text(encoding="utf-8"))
    bbox_src = json.loads(inputs["province-bbox"].read_text(encoding="utf-8"))
    boxes = bbox_src["boxes"]

    ids = [pid for a, b in meta["idRanges"] for pid in range(a, b + 1)]
    cls_of = {pid: meta["classNames"][c] for pid, c in zip(ids, meta["classes"])}
    geo = Geo(tree)

    # ---- resolve ---------------------------------------------------------
    dangling = defaultdict(list)
    resolved_cache = {}
    TIER_FIELD = [("provinces", None), ("counties", "county"), ("duchies", "duchy"),
                  ("kingdoms", "kingdom"), ("empires", "empire")]

    def resolve(key, stack=()):
        """The province ids a region covers, following sub-regions."""
        if key in resolved_cache:
            return resolved_cache[key]
        if key in stack:
            # No cycles exist today (the file header requires a sub-region to
            # be declared before its parent), but a patch that reorders the
            # file would loop forever without this.
            print(f"⚠ region cycle: {' → '.join(stack)} → {key} — cut here")
            return set()
        provinces = set()
        rec = regions[key]
        for field, tier in TIER_FIELD:
            for ref in rec.get(field, []):
                if tier is None:
                    if ref in cls_of:
                        provinces.add(ref)
                    else:
                        dangling[field].append((key, ref))
                    continue
                got = geo.provinces_of(tier, ref)
                if got is None:
                    dangling[field].append((key, ref))
                else:
                    provinces.update(got)
        for h in rec.get("hegemonies", []):
            # Documented in the file header, used by nothing today; a
            # hegemony's de jure kingdoms are not part of geo-tree.json.
            dangling["hegemonies"].append((key, h))
        for sub in rec.get("regions", []):
            if sub not in regions:
                dangling["regions"].append((key, sub))
                continue
            provinces |= resolve(sub, stack + (key,))
        resolved_cache[key] = provinces
        return provinces

    parents = defaultdict(list)
    for key, rec in regions.items():
        for sub in rec.get("regions", []):
            if sub in regions:
                parents[sub].append(key)

    usage = scan_usage(list(regions))

    out = []
    empty = []
    for key in order:
        rec = regions[key]
        provinces = resolve(key)
        counties, duchies, kingdoms = geo.touched(provinces)
        if not provinces:
            empty.append(key)
        by_class = Counter(cls_of.get(p, "unused") for p in provinces)
        px = [boxes[str(p)] for p in provinces if str(p) in boxes]
        bbox = [min(b[0] for b in px), min(b[1] for b in px),
                max(b[2] for b in px), max(b[3] for b in px)] if px else None

        loc_name = ck3.loc(key)
        used = {cat: sorted(files) for cat, files in sorted(usage.get(key, {}).items())}

        entry = {
            "id": key,
            "slug": slug_of(key),
            "file": rec["file"],
            "family": fams[key],
            "name": ck3.render_text(loc_name) if loc_name else pretty_key(key),
            "localized": bool(loc_name),
            "declared": {f: rec[f] for f in DECLARED if f in rec},
            "resolved": {
                "provinces": len(provinces),
                "land": by_class.get("land", 0),
                "sea": by_class.get("sea", 0),
                "other": sum(n for c, n in by_class.items() if c not in ("land", "sea")),
                "byClass": dict(sorted(by_class.items())),
                "counties": len(counties),
                "duchies": len(duchies),
                "kingdoms": len(kingdoms),
                "drawn": sum(1 for p in provinces if str(p) in boxes),
            },
            "parents": sorted(parents.get(key, [])),
            "usedBy": used,
            "usedByCount": sum(len(v) for v in used.values()),
        }
        if bbox:
            entry["bbox"] = bbox
        for flag in FLAGS:
            if rec.get(flag):
                entry[flag] = True
        if rec.get("color"):
            entry["color"] = rec["color"]
        if rec.get("generate_modifiers"):
            entry["modifiers"] = [{
                "key": f"{key}_{base}",
                "base": base,
                # The engine generates the key; the phrasing is the base
                # modifier's own, since no MOD_ loc exists per region and the
                # magnitude belongs to whatever applies it.
                "name": ck3.modifier_name(base),
            } for base in GENERATED_MODIFIERS]
        out.append(entry)

    slugs = Counter(r["slug"] for r in out)
    clash = [s for s, n in slugs.items() if n > 1]
    if clash:
        raise SystemExit(f"✗ region slugs collide: {clash}")
    if empty:
        raise SystemExit(f"✗ {len(empty)} regions resolve to no provinces: {empty[:8]}")
    for kind, items in sorted(dangling.items()):
        print(f"⚠ {len(items)} dangling {kind} reference(s): {items[:5]}")

    no_refs = [r["id"] for r in out if not r["usedBy"]]
    referenced = len(out) - len(no_refs)
    print(f"  cross-references: {referenced} regions referenced in script, "
          f"{len(no_refs)} with none")
    print(f"  names: {sum(1 for r in out if r['localized'])} localized, "
          f"{sum(1 for r in out if not r['localized'])} internal keys only")

    # What the map needs in the browser: the declared membership (it resolves
    # against geo-tree.json there) plus enough to label and zoom. usedBy and
    # the file lists stay server-side — they are the bulk of regions.json and
    # the canvas never reads them.
    ck3.write_public_json("map/regions-membership.json", [
        {
            "i": r["id"],
            # only the three keys containing `&` need a separate route slug
            **({"s": r["slug"]} if r["slug"] != r["id"] else {}),
            "n": r["name"],
            "f": r["family"],
            **({"L": 1} if r["localized"] else {}),
            **({"b": r["bbox"]} if r.get("bbox") else {}),
            "c": r["resolved"]["provinces"],
            **{short: r["declared"][field]
               for field, short in (("kingdoms", "k"), ("duchies", "d"),
                                    ("counties", "y"), ("provinces", "p"),
                                    ("regions", "r"), ("empires", "e"),
                                    ("hegemonies", "h"))
               if field in r["declared"]},
        } for r in out
    ], compact=True)

    ck3.write_json("regions.json", {
        "regions": out,
        "families": [f for f in FAMILY_ORDER if fam_counts[f]],
        "counts": {
            "regions": len(out),
            "localized": sum(1 for r in out if r["localized"]),
            "referenced": referenced,
            "unreferenced": len(no_refs),
            "files": {f.name: sum(1 for r in out if r["file"] == f.name) for f in FILES},
            "byFamily": {f: fam_counts[f] for f in FAMILY_ORDER if fam_counts[f]},
        },
        "raster": {"width": meta["width"], "height": meta["height"]},
    })


if __name__ == "__main__":
    main()
