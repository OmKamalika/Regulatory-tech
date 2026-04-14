"""
LangGraph compliance agent for DPDPA video compliance checking.

Pipeline:
  load_video_data -> check_visual_rules -> check_ocr_rules -> check_audio_rules
  -> check_metadata_rules -> semantic_enrich -> synthesize_findings
  -> generate_report -> save_to_db

Phase 1 (sync, ~30s): All nodes up to save_to_db — produces structured findings.
Phase 2 (async, via Celery): LLM writes executive_summary after Phase 1 completes.
"""
import time
import uuid
from datetime import datetime, timezone
from typing import TypedDict, List
from langgraph.graph import StateGraph, END

from app.dpdpa.definitions import get_all_rules, get_rules_by_check_type
from app.common.patterns import detect_pii as _detect_pii_in_text, detect_gst as _detect_gst_in_text
# Prompt templates imported here for use in Phase 2 (LLM summary generation)
# Currently used by compliance_checker.py when use_llm=True
from app.langchain_components.prompts.compliance_prompts import (  # noqa: F401
    FINDING_DESCRIPTION_PROMPT,
    EXECUTIVE_SUMMARY_PROMPT,
)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class ComplianceState(TypedDict):
    video_id: str
    frames: List[dict]              # FrameAnalysis rows as dicts
    transcripts: List[dict]         # TranscriptionSegment rows as dicts
    visual_findings: List[dict]     # Findings from YOLO check
    ocr_findings: List[dict]        # Findings from OCR/PII check
    audio_findings: List[dict]      # Findings from audio check
    metadata_findings: List[dict]   # Findings from retention/metadata check
    all_findings: List[dict]        # Merged + deduplicated
    report_data: dict               # Computed score/status from generate_report
    report_id: str                  # Created at save step
    audit_entries: List[dict]       # Accumulated log entries
    errors: List[str]
    use_llm: bool                   # Whether to call Ollama for narrative (Phase 2)


def _make_audit_entry(step: str, action: str, input_data: dict = None,
                      output_data: dict = None, rule_id: str = None,
                      duration_ms: int = None, success: bool = True,
                      error: str = None) -> dict:
    return {
        "step": step,
        "action": action,
        "input_data": input_data or {},
        "output_data": output_data or {},
        "rule_id": rule_id,
        "timestamp": datetime.utcnow().isoformat(),
        "duration_ms": duration_ms,
        "success": success,
        "error_message": error,
    }


def _make_finding(rule, frame_data: dict = None, transcript_data: dict = None,
                  pii_found: List[dict] = None, check_type: str = "",
                  similarity_score: float = 1.0, source: str = "rule_match") -> dict:
    timestamp = frame_data.get("timestamp") if frame_data else (
        transcript_data.get("start_time") if transcript_data else None)
    frame_num = frame_data.get("frame_number") if frame_data else None
    objects = frame_data.get("objects_detected") if frame_data else []
    ocr_text = frame_data.get("ocr_text", "") if frame_data else ""
    pii_strs = [f"{p['type']}:REDACTED" for p in (pii_found or [])]

    return {
        "id": str(uuid.uuid4()),
        "rule_id": rule.rule_id,
        "rule_name": rule.name,
        "section_ref": rule.section_ref,
        "category": rule.category,
        "severity": rule.severity,
        "requirement_text": rule.requirement_text,
        "violation_condition": rule.violation_condition,
        "penalty_ref": rule.penalty_ref,
        "check_type": check_type,
        "frame_number": frame_num,
        "timestamp": timestamp,
        "objects_detected": objects or [],
        "pii_found": pii_strs,
        "ocr_text": ocr_text,
        "transcript_text": transcript_data.get("text", "") if transcript_data else "",
        "similarity_score": similarity_score,
        "source": source,
        "description": "",  # Filled by LLM in Phase 2 or template in Phase 1
        "recommendation": rule.detection_guidance,
    }


# ---------------------------------------------------------------------------
# Node 1: Load video data from PostgreSQL
# ---------------------------------------------------------------------------

