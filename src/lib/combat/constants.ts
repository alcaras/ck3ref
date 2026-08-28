// Combat constants, loaded from the game's own defines via src/data/combat_sim.json
// (built by scripts/build_combat_sim.py). No number in this engine is invented — every
// constant here traces to a define, and every derived formula step is tagged with a
// provenance string (see FORMULAS in ./decompiled.ts for the compiled-in pieces).

import sim from '../../data/combat_sim.json';

type DefineRow = { ns: string; value: number | string };
const RAW = sim.defines as Record<string, DefineRow>;

function n(key: string): number {
  const row = RAW[key];
  if (!row || typeof row.value !== 'number') {
    throw new Error(`combat constant ${key} missing or non-numeric in combat_sim.json`);
  }
  return row.value;
}

/** NCombat / NArmy defines the resolver reads. Source: defines:00_defines.txt. */
export const D = {
  // Battle rhythm (days)
  MANEUVER_PHASE_DAYS: n('MANEUVER_PHASE_DAYS'),
  COMBAT_ROLL_DAYS: n('COMBAT_ROLL_DAYS'),
  PURSUIT_PHASE_DAYS: n('PURSUIT_PHASE_DAYS'),
  COMBAT_EVENT_DAYS: n('COMBAT_EVENT_DAYS'),
  MIN_DAYS_BEFORE_MANUAL_RETREAT: n('MIN_DAYS_BEFORE_MANUAL_RETREAT'),

  // Damage & casualties
  DAMAGE_SCALING_FACTOR: n('DAMAGE_SCALING_FACTOR'),
  ADVANTAGE_DAMAGE_SCALING_FACTOR: n('ADVANTAGE_DAMAGE_SCALING_FACTOR'),
  BASE_RATIO_CASUALTIES_CONVERSION: n('BASE_RATIO_CASUALTIES_CONVERSION'),
  BASE_RATIO_CASUALTIES_CONVERSION_PURSUIT: n('BASE_RATIO_CASUALTIES_CONVERSION_PURSUIT'),

  // Combat width
  BASE_WIDTH_RATIO: n('BASE_WIDTH_RATIO'),
  MINIMUM_COMBAT_WIDTH: n('MINIMUM_COMBAT_WIDTH'),

  // Advantage rolls
  COMMANDER_MIN_ROLL: n('COMMANDER_MIN_ROLL'),
  COMMANDER_MAX_ROLL: n('COMMANDER_MAX_ROLL'),

  // Counters
  MEN_AT_ARMS_MAX_COUNTER: n('MEN_AT_ARMS_MAX_COUNTER'),
  RATIO_FOR_MAX_COUNTER: n('RATIO_FOR_MAX_COUNTER'),

  // Pursuit phase
  PURSUIT_STAT_TO_PURSUIT_DAMAGE: n('PURSUIT_STAT_TO_PURSUIT_DAMAGE'),
  BASE_TOUGHNESS_TO_PURSUIT: n('BASE_TOUGHNESS_TO_PURSUIT'),
  MINIMUM_PURSUIT_DAMAGE: n('MINIMUM_PURSUIT_DAMAGE'),

  // Levy per-soldier stats (levies are a hardcoded unit)
  LEVY_ATTACK: n('LEVY_ATTACK'),
  LEVY_TOUGHNESS: n('LEVY_TOUGHNESS'),
  LEVY_SIEGE: n('LEVY_SIEGE'),
  LEVY_PURSUIT: n('LEVY_PURSUIT'),
  LEVY_SCREEN: n('LEVY_SCREEN'),

  // Knights (prowess -> stat conversion)
  KNIGHT_DAMAGE_PER_PROWESS: n('KNIGHT_DAMAGE_PER_PROWESS'),
  KNIGHT_TOUGHNESS_PER_PROWESS: n('KNIGHT_TOUGHNESS_PER_PROWESS'),

  REGIMENT_DEFAULT_STACK_SIZE: n('REGIMENT_DEFAULT_STACK_SIZE'),
} as const;

/** The advantage_damage_effect game rule: extra % damage per advantage point. */
export const ADVANTAGE_DAMAGE = sim.advantageDamageLadder as {
  pctPerAdvantageOptions: number[];
  default: number;
};

export const COMBAT_EFFECTS = sim.combatEffects as unknown as Record<
  string,
  { advantage: number; adjacency?: boolean; visible?: boolean }
>;

export const NAMED_MODIFIERS = sim.namedModifiers as unknown as Record<
  string,
  Record<string, number>
>;

/** CK3 map terrain distribution: land province counts per terrain + total. */
export const TERRAIN_WEIGHTS = sim.terrainWeights as unknown as {
  counts: Record<string, number>;
  total: number;
};

export type CommanderTrait = {
  id: string;
  name: string;
  category: string;
  base?: Record<string, number>;
  cultureParams?: Record<string, Record<string, number>>;
  track?: Record<string, Record<string, number>>;
};
export const COMMANDER_TRAITS = sim.commanderTraits as unknown as CommanderTrait[];

/** Cumulative men-at-arms era/innovation upgrades (maa_upgrade blocks), by culture era. */
export type EraUpgrade = {
  men_at_arms?: string;
  type?: string;
  damage?: number;
  toughness?: number;
  pursuit?: number;
  screen?: number;
  siege_value?: number;
  max_size?: number;
};
export const ERA_UPGRADES = sim.eraUpgrades as unknown as {
  order: string[];
  byEra: Record<string, EraUpgrade[]>;
};

/** Sum the stat deltas for a unit at a culture era (cumulative over all eras up to it). */
export function eraUpgradeDeltas(era: string | undefined, typeId: string, baseType: string) {
  const d = { damage: 0, toughness: 0, pursuit: 0, screen: 0 };
  if (!era) return d;
  const idx = ERA_UPGRADES.order.indexOf(era);
  if (idx < 0) return d;
  for (let i = 0; i <= idx; i++) {
    const key = ERA_UPGRADES.order[i];
    for (const u of ERA_UPGRADES.byEra[key] ?? []) {
      if (u.men_at_arms === typeId || (u.type && u.type === baseType)) {
        d.damage += u.damage ?? 0;
        d.toughness += u.toughness ?? 0;
        d.pursuit += u.pursuit ?? 0;
        d.screen += u.screen ?? 0;
      }
    }
  }
  return d;
}

/** Levy modelled as a men-at-arms-shaped stat block, from the LEVY_* defines. */
export const LEVY_STATS = {
  damage: D.LEVY_ATTACK,
  toughness: D.LEVY_TOUGHNESS,
  pursuit: D.LEVY_PURSUIT,
  screen: D.LEVY_SCREEN,
} as const;
