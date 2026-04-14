# Regulatory-Tech End-to-End Flow (Full Codebase Walkthrough)

## Purpose

This document captures the end-to-end execution flow across the full repository, including:

- User flows (frontend to backend to reporting)
- Agent flows (LangGraph/LangChain compliance execution)
- API flows (internal endpoints + external service calls)
- Async/background processing flow (Celery pipeline)
- Module-by-module responsibilities and call graph
- Data lifecycle and purge behavior
- Configuration dependencies that change runtime behavior

## Repository Areas

- `frontend/` - single-page upload and report UI
- `backend/app/` - FastAPI app, services, agents, tasks, config, DB session
- `backend/` scripts - operational scripts, tests, utilities
- `docker/` - local runtime dependencies (Postgres, Redis, Weaviate, MinIO, Ollama, etc.)

---

## Runtime Topology

### Core services

- **Frontend UI** (`frontend/index.html`)
- **FastAPI API server** (`backend/app/main.py`)
- **Celery worker** (`backend/app/celery_app.py`, `backend/app/tasks/video_pipeline.py`)
- **PostgreSQL** for metadata/reports/audit/raw extracted rows
- **Redis** for Celery broker/result and health checks
- **Weaviate** for vectorized content and guideline retrieval
- **MinIO** for object storage (videos/frames)
- **Model stack**: Whisper (audio), YOLO (visual), OCR engines (Qwen/Ollama, EasyOCR, Tesseract)

### High-level flow

1. User uploads a video from the UI.
2. API creates DB video record and queues Celery processing.
3. Worker runs Step-1 extraction/vectorization in detail:
   - Frame extraction (`FrameExtractor.extract_frames`):
     - Default sampling is `FRAME_EXTRACTION_FPS=1` (1 frame/sec) plus scene-change picks when `ENABLE_SCENE_DETECTION=True`.
     - Scene-change threshold is mean pixel diff `> 30.0` between resized frames.
     - Processing cap is first 10 minutes (`600s`) of video.
     - Output per frame: `frame_number`, `timestamp`, `file_path`, `is_scene_change`.
   - Audio extraction (`FrameExtractor.extract_audio`):
     - Uses ffprobe metadata first; if no audio stream, transcription is skipped.
     - If audio exists, extracts mono 16 kHz PCM WAV (`pcm_s16le`, `ac=1`, `ar=16000`).
   - Transcription (`AudioTranscriber` / Whisper):
     - Produces segment rows with `start`, `end`, `text`, `confidence`.
   - Visual analysis (`VisualAnalyzer` / YOLO):
     - Runs per frame with `conf_threshold=0.25`, `iou_threshold=0.45`.
     - Stores object class labels + confidence; tracks person count per frame.
   - OCR (`OCRService`):
     - Engine priority: Qwen2-VL (Ollama) -> EasyOCR -> Tesseract -> OpenCV fallback.
     - OpenCV fallback only finds text-like regions and returns empty text, so visual PII checks become unreliable.
   - Embeddings + storage:
     - Builds frame descriptions (`objects_detected + ocr_text + timestamp`) and transcript descriptions.
     - Embeds in batch via `sentence-transformers` and stores in Weaviate `VideoContent`.
     - Persists extracted rows to PostgreSQL (`FrameAnalysis`, `TranscriptionSegment`) for deterministic rule checks.
4. Worker runs compliance agent graph and persists report/findings/audit logs.
5. Report is returned by API/UI.
6. Raw artifacts are purged (data minimization), while report evidence remains.

---

## Module Inventory and Responsibility Map

## Frontend

### `frontend/index.html`

- Implements upload and status polling UI.
- Main interactions:
  - `submitVideo` -> `POST /api/v1/videos/upload-file`
  - `pollStatus` -> `GET /api/v1/videos/{video_id}/status`
  - `runComplianceCheck` -> `POST /api/v1/compliance/check/{video_id}`
  - Fetches report via `GET /api/v1/compliance/report/{video_id}`
- Renders compliance score/findings and supports JSON/CSV/Text export.

## API/Core

### `backend/app/main.py`

- FastAPI initialization, CORS, router registration.
- Startup (`lifespan`) creates DB tables.
- Endpoints:
  - `GET /`
  - `GET /health`
  - `GET /health/detailed`
- Detailed health checks:
  - Postgres query
  - Redis ping
  - Weaviate readiness HTTP call
  - FFmpeg availability command
  - OCR and YOLO service readiness
  - MinIO bucket access
  - Ollama tags endpoint call

### `backend/app/config.py`

