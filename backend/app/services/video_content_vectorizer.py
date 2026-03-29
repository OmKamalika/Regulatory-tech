"""
Video Content Vectorizer - Orchestrates the complete Step 1 pipeline.

Pipeline:
1. Extract frames from video
2. Transcribe audio
3. Run OCR on frames
4. Analyze frames visually
5. Generate text descriptions
6. Create embeddings
7. Store in vector database
"""
import logging
from typing import List, Dict
from pathlib import Path
import tempfile
import os

from app.services.frame_extractor import FrameExtractor
from app.services.audio_transcriber import AudioTranscriber
from app.services.ocr_service import OCRService
from app.services.visual_analyzer import VisualAnalyzer
from app.services.embedding_service import (
    EmbeddingService,
    create_frame_description,
    create_transcription_description
)
from app.services.vector_store import VectorStore
from app.db.session import SessionLocal
from app.models.frame_analysis import FrameAnalysis
from app.models.transcription import TranscriptionSegment

logger = logging.getLogger(__name__)


class VideoContentVectorizer:
    """
    Complete video processing and vectorization pipeline.

    This orchestrates all services to:
    1. Extract video content (frames, audio, text)
    2. Convert to embeddings
    3. Store in vector database
    """

    def __init__(self):
        logger.info("Initializing Video Content Vectorizer")

        # Initialize all services
        self.frame_extractor = FrameExtractor()
        self.transcriber = AudioTranscriber()
        self.ocr_service = OCRService()
        self.visual_analyzer = VisualAnalyzer()
        self.embedding_service = EmbeddingService()
        self.vector_store = VectorStore()

        logger.info("All services initialized successfully")

    def process_video(
        self,
        video_id: str,
        video_path: str,
        max_frames: int = None,
        process_audio: bool = True,
        process_ocr: bool = True
    ) -> Dict:
        """
        Complete video processing pipeline.

        Args:
            video_id: Unique video identifier
            video_path: Path to video file
            max_frames: Maximum frames to process (None = all)
            process_audio: Whether to transcribe audio
            process_ocr: Whether to run OCR on frames

        Returns:
            Dictionary with processing statistics
        """
        logger.info(f"Processing video {video_id}: {video_path}")

        stats = {
            "video_id": video_id,
            "frames_processed": 0,
            "transcription_segments": 0,
            "embeddings_created": 0,
            "vector_store_entries": 0
        }

        try:
            # Create temp directory for processing
            with tempfile.TemporaryDirectory() as temp_dir:

                # Step 1: Extract frames
                logger.info("Step 1: Extracting frames...")
                frames_dir = os.path.join(temp_dir, "frames")
                frames = self.frame_extractor.extract_frames(
                    video_path,
                    frames_dir,
                    max_frames=max_frames
                )
                stats["frames_processed"] = len(frames)
                logger.info(f"Extracted {len(frames)} frames")

                # Step 2: Extract and transcribe audio (skipped for video-only MP4s)
                transcription_segments = []
                if process_audio:
                    logger.info("Step 2: Transcribing audio...")
                    audio_path = os.path.join(temp_dir, "audio.wav")
                    extracted = self.frame_extractor.extract_audio(video_path, audio_path)

                    if extracted:
                        transcription_segments = self.transcriber.get_segments(audio_path)
                        stats["transcription_segments"] = len(transcription_segments)
                        logger.info(f"Transcribed {len(transcription_segments)} segments")
                    else:
                        logger.info("No audio track found — skipping transcription")

                # Step 3: Process frames (OCR + Visual Analysis)
                ocr_info = self.ocr_service.get_reader_info()
                ocr_can_read = ocr_info.get("can_read_text", False)
                if not ocr_can_read:
                    logger.warning(
                        "⚠️  OCR engine '%s' cannot read text. Visual PII (phone numbers, "
                        "Aadhaar, PAN visible on screen) will NOT be detected. "
                        "Install EasyOCR or Tesseract for full compliance coverage.",
                        ocr_info.get("engine", "fallback")
                    )
                else:
                    logger.info("OCR engine active: %s", ocr_info.get("engine"))
                logger.info("Step 3: Analyzing frames...")
                frame_data = self._process_frames(
                    frames,
                    process_ocr=process_ocr,
                    ocr_can_read=ocr_can_read,
                )

                # Step 4: Create embeddings and store in vector DB
                logger.info("Step 4: Creating embeddings and storing...")
                vector_count = self._vectorize_and_store(
                    video_id,
                    frame_data,
                    transcription_segments
                )
                stats["embeddings_created"] = vector_count
                stats["vector_store_entries"] = vector_count

            logger.info(f"Video processing complete: {stats}")
            return stats

        except Exception as e:
            logger.error(f"Error processing video: {e}")
            raise

    def _process_frames(
        self,
        frames: List,
        process_ocr: bool = True,
        ocr_can_read: bool = True,
    ) -> List[Dict]:
        """
        Process extracted frames with OCR and visual analysis.

        Args:
            frames: List of ExtractedFrame objects
            process_ocr: Whether to run OCR

        Returns:
            List of frame data dictionaries
        """
        frame_data = []
        dropped = 0

        for i, frame in enumerate(frames):
            logger.debug(f"Processing frame {i+1}/{len(frames)}")

            try:
                # Visual analysis — call analyze_image() once to get real confidence scores
                detected_objects = self.visual_analyzer.analyze_image(frame.file_path)
                person_count = sum(1 for obj in detected_objects if obj.class_name == "person")

                # OCR (if enabled)
                ocr_text = ""
                if process_ocr:
                    ocr_results = self.ocr_service.extract_text(frame.file_path)
                    ocr_text = " ".join([r.text for r in ocr_results])

                # Collect frame data
                frame_data.append({
                    "frame_number": frame.frame_number,
                    "timestamp": frame.timestamp,
                    "file_path": frame.file_path,
                    "objects_detected": [
                        {"class": obj.class_name, "confidence": round(obj.confidence, 3)}
                        for obj in detected_objects
                    ],
                    "ocr_text": ocr_text,
                    "ocr_readable": ocr_can_read,  # False when engine is in fallback mode
                    "has_persons": person_count > 0,
                    "persons_count": person_count,
                    "total_objects": len(detected_objects),
                })

            except Exception as e:
                dropped += 1
                logger.error(f"Error processing frame {frame.frame_number}: {e}", exc_info=True)
                continue

        if dropped:
            pct = dropped / len(frames) * 100 if frames else 0
            logger.warning(
                "_process_frames: %d/%d frames dropped due to errors (%.0f%% coverage loss)",
                dropped, len(frames), pct,
            )

        return frame_data

    def _vectorize_and_store(
        self,
        video_id: str,
        frame_data: List[Dict],
        transcription_segments: List
    ) -> int:
        """
        Create embeddings and store in vector database.

        Args:
            video_id: Video identifier
            frame_data: List of frame data dictionaries
            transcription_segments: List of transcription segments

        Returns:
            Number of vectors stored
        """
        # Build items and collect texts for batch embedding
        items_to_store = []
        texts_to_embed = []

        for frame in frame_data:
            text_description = create_frame_description(
                frame_number=frame["frame_number"],
                timestamp=frame["timestamp"],
                objects_detected=[o["class"] for o in frame["objects_detected"]],
                ocr_text=frame["ocr_text"]
            )
            texts_to_embed.append(text_description)
            items_to_store.append({
                "video_id": video_id,
                "content_type": "frame",
                "timestamp": frame["timestamp"],
                "text": text_description,
                "embedding": None,  # filled after batch embed
                "frame_number": frame["frame_number"],
                "frame_url": "",  # TODO: Upload to MinIO and add URL
                "metadata": {
                    "objects": [o["class"] for o in frame["objects_detected"]],
                    "has_persons": frame["has_persons"],
                    "ocr_text": frame["ocr_text"]
                }
            })

        for segment in transcription_segments:
            text_description = create_transcription_description(
                start_time=segment.start,
                end_time=segment.end,
                text=segment.text
            )
            texts_to_embed.append(text_description)
            items_to_store.append({
                "video_id": video_id,
                "content_type": "transcription",
                "timestamp": segment.start,
                "text": text_description,
                "embedding": None,  # filled after batch embed
                "metadata": {
                    "duration": segment.end - segment.start,
                    "confidence": segment.confidence
                }
            })

        # Single batch embed call for all items
        try:
            embeddings = self.embedding_service.embed_batch(texts_to_embed)
            for item, embedding in zip(items_to_store, embeddings):
                item["embedding"] = embedding
        except Exception as e:
            logger.error("embed_batch failed — vector store will not be updated: %s", e, exc_info=True)
            # Embeddings unavailable; compliance pipeline uses PostgreSQL directly so this is non-fatal
            items_to_store = []

        # Batch insert to vector store
        if items_to_store:
            try:
                logger.info(f"Storing {len(items_to_store)} embeddings in vector database")
                self.vector_store.add_video_content_batch(items_to_store)
            except Exception as e:
                logger.error("Weaviate batch insert failed — semantic enrichment will be skipped: %s", e, exc_info=True)

        # Persist frame analyses and transcription segments to PostgreSQL
        db = SessionLocal()
        try:
            for frame in frame_data:
                db.add(FrameAnalysis(
                    video_id=video_id,
                    frame_number=frame["frame_number"],
                    timestamp=frame["timestamp"],
                    objects_detected=frame["objects_detected"],
                    persons_detected=frame.get("persons_count", 0),
                    ocr_text=frame.get("ocr_text", ""),
                    visual_analysis_completed=True,
                    ocr_completed=frame.get("ocr_readable", True),
                    vectorized=True,
                ))
            for segment in transcription_segments:
                db.add(TranscriptionSegment(
                    video_id=video_id,
                    start_time=segment.start,
                    end_time=segment.end,
                    text=segment.text,
                    confidence=getattr(segment, "confidence", None),
                    vectorized=True,
                ))
            db.commit()
            logger.info(f"Saved {len(frame_data)} frame analyses and {len(transcription_segments)} transcription segments to PostgreSQL")
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to save to PostgreSQL: {e}")
        finally:
            db.close()

        return len(items_to_store)

    def search_video_content(
        self,
        query: str,
        video_id: str = None,
        limit: int = 10
    ) -> List[Dict]:
        """
        Search video content using natural language query.

        Args:
            query: Natural language search query
            video_id: Filter by specific video (optional)
            limit: Maximum results

        Returns:
            List of search results with metadata
        """
        logger.info(f"Searching for: '{query}'")

        # Generate query embedding
        query_embedding = self.embedding_service.embed(query)

        # Search vector store
        results = self.vector_store.search_video_content(
            query_embedding=query_embedding,
            video_id=video_id,
            limit=limit
        )

        # Format results
        formatted_results = []
        for result in results:
            formatted_results.append({
                "text": result.text,
                "similarity_score": result.score,
                "timestamp": result.metadata.get("timestamp"),
                "content_type": result.metadata.get("content_type"),
                "video_id": result.metadata.get("video_id"),
                "frame_url": result.metadata.get("frame_url")
            })

        logger.info(f"Found {len(formatted_results)} results")
        return formatted_results

    def get_processing_stats(self) -> Dict:
        """Get statistics about vector store"""
        return self.vector_store.get_stats()

    def cleanup_video(self, video_id: str):
        """Remove all vector data for a video"""
        logger.info(f"Cleaning up vector data for video {video_id}")
        self.vector_store.delete_video_content(video_id)
