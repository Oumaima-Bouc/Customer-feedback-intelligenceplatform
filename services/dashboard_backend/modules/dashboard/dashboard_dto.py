from pydantic import BaseModel, Field
class TopicsTrendQuery(BaseModel):
    days: int = Field(default=7, ge=1, le=30)