- Centralized environment settings via Pydantic.
- Controls behavior for:
  - Upload constraints
  - Processing toggles (scene detection, preprocessing)
  - Model names and inference endpoints
  - Infra URLs (DB, Redis, Weaviate, MinIO, Ollama)
  - Security keys and API key

### `backend/app/celery_app.py`

- Celery app definition with broker/backend config.
- Startup diagnostics test DB, Weaviate, FFmpeg, OCR, YOLO, and model insert viability.

### `backend/app/db/session.py`

- SQLAlchemy engine/session/base helpers.
- Exposes `get_db`, `create_tables`, and `drop_tables`.

### `backend/app/api/deps.py`

- API key dependency (`verify_api_key`) for secured endpoints.

## API Routes

### `backend/app/api/v1/videos.py`

- `POST /upload-file` (multipart upload) exact validations:
  - `file.filename` must exist, else `400`.
  - Extension must be one of `{mp4, avi, mov, mkv, webm}`, else `400`.
  - File is written to temp path: `%TEMP%/regvision_uploads/{video_id}.{ext}`.
  - Saved file size must be `<= MAX_UPLOAD_SIZE` (default `5368709120` bytes = 5 GB), else `413`.
  - On success inserts a `Video` row (`status=UPLOADED`, `processing_progress=0`) and attempts to queue Celery.
- `POST /upload` (local-path registration) exact validations:
  - `video_path` must exist on disk, else `400`.
  - Extension must be one of `{mp4, avi, mov, mkv, webm}`, else `400`.
  - File size must be `<= MAX_UPLOAD_SIZE` (default 5 GB), else `413`.
  - Duplicate `video_id` is rejected with `409` unless `force=true`.
  - `force=true` deletes prior matching records (same `video_id` and/or same file path) before re-creating the video row.
- `GET /{video_id}/status`
  - Returns processing state and progress
  - Also returns stage-level stats:
    - `frame_extraction`: `frames_total`, `persons_detected_in`
    - `ocr`: `frames_with_text`, coverage ratio, degraded warning
    - `transcription` and `vectorization` completion flags
- `GET /`
  - Lists latest 50 videos ordered by `created_at DESC`
  - Returns `video_id`, `filename`, `status`, `progress`, `created_at`
  - Important: current code does **not** implement query-param status filtering on this endpoint

### `backend/app/api/v1/compliance.py`

- `POST /check/{video_id}` -> runs compliance check flow
- `GET /report/{video_id}` -> latest report by video
- `GET /report-by-id/{report_id}` -> direct report fetch
- `GET /audit/{report_id}` -> audit trail entries
- `GET /findings/{report_id}` -> report findings
- `POST /purge/{video_id}` -> explicit raw data purge
- `GET /purge-status/{video_id}` -> verification of purge status
- `POST /guidelines/reload` -> reloads rules into DB + vector store

## Services

### `backend/app/services/video_content_vectorizer.py`

- Central Step-1 pipeline orchestration (`process_video`) with exact persisted artifacts:
  - Frame extraction:
    - Produces local JPEG frames in temp dir.
    - Tracks extraction count as `stats.frames_processed`.
  - Audio + transcription:
    - If audio present, Whisper segments are generated and counted in `stats.transcription_segments`.
    - If no audio track, this stage is skipped (non-fatal).
  - Per-frame analysis (`_process_frames`):
    - Runs YOLO once per frame; stores object list as `[{class, confidence}]`.
    - Computes `persons_count`, `has_persons`, and `total_objects`.
    - Runs OCR and stores concatenated frame text into `ocr_text`.
  - Embedding and vector write (`_vectorize_and_store`):
    - Creates frame text descriptions and transcript text descriptions.
    - Batch embeds all descriptions.
    - Batch inserts into Weaviate `VideoContent` with:
      - `content_type` = `frame` or `transcription`
      - `timestamp`, `text`, `frame_number` (frames), `metadata` JSON-as-string
    - Persists PostgreSQL rows:
      - `FrameAnalysis` (one row per processed frame)
      - `TranscriptionSegment` (one row per transcript segment)
    - Marks each persisted row as `vectorized=True` when applicable.
- Includes cleanup and search helpers for video content.

### `backend/app/services/frame_extractor.py`

- Extracts frames in one of two modes (`FrameExtractor.extract_frames`):
  - Fixed FPS (`_extract_fixed_fps`)
    - `frame_interval = int(original_fps / target_fps)` where `target_fps` defaults to `FRAME_EXTRACTION_FPS=1`
    - Extract condition: `frame_count % frame_interval == 0`
    - Output file naming: `frame_{extracted_count:06d}.jpg`, JPEG quality `90`
  - Scene + interval hybrid (`_extract_with_scene_detection`)
    - Maintains previous frame resized to `320x240`
    - Computes `mean(absdiff(prev_frame, current_frame_resized))`
    - Marks scene change when mean diff `> 30.0`
    - Extract condition: `(scene_change == True) OR (frame_count % frame_interval == 0)`
