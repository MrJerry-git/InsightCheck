"""发现到候选检查项目的映射（T05 的配置来源）。

映射是工程配置，不是医学结论：每条都带来源与版本；H02 的检查—发现—疾病目录接入后
由该目录替换本文件。目录里不存在的项目不会凭空生成候选，只记录为“目录缺少项目”。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

MAP_PATH = Path(__file__).resolve().parents[2] / "data" / "analysis_finding_map.json"


@dataclass(frozen=True)
class FindingRule:
    finding_code: str
    name: str
    system: str
    severity: str
    metric_codes: tuple[str, ...]
    directions: tuple[str, ...]
    lesion_keywords: tuple[str, ...]
    exam_codes: tuple[str, ...]
    relation_type: str
    note: str


@dataclass(frozen=True)
class FindingMap:
    version: str
    source: str
    rules: tuple[FindingRule, ...]

    def for_metric(self, metric_code: str) -> tuple[FindingRule, ...]:
        return tuple(rule for rule in self.rules if metric_code in rule.metric_codes)

    def for_lesion(self, text: str) -> tuple[FindingRule, ...]:
        lowered = text.lower()
        return tuple(
            rule
            for rule in self.rules
            if any(keyword.lower() in lowered for keyword in rule.lesion_keywords)
        )

    def rule(self, finding_code: str) -> FindingRule | None:
        for rule in self.rules:
            if rule.finding_code == finding_code:
                return rule
        return None


@lru_cache
def load_finding_map(path: Path | None = None) -> FindingMap:
    payload = json.loads((path or MAP_PATH).read_text(encoding="utf-8"))
    rules = tuple(
        FindingRule(
            finding_code=entry["finding_code"],
            name=entry["name"],
            system=entry["system"],
            severity=entry.get("severity", "unknown"),
            metric_codes=tuple(entry.get("match", {}).get("metric_codes", ())),
            directions=tuple(entry.get("match", {}).get("directions", ())),
            lesion_keywords=tuple(entry.get("match", {}).get("lesion_keywords", ())),
            exam_codes=tuple(entry.get("exam_codes", ())),
            relation_type=entry.get("relation_type", "复查"),
            note=entry.get("note", ""),
        )
        for entry in payload["entries"]
    )
    return FindingMap(version=payload["version"], source=payload["source"], rules=rules)
