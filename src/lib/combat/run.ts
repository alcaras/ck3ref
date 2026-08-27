// Run helpers over the battle engine: a single expected-value battle, and a Monte Carlo
// batch that reports win odds and casualty distributions.

import { resolveBattle } from './battle';
import { makeRng } from './rng';
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
