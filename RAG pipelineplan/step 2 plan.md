# Step 2: Parse DPDPA 2023/2025 Guidelines into Structured Rules

## Context

Step 1 (Video to Vector Pipeline) is complete. It extracts frames, runs YOLO object detection, OCR text extraction, creates embeddings, and stores everything in Weaviate. Step 2 converts the DPDPA (Digital Personal Data Protection Act) 2023 Act and 2025 Rules into structured, machine-readable compliance rules. These rules will be used by the LangGraph RAG agent (Step 3) to check videos for violations.

**What we already have built:**

- `backend/app/models/guideline.py` — SQLAlchemy Guideline model (ready to use)
- `backend/app/services/vector_store.py` — Weaviate `Guidelines` collection with `add_guideline()` and `search_guidelines()`
- `backend/app/services/embedding_service.py` — sentence-transformers all-mpnet-base-v2 (768 dims)
- `backend/app/pii/definitions.py` — Pattern to follow (@dataclass + category lists + helpers)

**No new dependencies needed. 100% open source.**

---

## New Files to Create

```
backend/app/dpdpa/                    # New package (mirrors app/pii/ pattern)
    __init__.py                       # Package exports
    definitions.py                    # ~35 DPDPA rules as @dataclass
    penalty_schedule.py               # Penalty tiers from Section 33

backend/app/services/
    guideline_loader.py               # Loads rules into PostgreSQL + Weaviate

backend/
    load_dpdpa_rules.py               # CLI script to run the loader
```

## Existing Files to Modify

- `backend/app/models/guideline.py` — Add `clause_number`, `penalty_ref`, `check_types_json` columns
- `backend/app/main.py` — Uncomment/register guidelines API router

---

## Implementation Steps to achieve Step2:

### Step 1: Create Rule Definitions (`backend/app/dpdpa/definitions.py`)

**What it does:** Defines all ~35 DPDPA compliance rules as Python dataclasses — a rulebook in code. Similar to how `app/pii/definitions.py` defines PII patterns, this defines compliance rules.

Core dataclass:

```python
@dataclass
class DPDPARule:
    rule_id: str              # "DPDPA-S4-001"
    name: str                 # "Consent Before Processing"
    section_ref: str          # "Section 4"
    category: str             # "consent"
    requirement_text: str     # Full rule description
    severity: str             # "critical" / "warning" / "info"
    check_types: List[str]    # What Step 1 outputs to check against
    violation_condition: str  # What constitutes a violation
    applicability: str        # When this rule applies
    penalty_ref: str          # "Section 33(a) - up to 250 crore"
    video_specific: bool      # Is this specifically about video/CCTV
    detection_guidance: str   # Hints for the LangGraph agent in Step 3
```

**~35 rules across 10 categories:**

| #   | Category                   | Section Reference    | Key Rules                                                              | Severity | Count |
| --- | -------------------------- | -------------------- | ---------------------------------------------------------------------- | -------- | ----- |
| 1   | Consent                    | Section 4, Rule 3    | Consent before processing, informed notice, facial recognition consent | CRITICAL | 7     |
| 2   | Data Principal Rights      | Sections 11-14       | Right to access, correction, erasure, grievance                        | CRITICAL | 5     |
| 3   | Data Fiduciary Obligations | Section 8            | Security safeguards, purpose limitation, data accuracy                 | CRITICAL | 5     |
| 4   | SDF Obligations            | Section 10, Rule 13  | DPIA requirement, DPO appointment                                      | CRITICAL | 3     |
| 5   | Children's Data            | Section 9            | Parental consent, no tracking/monitoring of minors                     | CRITICAL | 3     |
| 6   | Data Retention             | Section 8(7), Rule 8 | Retention limits, CCTV max 90 days, erasure after purpose              | CRITICAL | 3     |
| 7   | Breach Notification        | Rule 7               | 72-hour notification to board, notify data principal                   | CRITICAL | 2     |
| 8   | Cross-Border               | Section 16           | Transfer restrictions, additional consent                              | CRITICAL | 2     |
| 9   | Purpose Limitation         | Section 5, 6         | Purpose specification, no function creep                               | CRITICAL | 2     |
| 10  | Video-Specific PII         | Section 4, 8         | PII visible in frames, PII in audio, face as biometric data            | CRITICAL | 4     |

Helper functions: `get_all_rules()`, `get_category_rules(category)`, `get_video_specific_rules()`, `get_rules_by_check_type(check_type)`

---

### Step 2: Create Penalty Schedule (`backend/app/dpdpa/penalty_schedule.py`)

**What it does:** Defines the 5 penalty tiers from DPDPA Section 33. Each rule links to a penalty tier so the system knows how serious a violation is and what fine it could attract.

