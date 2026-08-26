// Catalog of all planned pages. Drives nav, the home index, and placeholder
// routes. Promote status to 'built' as pages land (see PLAN.md phases).

export type TabStatus = 'built' | 'placeholder';

export interface Tab {
  slug: string;
  label: string;
  section: (typeof SECTIONS)[number];
  status: TabStatus;
  summary: string;
}

export const SECTIONS = [
  'Characters',
  'Dynasty',
  'Culture',
  'Faith',
  'Realm',
  'Holdings',
  'Warfare',
  'World',
  'Activities',
  'Concepts',
  'Tools',
] as const;

export const TABS: Tab[] = [
  // Characters
  { slug: 'traits', label: 'Traits', section: 'Characters', status: 'built', summary: 'All character traits: modifiers, opinions, opposites, inheritance.' },
  { slug: 'lifestyles', label: 'Lifestyles & Perks', section: 'Characters', status: 'built', summary: 'The 18 perk trees, rendered as trees.' },
  { slug: 'schemes', label: 'Schemes', section: 'Characters', status: 'placeholder', summary: 'Scheme types, agents, countermeasures.' },
  { slug: 'court-positions', label: 'Court Positions', section: 'Characters', status: 'built', summary: 'Every court position and its tasks.' },
  { slug: 'council', label: 'Council', section: 'Characters', status: 'built', summary: 'Council positions and tasks.' },
  { slug: 'nicknames', label: 'Nicknames', section: 'Characters', status: 'placeholder', summary: 'All 683 nicknames and how to earn them.' },
  // Dynasty
  { slug: 'legacies', label: 'Dynasty Legacies', section: 'Dynasty', status: 'built', summary: '21 legacy tracks, five steps each.' },
  { slug: 'house', label: 'House Mechanics', section: 'Dynasty', status: 'placeholder', summary: 'Unity, aspirations, mottos.' },
  { slug: 'accolades', label: 'Accolades', section: 'Dynasty', status: 'placeholder', summary: 'Knight accolade types and pairings.' },
  // Culture
  { slug: 'traditions', label: 'Traditions', section: 'Culture', status: 'built', summary: '197 traditions: cost, gates, effects.' },
  { slug: 'innovations', label: 'Innovations', section: 'Culture', status: 'built', summary: '108 innovations by era.' },
  { slug: 'pillars', label: 'Pillars', section: 'Culture', status: 'built', summary: '162 pillars: ethos, heritage, language, martial custom.' },
  { slug: 'cultures', label: 'Cultures', section: 'Culture', status: 'placeholder', summary: 'All 193 cultures and their setups.' },
  // Faith
  { slug: 'faiths', label: 'Faiths', section: 'Faith', status: 'built', summary: '140 faiths under 49 religions.' },
  { slug: 'doctrines', label: 'Doctrines & Tenets', section: 'Faith', status: 'built', summary: 'Every doctrine and tenet, with piety costs.' },
  { slug: 'holy-sites', label: 'Holy Sites', section: 'Faith', status: 'built', summary: '326 holy sites and their bonuses.' },
  // Realm
  { slug: 'governments', label: 'Governments', section: 'Realm', status: 'built', summary: 'Feudal to nomadic: every government type.' },
  { slug: 'laws', label: 'Laws', section: 'Realm', status: 'built', summary: 'Crown authority, succession, admin policies.' },
  { slug: 'contracts', label: 'Vassal Contracts', section: 'Realm', status: 'built', summary: 'Obligations, stances, tax slots.' },
  { slug: 'domiciles', label: 'Domiciles', section: 'Realm', status: 'placeholder', summary: 'Camps and estates for landless play.' },
  // Holdings
  { slug: 'buildings', label: 'Buildings', section: 'Holdings', status: 'built', summary: '975 buildings in 366 upgrade chains.' },
  { slug: 'holdings', label: 'Holdings', section: 'Holdings', status: 'placeholder', summary: 'Castle, city, temple, tribe.' },
  { slug: 'great-projects', label: 'Great Projects', section: 'Holdings', status: 'placeholder', summary: 'Special buildings and wonders.' },
  { slug: 'terrain', label: 'Terrain', section: 'Holdings', status: 'placeholder', summary: 'Terrain modifiers and building gates.' },
  // Warfare
  { slug: 'men-at-arms', label: 'Men-at-Arms', section: 'Warfare', status: 'built', summary: 'All 110 regiment types: stats, counters, terrain, costs.' },
  { slug: 'counters', label: 'Counters Matrix', section: 'Warfare', status: 'built', summary: 'Who counters whom, in one grid.' },
  { slug: 'casus-belli', label: 'Casus Belli', section: 'Warfare', status: 'built', summary: '121 war declarations and their terms.' },
  { slug: 'combat', label: 'Combat Mechanics', section: 'Warfare', status: 'placeholder', summary: 'Advantage, phases, knights — from defines.' },
  // World
  { slug: 'titles', label: 'Titles', section: 'World', status: 'built', summary: 'De jure trees for every empire, kingdom, duchy.' },
  { slug: 'start-dates', label: 'Start Dates', section: 'World', status: 'placeholder', summary: 'Who holds what in 867 and 1066.' },
  { slug: 'struggles', label: 'Struggles', section: 'World', status: 'placeholder', summary: 'Iberia, Persia, and the steppe.' },
  { slug: 'legends', label: 'Legends', section: 'World', status: 'placeholder', summary: 'Legend types, seeds, chronicles.' },
  { slug: 'epidemics', label: 'Epidemics', section: 'World', status: 'placeholder', summary: 'The seven plagues.' },
  // Activities
  { slug: 'activities', label: 'Activities', section: 'Activities', status: 'placeholder', summary: 'Feasts, tours, tournaments, pilgrimages.' },
  { slug: 'decisions', label: 'Decisions', section: 'Activities', status: 'placeholder', summary: '431 decisions and their requirements.' },
  { slug: 'events', label: 'Events', section: 'Activities', status: 'placeholder', summary: 'The 9,792-event browser.' },
  // Concepts
  { slug: 'concepts', label: 'Glossary', section: 'Concepts', status: 'built', summary: 'Every game concept, auto-linked.' },
  { slug: 'defines', label: 'Defines', section: 'Concepts', status: 'placeholder', summary: '1,122 engine constants, annotated.' },
  { slug: 'dlc', label: 'DLC Index', section: 'Concepts', status: 'built', summary: 'What each DLC adds.' },
  { slug: 'patch-notes', label: 'Patch Notes', section: 'Concepts', status: 'placeholder', summary: 'Auto-generated data changelog.' },
  // Tools
  { slug: 'genetics', label: 'Genetics Calculator', section: 'Tools', status: 'placeholder', summary: 'Congenital trait inheritance odds.' },
  { slug: 'faith-creator', label: 'Faith Cost Calculator', section: 'Tools', status: 'placeholder', summary: 'Reformation piety costs.' },
  { slug: 'culture-calculator', label: 'Culture Calculator', section: 'Tools', status: 'placeholder', summary: 'Hybrid and divergence costs.' },
  { slug: 'army-builder', label: 'Army Builder', section: 'Tools', status: 'placeholder', summary: 'MAA comps vs counters and terrain.' },
];
