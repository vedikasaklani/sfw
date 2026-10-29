import base64

import httpx
import pytest

from app.integrations.koha import (
    KohaAuthenticationError,
    KohaClient,
    KohaNotFoundError,
    KohaUpstreamError,
    map_biblio,
    map_item,
)


def test_auth_configuration_rejects_missing_oauth_credentials():
    with pytest.raises(KohaUpstreamError, match="KOHA_CLIENT_ID"):
        KohaClient("http://koha.test/api/v1", "oauth2")


@pytest.mark.asyncio
async def test_oauth_search_maps_records_and_keeps_credentials_server_side():
    seen = []

    async def handler(request):
        seen.append(request)
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token":"sensitive-token", "expires_in":300})
        return httpx.Response(200, json=[{"biblio_id":17,"title":"Forest Studies","author":"A. Reader","isbn":"123","subject":["Nature"],"publication_year":"2020"}], headers={"x-total-count":"3"})

    client = KohaClient("http://koha.test/api/v1", "oauth2", "client-id", "client-secret", transport=httpx.MockTransport(handler))
    result = await client.search_catalogue("Forest", page=2, page_size=1)
    assert result["total"] == 3
    assert result["items"][0] == {
        "id":"17", "title":"Forest Studies", "authors":["A. Reader"], "subjects":["Nature"],
        "year":"2020", "isbn":"123", "description":"", "availability":"Unknown", "copies":None, "source":"koha",
    }
    assert seen[1].headers["authorization"] == "Bearer sensitive-token"
    assert seen[1].url.params.get("_page") == "2"
    assert seen[1].url.params.get("_per_page") == "1"
    assert '"-or"' in seen[1].url.params.get("q", "")
    assert "client-secret" not in repr(result)


@pytest.mark.asyncio
async def test_detail_loads_biblio_and_actual_item_statuses():
    async def handler(request):
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token":"token", "expires_in":300})
        if request.url.path.endswith("/biblios/12"):
            return httpx.Response(200, json={"biblio_id":12,"title":"Reading","author":"Writer"})
        if request.url.path.endswith("/biblios/12/items"):
            return httpx.Response(200, json=[{"item_id":31,"home_library_id":"MAIN","effective_not_for_loan_status":0}, {"item_id":32,"home_library_id":"MAIN","checked_out_date":"2026-10-01"}])
        raise AssertionError(request.url)

    client = KohaClient("http://koha.test/api/v1", "oauth2", "id", "secret", transport=httpx.MockTransport(handler))
    result = await client.get_book("12")
    assert result["id"] == "12"
    assert result["availability"] == "Available"
    assert result["copies"] == 2
    assert [item["status"] for item in result["items"]] == ["Available", "On loan"]


@pytest.mark.asyncio
async def test_items_follow_koha_pagination_links():
    async def handler(request):
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token":"token", "expires_in":300})
        if request.url.path.endswith("/items") and request.url.params.get("_page") == "1":
            return httpx.Response(200, json=[{"item_id":1,"effective_not_for_loan_status":0}], headers={"link": '<http://koha.test/api/v1/biblios/8/items?_page=2>; rel="next"'})
        return httpx.Response(200, json=[{"item_id":2,"checked_out_date":"2026-10-01"}])

    client = KohaClient("http://koha.test/api/v1", "oauth2", "id", "secret", transport=httpx.MockTransport(handler))
    items = await client.get_book_items("8")
    assert [item["item_id"] for item in items] == [1, 2]


@pytest.mark.asyncio
async def test_oauth_token_is_renewed_after_upstream_401():
    tokens = []
    used = []

    async def handler(request):
        if request.url.path.endswith("/oauth/token"):
            token = f"token-{len(tokens) + 1}"
            tokens.append(token)
            return httpx.Response(200, json={"access_token":token,"expires_in":300})
        used.append(request.headers.get("authorization"))
        if len(used) == 1:
            return httpx.Response(401, json={"error":"expired"})
        return httpx.Response(200, json=[])

    client = KohaClient("http://koha.test/api/v1", "oauth2", "id", "secret", transport=httpx.MockTransport(handler))
    assert (await client.search_catalogue())["items"] == []
    assert tokens == ["token-1", "token-2"]
    assert used == ["Bearer token-1", "Bearer token-2"]


