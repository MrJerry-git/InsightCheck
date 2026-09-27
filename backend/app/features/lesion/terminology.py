"""病灶术语归一：内置肺部词表 + 可配置多部位扩展（H06）。

默认行为与 lesion-terminology-v2 完全一致；新部位（甲状腺、肝、肾、
乳腺等）通过 :class:`LesionSiteConfig` 注入，不修改代码。跨部位永不
强制关联：部位归一只在本部位内进行，不做部位间推断。
"""

import json
import re
import unicodedata
from pathlib import Path

from pydantic import BaseModel, Field

from app.features.lesion.schemas import LesionTerminologyResult

TERMINOLOGY_VERSION = "lesion-terminology-v2"

DATA_DIR = Path(__file__).parent / "data"


def term_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().upper()
    return re.sub(r"\s+", "", normalized)


class LesionSiteConfig(BaseModel):
    """多部位术语配置：别名 → 规范编码，附器官归属与展示名。"""

    version: str = "lesion-terminology-sites-v1"
    location_aliases: dict[str, str] = Field(default_factory=dict)
    location_labels: dict[str, str] = Field(default_factory=dict)
    location_organs: dict[str, str] = Field(default_factory=dict)
    lesion_type_aliases: dict[str, str] = Field(default_factory=dict)
    organ_aliases: dict[str, str] = Field(default_factory=dict)
    body_part_aliases: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def load_builtin(cls) -> "LesionSiteConfig":
        path = DATA_DIR / "multisite_terminology.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls.model_validate(payload)


class LesionTerminology:
    """只统一结构化病灶术语，不推断病灶身份。"""

    _DEFAULT_LOCATION_ALIASES = {
        term_key("右上肺"): "RIGHT_UPPER_LOBE",
        term_key("右肺上叶"): "RIGHT_UPPER_LOBE",
        term_key("RUL"): "RIGHT_UPPER_LOBE",
        term_key("RIGHT_UPPER_LOBE"): "RIGHT_UPPER_LOBE",
        term_key("右下肺"): "RIGHT_LOWER_LOBE",
        term_key("右肺下叶"): "RIGHT_LOWER_LOBE",
        term_key("RLL"): "RIGHT_LOWER_LOBE",
        term_key("RIGHT_LOWER_LOBE"): "RIGHT_LOWER_LOBE",
    }
    _DEFAULT_LOCATION_LABELS = {
        "RIGHT_UPPER_LOBE": "右肺上叶",
        "RIGHT_LOWER_LOBE": "右肺下叶",
    }
    _DEFAULT_LOCATION_ORGANS = {
        "RIGHT_UPPER_LOBE": "LUNG",
        "RIGHT_LOWER_LOBE": "LUNG",
    }
    _DEFAULT_LESION_TYPE_ALIASES = {
        term_key("肺结节"): "PULMONARY_NODULE",
        term_key("PULMONARY_NODULE"): "PULMONARY_NODULE",
        term_key("DEMO_PULMONARY_NODULE"): "PULMONARY_NODULE",
        term_key("DEMO_LONGITUDINAL_PULMONARY_NODULE"): "PULMONARY_NODULE",
    }
    _DEFAULT_ORGAN_ALIASES = {
        term_key("肺"): "LUNG",
        term_key("右肺"): "LUNG",
        term_key("左肺"): "LUNG",
        term_key("LUNG"): "LUNG",
    }
    _DEFAULT_BODY_PART_ALIASES = {
        term_key("胸部"): "CHEST",
        term_key("CHEST"): "CHEST",
    }

    def __init__(self, site_config: LesionSiteConfig | None = None) -> None:
        """site_config 提供扩展部位；默认仅内置肺部词表（向后兼容）。"""
        config = site_config or LesionSiteConfig()
        self._location_aliases = {**self._DEFAULT_LOCATION_ALIASES}
        self._location_labels = {**self._DEFAULT_LOCATION_LABELS}
        self._location_organs = {**self._DEFAULT_LOCATION_ORGANS}
        self._lesion_type_aliases = {**self._DEFAULT_LESION_TYPE_ALIASES}
        self._organ_aliases = {**self._DEFAULT_ORGAN_ALIASES}
        self._body_part_aliases = {**self._DEFAULT_BODY_PART_ALIASES}

        for alias, canonical in config.location_aliases.items():
            key = term_key(alias)
            if key in self._location_aliases and self._location_aliases[key] != canonical:
                raise ValueError(
                    f"部位别名冲突：{alias} 已映射到 {self._location_aliases[key]}"
                )
            self._location_aliases[key] = canonical
        self._location_labels.update(config.location_labels)
        self._location_organs.update(config.location_organs)
        self._lesion_type_aliases.update(
            {term_key(k): v for k, v in config.lesion_type_aliases.items()}
        )
        self._organ_aliases.update(
            {term_key(k): v for k, v in config.organ_aliases.items()}
        )
        self._body_part_aliases.update(
            {term_key(k): v for k, v in config.body_part_aliases.items()}
        )
        self.site_config_version = config.version

    @property
    def multisite_enabled(self) -> bool:
        """是否注册了肺以外的器官（用于展示与测试）。"""
        return any(organ != "LUNG" for organ in self._location_organs.values())

    def organs(self) -> list[str]:
        return sorted(set(self._location_organs.values()))

    def normalize_location(self, location: str) -> LesionTerminologyResult:
        canonical = self._location_aliases.get(term_key(location))
        return LesionTerminologyResult(
            original_location=location,
            canonical_location=canonical,
            matched=canonical is not None,
            terminology_version=TERMINOLOGY_VERSION,
        )

    def normalize_lesion_type(self, lesion_type: str) -> str:
        return self._lesion_type_aliases.get(term_key(lesion_type), term_key(lesion_type))

    def normalize_organ(self, organ: str | None, location: str | None = None) -> str | None:
        if organ:
            return self._organ_aliases.get(term_key(organ), term_key(organ))
        if location:
            canonical = self.normalize_location(location).canonical_location
            return self._location_organs.get(canonical or "")
        return None

    def normalize_body_part(self, body_part: str | None) -> str | None:
        if not body_part:
            return None
        return self._body_part_aliases.get(term_key(body_part), term_key(body_part))

    def display_location(self, canonical_location: str) -> str:
        return self._location_labels.get(canonical_location, canonical_location)
