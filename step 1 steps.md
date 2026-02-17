# Step 1: Video to Vector Pipeline — Complete Reference

## Pipeline Overview

```
MP4 File
  |
  |--[1] OpenCV/FFmpeg -------> 50 JPEG frames
  |--[2] FFmpeg --------------> WAV audio (optional)
  |
  |--[3] YOLO v8 ------------> Object labels per frame
  |--[4] Tesseract -----------> Text per frame
  |
  |--[5] String format -------> "At timestamp 5.93s: Objects: person, cell phone Text: +91-7358..."
  |--[6] sentence-transformers -> [0.023, -0.156, ... ] (768 floats)
  |--[7] Weaviate ------------> Stored & searchable
  |
  |--[8] Python regex --------> PII Report with timestamps
```

---

## Detailed Action Table

| # | Action | Reason | Model / Library Used |
|---|--------|--------|---------------------|
| 1 | **Frame Extraction** — Extract individual image frames from the video at scene changes and fixed intervals | Videos are continuous streams; we need discrete images to analyze. Scene detection (pixel diff > 30.0) captures meaningful transitions instead of redundant similar frames. This reduces 1000s of frames to ~50 key frames. | **OpenCV (cv2)** — `cv2.VideoCapture` for reading, `cv2.absdiff` for scene change detection. **FFmpeg** for format handling. |
| 2 | **Audio Extraction** — Extract audio track from video as WAV file (16kHz, mono, PCM 16-bit) | Videos may contain spoken PII (names, phone numbers dictated aloud, addresses). Audio must be separated from video for transcription. 16kHz mono is the standard input format for speech models. | **FFmpeg** — `ffmpeg -acodec pcm_s16le -ac 1 -ar 16000` |
| 3 | **Object Detection** — Detect and label all objects visible in each frame (people, phones, laptops, etc.) | Knowing *what* is in the frame provides compliance context. A frame with `person + cell phone` showing a phone number = high PII risk. A frame with just `truck + road` = low risk. This context feeds the RAG agent in Step 3 for risk assessment. | **YOLO v8** (ultralytics) — Pre-trained on COCO dataset (80 object classes). Confidence threshold: 0.25, IoU: 0.45. |
| 4 | **OCR (Text Extraction)** — Read all visible text from each frame (numbers, emails, names, UI labels) | Text on screen is the primary source of PII in app/screen recordings — phone numbers, emails, Aadhaar numbers, PAN cards, etc. Without OCR, we'd only know objects exist but not *what data* is displayed. | **Tesseract 5.4.0** via `pytesseract` (primary). **OpenCV** text region detection (fallback if Tesseract unavailable). |
| 5 | **Text Description Creation** — Combine objects + OCR text + timestamp into a single structured text string | Vector embeddings work on text. We need to merge all extracted information (objects, OCR, timestamp) into one coherent sentence so semantic search can find it later. Format: `"At timestamp X seconds (frame Y): Objects visible: ... Text displayed: ..."` | **None** — Pure Python string formatting in `create_frame_description()`. |
| 6 | **Vector Embedding Generation** — Convert each text description into a 768-dimensional numeric vector | Text can't be searched by meaning directly. Embeddings capture semantic meaning as numbers, so "phone number visible" and "mobile number shown" are close in vector space. This enables semantic search in Step 3. | **sentence-transformers** — Model: `all-mpnet-base-v2` (768 dimensions). Runs locally on CPU/GPU. |
| 7 | **Vector Storage** — Store each embedding with metadata (video_id, timestamp, frame_number, text) in Weaviate | Embeddings need a specialized database for fast similarity search. Weaviate supports vector search + metadata filtering, so Step 3's RAG agent can query: "find frames with PII in video X" and get results in <100ms. | **Weaviate 1.27.3** — Vector database running in Docker (port 8080 + gRPC 50051). Distance metric: Euclidean. |
| 8 | **PII Detection** — Scan OCR text from each frame against 11 regex patterns (phone, email, Aadhaar, PAN, etc.) | This is the compliance output — identifying *what specific PII* exists and *when* it appears. Regex gives deterministic, explainable results (vs. LLM guessing). The PII list + timestamps become input for Step 3's DPDPA compliance checking. | **Python `re` module** — 11 regex patterns covering: Indian phone, international phone, 10-digit phone, email, credit card, Aadhaar, PAN, IP address, DOB, URL, SSN. |

