from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import Base, SessionLocal, engine
from app.models import User, UserInterest, RecommendationRecord
from app.integrations.demo import DemoKohaClient, BOOKS, LOANS, HISTORY
from app.integrations.koha import KohaClient, KohaError
from app.services import recommendations, analytics, hydrate
from app.recommendations import CONTRACT_VERSION, HAS_LIGHTFM, ContractError, recommend, resolve_backend
from app.integrations import koha as koha_adapter

Base.metadata.create_all(bind=engine)
if settings.demo_mode:
    with SessionLocal() as db:
        if not db.scalar(select(User).where(User.koha_borrower_id == "DEMO-1042")):
            db.add(User(name="Alex Morgan", email="alex@example.test", koha_borrower_id="DEMO-1042"))
            db.commit()

app = FastAPI(title=settings.app_name, version="0.1.0")
cors_origins = {origin.strip().rstrip("/") for origin in [settings.frontend_origin, *settings.frontend_origins.split(",")] if origin.strip()}
# Browsers treat localhost and 127.0.0.1 as different origins. Permit both for
# local development while keeping deployed origins explicitly configured.
if settings.app_env.casefold() == "development":
    if "http://localhost:5173" in cors_origins:
        cors_origins.add("http://127.0.0.1:5173")
    if "http://127.0.0.1:5173" in cors_origins:
        cors_origins.add("http://localhost:5173")
app.add_middleware(CORSMiddleware, allow_origins=sorted(cors_origins), allow_credentials=True, allow_methods=["GET", "POST", "PUT", "OPTIONS"], allow_headers=["*"])
if settings.app_session_secret:
    app.add_middleware(SessionMiddleware, secret_key=settings.app_session_secret, session_cookie="portal_session", same_site="lax", https_only=settings.session_cookie_secure, max_age=60 * 60 * 24 * 14)
koha = DemoKohaClient() if settings.demo_mode else None


def integration():
    if settings.demo_mode: return koha
    base = settings.koha_base_url.rstrip("/") + "/" + settings.koha_api_prefix.strip("/")
    return KohaClient(base, settings.koha_auth_method, settings.koha_client_id, settings.koha_client_secret, settings.koha_basic_username, settings.koha_basic_password, settings.koha_api_token, settings.koha_token_path)


def capability_error(exc):
    raise HTTPException(status_code=exc.status_code, detail=str(exc))


def include_catalogue_link(book: dict):
    book_id = str(book.get("id", ""))
    if not settings.demo_mode and settings.koha_opac_url and book_id.isdigit():
        book["catalogue_url"] = f"{settings.koha_opac_url.rstrip('/')}/cgi-bin/koha/opac-detail.pl?biblionumber={book_id}"
    return book


@app.post(settings.api_prefix + "/auth/login")
async def login(request: Request, payload: dict):
    if settings.demo_mode:
        raise HTTPException(400, "Sign-in is disabled in demo mode")
    if not settings.app_session_secret:
        raise HTTPException(503, "Portal sessions are not configured. Set APP_SESSION_SECRET in backend/.env and restart the backend.")
    identifier = str(payload.get("identifier", "")).strip()
    password = payload.get("password")
    if not identifier or not isinstance(password, str) or not password or len(identifier) > 255 or len(password) > 1024:
        raise HTTPException(422, "Enter your library username or card number and password")
    try:
        patron = await integration().validate_patron_password(identifier, password)
    except KohaError as exc:
        capability_error(exc)
    request.session.clear()
    request.session["patron_id"] = patron["patron_id"]
    request.session["userid"] = patron["userid"]
    return {"signed_in": True, "userid": patron["userid"]}


@app.get(settings.api_prefix + "/auth/me")
def auth_me(request: Request):
    patron_id = request.session.get("patron_id") if "portal_session" in request.cookies else None
    if not patron_id:
        raise HTTPException(401, "Sign in with your library account to continue")
    return {"signed_in": True, "userid": request.session.get("userid", "")}


@app.post(settings.api_prefix + "/auth/logout")
def logout(request: Request, response: Response):
    if settings.app_session_secret:
        request.session.clear()
    response.delete_cookie("portal_session", httponly=True, secure=settings.session_cookie_secure, samesite="lax")
    return {"signed_in": False}


@app.get(settings.api_prefix + "/health")
def health(): return {"status":"ok", "mode":"demo" if settings.demo_mode else "live", "app":settings.app_name}


