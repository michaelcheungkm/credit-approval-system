from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

from .pii import detect_bias_signals, sanitize_pii
from .policies import PolicyStore, retrieve_relevant_policies
from .state import UnderwritingState
from .tools import (
    baseline_decision,
    calculate_housing_expense_ratio,
    calculate_ltv_ratio,
    calculate_reserves,
    check_credit_score_policy,
    check_large_deposits,
    compute_metrics,
    sum_debts,
)


def initialize_application_node(state: UnderwritingState) -> UnderwritingState:
    app = state.get("applicant_data") or {}
    case_id = state.get("case_id") or str(app.get("case_id") or "demo")
    sanitized = sanitize_pii(app)
    now = datetime.now().isoformat()
    return {
        **state,
        "case_id": case_id,
        "sanitized_data": sanitized,
        "analysis_complete": False,
        "human_review_required": False,
        "human_review_completed": False,
        "bias_flags": [],
        "policy_violations": [],
        "conditions": [],
        "reasons": [],
        "reasoning_chain": [f"Application {case_id} initialized"],
        "timestamp": now,
    }


def supervisor_node(state: UnderwritingState) -> UnderwritingState:
    analyses_done = {
        "credit": state.get("credit_analysis") is not None,
        "income": state.get("income_analysis") is not None,
        "asset": state.get("asset_analysis") is not None,
        "collateral": state.get("collateral_analysis") is not None,
    }

    if not analyses_done["credit"]:
        next_agent = "credit"
    elif not analyses_done["income"]:
        next_agent = "income"
    elif not analyses_done["asset"]:
        next_agent = "asset"
    elif not analyses_done["collateral"]:
        next_agent = "collateral"
    else:
        next_agent = "decision"

    return {**state, "next_agent": next_agent, "analysis_complete": all(analyses_done.values())}


def should_continue(state: UnderwritingState) -> str:
    if state.get("analysis_complete"):
        return "decision"
    return state.get("next_agent") or "credit"


def _llm_invoke(llm: AzureChatOpenAI, system_prompt: str, user_prompt: str) -> str:
    resp = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
    return str(resp.content or "")


def credit_analyst_node(state: UnderwritingState, *, llm: AzureChatOpenAI, policy_store: PolicyStore) -> UnderwritingState:
    policies = retrieve_relevant_policies(
        "credit score requirements bankruptcies foreclosures late payments collections",
        policy_store,
    )
    app = state.get("sanitized_data") or {}
    case_id = state.get("case_id") or app.get("case_id") or "Unknown"

    credit_score = int(app.get("credit_score") or 0)
    credit_score_assessment = check_credit_score_policy(credit_score)
    credit_hist = app.get("credit_history") or {}

    system_prompt = f"""
You are a Senior Credit Analyst with 15+ years of mortgage underwriting experience.

Use the relevant policy excerpts to ensure your analysis is compliant and auditable.
Do not mention or rely on protected characteristics (race, religion, sex, etc.).

RELEVANT POLICIES (excerpts):
{policies}

ANALYSIS FRAMEWORK:
1) Credit score assessment (use the provided assessment; do NOT recalculate)
2) Payment history (late payments, patterns)
3) Derogatory items (bankruptcies/foreclosures/collections)
4) Policy compliance notes
5) Risk rating (Low/Medium/High)
6) Recommendations / conditions

Output ONLY a markdown report with these headings:

### Credit Analysis for Case {case_id}
#### Credit Score
#### Payment History
#### Derogatory / Public Records
#### Policy Compliance
#### Risk Rating
#### Recommendations
""".strip()

    user_prompt = f"""
CASE (sanitized):
{json.dumps(app, indent=2)}

EXACT CREDIT SCORE ASSESSMENT (do not recalculate):
{json.dumps(credit_score_assessment, indent=2)}

CREDIT HISTORY (sanitized):
{json.dumps(credit_hist, indent=2)}
""".strip()

    analysis = _llm_invoke(llm, system_prompt, user_prompt)
    bias_flags = detect_bias_signals(analysis, app)
    return {
        **state,
        "credit_analysis": analysis,
        "bias_flags": (state.get("bias_flags") or []) + bias_flags,
        "reasoning_chain": (state.get("reasoning_chain") or []) + [f"Credit Analyst: Completed credit analysis for {case_id}"],
    }


