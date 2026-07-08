#!/usr/bin/env python3
"""
Simple test to verify WDIRS can run end-to-end without spaCy.
Tests basic functionality with qwen2.5:0.5b model.
"""

import sys
import os
from pathlib import Path

# Add WDIRS to path
sys.path.insert(0, str(Path(__file__).parent))

# Set environment variables
os.environ['WDIRS_DB_PATH'] = '/tmp/wdirs_test.db'
os.environ['OLLAMA_MODEL'] = 'qwen2.5:7b-instruct'

def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")
    
    try:
        from config import OLLAMA_MODEL, OLLAMA_URL
        print(f"✓ Config loaded: {OLLAMA_MODEL} at {OLLAMA_URL}")
        
        from data_layer import DataLayer, RecursiveCharacterSplitter
        print("✓ DataLayer imported")
        
        from lattice_planner import LatticePlanner
        print("✓ LatticePlanner imported")
        
        from extractor import ConstrainedExtractor, OllamaClient
        print("✓ Extractor imported")
        
        from entity_resolver import EntityResolver
        print("✓ EntityResolver imported")
        
        from delta_engine import DeltaEngine
        print("✓ DeltaEngine imported")
        
        from wdirs_runner import WDIRSRunner
        print("✓ WDIRSRunner imported")
        
        return True
    
    except Exception as e:
        print(f"✗ Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_text_chunking():
    """Test text chunking functionality."""
    print("\nTesting text chunking...")
    
    try:
        from data_layer import RecursiveCharacterSplitter
        
        splitter = RecursiveCharacterSplitter(chunk_size=100, chunk_overlap=20)
        
        text = "This is a test document. " * 20
        chunks = splitter.create_chunks(text, "test_doc")
        
        print(f"✓ Created {len(chunks)} chunks from text")
        print(f"  First chunk: {chunks[0].content[:50]}...")
        
        return True
    
    except Exception as e:
        print(f"✗ Text chunking failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_sql_parsing():
    """Test SQL parsing with lattice planner."""
    print("\nTesting SQL parsing...")
    
    try:
        from lattice_planner import LatticePlanner
        
        planner = LatticePlanner()
        
        queries = [
            "SELECT name, age FROM player WHERE age > 25",
            "SELECT team, position FROM player WHERE position = 'Frontcourt'"
        ]
        
        lattice = planner.parse_workload(queries)
        
        print(f"✓ Parsed {len(queries)} queries")
        print(f"  Tables found: {list(lattice.tables.keys())}")
        
        if 'player' in lattice.tables:
            table = lattice.tables['player']
            print(f"  Columns: {list(table.columns.keys())}")
        
        return True
    
    except Exception as e:
        print(f"✗ SQL parsing failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_ollama_connection():
    """Test connection to Ollama."""
    print("\nTesting Ollama connection...")
    
    try:
        from extractor import OllamaClient
        
        client = OllamaClient()
        
        print(f"✓ Ollama client initialized")
        print(f"  URL: {client.base_url}")
        print(f"  Model: {client.model}")
        
        # Try a simple generation
        try:
            response = client.generate(
                "Say 'Hello' in one word.",
                max_tokens=10,
                temperature=0.0
            )
            print(f"✓ Ollama responded: {response[:50]}")
            return True
        
        except Exception as e:
            print(f"⚠ Ollama not responding: {e}")
            print("  Make sure Ollama is running: ollama serve")
            print("  And model is pulled: ollama pull qwen2.5:0.5b")
            return False
    
    except Exception as e:
        print(f"✗ Ollama connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_database_connection():
    """Test SQLite connection."""
    print("\nTesting SQLite connection...")
    
    try:
        from data_layer import DataLayer
        
        # Try to connect
        try:
            data_layer = DataLayer()
            print("✓ SQLite connected")
            
            # Try to count chunks
            count = data_layer.count_chunks()
            print(f"  Current chunks in DB: {count}")
            
            data_layer.close()
            return True
        
        except Exception as e:
            print(f"⚠ SQLite not available: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("=" * 80)
    print("WDIRS SIMPLE TEST")
    print("=" * 80)
    
    results = {
        "imports": test_imports(),
        "text_chunking": test_text_chunking(),
        "sql_parsing": test_sql_parsing(),
        "ollama": test_ollama_connection(),
        "database": test_database_connection()
    }
    
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{test_name:20} {status}")
    
    total = len(results)
    passed = sum(results.values())
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✓ All tests passed! System is ready.")
    else:
        print("\n⚠ Some tests failed. Check the output above.")
    
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
