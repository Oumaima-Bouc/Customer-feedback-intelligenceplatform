from fastapi import APIRouter
from fastapi.responses import JSONResponse
from config.database import check_connectivity as db_ok
from infrastructure.consul.consul_client import consul_client
router = APIRouter(tags=["Health"])
@router.get("/health")
async def health():
    checks = {"alive": True, "consul_connected": consul_client.check_connectivity(), "db_connected": db_ok()}
    ok = all(checks.values())
    return JSONResponse(status_code=200 if ok else 503, content={"status": "healthy" if ok else "degraded", "checks": checks})
