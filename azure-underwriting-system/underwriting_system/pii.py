from __future__ import annotations

import copy
import re
from typing import Any, Dict, List


def sanitize_pii(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Redact common PII fields in the applicant data.
    """
    sanitized = copy.deepcopy(data or {})

    # SSN
    if "ssn" in sanitized:
        ssn = str(sanitized.get("ssn") or "")
        last4 = ssn[-4:] if len(ssn) >= 4 else "XXXX"
        sanitized["ssn"] = f"***-**-{last4}"

    # Name / Address / Phone / Email
    if "name" in sanitized:
        sanitized["name"] = "[APPLICANT_NAME]"
    if "address" in sanitized:
        sanitized["address"] = "[ADDRESS]"
    if "phone" in sanitized:
        phone = str(sanitized.get("phone") or "")
        digits = re.sub(r"\D+", "", phone)
        last4 = digits[-4:] if len(digits) >= 4 else "XXXX"
        sanitized["phone"] = f"***-***-{last4}"
    if "email" in sanitized:
        sanitized["email"] = "[EMAIL]"

    return sanitized


def detect_bias_signals(analysis_text: str, applicant_data: Dict[str, Any]) -> List[str]:
    """
    Lightweight “red flag” detector for mention of protected classes.
    (This is NOT a full fair-lending model; it's just a safety signal.)
    """
    text = (analysis_text or "").lower()
    flags: List[str] = []

    protected_terms = [
        "race",
        "color",
        "religion",
        "national origin",
        "sex",
        "gender",
        "marital status",
        "age",
        "disability",
        "familial status",
        "pregnan",
        "citizenship",
    ]

    for term in protected_terms:
        if term in text:
            flags.append(f"Analysis mentions protected characteristic: {term}")

    # Geographic proxy signal
    if any(k in (applicant_data or {}) for k in ["zip", "zipcode"]):
        if "neighborhood" in text or "area" in text:
            flags.append("Potential geographic bias proxy (zip/neighborhood). Review for fair-lending compliance.")

    return flags

