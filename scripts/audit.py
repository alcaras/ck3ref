#!/usr/bin/env python3
"""Audit gates. Fails the pipeline (exit 1) on:

1. A game/common/ directory that is neither mapped to a build script nor in
   the conscious SKIP list — the patch tripwire for new content categories.
2. A has_dlc_feature flag not covered by ck3.FEATURE_TO_DLC.
3. Emitted entities without localized names.

Warnings (non-fatal): modifier keys emitted without a display format entry.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))
import ck3

# Dirs handled by a build script today.
MAPPED = {
    "men_at_arms_types": "build_maa.py",
    "traits": "build_traits.py",
    "lifestyles": "build_lifestyles.py",
    "lifestyle_perks": "build_lifestyles.py",
    "focuses": "build_lifestyles.py",
    "dynasty_legacies": "build_legacies.py",
    "dynasty_perks": "build_legacies.py",
    "buildings": "build_buildings.py",
    "religion": "build_faiths.py / build_doctrines.py / build_holy_sites.py",
    "terrain_types": "build_entities.py",
    "game_concepts": "build_concepts.py + lib/ck3.py link targets",
    "culture": "build_traditions.py / build_innovations.py / build_pillars.py"
               " (subdirs cultures/eras/name_lists pending phase 2)",
    "modifier_definition_formats": "lib/ck3.py (modifier formatter)",
    "script_values": "lib/ck3.py (value resolver)",
}

# Consciously not yet rendered; phase from PLAN.md. A NEW dir after a patch
# won't be in either set and fails the audit — that's the point.
SKIP = {
    # phase 1
    "holdings", "laws",
    "governments", "subject_contracts", "casus_belli_types", "casus_belli_groups",
    "court_positions", "council_positions", "council_tasks", "great_projects",
    # phase 2
    "landed_titles", "decisions", "decision_group_types", "activities", "travel",
    "struggle", "situation", "legends", "epidemics", "nicknames", "artifacts",
    "domiciles", "task_contracts", "accolade_types", "accolade_names",
    "accolade_icons", "character_interactions", "character_interaction_categories",
    "schemes", "secret_types", "hook_types", "factions", "succession_election",
    "succession_appointment", "tax_slots", "lease_contracts", "vassal_stances",
    "diarchies", "confederation_types", "legitimacy", "house_unities",
    "house_aspirations", "house_relation_types", "dynasty_houses", "dynasties",
    "dynasty_house_mottos", "dynasty_house_motto_inserts", "inspirations",
    "story_cycles", "bookmarks", "game_rules", "defines", "flavorization",
    "court_types", "court_amenities", "raids",
    # engine/plumbing — no reference value planned
    "on_action", "scripted_effects", "scripted_triggers", "scripted_modifiers",
    "scripted_lists", "scripted_costs", "scripted_rules", "scripted_guis",
    "scripted_animations", "scripted_character_templates", "modifiers",
    "opinion_modifiers", "modifier_icons", "named_colors", "coat_of_arms",
    "customizable_localization", "effect_localization", "trigger_localization",
    "messages", "message_filter_types", "message_group_types", "important_actions",
    "suggestions", "ruler_objective_advice_types", "tutorial_lessons",
    "tutorial_lesson_chains", "event_themes", "event_backgrounds",
    "event_transitions", "event_2d_effects", "ethnicities", "genes", "dna_data",
    "portrait_types", "bookmark_portraits", "achievements", "achievement_groups.txt",
    "character_backgrounds", "character_memory_types", "deathreasons",
    "scripted_relations", "pool_character_selectors", "guest_system",
    "courtier_guest_management", "graphical_unit_types", "combat_effects",
    "combat_phase_events", "ai_war_stances", "ai_goaltypes", "province_terrain",
    "connection_arrows", "playable_difficulty_infos", "console_groups",
    "province_mapping",
}

def main():
    failures = []

    dirs = {p.name for p in ck3.COMMON.iterdir()}
    unmapped = dirs - set(MAPPED) - SKIP
    if unmapped:
        failures.append(f"unmapped game/common dirs (new patch content?): {sorted(unmapped)}")

    # trigger DLC-feature scan over emitted datasets' sources
    data_dir = ck3.ROOT / "src" / "data"
    maa = json.loads((data_dir / "maa.json").read_text(encoding="utf-8"))
    unknown = ck3.unknown_feature_report()
    if unknown:
        failures.append(f"has_dlc_feature flags missing from FEATURE_TO_DLC: {unknown}")

    unnamed = [r["id"] for r in maa if not r.get("name")]
    if unnamed:
        failures.append(f"maa entries without localized names: {unnamed}")

    missing_fmt = ck3.missing_modifier_report()
    if missing_fmt:
        print(f"⚠ modifier keys without format/loc (generic fallback used): {missing_fmt[:12]}")

    if failures:
        for f in failures:
            print(f"✗ AUDIT: {f}")
        sys.exit(1)
    print("✓ audit passed")


if __name__ == "__main__":
    main()
