# DPDPA Video Compliance Tracker — Full Pipeline Reference

> **India's Digital Personal Data Protection Act 2023 + DPDP Rules 2025**
> Complete technical reference for all 3 pipeline steps — what each action does, why it exists, and which library handles it.

---

## System Overview

```
MP4 Video Upload
      │
      ▼
┌─────────────────────────────────────────────────────┐
│  STEP 1 — Video to Vector Pipeline                  │
│  Extract frames → Detect objects → OCR → Embed      │
│  Stores results in PostgreSQL + Weaviate             │
└─────────────────────────┬───────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│  STEP 2 — DPDPA Rule Definitions (one-time setup)   │
│  36 structured rules → PostgreSQL + Weaviate        │
└─────────────────────────┬───────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│  STEP 3 — LangGraph Compliance Agent                │
│  Read Step 1 data → Match Step 2 rules → Report     │
│  Writes: compliance_reports, findings, audit_logs   │
└─────────────────────────────────────────────────────┘
```

**Infrastructure (Docker):**

| Service | Port | Purpose |
|---|---|---|
| PostgreSQL 16 | 5433 | Structured storage — videos, frames, guidelines, reports, audit logs |
| Weaviate 1.27.3 | 8080 + 50051 (gRPC) | Vector database — semantic search on frames and rules |
| Redis 7 | 6379 | Task queue broker for Celery background jobs |
| MinIO | 9000 | Object storage — raw video files and extracted frame JPEGs |
| Ollama | 11434 | Local LLM (Llama 3.1:8b) for narrative summary generation (Phase 2) |

---

---

# STEP 1 — Video to Vector Pipeline

**Trigger:** A video is uploaded for compliance analysis.
**Goal:** Convert a raw MP4 into searchable, structured data — frame images, detected objects, OCR text, and 768-dimensional vector embeddings.
**Source files:** `backend/app/services/`

---

## Action 1.1 — Frame Extraction

**File:** `frame_extractor.py` → `FrameExtractor.extract_frames()`

**What it does:**
Reads the video file and extracts individual JPEG image frames. Instead of extracting every frame (which would produce thousands of nearly identical images), it uses **scene change detection** — only capturing frames where the visual content meaningfully changes. For longer videos, it auto-scales to ensure at least 1 frame per second of coverage, capped at 50 frames total.

**Why this matters:**
Videos are continuous streams. Every downstream AI model (YOLO, OCR, embeddings) works on still images. Scene-change extraction cuts ~10,000 potential frames down to ~50 high-value frames without losing important moments.

**How it works — step by step:**
1. Opens the video using `cv2.VideoCapture(video_path)`
2. Reads video metadata: total frames, FPS, duration
3. Iterates through frames, comparing each to the previous using `cv2.absdiff()` (pixel-level difference)
4. If the mean pixel difference exceeds the threshold (30.0), the frame is a scene change → save it
5. Saves each selected frame as a JPEG at 90% quality using `cv2.imwrite()`
6. Returns a list of `ExtractedFrame` objects with `frame_number`, `timestamp`, and `file_path`

**Parameters:**
- Scene change threshold: `30.0` (pixel mean difference)
- Comparison resolution: `320×240` (downscaled for speed)
- JPEG quality: `90`
- Max frames: `50` (auto-scaled for longer videos)

**Libraries used:**

| Library | Version | Role |
|---|---|---|
| `opencv-python` (cv2) | latest | Video reading, frame comparison, JPEG saving |
| `ffmpeg-python` | latest | Video format handling and conversion fallback |

---

## Action 1.2 — Audio Extraction

**File:** `frame_extractor.py` → `FrameExtractor.extract_audio()`

**What it does:**
Separates the audio track from the video file and saves it as a WAV file in the correct format for speech transcription models.

**Why this matters:**
People often speak PII aloud in videos — phone numbers dictated to a contact form, names mentioned in conversations, addresses read out. Audio is a separate PII source from visual frames.

**How it works — step by step:**
1. Uses FFmpeg to demux the video and extract the audio stream
2. Re-encodes audio to: `PCM 16-bit signed, mono, 16kHz` — the standard input format for Whisper and other speech models
3. Saves as `.wav` file alongside the extracted frames

**FFmpeg command equivalent:**
```
ffmpeg -i video.mp4 -acodec pcm_s16le -ac 1 -ar 16000 audio.wav
```

**Libraries used:**

| Library | Role |
|---|---|
| `ffmpeg-python` | Audio stream extraction and re-encoding |

---

## Action 1.3 — Object Detection (YOLO)

**File:** `visual_analyzer.py` → `VisualAnalyzer.analyze_image()`

**What it does:**
Runs each extracted frame through the YOLO v8 neural network to detect and label all objects visible in the image — people, phones, laptops, vehicles, etc. Returns bounding box coordinates and confidence scores for every detected object.

**Why this matters for compliance:**
Knowing *what* is in the frame provides the compliance context. A frame with `person + cell phone` showing a phone number = high PII risk (DPDPA-S4-001 consent required). A frame with only `truck + road` = low risk. The object labels directly trigger DPDPA rules in Step 3.

