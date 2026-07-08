from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import accounts, clients, posts

app = FastAPI(title="LinkedIn Engagement Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(clients.router)
app.include_router(accounts.router)
app.include_router(posts.router)


@app.get("/health")
def health():
    return {"ok": True}
