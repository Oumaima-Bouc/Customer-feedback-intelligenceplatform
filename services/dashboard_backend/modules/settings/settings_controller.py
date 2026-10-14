from typing import Any, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from middleware.auth_middleware import get_current_user, require_admin, require_editor
from modules.settings import settings_service as svc
from modules.settings.dto.update_schedule_dto import UpdateScheduleDTO
from modules.settings.dto.update_wordcloud_dto import UpdateWordcloudDTO
router = APIRouter(tags=["Settings"])
class ConfigUpdateRequest(BaseModel): settings: dict[str, Any]
class ScraperSettingsUpdateRequest(BaseModel):
    interval_hours: Optional[int] = Field(default=None, ge=1, le=24)
    stagger_seconds: Optional[int] = Field(default=None, ge=0, le=600)
@router.get("/config/versions")
async def config_versions(user: dict = Depends(get_current_user)): return svc.get_config_versions()
@router.get("/restart-status")
async def restart_status(user: dict = Depends(get_current_user)): return svc.get_restart_status()
@router.get("/config/{service_name}")
async def get_config(service_name: str, user: dict = Depends(get_current_user)): require_editor(user); return svc.get_service_config(service_name)
@router.put("/config/{service_name}")
async def update_config(service_name: str, request: ConfigUpdateRequest, user: dict = Depends(get_current_user)): require_admin(user); return svc.update_service_config(service_name, request.settings)
@router.get("/services/health")
async def services_health(user: dict = Depends(get_current_user)): return await svc.get_all_services_health()
class SourceCreateRequest(BaseModel): platform: str; external_id: str; access_token: str; name: Optional[str] = None
class SourceUpdateRequest(BaseModel): is_active: Optional[bool] = None; name: Optional[str] = None; access_token: Optional[str] = None
@router.get("/sources")
async def list_sources(user: dict = Depends(get_current_user)): return svc.list_sources()
@router.post("/sources")
async def create_source(req: SourceCreateRequest, user: dict = Depends(get_current_user)): require_editor(user); return svc.create_source(req.platform, req.external_id, req.access_token, req.name)
@router.put("/sources/{source_id}")
async def update_source(source_id: int, req: SourceUpdateRequest, user: dict = Depends(get_current_user)): require_editor(user); return svc.update_source(source_id, req.is_active, req.name, req.access_token)
@router.delete("/sources/{source_id}")
async def delete_source(source_id: int, user: dict = Depends(get_current_user)): require_admin(user); return svc.delete_source(source_id)
@router.get("/sources/{source_id}/health")
async def source_health(source_id: int, user: dict = Depends(get_current_user)): return svc.get_source_health(source_id)
@router.post("/sources/{source_id}/refresh")
async def refresh_source(source_id: int, user: dict = Depends(get_current_user)): require_editor(user); return svc.refresh_source(source_id)
@router.get("/scraper/settings")
async def scraper_settings(user: dict = Depends(get_current_user)): return svc.get_scraper_settings()
@router.put("/scraper/settings")
async def update_scraper_settings(req: ScraperSettingsUpdateRequest, user: dict = Depends(get_current_user)): require_editor(user); return svc.update_scraper_settings(req)
@router.get("/settings/pipeline")
async def get_pipeline_settings(user: dict = Depends(get_current_user)): return svc.get_pipeline_settings()
@router.put("/settings/pipeline")
async def update_pipeline_settings(req: UpdateScheduleDTO, user: dict = Depends(get_current_user)): require_editor(user); return svc.update_pipeline_settings(req)
@router.post("/settings/pipeline/validate-cron")
async def validate_cron(req: dict, user: dict = Depends(get_current_user)): return svc.validate_cron(req.get("cron", ""))
class WordAddRequest(BaseModel): word: str
@router.get("/word-cloud/settings")
async def get_wordcloud_settings(user: dict = Depends(get_current_user)): return svc.get_wordcloud_settings()
@router.put("/word-cloud/settings")
async def update_wordcloud_settings(req: UpdateWordcloudDTO, user: dict = Depends(get_current_user)): require_editor(user); return svc.update_wordcloud_settings(req)
@router.post("/word-cloud/words")
async def add_word(req: WordAddRequest, user: dict = Depends(get_current_user)): require_editor(user); return svc.add_word(req.word)
@router.delete("/word-cloud/words/{word}")
async def remove_word(word: str, user: dict = Depends(get_current_user)): require_editor(user); return svc.remove_word(word)
@router.put("/word-cloud/words/{word}/hide")
async def hide_word(word: str, user: dict = Depends(get_current_user)): require_editor(user); return svc.hide_word(word)
class CreateUserRequest(BaseModel): username: str; email: str; password: str; role: str = "user"
class UpdateUserRequest(BaseModel): username: Optional[str] = None; email: Optional[str] = None; role: Optional[str] = None; is_active: Optional[bool] = None
@router.get("/users")
async def list_users(user: dict = Depends(get_current_user)): require_admin(user); return svc.list_users()
@router.post("/users")
async def create_user(req: CreateUserRequest, user: dict = Depends(get_current_user)): require_admin(user); return svc.create_user(req.username, req.email, req.password, req.role)
@router.put("/users/{user_id}")
async def update_user(user_id: int, req: UpdateUserRequest, user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        if int(user.get("sub", 0)) != user_id or req.role is not None or req.is_active is not None:
            require_admin(user)
    return svc.update_user(user_id, req.role, req.is_active, req.username, req.email)
@router.delete("/users/{user_id}")
async def delete_user(user_id: int, user: dict = Depends(get_current_user)): require_admin(user); return svc.delete_user(user_id)
