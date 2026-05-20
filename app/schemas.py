from pydantic import BaseModel, Field, field_validator, model_validator


class GenerateRequest(BaseModel):
    template_id: str = Field(min_length=1)
    data: dict[str, str] = Field(default_factory=dict)
    replace: dict[str, str] = Field(default_factory=dict)

    @field_validator("data", "replace")
    @classmethod
    def validate_pairs(cls, val: dict[str, str]) -> dict[str, str]:
        if any(not key.strip() for key in val):
            raise ValueError("keys must not be empty")
        return val

    @model_validator(mode="after")
    def validate_payload(self) -> "GenerateRequest":
        if not self.data and not self.replace:
            raise ValueError("data or replace must not be empty")
        return self


class GenerateResponse(BaseModel):
    file_id: str
    file_url: str
