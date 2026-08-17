"""
evidence.py — the ONE definition of how record evidence combines into a relation.

Previously this logic lived in both trajectory.TrajectoryState.evidence_relation()
and extract_events.evidence_relation(), and the two had drifted (the scorer treated
an undated field as older; the class did not). Now there is a single function both
import, so they cannot disagree.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class EvidenceItem:
    relation: str          # support | contradict | silent | not_assessable
    assertion: str
    source_type: str       # MedicationRequest | Observation | medication_list | ...
    timestamp: str = ""    # ISO date; "" means undated


def _is_self_report(e: EvidenceItem) -> bool:
    st = (e.source_type or "").lower()
    return "self" in st or "patient" in st


def evidence_relation(evidence) -> str:
    """Combine a list of EvidenceItem (or dicts) into one relation.

    Rule for source_conflict: a supporting source and a contradicting source
    coexist AND the support is newer. If only one side is dated, the UNDATED
    structured field is treated as older (an un-updated list is, by definition,
    behind a dated note). Patient self-report is not counted as a record source.
    """
    items = [_as_item(e) for e in evidence]
    items = [e for e in items if not _is_self_report(e)]

    # Coexisting duplicate entries that CANNOT be adjudicated from the record
    # (e.g. two active statins on the same list, no basis to say which is current).
    # This is a record-internal source_conflict by *coexistence*, not by a
    # support-vs-contradict time difference — so we never invent a date or declare
    # one entry stale. Two or more not_assessable entries = source_conflict.
    not_assessable = [e for e in items if e.relation == "not_assessable"]
    if len(not_assessable) >= 2:
        return "source_conflict"

    sup = [e for e in items if e.relation == "support"]
    con = [e for e in items if e.relation == "contradict"]
    if sup and con:
        sup_dates = [e.timestamp for e in sup if e.timestamp]
        con_dates = [e.timestamp for e in con if e.timestamp]
        newer_support = (sup_dates and (not con_dates or max(sup_dates) > min(con_dates)))
        support_dated_other_not = (sup_dates and not con_dates)
        if newer_support or support_dated_other_not:
            return "source_conflict"
    if con:
        return "contradict"
    if sup:
        return "support"
    return items[0].relation if items else "silent"


def _as_item(e) -> EvidenceItem:
    if isinstance(e, EvidenceItem):
        return e
    # tolerate plain dicts (e.g. from the LLM extractor)
    return EvidenceItem(
        relation=e.get("relation", "silent"),
        assertion=e.get("assertion", ""),
        source_type=e.get("source_type", "record"),
        timestamp=e.get("timestamp") or "",
    )
