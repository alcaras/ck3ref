// Main-phase battle resolution, implemented directly from the decompiled CK3 formulas
// (see ~/code/ck3-decomp/FORMULAS.md; functions cited inline). All arithmetic is fixed-point
// scale 100000 to match the engine's CFixedPoint rounding.
//
// Confirmed each roll (COMBAT_ROLL_DAYS=3), for each side S dealing to enemy E:
//   adv_mult = 1 + |advantage_S| * ADVANTAGE_DAMAGE_SCALING_FACTOR/100        (FUN_1423053b0)
//   counter_mult[arch] = 1 - min(counter_power/own / RATIO_FOR_MAX_COUNTER, 1)*MEN_AT_ARMS_MAX_COUNTER (FUN_1423cf1b0)
//   raw = Σ_reg( per_soldier_damage * men * counter_mult[arch] )              (FUN_1423cae70)
//   engaged = min( menFighting_S / total_men_S , 1 )                          (combat width)
//   side_damage = raw * DAMAGE_SCALING_FACTOR(0.03) * adv_mult * engaged      (FUN_1423cb1d0)
//   then on E, per regiment r:
//     cas_r = side_damage * (men_r/total_men_E) / toughness_r ; cas_r=min(cas_r,men_r)  (FUN_1423ce080)
//     dead_r = cas_r * 0.3*(1+hard_mods) ; routed_r = cas_r - dead_r
//
// SIMPLIFIED / tagged-pending (not from a confirmed formula):
//  - morale/ordered retreat: v1 runs the main phase until one side is destroyed (men=0) or a
//    day cap; real battles often end in retreat earlier. Casualty magnitudes are faithful.
//  - roll accumulation: rolls are treated as independent per roll (advantage = base + this roll);
//    whether rolls accumulate is not confirmed.
//  - martial->advantage factor (MARTIAL_TO_ADVANTAGE, default 0) — see advantage.ts.

import { D } from './constants';
import { FX, toFx, fromFx, fxMul, fxDiv, fxMin } from './fixedpoint';
import { getMaa, resolveRegimentStats, levyStats, knightPool } from './stats';
import { baseAdvantage, drawRoll, expectedRoll, type AdvantageInputs } from './advantage';
import type {
  ArmySpec, BattleSetup, BattleResult, Side, SideResult, LiveRegiment,
  RegimentCasualties, Weather, Stats,
} from './types';
import type { Rng } from './rng';
import { makeRng } from './rng';

// --- effective-stat multiplier gathering from hand-entered modifiers ---------
function statMult(mods: Record<string, number> | undefined, baseType: string): Partial<Record<keyof Stats, number>> {
  if (!mods) return {};
  const g = (k: string) => mods[k] ?? 0;
  return {
    damage: g('army_damage_mult') + g(`${baseType}_damage_mult`),
    toughness: g('army_toughness_mult') + g(`${baseType}_toughness_mult`),
    pursuit: g('army_pursuit_mult') + g(`${baseType}_pursuit_mult`),
    screen: g('army_screen_mult') + g(`${baseType}_screen_mult`),
  };
}

// --- build the live regiment list for a side (all stats per-soldier, fixed-point) ------------
function buildSide(army: ArmySpec, terrainId: string, weather: Weather): LiveRegiment[] {
  const regs: LiveRegiment[] = [];
  for (const r of army.regiments) {
    if (r.men <= 0) continue;
    const maa = getMaa(r.typeId);
    if (!maa) throw new Error(`unknown men-at-arms type: ${r.typeId}`);
    const s = resolveRegimentStats(r.typeId, { terrainId, weather, era: army.era, mult: statMult(army.modifiers, maa.type) });
    regs.push({
      typeId: r.typeId, baseType: maa.type, isLevy: false,
      stats: fxStats(s), counters: maa.counters ?? {},
      stack: maa.stack ?? 100, startMen: toFx(r.men), men: toFx(r.men), dead: 0,
    });
  }
  if (army.levies > 0) {
    const s = levyStats(statMult(army.modifiers, 'levy'));
    regs.push({
      typeId: '__levy', baseType: 'levy', isLevy: true,
      stats: fxStats(s), counters: {}, stack: D.REGIMENT_DEFAULT_STACK_SIZE,
      startMen: toFx(army.levies), men: toFx(army.levies), dead: 0,
    });
  }
  if (army.knights.length > 0) {
    const pool = knightPool(army.knights, army.knightEffectiveness ?? 1);
    // Knights: a small, hard-hitting, tough pseudo-regiment. Per-soldier stats = pool/nKnights.
    const n = army.knights.length;
    regs.push({
      typeId: '__knights', baseType: 'knights', isLevy: false,
      stats: { damage: toFx(pool.damage / n), toughness: toFx(pool.toughness / n), pursuit: 0, screen: 0 },
      counters: {}, stack: 1, startMen: toFx(n), men: toFx(n), dead: 0,
    });
  }
  return regs;
}