def income_analyst_node(state: UnderwritingState, *, llm: AzureChatOpenAI, policy_store: PolicyStore) -> UnderwritingState:
    policies = retrieve_relevant_policies("employment income verification DTI ratio self-employed", policy_store)
    app = state.get("sanitized_data") or {}
    case_id = state.get("case_id") or app.get("case_id") or "Unknown"

    employment = app.get("employment") or {}
    loan = app.get("loan") or {}
    debts = app.get("debts") or {}

    monthly_income = float(employment.get("monthly_income") or 0)
    monthly_piti = float(loan.get("monthly_piti") or loan.get("estimated_payment") or 0)
    existing_debt = sum_debts(debts)

    # Use provided DTI when available, otherwise compute.
    dti_ratio = app.get("dti_ratio")
    dti_ratio = float(dti_ratio) if dti_ratio is not None else None
    computed_dti = (existing_debt + monthly_piti) / monthly_income if monthly_income > 0 else float("inf")
    dti_to_use = dti_ratio if (dti_ratio is not None and dti_ratio > 0) else computed_dti

    housing_ratio = calculate_housing_expense_ratio(monthly_piti, monthly_income)

    system_prompt = f"""
You are a Senior Income Analyst specializing in mortgage underwriting (employment/income/DTI).

RELEVANT POLICIES (excerpts):
{policies}

ANALYSIS FRAMEWORK:
1) Employment Stability - Review job history and tenure
2) Income Verification - Validate income sources
3) DTI Calculation - Use the provided DTI (DO NOT recalculate it)
4) Payment Capacity - Assess affordability
5) Risk Assessment - Identify income risks
6) Recommendations - Provide conditions if needed

Output ONLY a markdown report with these headings:

### Income Analysis for Case {case_id}
#### Employment Stability
#### Income Verification
#### DTI / Payment Capacity
#### Risk Assessment
#### Recommendations
""".strip()

    user_prompt = f"""
CASE (sanitized):
{json.dumps(app, indent=2)}

EMPLOYMENT (sanitized):
{json.dumps(employment, indent=2)}

DEBTS (sanitized):
{json.dumps(debts, indent=2)}

PRE-CALCULATED METRICS (use these exact values; do NOT recompute DTI):
- Monthly income: ${monthly_income:,.2f}
- Existing monthly debt (excluding proposed mortgage): ${existing_debt:,.2f}
- Proposed monthly PITI: ${monthly_piti:,.2f}
- DTI ratio (authoritative if present in file): {dti_to_use:.4f} ({dti_to_use*100:.1f}%)
- Housing ratio: {housing_ratio}
""".strip()

    analysis = _llm_invoke(llm, system_prompt, user_prompt)
    bias_flags = detect_bias_signals(analysis, app)
    return {
        **state,
        "income_analysis": analysis,
        "bias_flags": (state.get("bias_flags") or []) + bias_flags,
        "reasoning_chain": (state.get("reasoning_chain") or []) + [f"Income Analyst: Completed income analysis for {case_id}"],
    }


def asset_analyst_node(state: UnderwritingState, *, llm: AzureChatOpenAI, policy_store: PolicyStore) -> UnderwritingState:
    policies = retrieve_relevant_policies("down payment reserves assets large deposits gift funds", policy_store)
    app = state.get("sanitized_data") or {}
    case_id = state.get("case_id") or app.get("case_id") or "Unknown"

    assets = app.get("assets") or {}
    employment = app.get("employment") or {}
    loan = app.get("loan") or {}

    monthly_income = float(employment.get("monthly_income") or 0)
    monthly_piti = float(loan.get("monthly_piti") or loan.get("estimated_payment") or 0)

    liquid_assets_total = float(
        assets.get("liquid_assets_total")
        or (float(assets.get("checking") or 0) + float(assets.get("savings") or 0))
    )

    reserves = calculate_reserves(liquid_assets_total, monthly_piti, required_months=2)
    deposits = check_large_deposits(assets.get("recent_deposits") or [], monthly_income)
    deposits_documented = bool(str(assets.get("deposit_explanations") or "").strip())

    system_prompt = f"""
You are a Senior Asset Analyst in mortgage underwriting (down payment, reserves, source of funds).

RELEVANT POLICIES (excerpts):
{policies}

ANALYSIS FRAMEWORK:
1) Down Payment Adequacy
2) Reserve Requirements - Use the provided reserves calculation (do NOT recalculate)
3) Large Deposits - Use the provided deposit analysis (do NOT recalculate)
4) Source of Funds - Ensure acceptable sourcing
5) Risk Assessment
6) Documentation Needs

Output ONLY a markdown report with these headings:

### Asset Analysis for Case {case_id}
#### Down Payment Adequacy
#### Reserves
#### Large Deposits
#### Source of Funds
#### Risk Assessment
#### Documentation Needs
""".strip()

    user_prompt = f"""
CASE (sanitized):
{json.dumps(app, indent=2)}

ASSETS (sanitized):
{json.dumps(assets, indent=2)}

LOAN REQUIREMENTS (sanitized):
{json.dumps(loan, indent=2)}

PRE-CALCULATED METRICS (use these exact values; do NOT recompute):
- Liquid assets total: ${liquid_assets_total:,.2f}
- Monthly PITI: ${monthly_piti:,.2f}
- Reserves calculation: {reserves}
- Large deposits analysis: {deposits}
- Deposit explanations provided: {deposits_documented}
""".strip()

    analysis = _llm_invoke(llm, system_prompt, user_prompt)
    bias_flags = detect_bias_signals(analysis, app)
    return {
        **state,
        "asset_analysis": analysis,
        "bias_flags": (state.get("bias_flags") or []) + bias_flags,
        "reasoning_chain": (state.get("reasoning_chain") or []) + [f"Asset Analyst: Completed asset analysis for {case_id}"],
    }


