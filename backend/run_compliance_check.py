"""
CLI tool for running DPDPA compliance checks on processed videos.

Usage:
    venv\\Scripts\\python.exe run_compliance_check.py --video-id test_video_001
    venv\\Scripts\\python.exe run_compliance_check.py --video-id test_video_001 --report
    venv\\Scripts\\python.exe run_compliance_check.py --video-id test_video_001 --audit
    venv\\Scripts\\python.exe run_compliance_check.py --video-id test_video_001 --findings
    venv\\Scripts\\python.exe run_compliance_check.py --video-id test_video_001 --purge --report-id <id>
    venv\\Scripts\\python.exe run_compliance_check.py --list-videos
"""
import sys
import os
import argparse
# Add backend/ to path so app imports work
sys.path.insert(0, os.path.dirname(__file__))


def print_section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)


def run_check(video_id: str, use_llm: bool = False):
    from app.services.compliance_checker import check_video_compliance

    print_section(f"Running Compliance Check: {video_id}")
    print("Phase 1: Structured rule matching (YOLO + OCR + Audio + Metadata + Semantic)...")

    result = check_video_compliance(video_id=video_id, use_llm=use_llm)

    print(f"\n  Report ID:          {result['report_id']}")
    print(f"  Status:             {result['status'].upper()}")
    print(f"  Compliance Score:   {result['compliance_score']:.1f}/100" if result.get("compliance_score") is not None else "  Compliance Score:   N/A")
    print(f"  Total Checks:       {result['total_checks']}")
    print(f"  Failed Checks:      {result['failed_checks']}")
    print(f"  Critical Violations:{result['critical_violations']}")
    print(f"  Findings:           {result['findings_count']}")
    print(f"  Audit Entries:      {result['audit_entries_count']}")

    if result.get("errors"):
        print(f"\n  Errors ({len(result['errors'])}):")
        for err in result["errors"]:
            print(f"    - {err}")

    print(f"\n  Use --report to see the full compliance report.")
    print(f"  Use --audit  to see the step-by-step audit trail.")
    return result


def show_report(video_id: str):
    from app.services.compliance_checker import get_report_summary
    from app.db.session import SessionLocal
    from app.models.compliance_report import ComplianceReport

    db = SessionLocal()
    try:
        report = (
            db.query(ComplianceReport)
            .filter(ComplianceReport.video_id == video_id)
            .order_by(ComplianceReport.created_at.desc())
            .first()
        )
        if not report:
            print(f"\n  No report found for video {video_id}. Run without --report first.")
            return
        report_id = report.id
    finally:
        db.close()

    summary = get_report_summary(report_id)
    if not summary:
        print(f"\n  Report {report_id} not found.")
        return

    print_section(f"Compliance Report: {video_id}")
    print(f"  Report ID:          {summary['report_id']}")
    status_val = str(summary['status']).split('.')[-1].upper()
    print(f"  Status:             {status_val}")
    score = summary.get('compliance_score')
    print(f"  Compliance Score:   {score:.1f}/100" if score is not None else "  Compliance Score:   N/A")
    print(f"  Total Checks:       {summary['total_checks']}")
    print(f"  Passed Checks:      {summary['passed_checks']}")
    print(f"  Failed Checks:      {summary['failed_checks']}")
    print(f"  Critical Violations:{summary['critical_violations']}")
    print(f"  Warnings:           {summary['warnings']}")
    print(f"  Completed At:       {summary.get('completed_at', 'N/A')}")

    if summary.get("executive_summary"):
        print(f"\n  Executive Summary:")
        print(f"    {summary['executive_summary']}")

    findings = summary.get("findings", [])
    violations = [f for f in findings if f.get("is_violation")]
    if violations:
        print(f"\n  Violations ({len(violations)}):")
        for i, f in enumerate(violations, 1):
            ev = f.get("visual_evidence", {}) or {}
            sev = str(f.get('severity', '')).split('.')[-1].upper()
            print(f"\n    [{i}] {ev.get('rule_id', 'N/A')} | {sev}")
            print(f"        {f.get('description', '')}")
            if f.get("timestamp_start") is not None:
                print(f"        Timestamp: {f['timestamp_start']:.1f}s")
            if ev.get("pii_found"):
                print(f"        PII found: {ev['pii_found']}")
            penalty = ev.get("penalty_ref", "")
            if penalty:
                print(f"        Penalty: {penalty}")
    else:
        print("\n  No violations found.")


def show_audit(video_id: str):
    from app.services.compliance_checker import get_audit_trail
    from app.db.session import SessionLocal
    from app.models.compliance_report import ComplianceReport

    db = SessionLocal()
    try:
        report = (
            db.query(ComplianceReport)
            .filter(ComplianceReport.video_id == video_id)
            .order_by(ComplianceReport.created_at.desc())
            .first()
        )
        if not report:
            print(f"\n  No report found for video {video_id}.")
            return
        report_id = report.id
    finally:
        db.close()

    logs = get_audit_trail(report_id)
    print_section(f"Audit Trail: {video_id} (Report: {report_id})")
    print(f"  Total entries: {len(logs)}\n")

    for i, entry in enumerate(logs, 1):
        status = "✓" if entry.get("success") else "✗"
        duration = f" ({entry['duration_ms']}ms)" if entry.get("duration_ms") else ""
        rule = f" [{entry['rule_id']}]" if entry.get("rule_id") else ""
        print(f"  {i:3}. [{entry['step']}]{rule} {status}{duration}")
        print(f"       {entry['action']}")
        if entry.get("error_message"):
            print(f"       ERROR: {entry['error_message']}")


