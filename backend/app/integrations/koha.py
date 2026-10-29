"""Server-side Koha REST API client and catalogue DTO mapping."""
import asyncio
import json
import time
from datetime import date, datetime, timezone
from typing import Any, Protocol
from urllib.parse import quote

import httpx


class KohaError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class KohaAuthenticationError(KohaError):
    def __init__(self, message: str = "Koha rejected the configured API credentials or permissions"):
        super().__init__(message, 502)


class KohaNotFoundError(KohaError):
    def __init__(self, message: str = "Koha record not found"):
        super().__init__(message, 404)


class KohaUpstreamError(KohaError):
    pass


class KohaActionError(KohaError):
    pass


class KohaAPI(Protocol):
    demo: bool
    async def search_catalogue(self, query: str = "", subject: str | None = None, page: int = 1, page_size: int = 20) -> dict[str, Any]: ...
    async def get_book(self, book_id: str) -> dict[str, Any]: ...
    async def get_book_items(self, book_id: str) -> list[dict[str, Any]]: ...


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if v is not None and str(v).strip()]
    if isinstance(value, dict):
        return [str(v).strip() for v in value.values() if v is not None and str(v).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split("|;|" if "|;|" in value else ";") if part.strip()]
    return [str(value)]


def map_biblio(record: dict[str, Any]) -> dict[str, Any]:
    """Map Koha biblio fields to the portal's existing Book response shape."""
    biblio_id = record.get("biblio_id") or record.get("id")
    subjects = _as_list(record.get("subject") or record.get("subjects"))
    author = record.get("author") or record.get("authors")
    authors = _as_list(author)
    isbn = _as_list(record.get("isbn") or record.get("normalized_isbn"))
    return {
        "id": str(biblio_id) if biblio_id is not None else "",
        "title": str(record.get("title") or "Untitled record"),
        "authors": authors,
        "subjects": subjects,
        "year": record.get("publication_year"),
        "isbn": isbn[0] if isbn else None,
        "description": record.get("abstract") or record.get("notes") or "",
        "availability": "Unknown",
        "copies": None,
        "source": "koha",
    }


def map_marc_subjects(record: Any) -> list[str]:
    """Extract public subject headings from a Koha MARC-in-JSON record."""
    if not isinstance(record, dict) or not isinstance(record.get("fields"), list):
        return []
    subjects: list[str] = []
    tags = ("600", "610", "611", "630", "648", "650", "651", "653")
    for field in record["fields"]:
        if not isinstance(field, dict):
            continue
        for tag in tags:
            value = field.get(tag)
            if not isinstance(value, dict):
                continue
            subfields = value.get("subfields", [])
            parts = [str(v).strip() for subfield in subfields if isinstance(subfield, dict) for code, v in subfield.items() if code in {"a", "x", "y", "z", "v"} and str(v).strip()] if isinstance(subfields, list) else []
            heading = " -- ".join(parts)
            if heading and heading not in subjects:
                subjects.append(heading)
    return subjects


def map_item(item: dict[str, Any]) -> dict[str, Any]:
    checked_out = bool(item.get("checked_out_date") or item.get("checkout_date"))
    lost = bool(item.get("lost_status") or item.get("effective_lost_status"))
    withdrawn = bool(item.get("withdrawn"))
    not_for_loan = item.get("effective_not_for_loan_status", item.get("not_for_loan_status"))
    if checked_out:
        status = "On loan"
    elif lost:
        status = "Lost"
    elif withdrawn:
        status = "Withdrawn"
    elif not_for_loan not in (None, 0, "0", False):
        status = "Not for loan"
    elif not_for_loan in (0, "0", False):
        status = "Available"
    else:
        status = "Unknown"
    return {
        "item_id": item.get("item_id"),
        "library_id": item.get("home_library_id"),
        "item_type_id": item.get("item_type_id"),
        "status": status,
    }


MARC_SUBJECT_TAGS = ("600", "610", "611", "630", "648", "650", "651", "653")


def _marc_fields(marc: dict[str, Any], tag: str) -> list[Any]:
    return [f[tag] for f in marc.get("fields", []) if isinstance(f, dict) and tag in f]


def _subfield(field: Any, code: str) -> list[str]:
    if not isinstance(field, dict):
        return []
    return [str(sf[code]).strip().rstrip(" .,;:/") for sf in field.get("subfields", []) if isinstance(sf, dict) and sf.get(code)]