**How it works — step by step:**
1. Loads the YOLO v8 nano model (`yolov8n.pt`) on first call — cached in memory for subsequent frames
2. Reads each frame image from disk using `cv2.imread()`
3. Runs inference: `self.model(image, conf=0.25, iou=0.45)`
4. Extracts detections from results: class name, confidence score, bounding box `[x1, y1, x2, y2]`
5. Returns a list of `DetectedObject` dataclasses — one per detected object per frame
6. Key objects tracked: `person`, `face`, `cell phone`, `laptop`, `car`, `child` (maps to DPDPA check types)

**Parameters:**
- Model: `yolov8n.pt` (nano — fastest, 80 COCO classes)
- Confidence threshold: `0.25` (objects below 25% confidence are ignored)
- IoU threshold (NMS): `0.45` (deduplicates overlapping bounding boxes)
- Classes: 80 (full COCO dataset — people, vehicles, electronics, furniture, etc.)

**Libraries used:**

| Library | Role |
|---|---|
| `ultralytics` | YOLO v8 model loading and inference |
| `opencv-python` (cv2) | Image reading and preprocessing |
| `numpy` | Array operations on detection results |

---

## Action 1.4 — OCR Text Extraction

**File:** `ocr_service.py` → `OCRService.extract_text()`

**What it does:**
Reads all visible text from each video frame — phone numbers displayed on screen, email addresses in a profile, Aadhaar/PAN numbers on a document, UI labels, addresses. Returns the raw text string plus bounding box locations of where text appeared.

**Why this matters for compliance:**
Text on screen is the primary source of PII in app recordings and screen captures. Without OCR, the system would know a phone exists in the frame but not what number is displayed. OCR makes the text machine-readable so PII regex patterns can be applied.

**How it works — step by step (Hybrid approach):**

**Primary path — Tesseract:**
1. Checks if `pytesseract` is available and Tesseract binary is installed at `C:\Program Files\Tesseract-OCR\tesseract.exe`
2. If available: runs `pytesseract.image_to_data()` on the frame image
3. Returns text with per-word confidence scores and bounding boxes

**Fallback path — OpenCV text region detection:**
1. Converts image to grayscale using `cv2.cvtColor()`
2. Applies binary thresholding at pixel value `150` using `cv2.threshold()`
3. Finds contours using `cv2.findContours()`
4. Filters contours to regions likely to contain text: `width > 20px, height > 10px`
5. Returns the bounding boxes as detected text regions (without reading the actual characters)

This fallback ensures the pipeline never crashes — object detection alone is still compliance-useful even without full OCR.

**Libraries used:**

| Library | Role |
|---|---|
| `pytesseract` | Python wrapper for Tesseract OCR engine |
| Tesseract 5.4.0 | OCR binary (external install) — reads characters from images |
| `opencv-python` (cv2) | Image preprocessing, thresholding, contour detection (fallback) |
| `numpy` | Array operations for image manipulation |

---

## Action 1.5 — PII Detection via Regex

**File:** `video_content_vectorizer.py` → `_detect_pii_in_text()` / `extract_pii_from_video.py`

**What it does:**
Scans the OCR-extracted text from every frame against 11 regex patterns covering Indian and international PII types. Records what PII was found, where (frame number + timestamp), and the matched value.

**Why this matters:**
This is the deterministic compliance output — it gives exact, explainable results. Unlike an LLM guessing "this might be a phone number," regex either matches or it doesn't. The PII list + timestamps become the primary evidence in compliance findings.

**PII patterns detected:**

| PII Type | Regex Pattern | Example Match |
|---|---|---|
| Indian Phone | `\+?91[-.\s]?[6-9]\d{9}` | `+91-7358050632` |
| International Phone | `\+\d{1,3}[-.\s]?\d{4,14}` | `+1-800-555-1234` |
| 10-digit Mobile | `\b[6-9]\d{9}\b` | `9036337803` |
| Email | `\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b` | `user@gmail.com` |
| Credit Card | `\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b` | `4111-1111-1111-1111` |
| Aadhaar | `\b\d{4}[-\s]\d{4}[-\s]\d{4}\b` | `1234 5678 9012` |
| PAN Card | `\b[A-Z]{5}\d{4}[A-Z]\b` | `ABCDE1234F` |
| IP Address | `\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b` | `192.168.1.1` |
| Date of Birth | `\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b` | `15/08/1990` |
| URL | `https?://[^\s]+` | `https://example.com` |
| US SSN | `\b\d{3}-\d{2}-\d{4}\b` | `123-45-6789` |

**Libraries used:**

| Library | Role |
|---|---|
| `re` (Python stdlib) | Regex pattern matching |

---

## Action 1.6 — Text Description Construction

**File:** `video_content_vectorizer.py` → `create_frame_description()`

**What it does:**
Merges all extracted information for a single frame — detected objects, OCR text, and timestamp — into one coherent text string. This string is what gets embedded and stored in Weaviate.

**Why this matters:**
Vector embeddings work on text. The frame has multiple data types (visual objects, text, timestamps) that must be combined into a single representation before embedding. The format is structured so semantic search ("frames with phone numbers and people") can find relevant frames.

**Output format:**
```
At timestamp 5.93 seconds (frame 12):
Objects visible: person, cell phone
Text displayed: +91-7358050632 VEALTHX APP Welcome
```

**Libraries used:**

| Library | Role |
|---|---|
| Python stdlib (`str`) | String formatting only — no external dependencies |

---

