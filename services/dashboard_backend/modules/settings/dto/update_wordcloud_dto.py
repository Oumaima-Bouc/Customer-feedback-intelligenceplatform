from typing import Optional
from pydantic import BaseModel, Field
class UpdateWordcloudDTO(BaseModel):
    max_words: Optional[int] = Field(default=None, ge=1, le=1000)
    min_frequency: Optional[int] = Field(default=None, ge=1, le=1000)
