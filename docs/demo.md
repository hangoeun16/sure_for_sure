# Demo artifacts

The committed demo is derived from the independently authored public example. It exists
to demonstrate rendering and report shape without redistributing organizer records.

The organizer-data publication workflow is intentionally separate:

```text
local organizer records → live provider run → manual inspection
→ build_public_demo.py → redaction check → reviewed public artifact
```

The repository includes concise author annotations from a completed review of all 25
organizer records plus deterministic reasoning results. It does not publish a model-backed
organizer run because this checkout has no configured Anthropic key or model setting. The
fixture-backed public demo remains a reproducible product example, not extraction evidence.