## Action 1.7 — Vector Embedding Generation

**File:** `embedding_service.py` → `EmbeddingService.embed()` / `embed_batch()`

**What it does:**
Converts each frame's text description into a 768-dimensional vector of floating point numbers. Semantically similar descriptions produce vectors that are mathematically close together in the 768-dimensional space.

**Why this matters:**
Text cannot be searched by meaning directly. By converting to vectors, the system can answer queries like *"show me frames where someone is using a phone"* — even if the frame description says *"person, mobile device, contact list"* — because the vectors are close in meaning.

**How it works — step by step:**
1. Loads `all-mpnet-base-v2` model from HuggingFace on first call (cached locally)
2. For a single text: `self.model.encode(text)` → numpy array of 768 floats
3. For batch processing: `self.model.encode(texts, batch_size=32, show_progress_bar=True)` — processes 32 descriptions at once for efficiency
4. Returns the embedding as a Python `List[float]`

**Model specifications:**
- Model: `sentence-transformers/all-mpnet-base-v2`
- Dimensions: `768`
- Max input length: `384 tokens`
- Training: Trained on 1 billion+ sentence pairs for semantic similarity
- Runs: Fully local on CPU (no API calls, no cost)

**Libraries used:**

| Library | Role |
|---|---|
| `sentence-transformers` | Model loading and embedding generation |
| `torch` (PyTorch) | Neural network backend for the transformer model |
| `transformers` (HuggingFace) | Underlying MPNet model architecture |
| `numpy` | Array operations on embedding output |

---

## Action 1.8 — Vector Storage in Weaviate

**File:** `vector_store.py` → `VectorStore.add_video_content()`

**What it does:**
Stores each frame's embedding vector along with its metadata (video ID, timestamp, frame number, detected objects, OCR text, MinIO frame URL) in the Weaviate vector database. Creates the `VideoContent` collection if it doesn't exist.

**Why this matters:**
Embeddings need a specialized database for fast similarity search. Weaviate can search across millions of vectors in under 100ms — returning the most semantically similar frames for any query. This enables Step 3's semantic enrichment node to find relevant frames by meaning.

**How it works — step by step:**
1. Connects to Weaviate at `http://localhost:8080` (via gRPC port `50051` for data operations)
2. Checks if `VideoContent` collection exists; creates it with Euclidean distance metric if not
3. For each frame, calls `collection.data.insert(properties=data, vector=embedding)`
4. Properties stored: `video_id`, `content_type`, `timestamp`, `frame_number`, `text` (full description), `frame_url` (MinIO path)
5. Returns the Weaviate UUID of the stored object — saved back to PostgreSQL `frame_analyses.weaviate_id`

**Collection schema:**
- Collection name: `VideoContent`
- Distance metric: Euclidean
- Vectorizer: None (we supply pre-computed embeddings)

**Libraries used:**

| Library | Role |
|---|---|
| `weaviate-client` | Python SDK for Weaviate vector database |
| gRPC (built into weaviate-client) | High-performance binary protocol for data operations |

---

## Action 1.9 — Structured Storage in PostgreSQL

**File:** `video_content_vectorizer.py` → saves to `frame_analyses` table

**What it does:**
Stores the structured per-frame results in PostgreSQL for SQL queries, joins, and filtering. Every frame gets a row with YOLO detections, OCR text, processing flags, and a link back to its Weaviate vector via `weaviate_id`.

**Why this matters:**
Weaviate handles semantic search but cannot do SQL joins, COUNT queries, or filtering by multiple columns efficiently. PostgreSQL handles structured queries like "get all frames for video X with persons detected" which Step 3 uses to load frame data.

**Table: `frame_analyses`**

| Column | Type | Content |
|---|---|---|
| `id` | UUID | Primary key |
| `video_id` | FK | Links to `videos` table |
| `frame_number` | Integer | Frame sequence number |
| `timestamp` | Float | Time in video (seconds) |
| `minio_path` | String | Path to JPEG in MinIO |
| `objects_detected` | JSON | List of `{label, confidence, bbox}` from YOLO |
| `faces_detected` | Integer | Count of faces in frame |
| `persons_detected` | Integer | Count of persons in frame |
| `ocr_text` | Text | All text read from frame |
| `weaviate_id` | String | UUID linking to Weaviate `VideoContent` object |

**Libraries used:**

| Library | Role |
|---|---|
| `SQLAlchemy` | ORM for PostgreSQL operations |
| `psycopg2-binary` | PostgreSQL database driver |
| `alembic` | Database migration management |

---

---

# STEP 2 — DPDPA Rule Definitions (One-Time Setup)

**Trigger:** Run once when deploying the system (or when DPDPA rules are updated).
**Goal:** Load all 36 DPDPA 2023 + DPDP Rules 2025 compliance rules into both PostgreSQL (for structured queries) and Weaviate (for semantic matching).
**Source files:** `backend/app/dpdpa/`, `backend/app/services/guideline_loader.py`

---

## Action 2.1 — Rule Definition as Python Dataclasses

**File:** `app/dpdpa/definitions.py`

**What it does:**
Defines all 36 DPDPA compliance rules as Python `@dataclass` objects — a machine-readable rulebook. Each rule captures not just the legal text but also how to detect it, what penalty it carries, and which Step 1 pipeline outputs trigger it.

