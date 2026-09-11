#!/usr/bin/env python3
"""Build public/map/* — the province-index raster and the lookup tables the
Regions page paints through.

The game ships one authoritative picture of the world: map_data/provinces.png,
9216x4608, every pixel coloured with its province's RGB from definition.csv.
We re-encode that as a *province index* per pixel and downscale it, so the
browser can decode it once into a Uint16Array and treat the map as data:
palette swaps to recolour, an O(1) array lookup to hit-test the cursor.

Emitted:
  provinces-index.png   R = idx & 255, G = idx >> 8, B = 0. No gamma/ICC —
                        it is data, not a picture.
  map-meta.json         raster geometry, dense index -> province id, class
  geo-tree.json         county/duchy/kingdom/empire de jure tree + colours
  provinces-meta.json   columnar per-province name / county / terrain

Gotcha the build guards: definition.csv row 0 (`0;0;0;0;x;x;`) and province
12946 both claim RGB (0,0,0). Black is the null province; 12946 is undrawable.
A naive colour->id dict hands every black pixel on the map to 12946.
"""

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

MAP = ck3.REF / "game" / "map_data"
OUT = ck3.ROOT / "public" / "map"

SCALE = 3  # 9216x4608 -> 3072x1536; see PLAN-MAPS downscale test

# default.map's province-class keys, in the order they are applied. A barony
# beats all of them (a province with a holding is land, whatever else says).
CLASS_KEYS = [
    ("sea_zones", "sea"),
    ("river_provinces", "river"),
    ("lakes", "lake"),
    ("impassable_seas", "impassable"),
    ("impassable_mountains", "impassable"),
]
CLASS_ORDER = ["land", "sea", "river", "lake", "impassable", "wasteland", "unused"]

# Pillow refuses images this large by default (it is a decompression-bomb
# guard); ours is a 42 Mpx game asset we control.
Image.MAX_IMAGE_PIXELS = None


# ---------------------------------------------------------------------------
# definition.csv
# ---------------------------------------------------------------------------

def load_definitions():
    """province id -> (r, g, b, internal map name). Drops the null row 0."""
    defs = {}
    with (MAP / "definition.csv").open(encoding="utf-8-sig", errors="replace") as fh:
        for row in csv.reader(fh, delimiter=";"):
            if len(row) < 5 or not row[0].strip().isdigit():
                continue  # header noise and the 883 commented-out rows
            pid = int(row[0])
            if pid == 0:
                continue  # the null province: RGB (0,0,0) means "no province"
            defs[pid] = (int(row[1]), int(row[2]), int(row[3]), row[4].strip())
    return defs


# ---------------------------------------------------------------------------
# default.map ranges
# ---------------------------------------------------------------------------

_RANGE_RE = re.compile(r"^\s*(\w+)\s*=\s*(RANGE|LIST)\s*\{([^}]*)\}", re.M)


def load_default_map():
    """Every RANGE/LIST key in default.map -> set of province ids."""
    text = (MAP / "default.map").read_text(encoding="utf-8-sig", errors="replace")
    text = re.sub(r"#[^\n]*", "", text)  # comments carry ids in their prose
    out = {}
    for m in _RANGE_RE.finditer(text):
        key, kind, body = m.group(1), m.group(2), m.group(3)
        nums = [int(x) for x in re.findall(r"\d+", body)]
        bucket = out.setdefault(key, set())
        if kind == "RANGE":
            if len(nums) != 2:
                raise SystemExit(f"✗ default.map {key} RANGE with {len(nums)} bounds: {nums}")
            bucket.update(range(nums[0], nums[1] + 1))
        else:
            bucket.update(nums)
    return out


