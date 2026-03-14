# Product Requirements Document
**Type:** API / Backend Service
**Author:** Regtech Engineering
**Version:** 1.0 — Live Implementation
**Last Updated:** 2026-03-14
**Status:** 🟢 Operational

---

## 1. Overview

A RESTful API and async pipeline that automatically extracts, vectorizes, and DPDPA-checks video recordings — flagging PII violations, unmasked personal data, and data-retention breaches — and returns a structured compliance report with evidence, audit trail, and penalty references.

---

## 2. Business Use Case

### Context
Organizations that record video (CCTV, screen recordings, customer interactions) must comply with India's Digital Personal Data Protection Act 2023 (DPDPA). Manual review of video footage for PII violations is slow, error-prone, and unscalable. This API automates that compliance review pipeline.

### Target Users
| User Type | Description | Primary Need |
|-----------|-------------|--------------|
| Compliance Officer | Reviews reports for regulatory submissions | Accurate violation findings with evidence timestamps and penalty exposure |
| Data Protection Officer (DPO) | Oversees DPDPA programme | Audit trail proving due diligence on every video processed |
| Developer / Integrator | Connects recording systems to compliance pipeline | Simple REST API: submit path → poll status → fetch report |

### Value Proposition
- **Before:** Manual review of hours of video footage, no systematic PII detection, compliance posture unknown
- **After:** Automated pipeline processes a video in ~2–4 minutes and returns a DPDPA compliance report with frame-level evidence, penalty exposure, and audit log

### Success Metrics
| Metric | Target | How to Measure |
|--------|--------|----------------|
| Processing time per video | < 5 min for typical MP4 | Celery task duration log |
| PII detection accuracy | Flags visible phone numbers, Aadhaar, PAN, email | Manual spot-check on test videos |
| False-positive rate | < 10% | Review compliance_findings with violations_only |
| Audit completeness | 100% of pipeline steps logged | audit_logs row count per report |

---

## 3. Problem Statement & Goals

### Problem
Video recordings often contain visible or audible personal data (phone numbers, Aadhaar cards, PAN cards, email addresses, faces) that violates DPDPA data minimisation and consent requirements. Without automated tooling, organisations cannot consistently detect these violations across large volumes of footage before they become regulatory liabilities.

### Goals
- [x] Accept a video file path and trigger a fully automated compliance pipeline
- [x] Extract frames, detect objects (YOLO), read on-screen text (EasyOCR), and transcribe audio (Whisper)
- [x] Store all content as semantic embeddings in Weaviate for rule matching
- [x] Run 36 DPDPA rules across visual, OCR, audio, metadata, and semantic dimensions
- [x] Produce a structured compliance report with score, findings, evidence, and audit trail
- [x] Report honestly when a check could not be completed (no silent false-compliant results)

### Non-Goals (Out of Scope)
- UI / dashboard (API only)
- Real-time video streaming analysis
- Multi-tenancy / org-level access control (single-tenant prototype)
- LLM narrative summary (Phase 2 — wired but not enabled by default)
- Cloud storage of video files (local path only in current implementation)

---

## 4. System Pipeline — 3 Steps

### Step 1 — Video Content Vectorization

Triggered on upload. Converts raw video into searchable vector embeddings in Weaviate + structured rows in PostgreSQL.

