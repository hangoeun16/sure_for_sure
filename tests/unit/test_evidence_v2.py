from pipeline.evidence import FieldEvidence, combine_evidence
from pipeline.models import EvidenceRelation


def test_support_and_contradiction_are_source_conflict() -> None:
    assert (
        combine_evidence(
            [
                FieldEvidence(EvidenceRelation.SUPPORT, "a"),
                FieldEvidence(EvidenceRelation.CONTRADICT, "b"),
            ]
        )
        == EvidenceRelation.SOURCE_CONFLICT
    )


def test_no_record_evidence_is_silent_not_contradiction() -> None:
    assert combine_evidence([]) == EvidenceRelation.SILENT
