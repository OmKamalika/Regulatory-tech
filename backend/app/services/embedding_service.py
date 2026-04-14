"""
Embedding service using sentence-transformers for local embedding generation.
Converts text to vector embeddings for semantic search.
"""
import logging
import warnings
from typing import List, Union

import numpy as np
from dataclasses import dataclass

# Suppress two known-harmless warnings that fire on every worker startup:
#
# 1. "embeddings.position_ids | UNEXPECTED"
#    all-mpnet-base-v2 was serialised when transformers still stored position_ids
#    as a buffer. Current transformers computes it dynamically; the leftover key
#    in the checkpoint is logged as unexpected but is silently ignored.
#
# 2. HTTP 404 for processor_config.json
#    Newer sentence_transformers probes HF Hub for a processor config (needed only
#    by multimodal models). all-mpnet-base-v2 predates this and has no such file.
#    The 404 is expected; loading continues normally.
import transformers.utils.logging as _hf_logging
_hf_logging.set_verbosity_error()

from sentence_transformers import SentenceTransformer  # noqa: E402 (import after logging config)

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingResult:
    """Data class for embedding result"""
    text: str
    embedding: List[float]
    model_name: str


class EmbeddingService:
    """
    Generate embeddings using sentence-transformers models.
    Runs locally with no API costs.

    Recommended models:
    - all-mpnet-base-v2: Best quality (768 dim)
    - all-MiniLM-L6-v2: Faster, good quality (384 dim)
    - all-MiniLM-L12-v2: Balance (384 dim)
    """

    def __init__(self, model_name: str = None):
        self.model_name = model_name or settings.EMBEDDING_MODEL

        logger.info(f"Loading embedding model: {self.model_name}")

        try:
            self.model = SentenceTransformer(self.model_name)
            self.dimension = self.model.get_sentence_embedding_dimension()
            logger.info(f"Embedding model loaded successfully (dimension: {self.dimension})")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise

    def embed(self, text: str) -> List[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Input text to embed

        Returns:
            Embedding vector as list of floats
        """
        try:
            embedding = self.model.encode(text, convert_to_numpy=True)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            raise

    def embed_batch(
        self,
        texts: List[str],
        batch_size: int = 32,
        show_progress: bool = False
    ) -> List[List[float]]:
        """
        Generate embeddings for multiple texts efficiently.

        Args:
            texts: List of texts to embed
            batch_size: Batch size for processing
            show_progress: Show progress bar

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        logger.info(f"Generating embeddings for {len(texts)} texts")

        try:
            embeddings = self.model.encode(
                texts,
                batch_size=batch_size,
                show_progress_bar=show_progress,
                convert_to_numpy=True
            )

            return embeddings.tolist()
        except Exception as e:
            logger.error(f"Error generating batch embeddings: {e}")
            raise

    def embed_with_metadata(
        self,
        text: str,
        metadata: dict = None
    ) -> EmbeddingResult:
        """
        Generate embedding with metadata.

        Args:
            text: Input text
            metadata: Additional metadata to attach

        Returns:
            EmbeddingResult object
        """
        embedding = self.embed(text)

        return EmbeddingResult(
            text=text,
            embedding=embedding,
            model_name=self.model_name
        )

    def similarity(
        self,
        text1: str,
        text2: str
    ) -> float:
        """
        Calculate semantic similarity between two texts.

        Args:
            text1: First text
            text2: Second text

        Returns:
            Similarity score (0 to 1)
        """
        emb1 = np.array(self.embed(text1))
        emb2 = np.array(self.embed(text2))

        # Cosine similarity
        similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))

        return float(similarity)

    def find_most_similar(
        self,
        query: str,
        candidates: List[str],
        top_k: int = 5
    ) -> List[tuple]:
        """
        Find most similar texts to query from a list.

        Args:
            query: Query text
            candidates: List of candidate texts
            top_k: Number of results to return

        Returns:
            List of (text, similarity_score) tuples
        """
        query_emb = np.array(self.embed(query))
        candidate_embs = np.array(self.embed_batch(candidates))

        # Calculate cosine similarities
        similarities = np.dot(candidate_embs, query_emb) / (
            np.linalg.norm(candidate_embs, axis=1) * np.linalg.norm(query_emb)
        )

        # Get top k
        top_indices = np.argsort(similarities)[::-1][:top_k]

        results = [
            (candidates[idx], float(similarities[idx]))
            for idx in top_indices
        ]

        return results

    def get_model_info(self) -> dict:
        """Get information about the embedding model"""
        return {
            "model_name": self.model_name,
            "dimension": self.dimension,
            "max_seq_length": self.model.max_seq_length,
            "device": str(self.model.device)
        }


# Utility functions for common embedding tasks

def create_frame_description(
    frame_number: int,
    timestamp: float,
    objects_detected: List[str],
    ocr_text: str = None,
    scene_description: str = None
) -> str:
    """
    Create a text description from frame analysis results.
    This text will be embedded for semantic search.

    Args:
        frame_number: Frame number
        timestamp: Timestamp in seconds
        objects_detected: List of detected objects
        ocr_text: OCR extracted text
        scene_description: Scene description from vision model

    Returns:
        Formatted text description
    """
    parts = [f"At timestamp {timestamp:.2f} seconds (frame {frame_number}):"]

    if scene_description:
        parts.append(f"Scene: {scene_description}")

    if objects_detected:
        parts.append(f"Objects visible: {', '.join(objects_detected)}")

    if ocr_text:
        parts.append(f"Text displayed: {ocr_text}")

    return " ".join(parts)


def create_transcription_description(
    start_time: float,
    end_time: float,
    text: str,
    speaker: str = None
) -> str:
    """
    Create a text description from transcription segment.

    Args:
        start_time: Start time in seconds
        end_time: End time in seconds
        text: Transcribed text
        speaker: Speaker identifier

    Returns:
        Formatted text description
    """
    speaker_prefix = f"{speaker} says: " if speaker else "Audio: "
    return f"From {start_time:.2f}s to {end_time:.2f}s - {speaker_prefix}{text}"


def chunk_text(
    text: str,
    max_length: int = 500,
    overlap: int = 50
) -> List[str]:
    """
    Split long text into overlapping chunks for embedding.

    Args:
        text: Input text
        max_length: Maximum chunk length
        overlap: Overlap between chunks

    Returns:
        List of text chunks
    """
    if len(text) <= max_length:
        return [text]

    chunks = []
    start = 0

    while start < len(text):
        end = start + max_length
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap

    return chunks
