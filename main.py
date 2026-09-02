from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from core.infra.config import APP_NAME, ensure_dirs
from core.infra.csrf import CSRFMiddleware
from core.infra.security_headers import SecurityHeadersMiddleware
from core.infra.demo_session import DemoSessionMiddleware
from routers import listings_api, pages, photos, public
from core.infra.deps import RedirectToLogin

ensure_dirs()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from core.infra.db import init_db
    init_db()
    yield

app = FastAPI(title=APP_NAME, lifespan=lifespan)


@app.exception_handler(RedirectToLogin)
async def _redirect_to_login(request, exc):
    return RedirectResponse(url="/logowanie", status_code=303)


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(DemoSessionMiddleware)

app.mount("/static", StaticFiles(directory="static"), name="static")
# No public /photos mount - photos are private (SPEC §13), served only
# through routers.photos with an ownership check.

app.include_router(public.router)
app.include_router(photos.router)
app.include_router(pages.router)
app.include_router(listings_api.router)
