"""Server-side Koha REST API client and catalogue DTO mapping."""
import asyncio
import json
import time
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

    async def _get(self, path: str, params: dict[str, Any] | None = None, *, retry_auth: bool = True) -> tuple[Any, httpx.Headers]:
        auth = (self.username, self.password) if self.auth_method == "basic" else None
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
                response = await client.get(f"{self.base}/{path.lstrip('/')}", params=params, headers=await self._headers(), auth=auth)
            if response.status_code == 401 and retry_auth and self.auth_method == "oauth2":
                self._access_token = None
                self._token_expiry = 0
                return await self._get(path, params, retry_auth=False)
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

    async def get_book_items(self, book_id: str) -> list[dict[str, Any]]:
        if not book_id.isdigit():
            raise KohaNotFoundError()
        items: list[dict[str, Any]] = []
        for page in range(1, 101):
            payload, headers = await self._get(f"biblios/{quote(book_id, safe='')}/items", {"_page": page, "_per_page": 100})
            if not isinstance(payload, list):
                raise KohaUpstreamError("Koha returned an unexpected item response", 502)
            items.extend(map_item(row) for row in payload if isinstance(row, dict))
            total = headers.get("x-total-count")
            has_next = 'rel="next"' in headers.get("link", "")
            if total and total.isdigit():
                if len(items) >= int(total): break
            elif not has_next:
                break
        return items

    async def get_current_checkouts(self, borrower_id: str):
        raise KohaUpstreamError("Patron circulation is not enabled in the catalogue integration", 503)

    async def get_history(self, borrower_id: str):
        raise KohaUpstreamError("Patron history is not enabled in the catalogue integration", 503)