**Why this matters:**
Compliance rules need to be more than text descriptions. For the system to automatically check violations, each rule must specify: *what to look for* (`check_types`), *what constitutes a violation* (`violation_condition`), and *how serious it is* (`severity`, `penalty_ref`). This bridges legal language and code.

**`DPDPARule` dataclass fields:**

| Field | Type | Example |
|---|---|---|
| `rule_id` | str | `"DPDPA-S4-001"` |
| `name` | str | `"Consent Before Processing"` |
| `section_ref` | str | `"Section 4"` |
| `category` | str | `"consent"` |
| `requirement_text` | str | Full legal text of the rule |
| `severity` | str | `"critical"` / `"warning"` / `"info"` |
| `check_types` | List[str] | `["consent_indicator", "visual_person_detection"]` |
| `violation_condition` | str | What the system should flag as a violation |
| `applicability` | str | When this rule applies |
| `penalty_ref` | str | `"Section 33(d) - up to 150 crore INR"` |
| `video_specific` | bool | Whether this rule is specifically about video/CCTV |
| `detection_guidance` | str | Hints for the LangGraph agent (Step 3) |

**36 rules across 10 categories:**

| # | Category | Section | Count | Max Penalty |
|---|---|---|---|---|
| 1 | Consent | Section 4, Rule 3 | 7 | 150 crore |
| 2 | Data Principal Rights | Sections 11–14 | 5 | 100 crore |
| 3 | Data Fiduciary Obligations | Section 8 | 5 | 250 crore |
| 4 | Significant Data Fiduciary | Section 10, Rule 13 | 3 | 250 crore |
| 5 | Children's Data | Section 9 | 3 | 200 crore |
| 6 | Data Retention | Section 8(7), Rule 8 | 3 | 250 crore |
| 7 | Breach Notification | Rule 7 | 2 | 200 crore |
| 8 | Cross-Border Transfer | Section 16 | 2 | 250 crore |
| 9 | Purpose Limitation | Sections 5–6 | 2 | 150 crore |
| 10 | Video-Specific PII | Sections 4, 8 | 4 | 250 crore |

**Check type → DPDPA rules bridge (what Step 1 detects triggers which rules):**

| Step 1 Detects | Check Type | Rules Triggered |
|---|---|---|
| YOLO: `person` in frame | `visual_person_detection` | Consent, purpose limitation |
| YOLO: face detected | `visual_face_detection` | Facial recognition consent, biometric data |
| OCR: text in frame | `ocr_text_detection` | Notice requirements, OCR text as personal data |
| OCR + PII regex match | `ocr_pii_detection` | PII visible in video, security safeguards |
| Audio transcript PII | `audio_pii_detection` | PII spoken aloud |
| YOLO: child detected | `children_detection` | Parental consent, no tracking of minors |
| OCR: consent text found | `consent_indicator` | All consent rules |
| Video age > 90 days | `data_retention` | CCTV retention limit, erasure rules |

**Libraries used:**

| Library | Role |
|---|---|
| `dataclasses` (Python stdlib) | `@dataclass` decorator for rule objects |
| `typing` (Python stdlib) | Type hints (`List`, `Dict`, `Optional`) |

---

## Action 2.2 — Penalty Schedule Definition

**File:** `app/dpdpa/penalty_schedule.py`

**What it does:**
Defines the 5 penalty tiers from DPDPA Section 33 as Python dataclasses. Each penalty tier specifies the maximum fine, which section it comes from, and which rule categories it covers. Helper functions map any rule category to its applicable penalty tier.

**Why this matters:**
Compliance findings must include penalty exposure to be actionable. A finding that says "PII visible without consent" is not as useful as one that says "PII visible without consent — up to 150 crore INR penalty under Section 33(d)." The penalty schedule links every violation to its legal and financial consequence.

**5 penalty tiers (DPDPA Section 33):**

| Tier | Section | Violation Type | Max Penalty |
|---|---|---|---|
| PEN-001 | 33(a) | Security safeguard failures | 250 crore INR (~$30M USD) |
| PEN-002 | 33(b) | Breach notification failures | 200 crore INR (~$24M USD) |
| PEN-003 | 33(c) | Children's data violations | 200 crore INR (~$24M USD) |
| PEN-004 | 33(d) | Consent / notice failures | 150 crore INR (~$18M USD) |
| PEN-005 | 33(e) | Data principal rights denials | 100 crore INR (~$12M USD) |

**Libraries used:**

| Library | Role |
|---|---|
| `dataclasses` (Python stdlib) | `@dataclass` for `PenaltyTier` objects |

---

## Action 2.3 — Rule Embedding Generation

**File:** `guideline_loader.py` → `GuidelineLoader.load_all_rules()`

**What it does:**
For each of the 36 rules, creates a rich text representation combining multiple fields, then generates a 768-dimensional embedding. Embedding multiple fields (not just the requirement text) produces better semantic search — the agent in Step 3 can find relevant rules even when the query doesn't use the same words as the rule.

**Embedding text format (concatenated):**
```
{requirement_text}
Violation: {violation_condition}
Applicability: {applicability}
Detection: {detection_guidance}
```