def load_video_data(state: ComplianceState) -> ComplianceState:
    """Pull FrameAnalysis + TranscriptionSegment rows for the video."""
    t0 = time.time()
    video_id = state["video_id"]
    audit = list(state.get("audit_entries", []))
    errors = list(state.get("errors", []))
    frames = []
    transcripts = []

    try:
        from app.db.session import SessionLocal
        from app.models.frame_analysis import FrameAnalysis
        from app.models.transcription import TranscriptionSegment

        db = SessionLocal()
        try:
            frame_rows = db.query(FrameAnalysis).filter(
                FrameAnalysis.video_id == video_id
            ).order_by(FrameAnalysis.timestamp).all()

            for f in frame_rows:
                frames.append({
                    "id": f.id,
                    "frame_number": f.frame_number,
                    "timestamp": f.timestamp,
                    "minio_path": f.minio_path,
                    "objects_detected": f.objects_detected or [],
                    "faces_detected": f.faces_detected or 0,
                    "persons_detected": f.persons_detected or 0,
                    "ocr_text": f.ocr_text or "",
                    "weaviate_id": f.weaviate_id,
                })

            transcript_rows = db.query(TranscriptionSegment).filter(
                TranscriptionSegment.video_id == video_id
            ).order_by(TranscriptionSegment.start_time).all()

            for t in transcript_rows:
                transcripts.append({
                    "id": t.id,
                    "start_time": t.start_time,
                    "end_time": t.end_time,
                    "text": t.text,
                    "confidence": t.confidence,
                })
        finally:
            db.close()

    except Exception as e:
        errors.append(f"load_video_data error: {e}")

    duration_ms = int((time.time() - t0) * 1000)
    audit.append(_make_audit_entry(
        step="frame_fetch",
        action=f"Loaded {len(frames)} frames and {len(transcripts)} transcript segments for video {video_id}",
        input_data={"video_id": video_id},
        output_data={"frames_count": len(frames), "transcripts_count": len(transcripts)},
        duration_ms=duration_ms,
        success=len(errors) == 0,
    ))

    return {**state, "frames": frames, "transcripts": transcripts,
            "audit_entries": audit, "errors": errors}


# ---------------------------------------------------------------------------
# Node 2: Visual rules (YOLO detections -> check_types -> rules)
# ---------------------------------------------------------------------------

def check_visual_rules(state: ComplianceState) -> ComplianceState:
    """For each frame, map detected objects to check_types and find triggered rules."""
    t0 = time.time()
    audit = list(state.get("audit_entries", []))
    errors = list(state.get("errors", []))
    findings = []

    OBJECT_TO_CHECK_TYPE = {
        "person": "visual_person_detection",
        "face": "visual_face_detection",
        "child": "children_detection",
        "boy": "children_detection",
        "girl": "children_detection",
    }

    try:
        # Pre-fetch all visual rules once (avoids O(n*frames) rule iteration)
        all_visual_check_types = set(OBJECT_TO_CHECK_TYPE.values())
        visual_rules_by_check_type = {
            ct: get_rules_by_check_type(ct) for ct in all_visual_check_types
        }

        for frame in state.get("frames", []):
            objects = frame.get("objects_detected", [])
            if not objects:
                continue

            # Determine which check_types are triggered by detected objects
            triggered_check_types = set()
            object_labels = []
            for obj in objects:
                label = (obj.get("label") or obj.get("class") or "").lower()
                object_labels.append(label)
                if label in OBJECT_TO_CHECK_TYPE:
                    triggered_check_types.add(OBJECT_TO_CHECK_TYPE[label])

            # Also add face detection if faces_detected > 0
            if frame.get("faces_detected", 0) > 0:
                triggered_check_types.add("visual_face_detection")

            for check_type in triggered_check_types:
                rules = visual_rules_by_check_type.get(check_type, [])
                for rule in rules:
                    finding = _make_finding(
                        rule=rule,
                        frame_data=frame,
                        check_type=check_type,
                        source="visual_check",
                    )
                    findings.append(finding)

                    audit.append(_make_audit_entry(
                        step="visual_check",
                        action=f"Frame {frame['frame_number']} at {frame['timestamp']:.1f}s: {check_type} -> triggered rule {rule.rule_id}",
                        input_data={"frame_number": frame["frame_number"], "objects": object_labels, "check_type": check_type},
                        output_data={"rule_id": rule.rule_id, "severity": rule.severity},
                        rule_id=rule.rule_id,
                    ))

    except Exception as e:
        import traceback
        errors.append(f"VISUAL_CHECK_ERROR: {e}")
        audit.append(_make_audit_entry(
            step="visual_check",
            action=f"Visual rule check failed: {e}\n{traceback.format_exc()}",
            success=False,
            error=str(e),
        ))
        logger.error("check_visual_rules crashed: %s", e, exc_info=True)

    duration_ms = int((time.time() - t0) * 1000)
    audit.append(_make_audit_entry(
        step="visual_check",
        action=f"Visual rule check complete: {len(findings)} potential violations from {len(state.get('frames', []))} frames",
        output_data={"findings_count": len(findings)},
        duration_ms=duration_ms,
    ))

    return {**state, "visual_findings": findings, "audit_entries": audit, "errors": errors}