- Hard limits and coverage behavior:
  - Max processed duration is capped to `600s` (10 minutes)
  - Scene mode also hard-stops after `original_fps * 600` frames
  - If `max_frames` is provided and would under-sample, extractor raises it to at least `int(duration)` for ~1 fps coverage
- Completeness and missed-frame handling:
  - No explicit "all frames extracted" guarantee; this is deliberate sampling, not full-frame archival
  - Downstream `_process_frames` tracks dropped frames and logs `% coverage loss` when frame analysis fails
  - Multi-screen/frame-content edge case: extractor is frame sampler only; it does not reason about "two screens in one frame"
    - If a sampled frame contains multiple displays, later OCR/YOLO pass still runs once on that frame
    - If OCR misses text in that frame, there is no second model pass on the same frame by default (only engine-level fallback in OCR path)
- Audio extraction details (`extract_audio`):
  - Uses ffprobe metadata first; if no audio stream, returns `None` and pipeline skips transcription
  - If audio exists, extracts `pcm_s16le`, mono (`ac=1`), `16kHz` (`ar=16000`) WAV
- Metadata extraction (`get_video_info`) returns:
  - `duration`, `format`, `size`, `width`, `height`, `fps`, `codec`, `has_audio`, `audio_codec`
- Important implementation notes:
  - `ENABLE_SCENE_DETECTION` exists in config but constructor currently defaults to `enable_scene_detection=True` in `FrameExtractor()` callsites
  - If `target_fps > original_fps`, `frame_interval` can become `0` (potential modulo failure risk; no guard in current code)

### `backend/app/services/frame_preprocessor.py`

- Image cleanup to improve OCR:
  - blur/brightness quality gates
  - bilateral denoise
  - CLAHE contrast normalization
  - sharpening

### `backend/app/services/visual_analyzer.py`

- YOLO-based detection (`ultralytics.YOLO`) with model from config (`YOLO_MODEL`, default `yolov8n.pt`).
- `analyze_image` per-frame inference parameters:
  - `conf_threshold=0.25`
  - `iou_threshold=0.45`
- Detection payload available in-memory per object:
  - `class_name`, `confidence`, `bounding_box`, `class_id`
- Stored payload in vectorization pipeline:
  - persisted as reduced list `[{class, confidence}]` in `FrameAnalysis.objects_detected`
  - bounding boxes/class_id are currently not persisted by `video_content_vectorizer`
- Person count semantics:
  - `persons_count = sum(class_name == "person")`
  - stored as `persons_detected` and used by status/compliance checks
- PII-indicator helper (`detect_pii_indicators`) checks for display-device proxy classes:
  - `{laptop, cell phone, monitor, tv, keyboard, mouse, remote, book}`
  - risk levels: `high` (display+person), `medium` (display only), `low` (none)

### `backend/app/services/ocr_service.py`

- OCR fallback chain:
  1. Qwen vision OCR via Ollama
  2. EasyOCR
  3. Tesseract
  4. OpenCV fallback region extraction
- Exact fallback/dispatch behavior:
  - Engine is selected at init-time in this priority order
  - Runtime `extract_text()` dispatches to selected engine only
  - EasyOCR/Tesseract failures fallback to OpenCV region detector
  - Qwen failure returns empty OCR results (no dynamic fallback to EasyOCR in that call path)
- Frame preprocessing gate:
  - Controlled by `ENABLE_FRAME_PREPROCESSING`
  - When preprocessor marks frame unreadable (`meta["skipped"]=True`), OCR returns no text for that frame
  - Default config sets preprocessing disabled (`False`) to avoid skipping potential evidence
- Sensitive-info detection patterns come from shared runtime source:
  - `app/common/patterns.py` (`detect_pii`, `detect_gst`)
  - PII regex families include: Indian/international phones, email, credit card, Aadhaar, PAN, IP, DOB, URL
  - Separate GST regex for `gst_detection`
- What is stored for compliance:
  - OCR findings store only redacted typed tags (`{"type": ..., "redacted": True}`), not raw PII values
  - GST match count is used in findings/audit; raw GST value is not persisted in compliance finding payload

### `backend/app/services/audio_transcriber.py`

- Local Whisper transcription.
- Returns segment-level and full-text outputs.
- Includes language detection helper methods.

### `backend/app/services/embedding_service.py`

