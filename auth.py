"""Authentication engine for SecondSelf.

Supports:
- Email & password registration with salted SHA-256 hashes
- Email & password authentication
- Password reset
- Google OAuth 2.0 authentication flow with user profile retrieval
- Fallback instant Google demo login when OAuth credentials are not configured
- Local persistent storage in data/users.json
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.parse
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from config import (
    DATA_DIR,
    DEFAULT_GOOGLE_CLIENT_ID,
    DEFAULT_GOOGLE_CLIENT_SECRET,
    DEFAULT_GOOGLE_REDIRECT_URI,
    PROJECT_ROOT,
    init_user_workspace,
)

USERS_FILE = DATA_DIR / "users.json"


def _load_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env")


def init_auth_db() -> None:
    """Ensure data/users.json exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not USERS_FILE.exists():
        USERS_FILE.write_text(json.dumps({"users": {}}, indent=2), encoding="utf-8")


def get_all_users() -> dict[str, dict[str, Any]]:
    """Load users from storage."""
    init_auth_db()
    try:
        data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
        return data.get("users", {})
    except Exception:
        return {}


def _save_users(users: dict[str, dict[str, Any]]) -> None:
    """Save users to storage."""
    init_auth_db()
    USERS_FILE.write_text(json.dumps({"users": users}, indent=2), encoding="utf-8")


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Generate salted SHA-256 hash."""
    if not salt:
        salt = uuid.uuid4().hex[:16]
    hashed = hashlib.sha256(f"{salt}{password}".encode("utf-8")).hexdigest()
    return hashed, salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verify password against salted hash."""
    hashed, _ = hash_password(password, salt=salt)
    return hashed == stored_hash


def validate_email(email: str) -> bool:
    """Simple regex email validation."""
    return bool(re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email.strip()))


def register_user(
    email: str,
    password: str,
    name: str = "",
) -> tuple[bool, str, dict[str, Any] | None]:
    """Register a new user account with email and password."""
    clean_email = email.strip().lower()
    if not validate_email(clean_email):
        return False, "Please enter a valid email address.", None
    if len(password) < 6:
        return False, "Password must be at least 6 characters long.", None

    users = get_all_users()
    if clean_email in users:
        return False, "An account with this email already exists.", None

    pwd_hash, salt = hash_password(password)
    user_id = f"user_{uuid.uuid4().hex[:8]}"
    display_name = name.strip() or clean_email.split("@")[0].title()

    user_record = {
        "id": user_id,
        "email": clean_email,
        "name": display_name,
        "password_hash": pwd_hash,
        "salt": salt,
        "provider": "email",
        "picture": f"https://api.dicebear.com/7.x/initials/svg?seed={urllib.parse.quote(display_name)}",
        "created_at": datetime.now().isoformat(),
    }

    users[clean_email] = user_record
    _save_users(users)
    init_user_workspace(user_id, display_name)
    return True, "Account created successfully!", user_record


