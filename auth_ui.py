"""Authentication UI for SecondSelf.

Renders the stunning login / registration interface matching login.html & loginpage.css:
- Conic-gradient spinning border animation
- Frosted glassmorphism dark card (#272727)
- Custom user logo badge
- Email & password sign-in
- New account registration ("Sign up, it's free!")
- Password reset ("Forgot password?")
- Fully functional Google OAuth 2.0 sign-in with instant demo fallback
- Integrated user profile and logout controls
"""

from __future__ import annotations

import os
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

from auth import (
    authenticate_google_user,
    authenticate_user,
    exchange_google_code_for_user,
    get_google_auth_url,
    is_google_oauth_configured,
    register_user,
    reset_password,
)
from config import PROJECT_ROOT

CSS_FILE = PROJECT_ROOT / "loginpage.css"

_GOOGLE_SVG = """<svg class="icon" viewBox="-3 0 262 262" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid" fill="#000000" style="height:16px;vertical-align:middle;margin-right:8px;">
  <path d="M255.878 133.451c0-10.734-.871-18.567-2.756-26.69H130.55v48.448h71.947c-1.45 12.04-9.283 30.172-26.69 42.356l-.244 1.622 38.755 30.023 2.685.268c24.659-22.774 38.875-56.282 38.875-96.027" fill="#4285F4"></path>
  <path d="M130.55 261.1c35.248 0 64.839-11.605 86.453-31.622l-41.196-31.913c-11.024 7.688-25.82 13.055-45.257 13.055-34.523 0-63.824-22.773-74.269-54.25l-1.531.13-40.298 31.187-.527 1.465C35.393 231.798 79.49 261.1 130.55 261.1" fill="#34A853"></path>
  <path d="M56.281 156.37c-2.756-8.123-4.351-16.827-4.351-25.82 0-8.994 1.595-17.697 4.206-25.82l-.073-1.73L15.26 71.312l-1.335.635C5.077 89.644 0 109.517 0 130.55s5.077 40.905 13.925 58.602l42.356-32.782" fill="#FBBC05"></path>
  <path d="M130.55 50.479c24.514 0 41.05 10.589 50.479 19.438l36.844-35.974C195.245 12.91 165.798 0 130.55 0 79.49 0 35.393 29.301 13.925 71.947l42.211 32.783c10.59-31.477 39.891-54.251 74.414-54.251" fill="#EB4335"></path>
</svg>"""


