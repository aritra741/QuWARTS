"""
Test: what spaCy NER labels are produced for Finance and Healthcare text,
and what semantic types the heuristic assigns to relevant column names.

Run from :
    python3 test_ner_labels.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# ── 1. Check what spaCy's en_core_web_sm labels look like on real text ────────

print("=" * 70)
print("PART 1: spaCy NER labels on Finance and Healthcare text")
print("=" * 70)

try:
    import spacy
    nlp = spacy.load("en_core_web_sm")
    print(f"Loaded: en_core_web_sm\n")
    print(f"All available NER labels in this model:\n  {nlp.get_pipe('ner').labels}\n")
except Exception as e:
    print(f"Could not load en_core_web_sm: {e}")
    nlp = None

FINANCE_SAMPLE = """
Beazley plc is a specialist insurance group with operations in Europe, the US,
Canada, Latin America, and Asia. Beazley manages six Lloyd's syndicates and,
in 2012, underwrote gross premiums worldwide of $1,595.7m. All Lloyd's syndicates
are carefully supervised by the Society of Lloyd's, which operates the Lloyd's
market in the City of London.
"""

HEALTHCARE_SAMPLE = """
Imatinib (brand name Gleevec) is a tyrosine kinase inhibitor used as first-line
treatment for chronic myelogenous leukemia (CML) and gastrointestinal stromal
tumors (GIST). COVID-19, caused by SARS-CoV-2, is an infectious disease.
Patients with type 2 diabetes mellitus benefit from metformin therapy.
The trial was conducted at Massachusetts General Hospital and Johns Hopkins.
"""

LEGAL_SAMPLE = """
Apple Inc. filed a complaint against Samsung Electronics Co. Ltd. in the
United States District Court for the Northern District of California.
The plaintiff, represented by attorney John B. Quinn, argued that Samsung
infringed patents EP2059868B1 and US8074172.
"""

if nlp:
    for label, text in [
        ("Finance", FINANCE_SAMPLE),
        ("Healthcare", HEALTHCARE_SAMPLE),
        ("Legal", LEGAL_SAMPLE),
    ]:
        doc = nlp(text)
        print(f"--- {label} ---")
        if not doc.ents:
            print("  (no entities found)")
        for ent in doc.ents:
            print(f"  [{ent.label_:10s}]  {ent.text!r}")
        print()

# ── 2. Show what the heuristic assigns to relevant column names ───────────────

print("=" * 70)
print("PART 2: _heuristic_semantic_type on realistic column names")
print("=" * 70)

def _heuristic_semantic_type(column_name: str) -> str:
    col_lower = column_name.lower()
    if any(k in col_lower for k in ['name', 'patient', 'doctor', 'physician', 'person', 'author']):
        return "PERSON"
    if any(k in col_lower for k in ['company', 'organization', 'org', 'institution', 'hospital']):
        return "ORG"
    if any(k in col_lower for k in ['date', 'time', 'year', 'month', 'day', 'timestamp']):
        return "DATE"
    if any(k in col_lower for k in ['city', 'state', 'country', 'location', 'address', 'place']):
        return "GPE"
    if any(k in col_lower for k in ['code', 'id', 'identifier', 'number', 'icd']):
        return "CODE"
    if any(k in col_lower for k in ['price', 'cost', 'amount', 'salary', 'revenue', 'payment']):
        return "MONEY"
    if any(k in col_lower for k in ['count', 'quantity', 'total', 'sum', 'average']):
        return "QUANTITY"
    return "OTHER"

test_columns = [
    # Finance
    ("company_name",         "finance",    "should be ORG, heuristic sees 'name' → PERSON"),
    ("registered_office",    "finance",    "should be GPE"),
    ("earnings_per_share",   "finance",    "should be MONEY"),
    ("revenue",              "finance",    "should be MONEY"),
    ("incorporation_date",   "finance",    "should be DATE"),
    # Healthcare
    ("disease_name",         "disease",    "should be OTHER/custom — not in spaCy vocab"),
    ("drug_name",            "drug",       "should be OTHER/custom — not in spaCy vocab"),
    ("institution_name",     "institution","should be ORG, heuristic sees 'name' → PERSON"),
    ("patient_name",         "disease",    "should be PERSON — correct"),
    # Legal
    ("case_name",            "legal",      "should be OTHER — 'name' → PERSON (wrong)"),
    ("plaintiff",            "legal",      "should be PERSON — maps to OTHER"),
    ("defendant",            "legal",      "should be PERSON — maps to OTHER"),
]

print(f"{'Column':<30} {'Table':<15} {'Heuristic':<10}  Note")
print("-" * 80)
for col, table, note in test_columns:
    sem = _heuristic_semantic_type(col)
    print(f"{col:<30} {table:<15} {sem:<10}  {note}")

# ── 3. What spaCy label would these get, even if sem_type were right? ─────────

print()
print("=" * 70)
print("PART 3: Does spaCy NER actually tag diseases and drugs?")
print("=" * 70)
print("(Standard en_core_web_sm/md/lg/trf NER labels are for news-domain text.")
print(" DISEASE, DRUG, CHEMICAL are NOT in the label set.)\n")

DISEASE_CHUNK = "COVID-19 is caused by SARS-CoV-2. Type 2 diabetes and hypertension " \
                "are common comorbidities. Metformin and lisinopril are first-line treatments."

if nlp:
    doc = nlp(DISEASE_CHUNK)
    print(f"Text: {DISEASE_CHUNK!r}\n")
    print("spaCy entities found:")
    if not doc.ents:
        print("  NONE — spaCy sees no named entities here.")
    for ent in doc.ents:
        print(f"  [{ent.label_:10s}]  {ent.text!r}")

print()
print("=" * 70)
print("SUMMARY OF PROBLEMS")
print("=" * 70)
print("""
1. HEURISTIC BUG — 'company_name' has 'name' → PERSON (not ORG).
   The 'name' keyword is checked before 'company', so company_name,
   institution_name, disease_name, drug_name all become PERSON.

2. SPACY BLIND SPOT — spaCy en_core_web_* has NO labels for:
   - DISEASE  (COVID-19, diabetes, CML)
   - DRUG     (imatinib, metformin, Gleevec)
   - CHEMICAL (SARS-CoV-2, HbA1c)
   These are classified as NORP, ORG, or simply not tagged at all.

3. MISSING SEMANTIC TYPES — 'disease', 'drug', 'plaintiff', 'defendant'
   all fall through to OTHER, and then get no NER label → Pass 1 would
   use the no-label path (accept all entity types) which is very noisy.

FIX NEEDED:
   a) Fix _heuristic_semantic_type: check 'company' before 'name'.
   b) Add DISEASE and DRUG as new semantic types.
   c) For DISEASE/DRUG, use a different extraction strategy in Pass 1
      (e.g. scispacy for biomedical, or keyword matching from the
      workload's normalization hints, or a regex on common drug suffixes).
""")
