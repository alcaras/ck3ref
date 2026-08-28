// Search for two-unit army compositions that beat single-type armies. For each basis
// (equal regiments / recruitment gold / upkeep gold) we take an archetype-diverse candidate
// pool, brute-force every pair at several split ratios, and score each mix by its win rate
// against the whole 78-unit single-type field — same metric as the tier list, so scores are
// directly comparable. No genetic algorithm needed: pruning the pool makes 2-unit exhaustive.
// Emits src/data/compositions.json.
//
// Heavy (~1-2 min): run on demand via `make compositions`, not every build.

import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { mapWeightedWinFraction } from '../src/lib/combat/run.ts';
import maa from '../src/data/maa.json' with { type: 'json' };
import tiers from '../src/data/tiers.json' with { type: 'json' };
import type { ArmySpec } from '../src/lib/combat/types.ts';

const ERA = 'culture_era_late_medieval';
const RECRUIT_CAP = 1000, MAINT_CAP = 15, EQ_REG = 10;

type U = { id: string; name: string; type: string; stack: number; buy: number; maint: number; dmg: number; tough: number };
const units: U[] = (maa as any[])
  .filter((m) => !m.specialRecruitOnly && !m.specialAccess && m.maxRegiments !== 1 && m.type !== 'siege_weapon')
  .map((m) => ({
    id: m.id, name: m.name, type: m.type, stack: m.stack ?? 100,
    buy: m.buyCost?.gold ?? NaN, maint: m.highMaintenance?.gold ?? NaN,
    dmg: m.stats?.damage ?? 0, tough: m.stats?.toughness ?? 0,
  }))
  .filter((u) => Number.isFinite(u.buy) && Number.isFinite(u.maint));
const byId = new Map(units.map((u) => [u.id, u]));

type BasisKey = 'regiments' | 'recruit' | 'maintenance';
// regiments a single-type army of `u` fields under a basis
function singleRegs(u: U, basis: BasisKey): number {
  if (basis === 'recruit') return Math.max(1, Math.floor(RECRUIT_CAP / u.buy));
  if (basis === 'maintenance') return Math.max(1, Math.floor(MAINT_CAP / u.maint));
  return EQ_REG;
}
const oneUnitArmy = (u: U, regs: number): ArmySpec => ({ regiments: [{ typeId: u.id, men: regs * u.stack }], levies: 0, knights: [], era: ERA });
const twoUnitArmy = (a: U, ra: number, b: U, rb: number): ArmySpec =>
  ({ regiments: [{ typeId: a.id, men: ra * a.stack }, { typeId: b.id, men: rb * b.stack }], levies: 0, knights: [], era: ERA });

// archetype-diverse candidate pool: top generalists + stat extremes + canonical counter units
const CANON = ['pikemen_unit', 'light_footmen', 'armored_horsemen', 'bowmen'];
const topOverall = (tiers as any).byEra[ERA].overall.slice(0, 10).map((r: any) => r.id);
const maxDmg = units.reduce((x, y) => (y.dmg > x.dmg ? y : x)).id;
const maxTough = units.reduce((x, y) => (y.tough > x.tough ? y : x)).id;
const candidates = [...new Set([...topOverall, maxDmg, maxTough, ...CANON])].filter((id) => byId.has(id));

// splits per basis
function splits(basis: BasisKey, a: U, b: U): Array<{ ra: number; rb: number; label: string; note: string }> {
  const out: Array<{ ra: number; rb: number; label: string; note: string }> = [];
  if (basis === 'regiments') {
    for (let k = 3; k <= 7; k++) out.push({ ra: k, rb: EQ_REG - k, label: `${k}:${EQ_REG - k}`, note: `${k}× + ${EQ_REG - k}×` });
  } else {
    const cap = basis === 'recruit' ? RECRUIT_CAP : MAINT_CAP;
    const cost = (u: U) => (basis === 'recruit' ? u.buy : u.maint);
    for (const pA of [0.3, 0.4, 0.5, 0.6, 0.7]) {
      const ra = Math.floor((pA * cap) / cost(a));
      const rb = Math.floor(((1 - pA) * cap) / cost(b));
      if (ra >= 1 && rb >= 1) out.push({ ra, rb, label: `${Math.round(pA * 100)}/${Math.round((1 - pA) * 100)}`, note: `${ra}× + ${rb}×` });
    }
  }
  return out;
}

