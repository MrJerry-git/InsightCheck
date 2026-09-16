from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]
    service: str
    version: str
    environment: str