**How it works — step by step:**
1. Calls `get_all_rules()` to get all 36 `DPDPARule` objects
2. Builds the embedding text string for each rule (4 fields concatenated)
3. Calls `EmbeddingService.embed_batch(embedding_texts)` — processes all 36 in one batch for efficiency
4. Stores each embedding alongside the rule in Weaviate

**Libraries used:**

| Library | Role |
|---|---|
| `sentence-transformers` | Batch embedding generation |
| `torch` (PyTorch) | Neural network backend |

---

## Action 2.4 — Rule Storage in Weaviate

**File:** `guideline_loader.py` → `VectorStore.add_guideline()`

**What it does:**
Stores each rule's embedding vector plus its metadata in the Weaviate `Guidelines` collection. This enables semantic search — Step 3 can query "what rules apply to face detection in a video?" and get ranked results by meaning.

**Properties stored in Weaviate:**

| Property | Content |
|---|---|
| `guideline_id` | The DPDPA rule ID (e.g., `"DPDPA-S4-001"`) |
| `regulation_type` | `"DPDPA"` |
| `clause_number` | Section reference (e.g., `"Section 4"`) |
| `requirement_text` | Full requirement text |
| `severity` | `"critical"` / `"warning"` / `"info"` |
| `category` | Rule category (e.g., `"consent"`) |
| `metadata` | JSON string: check_types, violation_condition, penalty_ref |

**Libraries used:**

| Library | Role |
|---|---|
| `weaviate-client` | Python SDK for Weaviate vector database |

---

## Action 2.5 — Rule Storage in PostgreSQL

**File:** `guideline_loader.py` → saves to `guidelines` table via SQLAlchemy

**What it does:**
Stores each rule in the `guidelines` PostgreSQL table for structured queries. The `weaviate_id` column links each PostgreSQL row to its vector in Weaviate — enabling the system to go from a semantic search result to the full rule definition instantly.

**Table: `guidelines` (DPDPA-specific columns added in Step 2):**

| Column | Type | Content |
|---|---|---|
| `id` | UUID | Primary key |
| `name` | String | Rule ID (e.g., `"DPDPA-S4-001"`) |
| `regulation_type` | String | `"DPDPA"` |
| `requirement_text` | Text | Full rule text |
| `severity` | Enum | `critical` / `warning` / `info` |
| `clause_number` | String | Section reference |
| `penalty_ref` | String | Penalty text with amount |
| `check_types_json` | JSON | List of check types this rule responds to |
| `category` | String | Rule category |
| `weaviate_id` | String | UUID linking to Weaviate vector |

**Verification (run after loading):**
```powershell
venv\Scripts\python.exe load_dpdpa_rules.py --verify
# Expected: PostgreSQL: 36 OK | Weaviate: 36 OK | All OK: True
```

**Libraries used:**

| Library | Role |
|---|---|
| `SQLAlchemy` | ORM for PostgreSQL |
| `psycopg2-binary` | PostgreSQL driver |

---

---

# STEP 3 — LangGraph Compliance Agent

**Trigger:** Called after Step 1 completes for a video (on demand or automatically).
**Goal:** Read the Step 1 pipeline outputs, systematically check them against all 36 DPDPA rules, generate a scored compliance report with a full audit trail.
**Source files:** `backend/app/langchain_components/agents/compliance_agent.py`, `backend/app/services/compliance_checker.py`

**The agent is a LangGraph state machine with 9 sequential nodes.** Each node receives the full state, does one focused job, and passes the enriched state to the next node.

**State object (`ComplianceState`) — passed through all 9 nodes:**

```python
class ComplianceState(TypedDict):
    video_id: str               # Which video is being checked
    frames: List[dict]          # FrameAnalysis rows from PostgreSQL
    transcripts: List[dict]     # TranscriptionSegment rows from PostgreSQL
    visual_findings: List[dict] # Findings from YOLO check (Node 2)
    ocr_findings: List[dict]    # Findings from OCR check (Node 3)
    audio_findings: List[dict]  # Findings from audio check (Node 4)
    metadata_findings: List[dict] # Findings from retention check (Node 5)
    all_findings: List[dict]    # Merged + deduplicated (Node 7)
    report_data: dict           # Score + status (Node 8)
    report_id: str              # Database ID (Node 9)
    audit_entries: List[dict]   # Accumulated step-by-step log
    errors: List[str]           # Any non-fatal errors
    use_llm: bool               # Whether to call Ollama for narrative
```

---

## Node 3.1 — `load_video_data`

**What it does:**
Fetches all frame analysis rows and transcription segments for the video from PostgreSQL. This is the data that Step 1 produced — YOLO detections, OCR text, timestamps. It loads all of this into the LangGraph state so subsequent nodes can work from memory without repeated database calls.

**How it works — step by step:**
1. Opens a PostgreSQL session via `SessionLocal()`
2. Queries `frame_analyses` table: `WHERE video_id = X ORDER BY timestamp`
3. Queries `transcription_segments` table: `WHERE video_id = X ORDER BY start_time`
4. Converts each SQLAlchemy row to a plain `dict` for easy access in subsequent nodes
5. Adds an audit log entry: `"Loaded 5 frames and 2 transcript segments for video X"`

**Output added to state:** `frames` list, `transcripts` list

**Libraries used:**

| Library | Role |
|---|---|
| `SQLAlchemy` | Database session and query |
| `langgraph` | State passing between nodes |

---

