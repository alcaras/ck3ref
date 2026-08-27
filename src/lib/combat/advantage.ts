// Per-side battle advantage, composed from the sources CK3 confirms in the decompiled
// combat roll (FUN_1423cbfa0) and advantage store (side+0x710): terrain defender bonus,
// commander trait flat + terrain-keyed bonuses, hand-entered modifiers, and the per-roll
// random component in [min_roll, max_roll]. Advantage then scales damage in battle.ts via
// adv_mult = 1 + |advantage| * ADVANTAGE_DAMAGE_SCALING_FACTOR/100  (decompiled: FUN_1423053b0).

import terrainData from '../../data/terrain.json';
import { COMMANDER_TRAITS, NAMED_MODIFIERS, D } from './constants';
import type { ArmySpec, CultureParams, Side } from './types';
import type { Rng } from './rng';

type TerrainRow = { id: string; defenderAdvantage: number | null; combatWidth: number };
const TERRAIN: Record<string, TerrainRow> = Object.fromEntries(
  (terrainData as unknown as TerrainRow[]).map((t) => [t.id, t]),
);
const TRAIT = Object.fromEntries(COMMANDER_TRAITS.map((t) => [t.id, t]));

/**
 * PROVENANCE: the commander's martial skill contributes to base advantage (concept/loc text
 * lists "Martial skill" directly under Commander Advantage), but the exact per-point factor is
 * the one main-phase term not yet isolated in the decompilation (U1). Kept as a single tagged
 * constant so it is easy to correct and so callers can zero it out. Default 0 = martial ignored
 * until confirmed, rather than invent a factor.
 */
export const MARTIAL_TO_ADVANTAGE = { value: 0, source: 'assumed:pending-decompilation (U1)' };

/** Sum a commander's trait advantage bonuses that apply flatly or on this terrain. */
function commanderTraitAdvantage(traitIds: string[], terrainId: string, params: CultureParams): number {
  let adv = 0;
  const key = `${terrainId}_advantage`;
  for (const id of traitIds) {
    const t = TRAIT[id];
    if (!t) continue;
    const buckets: Array<Record<string, number> | undefined> = [t.base];
    for (const p of params) buckets.push(t.cultureParams?.[p]);
    // Track: apply the highest reached level (caller may not track XP; use top level present).
    if (t.track) {
      const levels = Object.keys(t.track).map(Number).sort((a, b) => b - a);
      if (levels.length) buckets.push(t.track[String(levels[0])]);
    }
    for (const b of buckets) {
      if (!b) continue;
      adv += b['advantage'] ?? 0;
      adv += b[key] ?? 0;
    }
  }
  return adv;
}

/** min/max combat-roll shift from commander traits + terrain (terrain roll mods not in data yet). */
function rollBounds(traitIds: string[], terrainId: string, params: CultureParams, hasCommander: boolean) {
  let min = hasCommander ? D.COMMANDER_MIN_ROLL : 0;
  let max = hasCommander ? D.COMMANDER_MAX_ROLL : 0;
  const minKey = `${terrainId}_min_combat_roll`;
  const maxKey = `${terrainId}_max_combat_roll`;
  for (const id of traitIds) {
    const t = TRAIT[id];
    if (!t) continue;
    const buckets: Array<Record<string, number> | undefined> = [t.base];
    for (const p of params) buckets.push(t.cultureParams?.[p]);
    for (const b of buckets) {
      if (!b) continue;
      min += (b['min_combat_roll'] ?? 0) + (b[minKey] ?? 0);
      max += (b['max_combat_roll'] ?? 0) + (b[maxKey] ?? 0);
    }
  }
  if (max < min) max = min;
  return { min, max };
}

export type AdvantageInputs = {
  army: ArmySpec;
  side: Side;
  terrainId: string;
  cultureParams: CultureParams;
  /** true if this side is the defender (gets terrain defender advantage) */
  isDefender: boolean;
};

/** The static (non-roll) part of a side's advantage. */
export function baseAdvantage(inp: AdvantageInputs): number {
  const terrain = TERRAIN[inp.terrainId];
  let adv = 0;
  if (inp.isDefender && terrain?.defenderAdvantage) adv += terrain.defenderAdvantage;

  const cmd = inp.army.commander;
  if (cmd) {
    adv += commanderTraitAdvantage(cmd.traits, inp.terrainId, inp.cultureParams);
    adv += cmd.martial * MARTIAL_TO_ADVANTAGE.value;
    if (cmd.leadsOwnTroops) adv += NAMED_MODIFIERS['leading_own_troops_modifier']?.advantage ?? 0;
  }
  // Hand-entered advantage from unmodelled sources (buildings/faith/etc.)
  adv += inp.army.modifiers?.advantage ?? 0;
  return adv;
}

/** min/max roll bounds for a side (for the per-roll random advantage component). */
export function rollRange(inp: AdvantageInputs) {
  const cmd = inp.army.commander;
  return rollBounds(cmd?.traits ?? [], inp.terrainId, inp.cultureParams, !!cmd);
}

/** Draw one combat roll in [min,max] (uniform int), as CK3 does each COMBAT_ROLL_DAYS. */
export function drawRoll(inp: AdvantageInputs, rng: Rng): number {
  const { min, max } = rollRange(inp);
  return rng.int(min, max);
}

/** Expected value of a roll (for deterministic EV mode). */
export function expectedRoll(inp: AdvantageInputs): number {
  const { min, max } = rollRange(inp);
  return (min + max) / 2;
}

export const _internal = { commanderTraitAdvantage, rollBounds };
