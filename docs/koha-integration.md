# Koha live catalogue integration

## Current KTD observations

- OPAC `http://localhost:8080`: HTTP 200.
- Staff API `http://localhost:8081/api/v1/biblios?limit=1`: HTTP 401 before API credentials were configured, confirming authentication was required (not a network failure).
- `/api/v1/public/biblios` returned 404 in this running instance, so this implementation does not try to bypass authentication through that path.
- Docker shows `kohadev-koha-1` on `kohadev_kohanet` with both Koha ports published to the host; no backend container is running. There are no Compose/KTD files in this project workspace. `dpkg-query` reports Koha `26.06.00-35~git+20261015000118.f7f4ff75-1`. The backend is host-run: `KOHA_BASE_URL=http://localhost:8081` plus `KOHA_API_PREFIX=/api/v1`; no container IP is used.
- The ignored `backend/.env` now has the host base URL, OAuth2 mode, `DEMO_MODE=false`, and locally configured client credentials. Secret values are intentionally not documented here.
- Authenticated smoke check through the portal now succeeds: `/koha/health` HTTP 200; catalogue page returns five Koha records; first record detail HTTP 200; item list HTTP 200 with one item.

## Koha admin setup (completed for the current KTD)

An administrator with access to the KTD staff interface must:

1. In Koha system preferences, enable `RESTOAuth2ClientCredentials`. If OAuth is unavailable and Basic auth is selected, enable `RESTBasicAuth` instead. Koha documentation says these preferences gate the respective REST API auth flows. For portal self-checkout, also review and enable `RESTPublicAPI` as described below.
2. Use a dedicated Koha API staff identity. The base catalogue integration needs `catalogue: 1` for reading bibliographic records and items. Grant the extra action permissions below only if the library wants the corresponding portal actions enabled.
3. Open that user's Koha account and select **More → Manage API keys**, create an API key pair, and deliver its client ID and secret to the backend operator through the local secret channel. Koha’s [official manual](https://koha-community.org/manual/21.05/en/html/webservices.html) describes this account key workflow. Do not put credentials in source control, the frontend, issue text, or logs.