def load_wasteland_ids():
    """The WASTELAND block of common/province_terrain/01_province_properties.txt.

    default.map lumps wasteland in with impassable_mountains; the properties
    file is where the game itself separates the two, by file section. Same
    provenance as building categories (CLAUDE.md): the game's own grouping.
    """
    path = ck3.COMMON / "province_terrain" / "01_province_properties.txt"
    ids, inside = set(), False
    head = re.compile(r"^#\s*([A-Z][A-Z ]+)\s*$")
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        m = head.match(line.strip())
        if m:
            inside = m.group(1).strip() == "WASTELAND"
            continue
        if inside:
            m = re.match(r"^\s*(\d+)\s*=\s*\{", line)
            if m:
                ids.add(int(m.group(1)))
    return ids


# ---------------------------------------------------------------------------
# landed_titles -> de jure tree
# ---------------------------------------------------------------------------

def color_hex(v):
    """rgb {…} / hsv {…} / bare triple -> #rrggbb. Same rules as build_titles."""
    if isinstance(v, Tagged):
        if v.tag == "hsv":
            import colorsys
            f = [x for x in v.block.values() if isinstance(x, (int, float))]
            if len(f) < 3:
                return None
            r, g, b = colorsys.hsv_to_rgb(f[0], f[1], f[2])
            return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
        v = v.block
    vals = [x for x in v.values() if isinstance(x, (int, float))] if isinstance(v, Block) else []
    if len(vals) < 3:
        return None
    if all(isinstance(x, float) and x <= 1.0 for x in vals[:3]):
        vals = [x * 255 for x in vals]
    return "#%02x%02x%02x" % tuple(int(max(0, min(255, x))) for x in vals[:3])


def load_geo_tree():
    """The de jure hierarchy, as the four levels the regions page needs.

    Barony `province = N` is the only link from a title to a map pixel.
    """
    tree = {"county": {}, "duchy": {}, "kingdom": {}, "empire": {}}
    TIER = {"e_": "empire", "k_": "kingdom", "d_": "duchy", "c_": "county"}

    def node(tier, key, blk, parent):
        # walk() may already have stashed the children/provinces here, so fill
        # the fields in rather than setdefault-ing a whole record over it.
        rec = tree[tier].setdefault(key, {})
        rec["name"] = ck3.render_text(ck3.loc(key) or key)
        color = color_hex(blk.get("color"))
        if color:
            rec["color"] = color
        if parent:
            rec["parent"] = parent
        return rec

    def walk(blk, key=None, tier=None):
        """Returns the province ids beneath this block."""
        provinces, children = [], []
        for k, _op, v in blk:
            if not isinstance(v, (Block, Tagged)):
                continue
            body = v.block if isinstance(v, Tagged) else v
            if not isinstance(k, str):
                continue
            if k.startswith("b_"):
                pid = body.get("province")
                if isinstance(pid, int):
                    provinces.append(pid)
                    baronies[pid] = k
                continue
            child_tier = TIER.get(k[:2])
            if child_tier:
                sub = walk(body, k, child_tier)
                node(child_tier, k, body, key)
                children.append(k)
                provinces.extend(sub)
            elif key is None:
                provinces.extend(walk(body)[0])  # a wrapper block, not a title
        if tier == "county":
            tree["county"].setdefault(key, {})["provinces"] = sorted(provinces)
        elif tier == "duchy":
            tree["duchy"].setdefault(key, {})["counties"] = children
        elif tier == "kingdom":
            tree["kingdom"].setdefault(key, {})["duchies"] = children
        elif tier == "empire":
            tree["empire"].setdefault(key, {})["kingdoms"] = children
        return provinces, children

    baronies = {}
    for f in sorted((ck3.COMMON / "landed_titles").glob("*.txt")):
        if f.name.startswith("_"):
            continue
        blk = ck3.parse_file(f)
        for key, _op, v in blk:
            if not (isinstance(key, str) and isinstance(v, Block)):
                continue
            tier = TIER.get(key[:2])
            if tier:
                walk(v, key, tier)
                node(tier, key, v, None)
            elif key.startswith("h_"):
                # hegemonies (All Under Heaven) hold kingdoms directly; the
                # regions files never reference them, but their subtree does
                # contain baronies, so walk it for the province links.
                walk(v, key, None)
    return tree, baronies