- SentenceTransformer embedding provider (local, no external embedding API).
- Runtime role in Step-1:
  - Loads model from `EMBEDDING_MODEL` (default `all-mpnet-base-v2`)
  - `embed_batch(texts)` is used by vectorization to encode frame+transcript descriptions in one call
  - Vectors are written to Weaviate `VideoContent`; relational pipeline remains usable even if vector write fails
- Text builders used before embedding:
  - `create_frame_description(...)` builds timestamped natural-language scene text from objects + OCR text
  - `create_transcription_description(...)` builds timestamped audio text
- Step-by-step runtime call sequence in Step-1:
  1. Build frame/transcript description strings
  2. Call `EmbeddingService.embed_batch(texts_to_embed)` once for all items
  3. Attach returned vectors to item payloads
  4. Batch insert vectors to Weaviate `VideoContent`
  5. Persist deterministic artifacts to PostgreSQL regardless of vector-store success
- Why this layer matters:
  - Enables semantic retrieval for enrichment (`semantic_enrich`) instead of only deterministic rule matching
  - Keeps compliance checks resilient: failed embedding/vector insert is logged as non-fatal, deterministic checks still run from PostgreSQL artifacts

### `backend/app/services/vector_store.py`

- Weaviate adapter for:
  - `VideoContent` collection
  - `Guidelines` collection
- Supports add/search/delete/stats operations.

### `backend/app/services/guideline_loader.py`

- Loads DPDPA rules from in-code canonical definitions (`app/dpdpa/definitions.py`), not from an external feed.
- Sync strategy:
  - `load_all_rules(clear_existing=False)` is idempotent on `Guideline.name == rule.rule_id`
  - Existing rules are skipped unless `clear_existing=True` is used
  - `clear_existing=True` deletes prior DPDPA rows and reloads from definitions
- "Latest rules" behavior:
  - The system treats repository code definitions as source of truth
  - New/updated legal rules require code update + guideline reload endpoint (`POST /api/v1/compliance/guidelines/reload`)
  - There is no automatic external legal update checker in current implementation

### `backend/app/services/compliance_checker.py`

- Top-level compliance execution wrapper.
- Detailed flow:
  - Pre-creates `ComplianceReport` with `PENDING_REVIEW` and placeholder summary
  - Executes LangGraph state machine (`run_compliance_check`)
  - Optionally tries to queue async LLM summary task when `use_llm=True`
  - Auto-triggers raw-data purge after report persistence (`purge_raw_data`)
- Report retrieval:
  - `get_report_summary(report_id)` returns report aggregates, findings, and `data_quality` block
  - `data_quality` flags stage failure and OCR reliability limitations
- Audit retrieval:
  - `get_audit_trail(report_id)` returns ordered per-step audit entries with input/output payload snapshots

### `backend/app/services/data_lifecycle.py`

- Raw artifact minimization/purge:
  - delete MinIO raw objects
  - remove Weaviate video vectors
  - remove DB raw extraction rows
  - preserve report/finding/audit entities

## Agent and Prompt Components

### `backend/app/langchain_components/agents/compliance_agent.py`

- Defines state graph and report generation logic.
- Node sequence:
  1. `load_video_data`
  2. `check_visual_rules`
  3. `check_ocr_rules`
  4. `check_audio_rules`
  5. `check_metadata_rules`
  6. `semantic_enrich`
  7. `synthesize_findings`
  8. `generate_report`
  9. `save_to_db`
- Why LangGraph is used here:
  - Encodes compliance as explicit, ordered, auditable state transitions
  - Keeps each rule-check stage deterministic and traceable with per-node audit entries
  - Produces a single shared state object carrying inputs, intermediate findings, errors, report data, and audit logs
