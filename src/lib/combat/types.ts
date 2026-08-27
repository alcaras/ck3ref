// Public input/output shapes for the battle simulator.

/** The four combat stats a regiment carries (siege handled separately). */
export type Stats = {
  damage: number;
  toughness: number;
  pursuit: number;
  screen: number;
};

/** One men-at-arms regiment in an army spec: a type id and a live man count. */
export type RegimentSpec = {
  /** men-at-arms type id, e.g. "armored_footmen", "horse_archers" (matches maa.json) */
  typeId: string;
  /** current soldiers in this regiment (may span several stacks/sub-regiments) */
  men: number;
};

export type Commander = {
  /** martial skill of the commander (feeds advantage; conversion is decompiled) */
  martial: number;
  /** commander trait ids (matches combat_sim.json commanderTraits) */
  traits: string[];
  /** whether the commander is the army owner (adds leading_own_troops advantage) */
  leadsOwnTroops?: boolean;
};

export type ArmySpec = {
  name?: string;
  regiments: RegimentSpec[];
  /** raised levies, modelled as LEVY_* stat soldiers */
  levies: number;
  /** knight prowess values; each knight becomes a damage/toughness pool via defines */
  knights: number[];
  /** knight_effectiveness multiplier (1 = normal, 2 = fight as if prowess doubled) */
  knightEffectiveness?: number;
  commander?: Commander;
  /** culture era for this army (applies cumulative men-at-arms upgrades); e.g. "culture_era_late_medieval" */
  era?: string;
  /**
   * Escape hatch for effects this v1 doesn't model natively (buildings, innovations,
   * accolades, culture). Raw modifier keys -> values, hand-entered, applied like any
   * other modifier so power users can reproduce a real army without us modelling
   * every source system. Keys match the game's modifier vocabulary
   * (advantage, army_damage_mult, hard_casualty_modifier, <base_type>_damage_mult, ...).
   */
  modifiers?: Record<string, number>;
};

/**
 * Which culture parameters each side's culture provides, so terrain-gated commander
 * trait bonuses (culture_modifier { parameter = X }) resolve. Empty = none active.
 */
export type CultureParams = string[];

export type Weather = 'none' | 'normal_winter' | 'harsh_winter';

export type BattleSetup = {
  attacker: ArmySpec;
  defender: ArmySpec;
  /** terrain id from terrain.json (drives defender advantage, combat width, stat deltas) */
  terrainId: string;
  weather?: Weather;
  attackerCultureParams?: CultureParams;
  defenderCultureParams?: CultureParams;
  /** which advantage_damage_effect rule is active (default from the ladder) */
  advantagePctPerPoint?: number;
};

export type Side = 'attacker' | 'defender';

/** A regiment as it actually fights: resolved stats + live/starting men + counter/knight state. */
export type LiveRegiment = {
  typeId: string;
  baseType: string; // archers, heavy_infantry, ...
  isLevy: boolean;
  stats: Stats; // effective, after terrain/winter/modifier resolution
  counters: Record<string, number>;
  stack: number; // sub-regiment size
  startMen: number;
  men: number; // soft-casualty-adjusted current strength
  dead: number; // permanent (hard) casualties
};

export type RegimentCasualties = {
  typeId: string;
  startMen: number;
  survivors: number;
  routed: number; // soft casualties that return after battle
  dead: number; // permanent
};

export type BattleResult = {
  winner: Side | 'draw';
  days: number;
  wiped: boolean; // loser destroyed rather than retreating
  attacker: SideResult;
  defender: SideResult;
  timeline?: TimelineEntry[]; // only for single-battle runs
};

export type SideResult = {
  startMen: number;
  survivors: number;
  dead: number;
  routed: number;
  regiments: RegimentCasualties[];
};

export type TimelineEntry = {
  day: number;
  phase: 'maneuver' | 'main' | 'pursuit';
  attackerRoll?: number;
  defenderRoll?: number;
  attackerAdvantage: number;
  defenderAdvantage: number;
  attackerMen: number;
  defenderMen: number;
  note?: string;
};
