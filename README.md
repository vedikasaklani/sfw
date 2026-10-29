# Modern Library Portal

A responsive library patron portal that sits in front of Koha. Koha remains authoritative for catalogue and circulation records; portal-owned data is limited to patron preferences and generated recommendation metadata.

## Progress

- [x] Reviewed the existing FastAPI, React and Koha adapter flow before integration; the original brief PDFs remain unavailable.
- [x] Establish a modular FastAPI API, React/Vite client, demo Koha adapter, and local SQLite persistence.
- [x] Implement coherent demo dashboard, catalogue search/details, loan history, recommendations, analytics, and profile views.
- [x] Document architecture, Koha boundaries, API contracts, data model, and implementation decisions.
- [x] Integrated OAuth2 client-credentials / Basic auth, paginated catalogue search, biblio details, item availability and live frontend status states.
- [x] Complete authenticated Koha smoke test: health, catalogue search, record detail and item retrieval succeeded.
- [x] Add an actual Koha patron sign-in form on Account, validate username/card plus password through Koha's password validation API, and keep the session in a signed HTTP-only cookie.
- [x] Make My reading the single borrowing home, wired to Koha active checkouts and returned-checkout history using only the patron ID from the server session.
- [x] Verify login and live dashboard end to end against KTD; three user-requested test checkouts were created and confirmed in the portal API response.
- [x] Add deterministic backend API/service tests; verify tests and frontend build after dependency setup.
- [x] Integrate the catalogue client with Koha OAuth2/Basic options, paging, book details and item availability. Update frontend to use the portal API without a live-to-demo fallback.
- [x] Inspect running KTD: Koha 26.06.00, host ports 8080/8081, host-run backend routing via localhost:8081.
- [x] Configure Koha OAuth2 credentials and catalogue permission in the local ignored environment; the unauthenticated endpoint's earlier HTTP 401 is resolved for the portal client.
- [ ] Complete live patron profile editing, self-service renewal actions, Alembic migrations, and notification delivery.
- [x] Prepared assessment submissions for AST08 testing and AST09 catalogue UI design in `AST08_AST09_Submission.txt`, including executed outcomes and clearly stated live Koha limits.
- [x] Documented Koha recommendation metadata sources and privacy limits; added a versioned source-neutral JSON Schema and synthetic offline fixture for recommendation work without Koha.
- [x] Connect reading insights to authenticated Koha checkout and history endpoints; compute six-month trend, counts, and available MARC subject headings from patron circulation data.
- [x] Add patron-scoped Koha hold placement and public self-checkout actions to live catalogue details; Koha validates pickup eligibility, checkout blockers and due dates.

## Local development

Requirements: Python 3.11+, Node.js 20+.

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e '.[dev]'
if (!(Test-Path .env)) { Copy-Item .env.example .env }
uvicorn app.main:app --reload
```

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The local ignored `backend/.env` is configured for live Koha mode. The UI reports Koha offline instead of substituting sample catalogue records if the connection fails. To use sample data explicitly, set `DEMO_MODE=true`. API docs: http://localhost:8000/docs.

## Configuration

Koha credentials are backend-only and stored in ignored `backend/.env`. OAuth2 client credentials are configured for the current KTD. The API returned 401 before the key was issued; authenticated health, catalogue, record-detail and item requests now return successfully. Setup details are in [Koha integration](docs/koha-integration.md).

### Patron sign-in

Open **Account settings** in the left sidebar and enter the same username (or library card number) and password used for Koha. The portal sends the credentials only to its backend, which asks Koha's `POST /api/v1/auth/password/validation` endpoint to verify them; the password is not stored. The configured OAuth API account needs Koha's `borrowers:api_validate_password` permission (Koha Administration → Manage API keys → that key's permissions). This validates a password without granting broad borrower-record access. Use HTTPS and set `SESSION_COOKIE_SECURE=true` when deploying; local KTD uses HTTP for development.

The backend accepts the configured `FRONTEND_ORIGIN`; in development it also accepts the localhost/127.0.0.1 Vite origin pair. If you open the frontend from another hostname or LAN IP, add its full origin (including scheme and port) to comma-separated `FRONTEND_ORIGINS` in `backend/.env`, then restart the backend. The frontend calls the API on the same hostname at port 8000 so browser session cookies stay same-site.

The signed-in Overview and My reading pages now request active loans and returned checkout history from Koha. The backend uses the patron ID in the signed session, maps titles/dates/status, and omits raw item barcodes and other borrower records. Koha's current API lists active loans via `GET /api/v1/checkouts?patron_id={patron_id}` and checkout history via `GET /api/v1/patrons/{patron_id}/checkouts`; see [Koha integration](docs/koha-integration.md#borrowing-data-needed-for-my-reading) for permissions. Renewal actions and editable patron details are not implemented yet.

Borrowing information is consolidated in My reading, which shows counts, all active loans and due dates, and returned-item history. The separate Overview entry has been removed to avoid repeating the same information.

Live KTD verification: authenticated portal login returned 200, and `/api/v1/dashboard` returned 200 with three active checkouts for the requested test patron. Koha assigned a due date of 2026-11-03 to each item. No patron password is stored in project files.

Book details now link to the matching full record in the Koha OPAC (`KOHA_OPAC_URL`, default `http://localhost:8080`) so users can open Koha's own catalog options. The link opens in a new tab; holds are still handled by Koha and are not placed by this portal.

