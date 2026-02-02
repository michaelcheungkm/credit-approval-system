from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class UnderwritingState(TypedDict, total=False):
    # Application Information
    case_id: str
    applicant_data: Dict[str, Any]
    sanitized_data: Dict[str, Any]

    # Agent Analysis Results
    credit_analysis: Optional[str]
    income_analysis: Optional[str]
    asset_analysis: Optional[str]
    collateral_analysis: Optional[str]

    # Coordination & Decision
    decision_memo: Optional[str]
    final_decision: Optional[str]  # APPROVED, DENIED, CONDITIONAL_APPROVAL
    risk_score: Optional[int]  # 0-100
    conditions: List[str]
    reasons: List[str]

    # Workflow Control
    next_agent: Optional[str]
    analysis_complete: bool
    human_review_required: bool
    human_review_completed: bool
    human_notes: Optional[str]

    # Compliance
    bias_flags: List[str]
    policy_violations: List[str]

    # Audit Trail
    reasoning_chain: List[str]
    timestamp: str


DECISION_APPROVED = "APPROVED"
DECISION_CONDITIONAL = "CONDITIONAL_APPROVAL"
DECISION_DENIED = "DENIED"

