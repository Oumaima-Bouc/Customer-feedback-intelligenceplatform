from typing import Any, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from middleware.auth_middleware import get_current_user, require_editor
from modules.replies import replies_service as svc

router = APIRouter(tags=["Replies"])


class SubmitReplyRequest(BaseModel):
    reply_text: str
    comment_ids: Optional[list[str]] = None
    filter: Optional[dict[str, Any]] = None
    select_all_matching: bool = False


@router.post("/replies")
async def submit_reply(req: SubmitReplyRequest, user: dict = Depends(get_current_user)):
    """Queue a Group Reply campaign. Never sends inline (R1) — returns an ack with an ETA."""
    require_editor(user)
    return svc.submit_campaign(
        req.reply_text, req.comment_ids, req.filter, req.select_all_matching, int(user["sub"])
    )


@router.get("/replies")
async def list_replies(limit: int = Query(50, ge=1, le=200), user: dict = Depends(get_current_user)):
    return svc.list_campaigns(limit)


@router.get("/replies/{campaign_id}")
async def get_reply(campaign_id: int, user: dict = Depends(get_current_user)):
    return svc.get_campaign(campaign_id)
