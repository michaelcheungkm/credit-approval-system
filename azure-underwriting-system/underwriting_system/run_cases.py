from __future__ import annotations

import argparse
import json
import os
from typing import Any, Dict, List

from rich.console import Console
from rich.table import Table

from .config import load_config
from .state import DECISION_APPROVED, DECISION_CONDITIONAL, DECISION_DENIED
from .workflow import build_workflow


console = Console()


def _normalize_expected(x: str) -> str:
    v = (x or "").strip().upper()
    if v in {"CONDITIONAL", "CONDITIONAL_APPROVAL"}:
        return DECISION_CONDITIONAL
    if v in {"REJECTED", "DENIED"}:
        return DECISION_DENIED
    return DECISION_APPROVED


def main() -> int:
    parser = argparse.ArgumentParser(description="Run all underwriting test cases via Azure OpenAI + LangGraph.")
    parser.add_argument("--policies", required=True, help="Path to underwriting_policies.pdf")
    parser.add_argument("--testcases", required=True, help="Path to mortgage_test_cases.json")
    args = parser.parse_args()

    policies_pdf = os.path.abspath(args.policies)
    testcases_path = os.path.abspath(args.testcases)

    cfg = load_config()
    wf = build_workflow(cfg=cfg, policies_pdf_path=policies_pdf)

    with open(testcases_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cases: List[Dict[str, Any]] = data.get("test_cases") if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise RuntimeError("Test cases JSON must be an array or { test_cases: [...] }")

    table = Table(title="Underwriting Results")
    table.add_column("case_id", style="bold")
    table.add_column("expected")
    table.add_column("actual", style="bold")
    table.add_column("risk_score")
    table.add_column("match")

    all_ok = True
    results: List[Dict[str, Any]] = []

    for c in cases:
        case_id = str(c.get("case_id") or "demo")
        expected = _normalize_expected(str(c.get("expected_decision") or ""))
        state = wf.run(case_id=case_id, applicant_data=c, thread_id=case_id)

        actual = str(state.get("final_decision") or "")
        risk_score = state.get("risk_score")
        match = "✅" if actual == expected else "❌"
        if match == "❌":
            all_ok = False

        table.add_row(case_id, expected, actual, str(risk_score), match)
        results.append(state)

    console.print(table)

    # Print the memo for each case (truncated)
    for r in results:
        memo = (r.get("decision_memo") or "").strip()
        if memo:
            console.rule(f"[bold]Decision memo: {r.get('case_id')}")
            console.print(memo[:2000] + ("\n...(truncated)" if len(memo) > 2000 else ""))

    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())

