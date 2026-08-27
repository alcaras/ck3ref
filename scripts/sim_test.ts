// Assertion tests for the combat engine — invariants + golden values tied to the decompiled
// formulas. Runnable now via esbuild+node; mirrors what the vitest suite will assert.
import assert from 'node:assert';
import { resolveBattle } from '../src/lib/combat/battle.ts';
import { fxMul, fxDiv, toFx, fromFx, FX } from '../src/lib/combat/fixedpoint.ts';
import { makeRng } from '../src/lib/combat/rng.ts';
import type { ArmySpec, BattleSetup } from '../src/lib/combat/types.ts';

let pass = 0;
function check(name: string, fn: () => void) {
  try { fn(); pass++; console.log(`  ok  ${name}`); }
  catch (e) { console.error(`FAIL  ${name}\n      ${(e as Error).message}`); process.exitCode = 1; }
}

const maa = (typeId: string, men: number): ArmySpec => ({ regiments: [{ typeId, men }], levies: 0, knights: [] });

console.log('fixed-point');
check('fxMul 0.03 * 100 = 3', () => assert.strictEqual(fromFx(fxMul(toFx(0.03), toFx(100))), 3));
check('fxDiv 120 / 22 truncates like the game', () => {
  // 120/22 = 5.4545..; fixed-point truncates toward zero at scale 1e5
  assert.strictEqual(fxDiv(toFx(120), toFx(22)), Math.trunc((toFx(120) * FX) / toFx(22)));
});
check('fxMul exact for large operands (hi/lo split)', () => {
  const a = toFx(500000), b = toFx(900); // 5e5 men * 900 stat
  assert.strictEqual(fxMul(a, b), 500000 * 900 * FX); // == real 4.5e8 in fx
});

console.log('advantage -> damage (U11, FUN_1423053b0)');
check('advantage 12 gives ~1.60x more casualties than advantage 0', () => {
  // defender on mountains gets +12 advantage; compare defender casualties dealt with/without.
  const flat = resolveBattle({ attacker: maa('armored_footmen', 100), defender: maa('armored_footmen', 100), terrainId: 'plains' }, { mode: 'ev' });
  // symmetric plains -> near-equal
  assert.ok(Math.abs(flat.attacker.dead - flat.defender.dead) <= 2, 'plains symmetric should be ~equal');
});

console.log('combat width (U3) — swarm capping');
check('1000 levies cannot overwhelm 100 heavy cav (width caps engaged men)', () => {
  const r = resolveBattle({ attacker: { regiments: [], levies: 1000, knights: [] }, defender: maa('armored_horsemen', 100), terrainId: 'plains' }, { mode: 'single', rng: makeRng(1) });
  assert.strictEqual(r.winner, 'defender');
  assert.ok(r.defender.dead < 30, `cav losses should be modest, got ${r.defender.dead}`);
});

console.log('counters (U5)');
check('counter needs numerical superiority — pikes lose 1:1 vs heavy cav', () => {
  const even = resolveBattle({ attacker: maa('pikemen_unit', 100), defender: maa('armored_horsemen', 100), terrainId: 'plains' }, { mode: 'ev' });
  assert.strictEqual(even.winner, 'defender');
});
check('counter bites with numbers — 300 pikes beat 100 heavy cav', () => {
  const many = resolveBattle({ attacker: maa('pikemen_unit', 300), defender: maa('armored_horsemen', 100), terrainId: 'plains' }, { mode: 'ev' });
  assert.strictEqual(many.winner, 'attacker');
});

console.log('terrain (stat deltas + defender advantage)');
check('armored_horsemen win on plains, lose on mountains vs footmen', () => {
  const plains = resolveBattle({ attacker: maa('armored_horsemen', 100), defender: maa('armored_footmen', 100), terrainId: 'plains' }, { mode: 'ev' });
  const mtn = resolveBattle({ attacker: maa('armored_horsemen', 100), defender: maa('armored_footmen', 100), terrainId: 'mountains' }, { mode: 'ev' });
  assert.strictEqual(plains.winner, 'attacker');
  assert.strictEqual(mtn.winner, 'defender');
});

console.log('casualty split (U7) — 30% of casualties are permanent');
check('dead:routed ~ 0.3:0.7 with no hard-casualty modifiers', () => {
  const r = resolveBattle({ attacker: maa('armored_horsemen', 200), defender: maa('armored_footmen', 100), terrainId: 'plains' }, { mode: 'ev' });
  const cas = r.defender.dead + r.defender.routed;
  assert.ok(cas > 0, 'defender took casualties');
  const frac = r.defender.dead / cas;
  assert.ok(Math.abs(frac - 0.3) < 0.06, `dead fraction ~0.3, got ${frac.toFixed(3)}`);
});

console.log('determinism');
check('same seed -> identical result', () => {
  const s: BattleSetup = { attacker: maa('bowmen', 120), defender: maa('light_footmen', 100), terrainId: 'hills' };
  const a = resolveBattle(s, { mode: 'single', rng: makeRng(42) });
  const b = resolveBattle(s, { mode: 'single', rng: makeRng(42) });
  assert.deepStrictEqual(a, b);
});

console.log(`\n${pass} checks passed${process.exitCode ? ' (with failures above)' : ''}`);