@pytest.mark.asyncio
async def test_empty_results_and_missing_record_are_normalized():
    async def handler(request):
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token":"token", "expires_in":300})
        if request.url.path.endswith("/biblios/9"):
            return httpx.Response(404, json={"error":"missing"})
        return httpx.Response(200, json=[])

    client = KohaClient("http://koha.test/api/v1", "oauth2", "id", "secret", transport=httpx.MockTransport(handler))
    assert (await client.search_catalogue())["items"] == []
    with pytest.raises(KohaNotFoundError):
        await client.get_book("9")


@pytest.mark.asyncio
async def test_patron_password_validation_posts_credentials_only_to_koha():
    seen = []
    async def handler(request):
        seen.append(request)
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token":"service-token", "expires_in":300})
        return httpx.Response(201, json={"patron_id":23,"userid":"reader","cardnumber":"1234"})
    client = KohaClient("http://koha.test/api/v1", "oauth2", "id", "secret", transport=httpx.MockTransport(handler))
    identity = await client.validate_patron_password("reader", "patron-password")
    assert identity == {"patron_id":"23", "userid":"reader"}
    assert seen[-1].url.path.endswith("/auth/password/validation")
    assert seen[-1].headers["authorization"] == "Bearer service-token"
    assert seen[-1].read() == b'{"identifier":"reader","password":"patron-password"}'


@pytest.mark.asyncio
async def test_patron_permission_failure_is_actionable_and_does_not_expose_koha_body():
    async def handler(request):
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token":"service-token", "expires_in":300})
        return httpx.Response(403, json={"error":"private upstream response"})
    client = KohaClient("http://koha.test/api/v1", "oauth2", "id", "secret", transport=httpx.MockTransport(handler))
    with pytest.raises(KohaUpstreamError, match="api_validate_password") as error:
        await client.validate_patron_password("reader", "pass")
    assert "private upstream response" not in str(error.value)


@pytest.mark.asyncio
async def test_auth_failure_and_timeout_are_safe_errors():
    async def unauthorized(request):
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token":"token", "expires_in":300})
        return httpx.Response(403, json={"error":"private Koha detail"})

    client = KohaClient("http://koha.test/api/v1", "oauth2", "id", "secret", transport=httpx.MockTransport(unauthorized))
    with pytest.raises(KohaAuthenticationError) as error:
        await client.search_catalogue()
    assert "private Koha detail" not in str(error.value)

    async def timeout(request):
        if request.url.path.endswith("/oauth/token"):
            return httpx.Response(200, json={"access_token":"token", "expires_in":300})
        raise httpx.ReadTimeout("sensitive request url", request=request)

    timed = KohaClient("http://koha.test/api/v1", "oauth2", "id", "secret", transport=httpx.MockTransport(timeout))
    with pytest.raises(KohaUpstreamError, match="timed out"):
        await timed.search_catalogue()


@pytest.mark.asyncio
async def test_basic_authorization_and_unknown_item_state():
    value = base64.b64encode(b"reader:pw").decode()
    async def handler(request):
        assert request.headers["authorization"] == f"Basic {value}"
        return httpx.Response(200, json=[])
    client = KohaClient("http://koha.test/api/v1", "basic", username="reader", password="pw", transport=httpx.MockTransport(handler))
    assert await client.search_catalogue() == {"items":[], "total":0, "page":1, "page_size":20}
    assert map_item({"item_id":2})["status"] == "Unknown"
    assert map_item({"item_id":3,"effective_not_for_loan_status":0})["status"] == "Available"
    assert map_biblio({"biblio_id":1,"title":None})["title"] == "Untitled record"