- Node-by-node I/O and decision logic (high-level):
  1. `load_video_data`
     - Input: `video_id`
     - Reads: `FrameAnalysis`, `TranscriptionSegment`
     - Output: normalized in-memory `frames[]`, `transcripts[]`
  2. `check_visual_rules`
     - Input: per-frame `objects_detected`, `faces_detected`
     - Rule trigger map: `person->visual_person_detection`, `face->visual_face_detection`, `child|boy|girl->children_detection`
     - Output: `visual_findings[]`
  3. `check_ocr_rules`
     - Input: per-frame `ocr_text`
     - Evaluates blind/partial OCR coverage and raises OCR warnings into `errors[]`
     - Runs `detect_pii()` + `detect_gst()` and maps to `ocr_pii_detection`, `ocr_text_detection`, `gst_detection`
     - Output: `ocr_findings[]`
  4. `check_audio_rules`
     - Input: transcript segment `text`
     - Runs `detect_pii()` and maps to `audio_pii_detection`
     - Output: `audio_findings[]`
  5. `check_metadata_rules`
     - Input: video metadata (`created_at`)
     - Current encoded rule: retention age check (`age_days > 90`) -> `data_retention`
     - Output: `metadata_findings[]`
  6. `semantic_enrich`
     - Input: high-risk frames (persons or OCR text), guideline vectors
     - Retrieves top semantic matches from Weaviate; adds only unseen rules above similarity threshold (`>=0.6`)
     - Output: additional findings appended into visual findings set
  7. `synthesize_findings`
     - Input: all finding lists
     - Dedup key: `(rule_id, frame_number, source)`, keeping highest similarity
     - Output: sorted `all_findings[]`
  8. `generate_report`
     - Input: `all_findings[]`, `errors[]`, `get_all_rules()`
     - Scores unique violated rules (`critical=-5`, `warning=-2`, `info=-1`)
     - Stage-failure override sets score `0` + status `incomplete` for OCR/visual/frame-extraction failure conditions
     - Output: `report_data`
  9. `save_to_db`
     - Input: findings, report data, audit entries
     - Writes `ComplianceReport`, `ComplianceFinding`, `AuditLog`
     - Output: `report_id`, persisted audit trail
- Synthesis dedup details:
  - Dedup is not global by rule only; it keeps distinct findings per source/frame context
  - If same key repeats, highest `similarity_score` wins

### `backend/app/langchain_components/prompts/compliance_prompts.py`

- Prompt templates for finding descriptions, recommendations, and executive summaries.
- Intended for narrative enhancement in report generation flows.

## Domain Definitions

### `backend/app/dpdpa/definitions.py`

- Canonical DPDPA rules and retrieval methods by check type/category.

### `backend/app/dpdpa/penalty_schedule.py`

- Penalty tier definitions and lookup helpers.
- Operational behavior:
  - Defines static `PENALTY_TIERS` and helper mapping functions
  - Used for reference/listing contexts
  - Runtime compliance findings primarily use `penalty_ref` already embedded in each rule definition from `definitions.py`
- Update strategy:
  - Update is code-driven (edit file + deploy)
  - No automatic external update ingestion

### `backend/app/pii/definitions.py`

- Detailed PII categories and regex-like pattern metadata.

### `backend/app/common/patterns.py`

- Runtime regex patterns and detection functions used by OCR/compliance logic.

## Tasks

### `backend/app/tasks/video_pipeline.py`

- Celery task `process_video_task(video_id, video_path)` orchestrates:
  - processing state transitions
  - vectorization phase
  - compliance phase
  - completion/failure and optional webhook notification
- Orchestration I/O details by stage:
  1. Initialization
     - Input: `video_id`, `video_path`
     - Loads `Video`; sets `status=PROCESSING`, `processing_started_at`
  2. Vectorization stage
     - Celery meta: `{step: "vectorizing", progress: 10}`
     - Calls `VideoContentVectorizer.process_video(...)`
     - Output stats: `frames_processed`, `transcription_segments`, `embeddings_created`, `vector_store_entries`
     - DB side effects: marks visual/OCR/vectorization flags and `processing_progress=60`
  3. Compliance stage
     - Celery meta: `{step: "compliance", progress: 65}`
     - Calls `check_video_compliance(video_id, use_llm=False)`
     - Output: report status/score/critical counts and report id
  4. Completion
     - Sets `status=COMPLETED`, `processing_progress=100`, `processing_completed_at`
     - Returns combined vectorization + compliance summary payload
  5. Failure
     - Sets `status=FAILED`, `error_message`
     - Optionally POSTs failure payload to `FAILURE_WEBHOOK_URL`
     - Re-raises exception for task failure visibility/retry policy

## Operational/Utility Scripts

- `backend/doctor.py` - infrastructure and dependency diagnostics
- `backend/load_dpdpa_rules.py` - rule load/search CLI
- `backend/run_compliance_check.py` - interactive compliance runner
- `backend/bulk_reprocess.py` - reset/requeue batch jobs
- `backend/reprocess_video_with_ocr.py` - single-video reprocess utility
- `backend/extract_pii_from_video.py` / `extract_pii_video2.py` - PII extraction/report scripts
- `backend/test_services.py`, `test_ocr.py`, `test_step1_complete.py` - manual diagnostics/tests
- `start.ps1` - local startup orchestration
- `install_ffmpeg.ps1` - ffmpeg install helper

---

## End-to-End User Flows

### Flow 1: Upload from UI and get compliance report

