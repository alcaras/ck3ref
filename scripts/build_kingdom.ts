// Precompute the best men-at-arms type for a fully-accoladed kingdom. Each type fills the
// realm's regiment slots as a mono-type army (the composition search showed single-type spam
// wins), buffed by the best accolades for it — the type's own attribute (bigger + cheaper
// regiments, +damage/+toughness while the acclaimed knight fights) plus the two army-wide
// attributes valiant (+30% army damage) and stalwart (+15% army toughness) — plus knights.
// We rank types by win rate vs the field of similarly-equipped kingdom armies (average map,
// both roles), and emit per-type regiment size + upkeep so the page can show power and
// upkeep-efficiency for any slot/knight count. Emits src/data/kingdom.json.
//
// Anchored: stack/cost/era from maa.json + combat_sim.json; accolade buffs from
// accolade_types; REGIMENT_DEFAULT_MAX_SIZE (3 base chunks/regiment) from defines.

import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { mapWeightedWinFraction } from '../src/lib/combat/run.ts';
import { resolveRegimentStats } from '../src/lib/combat/stats.ts';
import maa from '../src/data/maa.json' with { type: 'json' };
import sim from '../src/data/combat_sim.json' with { type: 'json' };
import type { ArmySpec, BattleSetup } from '../src/lib/combat/types.ts';

const ERA = 'culture_era_late_medieval';
const BASE_CHUNKS = (sim as any).defines?.REGIMENT_DEFAULT_MAX_SIZE?.value ?? 3; // chunks per regiment, base
const REF_SLOTS = 10, REF_KNIGHTS = 10, REF_PROWESS = 10; // scale-stable reference for the win-rate ranking
const acc = (sim as any).accoladeMaa as { byType: Record<string, any>; armyWide: Record<string, number> };
const VAL = acc.armyWide.valiant_army_damage_mult, STA = acc.armyWide.stalwart_army_toughness_mult;

type Unit = { id: string; name: string; type: string; stack: number; buy: number; maint: number };
const units: Unit[] = (maa as any[])
  .filter((m) => !m.specialRecruitOnly && m.maxRegiments !== 1 && m.type !== 'siege_weapon')
  .map((m) => ({ id: m.id, name: m.name, type: m.type, stack: m.stack ?? 100,
    buy: m.buyCost?.gold ?? NaN, maint: m.highMaintenance?.gold ?? NaN }))
  .filter((u) => Number.isFinite(u.maint));

// per-type accolade-derived facts
function facts(u: Unit) {
  const a = acc.byType[u.type] ?? {};
  const chunks = BASE_CHUNKS + (a.maxSizeAdd ?? 0);
  const regMen = chunks * u.stack;
  // army-wide + type-specific combat mults (knight_army_modifier applies while the knight fights)
  const dmgMult = VAL + (a.damageMult ?? 0);
  const toughMult = STA + (a.toughnessMult ?? 0);
  // upkeep per regiment scales with size (chunks/base) and gets the accolade maintenance discount
  const upkeepPerReg = u.maint * (chunks / BASE_CHUNKS) * (1 + (a.maintMult ?? 0));
  return { chunks, regMen, dmgMult, toughMult, upkeepPerReg, attribute: a.attribute ?? null };
}

// a kingdom army of `slots` regiments of one type, buffed by its accolades, plus knights
function kingdomArmy(u: Unit, slots: number, knights: number, prowess: number): ArmySpec {
  const f = facts(u);
  return {
    regiments: [{ typeId: u.id, men: slots * f.regMen }],
    levies: 0,
    knights: Array.from({ length: knights }, () => prowess),
    era: ERA,
    modifiers: { army_damage_mult: f.dmgMult, army_toughness_mult: f.toughMult },
  };
}

const t0 = Date.now();
const field = units.map((u) => kingdomArmy(u, REF_SLOTS, REF_KNIGHTS, REF_PROWESS));
const rows = units.map((u, i) => {
  const f = facts(u);
  const eff = resolveRegimentStats(u.id, { terrainId: 'plains', era: ERA, mult: { damage: f.dmgMult, toughness: f.toughMult } });
  const me = field[i];
  let s = 0;
  for (const opp of field) s += mapWeightedWinFraction({ attacker: me, defender: opp, terrainId: 'plains' } as BattleSetup);
  const winPct = Math.round((s / field.length) * 1000) / 10;
  return {
    id: u.id, name: u.name, type: u.type,
    stack: u.stack, chunks: f.chunks, regMen: f.regMen,
    upkeepPerReg: Math.round(f.upkeepPerReg * 1000) / 1000,
    hasAccolade: !!f.attribute, attribute: f.attribute,
    dmgMult: Math.round(f.dmgMult * 100) / 100, toughMult: Math.round(f.toughMult * 100) / 100,
    effDmg: Math.round(eff.damage), effTough: Math.round(eff.toughness),
    // crossbowmen are base-type archers: they already get the archer attribute, and can also
    // take the crossbowmen attribute (+archer screen/siege, capital fort) — a pursuit/siege
    // double-dip that trades an army-wide combat attribute, so it isn't in this power loadout.
    doubleDip: u.id === 'crossbowmen' ? 'also eligible for the crossbowmen attribute (+screen/siege/fort)' : undefined,
    winPct,
    // efficiency = strength per upkeep gold (scale-stable): win% per gold/month per regiment
    effPerGold: Math.round((winPct / f.upkeepPerReg) * 100) / 100,
  };
}).sort((a, b) => b.winPct - a.winPct);

const data = {
  meta: {
    era: ERA, baseChunks: BASE_CHUNKS, refSlots: REF_SLOTS, refKnights: REF_KNIGHTS, refProwess: REF_PROWESS,
    valiant: VAL, stalwart: STA,
    note: 'Accolades: each type takes its own MAA attribute + valiant (+army damage) + stalwart (+army toughness). '
      + '<type>_max_size_add enlarges each regiment (chunks), it does NOT add regiment slots. Win% is vs the field '
      + 'of similarly-accoladed kingdom armies (average map, both roles); it is ~independent of slot count, so the '
      + 'sliders scale the absolute men/upkeep, not the ranking.',
    provenance: 'engine:src/lib/combat · accolades from accolade_types · REGIMENT_DEFAULT_MAX_SIZE from defines',
  },
  units: rows,
};
writeFileSync(join(process.cwd(), 'src', 'data', 'kingdom.json'), JSON.stringify(data, null, 2) + '\n');
process.stderr.write(`✓ wrote src/data/kingdom.json — ${rows.length} types — ${((Date.now() - t0) / 1000).toFixed(0)}s\n`);
process.stderr.write(`  strongest: ${rows[0].name} ${rows[0].winPct}% (${rows[0].regMen} men/reg, ${rows[0].upkeepPerReg}g/mo/reg, ${rows[0].attribute})\n`);
const byEff = [...rows].sort((a, b) => b.effPerGold - a.effPerGold);
process.stderr.write(`  most efficient: ${byEff[0].name} ${byEff[0].effPerGold} win%/gold\n`);
