# Limitations and responsible use

- CED is an attention heuristic, not a clinical risk or diagnostic score.
- The record is treated as available evidence, not unquestioned ground truth.
- Structured extraction can fail or miss claims; malformed output fails explicitly.
- The medication normalizer is deterministic and intentionally narrow. It does not replace
  terminology services or pharmacist review.
- The organizer dataset is synthetic and has one encounter per patient. It cannot establish
  clinical validity, real-world generalization, or longitudinal performance.
- The checked-in 25-record evaluation is author-annotated rather than independently
  reviewed. Its reasoning metrics are engineering evidence, not clinical validation.
- Model-backed extraction precision, recall, F1, and field metrics were not run in this
  environment because the Anthropic key and model setting were unavailable.
- The software is a portfolio prototype and must not be used as autonomous clinical
  decision support.