function fxStats(s: Stats) {
  return { damage: toFx(s.damage), toughness: toFx(s.toughness), pursuit: toFx(s.pursuit), screen: toFx(s.screen) };
}

const totalMen = (regs: LiveRegiment[]) => regs.reduce((a, r) => a + r.men, 0);

// --- counter multiplier per receiving archetype (U5) ----------------------------------------
function counterMultipliers(attacker: LiveRegiment[], defender: LiveRegiment[]): Record<string, number> {
  // Countering is measured in CHUNKS (men / stack), not raw men — confirmed in the binary
  // (FUN_1423d2b90 returns men/stack). This matters because stack varies by type (100 for
  // most, 50 heavy cavalry, 25 elephants); using raw men over-counters low-stack units by
  // 100/stack (2x heavy cav, 4x elephants). counter_power against archetype A =
  // Σ over attacker regiments (chunks * counter_value_vs_A).
  const power: Record<string, number> = {};
  for (const a of attacker) {
    const chunks = fxDiv(a.men, toFx(a.stack));
    for (const [arch, cv] of Object.entries(a.counters)) {
      power[arch] = (power[arch] ?? 0) + fxMul(chunks, toFx(cv));
    }
  }
  const mult: Record<string, number> = {};
  for (const d of defender) {
    const cp = power[d.baseType];
    if (!cp || d.men <= 0) { mult[d.typeId] = FX; continue; }
    const ownChunks = fxDiv(d.men, toFx(d.stack));
    const ratio = fxDiv(cp, ownChunks); // counter_power(chunks) / own_strength(chunks)
    const norm = fxMin(fxDiv(ratio, toFx(D.RATIO_FOR_MAX_COUNTER)), FX); // min(ratio/2, 1)
    const penalty = fxMul(norm, toFx(D.MEN_AT_ARMS_MAX_COUNTER)); // * 0.9
    mult[d.typeId] = FX - penalty; // 1 - penalty
  }
  return mult;
}

// --- raw matchup damage: Σ per-soldier damage * men * counter_mult (U5 in, FUN_1423cae70) ---
function rawDamage(dealer: LiveRegiment[], counterMult: Record<string, number>): number {
  let raw = 0;
  for (const r of dealer) {
    if (r.men <= 0) continue;
    const cm = counterMult[r.typeId] ?? FX;
    const perReg = fxMul(r.stats.damage, r.men); // damage/soldier * men
    raw += fxMul(perReg, cm);
  }
  return raw;
}

// --- apply side_damage to the receiving side as casualties (U6/U7, FUN_1423ce080) -----------
function applyCasualties(recv: LiveRegiment[], sideDamage: number, hardMods: number): void {
  const total = totalMen(recv);
  if (total <= 0) return;
  const conversion = fxMul(toFx(D.BASE_RATIO_CASUALTIES_CONVERSION), FX + hardMods); // 0.3*(1+mods)
  for (const r of recv) {
    if (r.men <= 0) continue;
    const share = fxMul(sideDamage, fxDiv(r.men, total)); // damage * men/total
    let cas = fxDiv(share, r.stats.toughness); // / toughness
    if (cas > r.men) cas = r.men;
    if (cas < 0) cas = 0;
    const dead = fxMul(cas, conversion);
    r.dead += dead;
    r.men -= cas; // both dead and routed leave the fight; routed tracked as cas-dead
    // routed men (cas - dead) would return post-battle; we report them separately.
    (r as LiveRegiment & { routed?: number }).routed = ((r as { routed?: number }).routed ?? 0) + (cas - dead);
  }
}

function sideHardMods(army: ArmySpec, enemy: ArmySpec, weather: Weather): number {
  // hard_casualty_mods = hard_casualty_winter + enemy.enemy_hard_casualty_modifier + self.hard_casualty_modifier
  const winter = weather === 'harsh_winter' ? (army.modifiers?.hard_casualty_winter ?? toFxReal(0.2)) : 0;
  const self = army.modifiers?.hard_casualty_modifier ?? 0;
  const fromEnemy = enemy.modifiers?.enemy_hard_casualty_modifier ?? 0;
  return toFx(winter + self + fromEnemy);
}
const toFxReal = (r: number) => r; // hard_casualty_winter default 0.2 is a real fraction

// --- one main-phase roll: both sides deal simultaneously ------------------------------------
type SideState = { regs: LiveRegiment[]; adv: number; menFighting: number };

function resolveRoll(a: SideState, b: SideState, aHardMods: number, bHardMods: number): void {
  const advMult = (adv: number) => FX + Math.trunc((Math.abs(adv) * D.ADVANTAGE_DAMAGE_SCALING_FACTOR * FX) / 100);
  const engaged = (s: SideState) => {
    const t = totalMen(s.regs);
    return t <= 0 ? 0 : fxMin(fxDiv(s.menFighting, t), FX);
  };
  const scale = toFx(D.DAMAGE_SCALING_FACTOR);

  const aCounter = counterMultipliers(b.regs, a.regs); // b counters a's regiments
  const bCounter = counterMultipliers(a.regs, b.regs);

  const aRaw = rawDamage(a.regs, aCounter);
  const bRaw = rawDamage(b.regs, bCounter);

  const aDamage = fxMul(fxMul(fxMul(aRaw, scale), advMult(a.adv)), engaged(a));
  const bDamage = fxMul(fxMul(fxMul(bRaw, scale), advMult(b.adv)), engaged(b));

  // simultaneous: apply each side's output to the other
  applyCasualties(b.regs, aDamage, bHardMods);
  applyCasualties(a.regs, bDamage, aHardMods);
}