// fitness: mean win fraction (avg terrain, both roles) vs every single-type army in the field
function fieldWin(army: ArmySpec, field: ArmySpec[]): number {
  let s = 0;
  for (const opp of field) s += mapWeightedWinFraction({ attacker: army, defender: opp, terrainId: 'plains' });
  return s / field.length;
}

const t0 = Date.now();
const result: any = { meta: {
  era: ERA, recruitCap: RECRUIT_CAP, maintCap: MAINT_CAP, equalRegiments: EQ_REG,
  candidates: candidates.map((id) => byId.get(id)!.name),
  metric: 'mean win fraction vs all 78 single-type armies, average-terrain (province-weighted) + 50/50 attack/defend',
  provenance: 'engine:src/lib/combat · stack/cost from maa.json · terrain weights from province_terrain',
}, lists: {} };

for (const basis of ['regiments', 'recruit', 'maintenance'] as BasisKey[]) {
  process.stderr.write(`basis ${basis}…\n`);
  const field = units.map((u) => oneUnitArmy(u, singleRegs(u, basis)));
  // best single (comparable baseline), scored vs the same field
  const singles = units.map((u) => ({ id: u.id, name: u.name, winPct: Math.round(fieldWin(oneUnitArmy(u, singleRegs(u, basis)), field) * 100) }))
    .sort((a, b) => b.winPct - a.winPct);

  const duos: any[] = [];
  for (let i = 0; i < candidates.length; i++) {
    for (let j = i + 1; j < candidates.length; j++) {
      const a = byId.get(candidates[i])!, b = byId.get(candidates[j])!;
      let best: any = null;
      for (const sp of splits(basis, a, b)) {
        const win = fieldWin(twoUnitArmy(a, sp.ra, b, sp.rb), field);
        if (!best || win > best.win) best = { win, ...sp };
      }
      // also try the mirror split order for gold bases (A-heavy vs B-heavy differ by cost)
      if (basis !== 'regiments') {
        for (const sp of splits(basis, b, a)) {
          const win = fieldWin(twoUnitArmy(b, sp.ra, a, sp.rb), field);
          if (win > best.win) best = { win, ra: sp.rb, rb: sp.ra, label: sp.label.split('/').reverse().join('/'), note: `${sp.rb}× + ${sp.ra}×` };
        }
      }
      duos.push({ a: a.name, b: b.name, aId: a.id, bId: b.id, split: best.label, mix: best.note, ra: best.ra, rb: best.rb, winPct: Math.round(best.win * 100), win: best.win });
    }
  }
  duos.sort((x, y) => y.win - x.win);
  result.lists[basis] = {
    bestSingle: singles[0],
    topSingles: singles.slice(0, 5),
    duos: duos.slice(0, 24).map(({ win, ...d }) => d),
    duosBeatingBest: duos.filter((d) => d.winPct > singles[0].winPct).length,
  };
  process.stderr.write(`  best single ${singles[0].name} ${singles[0].winPct}% · best duo ${duos[0].a}+${duos[0].b} ${duos[0].winPct}% (${duos[0].mix}) · ${result.lists[basis].duosBeatingBest} duos beat best single\n`);
}

writeFileSync(join(process.cwd(), 'src', 'data', 'compositions.json'), JSON.stringify(result, null, 2) + '\n');
process.stderr.write(`✓ wrote src/data/compositions.json — ${((Date.now() - t0) / 1000).toFixed(0)}s\n`);