# ---------------------------------------------------------------------------
# Node 3: OCR rules (PII in frame text -> rules)
# ---------------------------------------------------------------------------

def check_ocr_rules(state: ComplianceState) -> ComplianceState:
    """For each frame with OCR text, scan for PII and map to rules."""
    t0 = time.time()
    audit = list(state.get("audit_entries", []))
    errors = list(state.get("errors", []))
    findings = []

    frames = state.get("frames", [])

    # Detect if OCR was non-functional during pipeline processing.
    # If ALL frames have empty ocr_text, OCR could not read anything — this is a
    # data quality failure, not a clean bill of health.
    frames_with_text = sum(1 for f in frames if f.get("ocr_text", "").strip())
    ocr_was_blind = len(frames) > 0 and frames_with_text == 0
    # Partial OCR failure: engine initialized but could only read <10% of frames.
    # Not fully blind, but coverage is too low to trust the result.
    ocr_partially_blind = (
        not ocr_was_blind
        and len(frames) >= 10
        and frames_with_text / len(frames) < 0.10
    )

    if ocr_was_blind:
        warning_msg = (
            "OCR_WARNING: OCR engine could not read text from any video frame during processing. "
            "Visual PII (phone numbers, email addresses, Aadhaar/PAN numbers visible on screen) "
            "was NOT checked. Compliance status for on-screen text is UNVERIFIED. "
            "Re-process the video with EasyOCR or Tesseract installed to enable visual PII detection."
        )
        errors.append(warning_msg)
        audit.append(_make_audit_entry(
            step="ocr_check",
            action=warning_msg,
            output_data={"frames_checked": len(frames), "frames_with_text": 0},
            success=False,
            error="OCR engine non-functional — visual PII unverified",
        ))
    elif ocr_partially_blind:
        pct = int(100 * frames_with_text / len(frames))
        warning_msg = (
            f"OCR_WARNING: OCR engine only read text from {frames_with_text}/{len(frames)} frames ({pct}%). "
            "Low OCR coverage means most on-screen PII (phone numbers, PAN, Aadhaar) may be undetected. "
            "Re-process the video with EasyOCR fully initialised for reliable compliance coverage."
        )
        errors.append(warning_msg)
        audit.append(_make_audit_entry(
            step="ocr_check",
            action=warning_msg,
            output_data={"frames_checked": len(frames), "frames_with_text": frames_with_text, "coverage_pct": pct},
            success=False,
            error=f"Low OCR coverage ({pct}%) — PII detection unreliable",
        ))
    if not ocr_was_blind:
        pii_rules = get_rules_by_check_type("ocr_pii_detection")
        ocr_text_rules = get_rules_by_check_type("ocr_text_detection")
        gst_rules = get_rules_by_check_type("gst_detection")

        for frame in frames:
            ocr_text = frame.get("ocr_text", "")
            if not ocr_text or not ocr_text.strip():
                continue

            # --- PII detection (personal data under DPDPA) ---
            pii_found = _detect_pii_in_text(ocr_text)
            if pii_found:
                for rule in pii_rules:
                    findings.append(_make_finding(
                        rule=rule,
                        frame_data=frame,
                        pii_found=pii_found,
                        check_type="ocr_pii_detection",
                        source="ocr_check",
                    ))
                    audit.append(_make_audit_entry(
                        step="ocr_check",
                        action=f"Frame {frame['frame_number']} at {frame['timestamp']:.1f}s: PII found in OCR text -> triggered rule {rule.rule_id}",
                        input_data={"frame_number": frame["frame_number"], "pii_types": [p["type"] for p in pii_found]},
                        output_data={"rule_id": rule.rule_id, "pii_count": len(pii_found)},
                        rule_id=rule.rule_id,
                    ))

                # OCR text present (non-PII check) -> ocr_text_detection
                for rule in ocr_text_rules:
                    findings.append(_make_finding(
                        rule=rule,
                        frame_data=frame,
                        pii_found=pii_found,
                        check_type="ocr_text_detection",
                        source="ocr_check",
                    ))

            # --- GST detection (business identifier, separate rule DPDPA-VID-005) ---
            gst_matches = _detect_gst_in_text(ocr_text)
            if gst_matches and gst_rules:
                for rule in gst_rules:
                    findings.append(_make_finding(
                        rule=rule,
                        frame_data=frame,
                        pii_found=[{"type": "gst", "redacted": True} for _ in gst_matches],
                        check_type="gst_detection",
                        source="ocr_check",
                    ))
                    audit.append(_make_audit_entry(
                        step="ocr_check",
                        action=f"Frame {frame['frame_number']} at {frame['timestamp']:.1f}s: {len(gst_matches)} GST number(s) detected -> triggered rule {rule.rule_id}",
                        input_data={"frame_number": frame["frame_number"], "gst_count": len(gst_matches)},
                        output_data={"rule_id": rule.rule_id, "severity": rule.severity},
                        rule_id=rule.rule_id,
                    ))

    duration_ms = int((time.time() - t0) * 1000)
    audit.append(_make_audit_entry(
        step="ocr_check",
        action=f"OCR rule check complete: {len(findings)} potential violations ({frames_with_text}/{len(frames)} frames had readable text)",
        output_data={"findings_count": len(findings), "frames_with_text": frames_with_text, "ocr_was_blind": ocr_was_blind},
        duration_ms=duration_ms,
    ))

    return {**state, "ocr_findings": findings, "audit_entries": audit, "errors": errors}


