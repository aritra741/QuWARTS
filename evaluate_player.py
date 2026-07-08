#!/usr/bin/env python3
"""
Evaluate QuWARTS on Player dataset with F1 score calculation.

Process:
1. Load ground truth from CSV files (Data/Player/)
2. Use 80% of filter queries for preprocessing (guide extraction)
3. Test on 100% of filter queries
4. Calculate F1 score by comparing with ground truth
"""

import sys
import os
import time
import csv
import random
import json
import sqlite3
from pathlib import Path
from collections import defaultdict
from difflib import SequenceMatcher
from typing import List, Dict, Set, Tuple, Optional

# Add QuWARTS to path
sys.path.insert(0, str(Path(__file__).parent))

# Set environment variables before importing QuWARTS
os.environ['QUWARTS_DB_PATH'] = str(Path(__file__).parent / '.databases' / 'quwarts_player_test.db')
os.environ['OLLAMA_MODEL'] = 'qwen2.5:7b-instruct'

from quwarts_runner import QuWARTSRunner, PreprocessingResult, QueryResult
from lattice_planner import LatticePlanner


# ============================================================================
# Configuration
# ============================================================================

PROJECT_ROOT = Path(__file__).parent.parent.parent
GROUND_TRUTH_DIR = PROJECT_ROOT / "Data" / "Player"
SOURCE_DATA_DIR = PROJECT_ROOT / "source_data" / "SyntheticPlayer"
QUERY_DIR = PROJECT_ROOT / "Query" / "Player" / "Filter"
RESULTS_DIR = PROJECT_ROOT / "results" / "quwarts_player_evaluation"

# Create results directory
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Fuzzy matching threshold
FUZZY_THRESHOLD = 0.85


# ============================================================================
# Timing Tracker
# ============================================================================

class TimingTracker:
    """Track timing for different operations."""
    
    def __init__(self):
        self.timings = defaultdict(list)
        self.start_times = {}
    
    def start(self, operation):
        self.start_times[operation] = time.time()
    
    def end(self, operation):
        if operation in self.start_times:
            elapsed = time.time() - self.start_times[operation]
            self.timings[operation].append(elapsed)
            del self.start_times[operation]
            return elapsed
        return 0
    
    def print_report(self):
        print(f"\n{'=' * 80}")
        print("TIMING REPORT")
        print(f"{'=' * 80}")
        
        total = sum(sum(times) for times in self.timings.values())
        print(f"\nTotal Time: {total:.2f}s ({total/60:.1f} min)\n")
        
        sorted_ops = sorted(self.timings.items(), key=lambda x: sum(x[1]), reverse=True)
        
        for op, times in sorted_ops:
            total_time = sum(times)
            pct = (total_time / total * 100) if total > 0 else 0
            print(f"{op:<40} {total_time:>9.2f}s ({pct:>5.1f}%)")


# ============================================================================
# Ground Truth Loading
# ============================================================================

def load_ground_truth() -> Dict[str, List[Dict]]:
    """Load ground truth data from CSV files."""
    print("\n" + "=" * 80)
    print("LOADING GROUND TRUTH")
    print("=" * 80)
    
    ground_truth = {}
    
    for csv_file in GROUND_TRUTH_DIR.glob("*.csv"):
        table_name = csv_file.stem
        
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            ground_truth[table_name] = rows
            print(f"Loaded {len(rows)} rows from {table_name}")
    
    return ground_truth


# ============================================================================
# Query Loading
# ============================================================================

def load_queries_from_file(file_path: Path) -> List[Tuple[int, str]]:
    """Load queries from SQL file."""
    queries = []
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Split by comments that start with "-- Query"
    lines = content.split('\n')
    current_query = None
    query_num = 0
    
    for line in lines:
        line = line.strip()
        
        if line.startswith('-- Query'):
            # Extract query number
            parts = line.split(':')
            if len(parts) >= 2:
                query_num = int(parts[0].replace('-- Query', '').strip())
        elif line and not line.startswith('--'):
            # This is the actual query
            if current_query is None:
                current_query = line
            else:
                current_query += ' ' + line
            
            # If query ends with semicolon, save it
            if line.endswith(';'):
                queries.append((query_num, current_query.rstrip(';')))
                current_query = None
    
    return queries


