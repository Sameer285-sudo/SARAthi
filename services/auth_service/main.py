"""Auth service — port 8000."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from shared.db import Base, engine
from shared.models import User  # ensure table created
from auth_service.api.routes import router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="PDS360 Auth Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "auth"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
