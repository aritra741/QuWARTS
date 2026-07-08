"""
Test suite for WDIRS system.
"""

import pytest
import json
from pathlib import Path
import tempfile
import shutil

from data_layer import DataLayer, RecursiveCharacterSplitter, TextChunk
from lattice_planner import LatticePlanner
from sieve_synthesizer import SieveSynthesizer
from extractor import ConstrainedExtractor, OllamaClient
from entity_resolver import EntityResolver, EntityMention
from delta_engine import DeltaEngine, DeltaType
from wdirs_runner import WDIRSRunner


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_dir():
    """Create temporary directory for tests."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path)


@pytest.fixture
def sample_text():
    """Sample text for testing."""
    return """
    Patient John Doe was diagnosed with Type 2 Diabetes Mellitus on January 15, 2023.
    The treatment includes Metformin 500mg twice daily. The patient's status is Approved.
    Dr. Sarah Smith is the attending physician at Memorial Hospital.
    """


@pytest.fixture
def sample_queries():
    """Sample SQL queries for testing."""
    return [
        "SELECT disease_name, status FROM disease WHERE status = 'Approved'",
        "SELECT disease_name, treatment FROM disease WHERE status = 'Denied'",
        "SELECT patient_name, physician FROM patient WHERE hospital = 'Memorial'"
    ]


# ============================================================================
# Data Layer Tests
# ============================================================================

class TestDataLayer:
    """Tests for data layer."""
    
    def test_text_chunking(self, sample_text):
        """Test recursive character splitting."""
        splitter = RecursiveCharacterSplitter(chunk_size=100, chunk_overlap=20)
        chunks = splitter.create_chunks(sample_text, "test_doc")
        
        assert len(chunks) > 0
        assert all(isinstance(c, TextChunk) for c in chunks)
        assert chunks[0].doc_id == "test_doc"
    
    def test_chunk_overlap(self):
        """Test that chunks have proper overlap."""
        text = "A" * 200 + "B" * 200
        splitter = RecursiveCharacterSplitter(chunk_size=100, chunk_overlap=20)
        chunks = splitter.split_text(text)
        
        assert len(chunks) >= 2
        # Check overlap exists
        if len(chunks) >= 2:
            assert chunks[1][:20] == chunks[0][-20:]


# ============================================================================
# Lattice Planner Tests
# ============================================================================

class TestLatticePlanner:
    """Tests for lattice planner."""
    
    def test_query_parsing(self, sample_queries):
        """Test SQL query parsing."""
        planner = LatticePlanner()
        lattice = planner.parse_workload(sample_queries)
        
        assert len(lattice.tables) > 0
        assert "disease" in lattice.tables
        assert "patient" in lattice.tables
    
    def test_column_extraction(self):
        """Test column extraction from queries."""
        planner = LatticePlanner()
        query = "SELECT name, age FROM person WHERE age > 30"
        lattice = planner.parse_workload([query])
        
        assert "person" in lattice.tables
        table = lattice.tables["person"]
        assert "name" in table.columns
        assert "age" in table.columns
    
    def test_predicate_extraction(self):
        """Test predicate extraction."""
        planner = LatticePlanner()
        query = "SELECT * FROM disease WHERE status = 'Approved'"
        lattice = planner.parse_workload([query])
        
        table = lattice.tables["disease"]
        assert len(table.predicates) > 0
        assert any("status" in pred for pred in table.predicates)
    
    def test_semantic_type_identification(self):
        """Test semantic type identification."""
        planner = LatticePlanner()
        
        # Test heuristic types
        assert planner._heuristic_semantic_type("patient_name") == "PERSON"
        assert planner._heuristic_semantic_type("hospital") == "ORG"
        assert planner._heuristic_semantic_type("admission_date") == "DATE"
        assert planner._heuristic_semantic_type("city") == "GPE"
        assert planner._heuristic_semantic_type("icd_code") == "CODE"


# ============================================================================
# Sieve Synthesizer Tests
# ============================================================================

class TestSieveSynthesizer:
    """Tests for sieve synthesizer."""
    
    def test_keyword_extraction(self, sample_text):
        """Test keyword extraction from sample."""
        # Mock LLM client
        class MockLLM:
            def generate(self, prompt, **kwargs):
                return """
import re
from flashtext import KeywordProcessor

def is_relevant(text: str) -> bool:
    keywords = ["diabetes", "patient", "treatment"]
    return any(k in text.lower() for k in keywords)
