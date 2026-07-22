# core/modules/predictive/tests/test_contract_doc.py
#
# The frozen contract doc (docs/predictive/API.md) is what the Unity client
# is built against — its JSON examples must validate against the actual
# Pydantic models. Every ```json fence preceded by a
# `<!-- validate: ModelName -->` marker is checked here; if the doc and the
# code disagree, this fails.

import json
import re
from pathlib import Path

import pytest
from predictive import schema

# tests/ → predictive/ → modules/ → core/ → repo root
_DOC = Path(__file__).resolve().parents[4] / "docs" / "predictive" / "API.md"

_MARKED_FENCE = re.compile(
    r"<!--\s*validate:\s*(\w+)\s*-->\s*```json\n(.*?)```",
    re.DOTALL,
)


def _examples() -> list[tuple[str, str, dict]]:
    text = _DOC.read_text(encoding="utf-8")
    out = []
    for idx, match in enumerate(_MARKED_FENCE.finditer(text)):
        model_name, payload = match.group(1), match.group(2)
        out.append((f"{idx:02d}-{model_name}", model_name, json.loads(payload)))
    return out


_CASES = _examples()


def test_doc_exists_and_has_examples():
    assert _DOC.exists()
    # The frozen contract documents at least these models by example.
    names = {model for _, model, _ in _CASES}
    assert {
        "Prediction",
        "AnalyzeRequest",
        "PredictiveReport",
        "SimulateRequest",
        "SimulateResponse",
        "SessionStartRequest",
        "IngestRequest",
        "SceneDigest",
    } <= names


@pytest.mark.parametrize(
    "case_id,model_name,payload",
    _CASES,
    ids=[case_id for case_id, _, _ in _CASES],
)
def test_doc_example_validates_against_model(case_id, model_name, payload):
    model = getattr(schema, model_name, None)
    assert model is not None, (
        f"API.md references schema.{model_name}, which does not exist"
    )
    # Strict-by-intent: the example must parse into the model without error.
    instance = model(**payload)
    # And the declared schema_version, when present, must match the code's.
    if "schema_version" in payload:
        assert payload["schema_version"] == schema.SCHEMA_VERSION
    assert instance is not None
