"""
Entity Anchor — identity-column detection for QuWARTS.

Two strategies depending on whether the workload provides an identity hint:

  1. detect_identity_column(table_name, schema_columns, llm_client)
     Tournament-style LLM elimination: columns compete in groups of
     TOURNAMENT_GROUP_SIZE.  The LLM picks the best identity column from each
     group; winners advance until one remains.  Works for any schema size and
     any dataset — no hardcoded heuristics.

  2. discover_entity_attribute(table_name, sample_chunks, llm_client)
     Evaporate-inspired fallback: samples raw text chunks, asks the LLM to
     enumerate attribute:value pairs, counts field frequencies, then picks the
     most entity-like attribute.  Used when the workload has no column that
     could serve as an identity (e.g. pure aggregation queries).
"""

import logging
import random
from collections import Counter
from typing import List, Optional

logger = logging.getLogger(__name__)

# Columns per LLM call in each tournament round.  7 is large enough to give
# the model comparative context but small enough for reliable 7B-model output.
TOURNAMENT_GROUP_SIZE = 7


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_response(resp: str, col_lower: dict) -> Optional[str]:
    """
    Try to match an LLM response string back to a canonical column name.
    Handles case, surrounding punctuation, and underscore/space differences.
    """
    resp = resp.strip().strip('"').strip("'").rstrip(".").strip()
    if resp.lower() in col_lower:
        return col_lower[resp.lower()]
    for c_lower, c_orig in col_lower.items():
        if resp.lower().replace(" ", "_") == c_lower:
            return c_orig
    return None


def _format_sample_block(group: List[str], sample_values: Optional[dict]) -> str:
    """
    Build a compact sample-values block for a subset of columns.
    Each column shows up to 3 sample values so the LLM has concrete evidence.
    """
    if not sample_values:
        return ""
    lines = []
    for col in group:
        vals = sample_values.get(col, [])
        if vals:
            preview = [str(v)[:60] for v in vals[:3]]
            lines.append(f"  {col}: {preview}")
    return "\n".join(lines)


def _pick_from_group(
    table_name: str,
    group: List[str],
    llm_client,
    round_num: int = 1,
    sample_values: Optional[dict] = None,
) -> Optional[str]:
    """
    Ask the LLM to pick the single best identity column from a small group.
    When sample_values is provided, up to 3 example values per column are
    shown so the model has concrete evidence rather than just column names.
    Tries two differently-phrased prompts before giving up.

    Returns the winning column name (case-preserving), or None if both
    prompts fail (caller will keep all group members for the next round).
    """
    if len(group) == 1:
        return group[0]

    col_lower = {c.lower(): c for c in group}
    bullet_list = "\n".join(f"  - {c}" for c in group)
    sample_block = _format_sample_block(group, sample_values)

    sample_section = (
        f"\nSample values from the data:\n{sample_block}\n"
        if sample_block else ""
    )

    prompt1 = (
        f"A relational table called '{table_name}' has these candidate columns:\n"
        f"{bullet_list}\n"
        f"{sample_section}\n"
        f"The PRIMARY IDENTIFIER is the column whose value is the NAME or UNIQUE "
        f"LABEL of the real-world entity each row describes — the thing you would "
        f"use to look up or reference a specific record.\n\n"
        f"Rules:\n"
        f"  ✓ Typically contains a proper name or a natural unique label "
        f"(e.g., a person's name, an organisation's name, a product title, "
        f"a patient ID).\n"
        f"  ✗ NOT an address, location, date, financial metric, description, "
        f"code/ticker, or any numeric attribute.\n\n"
        f"Which column from the list is the PRIMARY IDENTIFIER?\n"
        f"Respond with ONLY the exact column name. You must pick one."
    )

    prompt2 = (
        f"Table: '{table_name}'\n"
        f"Columns: {group}\n"
        f"{sample_section}\n"
        f"One column is the anchor identity of every row — it uniquely names "
        f"the entity the row is about.  All other columns are attributes "
        f"(measurements, descriptions, codes, addresses) that only make sense "
        f"once you know WHICH entity you are looking at.\n\n"
        f"Which column is the identity anchor?\n"
        f"Respond with ONLY the exact column name. You must pick one."
    )

    for attempt, prompt in enumerate((prompt1, prompt2), start=1):
        try:
            resp = llm_client.generate(prompt, max_tokens=30, temperature=0.0)
            winner = _normalize_response(resp, col_lower)
            if winner:
                logger.debug(
                    f"[EntityAnchor] Round {round_num}, group {group}: "
                    f"'{winner}' (attempt {attempt})"
                )
                return winner
        except Exception as exc:
            logger.warning(
                f"[EntityAnchor] Round {round_num} group pick failed "
                f"(attempt {attempt}): {exc}"
            )

    logger.debug(
        f"[EntityAnchor] Round {round_num}, group {group}: "
        f"both prompts failed — keeping all members"
    )
    return None