1. User selects video in `frontend/index.html`.
2. `submitVideo()` sends multipart request to `POST /api/v1/videos/upload-file`.
3. Backend writes temp file and creates `Video` record (`pending`/queued).
4. API enqueues Celery `process_video_task`.
5. UI starts periodic `pollStatus(video_id)` every 30s.
6. Worker updates status to `processing`, runs extraction/vectorization.
7. Worker runs compliance agent and persists `ComplianceReport` + findings.
8. Worker marks video complete.
9. UI calls compliance endpoint and fetches report JSON.
10. UI renders score, status, findings; user exports report if needed.

### Flow 2: API-driven local file registration

1. External caller hits `POST /api/v1/videos/upload` with filesystem path.
2. API validates path and creates/updates video row.
3. Celery pipeline executes same as Flow 1.

### Flow 3: Manual compliance re-check

1. Caller invokes `POST /api/v1/compliance/check/{video_id}`.
2. Service checks extraction artifacts and executes agent graph again.
3. New report snapshot and audit entries are saved.

### Flow 4: Purge and verification

1. Automatic purge occurs after compliance run (service-level).
2. Manual purge optional through `POST /api/v1/compliance/purge/{video_id}`.
3. Verification through `GET /api/v1/compliance/purge-status/{video_id}`.
4. Raw artifacts are removed while compliance report records remain queryable.

---

## Agent Flow (Detailed)

### Agent entrypoint

- `app/services/compliance_checker.py` -> `check_video_compliance()`
- Initializes dependencies and runs `run_compliance_check(video_id, db)`

### Graph node behavior

#### 1) `load_video_data`

- Loads extracted records from PostgreSQL:
  - `FrameAnalysis` fields consumed: `id`, `frame_number`, `timestamp`, `minio_path`, `objects_detected`, `faces_detected`, `persons_detected`, `ocr_text`, `weaviate_id`
  - `TranscriptionSegment` fields consumed: `id`, `start_time`, `end_time`, `text`, `confidence`
- Initializes graph state collections (`visual_findings`, `ocr_findings`, etc.) and appends audit entry (`step=frame_fetch`)

#### 2) `check_visual_rules`

- Evaluation criteria:
  - Input is per-frame detected object labels (`objects_detected`) and optional `faces_detected`
  - Labels are mapped to check types via fixed map:
    - `person -> visual_person_detection`
    - `face -> visual_face_detection`
    - `child|boy|girl -> children_detection`
  - For each triggered check type, matching DPDPA rules are pulled through `get_rules_by_check_type`
- Output:
  - Structured finding objects with rule/category/severity/timestamp/object evidence
  - Per-trigger audit entry (`step=visual_check`) and stage summary audit record
- Output derivation:
  - Deterministic map from object labels to rule check types, then direct rule expansion

#### 3) `check_ocr_rules`

- Scans OCR text using PII/GST/pattern checks.
- Maps pattern matches to rule violations with evidence references.

#### 4) `check_audio_rules`

- Evaluates transcription segments for sensitive spoken disclosures.
- Generates findings with transcript evidence and timing references.

#### 5) `check_metadata_rules`

- Applies metadata-level checks (retention, purpose, consent signaling where represented).

#### 6) `semantic_enrich`

- Embeds finding context and queries guideline vectors from Weaviate.
- Adds semantically similar guideline references to strengthen recommendations.

#### 7) `synthesize_findings`

- Deduplication:
  - Key is `(rule_id, frame_number, source)`
  - If duplicates exist for same key, keeps finding with higher `similarity_score`
- Normalization:
  - Merges findings from visual/OCR/audio/metadata paths
  - Sort order: severity (`critical`, `warning`, `info`) then timestamp

#### 8) `generate_report`

- Computes overall compliance score and status.
- Generates report structure with summary and recommendation data.

#### 9) `save_to_db`

- Persists `ComplianceReport`, `ComplianceFinding`, `AuditLog`.
- Returns final graph output to caller.

---

## API Call Matrix

### Backend HTTP endpoints

- `GET /`
- `GET /health`
- `GET /health/detailed`
- `POST /api/v1/videos/upload-file`
- `POST /api/v1/videos/upload`
- `GET /api/v1/videos/{video_id}/status`
- `GET /api/v1/videos/`
- `POST /api/v1/compliance/check/{video_id}`
- `GET /api/v1/compliance/report/{video_id}`
- `GET /api/v1/compliance/report-by-id/{report_id}`
- `GET /api/v1/compliance/audit/{report_id}`
- `GET /api/v1/compliance/findings/{report_id}`
- `POST /api/v1/compliance/purge/{video_id}`
- `GET /api/v1/compliance/purge-status/{video_id}`
- `POST /api/v1/compliance/guidelines/reload`

### External and infra calls by module

