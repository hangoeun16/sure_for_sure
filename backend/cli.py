"""CLI using the same repository and runner as the API."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pipeline.input_contract import EncounterInput
from pipeline.models import EncounterAnalysis
from pipeline.providers import (
    AnthropicClaimExtractionProvider,
    ProviderError,
    StubClaimExtractionProvider,
)
from pipeline.providers.base import ClaimExtractionProvider
from pipeline.runner import run_pipeline

from backend.config import load_local_env
from backend.human_review import (
    DEFAULT_REVIEW_ROOT,
    DEFAULT_REVIEW_RUN_ID,
    DEFAULT_RUNS_ROOT,
    HumanReviewService,
    ReviewError,
)
from backend.live_run import (
    ARTIFACT_FILES,
    DEFAULT_ARTIFACTS_ROOT,
    inspect_latest_run,
    preflight_anthropic_run,
    run_anthropic_live,
)
from backend.repository import EncounterRepository, RepositoryError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sure-for-sure")
    commands = parser.add_subparsers(dest="command", required=True)
    one = commands.add_parser("analyze", help="Analyze one encounter end to end.")
    one.add_argument("--input", required=True)
    selector = one.add_mutually_exclusive_group()
    selector.add_argument("--index", type=int, default=0)
    selector.add_argument("--record-id")
    one.add_argument("--provider", choices=("stub", "anthropic"), default="stub")
    one.add_argument("--output")
    one.add_argument("--artifacts-root", default=str(DEFAULT_ARTIFACTS_ROOT))
    all_records = commands.add_parser("analyze-all", help="Analyze every input encounter.")
    all_records.add_argument("--input", required=True)
    all_records.add_argument("--provider", choices=("stub", "anthropic"), default="stub")
    all_records.add_argument("--output")
    all_records.add_argument("--artifacts-root", default=str(DEFAULT_ARTIFACTS_ROOT))
    preflight = commands.add_parser(
        "anthropic-preflight",
        help="Validate a 25-record live run without sending an API request.",
    )
    preflight.add_argument("--input", required=True)
    preflight.add_argument("--provider", choices=("anthropic",), required=True)
    preflight.add_argument("--artifacts-root", default=str(DEFAULT_ARTIFACTS_ROOT))
    inspect_run = commands.add_parser(
        "inspect-live-run",
        help="Print one artifact from the latest one-record or batch live run.",
    )
    inspect_run.add_argument("--artifacts-root", default=str(DEFAULT_ARTIFACTS_ROOT))
    inspect_run.add_argument("--latest", choices=("one", "batch"), required=True)
    inspect_run.add_argument("--file", choices=tuple(ARTIFACT_FILES), required=True)
    human_review = commands.add_parser(
        "human-review",
        help="Launch the local transcript-only human-review interface.",
    )
    _add_human_review_paths(human_review)
    human_review.add_argument("--host", default="127.0.0.1")
    human_review.add_argument("--port", default=8000, type=int)
    human_metrics = commands.add_parser(
        "human-review-metrics",
        help="Calculate transcript-only metrics after human review is complete.",
    )
    _add_human_review_paths(human_metrics)
    return parser


def _add_human_review_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", default=DEFAULT_REVIEW_RUN_ID)
    parser.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    parser.add_argument("--review-root", default=str(DEFAULT_REVIEW_ROOT))


def _human_review_service(args: argparse.Namespace) -> HumanReviewService:
    return HumanReviewService(
        run_id=args.run_id,
        runs_root=args.runs_root,
        review_root=args.review_root,
    )


def _provider(name: str, encounter: EncounterInput) -> ClaimExtractionProvider:
    if name == "anthropic":
        return AnthropicClaimExtractionProvider()
    fixture = encounter.metadata.get("claim_extraction")
    return StubClaimExtractionProvider(fixture if isinstance(fixture, dict) else None)


def main(argv: Sequence[str] | None = None) -> int:
    load_local_env()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "human-review":
            service = _human_review_service(args)
            _ = service.dataset  # Validate the frozen source before starting the server.
            frontend_index = (
                Path(__file__).resolve().parents[1] / "frontend" / "dist" / "index.html"
            )
            if not frontend_index.is_file():
                raise ValueError("Build the frontend before launching human review.")
            os.environ["SURE_FOR_SURE_REVIEW_RUN_ID"] = args.run_id
            os.environ["SURE_FOR_SURE_REVIEW_RUNS_ROOT"] = str(Path(args.runs_root).resolve())
            os.environ["SURE_FOR_SURE_HUMAN_REVIEW_ROOT"] = str(
                Path(args.review_root).resolve()
            )
            import uvicorn

            uvicorn.run("backend.main:app", host=args.host, port=args.port)
            return 0
        if args.command == "human-review-metrics":
            metrics = _human_review_service(args).calculate_metrics()
            print(json.dumps(metrics, indent=2))
            return 0
        if args.command == "anthropic-preflight":
            result = preflight_anthropic_run(
                input_path=args.input,
                artifacts_root=args.artifacts_root,
            )
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "inspect-live-run":
            print(
                inspect_latest_run(
                    artifacts_root=args.artifacts_root,
                    run_kind=args.latest,
                    artifact=args.file,
                ),
                end="",
            )
            return 0
        repository = EncounterRepository(args.input)
        if args.provider == "anthropic":
            if args.command == "analyze":
                if args.record_id:
                    _, selected_source = repository.get_by_id(args.record_id)
                    selected_indexes = [selected_source.source_record_index]
                else:
                    repository.get_by_index(args.index)
                    selected_indexes = [args.index]
                run_kind = "one"
            else:
                selected_indexes = list(range(len(repository.raw_records())))
                run_kind = "batch"
            live_result = run_anthropic_live(
                repository=repository,
                record_indexes=selected_indexes,
                run_kind=run_kind,
                artifacts_root=args.artifacts_root,
            )
            if args.output:
                _write_reports(Path(args.output), live_result.reports)
            print(json.dumps(live_result.summary, indent=2))
            return 1 if live_result.summary["failed_records"] else 0
        if args.command == "analyze":
            encounter, source = (
                repository.get_by_id(args.record_id)
                if args.record_id
                else repository.get_by_index(args.index)
            )
            report = run_pipeline(encounter, _provider(args.provider, encounter), source=source)
            rendered = json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False)
            if args.output:
                Path(args.output).write_text(rendered + "\n", encoding="utf-8")
            else:
                print(rendered)
            return 0
        if not args.output:
            raise ValueError("--output is required for stub analyze-all runs")
        reports: list[EncounterAnalysis] = []
        failures: list[dict[str, Any]] = []
        for index, raw in enumerate(repository.raw_records()):
            try:
                encounter, source = repository.get_by_index(index)
                reports.append(
                    run_pipeline(encounter, _provider(args.provider, encounter), source=source)
                )
            except (
                RepositoryError,
                ProviderError,
                ValueError,
                IndexError,
                KeyError,
            ) as exc:
                failures.append({"index": index, "id": raw.get("id"), "error": str(exc)})
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            "".join(
                json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n"
                for item in reports
            ),
            encoding="utf-8",
        )
        summary = _summary(len(repository.raw_records()), reports, failures)
        output.with_name(f"{output.stem}-summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(summary, indent=2))
        return 1 if failures else 0
    except (
        RepositoryError,
        ProviderError,
        ReviewError,
        ValueError,
        IndexError,
        KeyError,
    ) as exc:
        parser.error(str(exc))
    return 2


def _write_reports(path: Path, reports: Sequence[EncounterAnalysis]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if len(reports) == 1:
        rendered = json.dumps(reports[0].model_dump(mode="json"), indent=2, ensure_ascii=False)
        path.write_text(rendered + "\n", encoding="utf-8")
        return
    path.write_text(
        "".join(
            json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n"
            for item in reports
        ),
        encoding="utf-8",
    )


def _summary(
    attempted: int,
    reports: Sequence[EncounterAnalysis],
    failures: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    confidences: Counter[str] = Counter(
        claim.confidence.level.value for report in reports for claim in report.claims
    )
    relations: Counter[str] = Counter(
        result.relation.value for report in reports for result in report.divergences.values()
    )
    routes: Counter[str] = Counter(
        action.route.value for report in reports for action in report.actions
    )
    scores = sorted(
        result.ced_score
        for report in reports
        for result in report.ced_results.values()
        if result.ced_score is not None
    )
    median = scores[len(scores) // 2] if scores else None
    return {
        "records_attempted": attempted,
        "records_succeeded": len(reports),
        "records_failed": len(failures),
        "claims_extracted": sum(len(report.claims) for report in reports),
        "confidence_distribution": dict(confidences),
        "evidence_relation_distribution": dict(relations),
        "routes": dict(routes),
        "ced": {
            "scorable_claims": len(scores),
            "unscorable_claims": sum(
                not result.scorable for report in reports for result in report.ced_results.values()
            ),
            "min": scores[0] if scores else None,
            "median": median,
            "max": scores[-1] if scores else None,
        },
        "failures": failures,
    }


if __name__ == "__main__":
    raise SystemExit(main())