| Sub-step | Action | Library |
|----------|--------|---------|
| 1.1 Frame extraction | Extract keyframes at configured FPS using scene-change detection | `OpenCV (cv2)`, `ffmpeg-python`, `PySceneDetect` |
| 1.2 FFmpeg verification | Confirm FFmpeg binary on PATH at task startup | `subprocess`, FFmpeg binary |
| 1.3 Audio check | Probe video for audio stream before attempting extraction | `ffmpeg-python` (`ffmpeg.probe`) |
| 1.4 Audio extraction | Extract mono 16kHz WAV if audio track present; returns `None` silently if video-only | `ffmpeg-python` |
| 1.5 Transcription | Transcribe audio to timestamped segments | `openai-whisper` (local, open-source) |
| 1.6 Visual object detection | Run YOLO v8 on each frame → detect persons, faces, devices | `ultralytics` (YOLOv8) |
| 1.7 OCR text reading | Read on-screen text from each frame | `easyocr` (primary), `pytesseract` (fallback), OpenCV region detection (last resort) |
| 1.8 Embedding generation | Convert frame descriptions + transcription segments to vectors | `sentence-transformers` (`all-mpnet-base-v2`, 768-dim) |
| 1.9 Vector storage | Batch-insert embeddings into Weaviate `VideoContent` collection | `weaviate-client` 4.x (gRPC) |
| 1.10 PostgreSQL persistence | Store `FrameAnalysis` + `TranscriptionSegment` rows with OCR text, object detections, persons count | `SQLAlchemy` 2.x + `psycopg2` |

**Output:** `frames_processed`, `transcription_segments`, `embeddings_created` counts. OCR engine logged clearly; fallback triggers warning.

---

### Step 2 — DPDPA Rule Definitions

Pre-loaded into PostgreSQL and Weaviate. No per-video processing — rules are static.

| Sub-step | Action | Library / Format |
|----------|--------|-----------------|
| 2.1 Rule definitions | 36 rules defined as `DPDPARule` dataclasses | Python dataclasses (`app/dpdpa/definitions.py`) |
| 2.2 Guideline loader | Load rules into `guidelines` PostgreSQL table + `Guidelines` Weaviate collection | `SQLAlchemy`, `weaviate-client` |
| 2.3 Semantic embedding | Embed `requirement_text` of each rule for semantic search | `sentence-transformers` |

**Rule inventory:**
| Category | Rule Count |
|----------|------------|
| Consent | 7 |
| Data Principal Rights | 5 |
| Data Fiduciary Obligations | 5 |
| Video / PII Specific | 4 |
| Children Data | 3 |
| Data Retention | 3 |
| SDF (Significant Data Fiduciary) | 3 |
| Breach Notification | 2 |
| Cross-Border Transfer | 2 |
| Purpose Limitation | 2 |
| **Total** | **36** |

---

### Step 3 — LangGraph Compliance Agent

A 9-node LangGraph state machine that runs against the stored frame/transcript data and produces the compliance report.

| Node | Action | What It Checks |
|------|--------|----------------|
| 1. `load_video_data` | Fetch `FrameAnalysis` + `TranscriptionSegment` rows from PostgreSQL | — |
| 2. `check_visual_rules` | Map YOLO-detected objects to DPDPA check types → find triggered rules | Persons, faces, children (`visual_person_detection`, `visual_face_detection`, `children_detection`) |
| 3. `check_ocr_rules` | Scan OCR text from each frame using PII regex patterns → find triggered rules | Phone numbers, email, Aadhaar, PAN, credit cards, IP address, DOB, URL (`ocr_pii_detection`, `ocr_text_detection`) |
| 4. `check_audio_rules` | Scan transcription segments with same PII regex → find triggered rules | Spoken PII (`audio_pii_detection`) |
| 5. `check_metadata_rules` | Check video creation date vs. 90-day CCTV retention limit | Data retention (`data_retention`) |
| 6. `semantic_enrich` | Query Weaviate Guidelines with high-risk frame descriptions → catch rules not in check_type map | Any rule with similarity ≥ 0.6 to frame content |
| 7. `synthesize_findings` | Deduplicate by (rule_id + frame + source), sort by severity then timestamp | — |
| 8. `generate_report` | Compute score, status, counts; apply OCR-blind override if needed | — |
| 9. `save_to_db` | Write `ComplianceReport`, `ComplianceFinding`, `AuditLog` rows | — |

