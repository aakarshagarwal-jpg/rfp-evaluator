"""Validation Tool: parse, schema-check and normalise an LLM scorecard.

Guarantees on output (regardless of what the LLM returned):
  * exactly one result per ACTIVE criterion, in criterion_id order
  * every score is a finite number within [0, max_score]  (max_score comes from the DB, not the LLM)
  * every adjustment is recorded as a human-readable warning
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class ParseError(ValueError):
    """The evaluator output is not parseable JSON."""


# ------------------------------------------------------------------ schema
class RawCriterionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    criterion_id: int | None = None
    criterion_name: str | None = None
    score: float | None = None
    max_score: float | None = None
    justification: str = ""
    evidence: str = ""

    @field_validator("criterion_id", mode="before")
    @classmethod
    def _id(cls, v):
        try:
            return int(str(v).strip()) if v is not None and str(v).strip() != "" else None
        except (TypeError, ValueError):
            return None

    @field_validator("score", "max_score", mode="before")
    @classmethod
    def _num(cls, v):
        if v is None or isinstance(v, bool):
            return None
        if isinstance(v, str):
            m = re.search(r"-?\d+(\.\d+)?", v)      # "8/10" -> 8, "seven" -> None
            v = m.group(0) if m else None
        try:
            f = float(v) if v is not None else None
        except (TypeError, ValueError):
            return None
        return f if f is not None and math.isfinite(f) else None

    @field_validator("justification", "evidence", "criterion_name", mode="before")
    @classmethod
    def _text(cls, v):
        if v is None:
            return ""
        if isinstance(v, list):
            return " | ".join(str(x) for x in v)
        return str(v).strip()


class RawScorecard(BaseModel):
    model_config = ConfigDict(extra="ignore")
    supplier_name: str = ""
    criteria: list[RawCriterionResult] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    overall_summary: str = ""

    @field_validator("risks", mode="before")
    @classmethod
    def _risks(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return [str(x) for x in v if str(x).strip()]

    @field_validator("supplier_name", "overall_summary", mode="before")
    @classmethod
    def _s(cls, v):
        return "" if v is None else str(v).strip()


# ------------------------------------------------------------------ parsing
def parse_json(raw: str | dict) -> dict:
    """Accept a dict or a string that may be wrapped in ```json fences or prose."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        raise ParseError("Evaluator returned an empty response.")
    text = re.sub(r"```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ParseError("No JSON object found in evaluator response.")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ParseError(f"Invalid JSON from evaluator: {exc.msg} (line {exc.lineno}).") from exc
    if not isinstance(data, dict):
        raise ParseError("Evaluator JSON root is not an object.")
    return data


# ------------------------------------------------------------------ normalisation
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def validate_scorecard(raw: str | dict, criteria: list[dict], supplier_name: str) -> dict:
    """Return a normalised scorecard dict. Raises ParseError only for unparseable output."""
    data = parse_json(raw)
    warnings: list[str] = []
    tag = f"[{supplier_name}]"

    try:
        card = RawScorecard.model_validate(data)
    except ValidationError as exc:
        warnings.append(f"{tag} Scorecard failed schema validation ({exc.error_count()} error(s)); "
                        "criteria results discarded and treated as missing.")
        card = RawScorecard(supplier_name=str(data.get("supplier_name") or ""),
                            overall_summary=str(data.get("overall_summary") or ""))

    if card.supplier_name and _norm(card.supplier_name) != _norm(supplier_name):
        warnings.append(f"{tag} Evaluator named the supplier '{card.supplier_name}'; "
                        "the user-entered name is used instead.")

    by_id: dict[int, RawCriterionResult] = {}
    active_ids = {int(c["criterion_id"]) for c in criteria}
    name_to_id = {_norm(c["name"]): int(c["criterion_id"]) for c in criteria}

    for item in card.criteria:
        cid = item.criterion_id
        if cid is None and item.criterion_name:          # fall back to name matching
            cid = name_to_id.get(_norm(item.criterion_name))
        if cid is None:
            warnings.append(f"{tag} Dropped a criterion result with no usable id or name.")
            continue
        if cid not in active_ids:
            warnings.append(f"{tag} Dropped result for unknown/inactive criterion_id {cid}.")
            continue
        if cid in by_id:
            warnings.append(f"{tag} Duplicate result for criterion_id {cid}; kept the first one.")
            continue
        by_id[cid] = item

    results = []
    for c in sorted(criteria, key=lambda x: int(x["criterion_id"])):
        cid, max_s, name = int(c["criterion_id"]), float(c["max_score"]), c["name"]
        item = by_id.get(cid)
        flags: list[str] = []
        if item is None:
            score, just, evid = 0.0, "No result returned by the evaluator for this criterion.", ""
            flags.append("MISSING")
            warnings.append(f"{tag} '{name}' missing from evaluator output; scored 0.")
        else:
            just, evid = item.justification, item.evidence
            if item.score is None:
                score = 0.0
                flags.append("INVALID_SCORE")
                warnings.append(f"{tag} '{name}' had a missing/non-numeric score; set to 0.")
            else:
                score = item.score
                if score < 0 or score > max_s:
                    clipped = min(max(score, 0.0), max_s)
                    flags.append("CLIPPED")
                    warnings.append(f"{tag} '{name}' score {score:g} outside 0–{max_s:g}; clipped to {clipped:g}.")
                    score = clipped
            if item.max_score is not None and item.max_score != max_s:
                warnings.append(f"{tag} '{name}' evaluator used max_score {item.max_score:g}; "
                                f"database value {max_s:g} applied.")
            if not evid:
                flags.append("NO_EVIDENCE")
                warnings.append(f"{tag} '{name}' has no supporting evidence quoted.")
            if not just:
                just = "No justification provided."
        results.append({
            "criterion_id": cid, "criterion_name": name,
            "score": round(float(score), 2), "max_score": max_s,
            "justification": just, "evidence": evid, "validation_flags": flags,
        })

    return {
        "supplier_name": supplier_name,
        "criteria": results,
        "risks": card.risks,
        "overall_summary": card.overall_summary or "No summary provided.",
        "warnings": warnings,
    }


def fallback_scorecard(criteria: list[dict], supplier_name: str, reason: str) -> dict:
    """Used when the evaluator output could not be parsed even after a retry."""
    card = validate_scorecard({"supplier_name": supplier_name, "criteria": []}, criteria, supplier_name)
    card["warnings"].insert(0, f"[{supplier_name}] Evaluator output unusable ({reason}); all criteria scored 0.")
    card["overall_summary"] = "Evaluation failed; supplier scored 0 on every criterion pending manual review."
    return card