Koha `26.06` is a development version, so use the [official current REST API reference](https://api.koha-community.org/Development.html) and confirm the matching operations in KTD before granting access. The current official API docs describe OAuth2 client credentials and Basic auth as system-preference gated and note that responses can be redacted by API-user permissions. The biblios list/detail and items routes require `catalogue: 1` in the documented spec. See also the [official system-preference documentation](https://koha-community.org/manual/latest/en/html/webservicespreferences.html).

## Backend environment

Set these only in the ignored local `backend/.env` (or deployment secret store):

```dotenv
DEMO_MODE=false
KOHA_BASE_URL=http://localhost:8081
KOHA_OPAC_URL=http://localhost:8080
KOHA_API_PREFIX=/api/v1
KOHA_AUTH_METHOD=oauth2
KOHA_CLIENT_ID=<issued by Koha>
KOHA_CLIENT_SECRET=<issued by Koha>
KOHA_TOKEN_PATH=/oauth/token
```

When backend is placed in a Docker container later, `localhost` will point to that backend container. First inspect the KTD and backend Docker network, then use `host.docker.internal` if host routing is supported or join the existing KTD network. Never hardcode a container IP or recreate KTD volumes.

For a Koha instance without OAuth enabled, use `KOHA_AUTH_METHOD=basic` and backend-only `KOHA_BASIC_USERNAME` / `KOHA_BASIC_PASSWORD` for a dedicated account granted catalogue permission. Static bearer tokens are also accepted as a configured option but do not renew; OAuth2 is preferred.

## Live smoke test

With OAuth credentials configured, start the backend on the host and run:

```powershell
cd backend
uvicorn app.main:app --reload
```

From another terminal:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/koha/health
Invoke-RestMethod 'http://localhost:8000/api/v1/catalogue?page=1&page_size=5'
```

Use a returned Koha bibliographic `id` for details and physical-copy status:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/catalogue/<biblio_id>
Invoke-RestMethod http://localhost:8000/api/v1/catalogue/<biblio_id>/items
```

If search is 401/502, check OAuth enablement, client credentials and expiration/auth endpoint. A 403 means the API user lacks `catalogue: 1` or a permission check failed. A 404 for details means the supplied biblio ID is absent. A 503 means Koha is unavailable or timed out. Responses and errors do not include upstream credentials or raw Koha error bodies.

Current result: health 200, search 200 with five real records, detail 200, and item list 200. An initial HTTP 406 was resolved by explicitly sending `Accept: application/json` on Koha API requests.

## Patron sign-in

The Account page now contains a patron sign-in form. It sends the username/card number and password to the portal backend, which validates them through Koha's `POST /api/v1/auth/password/validation` operation. Koha documents the required permission as `borrowers:api_validate_password`; add this subpermission to the configured API key under the Koha staff account's **More ? Manage API keys** permissions. This allows password validation without broad borrower-record access. A successful login sets a signed HTTP-only session cookie containing only the patron ID and userid. The password is not stored or logged. Live login plus dashboard was verified against KTD; three test checkouts were created for the requested test patron and Koha applied a due date of 2026-11-03.

Book details include a link to the corresponding Koha OPAC record, built with `KOHA_OPAC_URL` and Koha's biblio ID. It opens the full Koha record, where the library can offer OPAC options alongside the portal's hold and self-checkout actions.

### Online holds and self-checkout

The portal now offers patron-scoped circulation actions from Koha book details:

- **Place a hold:** the backend gets pickup locations valid for the signed-in patron and selected biblio, then posts a title-level hold to Koha. Koha checks branch rules, hold limits, account blocks, and queue eligibility. The session patron ID is always used; the browser cannot choose a different patron.
- **Check out a copy:** only copies Koha currently reports as available show this action. The patron must physically have the copy. The backend first requests Koha's checkout-availability result, including blocks and confirmation warnings, then completes checkout through Koha's public self-checkout endpoint using Koha's confirmation token. Koha assigns the due date and applies circulation rules.

To enable holds, the API staff account needs catalogue read access plus the Koha hold permission required by the deployed version (`reserveforothers:place_holds`; current Koha API specs may require the parent `reserveforothers:1` permission for `POST /holds`). This permission lets that API identity place holds for patrons, so keep access restricted to the backend secret and review the grant with the Koha administrator.

The **My reading** page also lists current holds from `GET /patrons/{patron_id}/holds`, using the patron ID from the signed session. Koha's holds endpoint requires `borrowers:view_holds_history` (or `borrowers:edit_borrowers`); grant the narrower read permission where supported. Holds with a Koha waiting date/status are labeled **Now available**.

To enable self-checkout, Koha's `RESTPublicAPI` system preference must allow the public checkout availability and checkout operations. This is a Koha configuration choice; review which public endpoints it exposes. Koha can reject a checkout because of item status, patron blocks, holds, debt limits, or circulation rules. The portal does not override those decisions. A `FEATURE_DISABLED` response means the public self-checkout capability is not enabled for this Koha instance.

The [official Koha API reference](https://api.koha-community.org/Development.html) documents `GET /biblios/{biblio_id}/pickup_locations`, `POST /holds`, `GET /public/checkouts/availability`, and `POST /public/patrons/{patron_id}/checkouts`. Holds and checkouts are not simulated in demo mode. No hold or checkout was placed as part of implementing these controls.

`APP_SESSION_SECRET` is generated in the ignored local `backend/.env`; restart the backend after changing it. Keep `SESSION_COOKIE_SECURE=false` only for local HTTP development; set it to `true` when serving the portal over HTTPS. Sign-in verifies identity; profile editing and live personal recommendations remain unavailable.

### Borrowing data needed for “My reading”

After sign-in, the backend uses the patron ID stored in the signed session (never an ID supplied by the browser) to call Koha. The current official API documents `GET /api/v1/checkouts?patron_id={id}` for active loans and `GET /api/v1/patrons/{patron_id}/checkouts` for checkout history. The latter also requires `borrowers:view_checkout_history`; Koha privacy/retention settings can limit which past returns exist. The integration embeds item data and fetches the corresponding biblio record where necessary, then maps titles, authors, checkout/due/return dates and overdue state without returning barcodes or other borrower records to the browser. A combined nested embed header caused Koha 26.06 to return 400, so the adapter uses its accepted item embed and a separate biblio lookup. Renewal status/actions would additionally call `GET /checkouts/{checkout_id}/allows_renewal` and, only when offered, `POST /checkouts/{checkout_id}/renewals`; those actions are not implemented yet.

Koha's current API spec lists `circulate:circulate_remaining_permissions` and `circulate:manage_bookings` for listing checkouts, plus `borrowers:view_checkout_history` for patron checkout history. `circulate_remaining_permissions` grants broad circulation rights in Koha (not read-only access), so have the Koha administrator review the API account's scope. The portal's active checkout fetch, mapping and dashboard display were verified end to end.

## Portal mapping and safety

`app/integrations/koha.py` owns API URLs, OAuth token caching/renewal, Basic auth, timeouts, errors, JSON validation, pagination and DTO normalization. Search accepts Koha's `q` JSON filter with a title/author/ISBN/subject OR filter and optional separate subject filter. The frontend talks only to the portal API.

Biblio records and physical items are separate Koha resources. Search results indicate availability as `Unknown` until item records are retrieved; details request the items endpoint and derive status from Koha’s returned `checked_out_date`, `effective_not_for_loan_status`, lost and withdrawn fields. If status fields are missing/redacted, availability remains `Unknown`. Barcode/external item IDs, staff notes, patron records and due dates are not returned to the UI.

Live dashboard, My reading, and Reading insights use the signed-in patron's Koha circulation data; live recommendations and profile editing remain unavailable instead of showing seeded patron data. Set `DEMO_MODE=true` only when intentionally previewing the labelled sample environment.

## Recommendation metadata

The full Koha-to-portal recommendation field inventory, endpoint and permission notes, MARC candidates, privacy exclusions, and offline workflow are documented in [Koha recommendation metadata](koha-recommendation-metadata.md). Recommendation logic should consume the source-neutral [JSON Schema](recommendation-metadata.schema.json) and [synthetic snapshot](examples/recommendation-snapshot.json), never raw Koha responses. This lets contributors change ranking behavior without a running Koha instance; only adapter work needs Koha-shaped fixtures and mapping knowledge.