def extract_marc21_v1(marc: dict[str, Any]) -> dict[str, Any]:
    """MARC21 (MARC-in-JSON) -> contract fields. Only known tags are read; unknown tags are ignored."""
    if not isinstance(marc, dict):
        return {}
    pick = lambda tags, code="a": list(dict.fromkeys(v for t in tags for f in _marc_fields(marc, t) for v in _subfield(f, code) if v))
    control_008 = next((f for f in _marc_fields(marc, "008") if isinstance(f, str)), "")
    language = (pick(("041",)) or [control_008[35:38].strip() if len(control_008) >= 38 else ""])[0] or None
    summary = pick(("520",))
    return {
        "authors": pick(("100", "110", "111")),
        "contributors": pick(("700", "710", "711", "720")),
        "subjects": pick(MARC_SUBJECT_TAGS),
        "genres": pick(("655",)),
        "language": language,
        "series": (pick(("830", "490")) or [None])[0],
        "format": (pick(("336",)) or [None])[0],
        "description": summary[0] if summary else None,
    }


def _count(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def contract_book(record: dict[str, Any], marc: dict[str, Any], raw_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Build one source-neutral catalogue entry; no Koha IDs, barcodes or staff fields leave here."""
    mapped = map_biblio(record)
    statuses = [map_item(i)["status"] for i in raw_items]
    year = record.get("publication_year")
    def total(key):
        counts = [c for c in (_count(i.get(key)) for i in raw_items) if c is not None]
        return sum(counts) if counts else None
    return {
        "book_id": mapped["id"],
        "title": mapped["title"],
        "authors": marc.get("authors") or mapped["authors"],
        "contributors": marc.get("contributors") or [],
        "subjects": marc.get("subjects") or mapped["subjects"],
        "genres": marc.get("genres") or [],
        "language": marc.get("language"),
        "publication_year": int(year) if str(year or "").isdigit() else None,
        "publisher": record.get("publisher") or None,
        "series": marc.get("series") or record.get("series_title") or None,
        "format": marc.get("format") or record.get("item_type") or None,
        "description": marc.get("description") or mapped["description"] or None,
        "age_restriction": record.get("age_restriction") or None,
        "availability": "available" if "Available" in statuses else "unavailable" if statuses and "Unknown" not in statuses else "unknown",
        "popularity": {"checkouts": total("checkouts_count"), "renewals": total("renewals_count"), "holds": total("holds_count")},
    }


# shortcut: per-process cache of the candidate catalogue, move to the DB if several workers run.
_CATALOGUE_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
CATALOGUE_TTL = 900


class KohaClient:
    """Koha HTTP/auth boundary. One client instance can be shared by the app."""
    demo = False

    def __init__(self, base_url: str, auth_method: str = "oauth2", client_id: str = "", client_secret: str = "", username: str = "", password: str = "", api_token: str = "", token_path: str = "/oauth/token", timeout: float = 8.0, transport: httpx.AsyncBaseTransport | None = None):
        if not base_url:
            raise KohaUpstreamError("KOHA_BASE_URL is required when demo mode is disabled", 503)
        self.base = base_url.rstrip("/")
        self.auth_method = auth_method.casefold().strip()
        self.client_id, self.client_secret = client_id, client_secret
        self.username, self.password, self.api_token = username, password, api_token
        self.token_url = self.base + "/" + token_path.strip("/")
        self.timeout = httpx.Timeout(timeout, connect=min(timeout, 3.0))
        self.transport = transport
        self._access_token: str | None = None
        self._token_expiry = 0.0
        self._token_lock = asyncio.Lock()
        if self.auth_method == "oauth2" and not (client_id and client_secret):
            raise KohaUpstreamError("Set KOHA_CLIENT_ID and KOHA_CLIENT_SECRET for OAuth2 client credentials", 503)
        if self.auth_method == "basic" and not (username and password):
            raise KohaUpstreamError("Set KOHA_BASIC_USERNAME and KOHA_BASIC_PASSWORD for Koha Basic authentication", 503)
        if self.auth_method == "bearer" and not api_token:
            raise KohaUpstreamError("Set KOHA_API_TOKEN for configured bearer authentication", 503)
        if self.auth_method not in {"oauth2", "basic", "bearer"}:
            raise KohaUpstreamError("KOHA_AUTH_METHOD must be oauth2, basic, or bearer", 503)

    async def _oauth_token(self) -> str:
        if self._access_token and time.monotonic() < self._token_expiry - 20:
            return self._access_token
        async with self._token_lock:
            if self._access_token and time.monotonic() < self._token_expiry - 20:
                return self._access_token
            try:
                async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                    response = await client.post(self.token_url, data={"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret})
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise KohaUpstreamError("Koha OAuth response was not a JSON object", 502)
                token = body.get("access_token")
                if not token:
                    raise KohaUpstreamError("Koha OAuth response did not include an access token", 502)
                self._access_token = str(token)
                try:
                    lifetime = max(1, int(body.get("expires_in", 300)))
                except (TypeError, ValueError) as exc:
                    raise KohaUpstreamError("Koha OAuth response contained an invalid expiry", 502) from exc
                self._token_expiry = time.monotonic() + lifetime
                return self._access_token
            except KohaError:
                raise
            except httpx.TimeoutException as exc:
                raise KohaUpstreamError("Koha authentication request timed out", 503) from exc
            except (httpx.HTTPError, ValueError) as exc:
                raise KohaUpstreamError("Koha authentication failed; verify API auth settings and client permissions", 502) from exc

    async def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.auth_method == "oauth2":
            headers["Authorization"] = f"Bearer {await self._oauth_token()}"
        if self.auth_method == "bearer":
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    async def _get(self, path: str, params: dict[str, Any] | None = None, *, request_headers: dict[str, str] | None = None, retry_auth: bool = True) -> tuple[Any, httpx.Headers]:
        auth = (self.username, self.password) if self.auth_method == "basic" else None
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.get(f"{self.base}/{path.lstrip('/')}", params=params, headers={**(await self._headers()), **(request_headers or {})}, auth=auth)
            if response.status_code == 401 and retry_auth and self.auth_method == "oauth2":
                self._access_token = None
                self._token_expiry = 0
                return await self._get(path, params, request_headers=request_headers, retry_auth=False)
            if response.status_code in (401, 403):
                raise KohaAuthenticationError()
            if response.status_code == 404:
                raise KohaNotFoundError()
            if response.status_code == 429:
                raise KohaUpstreamError("Koha rate limit reached; retry later", 503)
            if response.status_code >= 500:
                raise KohaUpstreamError("Koha catalogue service is temporarily unavailable", 503)
            if response.is_error:
                raise KohaUpstreamError(f"Koha rejected the catalogue request (HTTP {response.status_code})", 502)
            try:
                return response.json(), response.headers
            except ValueError as exc:
                raise KohaUpstreamError("Koha returned malformed JSON", 502) from exc
        except KohaError:
            raise
        except httpx.TimeoutException as exc:
            raise KohaUpstreamError("Koha catalogue request timed out", 503) from exc
        except httpx.HTTPError as exc:
            raise KohaUpstreamError("Could not connect to the Koha REST API", 503) from exc

    async def _post_json(self, path: str, payload: dict[str, Any], params: dict[str, Any] | None = None, *, retry_auth: bool = True) -> Any:
        auth = (self.username, self.password) if self.auth_method == "basic" else None
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.post(f"{self.base}/{path.lstrip('/')}", params=params, json=payload, headers=await self._headers(), auth=auth)
            if response.status_code == 401 and retry_auth and self.auth_method == "oauth2":
                self._access_token = None
                self._token_expiry = 0
                return await self._post_json(path, payload, params, retry_auth=False)
            if response.status_code in (401, 403):
                raise KohaAuthenticationError("Koha denied this action. Check the API account permissions and Koha patron rules")
            if response.status_code == 404:
                raise KohaNotFoundError()
            if response.status_code == 409:
                raise KohaActionError("Koha cannot complete this action because of a circulation restriction", 409)
            if response.status_code in (400, 412):
                raise KohaActionError("Koha rejected this action. Check item eligibility and circulation rules", 409)
            if response.status_code == 405:
                raise KohaUpstreamError("This Koha self-checkout feature is disabled", 503)
            if response.status_code == 429:
                raise KohaUpstreamError("Koha rate limit reached; retry later", 503)
            if response.status_code >= 500:
                raise KohaUpstreamError("Koha circulation service is temporarily unavailable", 503)
            if response.is_error:
                raise KohaUpstreamError(f"Koha rejected the action (HTTP {response.status_code})", 502)
            try:
                return response.json()
            except ValueError as exc:
                raise KohaUpstreamError("Koha returned malformed JSON", 502) from exc
        except KohaError:
            raise
        except httpx.TimeoutException as exc:
            raise KohaUpstreamError("Koha circulation request timed out", 503) from exc
        except httpx.HTTPError as exc:
            raise KohaUpstreamError("Could not connect to the Koha REST API", 503) from exc

    async def validate_patron_password(self, identifier: str, password: str) -> dict[str, Any]:
        """Ask Koha to validate a patron; never retain the submitted password."""
        auth = (self.username, self.password) if self.auth_method == "basic" else None
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.post(
                    f"{self.base}/auth/password/validation",
                    json={"identifier": identifier, "password": password},
                    headers=await self._headers(), auth=auth,
                )
            if response.status_code == 401:
                raise KohaAuthenticationError("Koha rejected the API credentials")
            if response.status_code == 403:
                raise KohaUpstreamError("Koha API account needs the borrowers:api_validate_password permission", 503)
            if response.status_code in (400, 422):
                raise KohaAuthenticationError("That library username/card number or password was not accepted")
            if response.status_code == 429:
                raise KohaUpstreamError("Koha rate limit reached; retry later", 503)
            if response.status_code >= 500:
                raise KohaUpstreamError("Koha authentication service is temporarily unavailable", 503)
            if response.status_code != 201:
                raise KohaUpstreamError(f"Koha rejected the sign-in request (HTTP {response.status_code})", 502)
            result = response.json()
            if not isinstance(result, dict) or not result.get("patron_id"):
                raise KohaUpstreamError("Koha returned an incomplete patron identity", 502)
            return {"patron_id": str(result["patron_id"]), "userid": str(result.get("userid") or "")}
        except KohaError:
            raise
        except httpx.TimeoutException as exc:
            raise KohaUpstreamError("Koha sign-in request timed out", 503) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise KohaUpstreamError("Could not complete sign-in with Koha", 503) from exc

    async def search_catalogue(self, query: str = "", subject: str | None = None, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        filters = []
        term = query.strip()
        if term:
            pattern = f"%{term}%"
            filters.append({"-or": [{"title": {"-like": pattern}}, {"author": {"-like": pattern}}, {"isbn": {"-like": pattern}}, {"subject": {"-like": pattern}}]})
        if subject:
            filters.append({"subject": {"-like": f"%{subject.strip()}%"}})
        q: Any = filters[0] if len(filters) == 1 else ({"-and": filters} if filters else None)
        params: dict[str, Any] = {"_page": page, "_per_page": page_size}
        if q is not None:
            params["q"] = json.dumps(q, separators=(",", ":"))
        payload, headers = await self._get("biblios", params)
        if not isinstance(payload, list):
            raise KohaUpstreamError("Koha returned an unexpected catalogue response", 502)
        total = headers.get("x-total-count")
        if total is None:
            # Koha's Link header advertises pagination when the total-count header is absent.
            link = headers.get("link", "")
            total = None if 'rel="next"' in link else str((page - 1) * page_size + len(payload))
        return {"items": [map_biblio(row) for row in payload if isinstance(row, dict)], "total": int(total) if total and total.isdigit() else None, "page": page, "page_size": page_size}

    async def get_book(self, book_id: str) -> dict[str, Any]:
        if not book_id.isdigit():
            raise KohaNotFoundError()
        payload, _ = await self._get(f"biblios/{quote(book_id, safe='')}")
        if not isinstance(payload, dict):
            raise KohaUpstreamError("Koha returned an unexpected bibliographic record", 502)
        record = map_biblio(payload)
        items = await self.get_book_items(book_id)
        statuses = [item["status"] for item in items]
        record["items"] = items
        record["copies"] = len(items)
        record["availability"] = ("Available" if "Available" in statuses else "On loan" if statuses and all(s == "On loan" for s in statuses) else "Unavailable" if statuses and all(s in {"Lost", "Withdrawn", "Not for loan"} for s in statuses) else "Unknown")
        return record

    async def _item_rows(self, book_id: str) -> list[dict[str, Any]]:
        if not book_id.isdigit():
            raise KohaNotFoundError()
        items: list[dict[str, Any]] = []
        for page in range(1, 101):
            payload, headers = await self._get(f"biblios/{quote(book_id, safe='')}/items", {"_page": page, "_per_page": 100})
            if not isinstance(payload, list):
                raise KohaUpstreamError("Koha returned an unexpected item response", 502)
            items.extend(row for row in payload if isinstance(row, dict))
            total = headers.get("x-total-count")
            has_next = 'rel="next"' in headers.get("link", "")
            if total and total.isdigit():
                if len(items) >= int(total): break
            elif not has_next:
                break
        return items

    async def get_hold_pickup_locations(self, biblio_id: str, patron_id: str) -> list[dict[str, Any]]:
        if not biblio_id.isdigit() or not patron_id.isdigit():
            raise KohaNotFoundError()
        payload, _ = await self._get(f"biblios/{quote(biblio_id, safe='')}/pickup_locations", {"patron_id": int(patron_id)})
        if not isinstance(payload, list):
            raise KohaUpstreamError("Koha returned an unexpected pickup location response", 502)
        return [{"library_id": str(row.get("library_id") or ""), "name": str(row.get("name") or row.get("library_id") or "")} for row in payload if isinstance(row, dict) and row.get("library_id")]

    async def place_hold(self, biblio_id: str, patron_id: str, pickup_library_id: str) -> dict[str, Any]:
        if not biblio_id.isdigit() or not patron_id.isdigit() or not pickup_library_id.strip():
            raise KohaNotFoundError()
        result = await self._post_json("holds", {"biblio_id": int(biblio_id), "patron_id": int(patron_id), "pickup_library_id": pickup_library_id.strip()})
        if not isinstance(result, dict) or not result.get("hold_id"):
            raise KohaUpstreamError("Koha did not confirm the hold", 502)
        return {"hold_id": str(result["hold_id"]), "status": str(result.get("status") or "Placed"), "pickup_library_id": str(result.get("pickup_library_id") or pickup_library_id)}

    async def get_patron_holds(self, patron_id: str) -> list[dict[str, Any]]:
        """Return current holds for one authenticated patron, with public display fields."""
        if not patron_id.isdigit():
            raise KohaNotFoundError("Signed-in Koha patron identity is invalid")
        rows: list[dict[str, Any]] = []
        for page in range(1, 101):
            payload, headers = await self._get(
                f"patrons/{quote(patron_id, safe='')}/holds",
                {"_page": page, "_per_page": 100},
                request_headers={"x-koha-embed": "biblio,pickup_library,item,+strings"},
            )
            if not isinstance(payload, list):
                raise KohaUpstreamError("Koha returned an unexpected holds response", 502)
            rows.extend(row for row in payload if isinstance(row, dict))
            total = headers.get("x-total-count")
            has_next = 'rel="next"' in headers.get("link", "")
            if total and total.isdigit():
                if len(rows) >= int(total):
                    break
            elif not has_next:
                break

        holds = []
        for row in rows:
            biblio = row.get("biblio") if isinstance(row.get("biblio"), dict) else {}
            item = row.get("item") if isinstance(row.get("item"), dict) else {}
            pickup = row.get("pickup_library") if isinstance(row.get("pickup_library"), dict) else {}
            status = row.get("status")
            if not status and isinstance(row.get("_strings"), dict):
                status = (row["_strings"].get("status") or {}).get("str") if isinstance(row["_strings"].get("status"), dict) else None
            status_text = str(status or "Pending")
            waiting_date = row.get("waiting_date")
            status_key = status_text.casefold().replace(" ", "_")
            ready = bool(waiting_date) or status_key in {"w", "waiting", "available", "ready", "ready_for_pickup"}
            holds.append({
                "id": str(row.get("hold_id") or ""),
                "book_id": str(row.get("biblio_id") or biblio.get("biblio_id") or ""),
                "title": str(biblio.get("title") or item.get("title") or "Library item"),
                "authors": _as_list(biblio.get("author") or biblio.get("authors")),
                "placed_date": str(row.get("hold_date") or "")[:10] or None,
                "pickup_location": str(pickup.get("name") or pickup.get("library_id") or row.get("pickup_library_id") or ""),
                "status": "Now available" if ready else status_text,
                "available_now": ready,
                "waiting_date": str(waiting_date)[:10] if waiting_date else None,
            })
        return holds

    async def checkout_availability(self, patron_id: str, item_id: str) -> dict[str, Any]:
        if not patron_id.isdigit() or not item_id.isdigit():
            raise KohaNotFoundError()
        payload, _ = await self._get("public/checkouts/availability", {"patron_id": int(patron_id), "item_id": int(item_id)})
        if not isinstance(payload, dict):
            raise KohaUpstreamError("Koha returned an unexpected checkout availability response", 502)
        return payload

    async def self_checkout(self, patron_id: str, item_id: str, confirmation: str) -> dict[str, Any]:
        if not patron_id.isdigit() or not item_id.isdigit() or not confirmation:
            raise KohaActionError("Checkout confirmation expired; check availability again", 409)
        result = await self._post_json(f"public/patrons/{quote(patron_id, safe='')}/checkouts", {"item_id": int(item_id)}, {"confirmation": confirmation})
        if not isinstance(result, dict):
            raise KohaUpstreamError("Koha did not confirm the checkout", 502)
        return {"checkout_id": str(result.get("checkout_id") or ""), "due_date": result.get("due_date")}
    async def get_book_items(self, book_id: str) -> list[dict[str, Any]]:
        return [map_item(row) for row in await self._item_rows(book_id)]

    async def _contract_entry(self, record: dict[str, Any]) -> dict[str, Any] | None:
        book_id = str(record.get("biblio_id") or "")
        if not book_id.isdigit() or record.get("opac_suppressed"):
            return None
        try:
            marc, _ = await self._get(f"biblios/{book_id}", request_headers={"Accept": "application/marc-in-json"})
        except KohaError:
            marc = {}  # subjects are optional in the contract; fall back to flat fields
        try:
            items = await self._item_rows(book_id)
        except KohaError:
            items = []
        return contract_book(record, extract_marc21_v1(marc), items)

    async def recommendation_catalogue(self, required_ids: set[str], max_records: int = 60) -> list[dict[str, Any]]:
        """Candidate works plus every work in the reader's history, in contract form."""
        cached = _CATALOGUE_CACHE.get(self.base)
        if cached and time.time() - cached[0] < CATALOGUE_TTL:
            entries = cached[1]
        else:
            payload, _ = await self._get("biblios", {"_page": 1, "_per_page": max_records})
            records = [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []
            gate = asyncio.Semaphore(8)

            async def one(record):
                async with gate:
                    return await self._contract_entry(record)
            entries = [e for e in await asyncio.gather(*(one(r) for r in records)) if e]
            _CATALOGUE_CACHE[self.base] = (time.time(), entries)
        known = {e["book_id"] for e in entries}
        extra = []
        for book_id in sorted(i for i in required_ids if i.isdigit() and i not in known):
            try:
                record, _ = await self._get(f"biblios/{book_id}")
            except KohaError:
                continue
            if isinstance(record, dict) and (entry := await self._contract_entry(record)):
                extra.append(entry)
        return entries + extra

    async def build_recommendation_snapshot(self, borrower_id: str, interests: list[str] | None = None) -> dict[str, Any]:
        current = await self.get_current_checkouts(borrower_id)
        try:
            history = await self.get_history(borrower_id)
        except KohaError:
            history = []  # history permission/privacy may be off; current loans still help
        events = [{"book_id": h["book_id"], "checked_out_on": h["checkout_date"] or h["date"], "returned_on": h["return_date"], "status": "returned"} for h in history if h["book_id"] and (h["checkout_date"] or h["date"])]
        events += [{"book_id": c["book_id"], "checked_out_on": c["checkout_date"], "returned_on": None, "status": "active"} for c in current if c["book_id"] and c["checkout_date"]]
        catalogue = await self.recommendation_catalogue({e["book_id"] for e in events})
        return {"contract_version": "1.0", "catalogue": catalogue, "reader_history": events, "explicit_preferences": list(interests or [])}

    @staticmethod
    def _map_checkout(row: dict[str, Any], *, returned: bool = False) -> dict[str, Any]:
        item = row.get("item") if isinstance(row.get("item"), dict) else {}
        biblio = item.get("biblio") if isinstance(item.get("biblio"), dict) else {}
        biblio_id = item.get("biblio_id") or biblio.get("biblio_id") or row.get("biblio_id")
        item_id = row.get("item_id") or item.get("item_id")
        due_value = row.get("due_date")
        due_date = str(due_value)[:10] if due_value else None
        checked_in = row.get("checkin_date")
        try:
            due_at = datetime.fromisoformat(str(due_value).replace("Z", "+00:00")) if due_value else None
            if due_at and due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=timezone.utc)
            overdue = bool(due_at and due_at.date() < datetime.now(timezone.utc).date())
        except ValueError:
            overdue = False
        status = "Returned" if returned or checked_in else "Overdue" if overdue else "On track"
        authors = _as_list(biblio.get("author") or item.get("author"))
        return {
            "id": str(row.get("checkout_id") or item_id or ""),
            "book_id": str(biblio_id or item_id or ""),
            "item_id": item_id,
            "title": str(biblio.get("title") or item.get("title") or row.get("title") or "Library item"),
            "authors": authors,
            "checkout_date": str(row.get("checkout_date") or "")[:10],
            "due_date": due_date,
            "return_date": str(checked_in)[:10] if checked_in else None,
            "date": str(checked_in or row.get("checkout_date") or "")[:10],
            "subjects": _as_list(biblio.get("subject") or biblio.get("subjects")),
            "status": status,
        }

    async def _checkout_list(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for page in range(1, 101):
            page_params = {**(params or {}), "_page": page, "_per_page": 100}
            # Koha 26.06 rejects the combined nested value with 400; `item` is
            # the supported embed here, and biblio metadata is mapped separately.
            payload, headers = await self._get(path, page_params, request_headers={"x-koha-embed": "item"})
            if not isinstance(payload, list):
                raise KohaUpstreamError("Koha returned an unexpected checkout response", 502)
            rows.extend(row for row in payload if isinstance(row, dict))
            total = headers.get("x-total-count")
            has_next = 'rel="next"' in headers.get("link", "")
            if total and total.isdigit():
                if len(rows) >= int(total):
                    break
            elif not has_next:
                break
        return rows

    async def _map_checkout_rows(self, rows: list[dict[str, Any]], *, returned: bool = False, include_subjects: bool = False) -> list[dict[str, Any]]:
        mapped = []
        biblio_cache: dict[str, dict[str, Any]] = {}
        subject_cache: dict[str, list[str]] = {}
        for row in rows:
            checkout = dict(row)
            item = dict(row.get("item")) if isinstance(row.get("item"), dict) else {}
            biblio_id = item.get("biblio_id")
            if not biblio_id and isinstance(item.get("biblio"), dict):
                biblio_id = item["biblio"].get("biblio_id") or item["biblio"].get("id")
            biblio = item.get("biblio") if isinstance(item.get("biblio"), dict) else {}
            if biblio_id and not biblio.get("title"):
                key = str(biblio_id)
                if key not in biblio_cache:
                    payload, _ = await self._get(f"biblios/{quote(key, safe='')}")
                    if isinstance(payload, dict):
                        biblio_cache[key] = payload
                biblio = biblio_cache.get(key, biblio)
                item["biblio"] = biblio
            if include_subjects and biblio_id and not (biblio.get("subject") or biblio.get("subjects")):
                key = str(biblio_id)
                if key not in subject_cache:
                    try:
                        marc, _ = await self._get(f"biblios/{quote(key, safe='')}", request_headers={"Accept": "application/marc-in-json"})
                        subject_cache[key] = map_marc_subjects(marc)
                    except KohaError:
                        # Subjects enrich analytics but are optional; a MARC
                        # representation failure must not discard checkout counts.
                        subject_cache[key] = []
                if subject_cache[key]:
                    biblio["subjects"] = subject_cache[key]
            checkout["item"] = item
            mapped.append(self._map_checkout(checkout, returned=returned))
        return mapped

    async def get_current_checkouts(self, borrower_id: str, *, include_subjects: bool = False) -> list[dict[str, Any]]:
        if not borrower_id.isdigit():
            raise KohaNotFoundError("Signed-in Koha patron identity is invalid")
        rows = await self._checkout_list("checkouts", {"patron_id": int(borrower_id)})
        active = [row for row in rows if not row.get("checkin_date")]
        return await self._map_checkout_rows(active, include_subjects=include_subjects)

    async def get_history(self, borrower_id: str, *, include_subjects: bool = False) -> list[dict[str, Any]]:
        if not borrower_id.isdigit():
            raise KohaNotFoundError("Signed-in Koha patron identity is invalid")
        rows = await self._checkout_list(f"patrons/{quote(borrower_id, safe='')}/checkouts")
        returned = [row for row in rows if row.get("checkin_date")]
        return await self._map_checkout_rows(returned, returned=True, include_subjects=include_subjects)
