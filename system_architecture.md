# Regtech Video Compliance System - Comprehensive Technical Design

## Table of Contents
1. [Executive Summary](#executive-summary)
2. [High-Level System Architecture](#high-level-system-architecture)
3. [Core Application Layer](#core-application-layer)
4. [AI/ML Processing Services](#aiml-processing-services)
5. [Regulatory Intelligence Layer](#regulatory-intelligence-layer)
6. [Data Storage Architecture](#data-storage-architecture)
7. [System Interaction Diagrams](#system-interaction-diagrams)
8. [Technology Stack](#technology-stack)
9. [Deployment Architecture](#deployment-architecture)
10. [Module Dependency Graph](#module-dependency-graph)

---

## Executive Summary

The **Regtech Video Compliance System** is an AI-powered platform that automatically checks video content against the **Digital Personal Data Protection Act (DPDPA) 2023** and **DPDP Rules 2025** of India. The system uses 100% open-source AI models to extract, analyze, and evaluate video content for privacy compliance violations.

### Key Capabilities
- **Video Content Extraction**: Frame extraction, audio transcription, OCR text extraction, object detection
- **PII Detection**: 11+ regex patterns for Indian PII (Aadhaar, PAN, phone numbers, etc.)
- **Semantic Vectorization**: Converts video content to searchable vector embeddings
- **Compliance Checking**: Automated DPDPA rule violation detection
- **Evidence-Based Reporting**: Timestamps and frames for each violation

### Processing Pipeline Overview
```
Video Upload → Frame Extraction → AI Analysis → Vector Embeddings → 
Compliance Check → Violation Report
```

---

## High-Level System Architecture

```mermaid
graph TB
    subgraph "Client Layer"
        User([User/Browser])
        Frontend[React Frontend<br/>Port: 5173]
    end

    subgraph "API Layer"
        FastAPI[FastAPI Backend<br/>Port: 8000]
        CORS[CORS Middleware]
        Health[Health Check Endpoints]
    end

    subgraph "Task Queue"
        Celery[Celery Workers]
        Redis[(Redis<br/>Port: 6379)]
    end

    subgraph "AI Processing Pipeline"
        direction TB
        FrameExt[Frame Extractor<br/>OpenCV + FFmpeg]
        AudioTrans[Audio Transcriber<br/>Whisper]
        VisualAnal[Visual Analyzer<br/>YOLO v8]
        OCR[OCR Service<br/>Tesseract]
        Embed[Embedding Service<br/>sentence-transformers]
    end

    subgraph "Regulatory Engine"
        DPDPARules[DPDPA Rules Engine<br/>35+ Rules]
        PIIDetect[PII Detector<br/>11 Patterns]
        PenaltyCalc[Penalty Calculator<br/>5 Tiers]
    end

    subgraph "Storage Layer"
        PostgreSQL[(PostgreSQL<br/>Port: 5433)]
        Weaviate[(Weaviate Vector DB<br/>Port: 8080)]
        MinIO[(MinIO Object Storage<br/>Port: 9000)]
    end

    subgraph "LLM Service"
        Ollama[Ollama<br/>Port: 11434]
        Llama[Llama 3.1:8b Model]
    end

    User --> Frontend
    Frontend --> FastAPI
    FastAPI --> CORS
    FastAPI --> Health
    FastAPI --> Celery
    FastAPI --> PostgreSQL
    FastAPI --> Weaviate
    FastAPI --> MinIO
    
    Celery --> Redis
    Celery --> FrameExt
    Celery --> AudioTrans
    Celery --> VisualAnal
    Celery --> OCR
    Celery --> Embed
    Celery --> DPDPARules
    Celery --> PIIDetect
    
    FrameExt --> MinIO
    Embed --> Weaviate
    DPDPARules --> PostgreSQL
    DPDPARules --> Weaviate
    
    FastAPI -.-> Ollama
    Ollama --> Llama
```

---

## Core Application Layer

### 1. Application Entry Point (`backend/app/main.py`)

**Purpose**: FastAPI application initialization and lifecycle management

**Key Components**:
| Component | Description |
|-----------|-------------|
| `lifespan()` | Async context manager for startup/shutdown events |
| `app` | FastAPI instance with CORS middleware |
| Health endpoints | `/health` (basic), `/health/detailed` (with dependency checks) |
| Exception handlers | Global error handling with JSON responses |

**Dependencies Checked on Startup**:
- PostgreSQL (database connectivity)
- Redis (cache/task queue)
- MinIO (object storage buckets)
- Weaviate (vector database)
- Ollama (LLM service)

**Configuration Integration**:
```python
from app.config import settings
# Loads: APP_NAME, DATABASE_URL, REDIS_URL, etc.
```

### 2. Configuration Management (`backend/app/config.py`)

**Purpose**: Centralized configuration using Pydantic Settings

**Configuration Categories**:

| Category | Key Settings | Default Value |
|----------|--------------|---------------|
| **Application** | `APP_NAME`, `DEBUG`, `LOG_LEVEL` | "Regtech Video Compliance", True, "INFO" |
| **Database** | `DATABASE_URL` | postgresql://postgres:postgres@localhost:5433/regtech_db |
| **Redis** | `REDIS_URL` | redis://localhost:6379/0 |
| **MinIO** | `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY` | localhost:9000, minioadmin, minioadmin |
| **Weaviate** | `WEAVIATE_URL` | http://localhost:8080 |
| **Ollama** | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | http://localhost:11434, llama3.1:8b |
| **Models** | `WHISPER_MODEL`, `YOLO_MODEL`, `EMBEDDING_MODEL` | medium, yolov8n.pt, all-mpnet-base-v2 |
| **Processing** | `FRAME_EXTRACTION_FPS`, `MAX_CONCURRENT_JOBS` | 1, 3 |
| **Security** | `SECRET_KEY`, `JWT_SECRET_KEY`, `ACCESS_TOKEN_EXPIRE_MINUTES` | [dev keys], 30 |

**Property Methods**:
- `allowed_origins_list` → Parses comma-separated CORS origins
- `allowed_video_formats_list` → Parses video format extensions
- `ocr_languages_list` → Parses OCR language codes

### 3. Database Session Management (`backend/app/db/session.py`)

**Purpose**: SQLAlchemy database connection and session management

**Key Components**:
| Component | Function |
|-----------|----------|
| `engine` | SQLAlchemy engine with `pool_pre_ping=True` for connection validation |
| `SessionLocal` | Session factory for database transactions |
| `Base` | Declarative base class for ORM models |
| `get_db()` | Dependency generator for FastAPI route injection |
| `create_tables()` | Creates all tables from metadata |
| `drop_tables()` | Drops all tables (use with caution) |

---

## AI/ML Processing Services

### 1. Video Content Vectorizer (`backend/app/services/video_content_vectorizer.py`)

**Purpose**: Main orchestrator for the video processing pipeline (Step 1)

**Pipeline Flow**:
```
Video Input
    ↓
[Frame Extraction] → JPEG frames at 1 FPS + scene changes
    ↓
[Audio Extraction] → WAV file (16kHz, mono, PCM 16-bit)
    ↓
[Parallel Processing]
    ├── Visual Analysis (YOLO) → Object detection
    ├── OCR (Tesseract) → Text extraction
    └── Audio Transcription (Whisper) → Speech-to-text
    ↓
[Text Description Creation] → Structured descriptions
    ↓
[Embedding Generation] → 768-dim vectors
    ↓
[Vector Storage] → Weaviate batch insert
```

**Class: `VideoContentVectorizer`**

| Method | Purpose | Input | Output |
|--------|---------|-------|--------|
| `__init__()` | Initialize all services | - | Service instances |
| `process_video()` | Main pipeline entry | video_path, video_id | Processing stats dict |
| `_process_frames()` | Analyze frames with OCR/Visual | frame list | Frame data dicts |
| `_vectorize_and_store()` | Create embeddings and store | frame_data, transcriptions | Vector count |
| `search_video_content()` | Semantic search | query string | Search results |
| `cleanup_video()` | Remove video data | video_id | - |

**Processing Configuration**:
- Max frames: 50 (configurable)
- Scene change threshold: 30.0 (pixel mean difference)
- Video duration cap: 10 minutes (600 seconds)
- Frame quality: JPEG 90

### 2. Frame Extractor (`backend/app/services/frame_extractor.py`)

**Purpose**: Extract frames and audio from video files

**Class: `FrameExtractor`**

| Method | Description |
|--------|-------------|
| `extract_frames()` | Main extraction with scene detection |
| `_extract_fixed_fps()` | Fixed interval extraction |
| `_extract_with_scene_detection()` | Scene change + interval extraction |
| `get_video_info()` | FFmpeg probe for metadata |
| `extract_audio()` | Extract WAV audio track |

**Data Class: `ExtractedFrame`**
```python
@dataclass
class ExtractedFrame:
    frame_number: int
    timestamp: float  # seconds
    file_path: str
    is_scene_change: bool
```

**Video Info Extracted**:
- Duration, format, file size
- Resolution (width x height)
- FPS, codec
- Audio presence and codec

### 3. Visual Analyzer (`backend/app/services/visual_analyzer.py`)

**Purpose**: Object detection using YOLO v8

**Class: `VisualAnalyzer`**

| Method | Purpose |
|--------|---------|
| `analyze_image()` | Detect all objects in image |
| `detect_persons()` | Filter for person class only |
| `get_summary()` | Get object counts and metadata |
| `annotate_image()` | Create visualization with bounding boxes |
| `batch_analyze()` | Process multiple images |
| `detect_pii_indicators()` | Detect devices that might display PII |

**YOLO Configuration**:
- Model: yolov8n.pt (nano, fastest)
- Confidence threshold: 0.25
- IoU threshold: 0.45
- Classes: 80 (COCO dataset)

**Key Object Classes for Compliance**:
- `person` → Consent requirements
- `cell phone`, `laptop`, `monitor` → PII display risk
- `book`, `keyboard` → Data entry indicators

**Data Class: `DetectedObject`**
```python
@dataclass
class DetectedObject:
    class_name: str
    confidence: float
    bounding_box: List[float]  # [x1, y1, x2, y2]
    class_id: int
```

### 4. OCR Service (`backend/app/services/ocr_service.py`)

**Purpose**: Text extraction from video frames

**Class: `OCRService`**

| Method | Description |
|--------|-------------|
| `extract_text()` | Main entry with fallback |
| `_extract_with_tesseract()` | Primary OCR using Tesseract |
| `_extract_with_fallback()` | OpenCV-based text region detection |
| `get_full_text()` | Concatenate all extracted text |
| `detect_sensitive_info()` | Pattern-based sensitive data detection |
| `extract_text_with_visualization()` | OCR with bounding box visualization |

**Tesseract Configuration**:
- Windows path: `C:\Program Files\Tesseract-OCR\tesseract.exe`
- Languages: English (configurable)
- Output: Bounding boxes + confidence scores

**Fallback Detection**:
- Binary threshold: 150
- Min region size: 20x10 pixels
- Max region size: 80% of image dimensions

**Data Class: `OCRResult`**
```python
@dataclass
class OCRResult:
    text: str
    confidence: float
    bounding_box: List[List[int]]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
```

### 5. Audio Transcriber (`backend/app/services/audio_transcriber.py`)

**Purpose**: Speech-to-text using OpenAI Whisper (local)

**Class: `AudioTranscriber`**

| Method | Description |
|--------|-------------|
| `transcribe()` | Full transcription with timestamps |
| `get_segments()` | Get timed transcription segments |
| `get_full_text()` | Plain text without timestamps |
| `detect_language()` | Auto-detect audio language |
| `transcribe_with_speaker_diarization()` | Basic speaker separation |

**Whisper Models** (configurable):
- `tiny` - Fastest, lowest accuracy
- `small` - Balanced
- `medium` - Default, good accuracy
- `large` - Best accuracy, slowest

**Data Class: `TranscriptionSegment`**
```python
@dataclass
class TranscriptionSegment:
    start: float  # seconds
    end: float
    text: str
    confidence: Optional[float]
```

### 6. Embedding Service (`backend/app/services/embedding_service.py`)

**Purpose**: Convert text to vector embeddings for semantic search

**Class: `EmbeddingService`**

| Method | Description |
|--------|-------------|
| `embed()` | Single text embedding |
| `embed_batch()` | Batch embedding (efficient) |
| `similarity()` | Cosine similarity between texts |
| `find_most_similar()` | Top-k similar texts |
| `get_model_info()` | Model metadata |

**Model: `all-mpnet-base-v2`**
- Dimensions: 768
- Framework: sentence-transformers
- Max sequence length: 512 tokens
- Device: Auto (CUDA if available, else CPU)

**Utility Functions**:
- `create_frame_description()` - Format frame analysis for embedding
- `create_transcription_description()` - Format transcription for embedding
- `chunk_text()` - Split long text with overlap

**Data Class: `EmbeddingResult`**
```python
@dataclass
class EmbeddingResult:
    text: str
    embedding: List[float]
    model_name: str
```

### 7. Vector Store (`backend/app/services/vector_store.py`)

**Purpose**: Weaviate vector database integration

**Class: `VectorStore`**

| Method | Collection | Description |
|--------|------------|-------------|
| `add_video_content()` | VideoContent | Store frame/transcription vectors |
| `add_video_content_batch()` | VideoContent | Batch insert for efficiency |
| `search_video_content()` | VideoContent | Semantic search with filters |
| `add_guideline()` | Guidelines | Store DPDPA rule vectors |
| `search_guidelines()` | Guidelines | Find relevant compliance rules |
| `delete_video_content()` | VideoContent | Remove video data |
| `get_stats()` | Both | Collection statistics |

**Weaviate Collections**:

**VideoContent**:
```python
Properties:
- video_id (text)
- content_type (text)  # "frame", "transcription", "ocr"
- timestamp (number)
- text (text)
- frame_number (int)
- frame_url (text)
- metadata (text)  # JSON string
```

**Guidelines**:
```python
Properties:
- guideline_id (text)
- regulation_type (text)  # "DPDPA", "GDPR"
- clause_number (text)
- requirement_text (text)
- severity (text)
- category (text)
- metadata (text)
```

**Data Class: `SearchResult`**
```python
@dataclass
class SearchResult:
    id: str
    text: str
    metadata: Dict
    score: float  # Similarity score (0-1)
```

---

## Regulatory Intelligence Layer

### 1. DPDPA Rule Definitions (`backend/app/dpdpa/definitions.py`)

**Purpose**: Structured definitions of all DPDPA 2023/2025 compliance rules

**Data Class: `DPDPARule`**
```python
@dataclass
class DPDPARule:
    rule_id: str              # e.g., "DPDPA-S4-001"
    name: str                 # e.g., "Consent Before Processing"
    section_ref: str          # e.g., "Section 4"
    category: str             # e.g., "consent"
    requirement_text: str     # Full rule description
    severity: str             # "critical" / "warning" / "info"
    check_types: List[str]    # What to check in pipeline output
    violation_condition: str  # What constitutes a violation
    applicability: str        # When this rule applies
    penalty_ref: str          # e.g., "Section 33(d) - up to 150 crore"
    video_specific: bool      # Is this video/CCTV specific
    detection_guidance: str   # Hints for LangGraph agent
    exemptions: List[str]     # Rule exemptions
    related_rules: List[str]  # Cross-references
```

**Rule Categories (10 Total, ~35 Rules)**:

| Category | Section | Rule Count | Key Rules |
|----------|---------|------------|-----------|
| **Consent** | Section 4, Rule 3 | 7 | Consent before processing, informed notice, facial recognition consent |
| **Data Principal Rights** | Sections 11-14 | 5 | Access, correction, erasure, grievance, nomination |
| **Data Fiduciary Obligations** | Section 8 | 5 | Security safeguards, purpose limitation, data accuracy, breach notification |
| **SDF Obligations** | Section 10, Rule 13-14 | 3 | DPIA requirement, DPO appointment, enhanced controls |
| **Children's Data** | Section 9 | 3 | Parental consent, no tracking, no detrimental processing |
| **Data Retention** | Section 8(7), Rule 8 | 3 | Retention limits, CCTV 90-day max, erasure after purpose |
| **Breach Notification** | Rule 7 | 2 | Notify Board, notify data principals |
| **Cross-Border Transfer** | Section 16 | 2 | Transfer restrictions, additional consent |
| **Purpose Limitation** | Sections 5-6 | 2 | Purpose specification, no function creep |
| **Video-Specific PII** | Section 4, 8 | 4 | PII in frames, PII in audio, face as biometric, OCR text as personal data |

**Check Types** (Bridge between Step 1 and Step 2):
- `visual_person_detection` → YOLO finds persons
- `visual_face_detection` → Face/biometric detection
- `ocr_text_detection` → Text visible on screen
- `ocr_pii_detection` → PII patterns in OCR text
- `audio_pii_detection` → PII in transcription
- `consent_indicator` → Consent banners/notices
- `children_detection` → Minors in video
- `data_retention` → Storage duration checks
- `cross_border_transfer` → Data transfer indicators
- `metadata_check` → System/metadata analysis

**Helper Functions**:
- `get_all_rules()` → Returns all ~35 rules
- `get_category_rules(category)` → Rules by category
- `get_video_specific_rules()` → Video-specific rules only
- `get_rules_by_check_type(check_type)` → Rules requiring specific check
- `get_rules_by_severity(severity)` → Filter by severity

### 2. Penalty Schedule (`backend/app/dpdpa/penalty_schedule.py`)

**Purpose**: DPDPA Section 33 penalty tiers

**Data Class: `PenaltyTier`**
```python
@dataclass
class PenaltyTier:
    tier_id: str
    section_ref: str
    description: str
    max_penalty_crore: int
    max_penalty_display: str
    applicable_categories: List[str]
```

**Penalty Tiers**:

| Tier | Section | Max Penalty | Applicable Categories |
|------|---------|-------------|----------------------|
| PEN-001 | Section 33(a) | 250 crore INR | Security failures, SDF obligations, data retention, cross-border, video PII |
| PEN-002 | Section 33(b) | 200 crore INR | Breach notification failures |
| PEN-003 | Section 33(c) | 200 crore INR | Children's data violations |
| PEN-004 | Section 33(d) | 150 crore INR | Consent/notice violations, purpose limitation |
| PEN-005 | Section 33(e) | 100 crore INR | Data principal rights denial |

### 3. PII Definitions (`backend/app/pii/definitions.py`)

**Purpose**: Regex patterns for PII detection under Indian compliance framework

**Data Class: `PIIPattern`**
```python
@dataclass
class PIIPattern:
    name: str
    display_name: str
    category: str
    regex: str
    description: str
    severity: str = "high"
    needs_digit_cleanup: bool = False
    min_digits: int = 0
    max_digits: int = 0
    context_required: bool = False
    context_words: List[str] = field(default_factory=list)
```

**PII Categories (5 Total, 17+ Patterns)**:

| Category | Patterns | Examples |
|----------|----------|----------|
| **Direct Identifiers** | 4 | Name (labeled), DOB, Age, Gender |
| **Government IDs** | 5 | Aadhaar, PAN, Passport, Voter ID, Driving Licence |
| **Contact & Location** | 8 | Phone (India/Intl/10-digit), Email, PIN Code, IP Address, GPS, URL |
| **Financial Data** | 4 | Credit Card, Bank Account, IFSC, UPI ID |
| **Authentication** | 2 | OTP, SSN |

**Key Regex Patterns**:

| PII Type | Pattern | Example |
|----------|---------|---------|
| Aadhaar | `\b\d{4}[-\s]\d{4}[-\s]\d{4}\b` | 1234 5678 9012 |
| PAN | `\b[A-Z]{5}\d{4}[A-Z]\b` | ABCDE1234F |
| Phone (India) | `\+?91[-.\s]*[6-9][\d\s-]{9,14}` | +91-7358050632 |
| Email | `\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z\|a-z]{2,}\b` | user@example.com |
| Credit Card | `\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b` | 4111-1111-1111-1111 |

### 4. Guideline Loader (`backend/app/services/guideline_loader.py`)

**Purpose**: Load DPDPA rules into PostgreSQL + Weaviate

**Class: `GuidelineLoader`**

| Method | Description |
|--------|-------------|
| `load_all_rules()` | Load all rules into both databases |
| `clear_all_rules()` | Remove all DPDPA rules |
| `verify_load()` | Verify rules loaded correctly |
| `search_rules()` | Semantic search for rules |

**Loading Process**:
```
For each DPDPARule:
    1. Create rich embedding text (requirement + violation + guidance)
    2. Generate embedding with EmbeddingService
    3. Store in Weaviate Guidelines collection
    4. Create Guideline ORM object
    5. Store in PostgreSQL with weaviate_id reference
```

---

## Data Storage Architecture

```mermaid
graph LR
    subgraph "Structured Data - PostgreSQL"
        PG[(PostgreSQL)]
        Videos[Video Table]
        Guidelines[Guideline Table]
        Reports[ComplianceReport Table]
        Users[User Table]
        
        PG --> Videos
        PG --> Guidelines
        PG --> Reports
        PG --> Users
    end

    subgraph "Vector Data - Weaviate"
        WV[(Weaviate)]
        VideoContent[VideoContent Collection]
        GuidelineVec[Guidelines Collection]
        
        WV --> VideoContent
        WV --> GuidelineVec
    end

    subgraph "Object Storage - MinIO"
        MIN[(MinIO)]
        VideoBucket[videos bucket]
        FrameBucket[frames bucket]
        DocBucket[documents bucket]
        
        MIN --> VideoBucket
        MIN --> FrameBucket
        MIN --> DocBucket
    end

    subgraph "Cache - Redis"
        RD[(Redis)]
        TaskQueue[Celery Task Queue]
        Cache[Application Cache]
        
        RD --> TaskQueue
        RD --> Cache
    end
```

### PostgreSQL Schema

**Video Table**:
```sql
- id (PK)
- filename
- file_path
- duration
- status (pending/processing/completed/failed)
- created_at
- updated_at
```

**Guideline Table**:
```sql
- id (PK)
- name (rule_id)
- regulation_type ("DPDPA")
- version ("2023+2025_Rules")
- description
- requirement_text
- severity (CRITICAL/WARNING/INFO)
- check_type
- weaviate_id (FK to Weaviate)
- clause_number
- penalty_ref
- check_types_json (JSON array)
- category
- is_active
```

**ComplianceReport Table**:
```sql
- id (PK)
- video_id (FK)
- status
- overall_compliance_score
- violations_count
- report_data (JSON)
- created_at
```

### Weaviate Collections

**VideoContent** (for semantic search):
- Stores: Frame descriptions, OCR text, transcriptions
- Vector: 768-dim from sentence-transformers
- Metadata: video_id, timestamp, frame_number, content_type

**Guidelines** (for compliance matching):
- Stores: DPDPA rule requirement text
- Vector: 768-dim embedding of rule text
- Metadata: guideline_id, regulation_type, clause_number, severity, category

### MinIO Buckets

| Bucket | Purpose | Access |
|--------|---------|--------|
| `videos` | Original uploaded videos | Private |
| `frames` | Extracted frame images | Public read |
| `documents` | Guideline PDFs, reports | Private |

---

## System Interaction Diagrams

### 1. Video Processing Pipeline (Step 1)

```mermaid
sequenceDiagram
    participant User
    participant API as FastAPI
    participant Celery as Celery Worker
    participant FE as FrameExtractor
    participant VA as VisualAnalyzer
    participant OCR as OCRService
    participant AT as AudioTranscriber
    participant ES as EmbeddingService
    participant VS as VectorStore
    participant MIN as MinIO

    User->>API: POST /videos/upload
    API->>MIN: Store video file
    MIN-->>API: file_url
    API->>Celery: Dispatch process_video task
    API-->>User: task_id (accepted)

    Celery->>FE: extract_frames(video_path)
    FE->>FE: OpenCV scene detection
    FE-->>Celery: List[ExtractedFrame]

    Celery->>FE: extract_audio(video_path)
    FE-->>Celery: audio.wav

    par Frame Processing
        loop For each frame
            Celery->>VA: analyze_image(frame)
            VA->>VA: YOLO inference
            VA-->>Celery: DetectedObjects
            
            Celery->>OCR: extract_text(frame)
            OCR->>OCR: Tesseract OCR
            OCR-->>Celery: OCR text
            
            Celery->>Celery: create_frame_description()
        end
    and Audio Processing
        Celery->>AT: transcribe(audio.wav)
        AT->>AT: Whisper inference
        AT-->>Celery: TranscriptionSegments
    end

    Celery->>ES: embed_batch(descriptions)
    ES->>ES: sentence-transformers
    ES-->>Celery: List[embeddings]

    Celery->>VS: add_video_content_batch()
    VS->>VS: Weaviate batch insert
    VS-->>Celery: object_ids

    Celery-->>API: Task complete
    API->>API: Update video status
```

### 2. PII Extraction Flow

```mermaid
sequenceDiagram
    participant Script as extract_pii_from_video.py
    participant VS as VectorStore
    participant PD as PIIDefinitions
    participant Output as Console Output

    Script->>VS: get_all_frames(video_id)
    VS->>VS: Query VideoContent collection
    VS-->>Script: List[FrameData]

    loop For each frame
        Script->>Script: Extract OCR text
        
        loop For each PII pattern
            Script->>PD: pattern.regex
            PD-->>Script: Match results
            
            alt Pattern needs context
                Script->>Script: Check context_words
            end
            
            alt Pattern needs digit cleanup
                Script->>Script: Clean phone number
            end
        end
    end

    Script->>Script: Aggregate by category
    Script->>Script: Sort by timestamp
    Script->>Output: Print PII report
```

### 3. DPDPA Rule Loading (Step 2)

```mermaid
sequenceDiagram
    participant CLI as load_dpdpa_rules.py
    participant GL as GuidelineLoader
    participant DD as DPDPADefinitions
    participant ES as EmbeddingService
    participant PG as PostgreSQL
    participant VS as VectorStore

    CLI->>GL: load_all_rules()
    GL->>DD: get_all_rules()
    DD-->>GL: List[DPDPARule] (~35 rules)

    loop For each rule
        GL->>GL: _create_embedding_text(rule)
        GL->>ES: embed(embedding_text)
        ES-->>GL: embedding vector
        
        GL->>VS: add_guideline(...)
        VS->>VS: Insert into Guidelines
        VS-->>GL: weaviate_id
        
        GL->>GL: Create Guideline ORM
        GL->>PG: db.add(guideline)
    end

    GL->>PG: db.commit()
    GL-->>CLI: Stats dict
```

### 4. Compliance Checking Flow (Step 3 - Planned)

```mermaid
sequenceDiagram
    participant API as FastAPI
    participant LG as LangGraph Agent
    participant VS as VectorStore
    participant Ollama as Ollama
    participant Report as Report Generator

    API->>LG: check_compliance(video_id)
    
    LG->>VS: search_video_content("PII detected")
    VS-->>LG: Video frames with PII
    
    LG->>VS: search_guidelines("consent requirements")
    VS-->>LG: Relevant DPDPA rules
    
    LG->>Ollama: analyze(violation_context)
    Ollama->>Ollama: Llama 3.1 inference
    Ollama-->>LG: Analysis result
    
    LG->>Report: generate_report(violations)
    Report-->>API: ComplianceReport
```

### 5. Health Check Flow

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI
    participant PG as PostgreSQL
    participant RD as Redis
    participant MIN as MinIO
    participant VS as VectorStore
    participant Ollama as Ollama

    Client->>API: GET /health/detailed

    par Dependency Checks
        API->>PG: SELECT 1
        PG-->>API: OK
        
        API->>RD: ping()
        RD-->>API: PONG
        
        API->>MIN: bucket_exists()
        MIN-->>API: True
        
        API->>VS: schema.get()
        VS-->>API: OK
        
        API->>Ollama: GET /api/tags
        Ollama-->>API: Models list
    end

    API-->>Client: Health status JSON
```

---

## Technology Stack

### Backend Framework
| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.10+ | Runtime |
| FastAPI | 0.109.0 | Web framework |
| Uvicorn | 0.27.0 | ASGI server |
| Pydantic | 2.6.0 | Data validation |
| Pydantic-Settings | 2.1.0 | Configuration |

### Database & Storage
| Technology | Version | Purpose |
|------------|---------|---------|
| PostgreSQL | 16 | Relational database |
| SQLAlchemy | 2.0.25 | ORM |
| Alembic | 1.13.1 | Migrations |
| Weaviate | 1.27.3 | Vector database |
| Redis | 7 | Cache/Task queue |
| MinIO | Latest | Object storage |

### AI/ML Models
| Technology | Version | Purpose |
|------------|---------|---------|
| OpenAI Whisper | 20231117 | Audio transcription |
| Ultralytics YOLO | 8.1.9 | Object detection |
| sentence-transformers | 2.3.1 | Text embeddings |
| Tesseract | 5.4.0 | OCR |
| PyTorch | 2.1.2 | ML framework |
| Transformers | 4.36.2 | HuggingFace models |

### AI Orchestration
| Technology | Version | Purpose |
|------------|---------|---------|
| LangChain | 0.1.6 | LLM orchestration |
| LangGraph | 0.0.20 | Agent workflows |
| Ollama | Latest | Local LLM hosting |
| Llama 3.1 | 8b | Primary LLM |

### Video Processing
| Technology | Version | Purpose |
|------------|---------|---------|
| OpenCV | 4.9.0.80 | Frame extraction |
| FFmpeg-python | 0.2.0 | Audio extraction |
| scenedetect | 0.6.2 | Scene detection |
| Pillow | 10.2.0 | Image processing |

### Task Queue
| Technology | Version | Purpose |
|------------|---------|---------|
| Celery | 5.3.6 | Distributed tasks |
| Redis | 5.0.1 | Broker/Backend |

### Development & Testing
| Technology | Version | Purpose |
|------------|---------|---------|
| pytest | 7.4.4 | Testing framework |
| pytest-asyncio | 0.23.3 | Async testing |
| black | 24.1.1 | Code formatting |
| flake8 | 7.0.0 | Linting |
| mypy | 1.8.0 | Type checking |

---

## Deployment Architecture

### Docker Compose Services

```mermaid
graph TB
    subgraph "Regtech Network"
        direction TB
        
        subgraph "Database Tier"
            PG[(PostgreSQL<br/>Port: 5433)]
            WV[(Weaviate<br/>Port: 8080<br/>gRPC: 50051)]
            RD[(Redis<br/>Port: 6379)]
        end
        
        subgraph "Storage Tier"
            MIN[(MinIO<br/>API: 9000<br/>Console: 9001)]
            MIN_SETUP[MinIO Setup<br/>Bucket creation]
        end
        
        subgraph "AI Tier"
            OLL[Ollama<br/>Port: 11434]
        end
        
        subgraph "Application Tier"
            API[FastAPI<br/>Port: 8000]
            WORKER[Celery Worker]
        end
        
        API --> PG
        API --> WV
        API --> RD
        API --> MIN
        API --> OLL
        
        WORKER --> PG
        WORKER --> WV
        WORKER --> RD
        WORKER --> MIN
        WORKER --> OLL
        
        MIN_SETUP --> MIN
    end
```

### Service Configuration

| Service | Image | Ports | Volumes | Health Check |
|---------|-------|-------|---------|--------------|
| PostgreSQL | postgres:16-alpine | 5433:5432 | postgres_data | pg_isready |
| Redis | redis:7-alpine | 6379:6379 | redis_data | redis-cli ping |
| Weaviate | semitechnologies/weaviate:1.27.3 | 8080:8080, 50051:50051 | weaviate_data | curl /v1/.well-known/ready |
| MinIO | minio/minio:latest | 9000:9000, 9001:9001 | minio_data | curl /minio/health/live |
| MinIO Setup | minio/mc:latest | - | - | - |
| Ollama | ollama/ollama:latest | 11434:11434 | ollama_data | - |

### Environment Variables

**Database**:
- `DATABASE_URL=postgresql://postgres:postgres@localhost:5433/regtech_db`

**Redis**:
- `REDIS_URL=redis://localhost:6379/0`
- `CELERY_BROKER_URL=redis://localhost:6379/0`
- `CELERY_RESULT_BACKEND=redis://localhost:6379/0`

**MinIO**:
- `MINIO_ENDPOINT=localhost:9000`
- `MINIO_ACCESS_KEY=minioadmin`
- `MINIO_SECRET_KEY=minioadmin`
- `MINIO_BUCKET_VIDEOS=videos`
- `MINIO_BUCKET_FRAMES=frames`
- `MINIO_BUCKET_DOCUMENTS=documents`

**Weaviate**:
- `WEAVIATE_URL=http://localhost:8080`

**Ollama**:
- `OLLAMA_BASE_URL=http://localhost:11434`
- `OLLAMA_MODEL=llama3.1:8b`

---

## Module Dependency Graph

```mermaid
graph TB
    subgraph "Entry Points"
        Main[app/main.py]
        TestStep1[test_step1_complete.py]
        ExtractPII[extract_pii_from_video.py]
        LoadRules[load_dpdpa_rules.py]
    end

    subgraph "Configuration"
        Config[app/config.py]
    end

    subgraph "Database"
        DBSession[app/db/session.py]
    end

    subgraph "Services"
        VCV[VideoContentVectorizer]
        FE[FrameExtractor]
        VA[VisualAnalyzer]
        OCR[OCRService]
        AT[AudioTranscriber]
        ES[EmbeddingService]
        VS[VectorStore]
        GL[GuidelineLoader]
    end

    subgraph "Regulatory"
        DPDPADef[app/dpdpa/definitions.py]
        DPDPAPen[app/dpdpa/penalty_schedule.py]
        PIIDef[app/pii/definitions.py]
    end

    subgraph "External APIs"
        WeaviateClient[weaviate-client]
        OpenCV[opencv-python]
        Whisper[openai-whisper]
        YOLO[ultralytics]
        Tesseract[pytesseract]
        ST[sentence-transformers]
    end

    Main --> Config
    Main --> DBSession
    
    TestStep1 --> VCV
    ExtractPII --> VS
    ExtractPII --> PIIDef
    LoadRules --> GL
    
    VCV --> FE
    VCV --> VA
    VCV --> OCR
    VCV --> AT
    VCV --> ES
    VCV --> VS
    
    GL --> DPDPADef
    GL --> DPDPAPen
    GL --> ES
    GL --> VS
    GL --> DBSession
    
    VS --> WeaviateClient
    FE --> OpenCV
    VA --> YOLO
    OCR --> Tesseract
    AT --> Whisper
    ES --> ST
```

### Import Dependencies

```
app/main.py
├── app/config.py
├── app/db/session.py
└── (future) app/api/v1/ routers

app/services/video_content_vectorizer.py
├── app/services/frame_extractor.py
├── app.services/audio_transcriber.py
├── app.services.ocr_service.py
├── app.services.visual_analyzer.py
├── app.services.embedding_service.py
└── app.services.vector_store.py

app/services/guideline_loader.py
├── app.dpdpa.definitions.py
├── app.dpdpa.penalty_schedule.py
├── app.services.embedding_service.py
├── app.services.vector_store.py
└── (future) app.models.guideline.py

app/dpdpa/definitions.py
└── (stdlib) dataclasses, typing

app/pii/definitions.py
├── (stdlib) re, dataclasses, typing
```

---

## File Structure Summary

```
Regulatory-tech/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI entry point
│   │   ├── config.py                  # Pydantic settings
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── v1/
│   │   │       └── __init__.py        # API routers (future)
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   └── session.py             # SQLAlchemy session
│   │   ├── dpdpa/
│   │   │   ├── __init__.py
│   │   │   ├── definitions.py         # 35 DPDPA rules
│   │   │   └── penalty_schedule.py    # 5 penalty tiers
│   │   ├── pii/
│   │   │   ├── __init__.py
│   │   │   └── definitions.py         # 17 PII patterns
│   │   ├── langchain_components/
│   │   │   ├── agents/
│   │   │   ├── chains/
│   │   │   └── prompts/
│   │   ├── schemas/
│   │   │   └── __init__.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── video_content_vectorizer.py  # Pipeline orchestrator
│   │   │   ├── frame_extractor.py           # OpenCV/FFmpeg
│   │   │   ├── visual_analyzer.py           # YOLO v8
│   │   │   ├── ocr_service.py               # Tesseract
│   │   │   ├── audio_transcriber.py         # Whisper
│   │   │   ├── embedding_service.py         # sentence-transformers
│   │   │   ├── vector_store.py              # Weaviate
│   │   │   └── guideline_loader.py          # DPDPA loader
│   │   └── tasks/
│   │       └── __init__.py            # Celery tasks (future)
│   ├── tests/
│   │   └── __init__.py
│   ├── extract_pii_from_video.py      # PII extraction CLI
│   ├── extract_pii_video2.py          # Video 2 helper
│   ├── load_dpdpa_rules.py            # DPDPA loader CLI
│   ├── reprocess_video_with_ocr.py    # Reprocessing helper
│   ├── test_services.py               # Service test script
│   ├── test_step1_complete.py         # Step 1 test script
│   ├── setup.py                       # Backend setup
│   ├── requirements.txt               # Pinned dependencies
│   ├── requirements-fixed.txt         # Flexible versions
│   └── requirements-minimal.txt       # Minimal deps
├── docker/
│   └── docker-compose.yml             # Infrastructure services
├── .env.example                       # Environment template
├── README.md                          # Project overview
├── technical_design.md                # Original design doc
├── STEP1_COMPLETE.md                  # Step 1 completion report
└── step 1 steps.md                    # Step 1 detailed reference
```

---

## Performance Characteristics

| Operation | Time | Notes |
|-----------|------|-------|
| Frame Extraction | ~1s per frame | Depends on video resolution |
| YOLO Inference | ~1.5s per frame | On CPU; faster with GPU |
| OCR (Tesseract) | ~0.5s per frame | Depends on text complexity |
| Whisper Transcription | Real-time factor 0.5x | 1 min audio ~ 30s processing |
| Embedding Generation | ~0.1s per text | Batch processing faster |
| Vector Storage | ~0.05s per entry | Batch insert |
| Semantic Search | <100ms | Weaviate near-vector query |
| **Total Video Processing** | ~5 min for 50-frame video | 45-second source video |

---

## Security Considerations

1. **PII Handling**: All PII detection is local; no data sent to external APIs
2. **Model Execution**: All AI models run locally via Ollama
3. **Data Storage**: MinIO buckets configurable with encryption
4. **API Security**: JWT authentication ready (implementation pending)
5. **Database**: PostgreSQL with SSL support
6. **Vector DB**: Weaviate with anonymous access disabled in production

---

## Future Enhancements

### Step 3: RAG Compliance Agent
- LangGraph workflow for automated compliance checking
- Integration between video content and DPDPA rules
- Automated violation report generation

### API Endpoints
- `/api/v1/videos` - Video upload and management
- `/api/v1/compliance` - Compliance check initiation
- `/api/v1/reports` - Report retrieval and export
- `/api/v1/guidelines` - Guideline management

### Frontend
- React-based web interface
- Video upload with progress tracking
- Interactive compliance timeline
- Report visualization

---

*Document Version: 1.0*
*Last Updated: March 2026*
*System Status: Step 1 & 2 Complete, Step 3 In Planning*
