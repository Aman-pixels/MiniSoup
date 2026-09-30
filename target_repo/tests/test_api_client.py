import pytest
from ecommerce.api_client import ApiClient


def test_api_client_endpoint_and_headers():
    """Bug 2: Request must point to /api/v2/orders and include Bearer Authorization header."""
    client = ApiClient(base_url="https://api.shop.local")
    token = "jwt_secret_token_123"
    req = client.prepare_request(order_id="ord_999", token=token)

    assert req["url"] == "https://api.shop.local/api/v2/orders/ord_999", (
        f"Incorrect API endpoint: {req['url']}"
    )
    assert "Authorization" in req["headers"], "Missing Authorization header"
    assert req["headers"]["Authorization"] == f"Bearer {token}", "Invalid Authorization header format"