# ---------------------------------------------------------------------------
# Node 4: Audio rules (transcript PII -> rules)
# ---------------------------------------------------------------------------

def check_audio_rules(state: ComplianceState) -> ComplianceState:
    """Scan transcription segments for PII and map to audio rules."""
    t0 = time.time()
    audit = list(state.get("audit_entries", []))
    errors = list(state.get("errors", []))
    findings = []
    skipped = 0

    for segment in state.get("transcripts", []):
        try:
            text = segment.get("text", "")
            if not text:
                skipped += 1
                continue

            pii_found = _detect_pii_in_text(text)
            if not pii_found:
                continue

            rules = get_rules_by_check_type("audio_pii_detection")
            for rule in rules:
                finding = _make_finding(
                    rule=rule,
                    transcript_data=segment,
                    pii_found=pii_found,
                    check_type="audio_pii_detection",
                    source="audio_check",
                )
                findings.append(finding)

                audit.append(_make_audit_entry(
                    step="audio_check",
                    action=f"Audio at {segment['start_time']:.1f}s-{segment['end_time']:.1f}s: PII found in transcript -> triggered rule {rule.rule_id}",
                    input_data={"start_time": segment["start_time"], "pii_types": [p["type"] for p in pii_found]},
                    output_data={"rule_id": rule.rule_id},
                    rule_id=rule.rule_id,
                ))
        except Exception as e:
            errors.append(f"AUDIO_SEGMENT_ERROR: {e}")
            logger.warning("check_audio_rules: error on segment: %s", e, exc_info=True)

    if skipped:
        logger.debug("check_audio_rules: %d segments skipped (empty text)", skipped)

    duration_ms = int((time.time() - t0) * 1000)
    audit.append(_make_audit_entry(
        step="audio_check",
        action=f"Audio rule check complete: {len(findings)} potential violations from {len(state.get('transcripts', []))} segments ({skipped} empty skipped)",
        output_data={"findings_count": len(findings), "skipped": skipped},
        duration_ms=duration_ms,
    ))

    return {**state, "audio_findings": findings, "audit_entries": audit, "errors": errors}


# ---------------------------------------------------------------------------
# Node 5: Metadata rules (data retention, consent indicators)
# ---------------------------------------------------------------------------

def check_metadata_rules(state: ComplianceState) -> ComplianceState:
    """Check video-level metadata: retention period, consent banners."""
    t0 = time.time()
    audit = list(state.get("audit_entries", []))
    findings = []

    try:
        from app.db.session import SessionLocal
        from app.models.video import Video

        db = SessionLocal()
        try:
            video = db.query(Video).filter(Video.id == state["video_id"]).first()
            if video:
                # Check data retention — DPDPA requires CCTV max 90 days
                if hasattr(video, "created_at") and video.created_at:
                    age_days = (datetime.now(timezone.utc) - video.created_at).days
                    if age_days > 90:
                        rules = get_rules_by_check_type("data_retention")
                        for rule in rules:
                            finding = _make_finding(
                                rule=rule,
                                check_type="data_retention",
                                source="metadata_check",
                            )
                            finding["description"] = (
                                f"Video is {age_days} days old, exceeding the 90-day CCTV retention limit."
                            )
                            findings.append(finding)
                            audit.append(_make_audit_entry(
                                step="rule_match",
                                action=f"Video age {age_days} days exceeds 90-day CCTV retention limit -> triggered rule {rule.rule_id}",
                                input_data={"video_age_days": age_days},
                                output_data={"rule_id": rule.rule_id},
                                rule_id=rule.rule_id,
                            ))
        finally:
            db.close()
    except Exception as e:
        audit.append(_make_audit_entry(
            step="rule_match",
            action=f"Metadata check failed: {e}",
            success=False,
            error=str(e),
        ))

    duration_ms = int((time.time() - t0) * 1000)
    audit.append(_make_audit_entry(
        step="finding_created",
        action=f"Metadata rule check complete: {len(findings)} potential violations",
        output_data={"findings_count": len(findings)},
        duration_ms=duration_ms,
    ))

    return {**state, "metadata_findings": findings, "audit_entries": audit}