def collateral_analyst_node(state: UnderwritingState, *, llm: AzureChatOpenAI, policy_store: PolicyStore) -> UnderwritingState:
    policies = retrieve_relevant_policies("appraisal property condition LTV collateral condo repairs", policy_store)
    app = state.get("sanitized_data") or {}
    case_id = state.get("case_id") or app.get("case_id") or "Unknown"

    prop = app.get("property") or {}
    loan = app.get("loan") or {}

    loan_amount = float(loan.get("amount") or 0)
    appraised_value = float(prop.get("appraised_value") or 0)
    ltv = calculate_ltv_ratio(loan_amount, appraised_value)

    system_prompt = f"""
You are a Senior Collateral Analyst specializing in property valuation and collateral risk.

RELEVANT POLICIES (excerpts):
{policies}

ANALYSIS FRAMEWORK:
1) Appraisal Review
2) LTV Calculation - Use the provided LTV (do NOT recalculate)
3) Property Condition / Repairs
4) Marketability
5) Risk Assessment
6) Recommendations / conditions

Output ONLY a markdown report with these headings:

### Collateral Analysis for Case {case_id}
#### Appraisal / Value
#### LTV
#### Condition / Repairs
#### Marketability
#### Risk Assessment
#### Recommendations
""".strip()

    user_prompt = f"""
CASE (sanitized):
{json.dumps(app, indent=2)}

PROPERTY (sanitized):
{json.dumps(prop, indent=2)}

LOAN (sanitized):
{json.dumps(loan, indent=2)}

PRE-CALCULATED LTV (use these exact values; do NOT recompute):
{ltv}
""".strip()

    analysis = _llm_invoke(llm, system_prompt, user_prompt)
    bias_flags = detect_bias_signals(analysis, app)
    return {
        **state,
        "collateral_analysis": analysis,
        "bias_flags": (state.get("bias_flags") or []) + bias_flags,
        "reasoning_chain": (state.get("reasoning_chain") or []) + [f"Collateral Analyst: Completed collateral analysis for {case_id}"],
    }


def decision_agent_node(state: UnderwritingState, *, llm: AzureChatOpenAI, policy_store: PolicyStore) -> UnderwritingState:
    """
    Final synthesis. Uses guardrailed baseline decision/risk_score for stability,
    and uses the LLM to write an audit-ready memo + conditions/reasons.
    """
    policies = retrieve_relevant_policies("final decision risk score approval conditions denial reasons", policy_store)
    app = state.get("sanitized_data") or {}
    case_id = state.get("case_id") or app.get("case_id") or "Unknown"

    metrics = compute_metrics(app)
    risk_score, decision, conditions, reasons = baseline_decision(metrics)

    system_prompt = f"""
You are the Senior Underwriter (Decision Agent). Produce an audit-ready credit memo.

RELEVANT POLICIES (excerpts):
{policies}

You MUST:
- Use the provided baseline decision + risk score as the final outcome.
- Explain the decision with clear, policy-aligned rationale.
- List conditions (if conditional approval) and reasons (if denied) consistent with the provided outcome.
- Do not include any protected-class reasoning.

Output ONLY markdown with these headings:

### RISK_SCORE: {risk_score}
### DECISION: {decision}
### CONDITIONS
### REASONS
### CREDIT_MEMO
""".strip()

    user_prompt = f"""
CASE (sanitized):
{json.dumps(app, indent=2)}

SPECIALIST ANALYSES (verbatim):
--- CREDIT ---
{state.get("credit_analysis") or "N/A"}

--- INCOME ---
{state.get("income_analysis") or "N/A"}

--- ASSET ---
{state.get("asset_analysis") or "N/A"}

--- COLLATERAL ---
{state.get("collateral_analysis") or "N/A"}

BASELINE OUTCOME (final, do not change):
- risk_score: {risk_score}
- decision: {decision}
- conditions: {conditions}
- reasons: {reasons}

Write the memo and include the conditions/reasons sections.
""".strip()

    memo = _llm_invoke(llm, system_prompt, user_prompt)

    # Human review trigger: deny, high score, or bias flags
    human_review_required = decision == "DENIED" or risk_score >= 65 or len(state.get("bias_flags") or []) > 0

    return {
        **state,
        "risk_score": risk_score,
        "final_decision": decision,
        "conditions": conditions,
        "reasons": reasons,
        "decision_memo": memo,
        "human_review_required": human_review_required,
        "reasoning_chain": (state.get("reasoning_chain") or []) + [f"Decision Agent: Final decision {decision} (risk {risk_score})"],
    }