**PII Patterns (regex):**
| Pattern Name | Matches |
|---|---|
| `phone_india` | `+91` format mobile numbers |
| `phone_10` | 10-digit Indian mobile (starts 6–9) |
| `phone_intl` | International format `+CC XXXXXXXX` |
| `email` | Standard email addresses |
| `aadhaar` | `XXXX XXXX XXXX` format |
| `pan` | `AAAAA9999A` format |
| `credit_card` | 16-digit card numbers |
| `ip_address` | IPv4 addresses |
| `dob` | DD/MM/YYYY date patterns |
| `url` | `http(s)://` URLs |
| `gst` | GST registration number (15-char, e.g. `27AAPFU0939F1ZV`) |

---

## 5. Video Upload Flow

```
POST /api/v1/videos/upload  {"video_path": "/path/to/file.mp4"}
          │
          ▼
   Validate file exists + format allowed (mp4, avi, mov, mkv, webm)
          │
          ▼
   Create Video row in PostgreSQL (status: UPLOADED)
          │
          ▼
   Queue Celery task: process_video_task(video_id, video_path)
          │
          ▼
   Return {video_id, task_id, status: "queued"}
          │
          ▼ (async, Celery worker)
   Mark Video status: PROCESSING
          │
          ├── Step 1: VideoContentVectorizer.process_video()
          │        → Frames, OCR, Audio, Embeddings → Weaviate + PostgreSQL
          │
          ├── Update Video: visual_analysis_completed, ocr_completed, vectorization_completed = True
          │
          ├── Step 3: check_video_compliance()
          │        → LangGraph 9-node pipeline → ComplianceReport + Findings + AuditLog
          │
          └── Mark Video status: COMPLETED (or FAILED on exception)
                   → Print ✅ PIPELINE COMPLETE banner in worker terminal
```

**Poll for status:**
```
GET /api/v1/videos/{video_id}/status
→ Returns processing flags + compliance summary when COMPLETED
```

---

## 6. Compliance Report — Format & Scoring

### Report Output Structure

```json
{
  "report_id": "uuid",
  "video_id": "uuid",
  "status": "compliant | non_compliant | partial",
  "compliance_score": 87.0,
  "total_checks": 36,
  "passed_checks": 34,
  "failed_checks": 2,
  "critical_violations": 0,
  "warnings": 2,
  "ocr_verified": true,
  "limitations": [],
  "executive_summary": "...",
  "recommendations": ["..."],
  "created_at": "ISO timestamp",
  "completed_at": "ISO timestamp",
  "findings": [
    {
      "id": "uuid",
      "guideline_id": "uuid",
      "is_violation": true,
      "severity": "warning",
      "description": "Phone number detected in frame at 12.3s",
      "recommendation": "Mask or blur phone numbers before recording",
      "timestamp_start": 12.3,
      "timestamp_end": 12.3,
      "ocr_text_excerpt": "9876543210",
      "transcript_excerpt": null,
      "visual_evidence": {
        "rule_id": "DPDPA-S4-002",
        "check_type": "ocr_pii_detection",
        "objects_detected": ["person", "cell phone"],
        "pii_found": ["phone_10:9876543210"],
        "frame_number": 74,
        "similarity_score": 1.0,
        "source": "ocr_check"
      },
      "confidence_score": 1.0
    }
  ]
}
```

### Scoring Rules

| Component | Weight |
|-----------|--------|
| Each critical violation | −5 points |
| Each warning violation | −2 points |
| Each info violation | −1 point |

```
penalty = (critical_count × 5) + (warning_count × 2) + (info_count × 1)
compliance_score = max(0.0, 100.0 - penalty)
```

### Status Determination

| Condition | Status |
|-----------|--------|
| 0 violations found AND OCR verified | `compliant` |
| Any critical violation | `non_compliant` |
| Warnings only, no critical | `partial` |
| OCR engine was non-functional (all frames had empty text) | `partial` (score capped at 70) |
| Info violations only | `compliant` (score reduced) |

### Penalty Reference (DPDPA Section 33)
| Tier | Section | Max Penalty (INR) |
|------|---------|------------------|
| 1 | 33(a) | 250 crore |
| 2 | 33(b) | 200 crore |
| 3 | 33(c) | 200 crore |
| 4 | 33(d) | 150 crore |
| 5 | 33(e) | 100 crore |