# ---------------------------------------------------------------------------
# Node 6: Semantic enrichment (Weaviate Guidelines search)
# ---------------------------------------------------------------------------

def semantic_enrich(state: ComplianceState) -> ComplianceState:
    """
    Semantic search Weaviate Guidelines for any rules not caught by check_type mapping.
    Uses frame descriptions as query text to find additional relevant rules.
    """
    t0 = time.time()
    audit = list(state.get("audit_entries", []))
    errors = list(state.get("errors", []))
    extra_findings = []

    # Build a set of rule_ids already found to avoid duplicates
    existing_rule_ids = set()
    for f in (state.get("visual_findings", []) + state.get("ocr_findings", []) +
              state.get("audio_findings", []) + state.get("metadata_findings", [])):
        existing_rule_ids.add(f["rule_id"])

    try:
        from app.services.vector_store import VectorStore
        from app.services.embedding_service import EmbeddingService
        from app.dpdpa.definitions import get_all_rules

        vs = VectorStore()
        embedding_service = EmbeddingService()
        all_rules = {r.rule_id: r for r in get_all_rules()}

        # Query with descriptions of high-risk frames (persons + OCR found)
        query_frames = [
            f for f in state.get("frames", [])
            if f.get("persons_detected", 0) > 0 or f.get("ocr_text", "").strip()
        ][:5]  # limit to top 5 frames

        for frame in query_frames:
            objects = frame.get("objects_detected", [])
            obj_labels = [o.get("class", o.get("label", "")) for o in objects if isinstance(o, dict)]
            query_text = (
                f"Person detected in video frame at {frame['timestamp']:.1f}s. "
                f"Objects: {', '.join(obj_labels)}. OCR text: {frame.get('ocr_text', '')[:200]}"
            )

            query_embedding = embedding_service.embed(query_text)
            results = vs.search_guidelines(query_embedding, limit=5)
            for result in results:
                # SearchResult has .metadata dict with "guideline_id" = DPDPA rule_id
                rule_id = result.metadata.get("guideline_id", "")
                if not rule_id or rule_id in existing_rule_ids:
                    continue

                rule = all_rules.get(rule_id)
                if not rule:
                    continue

                existing_rule_ids.add(rule_id)
                similarity = result.score  # SearchResult.score is similarity (1 - distance)
                if similarity < 0.6:
                    continue

                finding = _make_finding(
                    rule=rule,
                    frame_data=frame,
                    check_type="semantic_match",
                    similarity_score=similarity,
                    source="semantic_enrich",
                )
                extra_findings.append(finding)

                audit.append(_make_audit_entry(
                    step="rule_match",
                    action=f"Semantic search: frame {frame['frame_number']} -> rule {rule_id} (similarity={similarity:.3f})",
                    input_data={"query": query_text[:100]},
                    output_data={"rule_id": rule_id, "similarity": round(similarity, 4)},
                    rule_id=rule_id,
                ))

    except Exception as e:
        errors.append(f"SEMANTIC_ERROR: {e}")
        audit.append(_make_audit_entry(
            step="rule_match",
            action=f"Semantic enrichment failed: {e}",
            success=False,
            error=str(e),
        ))
        logger.warning("semantic_enrich failed: %s", e, exc_info=True)

    duration_ms = int((time.time() - t0) * 1000)
    audit.append(_make_audit_entry(
        step="rule_match",
        action=f"Semantic enrichment complete: {len(extra_findings)} additional rules found",
        output_data={"extra_findings": len(extra_findings)},
        duration_ms=duration_ms,
    ))

    # Merge extra findings into the appropriate list
    return {**state, "visual_findings": state.get("visual_findings", []) + extra_findings,
            "audit_entries": audit, "errors": errors}


# ---------------------------------------------------------------------------
# Node 7: Synthesize findings (deduplicate + score)
# ---------------------------------------------------------------------------

