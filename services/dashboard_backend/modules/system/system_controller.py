from fastapi import APIRouter, Depends, HTTPException
from middleware.auth_middleware import get_current_user, require_editor
from modules.system import system_service as svc

router = APIRouter(tags=["System"])


@router.post("/system/run")
async def trigger_system_run(user: dict = Depends(get_current_user)):
    """Manually run the full chain (scrape -> pipeline). 409 if a run is in progress."""
    require_editor(user)
    result = svc.trigger_run(triggered_by=user.get("username") or str(user.get("sub")))
    if result is None:
        raise HTTPException(status_code=409, detail="A run is already in progress.")
    return result


@router.get("/system/run/status")
async def system_run_status(user: dict = Depends(get_current_user)):
    return svc.get_status()
