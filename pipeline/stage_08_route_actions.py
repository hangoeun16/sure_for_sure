"""Stage 08: route remaining uncertainty without inventing another priority score."""

from __future__ import annotations

from pipeline.models import ActionItem, ActionRoute, ConfidenceLevel, EvidenceRelation
from pipeline.state import PipelineState


def run(state: PipelineState) -> PipelineState:
    actions = []
    resolving_claim_ids = {
        result.resolving_claim_id
        for result in state.resolutions.values()
        if result.resolved and result.resolving_claim_id is not None
    }
    for claim in state.claims:
        divergence = state.divergences[claim.claim_id]
        resolution = state.resolutions[claim.claim_id]
        ced = state.ced_results[claim.claim_id]
        is_resolving_claim = claim.claim_id in resolving_claim_ids
        if resolution.resolved:
            route = (
                ActionRoute.CHART_CLEANUP
                if resolution.chart_conflict_remaining
                else ActionRoute.NO_ACTION
            )
        elif (
            is_resolving_claim
            and divergence.relation == EvidenceRelation.SOURCE_CONFLICT
        ):
            route = ActionRoute.NO_ACTION
        elif claim.adherence_gap:
            route = ActionRoute.PATIENT_CLARIFICATION
        elif divergence.relation == EvidenceRelation.SUPPORT:
            route = ActionRoute.NO_ACTION
        elif divergence.relation == EvidenceRelation.NOT_ASSESSABLE:
            route = ActionRoute.CLINICIAN_REVIEW
        elif (
            divergence.relation == EvidenceRelation.SOURCE_CONFLICT
            and claim.confidence.level == ConfidenceLevel.EMPHATIC
            and divergence.supporting_evidence_ids
        ):
            route = ActionRoute.CHART_CLEANUP
        elif divergence.relation in {
            EvidenceRelation.CONTRADICT,
            EvidenceRelation.SOURCE_CONFLICT,
            EvidenceRelation.SILENT,
        }:
            route = ActionRoute.PATIENT_CLARIFICATION
        else:
            route = ActionRoute.CLINICIAN_REVIEW
        actions.append(
            ActionItem(
                claim_id=claim.claim_id,
                route=route,
                ced_score=ced.ced_score,
                rank=None,
                recommended_action=_recommendation(route, claim.medication_name),
                routing_rationale=_routing_rationale(
                    route,
                    divergence.relation,
                    resolution.resolved,
                    claim.adherence_gap,
                    is_resolving_claim,
                ),
                claim=claim,
                divergence=divergence,
                resolution=resolution,
            )
        )
    state.actions = actions
    return state


def _recommendation(route: ActionRoute, medication: str) -> str:
    if route == ActionRoute.PATIENT_CLARIFICATION:
        return f"Clarify the current {medication} regimen or adherence concern with the patient."
    if route == ActionRoute.CHART_CLEANUP:
        return f"Reconcile stale or conflicting {medication} entries in the record."
    if route == ActionRoute.CLINICIAN_REVIEW:
        return f"Review the unscorable {medication} claim and evidence before changing the chart."
    return f"No additional action is indicated for the {medication} claim."


def _routing_rationale(
    route: ActionRoute,
    relation: EvidenceRelation,
    resolved: bool,
    adherence_gap: bool,
    is_resolving_claim: bool,
) -> str:
    if resolved:
        return (
            "A later patient statement established every disputed field; "
            "the route reflects whether a chart conflict remains."
        )
    if adherence_gap:
        return "The patient described an adherence gap that needs clarification."
    if is_resolving_claim and relation == EvidenceRelation.SOURCE_CONFLICT:
        return (
            "This later claim resolves an earlier patient discrepancy; the linked "
            "earlier action already owns the remaining chart cleanup."
        )
    if relation == EvidenceRelation.SUPPORT:
        return "All patient-asserted comparable fields are supported by the record."
    if relation == EvidenceRelation.SILENT:
        return "At least one patient-asserted field is not verifiable in the record."
    if relation == EvidenceRelation.CONTRADICT:
        return "The record directly contradicts at least one patient-asserted field."
    if relation == EvidenceRelation.SOURCE_CONFLICT:
        return "Same-patient record sources disagree on at least one material field."
    return "The claim cannot be scored defensibly and requires clinician review."