// --- combat width (defender size drives it) -------------------------------------------------
function combatWidth(defenderMenFx: number, terrainCombatWidth: number): number {
  const base = fxMul(defenderMenFx, toFx(D.BASE_WIDTH_RATIO));
  const floored = Math.max(base, toFx(D.MINIMUM_COMBAT_WIDTH));
  return fxMul(floored, toFx(terrainCombatWidth));
}

export type RunMode = 'single' | 'ev';

export function resolveBattle(setup: BattleSetup, opts: { mode?: RunMode; rng?: Rng; maxDays?: number } = {}): BattleResult {
  const weather = setup.weather ?? 'none';
  const mode = opts.mode ?? 'single';
  const rng = opts.rng ?? makeRng(1);
  const maxDays = opts.maxDays ?? 400;

  const aRegs = buildSide(setup.attacker, setup.terrainId, weather);
  const dRegs = buildSide(setup.defender, setup.terrainId, weather);
  const aStart = totalMen(aRegs);
  const dStart = totalMen(dRegs);

  const terrainCW = terrainCombatWidth(setup.terrainId);
  const width = combatWidth(dStart, terrainCW);

  const advA: AdvantageInputs = {
    army: setup.attacker, side: 'attacker', terrainId: setup.terrainId,
    cultureParams: setup.attackerCultureParams ?? [], isDefender: false,
  };
  const advD: AdvantageInputs = {
    army: setup.defender, side: 'defender', terrainId: setup.terrainId,
    cultureParams: setup.defenderCultureParams ?? [], isDefender: true,
  };
  const aBase = baseAdvantage(advA);
  const dBase = baseAdvantage(advD);
  const aHardMods = sideHardMods(setup.attacker, setup.defender, weather);
  const dHardMods = sideHardMods(setup.defender, setup.attacker, weather);

  let day = D.MANEUVER_PHASE_DAYS; // maneuver phase passes with no damage
  let wiped = false;
  while (day < maxDays) {
    const aMen = totalMen(aRegs);
    const dMen = totalMen(dRegs);
    if (aMen <= 0 || dMen <= 0) { wiped = true; break; }

    const aRoll = mode === 'ev' ? expectedRoll(advA) : drawRoll(advA, rng);
    const dRoll = mode === 'ev' ? expectedRoll(advD) : drawRoll(advD, rng);
    const a: SideState = { regs: aRegs, adv: aBase + aRoll, menFighting: fxMin(width, aMen) };
    const d: SideState = { regs: dRegs, adv: dBase + dRoll, menFighting: fxMin(width, dMen) };
    resolveRoll(a, d, aHardMods, dHardMods);
    day += D.COMBAT_ROLL_DAYS;
  }

  const aMen = totalMen(aRegs);
  const dMen = totalMen(dRegs);
  const winner: Side | 'draw' = aMen > dMen ? 'attacker' : dMen > aMen ? 'defender' : 'draw';

  return {
    winner, days: day, wiped,
    attacker: sideResult(aRegs, aStart),
    defender: sideResult(dRegs, dStart),
  };
}

function sideResult(regs: LiveRegiment[], startFx: number): SideResult {
  const rc: RegimentCasualties[] = regs.map((r) => {
    const routed = (r as { routed?: number }).routed ?? 0;
    return {
      typeId: r.typeId,
      startMen: Math.round(fromFx(r.startMen)),
      survivors: Math.max(0, Math.round(fromFx(r.men))),
      routed: Math.round(fromFx(routed)),
      dead: Math.round(fromFx(r.dead)),
    };
  });
  const survivors = regs.reduce((a, r) => a + Math.max(0, r.men), 0);
  const dead = regs.reduce((a, r) => a + r.dead, 0);
  const routed = regs.reduce((a, r) => a + ((r as { routed?: number }).routed ?? 0), 0);
  return {
    startMen: Math.round(fromFx(startFx)),
    survivors: Math.round(fromFx(survivors)),
    dead: Math.round(fromFx(dead)),
    routed: Math.round(fromFx(routed)),
    regiments: rc,
  };
}

// terrain combat_width multiplier from terrain.json
import terrainData from '../../data/terrain.json';
const _terrainCW: Record<string, number> = Object.fromEntries(
  (terrainData as unknown as { id: string; combatWidth: number }[]).map((t) => [t.id, t.combatWidth ?? 1]),
);
function terrainCombatWidth(id: string): number {
  return _terrainCW[id] ?? 1;
}