## Recommendation engine (LightFM)

The engine is in `backend/app/recommendations/` and reads only the source-neutral snapshot defined in [`docs/recommendation-metadata.schema.json`](docs/recommendation-metadata.schema.json). Details are in [Koha metadata for recommendations](docs/koha-recommendation-metadata.md).

| File | What it owns |
|---|---|
| `engine.py` | Contract validation, taste profile, popularity/availability blend, explanations, backend choice |
| `lightfm_model.py` | The only LightFM import. `ModelConfig` holds the hyperparameters; `score()` fits and predicts |
| `__main__.py` | Offline CLI over any snapshot file |
| `app/integrations/koha.py` | Koha → snapshot (`extract_marc21_v1`, `contract_book`, `build_recommendation_snapshot`) |
| `app/services.py` | Sample library → snapshot (`demo_snapshot`) |

### Set up LightFM (Ubuntu/WSL)

LightFM can't be installed as a normal dependency:
- It ships no Linux wheels.
- The PyPI 1.17 release fails on current setuptools.
- The C files in its repo were generated by an old Cython and don't compile on Python 3.12.

`scripts/install_lightfm.sh` builds a pinned upstream commit, regenerating those files with Cython 0.29 first:

```bash
sudo apt install -y build-essential python3-dev   # one-time C compiler
cd backend
./scripts/install_lightfm.sh                       # builds into backend/.venv (set PYTHON=... for another env)
```

### Choose the backend

Set `RECOMMENDER_BACKEND` in `backend/.env`:

- `auto` (default): LightFM if installed, otherwise the content ranker.
- `lightfm`: refuses to start without LightFM, so a broken install can't silently fall back.
- `content`: never uses LightFM.

Both backends return the same shape: `book_id`, `score`, `reason_code`, `reason`, `strategy`.

### Check it is working

```bash
cd backend
python -m pytest tests/test_recommendation_engine.py -q     # 3 LightFM tests skip until it is installed
python -m app.recommendations ../docs/examples/recommendation-snapshot.json --backend lightfm --today 2026-10-29
curl -s localhost:8000/api/v1/recommendations/status        # {"engine":"lightfm","lightfm_installed":true,...}
```

### Work on the model

Tune `ModelConfig` in `lightfm_model.py` (loss, components, learning rate, epochs; `random_state` keeps runs reproducible). Change the blend weights or decay at the top of `engine.py`. Iterate offline with the CLI against your own snapshot JSON; no Koha or `.env` is needed. New metadata goes into the adapter and schema first, never straight into the engine.

## Commands

```powershell
# Backend checks
cd backend
pytest

# Frontend checks/build
cd frontend
npm run build
```

## Current verification

- Backend: `python -m pytest tests -q` — 16 passed in the current integration pass; warnings are from upstream Starlette/pytest-asyncio compatibility.
- Frontend: `npm run build` — succeeded. Vite reported a 626 kB main bundle advisory.
- Live Koha: KTD package version is 26.06.00-35~git+20261015000118.f7f4ff75-1. Authenticated portal health returned 200; search returned five Koha records; first record detail and item requests both returned 200. Client credentials remain in the ignored environment file.
- PDFs/UML: not present in the supplied workspace; written brief used instead.

See [docs/api.md](docs/api.md), [architecture](docs/architecture.md), [data model](docs/data-model.md), and [decisions](docs/decisions.md).

For recommendation development, start with [Koha recommendation metadata](docs/koha-recommendation-metadata.md), validate against [the snapshot schema](docs/recommendation-metadata.schema.json), and use the [synthetic example](docs/examples/recommendation-snapshot.json). The recommender should consume this source-neutral format; Koha-specific extraction stays in the backend adapter.