### LLM Report Templates (Phase 2 — async, optional)

Three prompt templates fill human-readable fields when `use_llm=true`:

| Template | Input Variables | Output |
|----------|----------------|--------|
| `FINDING_DESCRIPTION_PROMPT` | rule_name, rule_id, section_ref, requirement_text, violation_condition, penalty_ref, frame_number, timestamp, objects_detected, pii_found, ocr_text, check_types, similarity_score | 2–3 sentence plain-English finding description |
| `RECOMMENDATION_PROMPT` | rule_name, rule_id, section_ref, finding_description, penalty_ref | 2–4 bullet actionable remediation steps |
| `EXECUTIVE_SUMMARY_PROMPT` | video_id, compliance_score, status, total_checks, passed_checks, failed_checks, critical_violations, violations_summary | 3–5 sentence executive prose for compliance/legal team |

---

## 7. Fallback & Failure Handling

| Failure | Behaviour | Output / Effect |
|---------|-----------|-----------------|
| **FFmpeg not on PATH** | `FrameExtractor.__init__` raises `EnvironmentError` at startup | Worker fails to start; clear error message with install instructions |
| **Video has no audio track** | `extract_audio()` probes with `ffmpeg.probe`, returns `None` | Transcription skipped silently; `transcription_completed = False` in Video record |
| **EasyOCR unavailable** | Falls back to Tesseract; if also missing, falls back to OpenCV region detection | OpenCV fallback returns empty text (not placeholder); compliance report status forced to `partial`, score capped at 70; `limitations` field populated with explicit warning |
| **OCR engine blind (all frames empty text)** | Detected in `check_ocr_rules` when `frames_with_text == 0` | `OCR_WARNING` added to `errors[]`; report status overridden to `partial`; audit log entry with `success=False` |
| **Weaviate connection failure** | Exception caught in `_vectorize_and_store` | Logged; PostgreSQL rows still written; vector search unavailable but structured rule checks proceed |
| **PostgreSQL write failure** | `db.rollback()` called; error logged | Frame/transcript data not persisted; compliance agent re-fetches empty → 0 findings; report still generated with limitation |
| **LangGraph node exception** | Per-node try/except; error appended to `state["errors"]` | Pipeline continues to next node; errors surfaced in final report `errors[]` field |
| **Celery task exception** | `except Exception` in `process_video_task` | Video status set to `FAILED`, `error_message` stored; ❌ PIPELINE FAILED banner printed in worker terminal |
| **YOLO model missing** | Exception on `VisualAnalyzer.__init__` | Frame processing fails; `visual_analysis_completed = False` |
| **Semantic search fails** | Exception caught in `semantic_enrich` node | Audit entry logged with `success=False`; pipeline continues with structured findings only |

**Principle:** No silent failures. Every failure either surfaces in the report `errors[]`, sets `ocr_verified=false`, forces `status=partial`, or marks the video `FAILED` in the DB.

---

## 8. API Endpoints

### Video Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/videos/upload` | Submit video path → triggers full pipeline |
| `GET` | `/api/v1/videos/{video_id}/status` | Poll processing status + compliance summary |
| `GET` | `/api/v1/videos/` | List all videos (last 50) |

**Upload Request:**
```json
{ "video_path": "C:/path/to/video.mp4", "video_id": "optional-uuid" }
```

### Compliance Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/compliance/check/{video_id}` | Re-run compliance check on already-processed video |
| `GET` | `/api/v1/compliance/report/{video_id}` | Full report (latest) for a video |
| `GET` | `/api/v1/compliance/report-by-id/{report_id}` | Report by specific report ID |
| `GET` | `/api/v1/compliance/audit/{report_id}` | Full step-by-step audit trail |
| `GET` | `/api/v1/compliance/findings/{report_id}?violations_only=true` | All findings; filter to violations only |
| `POST` | `/api/v1/compliance/purge/{video_id}?report_id=` | Purge raw data (DPDPA data minimisation) |
| `GET` | `/api/v1/compliance/purge-status/{video_id}` | Check if raw data has been purged |

