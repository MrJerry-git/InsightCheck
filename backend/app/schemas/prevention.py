"""Explicit, dated inputs; unknown is never silently treated as no."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class Visit(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    date: date
    age: int = Field(ge=18, le=100)
    sbp: float = Field(ge=60, le=260)
    total_c: float = Field(gt=0, le=600)
    hdl_c: float = Field(gt=0, le=200)
    chol_unit: Literal["mmol/L", "mg/dL"] = "mmol/L"
    bmi: float = Field(ge=10, le=70)
    egfr: float = Field(gt=0, le=200)
    dm: StrictBool
    smoking: StrictBool
    bp_tx: StrictBool
    statin: StrictBool
    hba1c: float | None = Field(default=None, ge=3, le=20)
    fasting_glucose: float | None = Field(default=None, ge=1, le=40)
    glucose_status: Literal["normal", "prediabetes", "diabetes", "unknown"] = "unknown"

    @model_validator(mode="after")
    def coherent(self):
        if self.hdl_c >= self.total_c:
            raise ValueError("HDL 胆固醇必须小于总胆固醇，请检查单位")
        if self.glucose_status == "diabetes" and not self.dm:
            raise ValueError("已确诊糖尿病时，糖尿病病史不能选择否")
        if self.dm and self.glucose_status in ("normal", "prediabetes"):
            raise ValueError("糖尿病病史与已确认的血糖状态冲突")
        return self


class PreventionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=80)
    sex: Literal["female", "male"]
    known_cvd: StrictBool
    pregnant: StrictBool
    symptomatic: StrictBool
    source: Literal["synthetic", "manual", "public_dataset"]
    source_note: str = Field(min_length=1, max_length=500)
    as_of: date
    visits: list[Visit] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def dated(self):
        if self.as_of > date.today():
            raise ValueError("评估日期不能晚于今天")
        dates = [v.date for v in self.visits]
        if len(set(dates)) != len(dates):
            raise ValueError("同一天只能保留一条已确认记录")
        if max(dates) > self.as_of:
            raise ValueError("检查日期不能晚于评估日期")
        ordered = sorted(self.visits, key=lambda v: v.date)
        for first, second in zip(ordered, ordered[1:], strict=False):
            elapsed = (second.date - first.date).days / 365.2425
            if abs(second.age - first.age - elapsed) > 1.1:
                raise ValueError("历次年龄与检查日期不一致")
            if first.dm and not second.dm:
                raise ValueError("既往糖尿病病史不能因后来指标正常而消失")
        return self