def _get_login_css() -> str:
    """Load loginpage.css and bind it seamlessly to Streamlit auth container."""
    raw_user_css = ""
    if CSS_FILE.exists():
        raw_user_css = CSS_FILE.read_text(encoding="utf-8")

    return f"""
<style>
/* Base page styling - transparent Streamlit containers so WebGL canvas shows through */
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stBottom"], .main {{
    background: transparent !important;
    background-color: transparent !important;
}}

body {{
    background-color: #170E17 !important;
}}

/* Perfectly center the login container vertically & horizontally */
.block-container {{
    min-height: 90vh !important;
    display: flex !important;
    flex-direction: column !important;
    justify-content: center !important;
    align-items: center !important;
    padding-top: 1rem !important;
    padding-bottom: 1rem !important;
    max-width: 480px !important;
    position: relative !important;
    z-index: 10 !important;
}}

/* Hide sidebar and chrome clutter during authentication */
[data-testid="stSidebar"],
[data-testid="collapsedControl"],
[data-testid="stToolbar"],
footer {{
    display: none !important;
}}

/* Hide component iframe container so it takes 0px */
iframe[title="streamlit_components_v1.html"],
[data-testid="stCustomComponentV1"] {{
    position: fixed !important;
    top: 0 !important;
    left: 0 !important;
    width: 0 !important;
    height: 0 !important;
    border: none !important;
    opacity: 0 !important;
    pointer-events: none !important;
}}

/* User provided loginpage.css declarations */
{raw_user_css}

/* Vertical rectangular login card matching firstpage.12 & loginpage.css */
[data-testid="stForm"] {{
    --form-width: 345px;
    --login-box-color: rgba(30, 22, 32, 0.82);
    --input-color: #2e1d2f;
    --button-color: #3b223c;
    --footer-color: rgba(255, 255, 255, 0.58);
    position: relative !important;
    overflow: hidden !important;
    background: var(--login-box-color) !important;
    backdrop-filter: blur(20px) !important;
    -webkit-backdrop-filter: blur(20px) !important;
    border-radius: 24px !important;
    width: 100% !important;
    max-width: var(--form-width) !important;
    margin: auto !important;
    padding: 30px 26px !important;
    border: 1px solid rgba(188, 123, 185, 0.25) !important;
    box-shadow:
        0 12px 40px rgba(0, 0, 0, 0.6),
        0 0 24px rgba(188, 123, 185, 0.18),
        inset 0 40px 60px -8px rgba(188, 123, 185, 0.12),
        inset 4px 0 12px -6px rgba(188, 123, 185, 0.12),
        inset 0 0 12px -4px rgba(255, 255, 255, 0.12) !important;
    z-index: 10 !important;
}}

/* Rotating conic spinning border effect with matching purple accent */
[data-testid="stForm"]::before {{
    content: "" !important;
    position: absolute !important;
    inset: -120px !important;
    z-index: 0 !important;
    background: conic-gradient(
        from 45deg,
        transparent 70%,
        #BC7BB9 88%,
        #ffffff 100%
    ) !important;
    animation: spin 4s ease-in-out infinite !important;
    pointer-events: none !important;
}}

@keyframes spin {{
    100% {{
        transform: rotate(360deg);
    }}
}}

/* Inner card background layer with frosted blur */
[data-testid="stForm"]::after {{
    content: "" !important;
    position: absolute !important;
    inset: 2px !important;
    background: rgba(26, 17, 27, 0.88) !important;
    backdrop-filter: blur(20px) !important;
    -webkit-backdrop-filter: blur(20px) !important;
    border-radius: 22px !important;
    z-index: 1 !important;
    pointer-events: none !important;
}}

/* Raise interactive elements above spinning gradient and background */
[data-testid="stForm"] > * {{
    position: relative !important;
    z-index: 2 !important;
}}

/* Inputs */
[data-testid="stForm"] .stTextInput {
    margin-bottom: 6px !important;
}

[data-testid="stForm"] .stTextInput input {
    background-color: var(--input-color, #2e1d2f) !important;
    color: white !important;
    border-radius: 12px !important;
    border: 1px solid rgba(188, 123, 185, 0.25) !important;
    padding: 10px 14px !important;
    font-size: 14px !important;
    outline: none !important;
    box-shadow: none !important;
}

[data-testid="stForm"] .stTextInput input:focus {
    border-color: #BC7BB9 !important;
    box-shadow: 0 0 10px rgba(188, 123, 185, 0.35) !important;
}

[data-testid="stForm"] .stTextInput label {
    display: none !important;
}

/* Primary Submit Button */
[data-testid="stForm"] button[kind="primaryFormSubmit"],
[data-testid="stForm"] button[kind="secondaryFormSubmit"],
[data-testid="stForm"] .stButton > button {
    width: 100% !important;
    height: 40px !important;
    border: none !important;
    border-radius: 20px !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    cursor: pointer !important;
    background: linear-gradient(135deg, #48234a 0%, #311634 100%) !important;
    color: white !important;
    transition: 0.3s !important;
    box-shadow:
        inset 0px 3px 6px -4px rgba(255, 255, 255, 0.6),
        inset 0px -3px 6px -2px rgba(0, 0, 0, 0.8),
        0 4px 12px rgba(0, 0, 0, 0.35) !important;
    margin-top: 6px !important;
}

[data-testid="stForm"] button[kind="primaryFormSubmit"]:hover,
[data-testid="stForm"] button[kind="secondaryFormSubmit"]:hover,
[data-testid="stForm"] .stButton > button:hover {
    background: linear-gradient(135deg, #663269 0%, #48234a 100%) !important;
    box-shadow:
        inset 0px 3px 6px rgba(255, 255, 255, 0.6),
        inset 0px -3px 6px rgba(0, 0, 0, 0.8),
        0px 0px 14px rgba(188, 123, 185, 0.4) !important;
    color: white !important;
}

/* Google Sign In Button */
.google-sign-in-btn {
    display: flex !important;
    justify-content: center !important;
    align-items: center !important;
    gap: 10px !important;
    width: 100% !important;
    height: 40px !important;
    border-radius: 20px !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    cursor: pointer !important;
    background: linear-gradient(135deg, #2e1d2f 0%, #201321 100%) !important;
    border: 1px solid rgba(188, 123, 185, 0.25) !important;
    color: white !important;
    text-decoration: none !important;
    transition: 0.3s !important;
    box-shadow:
        inset 0px 3px 6px -4px rgba(255, 255, 255, 0.5),
        inset 0px -3px 6px -2px rgba(0, 0, 0, 0.8) !important;
    margin-top: 10px !important;
    margin-bottom: 6px !important;
}

.google-sign-in-btn:hover {
    background: linear-gradient(135deg, #492b4b 0%, #301b33 100%) !important;
    border-color: #BC7BB9 !important;
    color: white !important;
    text-decoration: none !important;
    box-shadow:
        inset 0px 3px 6px rgba(255, 255, 255, 0.6),
        inset 0px -3px 6px rgba(0, 0, 0, 0.8),
        0px 0px 12px rgba(188, 123, 185, 0.35) !important;
}

.footer-nav {{
    width: 100%;
    text-align: left;
    color: var(--footer-color, rgba(255, 255, 255, 0.55));
    font-size: 12px;
    margin-top: 14px;
    line-height: 1.6;
}}

.footer-nav a {{
    position: relative;
    color: var(--footer-color, rgba(255, 255, 255, 0.55));
    font-weight: 600;
    text-decoration: none;
    transition: color 0.3s ease;
}}

.footer-nav a:hover {{
    color: #ffffff;
}}
</style>
"""


