from pydantic import BaseModel, ConfigDict


class PipelineVersions(BaseModel):
    """核心输出的版本集合；未运行的模块使用 None，而不是伪造版本。"""

    model_config = ConfigDict(frozen=True)

    feature_pipeline_version: str | None = None
    risk_model_version: str | None = None
    recommendation_model_version: str | None = None
    rule_version: str | None = None
    llm_model: str | None = None
