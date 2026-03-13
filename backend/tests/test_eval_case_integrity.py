import json
from pathlib import Path


def test_pdf_regression_cases_are_not_corrupted():
    case_file = Path("tests/evals/pdf_regression_cases.jsonl")
    lines = [line for line in case_file.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert lines, "pdf regression cases should not be empty"

    for line in lines:
        case = json.loads(line)
        assert "?" not in case["question"]
        assert "?" not in case["query"]
        assert all("?" not in source for source in case["expected_sources"])
        assert all(keyword.strip() and "?" not in keyword for keyword in case["expected_keywords"])