| Tier    | Violation                    | Max Penalty   |
| ------- | ---------------------------- | ------------- |
| PEN-001 | Security safeguard failures  | 250 crore INR |
| PEN-002 | Breach notification failures | 200 crore INR |
| PEN-003 | Children's data violations   | 200 crore INR |
| PEN-004 | Consent/notice violations    | 150 crore INR |
| PEN-005 | Data principal rights denial | 100 crore INR |

---

### Step 3: Create Package Init (`backend/app/dpdpa/__init__.py`)

**What it does:** Makes `dpdpa/` a proper Python package and exports key functions so other parts of the code can import and use the rules easily.

Exports: `DPDPARule`, `get_all_rules`, `get_category_rules`, `PENALTY_TIERS`

---

### Step 4: Update Guideline Model (`backend/app/models/guideline.py`)

**What it does:** Adds 3 new columns to the existing database table to store the new rule data.

- `clause_number` (String) — e.g., "Section 4(1)"
- `penalty_ref` (String) — e.g., "Section 33(a) - up to 250 crore"
- `check_types_json` (JSON) — Full list of check types for this rule

---

### Step 5: Create Guideline Loader Service (`backend/app/services/guideline_loader.py`)

**What it does:** The engine that takes rule definitions from Step 1 and loads them into both databases — PostgreSQL (for structured queries/filtering) and Weaviate (for semantic search). Creates embeddings for each rule so the LangGraph agent in Step 3 can find relevant rules by meaning.

```python
class GuidelineLoader:
    def load_all_rules(clear_existing=False) -> dict:
        # 1. Optionally clear existing rules from PostgreSQL + Weaviate
        # 2. For each DPDPARule:
        #    a. Convert to Guideline model -> insert into PostgreSQL
        #    b. Create rich embedding text (requirement + violation + guidance)
        #    c. Embed with EmbeddingService -> store in Weaviate
        #    d. Save weaviate_id back to PostgreSQL row
        # 3. Return stats {total, inserted, skipped, errors}

    def clear_all_rules() -> dict
    def verify_load() -> dict
```

**Key design:** Embedding text = `requirement_text + violation_condition + applicability + detection_guidance` concatenated for better semantic search quality.

---

### Step 6: Create Loader CLI Script (`backend/load_dpdpa_rules.py`)

**What it does:** A command-line script you run in PowerShell to trigger loading, verify it worked, or test search. Like how `extract_pii_from_video.py` lets you test PII extraction from the terminal.

```powershell
venv\Scripts\python.exe load_dpdpa_rules.py              # Load all rules
venv\Scripts\python.exe load_dpdpa_rules.py --clear       # Clear and reload
venv\Scripts\python.exe load_dpdpa_rules.py --verify      # Verify loaded rules
venv\Scripts\python.exe load_dpdpa_rules.py --search "consent for recording"
```

---

## How Step 1 Output Maps to Step 2 Rules

This is the bridge — what the video pipeline detects triggers which DPDPA rules:

| Step 1 Detects              | Check Type                | Example Rules Triggered                        |
| --------------------------- | ------------------------- | ---------------------------------------------- |
| YOLO finds "person"         | `visual_person_detection` | Consent before processing, purpose limitation  |
| YOLO finds face             | `visual_face_detection`   | Facial recognition consent, face as biometric  |
| OCR extracts text           | `ocr_text_detection`      | Notice requirements, OCR text is personal data |
| OCR text matches PII regex  | `ocr_pii_detection`       | PII visible in video, data accuracy            |
| Audio transcription has PII | `audio_pii_detection`     | PII spoken in audio                            |
| Video contains children     | `children_detection`      | Parental consent, no tracking of minors        |
| Consent banner detected     | `consent_indicator`       | All consent rules                              |
| Video stored > 90 days      | `data_retention`          | CCTV retention limit, erasure rules            |

---

## Verification Plan

After implementation, test with:

```powershell
cd c:\Users\mailt\OneDrive\Desktop\Regtech\backend

# 1. Load all DPDPA rules
venv\Scripts\python.exe load_dpdpa_rules.py

# 2. Verify rules loaded correctly
venv\Scripts\python.exe load_dpdpa_rules.py --verify

# 3. Test semantic search
venv\Scripts\python.exe load_dpdpa_rules.py --search "consent for video recording"
venv\Scripts\python.exe load_dpdpa_rules.py --search "children in video"
venv\Scripts\python.exe load_dpdpa_rules.py --search "how long to keep CCTV footage"
venv\Scripts\python.exe load_dpdpa_rules.py --search "personal data visible in video"
```

**Expected results:**

- ~35 rules loaded into PostgreSQL (Guideline table)
- ~35 vectors stored in Weaviate Guidelines collection
- Semantic search returns relevant rules for each test query
- Each PostgreSQL row has a valid `weaviate_id` linking to its vector