## Node 3.2 — `check_visual_rules`

**What it does:**
For every frame, looks at the YOLO-detected objects and maps them to DPDPA check types. If a `person` is detected → triggers `visual_person_detection` rules. If a face is detected → triggers `visual_face_detection` rules. Each triggered check type fetches the associated DPDPA rules and creates a potential finding.

**How it works — step by step:**
1. Iterates through each frame in state
2. Extracts object labels from `objects_detected` JSON (e.g., `["person", "cell phone"]`)
3. Maps labels to check types using a lookup dict:
   - `"person"` → `visual_person_detection`
   - `"face"` → `visual_face_detection`
   - `"child"`, `"boy"`, `"girl"` → `children_detection`
4. Also checks `faces_detected > 0` → adds `visual_face_detection`
5. For each triggered check type, calls `get_rules_by_check_type()` → gets matching `DPDPARule` objects
6. Creates a finding dict for each rule with: rule details, frame evidence, timestamp, objects detected
7. Logs each rule trigger to the audit trail: `"Frame 1 at 5.9s: visual_person_detection -> triggered rule DPDPA-S4-001"`

**Output added to state:** `visual_findings` list (one entry per frame × rule triggered)

**Libraries used:**

| Library | Role |
|---|---|
| `app.dpdpa.definitions` | `get_rules_by_check_type()` — maps check type to rules |

---

## Node 3.3 — `check_ocr_rules`

**What it does:**
For every frame that has OCR text, runs the 11 PII regex patterns against that text. If PII is found (phone number, email, Aadhaar, etc.), it triggers `ocr_pii_detection` rules (PII visible in video without masking). It also triggers `ocr_text_detection` rules for any frame with OCR text regardless of PII.

**How it works — step by step:**
1. Iterates through frames that have non-empty `ocr_text`
2. Runs all 11 PII regex patterns against the OCR text using `re.findall()`
3. If PII found → fetches `ocr_pii_detection` rules (e.g., DPDPA-VID-001, DPDPA-S8-002)
4. Creates findings with: which PII types were matched, the actual matched strings, which frame/timestamp
5. Also fetches `ocr_text_detection` rules for all frames with text (OCR text = personal data rule)
6. Logs: `"Frame 3 at 22.5s: PII found in OCR text -> triggered rule DPDPA-S8-002"`

**PII types detected:** `phone_india`, `phone_intl`, `phone_10`, `email`, `credit_card`, `aadhaar`, `pan`, `ip_address`, `dob`, `url`, `ssn`

**Output added to state:** `ocr_findings` list

**Libraries used:**

| Library | Role |
|---|---|
| `re` (Python stdlib) | 11 PII regex pattern matching |
| `app.dpdpa.definitions` | `get_rules_by_check_type()` |

---

## Node 3.4 — `check_audio_rules`

**What it does:**
Runs the same 11 PII regex patterns against each transcription segment's text. If someone spoke a phone number or email address aloud in the video, this node catches it and maps it to `audio_pii_detection` rules.

**How it works — step by step:**
1. Iterates through transcript segments from state
2. Applies all 11 PII regex patterns to each segment's `text` field
3. If PII found → fetches `audio_pii_detection` rules
4. Creates findings with: start/end timestamp of the speech, which PII types were spoken
5. Logs: `"Audio at 15.0s-18.5s: PII found in transcript -> triggered rule DPDPA-VID-002"`

**Output added to state:** `audio_findings` list

**Libraries used:**

| Library | Role |
|---|---|
| `re` (Python stdlib) | PII regex matching on transcription text |
| `app.dpdpa.definitions` | `get_rules_by_check_type()` |

---

## Node 3.5 — `check_metadata_rules`

**What it does:**
Checks video-level metadata for DPDPA violations that don't require frame-by-frame analysis. Currently checks **data retention**: if the video is older than 90 days, DPDPA Section 8(7) is violated (CCTV footage must not be kept longer than 90 days without legal justification).

**How it works — step by step:**
1. Fetches the `Video` row from PostgreSQL to get `created_at` timestamp
2. Calculates `age_days = (now - created_at).days`
3. If `age_days > 90` → fetches `data_retention` rules (DPDPA-RET-001, DPDPA-CCTV-001)
4. Creates a finding with: how many days past the retention limit, which rules are violated
5. Logs: `"Video age 95 days exceeds 90-day CCTV retention limit -> triggered rule DPDPA-CCTV-001"`

**Output added to state:** `metadata_findings` list

**Libraries used:**

| Library | Role |
|---|---|
| `SQLAlchemy` | `Video` model query |
| `datetime` (Python stdlib) | Age calculation |
| `app.dpdpa.definitions` | `get_rules_by_check_type()` |

---

## Node 3.6 — `semantic_enrich`

**What it does:**
Uses Weaviate's semantic search to find DPDPA rules that weren't caught by the deterministic check-type mapping in nodes 2–5. For each high-risk frame (one with persons or OCR text), it builds a natural language description and searches the Weaviate `Guidelines` collection for semantically similar rules.

**Why this matters:**
The check-type mapping in nodes 2–5 is rule-based — it only catches rules explicitly linked to detected check types. Semantic search catches rules where the meaning matches even if the exact keywords don't. This is the "catch everything else" safety net.

