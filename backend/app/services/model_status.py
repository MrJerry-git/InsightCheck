"""T08 × H09：模型任务与制品的真实可用状态。

审核 P2 的问题：只要 ``recommendation_artifact_path`` 非空就显示"制品可加载"，
文件不存在或损坏时也在骗前端。这里把状态拆成四档，并只在真正加载成功后
才算"可加载"：

* ``unconfigured``：未配置路径；
* ``missing_file``：配置了路径但文件不存在；
* ``load_error``：文件存在但加载失败（版本/格式/依赖问题）；
* ``loadable``：实际加载成功（可交给 H09 适配器槽位使用）。

注册表状态（H09 ``ModelTaskRegistry``）单独报告：任务未登记为 integrated 时
即使制品可加载也不算已接入，避免用"文件存在"冒充"模型已接入"。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.ml.tasks import load_builtin_registry

RANKING_TASK_ID = "exam-item-matching-deepfm"


@lru_cache(maxsize=8)
def artifact_status(path: str | None) -> dict[str, Any]:
    """检查推荐制品：配置 / 存在 / 可加载，并给出可核验的说明。"""

    if not path:
        return {
            "state": "unconfigured",
            "configured": False,
            "exists": False,
            "loadable": False,
            "path": None,
            "detail": "未配置制品路径；当前按规则确定性排序，规则推荐不受影响",
        }
    file = Path(path)
    if not file.exists() or not file.is_file():
        return {
            "state": "missing_file",
            "configured": True,
            "exists": False,
            "loadable": False,
            "path": path,
            "detail": "配置了制品路径，但文件不存在，不能按已就绪展示",
        }
    try:
        from app.ml.recommendation.model import DeepFMRecommendationModel

        DeepFMRecommendationModel.load(file)
    except Exception as exc:  # 加载失败必须显式暴露原因类型，不吞掉
        return {
            "state": "load_error",
            "configured": True,
            "exists": True,
            "loadable": False,
            "path": path,
            "detail": f"制品存在但无法加载：{type(exc).__name__}",
        }
    return {
        "state": "loadable",
        "configured": True,
        "exists": True,
        "loadable": True,
        "path": path,
        "detail": "制品已实际加载验证，可交给排序适配器使用",
    }


def model_task_status() -> dict[str, Any]:
    """管理 API 用的模型状态：H09 注册表 + 制品实际状态。"""

    registry = load_builtin_registry()
    artifact = artifact_status(get_settings().recommendation_artifact_path)
    ranking_registration = registry.get(RANKING_TASK_ID)
    availability = registry.availability(RANKING_TASK_ID)
    return {
        "registry_version": registry.VERSION,
        "artifact": artifact,
        "ranking": {
            "task_id": RANKING_TASK_ID,
            "registry_status": (
                ranking_registration.status.value if ranking_registration else "unregistered"
            ),
            "available": availability.available,
            "unavailable_reason": availability.reason,
            "adapter": availability.adapter_name,
        },
    }