def synthesize_findings(state: ComplianceState) -> ComplianceState:
    """Merge all findings, deduplicate by rule_id+frame, assign confidence scores."""
    t0 = time.time()
    audit = list(state.get("audit_entries", []))

    all_raw = (
        state.get("visual_findings", []) +
        state.get("ocr_findings", []) +
        state.get("audio_findings", []) +
        state.get("metadata_findings", [])
    )

    # Deduplicate: same rule_id + same frame = one finding (keep highest similarity)
    seen = {}
    for f in all_raw:
        key = (f["rule_id"], f.get("frame_number"), f.get("source"))
        if key not in seen or f.get("similarity_score", 0) > seen[key].get("similarity_score", 0):
            seen[key] = f

    deduplicated = list(seen.values())

    # Sort by severity then timestamp
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    deduplicated.sort(key=lambda x: (
        severity_order.get(x.get("severity", "info"), 2),
        x.get("timestamp") or 0
    ))

    duration_ms = int((time.time() - t0) * 1000)
    audit.append(_make_audit_entry(
        step="finding_created",
        action=f"Synthesized {len(all_raw)} raw findings -> {len(deduplicated)} unique findings after deduplication",
        output_data={"raw": len(all_raw), "unique": len(deduplicated)},
        duration_ms=duration_ms,
    ))

    return {**state, "all_findings": deduplicated, "audit_entries": audit}


# ---------------------------------------------------------------------------
# Node 8: Generate report (Phase 1 — structured, no LLM)
# ---------------------------------------------------------------------------

def generate_report(state: ComplianceState) -> ComplianceState:
    """
    Phase 1: Compute compliance score and status from structured findings.
    LLM narrative summary (Phase 2) runs asynchronously via Celery after this.
    """
    t0 = time.time()
    audit = list(state.get("audit_entries", []))
    errors = list(state.get("errors", []))
    findings = state.get("all_findings", [])

    try:
        all_rules = get_all_rules()
    except Exception as e:
        errors.append(f"REPORT_ERROR: could not load rules: {e}")
        logger.error("generate_report: get_all_rules() failed: %s", e, exc_info=True)
        all_rules = []
    total_checks = len(all_rules)

    # Count UNIQUE rules violated per severity (not total findings)
    # e.g. phone number in 30 frames = 1 critical rule = -5 pts, not -150
    violated_rule_ids = set(f["rule_id"] for f in findings)
    failed_checks = len(violated_rule_ids)
    passed_checks = total_checks - failed_checks

    severity_by_rule = {}
    for f in findings:
        rule_id = f["rule_id"]
        # Most severe finding wins if same rule appears multiple times
        existing = severity_by_rule.get(rule_id, "info")
        sev = f.get("severity", "info")
        if sev == "critical" or (sev == "warning" and existing == "info"):
            severity_by_rule[rule_id] = sev

    critical_violations = sum(1 for s in severity_by_rule.values() if s == "critical")
    warnings = sum(1 for s in severity_by_rule.values() if s == "warning")
    info_violations = sum(1 for s in severity_by_rule.values() if s == "info")

    # Score: each unique violated rule deducts points based on its severity
    # critical rule = -5, warning rule = -2, info rule = -1
    penalty = (critical_violations * 5) + (warnings * 2) + info_violations
    compliance_score = max(0.0, 100.0 - penalty)

    if failed_checks == 0:
        status = "compliant"
    elif critical_violations > 0:
        status = "non_compliant"
    elif warnings > 0:
        status = "partial"
    else:
        status = "compliant"

    # Detect stage failures — any failure forces score to 0 and status to "incomplete".
    # Relying on partial data would give a misleading compliance result.
    all_errors = state.get("errors", [])
    ocr_failed = any("OCR_WARNING" in e for e in all_errors)
    visual_failed = any("VISUAL_CHECK_ERROR" in e for e in all_errors)
    no_frames = len(state.get("frames", [])) == 0

    stage_failure = ocr_failed or visual_failed or no_frames

    limitations = []
    if stage_failure:
        compliance_score = 0.0
        status = "incomplete"
        passed_checks = 0
        if no_frames:
            limitations.append(
                "STAGE FAILURE — Frame extraction produced no frames. "
                "The video could not be processed. Check FFmpeg installation and re-upload."
            )
        if ocr_failed:
            limitations.append(
                "STAGE FAILURE — OCR engine could not read text from video frames. "
                "On-screen PII (Aadhaar, PAN, phone numbers) was not checked. "
                "Install Tesseract or EasyOCR and re-process with force=true."
            )
        if visual_failed:
            limitations.append(
                "STAGE FAILURE — Visual object detection (YOLO) encountered an error. "
                "Person and display-device detection did not complete. "
                "Verify the YOLO model file path in settings and re-process."
            )

    report_data = {
        "total_checks": total_checks,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "critical_violations": critical_violations,
        "warnings": warnings,
        "compliance_score": compliance_score,
        "status": status,
        "ocr_verified": not ocr_failed,
        "stage_failure": stage_failure,
        "limitations": limitations,
    }

    duration_ms = int((time.time() - t0) * 1000)
    audit.append(_make_audit_entry(
        step="report_generated",
        action=f"Report generated: score={compliance_score:.1f}, status={status}, violations={failed_checks}" +
               (" [STAGE FAILURE — score forced to 0]" if stage_failure else ""),
        output_data=report_data,
        duration_ms=duration_ms,
    ))

    return {**state, "report_data": report_data, "audit_entries": audit, "errors": errors}


