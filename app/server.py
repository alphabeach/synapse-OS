"""FastAPI app wiring: routers, hardening middleware, static SPA."""
import hmac
import os
import pathlib

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import auth
from app.routes import auth as auth_routes
from app.routes import customs, inventory, quotes

WEB_DIR = pathlib.Path(__file__).resolve().parent.parent / "web"
MAX_BODY = 1024 * 1024  # 1 MB

# No CDNs, no inline script, no inline style: everything is served from /.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)

app = FastAPI(title="Exin Lab Ops", version="0.1.0")

app.include_router(auth_routes.router, prefix="/api")
app.include_router(inventory.router, prefix="/api")
app.include_router(quotes.router, prefix="/api")
app.include_router(customs.router, prefix="/api")


@app.middleware("http")
async def harden(request: Request, call_next):
    # Body cap. Content-Length covers every request the SPA and the tests send;
    # shortcut: a chunked body without Content-Length is not measured here.
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY:
        return JSONResponse({"detail": "request body too large"}, status_code=413)

    # Double-submit CSRF: the header must match the readable cookie. Requests
    # made before login carry no session, so login itself is exempt.
    if request.method in ("POST", "PATCH", "PUT", "DELETE") and request.cookies.get(
        auth.SESSION_COOKIE
    ):
        cookie = request.cookies.get(auth.CSRF_COOKIE) or ""
        header = request.headers.get("x-csrf-token") or ""
        if not cookie or not hmac.compare_digest(cookie, header):
            return JSONResponse(
                {"detail": "CSRF token missing or invalid"}, status_code=403
            )

    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = CSP
    # Buildless SPA with stable filenames: assets must revalidate (cheap 304)
    # so an edited CSS/JS file is picked up on a normal reload. API responses
    # carry user data and are never cached.
    if request.url.path.startswith("/api"):
        response.headers.setdefault("Cache-Control", "no-store")
    else:
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


@app.exception_handler(OverflowError)
async def overflow_handler(request: Request, exc: OverflowError):
    # An integer beyond SQLite's signed 64-bit range is bad input, not a 500.
    return JSONResponse({"detail": "number out of range"}, status_code=400)


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