def show_findings(video_id: str):
    from app.services.compliance_checker import get_report_summary
    from app.db.session import SessionLocal
    from app.models.compliance_report import ComplianceReport

    db = SessionLocal()
    try:
        report = (
            db.query(ComplianceReport)
            .filter(ComplianceReport.video_id == video_id)
            .order_by(ComplianceReport.created_at.desc())
            .first()
        )
        if not report:
            print(f"\n  No report found for video {video_id}.")
            return
        report_id = report.id
    finally:
        db.close()

    summary = get_report_summary(report_id)
    findings = summary.get("findings", []) if summary else []

    print_section(f"All Findings: {video_id}")
    print(f"  Total findings: {len(findings)}\n")

    for i, f in enumerate(findings, 1):
        ev = f.get("visual_evidence", {}) or {}
        is_v = "VIOLATION" if f.get("is_violation") else "PASSED"
        sev = str(f.get('severity', '')).split('.')[-1].upper()
        print(f"  [{i}] {ev.get('rule_id', 'N/A')} | {is_v} | {sev}")
        print(f"       {f.get('description', '')[:120]}")
        if f.get("timestamp_start") is not None:
            print(f"       @ {f['timestamp_start']:.1f}s", end="")
        if ev.get("objects_detected"):
            print(f" | objects: {ev['objects_detected']}", end="")
        print()


def do_purge(video_id: str, report_id: str):
    from app.services.data_lifecycle import purge_raw_data

    print_section(f"Purging Raw Data: {video_id}")
    print("  This will delete raw video artifacts. Compliance report will be preserved.")
    confirm = input("  Confirm purge? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("  Purge cancelled.")
        return

    result = purge_raw_data(video_id=video_id, report_id=report_id)
    print(f"\n  Deleted:")
    print(f"    MinIO video:              {'yes' if result['deleted']['minio_video'] else 'no/skipped'}")
    print(f"    MinIO frames:             {result['deleted']['minio_frames']}")
    print(f"    Weaviate vectors:         {result['deleted']['weaviate_vectors']}")
    print(f"    frame_analyses rows:      {result['deleted']['frame_analyses']}")
    print(f"    transcription_segments:   {result['deleted']['transcription_segments']}")
    if result.get("errors"):
        print(f"\n  Errors:")
        for err in result["errors"]:
            print(f"    - {err}")


def list_videos():
    from app.db.session import SessionLocal
    from app.models.video import Video
    from app.models.compliance_report import ComplianceReport

    db = SessionLocal()
    try:
        videos = db.query(Video).order_by(Video.created_at.desc()).limit(20).all()
        print_section("Videos in Database")
        if not videos:
            print("  No videos found.")
            return

        for v in videos:
            report = (
                db.query(ComplianceReport)
                .filter(ComplianceReport.video_id == v.id)
                .order_by(ComplianceReport.created_at.desc())
                .first()
            )
            report_status = str(report.status) if report else "no report"
            score = f"{report.compliance_score:.0f}/100" if report and report.compliance_score else "N/A"
            print(f"  {v.id}  |  {str(v.status)}  |  compliance: {report_status}  |  score: {score}")
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="DPDPA Compliance Check CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Run compliance check:
    python run_compliance_check.py --video-id test_video_001

  View the compliance report:
    python run_compliance_check.py --video-id test_video_001 --report

  View step-by-step audit trail:
    python run_compliance_check.py --video-id test_video_001 --audit

  View all findings with evidence:
    python run_compliance_check.py --video-id test_video_001 --findings

  Enable LLM narrative summary (Ollama must be running):
    python run_compliance_check.py --video-id test_video_001 --llm

  Purge raw data after report is complete:
    python run_compliance_check.py --video-id test_video_001 --purge --report-id <id>

  List all videos:
    python run_compliance_check.py --list-videos
        """
    )

    parser.add_argument("--video-id", help="Video ID to process")
    parser.add_argument("--report", action="store_true", help="Show compliance report for the video")
    parser.add_argument("--audit", action="store_true", help="Show step-by-step audit trail")
    parser.add_argument("--findings", action="store_true", help="Show all findings with evidence")
    parser.add_argument("--purge", action="store_true", help="Purge raw data (requires --report-id)")
    parser.add_argument("--report-id", help="Report ID (used with --purge)")
    parser.add_argument("--llm", action="store_true", help="Enable Ollama LLM for narrative summary")
    parser.add_argument("--list-videos", action="store_true", help="List all videos in database")

    args = parser.parse_args()

    if args.list_videos:
        list_videos()
        return

    if not args.video_id:
        parser.print_help()
        return

    if args.report:
        show_report(args.video_id)
    elif args.audit:
        show_audit(args.video_id)
    elif args.findings:
        show_findings(args.video_id)
    elif args.purge:
        if not args.report_id:
            print("Error: --purge requires --report-id <id>")
            sys.exit(1)
        do_purge(args.video_id, args.report_id)
    else:
        # Default: run compliance check
        run_check(args.video_id, use_llm=args.llm)


if __name__ == "__main__":
    main()