- `main.py` -> Weaviate readiness, Ollama tags, FFmpeg command, Redis ping, MinIO checks
- `celery_app.py` -> DB probe, Weaviate readiness, FFmpeg check, OCR/YOLO initialization
- `ocr_service.py` -> Ollama tags/chat endpoints; local EasyOCR/Tesseract
- `vector_store.py` -> Weaviate CRUD/search operations
- `video_pipeline.py` -> optional failure webhook POST
- `data_lifecycle.py` -> MinIO object delete + Weaviate delete + DB row delete
- `frame_extractor.py` -> ffmpeg/openCV calls for probe/extract

---

### Celery/Async Processing Flow

#### `process_video_task(video_id, video_path)` sequence

1. Load video row and set processing state.
2. Ensure ffmpeg path availability (`_ensure_ffmpeg_on_path`).
3. Execute `VideoContentVectorizer.process_video`.
4. On success, execute `check_video_compliance`.
5. Persist status updates and completion timestamps.
6. On error, set failure status and optionally call failure webhook.
7. Return combined result payload with vectorization stats + compliance summary.

---

### Data Stores and Lifecycle

#### PostgreSQL (structured entities)

- Schema fidelity note:
  - This repository snapshot references `app.models.*` in many modules, but model source files are not present here.
  - The field inventory below is reconstructed from read/write usage in API/services/tasks code and is accurate to runtime usage; exact SQLAlchemy types/nullability/index declarations are not directly verifiable in this snapshot.
- Runtime table/field inventory (from actual model usage in pipeline/API code):
  - `videos`
    - `id` (UUID/string PK), `filename`, `original_filename`, `file_size`, `format`, `minio_path`
    - `status`, `processing_progress`, `error_message`
    - `frames_processed`, `visual_analysis_completed`, `ocr_completed`, `transcription_completed`, `vectorization_completed`
    - `created_at`, `updated_at`, `processing_started_at`, `processing_completed_at`
  - `frame_analyses`
    - `id`, `video_id` (FK), `frame_number`, `timestamp`, `minio_path`
    - `objects_detected` (JSON-like list), `faces_detected`, `persons_detected`, `ocr_text`
    - `weaviate_id`, `visual_analysis_completed`, `ocr_completed`, `vectorized`
  - `transcription_segments`
    - `id`, `video_id` (FK), `start_time`, `end_time`, `text`, `confidence`, `vectorized`
  - `compliance_reports`
    - `id`, `video_id` (FK), `status`, `compliance_score`
    - `total_checks`, `passed_checks`, `failed_checks`, `critical_violations`, `warnings`
    - `executive_summary`, `recommendations` (list/JSON), `created_at`, `completed_at`
  - `compliance_findings`
    - `id`, `report_id` (FK), `guideline_id` (FK), `is_violation`, `severity`
    - `description`, `recommendation`
    - `timestamp_start`, `timestamp_end`, `confidence_score`
    - `visual_evidence` (JSON), `ocr_text_excerpt`, `transcript_excerpt`
  - `audit_logs`
    - `id`, `video_id` (FK), `report_id` (FK), `step`, `action`
    - `input_data` (JSON), `output_data` (JSON), `rule_id`
    - `timestamp`, `duration_ms`, `success`, `error_message`
  - `guidelines`
    - `id`, `name` (rule_id), `regulation_type`, `version`, `description`, `requirement_text`
    - `severity`, `check_type`, `weaviate_id`, `clause_number`, `penalty_ref`
    - `check_types_json`, `category`, `is_active`

#### Raw vs processed storage

- Raw input video:
  - Stored to local temp path (`%TEMP%/regvision_uploads/{video_id}.{ext}`) for multipart upload flow
  - Path is persisted in `videos.minio_path` (field name historical; currently may hold local path)
- Processed artifacts currently persisted:
  - PostgreSQL:
    - `frame_analyses`: per processed frame detections/text/status flags
    - `transcription_segments`: per audio segment text/timestamps/confidence
  - Weaviate `VideoContent`:
    - embedding vectors + text descriptions + metadata for frame/transcription items
  - Compliance persistence:
    - `compliance_reports`, `compliance_findings`, `audit_logs`
- Not fully persisted in current code path:
  - Frame binary object URLs (`frame_url`) and `frame_analyses.minio_path` are currently written as empty strings in vectorizer path
  - This means analysis is persisted, but full processed image artifacts are not uploaded by this path

#### Weaviate (semantic retrieval)

- `VideoContent` collection:
  - Properties: `video_id`, `content_type`, `timestamp`, `text`, `frame_number`, `frame_url`, `metadata`
  - Stores embeddings for processed frame descriptions and transcript descriptions (not raw binary data).
