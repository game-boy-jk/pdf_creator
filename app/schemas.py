from pydantic import BaseModel, Field, field_validator


class GenerateRequest(BaseModel):
    template_id: str = Field(min_length=1)
    data: dict[str, str]

    @field_validator("data")
    @classmethod
    def validate_data(cls, val: dict[str, str]) -> dict[str, str]:
        if not val:
            raise ValueError("data must not be empty")
        return val


class GenerateResponse(BaseModel):
    file_id: str
    file_url: str