def check_and_handle_google_redirect() -> bool:
    """Check if the page was opened with a Google OAuth code parameter or demo."""
    # 1. Real OAuth Code
    code = st.query_params.get("code")
    if code:
        with st.spinner("Authenticating with Google..."):
            profile = exchange_google_code_for_user(code, "")
            if profile and profile.get("email"):
                user = authenticate_google_user(
                    email=profile["email"],
                    name=profile.get("name", ""),
                    picture=profile.get("picture", ""),
                )
                st.session_state["authenticated_user"] = user
                st.query_params.clear()
                st.toast(f"Welcome back, {user['name']}!", icon="👋")
                st.rerun()
                return True
            else:
                st.error("Google authentication failed. Please try again.")
                st.query_params.clear()

    # 2. Missing OAuth Notification
    if st.query_params.get("missing_google"):
        st.warning("⚠️ Google OAuth is not configured on this server. Please add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in Streamlit Secrets or .env.")
        st.query_params.clear()

    return False


def get_current_user() -> dict[str, Any] | None:
    """Return currently authenticated user from session state."""
    return st.session_state.get("authenticated_user")


def logout_user() -> None:
    """Log out current user and return to login screen."""
    st.session_state.pop("authenticated_user", None)
    st.query_params.clear()
    st.rerun()


def render_login_page() -> None:
    """Render the full login / registration interface."""
    # Handle incoming OAuth redirect or demo click first
    if check_and_handle_google_redirect():
        return

    # Check mode query param
    param_mode = st.query_params.get("auth_mode")
    if param_mode in ("signin", "signup", "forgot"):
        st.session_state["auth_mode"] = param_mode

    if "auth_mode" not in st.session_state:
        st.session_state["auth_mode"] = "signin"
    mode = st.session_state["auth_mode"]

    # Inject visual styles
    st.markdown(_get_login_css(), unsafe_allow_html=True)

    # Inject live WebGL particle drift background from particle_drift.html
    drift_file = PROJECT_ROOT / "particle_drift.html"
    if drift_file.exists():
        drift_code = drift_file.read_text(encoding="utf-8")
        components.html(drift_code, height=0, width=0)

    if mode == "signin":
        _render_signin_card()
    elif mode == "signup":
        _render_signup_card()
    else:
        _render_forgot_card()


