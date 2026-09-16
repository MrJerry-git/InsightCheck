import re
import unicodedata

from app.features.lesion.schemas import LesionTerminologyResult

TERMINOLOGY_VERSION = "lesion-terminology-v2"


def term_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().upper()
    return re.sub(r"\s+", "", normalized)


class LesionTerminology:
    """只统一结构化病灶术语，不推断病灶身份。"""

    _LOCATION_ALIASES = {
        term_key("右上肺"): "RIGHT_UPPER_LOBE",
        term_key("右肺上叶"): "RIGHT_UPPER_LOBE",
        term_key("RUL"): "RIGHT_UPPER_LOBE",
        term_key("RIGHT_UPPER_LOBE"): "RIGHT_UPPER_LOBE",
        term_key("右下肺"): "RIGHT_LOWER_LOBE",
        term_key("右肺下叶"): "RIGHT_LOWER_LOBE",
        term_key("RLL"): "RIGHT_LOWER_LOBE",
        term_key("RIGHT_LOWER_LOBE"): "RIGHT_LOWER_LOBE",
    }
    _LOCATION_LABELS = {
        "RIGHT_UPPER_LOBE": "右肺上叶",
        "RIGHT_LOWER_LOBE": "右肺下叶",
    }
    _LOCATION_ORGANS = {
        "RIGHT_UPPER_LOBE": "LUNG",
        "RIGHT_LOWER_LOBE": "LUNG",
    }
    _LESION_TYPE_ALIASES = {
        term_key("肺结节"): "PULMONARY_NODULE",
        term_key("PULMONARY_NODULE"): "PULMONARY_NODULE",
        term_key("DEMO_PULMONARY_NODULE"): "PULMONARY_NODULE",
        term_key("DEMO_LONGITUDINAL_PULMONARY_NODULE"): "PULMONARY_NODULE",
    }
    _ORGAN_ALIASES = {
        term_key("肺"): "LUNG",
        term_key("右肺"): "LUNG",
        term_key("左肺"): "LUNG",
        term_key("LUNG"): "LUNG",
    }
    _BODY_PART_ALIASES = {
        term_key("胸部"): "CHEST",
        term_key("CHEST"): "CHEST",
    }

    def normalize_location(self, location: str) -> LesionTerminologyResult:
        canonical = self._LOCATION_ALIASES.get(term_key(location))
        return LesionTerminologyResult(
            original_location=location,
            canonical_location=canonical,
            matched=canonical is not None,
            terminology_version=TERMINOLOGY_VERSION,
        )

    def normalize_lesion_type(self, lesion_type: str) -> str:
        return self._LESION_TYPE_ALIASES.get(term_key(lesion_type), term_key(lesion_type))

    def normalize_organ(self, organ: str | None, location: str | None = None) -> str | None:
        if organ:
            return self._ORGAN_ALIASES.get(term_key(organ), term_key(organ))
        if location:
            canonical = self.normalize_location(location).canonical_location
            return self._LOCATION_ORGANS.get(canonical or "")
        return None

    def normalize_body_part(self, body_part: str | None) -> str | None:
        if not body_part:
            return None
        return self._BODY_PART_ALIASES.get(term_key(body_part), term_key(body_part))

    def display_location(self, canonical_location: str) -> str:
        return self._LOCATION_LABELS.get(canonical_location, canonical_location)
