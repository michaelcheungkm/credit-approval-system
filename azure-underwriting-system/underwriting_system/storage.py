from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional


def _safe_case_id(case_id: str) -> str:
    cid = (case_id or "demo").strip()
    cid = re.sub(r"[^A-Za-z0-9._-]+", "_", cid)
    return cid[:120] if len(cid) > 120 else cid


@dataclass
class LocalJSONStore:
    base_dir: str

    def __post_init__(self) -> None:
        os.makedirs(self.base_dir, exist_ok=True)

    def _path(self, case_id: str) -> str:
        return os.path.join(self.base_dir, f"{_safe_case_id(case_id)}.json")

    def save(self, case_id: str, payload: Dict[str, Any]) -> None:
        path = self._path(case_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def get(self, case_id: str) -> Optional[Dict[str, Any]]:
        path = self._path(case_id)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

