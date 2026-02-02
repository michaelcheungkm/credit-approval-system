from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


def _as_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def calculate_dti_ratio(monthly_debt: float, monthly_income: float) -> Dict[str, Any]:
    if monthly_income <= 0:
        return {"error": "Monthly income must be > 0"}
    dti = monthly_debt / monthly_income
    status = "Acceptable" if dti <= 0.43 else "High" if dti <= 0.50 else "Excessive"
    return {
        "dti_ratio": round(dti, 4),
        "monthly_debt": round(monthly_debt, 2),
        "monthly_income": round(monthly_income, 2),
        "status": status,
    }


def calculate_ltv_ratio(loan_amount: float, property_value: float) -> Dict[str, Any]:
    if property_value <= 0:
        return {"error": "Property value must be > 0"}
    ltv = loan_amount / property_value
    status = "Excellent" if ltv <= 0.80 else "Good" if ltv <= 0.90 else "High" if ltv <= 0.97 else "Excessive"
    return {
        "ltv_ratio": round(ltv, 4),
        "loan_amount": round(loan_amount, 2),
        "property_value": round(property_value, 2),
        "status": status,
    }


def calculate_reserves(liquid_assets: float, monthly_payment: float, required_months: int = 2) -> Dict[str, Any]:
    if monthly_payment <= 0:
        return {"error": "Monthly payment must be > 0"}
    months_coverage = liquid_assets / monthly_payment
    required_amount = monthly_payment * required_months
    status = "Adequate" if months_coverage >= required_months else "Insufficient"
    return {
        "months_coverage": round(months_coverage, 2),
        "liquid_assets": round(liquid_assets, 2),
        "monthly_payment": round(monthly_payment, 2),
        "required_months": int(required_months),
        "required_amount": round(required_amount, 2),
        "surplus_deficit": round(liquid_assets - required_amount, 2),
        "status": status,
    }


def calculate_housing_expense_ratio(monthly_payment: float, monthly_income: float) -> Dict[str, Any]:
    if monthly_income <= 0:
        return {"error": "Monthly income must be > 0"}
    ratio = monthly_payment / monthly_income
    status = "Acceptable" if ratio <= 0.28 else "Elevated" if ratio <= 0.35 else "High"
    return {
        "housing_ratio": round(ratio, 4),
        "monthly_payment": round(monthly_payment, 2),
        "monthly_income": round(monthly_income, 2),
        "status": status,
    }


def check_credit_score_policy(credit_score: int) -> Dict[str, Any]:
    cs = int(credit_score or 0)
    if cs >= 740:
        tier = "Excellent"
        note = "Best rates available"
    elif cs >= 700:
        tier = "Very Good"
        note = "Favorable rates"
    elif cs >= 660:
        tier = "Good"
        note = "Standard rates"
    elif cs >= 620:
        tier = "Fair"
        note = "Higher rates, may require compensating factors"
    else:
        tier = "Below Minimum"
        note = "Does not meet conventional loan minimum"
    return {"credit_score": cs, "tier": tier, "note": note}


def check_large_deposits(deposits: List[Dict[str, Any]], monthly_income: float) -> Dict[str, Any]:
    income = _as_float(monthly_income, 0.0)
    threshold = max(0.0, income * 0.25)
    large: List[Dict[str, Any]] = []
    for d in deposits or []:
        amt = _as_float(d.get("amount"), 0.0)
        if amt >= threshold and threshold > 0:
            large.append(
                {
                    "amount": round(amt, 2),
                    "date": d.get("date") or "Unknown",
                    "description": d.get("description") or "",
                    "sourcing_required": True,
                }
            )
    return {"threshold": round(threshold, 2), "large_deposits": large, "count": len(large)}


def sum_debts(debts: Dict[str, Any]) -> float:
    if not isinstance(debts, dict):
        return 0.0
    total = 0.0
    for k, v in debts.items():
        # ignore precomputed totals commonly included in the JSON
        if str(k).lower().startswith("total_"):
            continue
        total += _as_float(v, 0.0)
    return float(total)


@dataclass(frozen=True)
class Metrics:
    credit_score: int
    dti: float
    housing_ratio: float
    ltv: float
    reserves_months: float
    late_payments_12mo: int
    bankruptcies: int
    foreclosures: int
    employment_years: float
    employment_type: str
    property_type: str
    required_repairs: float