# ---------------------------------------------------------------------------
# Node 9: Save to DB
# ---------------------------------------------------------------------------

def save_to_db(state: ComplianceState) -> ComplianceState:
    """Write ComplianceReport, ComplianceFinding, and AuditLog rows to PostgreSQL."""
    t0 = time.time()
    audit = list(state.get("audit_entries", []))
    errors = list(state.get("errors", []))
    report_id = None

    try:
        from app.db.session import SessionLocal
        from app.models.compliance_report import ComplianceReport, ComplianceFinding, ComplianceStatus
        from app.models.guideline import Guideline
        from app.models.audit_log import AuditLog, AuditStep

        db = SessionLocal()
        try:
            report_data = state.get("report_data", {})

            # Create or update ComplianceReport
            existing_report_id = state.get("report_id")
            if existing_report_id:
                report = db.query(ComplianceReport).filter(
                    ComplianceReport.id == existing_report_id
                ).first()
            else:
                report = None

            if not report:
                report = ComplianceReport(
                    id=existing_report_id or str(uuid.uuid4()),
                    video_id=state["video_id"],
                )
                db.add(report)

            status_map = {
                "compliant": ComplianceStatus.COMPLIANT,
                "non_compliant": ComplianceStatus.NON_COMPLIANT,
                "partial": ComplianceStatus.PARTIAL,
                "incomplete": ComplianceStatus.PENDING_REVIEW,  # stage failure — not enough data
            }
            report.status = status_map.get(report_data.get("status", ""), ComplianceStatus.PENDING_REVIEW)
            report.compliance_score = report_data.get("compliance_score")
            report.total_checks = report_data.get("total_checks", 0)
            report.passed_checks = report_data.get("passed_checks", 0)
            report.failed_checks = report_data.get("failed_checks", 0)
            report.critical_violations = report_data.get("critical_violations", 0)
            report.warnings = report_data.get("warnings", 0)
            report.completed_at = datetime.utcnow()
            report.executive_summary = "Compliance check complete. LLM narrative summary generating in background."
            report.recommendations = report_data.get("limitations") or []
            db.flush()
            report_id = report.id

            # Pre-fetch all needed guidelines in one query (avoids N+1)
            all_findings_list = state.get("all_findings", [])
            rule_ids_needed = {f["rule_id"] for f in all_findings_list}
            guidelines_by_rule_id = {
                g.name: g
                for g in db.query(Guideline).filter(Guideline.name.in_(rule_ids_needed)).all()
            }

            # Write ComplianceFinding rows
            severity_map = {"critical": "critical", "warning": "warning", "info": "info"}
            for finding in all_findings_list:
                guideline = guidelines_by_rule_id.get(finding["rule_id"])

                if not guideline:
                    logger.warning(
                        "save_to_db: guideline '%s' not found in PostgreSQL — finding dropped. "
                        "Run POST /api/v1/compliance/guidelines/reload to sync rules.",
                        finding["rule_id"],
                    )
                    errors.append(f"GUIDELINE_MISSING: {finding['rule_id']} not in DB — finding not saved")
                    continue

                db_finding = ComplianceFinding(
                    report_id=report_id,
                    guideline_id=guideline.id,
                    is_violation=True,
                    severity=severity_map.get(finding.get("severity", "info"), "info"),
                    description=finding.get("description") or (
                        f"{finding['rule_name']}: {finding['violation_condition']}"
                    ),
                    recommendation=finding.get("recommendation", ""),
                    timestamp_start=finding.get("timestamp"),
                    timestamp_end=finding.get("timestamp"),
                    ocr_text_excerpt=finding.get("ocr_text", "")[:500] if finding.get("ocr_text") else None,
                    transcript_excerpt=finding.get("transcript_text", "")[:500] if finding.get("transcript_text") else None,
                    visual_evidence={
                        "rule_id": finding["rule_id"],
                        "check_type": finding.get("check_type"),
                        "objects_detected": finding.get("objects_detected", []),
                        "pii_found": finding.get("pii_found", []),
                        "frame_number": finding.get("frame_number"),
                        "similarity_score": finding.get("similarity_score"),
                        "source": finding.get("source"),
                    },
                    confidence_score=finding.get("similarity_score"),
                )
                db.add(db_finding)

            # Write AuditLog rows
            step_enum_map = {
                "frame_fetch": AuditStep.FRAME_FETCH,
                "visual_check": AuditStep.VISUAL_CHECK,
                "ocr_check": AuditStep.OCR_CHECK,
                "audio_check": AuditStep.AUDIO_CHECK,
                "rule_match": AuditStep.RULE_MATCH,
                "finding_created": AuditStep.FINDING_CREATED,
                "report_generated": AuditStep.REPORT_GENERATED,
                "data_purged": AuditStep.DATA_PURGED,
            }

            for entry in audit:
                step_val = step_enum_map.get(entry.get("step"), AuditStep.VISUAL_CHECK)
                ts = entry.get("timestamp")
                ts_dt = datetime.fromisoformat(ts) if isinstance(ts, str) else datetime.utcnow()
                log = AuditLog(
                    video_id=state["video_id"],
                    report_id=report_id,
                    step=step_val,
                    action=entry.get("action", "")[:1000],
                    input_data=entry.get("input_data"),
                    output_data=entry.get("output_data"),
                    rule_id=entry.get("rule_id"),
                    timestamp=ts_dt,
                    duration_ms=entry.get("duration_ms"),
                    success=entry.get("success", True),
                    error_message=entry.get("error_message"),
                )
                db.add(log)

            db.commit()

        finally:
            db.close()

    except Exception as e:
        errors.append(f"save_to_db error: {e}")
        audit.append(_make_audit_entry(
            step="report_generated",
            action=f"Failed to save to database: {e}",
            success=False,
            error=str(e),
        ))

    return {**state, "report_id": report_id, "audit_entries": audit, "errors": errors}