---

## Key Parameters

| Component | Parameter | Value |
|-----------|-----------|-------|
| Frame Extraction | Scene change threshold | 30.0 (pixel mean difference) |
| Frame Extraction | Comparison resolution | 320x240 |
| Frame Extraction | JPEG quality | 90 |
| Frame Extraction | Max frames | 50 |
| Audio Extraction | Format | WAV, PCM 16-bit, mono, 16kHz |
| Object Detection | Confidence threshold | 0.25 |
| Object Detection | IoU threshold (NMS) | 0.45 |
| Object Detection | Classes | 80 (COCO dataset) |
| OCR | Tesseract path (Windows) | `C:\Program Files\Tesseract-OCR\tesseract.exe` |
| OCR Fallback | Binary threshold | 150 |
| OCR Fallback | Min region size | w > 20px, h > 10px |
| Embeddings | Model | `all-mpnet-base-v2` |
| Embeddings | Dimensions | 768 |
| Embeddings | Batch size | 32 |
| Vector Store | Database | Weaviate 1.27.3 |
| Vector Store | Ports | 8080 (HTTP) + 50051 (gRPC) |
| Vector Store | Distance metric | Euclidean |

---

## PII Regex Patterns Used

| PII Type | Regex Pattern | Example Match |
|----------|---------------|---------------|
| Phone (India) | `\+?91[-.\s]?[6-9]\d{9}` | +91-7358050632 |
| Phone (International) | `\+\d{1,3}[-.\s]?\d{4,5}[-.\s]?\d{4,10}` | +1-800-555-1234 |
| Phone (10-digit) | `\b[6-9]\d{9}\b` | 9036337803 |
| Email | `\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z\|a-z]{2,}\b` | chanducheetu@gmail.com |
| Credit Card | `\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b` | 4111-1111-1111-1111 |
| Aadhaar | `\b\d{4}[-\s]\d{4}[-\s]\d{4}\b` | 1234 5678 9012 |
| PAN | `\b[A-Z]{5}\d{4}[A-Z]\b` | ABCDE1234F |
| IP Address | `\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b` | 192.168.1.1 |
| Date of Birth | `\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b` | 15/08/1990 |
| URL | `https?://[^\s]+` | https://example.com |
| SSN | `\b\d{3}-\d{2}-\d{4}\b` | 123-45-6789 |

---

## Test Results (3 Videos Processed)

| Video | Video ID | PII Found | Timestamps |
|-------|----------|-----------|------------|
| Video 1 (Vealthx app) | test_video_001 | Phone: `+91-7358050632` | 5.93s — 47.46s |
| Video 2 (SuperFam app) | test_video_002 | Email: `support@superfam.app` | 0.00s — 2.97s |
| Video 3 (Payment/Profile) | test_video_003 | Phone: `9036337803`, Email: `chanducheetu@gmail.com` | 22.00s — 27.00s |

---

## Performance Metrics

| Metric | Value |
|--------|-------|
| Processing time per video | ~3 minutes (45-second video) |
| Frames extracted per video | ~50 |
| Vector entries per video | 50 (1 per frame) |
| Semantic search speed | < 100ms per query |
| Embedding dimensions | 768 |

---

## Source Files

| File | Purpose |
|------|---------|
| `backend/app/services/video_content_vectorizer.py` | Main pipeline orchestrator |
| `backend/app/services/frame_extractor.py` | Frame + audio extraction |
| `backend/app/services/visual_analyzer.py` | YOLO v8 object detection |
| `backend/app/services/ocr_service.py` | Tesseract OCR with fallback |
| `backend/app/services/embedding_service.py` | sentence-transformers embeddings |
| `backend/app/services/vector_store.py` | Weaviate vector database |
| `backend/extract_pii_from_video.py` | PII regex extraction utility |