# ---------------------------------------------------------------------------
# terrain
# ---------------------------------------------------------------------------

def load_terrain():
    """province id -> terrain key, plus the game's own default_* fallbacks."""
    text = (ck3.COMMON / "province_terrain" / "00_province_terrain.txt").read_text(
        encoding="utf-8-sig", errors="replace")
    text = re.sub(r"#[^\n]*", "", text)
    per = {int(m.group(1)): m.group(2)
           for m in re.finditer(r"^\s*(\d+)\s*=\s*(\w+)", text, re.M)}
    defaults = dict(re.findall(r"^\s*(default_\w+)\s*=\s*(\w+)", text, re.M))
    return per, defaults


# ---------------------------------------------------------------------------
# raster
# ---------------------------------------------------------------------------

def id_ranges(ids):
    """[1,2,3,7,8] -> [[1,3],[7,8]] — the dense-index table, run-length coded."""
    out = []
    for pid in ids:
        if out and pid == out[-1][1] + 1:
            out[-1][1] = pid
        else:
            out.append([pid, pid])
    return out


def mode_downscale(idx, factor):
    """Most-common province in each factor x factor block.

    Averaging indices would invent provinces; nearest-neighbour drops thin
    coastal ones more often. Mode keeps whichever province actually owns the
    block. Ties resolve to the lowest index (sorted, first-longest-run wins),
    which keeps the output byte-identical across runs.
    """
    h, w = idx.shape
    h2, w2 = h // factor, w // factor
    blocks = (idx[:h2 * factor, :w2 * factor]
              .reshape(h2, factor, w2, factor)
              .transpose(0, 2, 1, 3)
              .reshape(h2, w2, factor * factor))
    s = np.sort(blocks, axis=-1)
    n = s.shape[-1]
    ar = np.arange(n, dtype=np.int16)
    changed = np.empty(s.shape, dtype=bool)
    changed[..., 0] = True
    np.not_equal(s[..., 1:], s[..., :-1], out=changed[..., 1:])
    start = np.maximum.accumulate(np.where(changed, ar, np.int16(0)), axis=-1)
    ends = np.empty(s.shape, dtype=bool)
    ends[..., :-1] = changed[..., 1:]
    ends[..., -1] = True
    runlen = np.where(ends, ar - start + 1, np.int16(0))
    best = np.argmax(runlen, axis=-1)[..., None]
    return np.take_along_axis(s, best, axis=-1)[..., 0]


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    defs = load_definitions()
    ids = sorted(defs)
    dense = {pid: i + 1 for i, pid in enumerate(ids)}  # 0 = no province
    print(f"  definition.csv — {len(ids)} provinces (row 0 dropped as the null province)")

    # colour -> dense index. (0,0,0) is deliberately absent: it is the null
    # province, and province 12946 shares it, so black must stay index 0.
    lut = np.zeros(1 << 24, dtype=np.uint16)
    shared_black = [pid for pid, (r, g, b, _n) in defs.items() if (r, g, b) == (0, 0, 0)]
    collisions = Counter((r, g, b) for r, g, b, _n in defs.values())
    for pid, (r, g, b, _name) in defs.items():
        if (r, g, b) == (0, 0, 0):
            continue
        packed = (r << 16) | (g << 8) | b
        if lut[packed]:
            raise SystemExit(f"✗ RGB collision: {ids[lut[packed] - 1]} and {pid} share "
                             f"({r},{g},{b}) — the raster cannot distinguish them")
        lut[packed] = dense[pid]
    dup = [c for c, n in collisions.items() if n > 1]
    print(f"  colour table — {len(ids) - len(shared_black)} distinct colours; "
          f"black shared by {sorted(shared_black)} → treated as the null province")
    if dup:
        print(f"⚠ shared colours among drawable provinces: {dup}")

    src = np.asarray(Image.open(MAP / "provinces.png").convert("RGB"))
    sh, sw = src.shape[:2]
    packed = (src[..., 0].astype(np.uint32) << 16) | \
             (src[..., 1].astype(np.uint32) << 8) | src[..., 2].astype(np.uint32)
    full = lut[packed]
    del packed, src
    print(f"  provinces.png — {sw}x{sh}")

    unknown = int((full == 0).sum())
    drawn_full = np.unique(full)
    drawn_full = drawn_full[drawn_full > 0]
    print(f"  drawn: {len(drawn_full)} provinces; {len(ids) - len(drawn_full)} defined but "
          f"never painted; {unknown} pixels have no province")

    small = mode_downscale(full, SCALE)
    drawn_small = set(np.unique(small).tolist()) - {0}
    lost = [i for i in drawn_full.tolist() if i not in drawn_small]

    # Force-stamp a pixel for anything the downscale swallowed, so every drawn
    # province stays hoverable. Stamp the drawn pixel nearest the centroid —
    # a computed centroid can fall outside a crescent-shaped province.
    for i in lost:
        ys, xs = np.nonzero(full == i)
        cy, cx = ys.mean(), xs.mean()
        k = int(np.argmin((ys - cy) ** 2 + (xs - cx) ** 2))
        ty, tx = int(ys[k]) // SCALE, int(xs[k]) // SCALE
        evicted = int(small[ty, tx])
        small[ty, tx] = i
        pid = ids[i - 1]
        print(f"  force-stamped province {pid} at ({tx},{ty}) — "
              f"{len(ys)} source pixels, lost to the ÷{SCALE} downscale"
              + (f", over {ids[evicted - 1]}" if evicted else ""))

    after = set(np.unique(small).tolist()) - {0}
    still_lost = [ids[i - 1] for i in drawn_full.tolist() if i not in after]
    if still_lost:
        raise SystemExit(f"✗ stamping evicted provinces that had survived: {still_lost}")
    print(f"  raster ÷{SCALE} → {small.shape[1]}x{small.shape[0]}, "
          f"{len(after)} provinces present, {len(lost)} stamped back in")

    h, w = small.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    rgb[..., 0] = (small & 255).astype(np.uint8)
    rgb[..., 1] = (small >> 8).astype(np.uint8)
    png = OUT / "provinces-index.png"
    # Fromarray on a bare ndarray carries no info dict, so PIL writes neither
    # gAMA nor iCCP — a colour-managed decode would resample our indices.
    Image.fromarray(rgb, "RGB").save(png, optimize=True)
    chunks = set(re.findall(rb"[a-zA-Z]{4}", png.read_bytes()[:2048]))
    for bad in (b"gAMA", b"iCCP", b"sRGB"):
        if bad in chunks:
            raise SystemExit(f"✗ {png.name} carries a {bad.decode()} chunk — indices "
                             "would be colour-managed on decode")
    print(f"✓ wrote public/map/{png.name} — {w}x{h}, {png.stat().st_size / 1024:.0f} KB")

    # ---- classes ---------------------------------------------------------
    ranges = load_default_map()
    tree, baronies = load_geo_tree()
    wasteland = load_wasteland_ids()

    cls = {}
    for key, name in CLASS_KEYS:
        for pid in ranges.get(key, ()):
            if pid in defs:
                cls.setdefault(pid, "wasteland" if (name == "impassable" and pid in wasteland)
                               else name)
    for pid in baronies:  # a holding outranks every default.map list
        cls[pid] = "land"
    for pid in ids:
        cls.setdefault(pid, "unused")
    counts = Counter(cls[pid] for pid in ids)
    print("  classes: " + ", ".join(f"{k} {counts[k]}" for k in CLASS_ORDER if counts[k]))

    missing_from_defs = {k: sorted(v - set(defs))[:5] for k, v in ranges.items()
                         if k in dict(CLASS_KEYS) and (v - set(defs))}
    if missing_from_defs:
        print(f"⚠ default.map lists ids with no definition.csv row: {missing_from_defs}")

    drawn_set = {ids[i - 1] for i in after}
    ck3.write_public_json("map/map-meta.json", {
        "width": w, "height": h, "scale": SCALE,
        "sourceWidth": sw, "sourceHeight": sh,
        # dense index 1..N -> province id, run-length encoded. It happens to be
        # 1:1 today (definition.csv has no gaps); a patch could change that, so
        # the page expands this table rather than assuming.
        "idRanges": id_ranges(ids),
        "classNames": CLASS_ORDER,
        "classes": [CLASS_ORDER.index(cls[pid]) for pid in ids],
        "counts": {k: counts[k] for k in CLASS_ORDER if counts[k]},
        "notDrawn": [pid for pid in ids if pid not in drawn_set],
        "stamped": [ids[i - 1] for i in lost],
        "undrawable": sorted(shared_black),
    }, compact=True)

    # ---- geo tree --------------------------------------------------------
    missing = {t: [k for k, r in tier.items() if not r.get("name")]
               for t, tier in tree.items()}
    missing = {t: v for t, v in missing.items() if v}
    if missing:
        print(f"⚠ de jure titles reached without a definition block: "
              f"{ {t: v[:4] for t, v in missing.items()} }")
    sizes = {k: len(v) for k, v in tree.items()}
    print(f"  de jure tree: {sizes}, {len(baronies)} baronies")
    # Shipped shape: n = name, c = colour, ch = child titles, p = province ids
    # (counties only). Parent links are left out — every tier lists its
    # children, so the page inverts them once on load instead of paying for
    # 6,068 redundant strings.
    ck3.write_public_json("map/geo-tree.json", {
        tier: {key: {
            "n": rec.get("name", key),
            # County colours are 66 KB the page never paints: the base layers
            # colour by kingdom, and borders are drawn from the index array.
            **({"c": rec["color"]} if rec.get("color") and tier != "county" else {}),
            **({"ch": rec[child]} if rec.get(child) else {}),
            **({"p": rec["provinces"]} if rec.get("provinces") else {}),
        } for key, rec in sorted(titles.items())}
        for tier, titles, child in (
            ("county", tree["county"], "counties"),
            ("duchy", tree["duchy"], "counties"),
            ("kingdom", tree["kingdom"], "duchies"),
            ("empire", tree["empire"], "kingdoms"),
        )
    }, compact=True)

    # ---- title index (build-time, for server-rendered links) -------------
    # /titles/ only has a page per empire (and hegemony); kingdoms, duchies
    # and counties are anchors on their empire's page. Every province-bearing
    # title has an empire ancestor — the parentless ones are all titular
    # noble-family titles with no land — so `page` is null only for those.
    page_of = {}
    for eid, erec in tree["empire"].items():
        page_of[eid] = eid
        for kid in erec.get("kingdoms", []):
            page_of[kid] = eid
            for did in tree["kingdom"].get(kid, {}).get("duchies", []):
                page_of[did] = eid
                for cid in tree["duchy"].get(did, {}).get("counties", []):
                    page_of[cid] = eid
    index = {}
    for tier in ("empire", "kingdom", "duchy", "county"):
        for key, rec in tree[tier].items():
            index[key] = {"name": rec.get("name", key), "tier": tier,
                          **({"page": page_of[key]} if key in page_of else {})}
    ck3.write_json("title-index.json", index)

    # ---- per-province meta ----------------------------------------------
    per_terrain, terr_defaults = load_terrain()
    terr_names = sorted({*per_terrain.values(), *terr_defaults.values()})
    terr_index = {t: i for i, t in enumerate(terr_names)}

    def terrain_for(pid):
        t = per_terrain.get(pid)
        if t:
            return terr_index[t], False
        # The same file states the fallbacks the game applies, so a land
        # province with no row of its own gets default_land. Nothing else is
        # derivable: a sea zone could be sea or coastal_sea and no file says
        # which, so those stay unknown rather than guessed.
        if cls[pid] == "land":
            return terr_index[terr_defaults["default_land"]], True
        return -1, True

    names, map_names, terrains, defaulted = [], [], [], []
    for i, pid in enumerate(ids, start=1):
        raw = defs[pid][3]
        if pid in baronies:
            name = ck3.render_text(ck3.loc(baronies[pid]) or baronies[pid])
        else:
            # Sea zones, lakes and major rivers carry their localized name
            # under their definition.csv name (map_items_l_english.yml).
            loc_name = ck3.loc(raw) if raw and raw != "x" else None
            name = ck3.render_text(loc_name) if loc_name else ""
        names.append(name)
        # Only worth shipping where there is no localized name to show; the
        # page labels it as the internal map name, never as an in-game one.
        map_names.append("" if name or raw == "x" else raw)
        ti, d = terrain_for(pid)
        terrains.append(ti)
        if d:
            defaulted.append(i)

    named = sum(1 for n in names if n)
    print(f"  names: {named} localized, {sum(1 for m in map_names if m)} internal-key only, "
          f"{len(ids) - named - sum(1 for m in map_names if m)} unnamed")
    print(f"  terrain: {len(per_terrain)} provinces assigned explicitly, "
          f"{sum(1 for pid in ids if pid not in per_terrain and cls[pid] == 'land')} land "
          f"provinces fall back to default_land ({terr_defaults['default_land']})")

    # The terrain layer paints the game's own terrain colours, not a palette
    # of our choosing (common/terrain_types/*.txt `color = hsv { … }`).
    terr_colors = {}
    for _path, key, blk in ck3.parse_dir(ck3.COMMON / "terrain_types"):
        body = blk.block if isinstance(blk, Tagged) else blk
        c = color_hex(body.get("color"))
        if c:
            terr_colors[key] = c
    missing_color = [t for t in terr_names if t not in terr_colors]
    if missing_color:
        print(f"⚠ terrain types with no colour in terrain_types/: {missing_color}")

    ck3.write_public_json("map/provinces-meta.json", {
        "terrainColors": [terr_colors.get(t, "") for t in terr_names],
        # localized terrain names; the keys stay alongside so the tooltip can
        # show what the file actually says
        "terrainLabels": [ck3.render_text(ck3.loc(t) or t.replace("_", " "))
                          for t in terr_names],
        "names": names,
        "mapNames": map_names,
        "terrain": terrains,
        "terrainNames": terr_names,
        # dense indices whose terrain is the game's default rather than an
        # explicit row; -1 terrain means no rule covers it at all.
        "terrainDefaulted": defaulted,
    }, compact=True)

    # ---- province bounding boxes (build-time only) -----------------------
    # build_regions.py unions these into a per-region bbox for zoom-to-region.
    # Kept out of public/ — 13k boxes would cost more than the raster.
    flat = small.ravel()
    order = np.argsort(flat, kind="stable")
    sv = flat[order]
    sx = (order % w).astype(np.int32)
    sy = (order // w).astype(np.int32)
    bounds = np.searchsorted(sv, np.arange(len(ids) + 2))
    boxes = {}
    for i in range(1, len(ids) + 1):
        a, b = bounds[i], bounds[i + 1]
        if a == b:
            continue
        boxes[str(ids[i - 1])] = [int(sx[a:b].min()), int(sy[a:b].min()),
                                  int(sx[a:b].max()), int(sy[a:b].max())]
    cache = ck3.ROOT / ".cache" / "province-bbox.json"
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps({"width": w, "height": h, "boxes": boxes},
                                sort_keys=True, separators=(",", ":")), encoding="utf-8")
    print(f"  province bboxes → .cache/{cache.name} ({len(boxes)} provinces)")

    total = sum((OUT / f).stat().st_size for f in
                ("provinces-index.png", "map-meta.json", "geo-tree.json",
                 "provinces-meta.json"))
    print(f"  map payload total: {total / 1024:.0f} KB")


if __name__ == "__main__":
    main()
