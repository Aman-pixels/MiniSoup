import pytest
from ecommerce.auth import AuthService


def test_auth_token_creation_and_verification():
    auth = AuthService(secret_key="test-secret")
    token = auth.create_token(user_id="user_123", expires_in_sec=60)
    assert auth.verify_token(token) == "user_123"


def test_page_refresh_jwt_cookie_authentication():
    """Bug 1: On page refresh, browser sends cookies with 'auth_jwt' key.
    
    The user must NOT be logged out.
    """
    auth = AuthService(secret_key="test-secret")
    token = auth.create_token(user_id="user_123", expires_in_sec=3600)
    
    # Request cookie sent on page refresh
    cookies = {"auth_jwt": token}
    user_id = auth.authenticate_request(cookies)
    
    assert user_id == "user_123", "User was logged out on page refresh due to cookie key mismatch"
