"""
Load DPDPA 2023/2025 rules into PostgreSQL + Weaviate.

Usage:
    python load_dpdpa_rules.py              # Load all rules
    python load_dpdpa_rules.py --clear      # Clear existing and reload
    python load_dpdpa_rules.py --verify     # Verify loaded rules
    python load_dpdpa_rules.py --search "consent for video recording"
    python load_dpdpa_rules.py --list       # List all rule definitions
"""

import argparse
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Load DPDPA rules into databases")
    parser.add_argument("--clear", action="store_true", help="Clear existing rules before loading")
    parser.add_argument("--verify", action="store_true", help="Verify loaded rules")
    parser.add_argument("--search", type=str, help="Test semantic search with a query")
    parser.add_argument("--list", action="store_true", help="List all rule definitions (no DB needed)")
    parser.add_argument("--limit", type=int, default=5, help="Number of search results (default: 5)")
    args = parser.parse_args()

    # --list doesn't need DB connections
    if args.list:
        _list_rules()
        return

    # Import here to avoid loading models when just listing
    from app.services.guideline_loader import GuidelineLoader
    from app.db.session import create_tables

    # Ensure tables exist
    create_tables()

    loader = GuidelineLoader()

    try:
        if args.verify:
            _verify(loader)
        elif args.search:
            _search(loader, args.search, args.limit)
        else:
            _load(loader, args.clear)
    finally:
        loader.close()


def _load(loader, clear_existing: bool):
    """Load all DPDPA rules"""
    print("\n" + "=" * 60)
    print("  DPDPA Rule Loader")
    print("=" * 60)

    if clear_existing:
        print("\n[1/2] Clearing existing rules...")
    else:
        print("\n[1/2] Checking for existing rules...")

    stats = loader.load_all_rules(clear_existing=clear_existing)

    print(f"\n[2/2] Loading complete!")
    print(f"\n  Results:")
    print(f"  ├── Total rules defined:     {stats['total']}")
    print(f"  ├── PostgreSQL inserted:     {stats['pg_inserted']}")
    print(f"  ├── Weaviate inserted:       {stats['weaviate_inserted']}")
    print(f"  ├── Skipped (already exist): {stats['skipped']}")
    print(f"  └── Errors:                  {stats['errors']}")

    if stats["errors"] > 0:
        print(f"\n  Errors:")
        for detail in stats["details"]:
            if "Error" in detail or "Fatal" in detail:
                print(f"    - {detail}")

    # Auto-verify after loading
    print("\n  Verifying...")
    report = loader.verify_load()
    if report["all_ok"]:
        print(f"  All OK: {report['pg_count']} rules in PostgreSQL, "
              f"{report['weaviate_count']} in Weaviate")
    else:
        print(f"  WARNING: PostgreSQL={report['pg_count']}, "
              f"Weaviate={report['weaviate_count']}, "
              f"Expected={report['expected_count']}")

    print()


def _verify(loader):
    """Verify loaded rules"""
    print("\n" + "=" * 60)
    print("  DPDPA Rule Verification")
    print("=" * 60)

    report = loader.verify_load()

    print(f"\n  Expected rules:    {report['expected_count']}")
    print(f"  PostgreSQL count:  {report['pg_count']}  {'OK' if report['pg_ok'] else 'MISMATCH'}")
    print(f"  Weaviate count:    {report['weaviate_count']}  {'OK' if report['weaviate_ok'] else 'MISMATCH'}")
    print(f"  Categories found:  {len(report['categories_found'])}")

    for cat in sorted(report['categories_found']):
        print(f"    - {cat}")

    if report["all_ok"]:
        print(f"\n  Status: ALL OK")
    else:
        print(f"\n  Status: ISSUES DETECTED — run with --clear to reload")

    print()


def _search(loader, query: str, limit: int):
    """Test semantic search"""
    print(f"\n" + "=" * 60)
    print(f"  Semantic Search: \"{query}\"")
    print("=" * 60)

    results = loader.search_rules(query, limit=limit)

    if not results:
        print("\n  No results found. Have you loaded the rules? Run: python load_dpdpa_rules.py")
        return

    for i, r in enumerate(results, 1):
        print(f"\n  [{i}] {r['rule_id']} (similarity: {r['similarity']})")
        print(f"      Category: {r['category']}  |  Severity: {r['severity']}")
        print(f"      Section:  {r['clause']}")
        # Truncate requirement text for display
        req = r['requirement']
        if len(req) > 120:
            req = req[:117] + "..."
        print(f"      Rule:     {req}")

    print()


def _list_rules():
    """List all rule definitions without needing DB"""
    from app.dpdpa.definitions import DPDPA_CATEGORIES, get_all_rules
    from app.dpdpa.penalty_schedule import PENALTY_TIERS

    print("\n" + "=" * 60)
    print("  DPDPA 2023/2025 Rule Definitions")
    print("=" * 60)

    all_rules = get_all_rules()
    print(f"\n  Total rules: {len(all_rules)}")
    print(f"  Categories:  {len(DPDPA_CATEGORIES)}")

    for cat_key, cat_info in DPDPA_CATEGORIES.items():
        rules = cat_info["rules"]
        print(f"\n  [{cat_key}] {cat_info['display_name']} ({len(rules)} rules)")
        print(f"  {cat_info['description']}")
        for rule in rules:
            video_tag = " [VIDEO]" if rule.video_specific else ""
            print(f"    {rule.rule_id}  {rule.name}  ({rule.severity}){video_tag}")

    print(f"\n  Penalty Schedule:")
    for tier in PENALTY_TIERS:
        print(f"    {tier.tier_id}  {tier.section_ref}: {tier.max_penalty_display}")
        print(f"           {tier.description}")

    print()


if __name__ == "__main__":
    main()
