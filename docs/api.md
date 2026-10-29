# Portal API

Prefix is configurable (`API_PREFIX`, default `/api/v1`). JSON errors use FastAPI's standard `detail` shape. The demo dashboard and sample borrowing routes are explicitly demo-only. Live circulation routes return 503 until a real portal authentication and borrower mapping adapter exists.

| Method and path | Purpose |
|---|---|
| `GET /health` | Portal status and data mode |
| `GET /koha/health` | Demo/configuration status |
| `GET /dashboard` | Patron summary, active loans, recent reading, recommendations, analytics |
| `GET /catalogue?q=&subject=&page=&page_size=` | Search with bounded pagination (page size 1–50) |
| `GET /catalogue/{book_id}` | Book detail |
| `GET /catalogue/{book_id}/items` | Koha item/copy records with safe availability status |
| `GET /borrowing/current` | Current loans (demo only currently) |
| `GET /borrowing/history` | Reading history (demo only currently) |
| `GET /recommendations` | Ranked recommendations with reasons |
| `POST /recommendations/refresh` | Recompute recommendation response |
| `GET /analytics/overview` | Borrowing counts, trend and subject distribution |
| `GET /profile` | Demo patron profile |
| `PUT /profile/interests` | Persist allowed demo interests |

The catalogue API uses OAuth2 client credentials (or configured Basic / static bearer auth) from backend environment variables. Koha remains behind the backend. The current client does not provide a login form/session. Authentication and ownership checks are required before exposing patron endpoints in a live deployment; the sample identity is never live authentication. When live mode is active, unsupported patron endpoints return capability errors rather than demo data.
