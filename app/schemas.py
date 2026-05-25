from pydantic import BaseModel, Field, field_validator


class GenerateRequest(BaseModel):
    template_id: str = Field(min_length=1)
    data: dict[str, str] = Field(min_length=1)  # min_length=1 заменяет model_validator

    @field_validator("data")
    @classmethod
    def validate_keys(cls, val: dict[str, str]) -> dict[str, str]:
        if any(not key.strip() for key in val):
            raise ValueError("keys must not be empty")
        return val


class GenerateResponse(BaseModel):
    file_id: str
    file_url: str