@app.get(settings.api_prefix + "/koha/health")
async def koha_health():
    if settings.demo_mode: return {"status":"demo", "message":"Sample data is active; no live Koha connection is made."}
    try:
        await integration().search_catalogue(page=1, page_size=1)
        return {"status":"connected", "message":"Authenticated Koha catalogue API is responding."}
    except KohaError as exc:
        capability_error(exc)


@app.get(settings.api_prefix + "/dashboard")
async def dashboard(request: Request):
    if settings.demo_mode:
        return {"patron":{"name":"Alex Morgan","card":"•••• 1042","joined":"2021"},"loans":LOANS,"history":HISTORY[:3],"recommendations":await personal_recommendations(request, 3),"analytics":analytics(),"source":"demo"}
    patron_id = request.session.get("patron_id")
    if not patron_id:
        raise HTTPException(401, "Sign in with your library account to load your dashboard")
    try:
        client = integration()
        current = await client.get_current_checkouts(str(patron_id))
        try:
            history = await client.get_history(str(patron_id))
        except KohaError:
            # Keep the live loan dashboard useful when history access is not
            # enabled; the dedicated history endpoint still reports the error.
            history = []
    except KohaError as exc:
        capability_error(exc)
    overdue = sum(loan["status"] == "Overdue" for loan in current)
    try: picks = await personal_recommendations(request, 3)
    except HTTPException: picks = []  # loans stay useful even if ranking input is unavailable
    return {
        "patron":{"name":request.session.get("userid") or "Library member","card":"","joined":""},
        "loans":current,"history":history[:8],"recommendations":picks,
        "analytics":{"borrowed_period":len(history),"active_loans":len(current),"overdue":overdue,"returned":len(history),"subjects":[],"trend":[]},
        "source":"koha",
    }


@app.get(settings.api_prefix + "/catalogue")
async def catalogue(q: str = "", subject: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(12, ge=1, le=50)):
    try:
        result = await integration().search_catalogue(q, subject, page, page_size)
        result["items"] = [include_catalogue_link(item) for item in result["items"]]
        return {**result,"source":"demo" if settings.demo_mode else "koha"}
    except KohaError as e: capability_error(e)


@app.get(settings.api_prefix + "/catalogue/{book_id}")
async def book(book_id: str):
    try: return include_catalogue_link(await integration().get_book(book_id))
    except KohaError as e: capability_error(e)


@app.get(settings.api_prefix + "/catalogue/{book_id}/items")
async def book_items(book_id: str):
    try:
        items = await integration().get_book_items(book_id)
        return {"items":items,"total":len(items),"source":"demo" if settings.demo_mode else "koha"}
    except KohaError as e: capability_error(e)


@app.get(settings.api_prefix + "/borrowing/history")
async def borrowing_history(request: Request):
    if settings.demo_mode: return {"items":HISTORY,"source":"demo"}
    patron_id = request.session.get("patron_id")
    if not patron_id: raise HTTPException(401, "Sign in with your library account to view checkout history")
    try: return {"items":await integration().get_history(str(patron_id)),"source":"koha"}
    except KohaError as exc: capability_error(exc)


@app.get(settings.api_prefix + "/borrowing/current")
async def borrowing_current(request: Request):
    if settings.demo_mode: return {"items":LOANS,"source":"demo"}
    patron_id = request.session.get("patron_id")
    if not patron_id: raise HTTPException(401, "Sign in with your library account to view current loans")
    try: return {"items":await integration().get_current_checkouts(str(patron_id)),"source":"koha"}
    except KohaError as exc: capability_error(exc)


# Resolved once at startup so RECOMMENDER_BACKEND=lightfm fails fast when LightFM is missing.
RECOMMENDER = resolve_backend(settings.recommender_backend)


def _portal_user(db: Session, borrower_id: str):
    return db.scalar(select(User).where(User.koha_borrower_id == borrower_id))


def _saved_interests(borrower_id: str) -> list[str]:
    with SessionLocal() as db:
        user = _portal_user(db, borrower_id)
        return list(db.scalars(select(UserInterest.subject).where(UserInterest.user_id == user.id)).all()) if user else []


def _store_recommendations(borrower_id: str, rows: list[dict]):
    """Keep the latest generated list per portal user (audit/debug; not read back for ranking)."""
    with SessionLocal() as db:
        user = _portal_user(db, borrower_id)
        if user is None: return
        db.query(RecommendationRecord).filter_by(user_id=user.id).delete()
        db.add_all([RecommendationRecord(user_id=user.id, book_id=str(r["id"]), score=float(r["score"]), reason=r["reason"], strategy=r["strategy"]) for r in rows])
        db.commit()


