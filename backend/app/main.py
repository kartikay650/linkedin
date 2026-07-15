from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth import require_user
from app.routers import analytics, clients, creators, cron, posts, webhooks

app = FastAPI(title="LinkedIn Engagement Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Protected routes require a valid Supabase session. CORSMiddleware wraps the app,
# so a 401 from the dependency still carries CORS headers (the browser sees the 401,
# not a CORS error). The webhook router is excluded — it uses its own shared secret.
_auth = [Depends(require_user)]
app.include_router(clients.router, dependencies=_auth)
app.include_router(posts.router, dependencies=_auth)
app.include_router(creators.router, dependencies=_auth)
app.include_router(analytics.router, dependencies=_auth)
app.include_router(webhooks.router)
app.include_router(cron.router)  # own secret (Vercel Cron bearer), no user auth


@app.get("/health")
def health():
    return {"ok": True}
