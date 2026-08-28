// Precompute troop-type tier lists. For each "basis" (how you equalise the two sides —
// equal regiments, equal recruitment gold, equal monthly maintenance) every unit fields a
// mono-type army and fights every other unit's mono-type army, on the average CK3 map
// (province-weighted terrain, both attack/defend roles). A unit's score is its mean win
// fraction against the field; units are then bucketed S/A/B/C/D. "Overall" averages the
// three bases. Emits src/data/tiers.json.
//
// Run (bundled by esbuild, see `make data`):
//   npx esbuild scripts/build_tiers.ts --bundle --platform=node --format=esm | node --input-type=module
//
// Anchored on game files: stack / buyCost / highMaintenance come straight from maa.json
// (which is built from common/men_at_arms_types). Caps are chosen from the cost spread.

import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { mapWeightedWinFraction } from '../src/lib/combat/run.ts';
import maa from '../src/data/maa.json' with { type: 'json' };
import details from '../src/data/unit_details.json' with { type: 'json' };
import type { ArmySpec, BattleSetup } from '../src/lib/combat/types.ts';

const ERAS = ['culture_era_tribal', 'culture_era_early_medieval', 'culture_era_high_medieval', 'culture_era_late_medieval'];
const ERA_RANK = Object.fromEntries(ERAS.map((e, i) => [e, i]));
const RECRUIT_CAP = 1000; // gold — fields 2–24 regiments across the roster
const MAINT_CAP = 15; // gold/month — fields 4–37 regiments
const EQUAL_REGIMENTS = 10;

type Unit = { id: string; name: string; type: string; stack: number; buy: number; maint: number; unlockEra: string };

const allUnits: Unit[] = (maa as any[])
  .filter((m) => !m.specialRecruitOnly && !m.specialAccess && m.maxRegiments !== 1 && m.type !== 'siege_weapon')
  .map((m) => ({
    id: m.id, name: m.name, type: m.type, stack: m.stack ?? 100,
    buy: typeof m.buyCost?.gold === 'number' ? m.buyCost.gold : NaN,
    maint: typeof m.highMaintenance?.gold === 'number' ? m.highMaintenance.gold : NaN,
    unlockEra: (details as any)[m.id]?.unlockEra ?? 'culture_era_tribal',
  }))
  .filter((u) => Number.isFinite(u.buy) && Number.isFinite(u.maint));

const BASES = {
  regiments: (u: Unit) => EQUAL_REGIMENTS,
  recruit: (u: Unit) => Math.max(1, Math.floor(RECRUIT_CAP / u.buy)),
  maintenance: (u: Unit) => Math.max(1, Math.floor(MAINT_CAP / u.maint)),
} as const;
type BasisKey = keyof typeof BASES;

const army = (u: Unit, regs: number, era: string): ArmySpec =>
  ({ regiments: [{ typeId: u.id, men: regs * u.stack }], levies: 0, knights: [], era });

function scoresFor(units: Unit[], basis: BasisKey, era: string) {
  const regCount = new Map(units.map((u) => [u.id, BASES[basis](u)]));
  const score = new Map<string, number>();
  for (const a of units) {
    let sum = 0, n = 0;
    for (const b of units) {
      if (a.id === b.id) continue;
      const setup: BattleSetup = { attacker: army(a, regCount.get(a.id)!, era), defender: army(b, regCount.get(b.id)!, era), terrainId: 'plains' };
      sum += mapWeightedWinFraction(setup); // average-terrain, role-blended
      n++;
    }
    score.set(a.id, n ? sum / n : 0);
  }
  return { score, regCount };
}

// Tiers are assigned by rank within each list (a standard tier-list pyramid), since the
// win-vs-field distribution is bimodal; the raw win% travels alongside so absolute strength
// stays visible. Cumulative share cutoffs: S 12% / A 32% / B 62% / C 85% / D rest.
const TIER_CUTS: Array<['S' | 'A' | 'B' | 'C' | 'D', number]> = [
  ['S', 0.12], ['A', 0.32], ['B', 0.62], ['C', 0.85], ['D', 1.01],
];
function tierByRank(rank0: number, count: number): 'S' | 'A' | 'B' | 'C' | 'D' {
  const q = (rank0 + 0.5) / count;
  for (const [t, cut] of TIER_CUTS) if (q < cut) return t;
  return 'D';
}

function listFor(units: Unit[], scoreMap: Map<string, number>, regCount?: Map<string, number>) {
  const sorted = units
    .map((u) => ({
      id: u.id, name: u.name, type: u.type, stack: u.stack, buy: u.buy, maint: u.maint,
      regiments: regCount ? regCount.get(u.id)! : undefined,
      score: Math.round(scoreMap.get(u.id)! * 1000) / 1000,
      winPct: Math.round(scoreMap.get(u.id)! * 100),
    }))
    .sort((a, b) => b.score - a.score);
  return sorted.map((u, i) => ({ ...u, tier: tierByRank(i, sorted.length) }));
}

const t0 = Date.now();
// One tier list per era: only units available by that era, fought at that era's stats.
const byEra: Record<string, any> = {};
for (const era of ERAS) {
  const units = allUnits.filter((u) => ERA_RANK[u.unlockEra] <= ERA_RANK[era]);
  process.stderr.write(`era ${era} (${units.length} units)…\n`);
  const perBasis: Record<string, { score: Map<string, number>; regCount: Map<string, number> }> = {};
  for (const basis of Object.keys(BASES) as BasisKey[]) perBasis[basis] = scoresFor(units, basis, era);
  const overall = new Map<string, number>();
  for (const u of units) {
    const s = (Object.keys(BASES) as BasisKey[]).map((k) => perBasis[k].score.get(u.id)!);
    overall.set(u.id, s.reduce((x, y) => x + y, 0) / s.length);
  }
  byEra[era] = {
    units: units.length,
    overall: listFor(units, overall),
    regiments: listFor(units, perBasis.regiments.score, perBasis.regiments.regCount),
    recruit: listFor(units, perBasis.recruit.score, perBasis.recruit.regCount),
    maintenance: listFor(units, perBasis.maintenance.score, perBasis.maintenance.regCount),
  };
}

const data = {
  meta: {
    eras: ERAS, recruitCap: RECRUIT_CAP, maintCap: MAINT_CAP, equalRegiments: EQUAL_REGIMENTS,
    metric: 'mean win fraction vs the era\'s roster, average-terrain (province-weighted) and 50/50 attack/defend',
    provenance: 'engine:src/lib/combat (decompiled main phase) · stack/cost/era from maa.json + combat_sim.json · unlock era from unit_details.json',
  },
  byEra,
};

const outDir = join(process.cwd(), 'src', 'data');
writeFileSync(join(outDir, 'tiers.json'), JSON.stringify(data, null, 2) + '\n');
process.stderr.write(`✓ wrote src/data/tiers.json — ${ERAS.length} eras — ${((Date.now() - t0) / 1000).toFixed(1)}s\n`);
for (const era of ERAS) {
  const l = byEra[era].overall;
  process.stderr.write(`  ${era.replace('culture_era_', '').padEnd(14)} ${byEra[era].units}u · top: ${l[0].name} ${l[0].winPct}%\n`);
}
