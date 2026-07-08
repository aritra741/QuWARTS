"""
QuWARTS - Query Workload Aware Relational Table Synthesis from Unstructured Text
=========================================================

A complete implementation of workload-driven incremental relational synthesis
that transforms unstructured text into queryable relational databases by
leveraging SQL workloads to optimize extraction costs.

Core Modules:
- config.py: System configuration and constants
- data_layer.py: PostgreSQL schema, metadata registry, provenance tracking
- lattice_planner.py: Workload analysis and MQO optimization
- sieve_synthesizer.py: Programmatic filtering with spaCy/FlashText
- extractor.py: LLM-based constrained extraction
- entity_resolver.py: Proactive entity resolution with embeddings
- delta_engine.py: Runtime incremental query execution
- quwarts_runner.py: Main system orchestrator

Version: 1.0.0
"""

__version__ = "1.0.0"
__author__ = "QuWARTS Development Team"
