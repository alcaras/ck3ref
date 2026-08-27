// Effective regiment stats: base men-at-arms stats + terrain flat deltas + winter flat
// deltas, then modifier multipliers. Terrain/winter deltas are documented in the game
// data (maa.json terrainBonus/winterBonus) as flat adds to the raw stat, applied before
// multipliers. The exact multiplier stacking order (U12) is a decompiled unknown — see
// applyMultipliers below.

import maaData from '../../data/maa.json';
import { LEVY_STATS, D, eraUpgradeDeltas } from './constants';
import type { Stats, Weather } from './types';

type MaaRow = {
  id: string;
  type: string;
  stats: Partial<Stats>;
  stack?: number;
  counters?: Record<string, number>;
  terrainBonus?: Record<string, Partial<Stats>>;
  winterBonus?: Record<string, Partial<Stats>>;
  mainPhase?: boolean; // false for siege weapons (fights_in_main_phase = no)
};

const MAA: Record<string, MaaRow> = Object.fromEntries(
  (maaData as unknown as MaaRow[]).map((m) => [m.id, m]),
);

export function getMaa(typeId: string): MaaRow | undefined {
  return MAA[typeId];
}

const ZERO: Stats = { damage: 0, toughness: 0, pursuit: 0, screen: 0 };

function addDelta(s: Stats, delta?: Partial<Stats>): Stats {
  if (!delta) return s;
  return {
    damage: s.damage + (delta.damage ?? 0),
    toughness: s.toughness + (delta.toughness ?? 0),
    pursuit: s.pursuit + (delta.pursuit ?? 0),
    screen: s.screen + (delta.screen ?? 0),
  };
}

/**
 * Clamp stats to >= 0. A large negative terrain delta (e.g. armored_horsemen in
 * mountains, -75 damage off a base of 100) can in principle push a stat below zero;
 * negative damage/toughness is not a modelled game behaviour, so we floor at 0.
 * PROVENANCE: assumed — no define proves the floor; flagged for decompiled confirmation.
 */
function clampNonNeg(s: Stats): Stats {
  return {
    damage: Math.max(0, s.damage),
    toughness: Math.max(0, s.toughness),
    pursuit: Math.max(0, s.pursuit),
    screen: Math.max(0, s.screen),
  };
}

/** Base stat block for a men-at-arms type (missing stats default to 0). */
export function baseStats(typeId: string): Stats {
  const row = MAA[typeId];
  if (!row) throw new Error(`unknown men-at-arms type: ${typeId}`);
  return { ...ZERO, ...row.stats };
}

export type ResolveOpts = {
  terrainId: string;
  weather?: Weather;
  /** culture era (e.g. "culture_era_late_medieval"); applies cumulative maa_upgrade deltas */
  era?: string;
  /**
   * Stat multipliers to apply (army_damage_mult, army_toughness_mult, and the
   * per-base-type <type>_damage_mult family, already summed per stat by the caller).
   * Values are additive fractions: 0.15 means +15%.
   */
  mult?: Partial<Record<keyof Stats, number>>;
};

/**
 * Apply summed multiplier fractions to a flat-adjusted stat block.
 * PROVENANCE: U12 (multiplier stacking order) — the game applies terrain/winter flat
 * deltas first, then multipliers; whether multiple mult sources sum or compound is the
 * decompiled unknown. This implements additive summation as the caller's contract.
 */
function applyMultipliers(s: Stats, mult?: Partial<Record<keyof Stats, number>>): Stats {
  if (!mult) return s;
  const f = (k: keyof Stats) => s[k] * (1 + (mult[k] ?? 0));
  return { damage: f('damage'), toughness: f('toughness'), pursuit: f('pursuit'), screen: f('screen') };
}

/** Effective stats for a men-at-arms regiment on this terrain/weather with modifiers. */
export function resolveRegimentStats(typeId: string, opts: ResolveOpts): Stats {
  const row = MAA[typeId];
  if (!row) throw new Error(`unknown men-at-arms type: ${typeId}`);
  let s = baseStats(typeId);
  // era/innovation upgrades are flat adds to the base stat (cumulative across eras)
  s = addDelta(s, eraUpgradeDeltas(opts.era, typeId, row.type));
  s = addDelta(s, row.terrainBonus?.[opts.terrainId]);
  if (opts.weather && opts.weather !== 'none') {
    s = addDelta(s, row.winterBonus?.[opts.weather]);
  }
  s = clampNonNeg(s);
  s = applyMultipliers(s, opts.mult);
  return s;
}

/** Levies do not get terrain/winter unit bonuses; only levy_* modifiers apply (later). */
export function levyStats(mult?: Partial<Record<keyof Stats, number>>): Stats {
  const s: Stats = { ...ZERO, ...LEVY_STATS };
  return applyMultipliers(s, mult);
}

/** Knights convert prowess into a damage/toughness pool via KNIGHT_*_PER_PROWESS. */
export function knightPool(prowessValues: number[], effectiveness = 1): { damage: number; toughness: number } {
  const eff = Math.max(0, effectiveness);
  let damage = 0;
  let toughness = 0;
  for (const p of prowessValues) {
    damage += p * D.KNIGHT_DAMAGE_PER_PROWESS * eff;
    toughness += p * D.KNIGHT_TOUGHNESS_PER_PROWESS * eff;
  }
  return { damage, toughness };
}

export const _internal = { addDelta, clampNonNeg, applyMultipliers };
