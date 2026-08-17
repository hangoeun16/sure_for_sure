"""Stage 02: extract patient claims and validate exact transcript provenance."""

from __future__ import annotations

import hashlib
import re

from pipeline.ced import CONFIDENCE_SCORE
from pipeline.confidence import (
    cue_rationale,
    derive_confidence_level,
    lexical_cue_matches_type,
)
from pipeline.models import (
    ClaimConfidence,
    ConfidenceCue,
    ConfidenceCueType,
    ConfidenceCueValidationWarning,
    ConfidenceCueWarningCode,
    PatientClaim,
    ProviderConfidenceCue,
    Speaker,
    TranscriptSpan,
)
from pipeline.normalization import (
    normalize_dose_unit,
    normalize_frequency,
    normalize_medication_name,
    normalize_route,
    normalize_status,
)
from pipeline.providers.base import (
    ClaimExtractionProvider,
    ProviderOutputError,
    ProviderSourceGroundingError,
)
from pipeline.stage_01_parse_dialogue import exact_span
from pipeline.state import PipelineState


def run(state: PipelineState, provider: ClaimExtractionProvider) -> PipelineState:
    result = provider.extract_claims(transcript=state.encounter.transcript, turns=state.turns)
    claims: list[PatientClaim] = []
    for ordinal, output in enumerate(result.claims):
        try:
            spans = [
                exact_span(state, turn_index=item.turn_index, quote=item.quote)
                for item in output.supporting_quotes
            ]
            if not any(state.turns[span.turn_index].speaker == Speaker.PATIENT for span in spans):
                raise ValueError("claim has no patient-grounded supporting quote")
            confidence_cues, confidence_warnings = _ground_confidence_cues(
                state,
                output.confidence_cues,
                spans,
            )
            confidence_cues.extend(_detect_hesitations(state, spans))
            confidence_cues = _deduplicate_cues(confidence_cues)
            adherence_span = None
            if output.adherence_quote:
                adherence_span = exact_span(
                    state,
                    turn_index=output.adherence_quote.turn_index,
                    quote=output.adherence_quote.quote,
                )
            negation_span = None
            if output.negation_quote:
                negation_span = exact_span(
                    state,
                    turn_index=output.negation_quote.turn_index,
                    quote=output.negation_quote.quote,
                )
            if output.negated and negation_span is None:
                raise ValueError("negated claim has no exact negation quote")
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderSourceGroundingError(
                f"Provider evidence failed exact-span validation: {exc}"
            ) from exc
        name = normalize_medication_name(output.medication_name)
        if not name:
            raise ProviderOutputError("Medication name normalized to an empty value.")
        material = f"{ordinal}|{name}|" + "|".join(f"{s.start_char}:{s.end_char}" for s in spans)
        claim_id = f"claim-{hashlib.sha256(material.encode()).hexdigest()[:16]}"
        confidence_level = derive_confidence_level(cue.type for cue in confidence_cues)
        claims.append(
            PatientClaim(
                claim_id=claim_id,
                medication_name=name,
                status=normalize_status(output.status),
                dose_value=output.dose_value,
                dose_unit=normalize_dose_unit(output.dose_unit),
                frequency=normalize_frequency(output.frequency),
                route=normalize_route(output.route),
                negated=output.negated,
                negation_span=negation_span,
                adherence_gap=output.adherence_gap,
                adherence_span=adherence_span,
                supporting_spans=spans,
                confidence=ClaimConfidence(
                    level=confidence_level,
                    score=CONFIDENCE_SCORE[confidence_level],
                    cues=confidence_cues,
                    validation_warnings=confidence_warnings,
                    rationale=cue_rationale(cue.type for cue in confidence_cues),
                ),
                first_turn=min(span.turn_index for span in spans),
                last_turn=max(span.turn_index for span in spans),
                extractor=result.metadata,
            )
        )
    state.claims = claims
    return state