def _display_book(entry: dict) -> dict:
    labels = {"available": "Available", "unavailable": "On loan"}
    return include_catalogue_link({"id": entry["book_id"], "title": entry["title"], "authors": entry.get("authors") or [], "subjects": (entry.get("subjects") or []) + (entry.get("genres") or []), "year": entry.get("publication_year"), "description": entry.get("description") or "", "availability": labels.get(entry.get("availability"), "Unknown"), "copies": None, "source": "koha"})


async def personal_recommendations(request: Request, limit: int) -> list[dict]:
    if settings.demo_mode:
        rows = recommendations(limit, _saved_interests("DEMO-1042"), RECOMMENDER)
        _store_recommendations("DEMO-1042", rows)
        return rows
    patron_id = request.session.get("patron_id")
    if not patron_id: raise HTTPException(401, "Sign in with your library account to get personal recommendations")
    client = integration()
    try:
        snapshot = await client.build_recommendation_snapshot(str(patron_id), _saved_interests(str(patron_id)))
        rows = hydrate(recommend(snapshot, limit, backend=RECOMMENDER), [_display_book(e) for e in snapshot["catalogue"]])
    except KohaError as exc: capability_error(exc)
    except ContractError as exc: raise HTTPException(502, f"Recommendation input was invalid: {exc}")
    _store_recommendations(str(patron_id), rows)
    return rows


@app.get(settings.api_prefix + "/recommendations")
async def get_recommendations(request: Request):
    return {"items": await personal_recommendations(request, 8), "source": "demo" if settings.demo_mode else "koha", "engine": RECOMMENDER}


@app.get(settings.api_prefix + "/recommendations/status")
def recommendation_status():
    return {"engine": RECOMMENDER, "configured": settings.recommender_backend, "lightfm_installed": HAS_LIGHTFM, "contract_version": CONTRACT_VERSION}


@app.post(settings.api_prefix + "/recommendations/refresh")
async def refresh_recommendations(request: Request):
    koha_adapter._CATALOGUE_CACHE.clear()
    return await get_recommendations(request)


@app.get(settings.api_prefix + "/analytics/overview")
def analytics_overview():
    if not settings.demo_mode: raise HTTPException(503, "Reading analytics require authenticated Koha borrowing data")
    return {**analytics(),"source":"demo"}


@app.get(settings.api_prefix + "/profile")
def profile():
    if not settings.demo_mode: raise HTTPException(503, "Portal profile mapping is unavailable until live authentication is configured")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.koha_borrower_id == "DEMO-1042"))
        if user is None: raise HTTPException(404, "Portal user not found")
        interests = db.scalars(select(UserInterest.subject).where(UserInterest.user_id == user.id)).all()
        return {"name":user.name,"email":user.email,"card":"•••• 1042","interests":interests or ["Nature","Design","Creativity"],"source":"demo"}


@app.put(settings.api_prefix + "/profile")
def update_profile(payload: dict):
    if not settings.demo_mode: raise HTTPException(401, "Configure portal authentication before editing profile details")
    name = str(payload.get("name", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    if not name or len(name) > 120 or "@" not in email or len(email) > 255:
        raise HTTPException(422, "Enter a name and valid email address")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.koha_borrower_id == "DEMO-1042"))
        if user is None: raise HTTPException(404, "Portal user not found")
        existing = db.scalar(select(User).where(User.email == email, User.id != user.id))
        if existing: raise HTTPException(409, "That email address is already in use")
        user.name, user.email = name, email
        db.commit()
    return {"name":name,"email":email,"saved":True}


@app.put(settings.api_prefix + "/profile/interests")
def update_interests(payload: dict):
    if not settings.demo_mode: raise HTTPException(401, "Configure portal authentication before editing personal interests")
    allowed = {"Nature","Design","Creativity","Fiction","Science","Technology","Arts","Psychology"}
    values = [v for v in payload.get("interests", []) if v in allowed][:8]
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.koha_borrower_id == "DEMO-1042"))
        if user is None: raise HTTPException(404, "Portal user not found")
        db.query(UserInterest).filter_by(user_id=user.id).delete()
        db.add_all([UserInterest(user_id=user.id, subject=v, weight=1.0) for v in values])
        db.commit()
    return {"interests":values,"saved":True}
