#!/usr/bin/env python3
"""Quick test to verify lattice planner extracts columns."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from lattice_planner import LatticePlanner

# Test queries from the Player dataset
test_queries = [
    "SELECT state_name, area, city_name FROM city WHERE area = 375.78",
    "SELECT name, age FROM player WHERE age > 25",
    "SELECT team, position FROM player WHERE position = 'Frontcourt'"
]

planner = LatticePlanner()
lattice = planner.parse_workload(test_queries)

print(f"\n✓ Parsed {len(test_queries)} queries")
print(f"  Tables found: {list(lattice.tables.keys())}")

for table_name, table_info in lattice.tables.items():
    print(f"\n  Table: {table_name}")
    print(f"    Columns: {list(table_info.columns.keys())}")
    print(f"    Predicates: {table_info.predicates}")

total_columns = sum(len(t.columns) for t in lattice.tables.values())
print(f"\n✓ Total columns extracted: {total_columns}")

if total_columns > 0:
    print("✓ SUCCESS: Columns are being extracted!")
else:
    print("✗ FAIL: No columns extracted")
    sys.exit(1)
