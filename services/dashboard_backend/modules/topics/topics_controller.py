from fastapi import APIRouter, Depends, Query
from middleware.auth_middleware import get_current_user
from modules.topics import topics_service as svc
router = APIRouter(tags=["Topics"])
@router.get("/topics/list")
async def topics_list(run_date: str = Query("", description="YYYY-MM-DD or empty for latest"), user: dict = Depends(get_current_user)): return svc.get_topics_list(run_date)
@router.get("/topics")
async def all_topics(user: dict = Depends(get_current_user)): return svc.get_all_topics()
@router.get("/topics/{topic_name}/comments")
async def topic_comments(topic_name: str, cursor: str = Query(""), limit: int = Query(10, ge=1, le=50), user: dict = Depends(get_current_user)): return svc.get_topic_comments(topic_name, cursor, limit)
