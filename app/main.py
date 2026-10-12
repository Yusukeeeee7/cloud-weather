from fastapi import FastAPI

from app.routers import health

app = FastAPI(title="cloud-weather")
app.include_router(health.router)
