#!/usr/bin/env python3
"""Small evidence-chain helpers for ADAM verification reports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EvidenceStep:
    task_id: str
    step: int
    agent: str
    tool: str
    artifact: str
    evidence: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    risk_score: float = 0.0
    quality_scores: dict[str, float] = field(default_factory=dict)
    mode: str = "standard"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "step": self.step,
            "agent": self.agent,
            "tool": self.tool,
            "artifact": self.artifact,
            "evidence": self.evidence,
            "missing": self.missing,
            "risk_score": self.risk_score,
            "quality_scores": self.quality_scores,
            "mode": self.mode,
            "notes": self.notes,
        }


class EvidenceChain:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.steps: list[EvidenceStep] = []

    def add(
        self,
        *,
        agent: str,
        tool: str,
        artifact: str,
        evidence: list[str],
        missing: list[str],
        risk_score: float,
        quality_scores: dict[str, float],
        mode: str = "standard",
        notes: str = "",
    ) -> None:
        self.steps.append(
            EvidenceStep(
                task_id=self.task_id,
                step=len(self.steps) + 1,
                agent=agent,
                tool=tool,
                artifact=artifact,
                evidence=evidence,
                missing=missing,
                risk_score=round(max(0.0, min(1.0, risk_score)), 3),
                quality_scores={key: round(max(0.0, min(1.0, value)), 3) for key, value in quality_scores.items()},
                mode=mode,
                notes=notes,
            )
        )

    def to_list(self) -> list[dict[str, Any]]:
        return [step.to_dict() for step in self.steps]

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_list(), indent=2) + "\n", encoding="utf-8")


def evidence_from_report(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for key, value in data.get("evidence", {}).items():
        if value:
            names.append(key)
    for step in data.get("evidence_chain", []):
        if not step.get("missing"):
            names.extend(str(item) for item in step.get("evidence", []))
    return list(dict.fromkeys(names))
