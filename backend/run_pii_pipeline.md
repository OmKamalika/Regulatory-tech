# How to Run the PII Extraction Pipeline on a New Video

## Prerequisites

- Docker Desktop must be running
- Tesseract OCR installed at `C:\Program Files\Tesseract-OCR\tesseract.exe`
- Backend virtual environment set up at `backend/venv`

---

## Step-by-Step Commands

### Step 1: Start Docker Containers

```powershell
cd c:\Users\mailt\OneDrive\Desktop\Regtech\docker
docker compose up -d
```

**Why**: Weaviate (vector database) runs inside Docker. Without it, embeddings cannot be stored or searched. This also starts PostgreSQL, Redis, MinIO, and Ollama.

---

### Step 2: Verify Weaviate is Ready

```powershell
curl "http://localhost:8080/v1/.well-known/ready" -UseBasicParsing
```

**Why**: Weaviate takes a few seconds to initialize. This endpoint returns HTTP 200 when ready. If it returns an error, wait a few seconds and retry.

---

### Step 3: Process the Video (Full Pipeline)

Replace **`MY_VIDEO_ID`** and **`VIDEO_PATH`** with your values, then run:

```powershell
cd c:\Users\mailt\OneDrive\Desktop\Regtech\backend

venv\Scripts\python.exe -c "from app.services.video_content_vectorizer import VideoContentVectorizer; vectorizer = VideoContentVectorizer(); vectorizer.vector_store.delete_video_content('MY_VIDEO_ID'); stats = vectorizer.process_video(video_id='MY_VIDEO_ID', video_path=r'VIDEO_PATH', max_frames=50, process_audio=False, process_ocr=True); print(stats)"
```

**Example** (with real values):

```powershell
venv\Scripts\python.exe -c "from app.services.video_content_vectorizer import VideoContentVectorizer; vectorizer = VideoContentVectorizer(); vectorizer.vector_store.delete_video_content('test_video_005'); stats = vectorizer.process_video(video_id='test_video_005', video_path=r'C:\Users\mailt\Downloads\WhatsApp Video 2026-02-17 at 12.20.19 PM.mp4', max_frames=50, process_audio=False, process_ocr=True); print(stats)"
```

**Why**: This runs the complete Step 1 pipeline:

| Stage            | Model / Library                           | What it Does                                       |
| ---------------- | ----------------------------------------- | -------------------------------------------------- |
| Frame Extraction | OpenCV                                    | Splits video into key frames using scene detection |
| Object Detection | YOLO v8                                   | Identifies people, phones, laptops in each frame   |
| OCR              | Tesseract 5.4                             | Reads all visible text from each frame             |
| Embedding        | sentence-transformers (all-mpnet-base-v2) | Converts descriptions to 768-dim vectors           |
| Storage          | Weaviate                                  | Stores vectors for semantic search                 |

**Notes**:

- `max_frames=50` auto-scales to 1 frame/second for videos longer than 50 seconds
- Videos are capped at 10 minutes max

---

### Step 4: Extract PII from the Processed Video

```powershell
cd c:\Users\mailt\OneDrive\Desktop\Regtech\backend

venv\Scripts\python.exe extract_pii_from_video.py --video-id my_video_001
```

**Why**: Scans all stored frames for PII using regex patterns defined in `app/pii/definitions.py`.

**PII types detected** (based on DPDPA 2023):

| Category           | Types                                                          |
| ------------------ | -------------------------------------------------------------- |
| Direct Identifiers | Person name, DOB, age, gender                                  |
| Government IDs     | Aadhaar, PAN, passport, voter ID, driving licence              |
| Contact & Location | Phone (Indian/international), email, PIN code, IP address, GPS |
| Financial          | Credit/debit card, bank account, IFSC, UPI ID                  |
| Authentication     | OTP, verification codes                                        |

Outputs a report grouped by DPDPA 2023 categories with timestamps.

---

## Quick One-Liner (All Steps Combined)

Replace `VIDEO_ID` and `VIDEO_PATH` with your values:

```powershell
cd c:\Users\mailt\OneDrive\Desktop\Regtech\backend

venv\Scripts\python.exe -c "
from app.services.video_content_vectorizer import VideoContentVectorizer
from extract_pii_from_video import PIIExtractor

VIDEO_ID = 'my_video_001'
VIDEO_PATH = r'C:\path\to\your\video.mp4'

# Process video through pipeline
vectorizer = VideoContentVectorizer()
vectorizer.vector_store.delete_video_content(VIDEO_ID)
stats = vectorizer.process_video(
    video_id=VIDEO_ID,
    video_path=VIDEO_PATH,
    max_frames=50,
    process_audio=False,
    process_ocr=True
)
print(f'Processed: {stats}')

# Extract PII
extractor = PIIExtractor()
extractor.extract_all_pii(VIDEO_ID)
"
```

---

## Useful Commands

### Read Vectors from Weaviate

```powershell
(curl "http://localhost:8080/v1/objects?class=VideoContent&limit=1&include=vector" -UseBasicParsing).Content | python -m json.tool
```

### Clear All Data in Vector DB

```powershell
cd c:\Users\mailt\OneDrive\Desktop\Regtech\backend

venv\Scripts\python.exe -c "from app.services.vector_store import VectorStore; vs = VectorStore(); vs.client.collections.delete('VideoContent'); print('VideoContent collection deleted'); vs.client.close()"
```

### Delete Data for a Specific Video Only

```powershell
cd c:\Users\mailt\OneDrive\Desktop\Regtech\backend

venv\Scripts\python.exe -c "from app.services.vector_store import VectorStore; vs = VectorStore(); count = vs.delete_video_content('test_video_004'); print(f'Deleted {count} entries'); vs.client.close()"
```

---

## Troubleshooting

| Problem                                             | Solution                                                      | Why                               |
| --------------------------------------------------- | ------------------------------------------------------------- | --------------------------------- |
| Docker not running                                  | Start Docker Desktop app                                      | Weaviate needs Docker             |
| Weaviate connection refused                         | `docker compose up -d` in `docker/` folder                    | Container may have stopped        |
| `&` error in PowerShell URL                         | Wrap URL in double quotes: `curl "http://..."`                | PowerShell treats `&` as operator |
| Security warning on `curl`                          | Add `-UseBasicParsing` flag                                   | Skips HTML parsing                |
| No OCR text / `[Text detected - install Tesseract]` | `pip install pytesseract` in backend venv                     | pytesseract package missing       |
| Tesseract binary not found                          | Install from https://github.com/tesseract-ocr/tesseract       | Binary not installed on system    |
| Only 50 frames from long video                      | Already fixed — auto-scales to 1fps                           | Older code had hard cap           |
| Phone number not detected                           | Already fixed — handles OCR spacing                           | Older regex was too strict        |
| Import errors                                       | Run from `backend/` directory using `venv\Scripts\python.exe` | Wrong venv or working directory   |
