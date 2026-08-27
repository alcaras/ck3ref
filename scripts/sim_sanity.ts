// Quick plausibility runner for the combat engine. Run with:
//   node --experimental-strip-types scripts/sim_sanity.ts
import { resolveBattle } from '../src/lib/combat/battle.ts';
import { makeRng } from '../src/lib/combat/rng.ts';
import type { ArmySpec, BattleSetup } from '../src/lib/combat/types.ts';

const empty = (): ArmySpec => ({ regiments: [], levies: 0, knights: [] });
const maa = (typeId: string, men: number): ArmySpec => ({ regiments: [{ typeId, men }], levies: 0, knights: [] });

function mc(setup: BattleSetup, n = 400) {
  let aWins = 0, dWins = 0, draws = 0, aDead = 0, dDead = 0, days = 0;
  for (let i = 0; i < n; i++) {
    const r = resolveBattle(setup, { mode: 'single', rng: makeRng(i + 1) });
    if (r.winner === 'attacker') aWins++; else if (r.winner === 'defender') dWins++; else draws++;
    aDead += r.attacker.dead; dDead += r.defender.dead; days += r.days;
  }
  return { aWinPct: (100 * aWins / n).toFixed(0), dWinPct: (100 * dWins / n).toFixed(0),
    draws, aDeadAvg: Math.round(aDead / n), dDeadAvg: Math.round(dDead / n), daysAvg: Math.round(days / n) };
}

function show(label: string, setup: BattleSetup) {
  const r = mc(setup);
  console.log(`${label.padEnd(52)} A ${r.aWinPct}% / D ${r.dWinPct}%  (draws ${r.draws})  dead A/D ≈ ${r.aDeadAvg}/${r.dDeadAvg}  ~${r.daysAvg}d`);
}

console.log('CK3 combat engine — sanity battles (400-run Monte Carlo each)\n');

show('symmetric: 100 armored_footmen vs 100 (plains)',
  { attacker: maa('armored_footmen', 100), defender: maa('armored_footmen', 100), terrainId: 'plains' });

show('1000 levies (attacker) vs 100 armored_horsemen (plains)',
  { attacker: { regiments: [], levies: 1000, knights: [] }, defender: maa('armored_horsemen', 100), terrainId: 'plains' });

show('100 bowmen vs 100 light_footmen [archers counter skirm] (plains)',
  { attacker: maa('bowmen', 100), defender: maa('light_footmen', 100), terrainId: 'plains' });

show('100 pikemen_unit vs 100 armored_horsemen [pikes counter cav]',
  { attacker: maa('pikemen_unit', 100), defender: maa('armored_horsemen', 100), terrainId: 'plains' });

show('100 armored_horsemen ATT vs 100 armored_footmen — plains',
  { attacker: maa('armored_horsemen', 100), defender: maa('armored_footmen', 100), terrainId: 'plains' });

show('100 armored_horsemen ATT vs 100 armored_footmen — mountains',
  { attacker: maa('armored_horsemen', 100), defender: maa('armored_footmen', 100), terrainId: 'mountains' });

show('defender terrain edge: 200 footmen ATT vs 150 footmen DEF (mountains)',
  { attacker: maa('armored_footmen', 200), defender: maa('armored_footmen', 150), terrainId: 'mountains' });

// detailed single battle
console.log('\nDetailed EV battle — 500 armored_footmen vs 300 pikemen_unit + 200 bowmen (hills):');
const detail = resolveBattle({
  attacker: maa('armored_footmen', 500),
  defender: { regiments: [{ typeId: 'pikemen_unit', men: 300 }, { typeId: 'bowmen', men: 200 }], levies: 0, knights: [] },
  terrainId: 'hills',
}, { mode: 'ev' });
console.log(`  winner=${detail.winner} wiped=${detail.wiped} days=${detail.days}`);
console.log(`  ATT: ${detail.attacker.survivors}/${detail.attacker.startMen} survive, ${detail.attacker.dead} dead, ${detail.attacker.routed} routed`);
console.log(`  DEF: ${detail.defender.survivors}/${detail.defender.startMen} survive, ${detail.defender.dead} dead, ${detail.defender.routed} routed`);
for (const r of detail.defender.regiments) console.log(`     def ${r.typeId}: ${r.survivors}/${r.startMen} (${r.dead} dead)`);
