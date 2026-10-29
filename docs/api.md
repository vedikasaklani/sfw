# Portal API

Prefix is configurable (`API_PREFIX`, default `/api/v1`). JSON errors use FastAPI's standard `detail` shape. Live patron endpoints require the signed session established by Koha password validation. The browser must send the session cookie (`credentials: include`) for those routes.

| Method and path | Purpose |
|---|---|
| `GET /health` | Portal status and data mode |
| `GET /koha/health` | Demo/configuration status |
| `GET /dashboard` | Patron summary, active loans, recent reading, source, and summary metrics |
| `GET /catalogue?q=&subject=&page=&page_size=` | Search with bounded pagination (page size 1–50) |
| `GET /catalogue/{book_id}` | Book detail |
| `GET /catalogue/{book_id}/items` | Koha item/copy records with safe availability status |
| `GET /catalogue/{book_id}/hold-options` | Pickup branches valid for the signed-in patron and title |
| `POST /catalogue/{book_id}/holds` | Place a Koha title-level hold for the signed-in patron |
| `GET /catalogue/{book_id}/items/{item_id}/checkout-options` | Check Koha self-checkout eligibility and confirmation requirements |
| `POST /catalogue/{book_id}/items/{item_id}/checkout` | Complete a Koha public self-checkout for an available copy |
| `GET /borrowing/current` | Current loans for the signed-in Koha patron; demo fixtures in demo mode |
| `GET /borrowing/history` | Returned checkout history for the signed-in Koha patron; requires Koha history permission; demo fixtures in demo mode |
| `GET /borrowing/holds` | Current holds for the signed-in Koha patron, including Koha's ready-for-pickup status |
| `GET /recommendations` | Demo recommendations; live personal recommendations currently return a capability error |
| `POST /recommendations/refresh` | Recompute recommendation response |
| `GET /analytics/overview` | Six-month borrowing counts, trend and subject distribution from the signed-in patron's Koha checkouts; demo figures only in explicit demo mode |
| `GET /profile` | Demo patron profile |
| `PUT /profile/interests` | Persist allowed demo interests |

`GET /analytics/overview` uses current checkouts and returned checkout history. Checkout counts are grouped by checkout date; subjects are extracted from the corresponding Koha biblio metadata (including MARC-in-JSON subject fields where flattened biblio JSON omits them). Koha checkout-history permissions/privacy settings can limit the returned events. The frontend shows a sign-in prompt when unauthenticated and surfaces Koha permission errors instead of fabricating live chart values. See [Koha integration](koha-integration.md#borrowing-data-needed-for-my-reading) and [recommendation metadata](koha-recommendation-metadata.md) for source details.

Hold and checkout writes always derive `patron_id` from the signed server session. Koha remains the authority for pickup options, availability, patron restrictions, confirmations and due dates. Enabling these actions requires the extra Koha permissions and system preferences documented in [Online holds and self-checkout](koha-integration.md#online-holds-and-self-checkout).

The catalogue API uses OAuth2 client credentials (or configured Basic / static bearer auth) from backend environment variables. Koha remains behind the backend. Patron sign-in creates a signed session; all live circulation requests use the patron ID held in that session rather than a browser-supplied ID. Unsupported live operations return capability errors rather than demo data.
