import os, uvicorn
if __name__ == "__main__":
    uvicorn.run("app:app", host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8000")), reload=os.environ.get("ENV", "production") == "development", log_level=os.environ.get("LOG_LEVEL", "info").lower())
