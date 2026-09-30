"""Authentication and Session Management Module."""

import time
from typing import Optional, Dict


class AuthService:
    """Handles JWT tokens, cookie extraction, and session verification."""

    def __init__(self, secret_key: str = "supersecret"):
        self.secret_key = secret_key

    def create_token(self, user_id: str, expires_in_sec: int = 3600) -> str:
        """Create a mock JWT session token."""
        expiry = int(time.time()) + expires_in_sec
        return f"{user_id}:{expiry}:{self.secret_key}"

    def extract_token_from_cookies(self, cookies: Dict[str, str]) -> Optional[str]:
        """Extract session token from request cookies.
        
        BUG 1: Looks for 'access_token' instead of checking both 'auth_jwt' and 'session_token',
        causing users to be logged out on page refresh when the browser sends 'auth_jwt'.
        """
        # Buggy implementation: only looks for wrong key 'access_token'
        return cookies.get("access_token")

    def verify_token(self, token: Optional[str]) -> Optional[str]:
        """Verify token and return user_id if valid."""
        if not token:
            return None
        parts = token.split(":")
        if len(parts) != 3:
            return None
        user_id, expiry_str, secret = parts
        try:
            expiry = int(expiry_str)
        except ValueError:
            return None

        if secret != self.secret_key:
            return None
        if time.time() > expiry:
            return None  # expired
        return user_id

    def authenticate_request(self, cookies: Dict[str, str]) -> Optional[str]:
        """Verify user session from cookies."""
        token = self.extract_token_from_cookies(cookies)
        return self.verify_token(token)
