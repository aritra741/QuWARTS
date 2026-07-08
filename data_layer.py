"""
Data Layer & State Management for WDIRS.
Implements PostgreSQL schema, metadata registry, and provenance tracking.
"""

import json
import logging
import uuid
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime

from sqlalchemy import (
    create_engine, Table, Column, String, Integer, Text, JSON,
    MetaData, DateTime, ForeignKey, Index, Boolean, select, insert, update, delete, text
)
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool

from config import (
    DATABASE_URI, STATUS_PARTIAL, STATUS_FULL,
    CHUNK_SIZE, CHUNK_OVERLAP, CHUNK_SEPARATORS
)

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class TextChunk:
    """Represents a chunk of text from source documents."""
    chunk_id: str
    doc_id: str
    content: str
    chunk_index: int
    metadata: Dict[str, Any]

@dataclass
class MetadataEntry:
    """Represents an entry in the metadata registry."""
    table_name: str
    column_name: str
    predicate_scope: List[str]
    status: str
    last_updated: datetime
    record_count: int

@dataclass
class ProvenanceRecord:
    """Links extracted rows to source chunks."""
    row_id: str
    table_name: str
    chunk_ids: List[str]


# ============================================================================
# Database Schema Manager
# ============================================================================

class DataLayer:
    """
    Manages all database operations for WDIRS.
    Handles text storage, metadata registry, and dynamic table creation.
    """
    
    def __init__(self, connection_uri: str = DATABASE_URI):
        """Initialize database connection and schema."""
        is_sqlite = 'sqlite' in connection_uri
        self.engine = create_engine(
            connection_uri,
            poolclass=NullPool,
            echo=False,
            connect_args={'check_same_thread': False} if is_sqlite else {}
        )

        # Enable WAL mode for SQLite: allows concurrent reads during writes
        # and dramatically reduces write contention from parallel extraction threads.
        if is_sqlite:
            with self.engine.connect() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL"))
                conn.execute(text("PRAGMA synchronous=NORMAL"))
                conn.execute(text("PRAGMA cache_size=-131072"))   # 128 MB page cache
                conn.execute(text("PRAGMA temp_store=MEMORY"))
                conn.commit()

        self.metadata = MetaData()
        self.Session = sessionmaker(bind=self.engine)
        
        # Define core tables
        self._define_core_tables()
        
        # Create all tables
        self.metadata.create_all(self.engine)
        
        logger.info("DataLayer initialized successfully")
    
    def _define_core_tables(self):
        """Define the core WDIRS tables."""
        
        # Raw_Chunks: Stores chunked text from source documents
        self.raw_chunks = Table(
            'raw_chunks',
            self.metadata,
            Column('chunk_id', String(36), primary_key=True),
            Column('doc_id', String(500), nullable=False, index=True),
            Column('content', Text, nullable=False),
            Column('chunk_index', Integer, nullable=False),
            Column('metadata', JSON, default='{}'),
            Column('created_at', DateTime, default=datetime.utcnow),
            # Unique constraint ensures the same document chunk is never stored twice,
            # even if ingest is called multiple times (e.g. once per query in a workload).
            Index('idx_doc_chunk', 'doc_id', 'chunk_index', unique=True)
        )
        
        # Metadata_Registry: Tracks completeness of synthesized tables
        self.metadata_registry = Table(
            'metadata_registry',
            self.metadata,
            Column('id', Integer, primary_key=True, autoincrement=True),
            Column('table_name', String(200), nullable=False),
            Column('column_name', String(200), nullable=False),
            Column('predicate_scope', JSON, default='[]'),
            Column('status', String(20), nullable=False),
            Column('last_updated', DateTime, default=datetime.utcnow, onupdate=datetime.utcnow),
            Column('record_count', Integer, default=0),
            Index('idx_table_column', 'table_name', 'column_name'),
            Index('idx_status', 'status')
        )
        
        # Row_Provenance: Links extracted rows to source chunks
        self.row_provenance = Table(
            'row_provenance',
            self.metadata,
            Column('row_id', String(36), primary_key=True),
            Column('table_name', String(200), nullable=False, index=True),
            Column('chunk_ids', JSON, nullable=False),
            Column('created_at', DateTime, default=datetime.utcnow)
        )
        
        # Candidate_Index: Stores sieve filtering results
        self.candidate_index = Table(
            'candidate_index',
            self.metadata,
            Column('id', Integer, primary_key=True, autoincrement=True),
            Column('table_name', String(200), nullable=False, index=True),
            Column('chunk_id', String(36), nullable=False),
            Column('relevance_score', Integer, default=1),
            Column('created_at', DateTime, default=datetime.utcnow),
            Index('idx_table_chunk', 'table_name', 'chunk_id', unique=True)
        )

        # Cell_Provenance: Per-cell source attribution (row × column → chunk + doc).
        # Allows the UI/evaluation to show exactly which document chunk supported
        # each extracted cell value.
        self.cell_provenance = Table(
            'cell_provenance',
            self.metadata,
            Column('id', Integer, primary_key=True, autoincrement=True),
            Column('row_id', String(36), nullable=False),
            Column('column_name', String(200), nullable=False),
            Column('chunk_id', String(36), nullable=False),
            Column('doc_id', String(500), nullable=False),
            Column('created_at', DateTime, default=datetime.utcnow),
            # (row_id, column_name) is unique: one source per cell.
            # If multiple chunks supported the same cell we keep the first writer.
            Index('idx_cell_prov', 'row_id', 'column_name', unique=True),
        )
    
    # ========================================================================
    # Text Chunk Operations
    # ========================================================================
    
    def insert_chunks(self, chunks: List[TextChunk]) -> int:
        """Insert text chunks into database, skipping duplicates.

        A chunk is a duplicate if the same (doc_id, chunk_index) pair already
        exists — which happens when the ingest pipeline is called multiple times
        for the same document (e.g. once per query in a multi-query workload).
        Using INSERT OR IGNORE on the unique (doc_id, chunk_index) index prevents
        the 13× inflation that otherwise turns ~222k unique chunks into 2.88M rows.
        """
        with self.Session() as session:
            try:
                # Prepare chunk data for bulk insert
                chunk_data = []
                for chunk in chunks:
                    chunk_data.append({
                        'chunk_id': str(chunk.chunk_id),
                        'doc_id': chunk.doc_id,
                        'content': chunk.content,
                        'chunk_index': chunk.chunk_index,
                        'metadata': json.dumps(chunk.metadata) if chunk.metadata else '{}'
                    })
                
                # Batch insert with OR IGNORE so duplicate (doc_id, chunk_index)
                # pairs are silently skipped instead of raising a constraint error.
                batch_size = 500
                inserted = 0
                for i in range(0, len(chunk_data), batch_size):
                    batch = chunk_data[i:i + batch_size]
                    result = session.execute(
                        insert(self.raw_chunks).prefix_with("OR IGNORE"), batch
                    )
                    inserted += result.rowcount
                
                session.commit()
                skipped = len(chunks) - inserted
                if skipped:
                    logger.debug(f"insert_chunks: {inserted} new, {skipped} duplicates skipped")
                else:
                    logger.info(f"Inserted {inserted} chunks")
                return len(chunks)
            except Exception as e:
                session.rollback()
                logger.error(f"Error inserting chunks: {e}")
                raise
    
    def get_chunks_by_doc(self, doc_id: str) -> List[TextChunk]:
        """Retrieve all chunks for a document."""
        with self.Session() as session:
            stmt = select(self.raw_chunks).where(
                self.raw_chunks.c.doc_id == doc_id
            ).order_by(self.raw_chunks.c.chunk_index)
            
            result = session.execute(stmt)
            rows = result.fetchall()
            
            return [
                TextChunk(
                    chunk_id=str(row.chunk_id),
                    doc_id=row.doc_id,
                    content=row.content,
                    chunk_index=row.chunk_index,
                    metadata=json.loads(row.metadata) if isinstance(row.metadata, str) else (row.metadata or {})
                )
                for row in rows
            ]
    
    def get_chunks_by_ids(self, chunk_ids: List[str]) -> List[TextChunk]:
        """Retrieve chunks by their IDs."""
        if not chunk_ids:
            return []
        
        # Batch requests to avoid SQLite parameter limit
        batch_size = 900  # Safe for SQLite (limit is usually 999)
        all_chunks = []
        
        with self.Session() as session:
            for i in range(0, len(chunk_ids), batch_size):
                batch_ids = chunk_ids[i:i + batch_size]
                str_ids = [str(cid) for cid in batch_ids]
                
                stmt = select(self.raw_chunks).where(
                    self.raw_chunks.c.chunk_id.in_(str_ids)
                )
                
                result = session.execute(stmt)
                rows = result.fetchall()
                
                for row in rows:
                    all_chunks.append(TextChunk(
                        chunk_id=str(row.chunk_id),
                        doc_id=row.doc_id,
                        content=row.content,
                        chunk_index=row.chunk_index,
                        metadata=row.metadata or {}
                    ))
            
            return all_chunks
    
    def get_all_chunks(self, limit: Optional[int] = None) -> List[TextChunk]:
        """Retrieve all chunks, optionally limited."""
        with self.Session() as session:
            stmt = select(self.raw_chunks).order_by(
                self.raw_chunks.c.doc_id,
                self.raw_chunks.c.chunk_index
            )
            
            if limit:
                stmt = stmt.limit(limit)
            
            result = session.execute(stmt)
            rows = result.fetchall()
            
            return [
                TextChunk(
                    chunk_id=str(row.chunk_id),
                    doc_id=row.doc_id,
                    content=row.content,
                    chunk_index=row.chunk_index,
                    metadata=json.loads(row.metadata) if isinstance(row.metadata, str) else (row.metadata or {})
                )
                for row in rows
            ]
    
    def count_chunks(self) -> int:
        """Count total chunks in database."""
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT COUNT(*) FROM raw_chunks")
            ).fetchone()
            return row[0] if row else 0

    def stream_chunks_paged(
        self,
        page_size: int = 10_000,
    ):
        """
        Yield pages of (chunk_id, content) tuples directly from the DB using
        LIMIT/OFFSET, so the full corpus is never held in RAM simultaneously.

        Each yielded page is a list of (chunk_id: str, content: str) tuples
        of length <= page_size.
        """
        offset = 0
        while True:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT chunk_id, content FROM raw_chunks "
                        "ORDER BY doc_id, chunk_index "
                        "LIMIT :lim OFFSET :off"
                    ),
                    {"lim": page_size, "off": offset},
                ).fetchall()
            if not rows:
                break
            yield [(str(r[0]), r[1]) for r in rows]
            if len(rows) < page_size:
                break
            offset += page_size
    
    # ========================================================================
    # Metadata Registry Operations
    # ========================================================================
    
    def update_metadata(
        self,
        table_name: str,
        column_name: str,
        predicate_scope: List[str],
        status: str,
        record_count: int = 0
    ) -> None:
        """Update or insert metadata registry entry."""
        with self.Session() as session:
            try:
                # Check if entry exists
                stmt = select(self.metadata_registry).where(
                    (self.metadata_registry.c.table_name == table_name) &
                    (self.metadata_registry.c.column_name == column_name)
                )
                result = session.execute(stmt)
                existing = result.fetchone()
                
                if existing:
                    # Update existing entry
                    update_stmt = update(self.metadata_registry).where(
                        (self.metadata_registry.c.table_name == table_name) &
                        (self.metadata_registry.c.column_name == column_name)
                    ).values(
                        predicate_scope=json.dumps(predicate_scope),
                        status=status,
                        record_count=record_count,
                        last_updated=datetime.utcnow()
                    )
                    session.execute(update_stmt)
                else:
                    # Insert new entry
                    insert_stmt = insert(self.metadata_registry).values(
                        table_name=table_name,
                        column_name=column_name,
                        predicate_scope=json.dumps(predicate_scope),
                        status=status,
                        record_count=record_count
                    )
                    session.execute(insert_stmt)
                
                session.commit()
                logger.debug(f"Updated metadata for {table_name}.{column_name}")
            except Exception as e:
                session.rollback()
                logger.error(f"Error updating metadata: {e}")
                raise
    
    def get_metadata(
        self,
        table_name: Optional[str] = None,
        column_name: Optional[str] = None
    ) -> List[MetadataEntry]:
        """Retrieve metadata entries."""
        with self.Session() as session:
            stmt = select(self.metadata_registry)
            
            if table_name:
                stmt = stmt.where(self.metadata_registry.c.table_name == table_name)
            if column_name:
                stmt = stmt.where(self.metadata_registry.c.column_name == column_name)
            
            result = session.execute(stmt)
            rows = result.fetchall()
            
            return [
                MetadataEntry(
                    table_name=row.table_name,
                    column_name=row.column_name,
                    predicate_scope=json.loads(row.predicate_scope) if isinstance(row.predicate_scope, str) else (row.predicate_scope or []),
                    status=row.status,
                    last_updated=row.last_updated,
                    record_count=row.record_count
                )
                for row in rows
            ]
    
    def check_materialization(
        self,
        table_name: str,
        columns: List[str],
        predicates: List[str]
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Check if requested columns and predicates are materialized.
        Returns: (is_complete, missing_columns, missing_predicates)
        """
        metadata_entries = self.get_metadata(table_name=table_name)
        
        # Build lookup
        column_map = {}
        for entry in metadata_entries:
            if entry.column_name not in column_map:
                column_map[entry.column_name] = {
                    'status': entry.status,
                    'predicates': set(entry.predicate_scope)
                }
        
        # Check columns
        missing_columns = []
        for col in columns:
            if col not in column_map:
                missing_columns.append(col)
        
        # Check predicates
        missing_predicates = []
        for pred in predicates:
            # Extract column from predicate (simple parsing)
            pred_col = pred.split('=')[0].strip() if '=' in pred else pred.split()[0].strip()

            if pred_col in column_map:
                col_entry = column_map[pred_col]
                # STATUS_FULL means ALL rows were extracted for this column —
                # any predicate value is already covered, no re-extraction needed.
                if col_entry['status'] == STATUS_FULL:
                    continue
                if pred not in col_entry['predicates']:
                    missing_predicates.append(pred)
            else:
                missing_predicates.append(pred)
        
        is_complete = len(missing_columns) == 0 and len(missing_predicates) == 0
        
        return is_complete, missing_columns, missing_predicates
    
    # ========================================================================
    # Provenance Operations
    # ========================================================================
    
    def insert_provenance(
        self,
        row_id: str,
        table_name: str,
        chunk_ids: List[str]
    ) -> None:
        """Insert a single provenance record."""
        # Use raw SQL so the JSON is stored as a plain array string, consistent
        # with bulk_insert_provenance.  The ORM JSON column type would
        # double-encode a pre-serialised string.
        with self.engine.connect() as conn:
            try:
                conn.execute(
                    text(
                        "INSERT OR IGNORE INTO row_provenance "
                        "(row_id, table_name, chunk_ids, created_at) "
                        "VALUES (:rid, :tname, :cids, :ts)"
                    ),
                    {
                        "rid": str(row_id),
                        "tname": table_name,
                        "cids": json.dumps(chunk_ids if isinstance(chunk_ids, list)
                                           else [chunk_ids]),
                        "ts": str(datetime.utcnow()),
                    },
                )
                conn.commit()
            except Exception as e:
                logger.error(f"Error inserting provenance: {e}")
                raise

    def bulk_insert_records(
        self,
        table_name: str,
        extraction_results: list,
    ) -> List[str]:
        """
        Insert all records from a list of ExtractionResult objects in a single
        transaction and return the generated row_ids paired with chunk_ids for
        provenance insertion.

        Returns list of (row_id, chunk_id) tuples.
        """
        row_provenance_pairs: List[tuple] = []

        # Fetch real column names once to strip LLM-hallucinated keys.
        with self.engine.connect() as _c:
            _rows = _c.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        valid_cols: set = {row[1] for row in _rows}

        with self.engine.connect() as conn:
            try:
                for extraction_result in extraction_results:
                    if extraction_result.error:
                        continue
                    for record in extraction_result.records:
                        # Filter to only real DB columns
                        clean = {k: v for k, v in record.items() if k in valid_cols}
                        if not clean:
                            continue
                        row_id = str(uuid.uuid4())
                        full_record = {"row_id": row_id, **clean}
                        columns = list(full_record.keys())
                        params = {}
                        for col in columns:
                            val = full_record[col]
                            if val is None:
                                params[col] = None
                            elif isinstance(val, (list, dict)):
                                params[col] = json.dumps(val)
                            else:
                                params[col] = val

                        columns_str = ", ".join(columns)
                        placeholders = ", ".join([f":{c}" for c in columns])
                        sql = f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders})"
                        conn.execute(text(sql), params)
                        row_provenance_pairs.append((row_id, extraction_result.chunk_id))

                conn.commit()
            except Exception as e:
                logger.error(f"Error bulk inserting into {table_name}: {e}")
                raise

        return row_provenance_pairs

    def bulk_insert_provenance(
        self,
        table_name: str,
        row_provenance_pairs: List[tuple],
    ) -> None:
        """
        Upsert provenance for all (row_id, chunk_id) pairs.

        Multiple chunks may map to the same row_id (e.g. when entity-first
        extraction assigns several chunks to the same entity row).  We
        aggregate all chunk_ids per row_id first, then either INSERT a new
        provenance row or append to the existing chunk_ids list.
        """
        if not row_provenance_pairs:
            return

        # Aggregate chunk_ids per row_id so we write one provenance row
        # per entity row, not one per chunk.
        from collections import defaultdict as _dd
        row_chunks: dict = _dd(list)
        for row_id, chunk_id in row_provenance_pairs:
            row_chunks[row_id].append(chunk_id)

        with self.engine.connect() as conn:
            try:
                for row_id, chunk_ids in row_chunks.items():
                    # Check if a provenance row already exists for this row_id.
                    existing = conn.execute(
                        text(
                            "SELECT chunk_ids FROM row_provenance "
                            "WHERE row_id = :rid"
                        ),
                        {"rid": row_id},
                    ).fetchone()

                    if existing:
                        # Merge new chunk_ids into the stored list.
                        try:
                            parsed = json.loads(existing[0]) if existing[0] else []
                        except (TypeError, ValueError):
                            parsed = []
                        # json.loads may return a scalar (str/int) if the stored
                        # value was not serialised as a JSON array — always coerce.
                        stored: list = parsed if isinstance(parsed, list) else [parsed]
                        merged = list(dict.fromkeys(stored + chunk_ids))  # dedup, preserve order
                        conn.execute(
                            text(
                                "UPDATE row_provenance SET chunk_ids = :cids "
                                "WHERE row_id = :rid"
                            ),
                            {"cids": json.dumps(merged), "rid": row_id},
                        )
                    else:
                        conn.execute(
                            text(
                                "INSERT INTO row_provenance "
                                "(row_id, table_name, chunk_ids, created_at) "
                                "VALUES (:rid, :tname, :cids, :ts)"
                            ),
                            {
                                "rid": row_id,
                                "tname": table_name,
                                "cids": json.dumps(chunk_ids),
                                "ts": str(datetime.utcnow()),
                            },
                        )

                conn.commit()
            except Exception as e:
                logger.error(f"Error upserting provenance: {e}")
                raise

    def bulk_insert_cell_provenance(
        self,
        cell_prov_triples: List[tuple],
    ) -> None:
        """
        Record per-cell source attribution.

        Parameters
        ----------
        cell_prov_triples : list of (row_id, column_name, chunk_id, doc_id)
            Each tuple says: "the value stored in column `column_name` of row
            `row_id` was extracted from chunk `chunk_id` of document `doc_id`."

        The unique index on (row_id, column_name) means only the FIRST writer
        wins — subsequent chunks that filled the same cell are not re-recorded
        (the COALESCE update path never overwrites a non-NULL cell anyway).
        """
        if not cell_prov_triples:
            return

        with self.engine.connect() as conn:
            try:
                ts = str(datetime.utcnow())
                for row_id, col_name, chunk_id, doc_id in cell_prov_triples:
                    conn.execute(
                        text(
                            "INSERT OR IGNORE INTO cell_provenance "
                            "(row_id, column_name, chunk_id, doc_id, created_at) "
                            "VALUES (:rid, :col, :cid, :did, :ts)"
                        ),
                        {
                            "rid": row_id,
                            "col": col_name,
                            "cid": chunk_id,
                            "did": doc_id,
                            "ts": ts,
                        },
                    )
                conn.commit()
            except Exception as exc:
                logger.error(f"Error inserting cell provenance: {exc}")
                raise

    def update_provenance_chunks(
        self,
        row_id: str,
        chunk_ids: List[str]
    ) -> None:
        """Replace the chunk_ids for an existing provenance record."""
        with self.Session() as session:
            try:
                stmt = text(
                    "UPDATE row_provenance SET chunk_ids = :chunk_ids WHERE row_id = :row_id"
                )
                session.execute(stmt, {"chunk_ids": json.dumps(chunk_ids), "row_id": row_id})
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Error updating provenance chunks for {row_id}: {e}")
                raise

    def delete_provenance(self, row_id: str) -> None:
        """Delete provenance record for a row."""
        with self.Session() as session:
            try:
                stmt = text("DELETE FROM row_provenance WHERE row_id = :row_id")
                session.execute(stmt, {"row_id": row_id})
                session.commit()
            except Exception as e:
                session.rollback()
                logger.error(f"Error deleting provenance for {row_id}: {e}")
                raise
    
    def get_provenance(
        self,
        row_ids: Optional[List[str]] = None,
        table_name: Optional[str] = None
    ) -> List[ProvenanceRecord]:
        """Retrieve provenance records."""
        with self.Session() as session:
            stmt = select(self.row_provenance)
            
            if table_name:
                stmt = stmt.where(self.row_provenance.c.table_name == table_name)
            
            if row_ids:
                # Batch queries to avoid parameter limit
                batch_size = 900
                all_records = []
                
                for i in range(0, len(row_ids), batch_size):
                    batch_ids = row_ids[i:i + batch_size]
                    str_ids = [str(rid) for rid in batch_ids]
                    
                    batch_stmt = stmt.where(self.row_provenance.c.row_id.in_(str_ids))
                    result = session.execute(batch_stmt)
                    rows = result.fetchall()
                    
                    for row in rows:
                        all_records.append(ProvenanceRecord(
                            row_id=str(row.row_id),
                            table_name=row.table_name,
                            chunk_ids=json.loads(row.chunk_ids) if isinstance(row.chunk_ids, str) else (row.chunk_ids or [])
                        ))
                
                return all_records
            else:
                result = session.execute(stmt)
                rows = result.fetchall()
                
                return [
                    ProvenanceRecord(
                        row_id=str(row.row_id),
                        table_name=row.table_name,
                        chunk_ids=json.loads(row.chunk_ids) if isinstance(row.chunk_ids, str) else (row.chunk_ids or [])
                    )
                    for row in rows
                ]
    
    # ========================================================================
    # Candidate Index Operations
    # ========================================================================
    
    def insert_candidates(
        self,
        table_name: str,
        chunk_ids: List[str],
        relevance_scores: Optional[List[int]] = None
    ) -> int:
        """Insert candidate chunks for a table."""
        with self.Session() as session:
            try:
                if relevance_scores is None:
                    relevance_scores = [1] * len(chunk_ids)
                
                # Get existing chunk_ids to avoid duplicates
                existing_ids = set()
                existing_result = session.execute(
                    select(self.candidate_index.c.chunk_id).where(
                        self.candidate_index.c.table_name == table_name
                    )
                ).fetchall()
                existing_ids = {str(row.chunk_id) for row in existing_result}
                
                # Prepare new candidates (filter out existing)
                new_candidates = []
                for chunk_id, score in zip(chunk_ids, relevance_scores):
                    chunk_id_str = str(chunk_id)
                    if chunk_id_str not in existing_ids:
                        new_candidates.append({
                            'table_name': table_name,
                            'chunk_id': chunk_id_str,
                            'relevance_score': score
                        })
                
                # Batch insert in chunks to avoid SQLite parameter limit (999)
                batch_size = 500  # Safe batch size for SQLite
                inserted_count = 0
                
                for i in range(0, len(new_candidates), batch_size):
                    batch = new_candidates[i:i + batch_size]
                    if batch:
                        session.execute(insert(self.candidate_index), batch)
                        inserted_count += len(batch)
                
                session.commit()
                logger.info(f"Inserted {inserted_count} new candidates for {table_name} (skipped {len(chunk_ids) - inserted_count} duplicates)")
                return inserted_count
            except Exception as e:
                session.rollback()
                logger.error(f"Error inserting candidates: {e}")
                raise
    
    def get_candidates(self, table_name: str) -> List[str]:
        """Retrieve candidate chunk IDs for a table."""
        with self.Session() as session:
            stmt = select(self.candidate_index.c.chunk_id).where(
                self.candidate_index.c.table_name == table_name
            ).order_by(self.candidate_index.c.relevance_score.desc())
            
            result = session.execute(stmt)
            rows = result.fetchall()
            
            return [str(row.chunk_id) for row in rows]
    
    # ========================================================================
    # Dynamic Table Management
    # ========================================================================
    
    def create_dynamic_table(
        self,
        table_name: str,
        schema: Dict[str, str]
    ) -> None:
        """
        Create a dynamic table for extracted data.
        schema: {column_name: sql_type}
        """
        with self.engine.connect() as conn:
            try:
                existed = self.table_exists(table_name)
                # Build CREATE TABLE statement
                columns = [
                    f"{col_name} {col_type}"
                    for col_name, col_type in schema.items()
                ]
                
                # Add standard columns
                columns.insert(0, "row_id TEXT PRIMARY KEY")
                columns.append("created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                
                create_stmt = f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    {', '.join(columns)}
                )
                """
                
                conn.execute(text(create_stmt))
                conn.commit()
                if existed:
                    logger.info(f"Table already exists: {table_name}")
                else:
                    logger.info(f"Created table: {table_name}")
            except Exception as e:
                logger.error(f"Error creating table {table_name}: {e}")
                raise
    
    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists."""
        with self.engine.connect() as conn:
            result = conn.execute(text("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name = :table_name
            """), {"table_name": table_name})
            return result.fetchone() is not None
    
    def execute_sql(self, query: str) -> List[Dict[str, Any]]:
        """
        Execute an arbitrary read-only SQL query against the DB and return
        results as a list of dicts.  Raises RuntimeError on failure.
        """
        with self.engine.connect() as conn:
            try:
                result = conn.execute(text(query))
                col_names = list(result.keys())
                return [dict(zip(col_names, row)) for row in result.fetchall()]
            except Exception as e:
                logger.error(f"SQL execution failed: {e}")
                raise RuntimeError(f"SQL execution failed: {e}") from e

    def get_distinct_values(self, table_name: str, column_name: str) -> List[str]:
        """Get all distinct values from a column in a dynamic table."""
        with self.engine.connect() as conn:
            try:
                result = conn.execute(
                    text(
                        f"SELECT DISTINCT {column_name} FROM {table_name} "
                        f"WHERE {column_name} IS NOT NULL"
                    )
                )
                return [str(row[0]) for row in result.fetchall()]
            except Exception as e:
                logger.error(f"Error getting distinct values from {table_name}.{column_name}: {e}")
                return []

    def update_column_values(
        self,
        table_name: str,
        column_name: str,
        value_map: Dict[str, str]
    ) -> int:
        """
        Update column values based on a mapping (old_value → new_value).
        Returns the number of rows updated.
        """
        with self.engine.connect() as conn:
            try:
                updated_count = 0
                for old_value, new_value in value_map.items():
                    result = conn.execute(
                        text(
                            f"UPDATE {table_name} SET {column_name} = :new_value "
                            f"WHERE {column_name} = :old_value"
                        ),
                        {"new_value": new_value, "old_value": old_value},
                    )
                    updated_count += result.rowcount
                conn.commit()
                logger.info(f"Updated {updated_count} rows in {table_name}.{column_name}")
                return updated_count
            except Exception as e:
                logger.error(f"Error updating column values in {table_name}.{column_name}: {e}")
                raise
    
    def insert_record(
        self,
        table_name: str,
        record: Dict[str, Any]
    ) -> str:
        """
        Insert a record into a dynamic table.
        Returns the generated row_id.
        """
        with self.engine.connect() as conn:
            try:
                # Fetch valid columns and strip any LLM-hallucinated keys.
                _valid = {
                    row[1] for row in
                    conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
                }
                clean_record = {k: v for k, v in record.items() if k in _valid}

                row_id = str(uuid.uuid4())
                full_record = {"row_id": row_id, **clean_record}

                columns = list(full_record.keys())
                values = [full_record[col] for col in columns]

                columns_str = ", ".join(columns)
                placeholders = ", ".join([f":{col}" for col in columns])

                sql = f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders})"

                params = {}
                for col, val in zip(columns, values):
                    if val is None:
                        params[col] = None
                    elif isinstance(val, (list, dict)):
                        params[col] = json.dumps(val)
                    else:
                        params[col] = val

                conn.execute(text(sql), params)
                conn.commit()
                
                return row_id
            except Exception as e:
                logger.error(f"Error inserting record into {table_name}: {e}")
                raise

    def upsert_by_entity(
        self,
        table_name: str,
        identity_col: str,
        record_chunk_triples: List[tuple],
        allow_insert_new_entities: bool = True,
    ) -> tuple:
        """
        Bulk upsert records using the `_entity` routing field.

        Each element of record_chunk_triples is (record_dict, chunk_id, doc_id).
        record_dict must contain `_entity` whose value is the identity value to
        match against identity_col in the DB.

        For each unique entity:
          - If a row already exists: UPDATE only NULL columns (COALESCE, never
            overwrite existing data).
          - Otherwise:
              * if allow_insert_new_entities=True: INSERT a new row.
              * if allow_insert_new_entities=False: skip (known-identity-only mode).

        `_entity` is stripped from the record before writing.

        Returns
        -------
        row_prov_pairs : List[(row_id, chunk_id)]
            For bulk_insert_provenance — one pair per (entity, chunk) that
            contributed to the row.
        cell_prov_triples : List[(row_id, col, chunk_id, doc_id)]
            For bulk_insert_cell_provenance — one triple per non-null cell
            that was written.  On UPDATE, only newly-filled cells are recorded.
        """
        # Fetch real column names once to strip LLM-hallucinated keys.
        with self.engine.connect() as _c:
            _rows = _c.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        valid_cols: set = {row[1] for row in _rows}

        def _sanitize(record: Dict[str, Any]) -> Dict[str, Any]:
            return {
                k: v for k, v in record.items()
                if k == "_entity" or k in valid_cols
            }

        # Group all triples by canonical entity key.
        entity_groups: Dict[str, List[tuple]] = {}
        no_entity: List[tuple] = []
        for triple in record_chunk_triples:
            # Support old 2-tuple callers (brute-force path) by defaulting doc_id.
            record, chunk_id, *rest = triple
            doc_id = rest[0] if rest else ""
            record = _sanitize(record)
            entity_val = record.get("_entity")
            if not entity_val or not str(entity_val).strip():
                no_entity.append((record, chunk_id, doc_id))
                continue
            key = str(entity_val).strip().lower()
            entity_groups.setdefault(key, []).append((record, chunk_id, doc_id))

        if no_entity:
            if allow_insert_new_entities:
                logger.warning(
                    f"[upsert_by_entity] {len(no_entity)} records for '{table_name}' "
                    f"have no _entity — inserting as new rows."
                )
            else:
                logger.info(
                    f"[upsert_by_entity] {len(no_entity)} records for '{table_name}' "
                    "have no _entity — skipped (known-identity-only mode)."
                )

        row_prov_pairs: List[tuple] = []
        cell_prov_triples: List[tuple] = []

        with self.engine.connect() as conn:
            # --- Records with entity routing ---
            for entity_key, group in entity_groups.items():
                canonical_entity = group[0][0].get("_entity", "").strip()

                try:
                    existing = conn.execute(
                        text(
                            f"SELECT row_id FROM {table_name} "
                            f"WHERE LOWER(CAST({identity_col} AS TEXT)) = :val LIMIT 1"
                        ),
                        {"val": entity_key},
                    ).fetchone()
                except Exception:
                    existing = None

                if existing:
                    existing_row_id = existing[0]

                    # Determine which columns are currently NULL so we can record
                    # cell provenance only for cells that actually get filled.
                    try:
                        null_cols_row = conn.execute(
                            text(f"SELECT * FROM {table_name} WHERE row_id = :rid"),
                            {"rid": existing_row_id},
                        ).fetchone()
                        null_cols: set = {
                            col for col, val in zip(
                                null_cols_row._mapping.keys(),   # type: ignore[union-attr]
                                null_cols_row,
                            )
                            if val is None
                        }
                    except Exception:
                        null_cols = set()

                    # Merge: first non-null value per column wins, track source.
                    merged: Dict[str, Any] = {}
                    col_source: Dict[str, tuple] = {}  # col → (chunk_id, doc_id)
                    for record, chunk_id, doc_id in group:
                        for k, v in record.items():
                            if k == "_entity":
                                continue
                            if v is not None and k not in merged:
                                merged[k] = v
                                col_source[k] = (chunk_id, doc_id)

                    if merged:
                        set_parts = [
                            f"{col} = COALESCE({col}, :{col})" for col in merged
                        ]
                        params: Dict[str, Any] = {}
                        for col, val in merged.items():
                            params[col] = json.dumps(val) if isinstance(val, (list, dict)) else val
                        params["_row_id"] = existing_row_id
                        conn.execute(
                            text(
                                f"UPDATE {table_name} SET {', '.join(set_parts)} "
                                f"WHERE row_id = :_row_id"
                            ),
                            params,
                        )
                        # Cell provenance only for columns that were NULL before.
                        for col, val in merged.items():
                            if col in null_cols and val is not None:
                                cid, did = col_source.get(col, ("", ""))
                                cell_prov_triples.append(
                                    (existing_row_id, col, cid, did)
                                )

                    for _, chunk_id, _doc_id in group:
                        row_prov_pairs.append((existing_row_id, chunk_id))

                else:
                    # INSERT new row (or skip in known-identity-only mode).
                    if not allow_insert_new_entities:
                        continue
                    merged = {}
                    col_source = {}
                    for record, chunk_id, doc_id in group:
                        for k, v in record.items():
                            if k == "_entity":
                                continue
                            if k not in merged and v is not None:
                                merged[k] = v
                                col_source[k] = (chunk_id, doc_id)
                    if identity_col not in merged:
                        merged[identity_col] = canonical_entity

                    row_id = str(uuid.uuid4())
                    full_record = {"row_id": row_id, **merged}
                    columns = list(full_record.keys())
                    params = {}
                    for col in columns:
                        val = full_record[col]
                        params[col] = (
                            json.dumps(val) if isinstance(val, (list, dict)) else val
                        )
                    sql = (
                        f"INSERT INTO {table_name} "
                        f"({', '.join(columns)}) "
                        f"VALUES ({', '.join(':' + c for c in columns)})"
                    )
                    conn.execute(text(sql), params)
                    for _, chunk_id, _doc_id in group:
                        row_prov_pairs.append((row_id, chunk_id))
                    # Cell provenance for all non-null cells of the new row.
                    for col, val in merged.items():
                        if val is not None and col != "row_id":
                            cid, did = col_source.get(col, ("", ""))
                            cell_prov_triples.append((row_id, col, cid, did))

            # --- Records without entity routing ---
            if allow_insert_new_entities:
                for record, chunk_id, doc_id in no_entity:
                    clean = {k: v for k, v in record.items() if k != "_entity"}
                    row_id = str(uuid.uuid4())
                    full_record = {"row_id": row_id, **clean}
                    columns = list(full_record.keys())
                    params = {}
                    for col in columns:
                        val = full_record[col]
                        params[col] = (
                            json.dumps(val) if isinstance(val, (list, dict)) else val
                        )
                    sql = (
                        f"INSERT INTO {table_name} "
                        f"({', '.join(columns)}) "
                        f"VALUES ({', '.join(':' + c for c in columns)})"
                    )
                    conn.execute(text(sql), params)
                    row_prov_pairs.append((row_id, chunk_id))
                    for col, val in clean.items():
                        if val is not None and col != "row_id":
                            cell_prov_triples.append((row_id, col, chunk_id, doc_id))

            conn.commit()

        return row_prov_pairs, cell_prov_triples

    def get_all_records(self, table_name: str) -> List[Dict[str, Any]]:
        """Return all rows from a dynamic table as a list of dicts."""
        with self.engine.connect() as conn:
            try:
                result = conn.execute(text(f"SELECT * FROM {table_name}"))
                columns = result.keys()
                return [dict(zip(columns, row)) for row in result.fetchall()]
            except Exception as e:
                logger.error(f"Error fetching all records from {table_name}: {e}")
                raise

    def update_record(
        self,
        table_name: str,
        row_id: str,
        data: Dict[str, Any]
    ) -> None:
        """Update specific fields of an existing row identified by row_id."""
        if not data:
            return
        with self.engine.connect() as conn:
            try:
                set_clauses = ", ".join([f"{col} = :{col}" for col in data.keys()])
                params = {col: (json.dumps(val) if isinstance(val, (list, dict)) else val)
                          for col, val in data.items()}
                params["_row_id"] = row_id
                sql = f"UPDATE {table_name} SET {set_clauses} WHERE row_id = :_row_id"
                conn.execute(text(sql), params)
                conn.commit()
            except Exception as e:
                logger.error(f"Error updating record {row_id} in {table_name}: {e}")
                raise

    def delete_record(self, table_name: str, row_id: str) -> None:
        """Delete a row from a dynamic table by row_id."""
        with self.engine.connect() as conn:
            try:
                conn.execute(
                    text(f"DELETE FROM {table_name} WHERE row_id = :row_id"),
                    {"row_id": row_id}
                )
                conn.commit()
            except Exception as e:
                logger.error(f"Error deleting record {row_id} from {table_name}: {e}")
                raise

    def create_chunks(
        self,
        text: str,
        doc_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[TextChunk]:
        """Create TextChunk objects from text using RecursiveCharacterSplitter."""
        return RecursiveCharacterSplitter().create_chunks(text, doc_id, metadata)

    def reset_ingestion(self) -> None:
        """
        Delete all raw chunks and candidate index rows so ingestion can be
        re-run with new chunking parameters (e.g. after changing CHUNK_SIZE).
        Does NOT drop synthesized tables or provenance — only the input layer.
        Call this when chunk size or overlap changes require re-ingestion.
        """
        with self.engine.connect() as conn:
            conn.execute(text("DELETE FROM candidate_index"))
            conn.execute(text("DELETE FROM raw_chunks"))
            conn.commit()
        logger.info("reset_ingestion: raw_chunks and candidate_index cleared")

    def close(self):
        """Close database connections."""
        self.engine.dispose()
        logger.info("DataLayer connections closed")


# ============================================================================
# Text Chunking Utilities
# ============================================================================

class RecursiveCharacterSplitter:
    """
    Implements recursive character splitting for text chunking.
    Based on LangChain's RecursiveCharacterTextSplitter.
    """

    def __init__(
        self,
        chunk_size: int = CHUNK_SIZE,
        chunk_overlap: int = CHUNK_OVERLAP,
        separators: List[str] = CHUNK_SEPARATORS
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators

    def split_text(self, text: str) -> List[str]:
        """Split text into chunks recursively."""
        return self._split_text_recursive(text, self.separators)

    def _split_text_recursive(
        self,
        text: str,
        separators: List[str]
    ) -> List[str]:
        """Recursively split text using separators."""
        if not separators:
            return self._split_by_length(text)

        separator = separators[0]
        remaining_separators = separators[1:]

        if separator:
            splits = text.split(separator)
        else:
            splits = list(text)

        chunks = []
        current_chunk = ""

        for split in splits:
            if len(current_chunk) + len(split) <= self.chunk_size:
                current_chunk += split + separator
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())

                if len(split) > self.chunk_size:
                    sub_chunks = self._split_text_recursive(split, remaining_separators)
                    chunks.extend(sub_chunks)
                    current_chunk = ""
                else:
                    current_chunk = split + separator

        if current_chunk:
            chunks.append(current_chunk.strip())

        return self._merge_with_overlap(chunks)

    def _split_by_length(self, text: str) -> List[str]:
        """Split text by fixed length."""
        chunks = []
        for i in range(0, len(text), self.chunk_size - self.chunk_overlap):
            chunks.append(text[i:i + self.chunk_size])
        return chunks

    def _merge_with_overlap(self, chunks: List[str]) -> List[str]:
        """Add overlap between chunks."""
        if not chunks or self.chunk_overlap == 0:
            return chunks

        merged = []
        for i, chunk in enumerate(chunks):
            if i > 0 and self.chunk_overlap > 0:
                prev_chunk = chunks[i - 1]
                overlap = prev_chunk[-self.chunk_overlap:]
                chunk = overlap + chunk
            merged.append(chunk)

        return merged

    def create_chunks(
        self,
        text: str,
        doc_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[TextChunk]:
        """Split text and wrap each piece in a TextChunk with a unique ID."""
        splits = self.split_text(text)
        return [
            TextChunk(
                chunk_id=str(uuid.uuid4()),
                doc_id=doc_id,
                content=content,
                chunk_index=idx,
                metadata=metadata or {},
            )
            for idx, content in enumerate(splits)
        ]