"""
        
        synthesizer = SieveSynthesizer(MockLLM())
        schema = {"disease_name": "DISEASE", "status": "STATUS"}
        
        keywords, patterns, entity_types = synthesizer._analyze_samples(
            [sample_text],
            schema
        )
        
        assert len(keywords) > 0 or len(patterns) > 0 or len(entity_types) > 0
    
    def test_column_variations(self):
        """Test column name variation generation."""
        synthesizer = SieveSynthesizer(None)
        
        variations = synthesizer._generate_column_variations("disease_name")
        assert "disease name" in variations
        assert "disease_names" in variations or "disease_nam" in variations


# ============================================================================
# Extractor Tests
# ============================================================================

class TestExtractor:
    """Tests for extractor."""
    
    def test_json_extraction(self):
        """Test JSON extraction from text."""
        extractor = ConstrainedExtractor()
        
        response = """
        Here are the results:
        [
            {"name": "John", "age": 30},
            {"name": "Jane", "age": 25}
        ]
        """
        
        json_str = extractor._extract_json(response)
        assert json_str is not None
        
        data = json.loads(json_str)
        assert len(data) == 2
    
    def test_extraction_prompt_building(self, sample_text):
        """Test extraction prompt construction."""
        extractor = ConstrainedExtractor()
        
        schema = {"disease_name": "DISEASE", "status": "STATUS"}
        constrained_keys = {"disease_name", "status"}
        
        prompt = extractor._build_extraction_prompt(
            sample_text,
            "disease",
            schema,
            constrained_keys
        )
        
        assert "disease" in prompt.lower()
        assert "disease_name" in prompt
        assert "status" in prompt


# ============================================================================
# Entity Resolver Tests
# ============================================================================

class TestEntityResolver:
    """Tests for entity resolver."""
    
    def test_union_find(self):
        """Test Union-Find data structure."""
        from entity_resolver import UnionFind
        
        uf = UnionFind(5)
        uf.union(0, 1)
        uf.union(2, 3)
        uf.union(1, 2)
        
        # 0, 1, 2, 3 should be in same cluster
        assert uf.find(0) == uf.find(3)
        # 4 should be separate
        assert uf.find(4) != uf.find(0)
        
        clusters = uf.get_clusters()
        assert len(clusters) == 2
    
    def test_mention_extraction(self):
        """Test mention extraction from records."""
        from entity_resolver import extract_mentions_from_records
        
        records = [
            {"disease_name": "Diabetes", "status": "Approved"},
            {"disease_name": "Hypertension", "status": "Denied"}
        ]
        
        schema = {"disease_name": "DISEASE", "status": "STATUS"}
        
        mentions = extract_mentions_from_records(records, "disease", schema)
        
        assert len(mentions) == 4  # 2 records × 2 fields
        assert any(m.value == "Diabetes" for m in mentions)
    
    def test_canonical_map_application(self):
        """Test applying canonical map to records."""
        from entity_resolver import apply_canonical_map
        
        records = [
            {"disease": "Type 2 Diabetes"},
            {"disease": "Diabetes Type II"}
        ]
        
        canonical_map = {
            "type 2 diabetes": "Type 2 Diabetes Mellitus",
            "diabetes type ii": "Type 2 Diabetes Mellitus"
        }
        
        normalized = apply_canonical_map(records, canonical_map)
        
        assert normalized[0]["disease"] == "Type 2 Diabetes Mellitus"
        assert normalized[1]["disease"] == "Type 2 Diabetes Mellitus"


# ============================================================================
# Delta Engine Tests
# ============================================================================

class TestDeltaEngine:
    """Tests for delta engine."""
    
    def test_query_analysis(self, sample_queries):
        """Test query analysis and delta type determination."""
        # This test would require a full setup with data layer
        # Simplified test
        pass
    
    def test_delta_type_determination(self):
        """Test delta type logic."""
        # Mock delta engine
        from delta_engine import DeltaEngine
        
        # Would need proper initialization
        pass


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """Integration tests for full pipeline."""
    
    def test_end_to_end_simple(self, temp_dir, sample_text):
        """Test simple end-to-end flow."""
        # This would require:
        # 1. Setting up test database
        # 2. Creating test documents
        # 3. Running preprocessing
        # 4. Executing queries
        # 5. Validating results
        
        # Simplified test - just check imports work
        from wdirs_runner import WDIRSRunner
        
        # Would need proper database setup
        pass


# ============================================================================
# Utility Tests
# ============================================================================

class TestUtilities:
    """Tests for utility functions."""
    
    def test_sql_statement_building(self):
        """Test SQL statement construction."""
        from delta_engine import build_insert_statement, build_update_statement
        
        record = {"name": "John", "age": 30}
        
        insert_sql = build_insert_statement("person", record)
        assert "INSERT INTO person" in insert_sql
        assert "name" in insert_sql
        assert "age" in insert_sql
        
        update_sql = build_update_statement("person", record, "123")
        assert "UPDATE person" in update_sql
        assert "WHERE row_id" in update_sql


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
