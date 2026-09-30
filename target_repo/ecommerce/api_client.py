"""API Client for internal and external microservices."""

from typing import Dict, Any, Optional


class ApiClient:
    """HTTP client simulating microservice communication."""

    def __init__(self, base_url: str = "https://api.shop.local"):
        self.base_url = base_url.rstrip("/")

    def build_headers(self, token: Optional[str] = None) -> Dict[str, str]:
        """Build request headers.
        
        BUG 2: Missing 'Authorization: Bearer <token>' header when token is supplied.
        """
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        # Bug: token is received but omitted from headers!
        return headers

    def get_order_endpoint(self, order_id: str) -> str:
        """Return the API endpoint for an order.
        
        BUG 2 (endpoint): Points to deprecated endpoint '/v1/order' instead of '/api/v2/orders'.
        """
        return f"{self.base_url}/v1/order/{order_id}"

    def prepare_request(self, order_id: str, token: str) -> Dict[str, Any]:
        """Prepare complete request configuration."""
        endpoint = self.get_order_endpoint(order_id)
        headers = self.build_headers(token)
        return {
            "url": endpoint,
            "headers": headers,
            "method": "GET"
        }
