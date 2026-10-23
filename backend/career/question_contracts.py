"""Current question constraints; archived advice never owns these values."""

import hashlib
import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=8000)]
Positive = Annotated[int, Field(strict=True, gt=0, le=100000)]
Family = Literal["JOB_COMPETENCY", "MOTIVATION", "COLLABORATION", "CHALLENGE",
                 "STRENGTH_WEAKNESS", "VALUES", "OTHER"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def normalized(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


class LengthPolicy(Contract):
    maximum: Positive
    minimum: Annotated[int, Field(strict=True, ge=0)] | None = None
    unit: Literal["CHARACTERS", "BYTES"] = "CHARACTERS"
    spaces: Literal["INCLUDED", "EXCLUDED", "UNKNOWN"] = "UNKNOWN"
    newlines: Literal["INCLUDED", "EXCLUDED", "UNKNOWN"] = "UNKNOWN"
    title: Literal["INCLUDED", "EXCLUDED", "UNKNOWN"] = "UNKNOWN"
    encoding: Literal["UTF-8", "EUC-KR", "UNKNOWN"] = "UNKNOWN"

    @model_validator(mode="after")
    def bounds(self):
        if self.minimum is not None and self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        return self

    @property
    def needs_confirmation(self) -> bool:
        return "UNKNOWN" in (self.spaces, self.newlines, self.title) or (
            self.unit == "BYTES" and self.encoding == "UNKNOWN")


class QuestionContract(Contract):
    application_id: Text
    question_id: Text
    version: Positive = 1
    company: Text
    role: Text
    raw_text: Text
    # Supplied from the current question, never inferred from a retrieved guide.
    required_demands: tuple[Text, ...] = ()
    excluded_topics: tuple[Text, ...] = ()
    length: LengthPolicy
    verified_status: Literal["UNCONFIRMED", "USER_CONFIRMED"] = "UNCONFIRMED"

    @property
    def revision(self) -> str:
        return fingerprint(self.model_dump(mode="json"))