**How it works — step by step:**
1. Builds a set of already-found `rule_id` values to avoid duplicates
2. Selects up to 5 high-risk frames (those with `persons_detected > 0` or non-empty OCR text)
3. For each selected frame, constructs a query string:
   `"Person detected in video frame at 5.9s. Objects: person, cell phone. OCR text: +91-7358050632"`
4. Calls `EmbeddingService.embed(query_text)` → 768-dim embedding
5. Calls `VectorStore.search_guidelines(embedding, limit=5)` → top 5 semantically similar rules
6. For each result with similarity > 0.6 (60% threshold): creates a finding
7. Logs: `"Semantic search: frame 1 -> rule DPDPA-S4-003 (similarity=0.731)"`

**Output added to state:** extra findings merged into `visual_findings`

**Libraries used:**

| Library | Role |
|---|---|
| `sentence-transformers` | Embedding query text for vector search |
| `weaviate-client` | `near_vector` semantic search on Guidelines collection |
| `app.dpdpa.definitions` | Rule lookup by ID |

---

## Node 3.7 — `synthesize_findings`

**What it does:**
Merges all findings from nodes 2–6 into a single deduplicated, sorted list. The same DPDPA rule can be triggered multiple times by different frames — this node collapses duplicates and keeps the finding with the highest confidence score.

**How it works — step by step:**
1. Combines all finding lists: `visual_findings + ocr_findings + audio_findings + metadata_findings`
2. Deduplication key: `(rule_id, frame_number, source)` — same rule on same frame from same source = duplicate
3. When duplicate found: keeps the finding with the higher `similarity_score`
4. Sorts results: first by severity (`critical` > `warning` > `info`), then by timestamp
5. Logs: `"Synthesized 62 raw findings -> 60 unique findings after deduplication"`

**Output added to state:** `all_findings` list (final deduplicated findings)

**Libraries used:**

| Library | Role |
|---|---|
| Python stdlib (`dict`, `sorted`) | Deduplication and sorting logic |

---

## Node 3.8 — `generate_report`

**What it does:**
Computes the final compliance score and status from the deduplicated findings. This is Phase 1 — purely mathematical, no LLM involved, results are instant. Phase 2 (Ollama LLM writing the executive summary in prose) runs optionally in the background.

**How it works — step by step:**
1. Counts unique violated rules: `failed_checks = len(set(finding["rule_id"] for finding in all_findings))`
2. Counts by severity: `critical_violations`, `warnings`, `info` counts from finding severities
3. Calculates penalty score: `(critical × 5) + (warning × 2) + (info × 1)`
4. Computes compliance score: `max(0.0, 100.0 - penalty_score)`
5. Determines status:
   - `"compliant"` → 0 failed checks
   - `"non_compliant"` → any critical violations
   - `"partial"` → warnings only, no criticals
6. Packages into `report_data` dict and adds an audit entry with the score

**Output added to state:** `report_data` dict with `status`, `compliance_score`, `total_checks`, `failed_checks`, `critical_violations`, `warnings`

**Libraries used:**

| Library | Role |
|---|---|
| Python stdlib | Arithmetic and logic only |

---

## Node 3.9 — `save_to_db`

**What it does:**
Writes all results to PostgreSQL in a single transaction: updates the `ComplianceReport` row with the score and status, creates one `ComplianceFinding` row per unique violation, and bulk-inserts all audit log entries. This is the persistence step — everything before this existed only in memory.

**How it works — step by step:**
1. Finds or creates the `ComplianceReport` row (created earlier with `PENDING_REVIEW` status)
2. Updates report: status, score, counts, `completed_at` timestamp, executive summary placeholder
3. For each finding in `all_findings`:
   - Looks up the corresponding `Guideline` row by `Guideline.name == finding["rule_id"]`
   - Creates a `ComplianceFinding` row with: severity, description, timestamps, PII evidence, objects detected, similarity score
   - Stores full evidence chain in `visual_evidence` JSON column
4. For each audit entry accumulated across all nodes:
   - Maps step string to `AuditStep` enum
   - Creates an `AuditLog` row with: step, action, input_data, output_data, rule_id, timestamp, duration_ms, success
5. Commits everything in one `db.commit()` call — atomic, all-or-nothing

**3 tables written:**

| Table | Rows Written | Content |
|---|---|---|
| `compliance_reports` | 1 (updated) | Score, status, summary, timestamps |
| `compliance_findings` | 1 per unique violation | Evidence chain, severity, timestamps, PII matched |
| `audit_logs` | ~50 (one per pipeline action) | Full step-by-step paper trail |

**Libraries used:**

| Library | Role |
|---|---|
| `SQLAlchemy` | ORM — ComplianceReport, ComplianceFinding, AuditLog inserts |
| `psycopg2-binary` | PostgreSQL driver |

---

## Supporting Service: Data Lifecycle (`data_lifecycle.py`)

**What it does:**
After the compliance report is complete and reviewed, purges all raw personal data from the system. Only the compliance report, findings, and audit trail are kept. This implements DPDPA's own data minimisation principle.

**Purge sequence:**
1. Logs `DATA_PURGED` audit entry *before* deleting anything (immutable record of intent)
2. Deletes original video file from MinIO: `videos/{video_id}/`
3. Deletes extracted frame JPEGs from MinIO: `frames/{video_id}/`
4. Deletes frame vectors from Weaviate `VideoContent` collection
5. Deletes `frame_analyses` rows from PostgreSQL
6. Deletes `transcription_segments` rows from PostgreSQL
7. Logs completion audit entry with counts of what was deleted

