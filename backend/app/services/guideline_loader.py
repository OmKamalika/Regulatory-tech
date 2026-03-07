"""
Guideline Loader Service

Loads DPDPA rule definitions into both PostgreSQL (Guideline model)
and Weaviate (Guidelines collection) with embeddings for semantic search.
"""

import logging
import json
from typing import Dict, List, Optional

from app.dpdpa.definitions import DPDPARule, get_all_rules, DPDPA_CATEGORIES
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore
from app.models.guideline import Guideline, GuidelineSeverity
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


class GuidelineLoader:
    """
    Loads DPDPA 2023/2025 rule definitions into PostgreSQL + Weaviate.

    - PostgreSQL: Structured storage for filtering/queries
    - Weaviate: Vector embeddings for semantic search by the LangGraph agent
    """

    def __init__(self):
        self.embedding_service = EmbeddingService()
        self.vector_store = VectorStore()

    def load_all_rules(self, clear_existing: bool = False) -> Dict:
        """
        Load all DPDPA rules into both databases.

        Args:
            clear_existing: If True, clear existing rules before loading

        Returns:
            Stats dict: {total, pg_inserted, weaviate_inserted, skipped, errors}
        """
        db = SessionLocal()
        stats = {
            "total": 0,
            "pg_inserted": 0,
            "weaviate_inserted": 0,
            "skipped": 0,
            "errors": 0,
            "details": [],
        }

        try:
            if clear_existing:
                clear_stats = self.clear_all_rules(db)
                stats["details"].append(f"Cleared: {clear_stats}")

            rules = get_all_rules()
            stats["total"] = len(rules)

            logger.info(f"Loading {len(rules)} DPDPA rules...")

            # Generate all embeddings in batch for efficiency
            embedding_texts = [self._create_embedding_text(rule) for rule in rules]
            embeddings = self.embedding_service.embed_batch(embedding_texts, show_progress=True)

            for i, rule in enumerate(rules):
                try:
                    # Check if rule already exists (idempotent)
                    existing = db.query(Guideline).filter(
                        Guideline.name == rule.rule_id
                    ).first()

                    if existing and not clear_existing:
                        stats["skipped"] += 1
                        stats["details"].append(f"Skipped (exists): {rule.rule_id}")
                        continue

                    # 1. Store in Weaviate with embedding
                    weaviate_id = self.vector_store.add_guideline(
                        guideline_id=rule.rule_id,
                        regulation_type="DPDPA",
                        clause_number=rule.section_ref,
                        requirement_text=rule.requirement_text,
                        embedding=embeddings[i],
                        severity=rule.severity,
                        category=rule.category,
                        metadata={
                            "check_types": rule.check_types,
                            "violation_condition": rule.violation_condition,
                            "video_specific": rule.video_specific,
                            "penalty_ref": rule.penalty_ref,
                        },
                    )
                    stats["weaviate_inserted"] += 1

                    # 2. Store in PostgreSQL
                    severity_map = {
                        "critical": GuidelineSeverity.CRITICAL,
                        "warning": GuidelineSeverity.WARNING,
                        "info": GuidelineSeverity.INFO,
                    }

                    guideline = Guideline(
                        name=rule.rule_id,
                        regulation_type="DPDPA",
                        version="2023+2025_Rules",
                        description=self._create_description(rule),
                        requirement_text=rule.requirement_text,
                        severity=severity_map.get(rule.severity, GuidelineSeverity.WARNING),
                        check_type=rule.check_types[0] if rule.check_types else None,
                        weaviate_id=weaviate_id,
                        clause_number=rule.section_ref,
                        penalty_ref=rule.penalty_ref,
                        check_types_json=rule.check_types,
                        category=rule.category,
                        is_active=True,
                    )
                    db.add(guideline)
                    stats["pg_inserted"] += 1

                    logger.debug(f"Loaded: {rule.rule_id} — {rule.name}")

                except Exception as e:
                    stats["errors"] += 1
                    stats["details"].append(f"Error loading {rule.rule_id}: {str(e)}")
                    logger.error(f"Error loading rule {rule.rule_id}: {e}")

            db.commit()
            logger.info(
                f"Loading complete: {stats['pg_inserted']} PostgreSQL, "
                f"{stats['weaviate_inserted']} Weaviate, "
                f"{stats['skipped']} skipped, {stats['errors']} errors"
            )

        except Exception as e:
            db.rollback()
            logger.error(f"Fatal error during loading: {e}")
            stats["errors"] += 1
            stats["details"].append(f"Fatal error: {str(e)}")
            raise

        finally:
            db.close()

        return stats

    def clear_all_rules(self, db=None) -> Dict:
        """
        Remove all DPDPA rules from both PostgreSQL and Weaviate.

        Returns:
            Stats dict: {pg_deleted, weaviate_cleared}
        """
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        stats = {"pg_deleted": 0, "weaviate_cleared": False}

        try:
            # Clear PostgreSQL
            deleted = db.query(Guideline).filter(
                Guideline.regulation_type == "DPDPA"
            ).delete()
            db.commit()
            stats["pg_deleted"] = deleted
            logger.info(f"Deleted {deleted} DPDPA guidelines from PostgreSQL")

            # Clear Weaviate Guidelines collection
            try:
                collection = self.vector_store.client.collections.get("Guidelines")
                collection.data.delete_many(
                    where=weaviate.classes.query.Filter.by_property("regulation_type").equal("DPDPA")
                )
                stats["weaviate_cleared"] = True
                logger.info("Cleared DPDPA guidelines from Weaviate")
            except Exception as e:
                logger.warning(f"Could not clear Weaviate guidelines: {e}")
                # Try alternate approach: delete and recreate collection
                try:
                    self.vector_store.client.collections.delete("Guidelines")
                    self.vector_store._init_collections()
                    stats["weaviate_cleared"] = True
                    logger.info("Recreated Guidelines collection in Weaviate")
                except Exception as e2:
                    logger.error(f"Failed to recreate Guidelines collection: {e2}")

        finally:
            if close_db:
                db.close()

        return stats

    def verify_load(self) -> Dict:
        """
        Verify that rules are loaded correctly in both stores.

        Returns:
            Verification report dict
        """
        db = SessionLocal()
        report = {
            "pg_count": 0,
            "weaviate_count": 0,
            "expected_count": len(get_all_rules()),
            "categories_found": [],
            "pg_ok": False,
            "weaviate_ok": False,
            "all_ok": False,
        }

        try:
            # Check PostgreSQL
            report["pg_count"] = db.query(Guideline).filter(
                Guideline.regulation_type == "DPDPA"
            ).count()
            report["pg_ok"] = report["pg_count"] == report["expected_count"]

            # Check categories
            categories = db.query(Guideline.category).filter(
                Guideline.regulation_type == "DPDPA"
            ).distinct().all()
            report["categories_found"] = [c[0] for c in categories]

            # Check Weaviate
            weaviate_stats = self.vector_store.get_stats()
            report["weaviate_count"] = weaviate_stats.get("guidelines_count", 0)
            report["weaviate_ok"] = report["weaviate_count"] >= report["expected_count"]

            report["all_ok"] = report["pg_ok"] and report["weaviate_ok"]

        except Exception as e:
            logger.error(f"Verification error: {e}")
            report["error"] = str(e)

        finally:
            db.close()

        return report

    def search_rules(self, query: str, limit: int = 5) -> List[Dict]:
        """
        Semantic search for relevant rules given a natural language query.

        Args:
            query: Natural language query (e.g., "consent for video recording")
            limit: Max results to return

        Returns:
            List of matching rules with similarity scores
        """
        query_embedding = self.embedding_service.embed(query)
        results = self.vector_store.search_guidelines(
            query_embedding=query_embedding,
            regulation_type="DPDPA",
            limit=limit,
        )

        return [
            {
                "rule_id": r.metadata.get("guideline_id"),
                "category": r.metadata.get("category"),
                "severity": r.metadata.get("severity"),
                "clause": r.metadata.get("clause_number"),
                "requirement": r.text,
                "similarity": round(r.score, 3),
            }
            for r in results
        ]

    def _create_embedding_text(self, rule: DPDPARule) -> str:
        """
        Create rich text for embedding that combines multiple fields
        for better semantic search quality.
        """
        parts = [
            rule.requirement_text,
            f"Violation: {rule.violation_condition}",
            f"Applies to: {rule.applicability}",
        ]
        if rule.detection_guidance:
            parts.append(f"Detection: {rule.detection_guidance}")
        return " ".join(parts)

    def _create_description(self, rule: DPDPARule) -> str:
        """Create a combined description for PostgreSQL storage"""
        parts = [
            f"[{rule.rule_id}] {rule.name}",
            f"Section: {rule.section_ref}",
            f"Violation: {rule.violation_condition}",
            f"Applies to: {rule.applicability}",
        ]
        if rule.video_specific:
            parts.append("(Video-Specific Rule)")
        return " | ".join(parts)

    def close(self):
        """Close connections"""
        self.vector_store.close()


# Add missing import at module level
import weaviate
import weaviate.classes.query