def compute_metrics(app: Dict[str, Any]) -> Metrics:
    credit_score = int(app.get("credit_score") or 0)

    employment = app.get("employment") or {}
    monthly_income = _as_float(employment.get("monthly_income"), 0.0)
    employment_years = _as_float(employment.get("years") or employment.get("years_employed"), 0.0)
    employment_type = str(employment.get("type") or "")

    loan = app.get("loan") or {}
    monthly_piti = _as_float(loan.get("monthly_piti") or loan.get("estimated_payment"), 0.0)
    loan_amount = _as_float(loan.get("amount"), 0.0)

    prop = app.get("property") or {}
    appraised_value = _as_float(prop.get("appraised_value"), 0.0)
    property_type = str(prop.get("type") or loan.get("property_type") or "")
    required_repairs = _as_float(prop.get("required_repairs"), 0.0)

    debts = app.get("debts") or {}
    existing_debt = sum_debts(debts)

    # DTI: treat provided dti_ratio as authoritative when present
    dti = app.get("dti_ratio")
    dti = _as_float(dti, -1.0)
    if dti <= 0:
        dti = (existing_debt + monthly_piti) / monthly_income if monthly_income > 0 else float("inf")

    housing_ratio = monthly_piti / monthly_income if monthly_income > 0 else float("inf")
    ltv = loan_amount / appraised_value if appraised_value > 0 else float("inf")

    assets = app.get("assets") or {}
    liquid_assets_total = _as_float(
        assets.get("liquid_assets_total"),
        _as_float(assets.get("checking"), 0.0) + _as_float(assets.get("savings"), 0.0),
    )
    reserves_months = liquid_assets_total / monthly_piti if monthly_piti > 0 else float("inf")

    credit_hist = app.get("credit_history") or {}
    late12 = int(credit_hist.get("late_payments_12mo") or 0)
    bankruptcies = int(credit_hist.get("bankruptcies") or 0)
    foreclosures = int(credit_hist.get("foreclosures") or 0)

    return Metrics(
        credit_score=credit_score,
        dti=float(dti),
        housing_ratio=float(housing_ratio),
        ltv=float(ltv),
        reserves_months=float(reserves_months),
        late_payments_12mo=late12,
        bankruptcies=bankruptcies,
        foreclosures=foreclosures,
        employment_years=float(employment_years),
        employment_type=employment_type,
        property_type=property_type,
        required_repairs=float(required_repairs),
    )


def baseline_decision(metrics: Metrics) -> Tuple[int, str, List[str], List[str]]:
    """
    Returns: (risk_score, decision, conditions, reasons)
    Decision is guardrailed so test cases are stable and policy-like.
    """
    score = 0
    conditions: List[str] = []
    reasons: List[str] = []

    # Hard fails
    if metrics.credit_score < 620:
        reasons.append(f"Credit score {metrics.credit_score} is below minimum 620.")
    if metrics.dti > 0.50:
        reasons.append(f"DTI {metrics.dti*100:.1f}% exceeds 50% maximum.")
    if metrics.late_payments_12mo > 2:
        reasons.append(f"Late payments in last 12 months ({metrics.late_payments_12mo}) exceed maximum of 2.")

    # Risk score factors (higher = worse)
    cs = metrics.credit_score
    if cs < 620:
        score += 45
    elif cs < 660:
        score += 25
    elif cs < 700:
        score += 15
    elif cs < 740:
        score += 8

    if metrics.dti > 0.50:
        score += 35
    elif metrics.dti > 0.43:
        score += 20
    elif metrics.dti > 0.36:
        score += 10

    if metrics.ltv > 0.97:
        score += 25
    elif metrics.ltv > 0.90:
        score += 10

    if metrics.reserves_months < 2:
        score += 15
        conditions.append(f"Increase reserves to at least 2 months of PITI (currently {metrics.reserves_months:.1f}).")
    elif metrics.reserves_months < 6:
        score += 5

    if metrics.late_payments_12mo > 0:
        score += 10
        conditions.append(f"Provide letter of explanation for {metrics.late_payments_12mo} late payment(s) in last 12 months.")

    if metrics.bankruptcies > 0:
        score += 30
        conditions.append("Provide bankruptcy documentation and confirm seasoning meets program requirements.")

    if metrics.foreclosures > 0:
        score += 30
        conditions.append("Provide foreclosure documentation and confirm seasoning meets program requirements.")

    if metrics.employment_years > 0 and metrics.employment_years < 2:
        score += 5
        conditions.append(
            f"Employment tenure is {metrics.employment_years:.1f} years; provide full 2-year employment history and verification."
        )

    if "self" in metrics.employment_type.lower():
        score += 5
        conditions.append("Self-employed: provide 2 years personal/business tax returns and YTD P&L per policy.")

    if metrics.required_repairs > 0:
        score += 5
        conditions.append(f"Property repairs required (${metrics.required_repairs:,.0f}): complete prior to closing or escrow holdback per policy.")

    if "condo" in metrics.property_type.lower():
        score += 3
        conditions.append("Condominium: require project approval/review documentation (HOA budget, insurance, questionnaire, etc.).")

    score = max(0, min(100, int(round(score))))

    if reasons:
        return score, "DENIED", conditions, reasons

    # Guardrail thresholds
    if score >= 75:
        return score, "DENIED", conditions, reasons
    if score >= 40 or conditions:
        return score, "CONDITIONAL_APPROVAL", conditions, reasons
    return score, "APPROVED", conditions, reasons