def load_all_filter_queries() -> Dict[str, List[Tuple[int, str]]]:
    """Load all filter queries from all SQL files."""
    print("\n" + "=" * 80)
    print("LOADING FILTER QUERIES")
    print("=" * 80)
    
    all_queries = {}
    
    for sql_file in QUERY_DIR.glob("*.sql"):
        table_name = sql_file.stem.replace('filter_queries_', '')
        queries = load_queries_from_file(sql_file)
        all_queries[table_name] = queries
        print(f"Loaded {len(queries)} queries for {table_name}")
    
    return all_queries


# ============================================================================
# Value Normalization and Matching
# ============================================================================

def normalize_value(val) -> str:
    """Normalize a value for comparison."""
    if val is None:
        return ""
    return str(val).strip().lower()


def fuzzy_match(val1, val2, threshold: float = FUZZY_THRESHOLD) -> bool:
    """Check if two values match using fuzzy string matching."""
    v1 = normalize_value(val1)
    v2 = normalize_value(val2)
    
    if v1 == v2:
        return True
    
    # Use SequenceMatcher for fuzzy comparison
    ratio = SequenceMatcher(None, v1, v2).ratio()
    return ratio >= threshold


def row_to_tuple(row: Dict, columns: List[str]) -> Tuple:
    """Convert a row dict to a normalized tuple for comparison."""
    return tuple(normalize_value(row.get(col, "")) for col in columns)


def find_matching_rows(
    gt_rows: List[Dict],
    quwarts_rows: List[Dict],
    columns: List[str],
    use_fuzzy: bool = True
) -> Tuple[int, int, int]:
    """
    Find matching rows between ground truth and QuWARTS results.
    
    Returns:
        (true_positives, false_positives, false_negatives)
    """
    # Convert to sets of tuples for exact matching
    gt_tuples = {row_to_tuple(row, columns) for row in gt_rows}
    quwarts_tuples = {row_to_tuple(row, columns) for row in quwarts_rows}
    
    # Exact matches
    exact_matches = gt_tuples & quwarts_tuples
    true_positives = len(exact_matches)
    
    # Remaining unmatched rows
    unmatched_gt = [row for row in gt_rows if row_to_tuple(row, columns) not in exact_matches]
    unmatched_quwarts = [row for row in quwarts_rows if row_to_tuple(row, columns) not in exact_matches]
    
    # Try fuzzy matching on unmatched rows
    if use_fuzzy and unmatched_gt and unmatched_quwarts:
        matched_quwarts_indices = set()
        
        for gt_row in unmatched_gt:
            for i, quwarts_row in enumerate(unmatched_quwarts):
                if i in matched_quwarts_indices:
                    continue
                
                # Check if all columns match fuzzily
                all_match = True
                for col in columns:
                    if not fuzzy_match(gt_row.get(col, ""), quwarts_row.get(col, "")):
                        all_match = False
                        break
                
                if all_match:
                    true_positives += 1
                    matched_quwarts_indices.add(i)
                    break
        
        # Update unmatched counts
        unmatched_quwarts = [row for i, row in enumerate(unmatched_quwarts) 
                          if i not in matched_quwarts_indices]
    
    false_positives = len(unmatched_quwarts)
    false_negatives = len(unmatched_gt)
    
    return true_positives, false_positives, false_negatives


def calculate_f1(tp: int, fp: int, fn: int) -> Tuple[float, float, float]:
    """Calculate precision, recall, and F1 score."""
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    return precision, recall, f1


# ============================================================================
# Query Execution
# ============================================================================

def execute_query_on_ground_truth(query: str, ground_truth: Dict[str, List[Dict]]) -> List[Dict]:
    """Execute query on ground truth data using SQLite."""
    # Create in-memory SQLite database
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()
    
    # Create tables and insert data
    for table_name, rows in ground_truth.items():
        if not rows:
            continue
        
        # Get columns from first row
        columns = list(rows[0].keys())
        
        # Create table
        col_defs = ', '.join([f'"{col}" TEXT' for col in columns])
        cursor.execute(f'CREATE TABLE {table_name} ({col_defs})')
        
        # Insert data
        for row in rows:
            values = [row.get(col, '') for col in columns]
            placeholders = ', '.join(['?' for _ in columns])
            cursor.execute(f'INSERT INTO {table_name} VALUES ({placeholders})', values)
    
    # Execute query
    try:
        cursor.execute(query)
        results = cursor.fetchall()
        
        # Get column names
        columns = [desc[0] for desc in cursor.description]
        
        # Convert to list of dicts
        result_dicts = [dict(zip(columns, row)) for row in results]
        
        conn.close()
        return result_dicts
    
    except Exception as e:
        print(f"Error executing query on ground truth: {e}")
        conn.close()
        return []