def _render_signin_card() -> None:
    """Render Sign In form with Email, Password, and Google Auth inside the animated card."""
    with st.form("signin_form", clear_on_submit=False):
        # Card Header: Logo & Title
        st.markdown(
            """
            <div style="display:flex;flex-direction:column;align-items:center;margin-bottom:12px;">
              <div class="logo"></div>
              <span class="header">Welcome Back!</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        email = st.text_input("Email", placeholder="Email", key="login_email", label_visibility="collapsed")
        password = st.text_input("Password", type="password", placeholder="Password", key="login_password", label_visibility="collapsed")

        submitted = st.form_submit_button("Sign In", use_container_width=True)

        if submitted:
            if not email or not password:
                st.warning("Please enter your email and password.")
            else:
                success, msg, user = authenticate_user(email, password)
                if success and user:
                    st.session_state["authenticated_user"] = user
                    st.toast(f"Welcome back, {user['name']}!", icon="👋")
                    st.rerun()
                else:
                    st.error(msg)

        # Google Sign In Button
        google_configured = is_google_oauth_configured()
        if google_configured:
            target_url = get_google_auth_url()
        else:
            target_url = "?missing_google=1"

        st.markdown(
            f"""
            <a href="{target_url}" target="_self" class="google-sign-in-btn">
              {_GOOGLE_SVG}
              <span>Sign in with Google</span>
            </a>
            """,
            unsafe_allow_html=True,
        )

        # Footer links matching login.html
        st.markdown(
            """
            <p class="footer-nav">
              Don't have an account?
              <a href="?auth_mode=signup" target="_self">Sign up, it's free!</a>
              <br />
              <a href="?auth_mode=forgot" target="_self">Forgot password?</a>
            </p>
            """,
            unsafe_allow_html=True,
        )


def _render_signup_card() -> None:
    """Render New Account Creation form inside the animated card."""
    with st.form("signup_form", clear_on_submit=False):
        # Card Header
        st.markdown(
            """
            <div style="display:flex;flex-direction:column;align-items:center;margin-bottom:12px;">
              <div class="logo"></div>
              <span class="header">Create Account</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        name = st.text_input("Full Name", placeholder="Full Name (e.g. Ayush Patil)", key="reg_name", label_visibility="collapsed")
        email = st.text_input("Email", placeholder="Email address", key="reg_email", label_visibility="collapsed")
        password = st.text_input("Password", type="password", placeholder="Password (min 6 chars)", key="reg_password", label_visibility="collapsed")
        confirm = st.text_input("Confirm Password", type="password", placeholder="Confirm Password", key="reg_confirm", label_visibility="collapsed")

        submitted = st.form_submit_button("Create Account", use_container_width=True)

        if submitted:
            if not email or not password:
                st.warning("Please fill in all required fields.")
            elif password != confirm:
                st.error("Passwords do not match.")
            else:
                success, msg, user = register_user(email, password, name=name)
                if success and user:
                    st.session_state["authenticated_user"] = user
                    st.toast("Account created successfully!", icon="🎉")
                    st.rerun()
                else:
                    st.error(msg)

        # Google Sign Up Button
        google_configured = is_google_oauth_configured()
        if google_configured:
            target_url = get_google_auth_url()
        else:
            target_url = "?missing_google=1"

        st.markdown(
            f"""
            <a href="{target_url}" target="_self" class="google-sign-in-btn">
              {_GOOGLE_SVG}
              <span>Sign up with Google</span>
            </a>
            """,
            unsafe_allow_html=True,
        )

        # Footer link
        st.markdown(
            """
            <p class="footer-nav">
              Already have an account?
              <a href="?auth_mode=signin" target="_self">Sign in!</a>
            </p>
            """,
            unsafe_allow_html=True,
        )


def _render_forgot_card() -> None:
    """Render Password Reset form inside the animated card."""
    with st.form("forgot_form", clear_on_submit=False):
        # Card Header
        st.markdown(
            """
            <div style="display:flex;flex-direction:column;align-items:center;margin-bottom:12px;">
              <div class="logo"></div>
              <span class="header">Reset Password</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        email = st.text_input("Email", placeholder="Registered Email", key="reset_email", label_visibility="collapsed")
        new_pwd = st.text_input("New Password", type="password", placeholder="New Password (min 6 chars)", key="reset_pwd", label_visibility="collapsed")
        confirm_pwd = st.text_input("Confirm New Password", type="password", placeholder="Confirm New Password", key="reset_confirm", label_visibility="collapsed")

        submitted = st.form_submit_button("Reset Password", use_container_width=True)

        if submitted:
            if not email or not new_pwd:
                st.warning("Please fill in all fields.")
            elif new_pwd != confirm_pwd:
                st.error("Passwords do not match.")
            else:
                success, msg = reset_password(email, new_pwd)
                if success:
                    st.success(msg)
                    st.session_state["auth_mode"] = "signin"
                    st.query_params.clear()
                    st.rerun()
                else:
                    st.error(msg)

        # Footer link
        st.markdown(
            """
            <p class="footer-nav">
              Remembered your password?
              <a href="?auth_mode=signin" target="_self">Sign in!</a>
            </p>
            """,
            unsafe_allow_html=True,
        )
