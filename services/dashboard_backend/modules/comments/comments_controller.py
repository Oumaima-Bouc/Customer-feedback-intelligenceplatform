from fastapi import APIRouter, Depends, Query
from middleware.auth_middleware import get_current_user
from modules.comments import comments_service as svc
router = APIRouter(tags=["Comments"])
@router.get("/comments")
async def list_comments(cursor: str = Query(""), limit: int = Query(50, ge=1, le=100), source: str = Query(""), sentiment: str = Query(""), topic: str = Query(""), user: dict = Depends(get_current_user)): return svc.list_comments(cursor, limit, source, sentiment, topic)
@router.get("/comments/count")
async def count_comments(source: str = Query(""), sentiment: str = Query(""), topic: str = Query(""), user: dict = Depends(get_current_user)): return svc.count_comments(source, sentiment, topic)
