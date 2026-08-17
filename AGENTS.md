# Active Repository Instructions

These are the only active repository-level instructions for the current rebuild.

## Goal

Build a portfolio-quality, end-to-end medication claim verification system using
the organizer-provided synthetic encounter dataset.

The original hackathon implementation under `legacy/` is archival reference only.
Preserve the product idea and useful data knowledge, not the legacy architecture
or implementation.

## Work rules

- Do not stop at internal phases, MCP checkpoints, audits, or infrastructure milestones.
- Do not treat ingestion, hashing, profiling, schemas, or provenance as project completion.
- Do not rewrite the root README until the end-to-end acceptance gate passes.
- Do not create accuracy metrics or claim human review without independently reviewed gold data.
- Do not hard-code record IDs, complete transcript phrases, encounter-specific expressions,
  or outputs from the 25 organizer-provided records.
- Do not modify locked acceptance tests after the acceptance-contract commit.
- Implement working product behavior, not documentation describing future behavior.
- Continue from planning directly into implementation unless genuinely blocked.
- Archived instruction files under `docs/archive/old_codex_instructions/` are non-authoritative.
