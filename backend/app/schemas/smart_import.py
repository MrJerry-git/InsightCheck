"""Incomplete extraction is a draft, never a valid clinical assessment."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from app.schemas.prevention import Visit


class StrictDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


DraftVisit = create_model(
    "DraftVisit", __base__=StrictDraft,
    **{name: (Annotated[field.annotation | None, *field.metadata, Field()], None)
       for name, field in Visit.model_fields.items()},
)


class Evidence(StrictDraft):
    path: str = Field(max_length=100)
    quote: str = Field(min_length=1, max_length=600)


class Extracted(StrictDraft):
    sex: Literal["female", "male"] | None = None
    known_cvd: bool | None = None
    pregnant: bool | None = None
    symptomatic: bool | None = None
    visits: list[DraftVisit] = Field(min_length=1, max_length=10)
    evidence: list[Evidence] = Field(default_factory=list, max_length=200)
    warnings: list[Annotated[str, Field(max_length=500)]] = Field(
        default_factory=list, max_length=30)


class ImportFile(StrictDraft):
    name: str = Field(min_length=1, max_length=150)
    content: str = Field(max_length=11_200_000)


class ImportRequest(StrictDraft):
    text: str = Field(default="", max_length=16000)
    file: ImportFile | None = None


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]
    # Validated with the existing assessment schema after explicit confirmation.
    intake: dict
