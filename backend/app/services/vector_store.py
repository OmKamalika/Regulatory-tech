"""
Vector store service using Weaviate for storing and searching embeddings.
Integrates with LangChain for easy RAG implementation.

LangChain Docs: https://python.langchain.com/docs/integrations/vectorstores/weaviate
"""
import weaviate
from weaviate.classes.config import Property, DataType, Configure
from weaviate.classes.query import Filter
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
import uuid

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Data class for search result"""
    id: str
    text: str
    metadata: Dict
    score: float  # Similarity/distance score


class VectorStore:
    """
    Vector store for video content embeddings using Weaviate.

    Collections:
    - VideoContent: Frame descriptions, OCR text, transcriptions
    - Guidelines: Compliance guideline clauses
    """

    def __init__(self):
        logger.info(f"Connecting to Weaviate at {settings.WEAVIATE_URL}")

        try:
            self.client = weaviate.connect_to_local(
                host=settings.WEAVIATE_URL.replace("http://", "").replace(":8080", ""),
                port=8080
            )
            logger.info("Connected to Weaviate successfully")

            # Initialize collections
            self._init_collections()

        except Exception as e:
            logger.error(f"Failed to connect to Weaviate: {e}")
            raise

    def _init_collections(self):
        """Initialize Weaviate collections (schemas)"""

        # VideoContent collection for storing video frame/audio/OCR embeddings
        try:
            if not self.client.collections.exists("VideoContent"):
                logger.info("Creating VideoContent collection")

                self.client.collections.create(
                    name="VideoContent",
                    properties=[
                        Property(name="video_id", data_type=DataType.TEXT),
                        Property(name="content_type", data_type=DataType.TEXT),  # "frame", "transcription", "ocr"
                        Property(name="timestamp", data_type=DataType.NUMBER),
                        Property(name="text", data_type=DataType.TEXT),
                        Property(name="frame_number", data_type=DataType.INT),
                        Property(name="frame_url", data_type=DataType.TEXT),
                        Property(name="metadata", data_type=DataType.TEXT),  # JSON string
                    ],
                    vectorizer_config=Configure.Vectorizer.none(),  # We provide embeddings manually
                )
                logger.info("VideoContent collection created")

        except Exception as e:
            logger.warning(f"VideoContent collection might already exist: {e}")

        # Guidelines collection for storing compliance guideline embeddings
        try:
            if not self.client.collections.exists("Guidelines"):
                logger.info("Creating Guidelines collection")

                self.client.collections.create(
                    name="Guidelines",
                    properties=[
                        Property(name="guideline_id", data_type=DataType.TEXT),
                        Property(name="regulation_type", data_type=DataType.TEXT),  # "GDPR", "DPDPA", etc.
                        Property(name="clause_number", data_type=DataType.TEXT),
                        Property(name="requirement_text", data_type=DataType.TEXT),
                        Property(name="severity", data_type=DataType.TEXT),  # "critical", "warning", "info"
                        Property(name="category", data_type=DataType.TEXT),
                        Property(name="metadata", data_type=DataType.TEXT),
                    ],
                    vectorizer_config=Configure.Vectorizer.none(),
                )
                logger.info("Guidelines collection created")

        except Exception as e:
            logger.warning(f"Guidelines collection might already exist: {e}")

    def add_video_content(
        self,
        video_id: str,
        content_type: str,
        timestamp: float,
        text: str,
        embedding: List[float],
        frame_number: int = None,
        frame_url: str = None,
        metadata: Dict = None
    ) -> str:
        """
        Add video content embedding to vector store.

        Args:
            video_id: Video identifier
            content_type: Type of content ("frame", "transcription", "ocr")
            timestamp: Timestamp in seconds
            text: Text description
            embedding: Vector embedding
            frame_number: Frame number (for frame content)
            frame_url: URL to frame image in MinIO
            metadata: Additional metadata

        Returns:
            Weaviate object ID
        """
        try:
            collection = self.client.collections.get("VideoContent")

            # Prepare data
            data = {
                "video_id": video_id,
                "content_type": content_type,
                "timestamp": timestamp,
                "text": text,
                "frame_number": frame_number or 0,
                "frame_url": frame_url or "",
                "metadata": str(metadata) if metadata else "{}"
            }

            # Add to Weaviate
            result = collection.data.insert(
                properties=data,
                vector=embedding
            )

            logger.debug(f"Added {content_type} content for video {video_id} at {timestamp}s")
            return str(result)

        except Exception as e:
            logger.error(f"Error adding video content: {e}")
            raise

    def add_video_content_batch(
        self,
        items: List[Dict[str, Any]]
    ) -> List[str]:
        """
        Add multiple video content embeddings in batch.

        Args:
            items: List of dicts with keys: video_id, content_type, timestamp,
                   text, embedding, frame_number, frame_url, metadata

        Returns:
            List of Weaviate object IDs
        """
        logger.info(f"Adding {len(items)} video content items in batch")

        try:
            collection = self.client.collections.get("VideoContent")

            # Use batch insert for efficiency
            with collection.batch.dynamic() as batch:
                object_ids = []

                for item in items:
                    data = {
                        "video_id": item["video_id"],
                        "content_type": item["content_type"],
                        "timestamp": item["timestamp"],
                        "text": item["text"],
                        "frame_number": item.get("frame_number", 0),
                        "frame_url": item.get("frame_url", ""),
                        "metadata": str(item.get("metadata", "{}"))
                    }

                    result = batch.add_object(
                        properties=data,
                        vector=item["embedding"]
                    )
                    object_ids.append(str(result))

            logger.info(f"Successfully added {len(object_ids)} items")
            return object_ids

        except Exception as e:
            logger.error(f"Error in batch insert: {e}")
            raise

    def search_video_content(
        self,
        query_embedding: List[float],
        video_id: str = None,
        content_type: str = None,
        limit: int = 10
    ) -> List[SearchResult]:
        """
        Search for similar video content using vector similarity.

        Args:
            query_embedding: Query vector embedding
            video_id: Filter by specific video (optional)
            content_type: Filter by content type (optional)
            limit: Maximum number of results

        Returns:
            List of SearchResult objects
        """
        try:
            collection = self.client.collections.get("VideoContent")

            # Build filters
            filters = []
            if video_id:
                filters.append(f"video_id == '{video_id}'")
            if content_type:
                filters.append(f"content_type == '{content_type}'")

            # Perform vector search
            response = collection.query.near_vector(
                near_vector=query_embedding,
                limit=limit,
                return_metadata=["distance"]
            )

            # Convert to SearchResult objects
            results = []
            for obj in response.objects:
                results.append(SearchResult(
                    id=str(obj.uuid),
                    text=obj.properties.get("text", ""),
                    metadata={
                        "video_id": obj.properties.get("video_id"),
                        "content_type": obj.properties.get("content_type"),
                        "timestamp": obj.properties.get("timestamp"),
                        "frame_number": obj.properties.get("frame_number"),
                        "frame_url": obj.properties.get("frame_url"),
                    },
                    score=1.0 - obj.metadata.distance  # Convert distance to similarity
                ))

            logger.info(f"Found {len(results)} results")
            return results

        except Exception as e:
            logger.error(f"Error searching video content: {e}")
            raise

    def add_guideline(
        self,
        guideline_id: str,
        regulation_type: str,
        clause_number: str,
        requirement_text: str,
        embedding: List[float],
        severity: str = "warning",
        category: str = None,
        metadata: Dict = None
    ) -> str:
        """
        Add guideline to vector store.

        Args:
            guideline_id: Guideline identifier
            regulation_type: Type of regulation (e.g., "DPDPA", "GDPR")
            clause_number: Clause/article number
            requirement_text: Full requirement text
            embedding: Vector embedding
            severity: Severity level
            category: Category (e.g., "Data Privacy")
            metadata: Additional metadata

        Returns:
            Weaviate object ID
        """
        try:
            collection = self.client.collections.get("Guidelines")

            data = {
                "guideline_id": guideline_id,
                "regulation_type": regulation_type,
                "clause_number": clause_number,
                "requirement_text": requirement_text,
                "severity": severity,
                "category": category or "",
                "metadata": str(metadata) if metadata else "{}"
            }

            result = collection.data.insert(
                properties=data,
                vector=embedding
            )

            logger.debug(f"Added guideline {guideline_id}")
            return str(result)

        except Exception as e:
            logger.error(f"Error adding guideline: {e}")
            raise

    def search_guidelines(
        self,
        query_embedding: List[float],
        regulation_type: str = None,
        severity: str = None,
        limit: int = 10
    ) -> List[SearchResult]:
        """
        Search for relevant guidelines using vector similarity.

        Args:
            query_embedding: Query vector embedding
            regulation_type: Filter by regulation type (optional)
            severity: Filter by severity (optional)
            limit: Maximum number of results

        Returns:
            List of SearchResult objects
        """
        try:
            collection = self.client.collections.get("Guidelines")

            response = collection.query.near_vector(
                near_vector=query_embedding,
                limit=limit,
                return_metadata=["distance"]
            )

            results = []
            for obj in response.objects:
                results.append(SearchResult(
                    id=str(obj.uuid),
                    text=obj.properties.get("requirement_text", ""),
                    metadata={
                        "guideline_id": obj.properties.get("guideline_id"),
                        "regulation_type": obj.properties.get("regulation_type"),
                        "clause_number": obj.properties.get("clause_number"),
                        "severity": obj.properties.get("severity"),
                        "category": obj.properties.get("category"),
                    },
                    score=1.0 - obj.metadata.distance
                ))

            logger.info(f"Found {len(results)} guideline results")
            return results

        except Exception as e:
            logger.error(f"Error searching guidelines: {e}")
            raise

    def delete_video_content(self, video_id: str) -> int:
        """
        Delete all content for a specific video.

        Args:
            video_id: Video identifier

        Returns:
            Number of deleted objects
        """
        try:
            collection = self.client.collections.get("VideoContent")

            result = collection.data.delete_many(
                where=Filter.by_property("video_id").equal(video_id)
            )

            logger.info(f"Deleted {result.successful} objects for video {video_id}")
            return result.successful

        except Exception as e:
            logger.error(f"Error deleting video content: {e}")
            raise

    def get_stats(self) -> Dict:
        """Get statistics about vector store collections"""
        try:
            video_collection = self.client.collections.get("VideoContent")
            guideline_collection = self.client.collections.get("Guidelines")

            stats = {
                "video_content_count": len(video_collection),
                "guidelines_count": len(guideline_collection),
            }

            return stats

        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}

    def close(self):
        """Close Weaviate connection"""
        if hasattr(self, 'client'):
            self.client.close()
            logger.info("Weaviate connection closed")
