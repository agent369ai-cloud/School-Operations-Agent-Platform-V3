# app/main.py
import uuid
from fastapi import FastAPI, Request
from app.database import init_db
from app.routers import chat_mock, ingestion

app = FastAPI(title="School Operations Agent Platform")

# Automatically build local database schema tables on boot
@app.on_event("startup")
def on_startup():
    init_db()

# Middleware tracking global correlation IDs for the 9:00 audit timeline demo
@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response

# Include endpoint routes
app.include_router(chat_mock.router, prefix="/api/v1/mock", tags=["Chat Simulator"])
app.include_router(ingestion.router, prefix="/api/v1/ingestion", tags=["Data Ingestion"])

@app.get("/")
def health_check():
    return {"status": "healthy", "service": "school-ops-agent"}