# ---------------------------------------------------------------------------
# Strategy 1 — Tournament identity detection
# ---------------------------------------------------------------------------

def detect_identity_column(
    table_name: str,
    schema_columns: List[str],
    llm_client,
    group_size: int = TOURNAMENT_GROUP_SIZE,
    sample_values: Optional[dict] = None,
) -> Optional[str]:
    """
    Tournament-style identity column detection.

    Algorithm
    ─────────
    Columns compete in groups of `group_size`.  The LLM picks the best
    identity column from each group; winners advance to the next round.
    This repeats until only one column remains — the champion is returned
    as the identity column.

    Why a tournament?
    ─────────────────
    • A single call with 25+ columns overwhelms small (7B) models — they
      either pick randomly or refuse to commit.
    • Binary yes/no per column has no comparative context, causing the model
      to over-veto and return None for everything.
    • Groups of 7-8 give the model enough context to make a meaningful
      comparative judgement while staying within its reliable output range.
    • The bracket structure guarantees a winner for any schema size and any
      dataset — no hardcoded column names, no domain-specific heuristics.

    Failure safety
    ──────────────
    If the LLM fails to pick from a group (both prompts exhausted), ALL
    members of that group survive to the next round with a randomised
    ordering, so the group does not silently vanish from the bracket.
    If ALL calls in a round fail (degenerate case: Ollama is down), the
    first surviving candidate is returned so the pipeline never falls to
    brute-force extraction due to this step alone.

    Returns the exact column name (case-preserving), or None only if the
    input list is empty.

    Parameters
    ──────────
    sample_values : optional dict mapping column name → list of example values.
        When provided, each LLM call shows up to 3 sample values per column so
        the model has concrete evidence rather than just column names.  Callers
        can build this from the first few rows of the source CSV/DataFrame.
    """
    if not schema_columns:
        return None
    if len(schema_columns) == 1:
        logger.info(
            f"[EntityAnchor] Single candidate for '{table_name}': "
            f"'{schema_columns[0]}' (no tournament needed)"
        )
        return schema_columns[0]

    candidates = list(schema_columns)
    # Shuffle so bracket position isn't biased by column declaration order
    random.shuffle(candidates)
    round_num = 1

    while len(candidates) > 1:
        logger.info(
            f"[EntityAnchor] Tournament round {round_num} for '{table_name}': "
            f"{len(candidates)} candidates → groups of ≤{group_size}"
        )

        groups = [
            candidates[i : i + group_size]
            for i in range(0, len(candidates), group_size)
        ]
        winners: List[str] = []

        for group in groups:
            winner = _pick_from_group(
                table_name, group, llm_client, round_num, sample_values=sample_values
            )
            if winner:
                winners.append(winner)
            else:
                # LLM failed for this group — all members survive
                winners.extend(group)

        # Safety: if no elimination happened, avoid an infinite loop
        if len(winners) >= len(candidates):
            logger.warning(
                f"[EntityAnchor] Tournament stalled at round {round_num} for "
                f"'{table_name}' — all group LLM calls failed. "
                f"Returning first surviving candidate."
            )
            break

        candidates = winners
        round_num += 1

    result = candidates[0] if candidates else None
    logger.info(
        f"[EntityAnchor] Tournament champion for '{table_name}': "
        f"'{result}' (decided in {round_num} round(s))"
    )
    return result