# ============================================================================
# Main Evaluation
# ============================================================================

def main():
    """Main evaluation function."""
    print("\n" + "=" * 80)
    print("QuWARTS PLAYER DATASET EVALUATION")
    print("=" * 80)
    
    # Initialize timing tracker
    timer = TimingTracker()
    
    # Load ground truth
    timer.start("load_ground_truth")
    ground_truth = load_ground_truth()
    timer.end("load_ground_truth")
    
    # Load queries
    timer.start("load_queries")
    all_queries = load_all_filter_queries()
    timer.end("load_queries")
    
    # Flatten all queries for preprocessing
    all_query_list = []
    for table_name, queries in all_queries.items():
        all_query_list.extend([(table_name, qnum, query) for qnum, query in queries])
    
    # Select 80% for preprocessing
    random.seed(42)  # For reproducibility
    num_train = int(len(all_query_list) * 0.8)
    train_queries = random.sample(all_query_list, num_train)
    
    print(f"\nTotal queries: {len(all_query_list)}")
    print(f"Training queries (80%): {len(train_queries)}")
    print(f"Testing on 100% of queries: {len(all_query_list)}")
    
    # Create training queries list (just the query strings, not tuples)
    training_query_strings = [query for table_name, qnum, query in train_queries]
    
    # Initialize QuWARTS
    print("\n" + "=" * 80)
    print("INITIALIZING QuWARTS")
    print("=" * 80)
    
    timer.start("init_quwarts")
    try:
        runner = QuWARTSRunner("Player")
        timer.end("init_quwarts")
    except Exception as e:
        print(f"Error initializing QuWARTS: {e}")
        print("\nNote: QuWARTS requires PostgreSQL. Make sure:")
        print("1. PostgreSQL is installed and running")
        print("2. Database 'quwarts_player_test' exists")
        print("3. Ollama is running with qwen2.5:7b-instruct")
        return
    
    # Preprocessing
    print("\n" + "=" * 80)
    print("PHASE 1: PREPROCESSING")
    print("=" * 80)
    
    timer.start("preprocessing")
    try:
        preprocess_result = runner.preprocess(workload_queries=training_query_strings)
        timer.end("preprocessing")
        
        if not preprocess_result.success:
            print(f"\n{'='*80}")
            print(f"PREPROCESSING FAILED!")
            print(f"{'='*80}")
            print(f"Error: {preprocess_result.error}")
            
            # Show log file location
            log_file = Path(__file__).parent / "quwarts.log"
            if log_file.exists():
                print(f"\nCheck log file for details: {log_file}")
                print("\nLast 50 lines of log:")
                print("-" * 80)
                with open(log_file, 'r') as f:
                    lines = f.readlines()
                    for line in lines[-50:]:
                        print(line.rstrip())
            return
        
        print(f"\n{'='*80}")
        print(f"PREPROCESSING COMPLETE!")
        print(f"{'='*80}")
        print(f"Tables processed: {preprocess_result.tables_processed}")
        print(f"Total chunks: {preprocess_result.total_chunks}")
        print(f"Total records: {preprocess_result.total_records}")
        print(f"Time: {preprocess_result.preprocessing_time:.2f}s")
        
        # Verify we extracted data
        if preprocess_result.total_records == 0:
            print(f"\n{'='*80}")
            print(f"WARNING: No records extracted!")
            print(f"{'='*80}")
            print("This will result in F1 score of 0. Check:")
            print("1. Are the source text files in the correct location?")
            print("2. Does the text contain relevant data?")
            print("3. Check the log file for extraction errors")
    
    except Exception as e:
        print(f"\n{'='*80}")
        print(f"PREPROCESSING ERROR!")
        print(f"{'='*80}")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        
        # Show log file
        log_file = Path(__file__).parent / "quwarts.log"
        if log_file.exists():
            print(f"\nCheck log file: {log_file}")
        return
    
    # Query Execution and Evaluation
    print("\n" + "=" * 80)
    print("PHASE 2: QUERY EXECUTION AND EVALUATION")
    print("=" * 80)
    
    results = []
    total_tp = 0
    total_fp = 0
    total_fn = 0
    
    for table_name, qnum, query in all_query_list:
        print(f"\n--- Query {qnum} ({table_name}) ---")
        print(f"SQL: {query[:100]}...")
        
        # Execute on ground truth
        timer.start("gt_execution")
        gt_results = execute_query_on_ground_truth(query, ground_truth)
        timer.end("gt_execution")
        
        print(f"Ground truth: {len(gt_results)} rows")
        
        # Execute with QuWARTS
        timer.start("quwarts_execution")
        try:
            quwarts_result = runner.execute_query(query)
            timer.end("quwarts_execution")
            
            if not quwarts_result.success:
                print(f"QuWARTS execution failed: {quwarts_result.error}")
                quwarts_results = []
            else:
                quwarts_results = quwarts_result.results
                print(f"QuWARTS: {len(quwarts_results)} rows")
                print(f"Delta type: {quwarts_result.delta_type}")
        
        except Exception as e:
            print(f"QuWARTS error: {e}")
            quwarts_results = []
            timer.end("quwarts_execution")
        
        # Calculate metrics
        if gt_results:
            columns = list(gt_results[0].keys())
            tp, fp, fn = find_matching_rows(gt_results, quwarts_results, columns)
            
            precision, recall, f1 = calculate_f1(tp, fp, fn)
            
            print(f"TP: {tp}, FP: {fp}, FN: {fn}")
            print(f"Precision: {precision:.3f}, Recall: {recall:.3f}, F1: {f1:.3f}")
            
            total_tp += tp
            total_fp += fp
            total_fn += fn
            
            results.append({
                'query_num': qnum,
                'table': table_name,
                'query': query,
                'gt_rows': len(gt_results),
                'quwarts_rows': len(quwarts_results),
                'tp': tp,
                'fp': fp,
                'fn': fn,
                'precision': precision,
                'recall': recall,
                'f1': f1
            })
    
    # Overall metrics
    print("\n" + "=" * 80)
    print("OVERALL RESULTS")
    print("=" * 80)
    
    overall_precision, overall_recall, overall_f1 = calculate_f1(total_tp, total_fp, total_fn)
    
    print(f"\nTotal TP: {total_tp}")
    print(f"Total FP: {total_fp}")
    print(f"Total FN: {total_fn}")
    print(f"\nOverall Precision: {overall_precision:.3f}")
    print(f"Overall Recall: {overall_recall:.3f}")
    print(f"Overall F1 Score: {overall_f1:.3f}")
    
    # Average per-query metrics
    if results:
        avg_precision = sum(r['precision'] for r in results) / len(results)
        avg_recall = sum(r['recall'] for r in results) / len(results)
        avg_f1 = sum(r['f1'] for r in results) / len(results)
        
        print(f"\nAverage per-query Precision: {avg_precision:.3f}")
        print(f"Average per-query Recall: {avg_recall:.3f}")
        print(f"Average per-query F1 Score: {avg_f1:.3f}")
    
    # Save results
    results_file = RESULTS_DIR / "evaluation_results.json"
    with open(results_file, 'w') as f:
        json.dump({
            'overall': {
                'tp': total_tp,
                'fp': total_fp,
                'fn': total_fn,
                'precision': overall_precision,
                'recall': overall_recall,
                'f1': overall_f1
            },
            'per_query': results
        }, f, indent=2)
    
    print(f"\nResults saved to: {results_file}")
    
    # Print timing report
    timer.print_report()
    
    # Cleanup
    runner.close()
    
    # Show any errors from log file
    log_file = Path(__file__).parent / "quwarts.log"
    if log_file.exists():
        print("\n" + "=" * 80)
        print("CHECKING FOR ERRORS IN LOG")
        print("=" * 80)
        
        with open(log_file, 'r') as f:
            log_content = f.read()
        
        # Search for errors
        error_lines = []
        for line in log_content.split('\n'):
            if any(keyword in line.lower() for keyword in ['error', 'exception', 'traceback', 'failed']):
                if 'warning' not in line.lower():  # Exclude warnings for now
                    error_lines.append(line)
        
        if error_lines:
            print(f"\nFound {len(error_lines)} error/exception lines:")
            print("-" * 80)
            for line in error_lines[-20:]:  # Show last 20
                print(line)
        else:
            print("\n✓ No errors found in log file")
    
    print("\n" + "=" * 80)
    print("EVALUATION COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