---

## 9. Data Storage

### PostgreSQL Tables

| Table | Purpose | Key Data |
|-------|---------|----------|
| `videos` | One row per video submitted | Status, progress flags, pipeline completion booleans, timestamps |
| `frame_analyses` | One row per extracted frame | Frame number, timestamp, YOLO objects, person count, OCR text, vectorized flag |
| `transcription_segments` | One row per audio segment | Start/end time, spoken text, confidence score |
| `guidelines` | DPDPA rules (static) | Rule ID, category, severity, requirement text, check types, penalty reference, Weaviate embedding ID |
| `compliance_reports` | One per compliance check run | Score (0–100), status, check counts, executive summary, recommendations, completed timestamp |
| `compliance_findings` | One per triggered rule per report | Rule reference, severity, description, timestamp evidence, OCR excerpt, transcript excerpt, visual evidence JSON, confidence score |
| `audit_logs` | One per pipeline step | Step name, action description, input data, output data, rule_id, duration_ms, success flag, error message |

### Weaviate Collections (Vector DB)

| Collection | Purpose | Key Properties |
|------------|---------|----------------|
| `VideoContent` | Semantic search over video frames and audio | `video_id`, `content_type` (frame/transcription), `timestamp`, `text` (description), `frame_number`, `metadata` JSON |
| `Guidelines` | Semantic search over DPDPA compliance rules | `guideline_id`, `regulation_type`, `clause_number`, `requirement_text`, `severity`, `category`, `metadata` JSON |

**Vectorizer:** Manual (embeddings pre-computed by `sentence-transformers` and provided at insert time)
**Embedding model:** `all-mpnet-base-v2` — 768-dimensional vectors
**Search:** Cosine similarity; threshold 0.6 for semantic rule matching

---

## 10. Technical Stack

| Layer | Choice | Version | Notes |
|-------|--------|---------|-------|
| Language | Python | 3.13 | |
| API Framework | FastAPI | ≥ 0.109 | Async REST |
| Task Queue | Celery + Redis | ≥ 5.3 / ≥ 5.0 | `--pool=solo` on Windows |
| ORM | SQLAlchemy | ≥ 2.0 | Declarative models |
| Relational DB | PostgreSQL | 15 (Docker) | Port 5433 (local) |
| Vector DB | Weaviate | 1.27.3 (Docker) | gRPC port 50051 |
| Object Storage | MinIO | Docker | Frames / video files |
| Frame extraction | OpenCV + FFmpeg + PySceneDetect | ≥ 4.9 / binary / ≥ 0.6 | |
| Object detection | YOLOv8 | via `ultralytics ≥ 8.1` | COCO dataset classes |
| OCR | EasyOCR → Tesseract → OpenCV | ≥ 1.7 | Priority order; fallback triggers report warning |
| Audio transcription | OpenAI Whisper | local via `openai-whisper` | No API key needed |
| Embeddings | sentence-transformers | ≥ 2.3 | `all-mpnet-base-v2`, 768-dim |
| Compliance pipeline | LangGraph | ≥ 0.0.20 | 9-node state machine |
| LLM (Phase 2) | Ollama (local) | Optional | Narrative summary only; not required for scoring |

---

## 11. Implementation Status

| Milestone | Status |
|-----------|--------|
| Step 1: Video → Frames → YOLO → OCR → Weaviate | ✅ Complete |
| Step 2: DPDPA 36-rule definitions loaded | ✅ Complete |
| Step 3: LangGraph 9-node compliance agent | ✅ Complete |
| Automated pipeline (upload → auto-run) | ✅ Complete |
| Honest failure reporting (no silent false-compliant) | ✅ Complete |
| EasyOCR as primary OCR engine | ✅ Complete |
| Phase 2 LLM narrative (Ollama) | 🔵 Wired, not enabled by default |
| MinIO frame upload (frame_url) | 🔵 Wired, TODO populated |
| Multi-tenancy / auth | ⬜ Out of scope for prototype |
