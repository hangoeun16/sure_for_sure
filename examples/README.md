# Public input/output example

`input.example.json` is independently authored and follows the organizer-compatible
top-level contract. Its `metadata.claim_extraction` object is deterministic fixture data
used only by the stub provider. It is not copied from or annotated against the organizer
dataset.

Regenerate the checked output with:

```bash
sure-for-sure analyze --input examples/input.example.json --provider stub --output examples/output.example.json
```
