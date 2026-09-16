"""兼容旧导入路径；新代码使用 app.features.lesion.terminology。"""

from app.features.lesion.terminology import TERMINOLOGY_VERSION, LesionTerminology

__all__ = ["TERMINOLOGY_VERSION", "LesionTerminology"]
