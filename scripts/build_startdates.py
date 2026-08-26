#!/usr/bin/env python3
"""Build src/data/startdates.json — who holds what at each bookmark date.

For every landed title, resolve holder / liege / government at 867.1.1 and
1066.9.15 from game/history/titles/, then reconstruct realms by walking de
facto liege chains: a realm = a held title with no held liege above it. County
counts come from the same resolution over all c_ titles.
"""

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3
from ck3 import Block, Tagged

HIST = ck3.REF / "game" / "history"
DATES = ["867.1.1", "1066.9.15"]


def dtup(s):
    try:
        y, m, d = (int(x) for x in s.split("."))
        return (y, m, d)
    except Exception:
        return None


def resolve_at(entries, date):
    """entries: list of (datetuple, Block). Returns dict of latest values ≤ date."""
    state = {}
    for dt, blk in entries:
        if dt > date:
            continue
        for k, _op, v in blk:
            if k in ("holder", "liege", "government", "de_jure_liege"):
                state[k] = v
    return state


def load_title_history():
    titles = {}
    for f in sorted((HIST / "titles").glob("*.txt")):
        blk = ck3.parse_file(f)
        for key, _op, v in blk:
            if not (isinstance(key, str) and key[:2] in ("e_", "k_", "d_", "c_", "b_", "h_")):
                continue
            if not isinstance(v, Block):
                continue
            entries = []
            for k2, _o2, v2 in v:
                dt = dtup(k2) if isinstance(k2, str) else None
                if dt and isinstance(v2, Block):
                    entries.append((dt, v2))
            entries.sort(key=lambda e: e[0])
            titles.setdefault(key, []).extend(entries)
    return titles


FIELDS = ("name", "dynasty", "dynasty_house", "religion", "culture", "female")


def load_characters(needed, date):
    """Targeted: regex-slice the bodies of needed characters out of the 20MB
    of history, then properly parse just those and resolve static fields plus
    dated overrides ≤ date (direct children of dated blocks only — nested
    create_character effects must not leak, that bug shipped once)."""
    chars = {}
    id_re = re.compile(r"^([\w.]+)\s*=\s*\{", re.M)
    for f in sorted((HIST / "characters").glob("*.txt")):
        text = f.read_text(encoding="utf-8-sig", errors="replace")
        matches = list(id_re.finditer(text))
        for i, m in enumerate(matches):
            cid = m.group(1)
            if cid not in needed or cid in chars:
                continue
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[m.start():end]
            try:
                blk = ck3.Parser(body, f"{f.name}:{cid}").parse().get(cid)
            except Exception:
                continue
            if not isinstance(blk, Block):
                continue
            fields = {}
            dated = []
            for k, _op, v in blk:
                if k in FIELDS and not isinstance(v, (Block, Tagged)):
                    fields.setdefault(k, v)
                elif isinstance(k, str) and isinstance(v, Block):
                    dt = dtup(k)
                    if dt and dt <= date:
                        dated.append((dt, v))
            for _dt, v in sorted(dated, key=lambda e: e[0]):
                for k, _op, val in v:
                    if k in FIELDS and not isinstance(val, (Block, Tagged)):
                        fields[k] = val
            chars[cid] = {k: str(v) for k, v in fields.items()}
    return chars


def load_dynasties():
    dyn = {}
    for sub in ("dynasties", "dynasty_houses"):
        d = ck3.COMMON / sub
        if not d.exists():
            continue
        for _p, key, blk in ck3.parse_dir(d):
            if isinstance(blk, Block):
                nm = blk.get("name") or blk.get("prefix")
                if isinstance(nm, str):
                    dyn[str(key)] = ck3.render_text(ck3.loc(nm) or nm)
    return dyn


def title_meta():
    """id -> (name, color, tier) from the already-built titles.json."""
    import json
    meta = {}
    tj = json.loads((ck3.ROOT / "src/data/titles.json").read_text(encoding="utf-8"))

    def walk(n):
        meta[n["id"]] = (n["name"], n.get("color"), n["tier"])
        for c in n.get("children", []):
            walk(c)
    for r in tj["roots"]:
        walk(r)
    return meta


def main():
    titles = load_title_history()
    meta = title_meta()
    out = {"dates": DATES, "realms": {}}

    for date_s in DATES:
        date = dtup(date_s)
        state = {}
        for t, entries in titles.items():
            st = resolve_at(entries, date)
            holder = st.get("holder")
            if holder in (0, "0", None):
                continue
            state[t] = {"holder": str(holder), "liege": st.get("liege"),
                        "government": st.get("government")}

        def top_of(t, seen=None):
            seen = seen or set()
            if t in seen:
                return t
            seen.add(t)
            liege = state.get(t, {}).get("liege")
            if isinstance(liege, str) and liege in state and liege != t:
                return top_of(liege, seen)
            return t

        county_counts = Counter()
        for t in state:
            if t.startswith("c_"):
                county_counts[top_of(t)] += 1

        tops = {t for t in state if top_of(t) == t and not t.startswith("b_")}
        needed = {state[t]["holder"] for t in tops}
        chars = load_characters(needed, date)
        dyn = load_dynasties()

        realms = []
        for t in sorted(tops):
            nm, color, tier = meta.get(t, (t, None, t[:1]))
            ch = chars.get(state[t]["holder"], {})
            gov = state[t].get("government")
            realms.append({
                "title": t, "name": nm, "tier": tier, "color": color,
                "counties": county_counts.get(t, 0),
                "ruler": ck3.render_text(ck3.loc(ch.get("name", "")) or ch.get("name", "?")),
                "female": ch.get("female") == "yes",
                "dynasty": dyn.get(ch.get("dynasty_house") or ch.get("dynasty", ""), None),
                "culture": ck3.render_text(ck3.loc(ch.get("culture", "")) or (ch.get("culture") or "").title()),
                "faith": ck3.render_text(ck3.loc(ch.get("religion", "")) or (ch.get("religion") or "").title()),
                "government": (gov or "").replace("_government", "") or None,
            })
        realms.sort(key=lambda r: -r["counties"])
        out["realms"][date_s] = realms
        print(f"  {date_s}: {len(realms)} independent realms, "
              f"{sum(r['counties'] for r in realms)} held counties")

    ck3.write_json("startdates.json", out)


if __name__ == "__main__":
    main()