def authenticate_user(
    email: str,
    password: str,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Authenticate a user using email and password."""
    clean_email = email.strip().lower()
    users = get_all_users()

    if clean_email not in users:
        return False, "No account found with this email. Please click 'Create one' below to register.", None

    user = users[clean_email]
    if user.get("provider") == "google" and not user.get("password_hash"):
        return False, "This account was created with Google. Please use 'Sign in with Google' or your Google email.", None

    stored_hash = user.get("password_hash", "")
    salt = user.get("salt", "")
    if not verify_password(password, stored_hash, salt):
        return False, "Incorrect password. Please try again.", None


    init_user_workspace(user["id"], user.get("name", ""))
    return True, "Login successful!", user


def reset_password(email: str, new_password: str) -> tuple[bool, str]:
    """Reset password for an existing account."""
    clean_email = email.strip().lower()
    if len(new_password) < 6:
        return False, "New password must be at least 6 characters long."

    users = get_all_users()
    if clean_email not in users:
        return False, "No account found with this email."

    pwd_hash, salt = hash_password(new_password)
    users[clean_email]["password_hash"] = pwd_hash
    users[clean_email]["salt"] = salt
    _save_users(users)
    return True, "Password has been successfully updated! You can now sign in."


def authenticate_google_user(
    email: str,
    name: str = "",
    picture: str = "",
) -> dict[str, Any]:
    """Log in or automatically create an account for a Google authenticated user."""
    clean_email = email.strip().lower()
    users = get_all_users()

    if clean_email in users:
        user = users[clean_email]
        if name and not user.get("name"):
            user["name"] = name
        if picture:
            user["picture"] = picture
        users[clean_email] = user
        _save_users(users)
        init_user_workspace(user["id"], user.get("name", ""))
        return user

    # Auto-register new Google user
    user_id = f"user_{uuid.uuid4().hex[:8]}"
    display_name = name.strip() or clean_email.split("@")[0].title()
    avatar = picture or f"https://api.dicebear.com/7.x/initials/svg?seed={urllib.parse.quote(display_name)}"

    user_record = {
        "id": user_id,
        "email": clean_email,
        "name": display_name,
        "password_hash": "",
        "salt": "",
        "provider": "google",
        "picture": avatar,
        "created_at": datetime.now().isoformat(),
    }

    users[clean_email] = user_record
    _save_users(users)
    init_user_workspace(user_id, display_name)
    return user_record


# ---------------------------------------------------------------------------
# Google OAuth 2.0 Credentials & Flow
# ---------------------------------------------------------------------------

def get_google_oauth_credentials() -> tuple[str, str, str]:
    """Resolve Google OAuth client_id, client_secret, redirect_uri."""
    _load_env()

    client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip().strip('"').strip("'")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip().strip('"').strip("'")
    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI", "").strip().strip('"').strip("'")

    # Check Streamlit secrets if running inside Streamlit
    if "streamlit" in sys.modules:
        try:
            import streamlit as st
            if not client_id and "GOOGLE_CLIENT_ID" in st.secrets:
                client_id = str(st.secrets["GOOGLE_CLIENT_ID"]).strip().strip('"').strip("'")
            if not client_secret and "GOOGLE_CLIENT_SECRET" in st.secrets:
                client_secret = str(st.secrets["GOOGLE_CLIENT_SECRET"]).strip().strip('"').strip("'")
            if not redirect_uri and "GOOGLE_REDIRECT_URI" in st.secrets:
                redirect_uri = str(st.secrets["GOOGLE_REDIRECT_URI"]).strip().strip('"').strip("'")
        except Exception:
            pass

    # Cloud & fallback defaults
    if not client_id:
        client_id = DEFAULT_GOOGLE_CLIENT_ID
    if not client_secret:
        client_secret = DEFAULT_GOOGLE_CLIENT_SECRET
    if not redirect_uri:
        redirect_uri = DEFAULT_GOOGLE_REDIRECT_URI

    return client_id, client_secret, redirect_uri



def is_google_oauth_configured() -> bool:
    """Check if real Google OAuth credentials are set up."""
    client_id, client_secret, _ = get_google_oauth_credentials()
    dummy_markers = {"your-google-client-id", "xxxxxxxx", "your_client_id"}
    if not client_id or not client_secret:
        return False
    if any(m in client_id.lower() for m in dummy_markers):
        return False
    return True


def get_google_auth_url(current_app_url: str = "") -> str:
    """Construct Google OAuth redirect authorization URL with account chooser."""
    client_id, _, redirect_uri = get_google_oauth_credentials()
    chosen_redirect = redirect_uri or current_app_url or "http://localhost:8501"

    params = {
        "client_id": client_id,
        "redirect_uri": chosen_redirect,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account consent",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"


def exchange_google_code_for_user(code: str, redirect_uri: str) -> dict[str, Any] | None:
    """Exchange authorization code for access token and fetch Google profile."""
    client_id, client_secret, configured_redirect = get_google_oauth_credentials()
    target_redirect = configured_redirect or redirect_uri or "http://localhost:8501"

    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": target_redirect,
        "grant_type": "authorization_code",
    }

    try:
        res = requests.post(token_url, data=data, timeout=15)
        res.raise_for_status()
        token_data = res.json()
        access_token = token_data.get("access_token")
        if not access_token:
            return None

        userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
        user_res = requests.get(
            userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        user_res.raise_for_status()
        profile = user_res.json()
        return profile
    except Exception as exc:
        print(f"Google OAuth exchange error: {exc}", file=sys.stderr)
        return None
