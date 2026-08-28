// Run helpers over the battle engine: a single expected-value battle, and a Monte Carlo
// batch that reports win odds and casualty distributions.

import { resolveBattle } from './battle';
import { makeRng } from './rng';
import { TERRAIN_WEIGHTS } from './constants';
import type { BattleSetup, BattleResult, Side } from './types';

export type McResult = {
  runs: number;
  winPct: Record<Side | 'draw', number>;
  attacker: { deadMean: number; deadP10: number; deadP90: number; survivorsMean: number };
  defender: { deadMean: number; deadP10: number; deadP90: number; survivorsMean: number };
  daysMean: number;
  wipePct: number;
  /** one representative battle (median attacker-deaths run) for a timeline/detail view */
  sample: BattleResult;
};

function pct(sorted: number[], p: number): number {
  if (!sorted.length) return 0;
  const i = Math.min(sorted.length - 1, Math.max(0, Math.round((p / 100) * (sorted.length - 1))));
  return sorted[i];
}

/** Deterministic expected-value battle (rolls taken at their mean). */
export function expected(setup: BattleSetup): BattleResult {
  return resolveBattle(setup, { mode: 'ev' });
}

export type TerrainOutcome = {
  terrainId: string;
  weight: number; // province count
  weightPct: number; // share of land provinces
  // "A" = the setup's attacker (the left/your army). We run each terrain both ways so
  // the terrain defender-advantage lands on each side in turn.
  aWinAsAttacker: number; // A wins when A is the attacker (enemy defends, gets terrain)
  aWinAsDefender: number; // A wins when A is the defender (A gets terrain), enemy attacks
  aWinBlended: number; // 0.5 * (above two) — role-neutral
};

export type MapWeightedResult = {
  overall: {
    // role-blended (50% attacking / 50% defending) and terrain-weighted
    aWinPct: number;
    bWinPct: number;
    drawPct: number;
    // for reference: the two role-pure, terrain-weighted numbers for A
    aWinAllAttacker: number;
    aWinAllDefender: number;
    aDeadMean: number;
    bDeadMean: number;
  };
  perTerrain: TerrainOutcome[]; // sorted by weight desc
  runsPerTerrain: number;
  provinceTotal: number;
};

/**
 * Run the matchup on every land terrain, each terrain fought BOTH ways (your army
 * attacking and defending), and weight by how common each terrain is on the CK3 map
 * (land province counts from province_terrain). The overall numbers blend the two roles
 * 50/50 — the expected result for a battle at a random location where you are equally
 * likely to be the attacker or the defender. setup.terrainId is ignored.
 */
export function mapWeighted(setup: BattleSetup, runsPerTerrain = 250): MapWeightedResult {
  const counts = TERRAIN_WEIGHTS.counts;
  const total = TERRAIN_WEIGHTS.total;
  const A = setup.attacker, B = setup.defender;
  const aCP = setup.attackerCultureParams, bCP = setup.defenderCultureParams;
  const perTerrain: TerrainOutcome[] = [];
  let aBlend = 0, bBlend = 0, drw = 0, aAtt = 0, aDef = 0, aDead = 0, bDead = 0;
  for (const [terrainId, weight] of Object.entries(counts)) {
    // A attacks (B is defender, gets terrain advantage)
    const mcAtt = monteCarlo({ ...setup, terrainId }, runsPerTerrain);
    // A defends (swap roles: A gets terrain advantage)
    const mcDef = monteCarlo(
      { ...setup, terrainId, attacker: B, defender: A, attackerCultureParams: bCP, defenderCultureParams: aCP },
      runsPerTerrain,
    );
    const aWinAtt = mcAtt.winPct.attacker; // A is attacker here
    const aWinDef = mcDef.winPct.defender; // A is defender here
    const bWinAtt = mcAtt.winPct.defender;
    const bWinDef = mcDef.winPct.attacker;
    const w = weight / total;
    const blended = 0.5 * (aWinAtt + aWinDef);
    aBlend += blended * w;
    bBlend += 0.5 * (bWinAtt + bWinDef) * w;
    drw += 0.5 * (mcAtt.winPct.draw + mcDef.winPct.draw) * w;
    aAtt += aWinAtt * w;
    aDef += aWinDef * w;
    aDead += 0.5 * (mcAtt.attacker.deadMean + mcDef.defender.deadMean) * w;
    bDead += 0.5 * (mcAtt.defender.deadMean + mcDef.attacker.deadMean) * w;
    perTerrain.push({
      terrainId, weight, weightPct: 100 * w,
      aWinAsAttacker: aWinAtt, aWinAsDefender: aWinDef, aWinBlended: blended,
    });
  }
  perTerrain.sort((a, b) => b.weight - a.weight);
  return {
    overall: {
      aWinPct: aBlend, bWinPct: bBlend, drawPct: drw,
      aWinAllAttacker: aAtt, aWinAllDefender: aDef,
      aDeadMean: aDead, bDeadMean: bDead,
    },
    perTerrain, runsPerTerrain, provinceTotal: total,
  };
}

/** Monte Carlo over `runs` seeded battles. */
export function monteCarlo(setup: BattleSetup, runs = 500, seed0 = 1): McResult {
  const wins = { attacker: 0, defender: 0, draw: 0 } as Record<Side | 'draw', number>;
  const aDead: number[] = [];
  const dDead: number[] = [];
  let aSurv = 0, dSurv = 0, days = 0, wipes = 0;
  const results: BattleResult[] = [];
  for (let i = 0; i < runs; i++) {
    const r = resolveBattle(setup, { mode: 'single', rng: makeRng(seed0 + i) });
    wins[r.winner]++;
    aDead.push(r.attacker.dead);
    dDead.push(r.defender.dead);
    aSurv += r.attacker.survivors;
    dSurv += r.defender.survivors;
    days += r.days;
    if (r.wiped) wipes++;
    results.push(r);
  }
  const aSorted = [...aDead].sort((x, y) => x - y);
  const dSorted = [...dDead].sort((x, y) => x - y);
  const mean = (a: number[]) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);

  // representative sample: the run whose attacker-deaths is nearest the median
  const medA = pct(aSorted, 50);
  let sample = results[0];
  let best = Infinity;
  for (const r of results) {
    const d = Math.abs(r.attacker.dead - medA);
    if (d < best) { best = d; sample = r; }
  }

  return {
    runs,
    winPct: {
      attacker: (100 * wins.attacker) / runs,
      defender: (100 * wins.defender) / runs,
      draw: (100 * wins.draw) / runs,
    },
    attacker: { deadMean: mean(aDead), deadP10: pct(aSorted, 10), deadP90: pct(aSorted, 90), survivorsMean: aSurv / runs },
    defender: { deadMean: mean(dDead), deadP10: pct(dSorted, 10), deadP90: pct(dSorted, 90), survivorsMean: dSurv / runs },
    daysMean: days / runs,
    wipePct: (100 * wipes) / runs,
    sample,
  };
}