# ---------------------------------------------------------------------------
# Strategy 2 — Evaporate-inspired discovery from raw text
# ---------------------------------------------------------------------------

def discover_entity_attribute(
    table_name: str,
    sample_chunks: List[str],
    llm_client,
    n_sample: int = 50,
) -> Optional[str]:
    """
    When the workload schema has no obvious identity column, sample raw text
    chunks and discover the primary entity attribute using an Evaporate-style
    two-phase approach:

      Phase A — extraction: for each chunk, ask the LLM to list all
        attribute:value pairs it can find.  Count field frequency across chunks.

      Phase B — selection: present the top-20 most frequent fields to the LLM
        and ask which one is the primary entity identifier.

    Returns a normalized attribute name string, or None if discovery fails.
    """
    chunks = sample_chunks[:n_sample]
    if not chunks:
        return None

    field_counts: Counter = Counter()

    # Phase A — enumerate fields from each chunk
    for chunk in chunks:
        prompt = (
            f"Read the following text and list every distinct attribute you can "
            f"find, as \"attribute: value\" pairs.\n"
            f"Focus on identifying the main subject and its properties.\n\n"
            f"Text:\n{chunk}\n\n"
            f"List attributes (one per line, format: attribute: value):"
        )
        try:
            response = llm_client.generate(prompt, max_tokens=400, temperature=0.0)
            for line in response.strip().split("\n"):
                line = line.strip().lstrip("-").lstrip("*").strip()
                if ": " not in line:
                    continue
                field = line.split(":")[0].strip().lower()
                # Skip obviously non-entity fields
                if field and len(field) <= 60:
                    field_counts[field] += 1
        except Exception as e:
            logger.warning(f"[EntityAnchor] Chunk sampling failed: {e}")
            continue

    if not field_counts:
        logger.warning(
            f"[EntityAnchor] Phase A found no fields for '{table_name}'."
        )
        return None

    top_fields = [f for f, _ in field_counts.most_common(20)]
    logger.info(
        f"[EntityAnchor] Top fields discovered for '{table_name}': {top_fields[:10]}"
    )

    # Phase B — ask LLM to pick the entity identifier from the candidate list
    prompt = (
        f"These attributes were found in text files about \"{table_name}\":\n"
        f"{top_fields}\n\n"
        f"Which SINGLE attribute is the PRIMARY IDENTIFIER that uniquely names "
        f"the main entity/subject of each record?\n"
        f"Examples of what a primary identifier looks like: "
        f"\"name\", \"player name\", \"company\", \"patient id\", \"title\".\n\n"
        f"Rules:\n"
        f"- Respond with ONLY one attribute from the list above.\n"
        f"- No explanation, no punctuation.\n"
        f"- If none qualify, respond with NULL."
    )

    try:
        response = llm_client.generate(prompt, max_tokens=20, temperature=0.0)
        chosen = response.strip().strip('"').strip("'").lower()

        if chosen == "null":
            logger.warning(
                f"[EntityAnchor] LLM could not pick entity attribute for '{table_name}'."
            )
            return None

        if chosen in field_counts:
            logger.info(
                f"[EntityAnchor] Discovered entity attribute for '{table_name}': '{chosen}'"
            )
            return chosen

        # LLM picked something not in the list — fall back to most common
        fallback = field_counts.most_common(1)[0][0]
        logger.warning(
            f"[EntityAnchor] LLM returned '{chosen}' not in candidate list. "
            f"Falling back to most common field: '{fallback}'"
        )
        return fallback

    except Exception as e:
        raise RuntimeError(
            f"[EntityAnchor] Phase B LLM call failed for '{table_name}': {e}"
        ) from e