# ---------------------------------------------------------------------------
# Build the LangGraph state machine
# ---------------------------------------------------------------------------

def build_compliance_graph():
    """Construct and compile the LangGraph compliance agent."""
    graph = StateGraph(ComplianceState)

    graph.add_node("load_video_data", load_video_data)
    graph.add_node("check_visual_rules", check_visual_rules)
    graph.add_node("check_ocr_rules", check_ocr_rules)
    graph.add_node("check_audio_rules", check_audio_rules)
    graph.add_node("check_metadata_rules", check_metadata_rules)
    graph.add_node("semantic_enrich", semantic_enrich)
    graph.add_node("synthesize_findings", synthesize_findings)
    graph.add_node("generate_report", generate_report)
    graph.add_node("save_to_db", save_to_db)

    graph.set_entry_point("load_video_data")
    graph.add_edge("load_video_data", "check_visual_rules")
    graph.add_edge("check_visual_rules", "check_ocr_rules")
    graph.add_edge("check_ocr_rules", "check_audio_rules")
    graph.add_edge("check_audio_rules", "check_metadata_rules")
    graph.add_edge("check_metadata_rules", "semantic_enrich")
    graph.add_edge("semantic_enrich", "synthesize_findings")
    graph.add_edge("synthesize_findings", "generate_report")
    graph.add_edge("generate_report", "save_to_db")
    graph.add_edge("save_to_db", END)

    return graph.compile()


# Singleton compiled graph
_compliance_graph = None


def get_compliance_graph():
    global _compliance_graph
    if _compliance_graph is None:
        _compliance_graph = build_compliance_graph()
    return _compliance_graph


def run_compliance_check(video_id: str, report_id: str = None, use_llm: bool = False) -> dict:
    """
    Run the full compliance pipeline for a video.

    Args:
        video_id: The video to check
        report_id: Pre-created report ID (optional — created in save_to_db if not given)
        use_llm: Whether to call Ollama for Phase 2 narrative (default False for speed)

    Returns:
        Final ComplianceState dict
    """
    initial_state: ComplianceState = {
        "video_id": video_id,
        "frames": [],
        "transcripts": [],
        "visual_findings": [],
        "ocr_findings": [],
        "audio_findings": [],
        "metadata_findings": [],
        "all_findings": [],
        "report_data": {},
        "report_id": report_id or "",
        "audit_entries": [],
        "errors": [],
        "use_llm": use_llm,
    }

    graph = get_compliance_graph()
    final_state = graph.invoke(initial_state)
    return final_state