- `Guidelines` collection:
  - Properties: `guideline_id`, `regulation_type`, `clause_number`, `requirement_text`, `severity`, `category`, `metadata`
  - Stores semantic embeddings of DPDPA rules used during enrichment.

#### MinIO (binary artifacts)

- Intended raw binary locations:
  - `videos/{video_id}/...` for original uploaded binaries
  - `frames/{video_id}/...` for extracted frame images
- Current implementation detail:
  - Uploaded file is always saved to local temp (`%TEMP%/regvision_uploads`) and referenced via `videos.minio_path`.
  - `frame_url` and `frame_analyses.minio_path` are currently left empty in vectorizer (`TODO` markers), so frame binaries are processed locally and not currently uploaded by this path.

### Purge behavior

- Automatic purge is triggered after successful compliance check (`check_video_compliance`).
- `purge_raw_data` deletes:
  - MinIO video objects under `videos/{video_id}/...`
  - MinIO frame objects under `frames/{video_id}/...`
  - Weaviate `VideoContent` vectors for that video
  - PostgreSQL `frame_analyses` rows for that video
  - PostgreSQL `transcription_segments` rows for that video
- `purge_raw_data` preserves:
  - `compliance_reports`
  - `compliance_findings`
  - `audit_logs`
  - `guidelines` and Weaviate `Guidelines`

### Audit trail structure and update strategy

- Audit payload structure (graph-internal then persisted):
  - `step`, `action`, `input_data`, `output_data`, `rule_id`, `timestamp`, `duration_ms`, `success`, `error_message`
- Mutation/appending strategy:
  - Each LangGraph node appends one or more audit entries into in-memory state
  - `save_to_db` persists all accumulated entries as `AuditLog` rows for the report
  - Purge flow appends separate start/completion `DATA_PURGED` audit rows outside the graph
- Input/output data strategy:
  - `input_data` captures trigger context (frame number, object labels, PII types, query snippets)
  - `output_data` captures derived results (rule IDs, severity, counts, score payloads)

### Libraries used and suitability notes

- Current stack by function:
  - Frame/video: `opencv-python`, `ffmpeg-python`
  - OCR: Ollama Qwen2-VL, EasyOCR, pytesseract, OpenCV fallback
  - Object detection: `ultralytics` YOLOv8
  - Audio transcription: `openai-whisper`
  - Embeddings: `sentence-transformers`
  - Graph orchestration: `langgraph` + `langchain`
  - Vector DB: `weaviate-client`
- Fit-for-purpose observations from implementation:
  - Strong: multi-engine OCR fallback and deterministic compliance graph with full audit trail
  - Strong: local embedding + vector search enables semantic enrichment without external APIs
  - Gap: scene detection currently uses simple frame-diff threshold, not `scenedetect` library despite dependency present
  - Gap: no explicit full-frame completeness verification against expected total-frame sampling targets
  - Gap: `search_video_content` builds filter strings but does not apply them in Weaviate query call path

---

## Configuration Keys That Drive Behavior

### Processing and model selection

- `FRAME_EXTRACTION_FPS`
- `ENABLE_SCENE_DETECTION`
- `ENABLE_FRAME_PREPROCESSING`
- `OCR_LANGUAGES`
- `WHISPER_MODEL`
- `YOLO_MODEL`
- `EMBEDDING_MODEL`
- `OLLAMA_BASE_URL`
- `OLLAMA_MODEL`
- `OLLAMA_OCR_MODEL`

### Infrastructure

- `DATABASE_URL`
- `REDIS_URL`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `WEAVIATE_URL`
- `MINIO_ENDPOINT`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`

### Security and API behavior

- `API_KEY`
- `SECRET_KEY`
- `JWT_SECRET_KEY`
- `MAX_UPLOAD_SIZE`
- `ALLOWED_VIDEO_FORMATS`
- `FAILURE_WEBHOOK_URL`

---

## Known Integration Gaps / Risks (from code walk)

- Some modules import `app.models.*`, but model files are not present in this repository snapshot.
- Optional Phase-2 LLM task (`app.tasks.compliance_tasks.generate_llm_summary_task`) is referenced but not present.
- A few utility scripts appear to expect service methods/response keys that differ from current implementations.
- Purge process is best-effort across multiple systems; partial purge states can occur if one backend fails.

---

## Quick Reference: End-to-End Sequence (Textual)

1. UI upload -> `videos.upload-file` endpoint
2. DB `Video` row creation
3. Celery task queued
4. Frame + audio extraction
5. OCR + visual + transcription analysis
6. Embedding + Weaviate indexing
7. Compliance graph run and report generation
8. Report/findings/audit persistence
9. Raw-data purge
10. UI report fetch and export

This is the canonical execution path currently implemented in the codebase.
