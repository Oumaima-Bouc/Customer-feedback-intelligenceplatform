from pydantic import BaseModel, field_validator, model_validator


class UpdatePasswordDTO(BaseModel):
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @model_validator(mode="after")
    def not_same_as_old(self) -> "UpdatePasswordDTO":
        if self.new_password == self.old_password:
            raise ValueError("New password must be different from the current password")
        return self
