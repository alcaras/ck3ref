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
    "casus_belli_types": "build_cbs.py",
    "casus_belli_groups": "build_cbs.py",
    "landed_titles": "build_titles.py + build_startworld.py",
    "governments": "build_governments.py",
    "laws": "build_laws.py",
    "subject_contracts": "build_contracts.py",
    "court_positions": "build_court.py",
    "council_positions": "build_council.py",
    "council_tasks": "build_council.py",
    "terrain_types": "build_terrain.py + build_entities.py",
    "holdings": "build_holdings.py",
    "great_projects": "build_great_projects.py",
    "activities": "build_activities.py",
    "travel": "build_activities.py",
    "decisions": "build_decisions.py",
    "decision_group_types": "build_decisions.py",
    "defines": "build_defines.py",
    "schemes": "build_schemes.py (pulse_actions skipped: flavor-event scheduling)",
    "nicknames": "build_nicknames.py",
    "struggle": "build_struggles.py",
    "situation": "build_situations.py",
    "legends": "build_legends.py",
    "epidemics": "build_epidemics.py",
    "artifacts": "build_artifacts.py",
    "accolade_types": "build_accolades.py",
    "accolade_names": "build_accolades.py",
    "house_unities": "build_house.py",
    "house_aspirations": "build_house.py",
    "house_relation_types": "build_house.py",
    "legitimacy": "build_house.py",
    "diarchies": "build_house.py",
    "domiciles": "build_domiciles.py",
    "task_contracts": "build_task_contracts.py",
    "game_concepts": "build_concepts.py + lib/ck3.py link targets",
    "culture": "build_traditions.py / build_innovations.py / build_pillars.py"
               " / build_cultures.py (subdirs eras/name_lists pending)",
    "modifier_definition_formats": "lib/ck3.py (modifier formatter)",
    "script_values": "lib/ck3.py (value resolver)",
}

# Consciously not yet rendered; phase from PLAN.md. A NEW dir after a patch
# won't be in either set and fails the audit — that's the point.
SKIP = {
    # phase 2
        "accolade_icons", "character_interactions", "character_interaction_categories",
    "secret_types", "hook_types", "factions", "succession_election",
    "succession_appointment", "tax_slots", "lease_contracts", "vassal_stances",
    "confederation_types", "dynasty_houses", "dynasties",
    "dynasty_house_mottos", "dynasty_house_motto_inserts", "inspirations",
    "story_cycles", "bookmarks", "game_rules", "flavorization",
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