**What is KEPT forever:**

| Data | Why Kept |
|---|---|
| `compliance_reports` | Legal evidence of compliance check |
| `compliance_findings` | Evidence chain for each violation |
| `audit_logs` | Tamper-evident paper trail for regulators |
| `guidelines` (DPDPA rules) | Reference data, not personal data |
| Weaviate `Guidelines` | Rule vectors, not personal data |

**Libraries used:**

| Library | Role |
|---|---|
| `minio` | Python SDK for MinIO object storage |
| `weaviate-client` | Deleting video vectors from Weaviate |
| `SQLAlchemy` | Deleting PostgreSQL rows |

---

---

# Complete Library Reference

## Step 1 Libraries

| Library | Version | Purpose |
|---|---|---|
| `opencv-python` | latest | Frame extraction, scene detection, image preprocessing |
| `ffmpeg-python` | latest | Video/audio demuxing, audio re-encoding |
| `ultralytics` | latest | YOLO v8 object detection |
| `pytesseract` | latest | Python wrapper for Tesseract OCR |
| Tesseract OCR | 5.4.0 | External OCR binary (Windows install) |
| `sentence-transformers` | latest | `all-mpnet-base-v2` embedding model |
| `torch` | latest | PyTorch backend for transformer models |
| `transformers` | latest | HuggingFace MPNet model architecture |
| `numpy` | latest | Array operations throughout pipeline |
| `weaviate-client` | latest | Weaviate vector database SDK |
| `SQLAlchemy` | latest | PostgreSQL ORM |
| `psycopg2-binary` | latest | PostgreSQL database driver |
| `minio` | latest | MinIO object storage SDK |

## Step 2 Libraries

| Library | Purpose |
|---|---|
| `dataclasses` (stdlib) | `@dataclass` for DPDPARule and PenaltyTier |
| `sentence-transformers` | Batch embedding of rule texts |
| `weaviate-client` | Storing rule vectors in Guidelines collection |
| `SQLAlchemy` | Storing rules in guidelines table |

## Step 3 Libraries

| Library | Purpose |
|---|---|
| `langgraph` | LangGraph state machine framework |
| `langchain` | LangChain base utilities |
| `sentence-transformers` | Embedding frame descriptions for semantic search |
| `weaviate-client` | Semantic search on Guidelines collection |
| `SQLAlchemy` | Reading frames, writing report + findings + audit logs |
| `re` (stdlib) | PII regex detection in OCR text and transcripts |
| `fastapi` | REST API endpoints for triggering checks and reading reports |
| `celery` | Background task queue for Phase 2 LLM summary (async) |
| `redis` | Celery broker |
| Ollama (Llama 3.1:8b) | Local LLM for Phase 2 narrative summary (optional) |

---

# Quick Reference: Source Files

```
backend/
├── load_dpdpa_rules.py              # Step 2 CLI: load/verify/search rules
├── run_compliance_check.py          # Step 3 CLI: run check, view report/audit

app/
├── config.py                        # All service URLs and model settings

├── dpdpa/
│   ├── definitions.py               # 36 DPDPA rules as dataclasses
│   ├── penalty_schedule.py          # 5 penalty tiers from Section 33
│   └── __init__.py                  # Package exports

├── models/
│   ├── video.py                     # Video upload record
│   ├── frame_analysis.py            # Per-frame YOLO + OCR results (Step 1 output)
│   ├── transcription.py             # Audio transcript segments (Step 1 output)
│   ├── guideline.py                 # DPDPA rules in PostgreSQL (Step 2 output)
│   ├── compliance_report.py         # ComplianceReport + ComplianceFinding
│   └── audit_log.py                 # AuditLog — full paper trail

├── services/
│   ├── frame_extractor.py           # Action 1.1 + 1.2 (frames + audio)
│   ├── visual_analyzer.py           # Action 1.3 (YOLO object detection)
│   ├── ocr_service.py               # Action 1.4 (Tesseract + OpenCV OCR)
│   ├── embedding_service.py         # Action 1.7 + 2.3 (sentence-transformers)
│   ├── vector_store.py              # Action 1.8 + 2.4 (Weaviate)
│   ├── video_content_vectorizer.py  # Step 1 orchestrator (all actions)
│   ├── guideline_loader.py          # Step 2 orchestrator (load rules)
│   ├── compliance_checker.py        # Step 3 orchestrator (run agent)
│   └── data_lifecycle.py            # Post-report raw data purge

├── langchain_components/
│   ├── agents/
│   │   └── compliance_agent.py      # LangGraph 9-node state machine
│   └── prompts/
│       └── compliance_prompts.py    # LLM prompt templates (Phase 2)

└── api/v1/
    └── compliance.py                # FastAPI REST endpoints

docker/
└── docker-compose.yml               # PostgreSQL, Weaviate, Redis, MinIO, Ollama
```

---

*Last updated: March 2026 — All 3 steps implemented and verified on test_video_001.*
*Test results: 36 DPDPA rules loaded | 60 compliance findings | 50 audit entries | Score: 0.0/100 (NON_COMPLIANT)*
