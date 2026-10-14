from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from middleware.auth_middleware import get_current_user, require_editor
from modules.feedback import feedback_service as svc

router = APIRouter(tags=["Feedback"])


class FeedbackRequest(BaseModel):
    comment_id: str
    new_topic: Optional[str] = None
    new_sentiment: Optional[str] = None


class BulkFeedbackRequest(BaseModel):
    comment_ids: list[str]
    new_topic: Optional[str] = None
    new_sentiment: Optional[str] = None


@router.post("/feedback")
async def submit_feedback(req: FeedbackRequest, user: dict = Depends(get_current_user)):
    """Correct one comment's topic/sentiment (first-writer-wins). Returns {effective_*, locked}."""
    require_editor(user)
    return svc.submit_feedback(req.comment_id, req.new_topic, req.new_sentiment, int(user["sub"]))


@router.post("/feedback/bulk")
async def submit_feedback_bulk(req: BulkFeedbackRequest, user: dict = Depends(get_current_user)):
    """Apply one correction across many comments. Returns {batch_id, applied, skipped}."""
    require_editor(user)
    return svc.submit_feedback_bulk(req.comment_ids, req.new_topic, req.new_sentiment, int(user["sub"]))
