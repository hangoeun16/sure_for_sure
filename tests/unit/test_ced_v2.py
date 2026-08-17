from __future__ import annotations

import pytest
from pipeline.ced import compute_ced


@pytest.mark.parametrize(
    ("confidence", "divergence", "expected"),
    [
        (1.0, 1.0, 1.0),
        (1.0, 0.75, 0.75),
        (0.67, 0.75, 0.5025),
        (0.33, 1.0, 0.33),
        (1.0, 0.0, 0.0),
    ],
)
def test_ced_is_multiplication(confidence, divergence, expected) -> None:
    assert compute_ced(confidence, divergence) == expected


def test_unscorable_axis_abstains() -> None:
    assert compute_ced(None, 1.0) is None
    assert compute_ced(1.0, None) is None