def _ground_confidence_cues(
    state: PipelineState,
    provider_cues: list[ProviderConfidenceCue],
    supporting_spans: list[TranscriptSpan],
) -> tuple[list[ConfidenceCue], list[ConfidenceCueValidationWarning]]:
    grounded = []
    warnings = []
    patient_spans = [
        span
        for span in supporting_spans
        if state.turns[span.turn_index].speaker == Speaker.PATIENT
    ]
    for cue in provider_cues:
        if not lexical_cue_matches_type(cue.type, cue.quote):
            warnings.append(
                _cue_warning(
                    cue,
                    ConfidenceCueWarningCode.TYPE_MISMATCH,
                    f"Rejected {cue.type.value} cue because its quote does not match "
                    "the supported lexical criteria.",
                )
            )
            continue
        cue_span = _find_within_supporting_spans(cue, patient_spans)
        if cue_span is None:
            warnings.append(
                _cue_warning(
                    cue,
                    ConfidenceCueWarningCode.OUTSIDE_PATIENT_SUPPORT,
                    "Rejected confidence cue because its quote is not verbatim within "
                    "this claim's patient supporting speech.",
                )
            )
            continue
        if cue.type == ConfidenceCueType.HESITATION and _is_bracketed_ellipsis(
            state.turns[cue_span.turn_index].text,
            cue_span.start_char - state.turns[cue_span.turn_index].start_char,
            cue_span.end_char - state.turns[cue_span.turn_index].start_char,
        ):
            warnings.append(
                _cue_warning(
                    cue,
                    ConfidenceCueWarningCode.BRACKETED_ELLIPSIS,
                    "Rejected bracketed editorial ellipsis as a patient hesitation cue.",
                )
            )
            continue
        grounded.append(ConfidenceCue(type=cue.type, span=cue_span))
    return grounded, warnings


def _cue_warning(
    cue: ProviderConfidenceCue,
    code: ConfidenceCueWarningCode,
    message: str,
) -> ConfidenceCueValidationWarning:
    return ConfidenceCueValidationWarning(
        code=code,
        attempted_type=cue.type,
        turn_index=cue.turn_index,
        quote=cue.quote,
        message=message,
    )


def _find_within_supporting_spans(
    cue: ProviderConfidenceCue,
    spans: list[TranscriptSpan],
) -> TranscriptSpan | None:
    for span in spans:
        if span.turn_index != cue.turn_index:
            continue
        local_start = span.text.find(cue.quote)
        if local_start >= 0:
            start = span.start_char + local_start
            return TranscriptSpan(
                turn_index=span.turn_index,
                start_char=start,
                end_char=start + len(cue.quote),
                text=cue.quote,
            )
    return None


def _detect_hesitations(
    state: PipelineState,
    supporting_spans: list[TranscriptSpan],
) -> list[ConfidenceCue]:
    cues = []
    for span in supporting_spans:
        if state.turns[span.turn_index].speaker != Speaker.PATIENT:
            continue
        for match in re.finditer(r"\.\.\.|…", span.text):
            if _is_bracketed_ellipsis(span.text, match.start(), match.end()):
                continue
            start = span.start_char + match.start()
            cues.append(
                ConfidenceCue(
                    type=ConfidenceCueType.HESITATION,
                    span=TranscriptSpan(
                        turn_index=span.turn_index,
                        start_char=start,
                        end_char=start + len(match.group()),
                        text=match.group(),
                    ),
                )
            )
    return cues


def _is_bracketed_ellipsis(text: str, start: int, end: int) -> bool:
    opening = text.rfind("[", 0, start + 1)
    closing_before = text.rfind("]", 0, start + 1)
    closing_after = text.find("]", end)
    return opening > closing_before and closing_after >= 0


def _deduplicate_cues(cues: list[ConfidenceCue]) -> list[ConfidenceCue]:
    unique: dict[tuple[ConfidenceCueType, int, int, int], ConfidenceCue] = {}
    for cue in cues:
        key = (
            cue.type,
            cue.span.turn_index,
            cue.span.start_char,
            cue.span.end_char,
        )
        unique[key] = cue
    return list(unique.values())
