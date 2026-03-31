"""Utility helpers for the I.D.R.A. desktop simulator."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import subprocess
import webbrowser
from typing import Tuple
from urllib.parse import parse_qs, urlparse


def parse_code_input(raw: str) -> Tuple[str, str]:
    """Extract OAuth `code` and optional `state` from raw input.

    Accepts:
    - full callback URL
    - query string (`code=...&state=...`)
    - plain code
    """
    value = (raw or "").strip()
    if not value:
        return "", ""
    if "?" in value and "code=" in value:
        try:
            parsed = urlparse(value)
            query = parse_qs(parsed.query or "")
            code = (query.get("code") or [""])[0].strip()
            state = (query.get("state") or [""])[0].strip()
            return code, state
        except Exception:
            return "", ""
    if "code=" in value:
        try:
            query = parse_qs(value)
            code = (query.get("code") or [""])[0].strip()
            state = (query.get("state") or [""])[0].strip()
            return code, state
        except Exception:
            return "", ""
    return value, ""


def generate_pkce() -> Tuple[str, str]:
    """Generate PKCE code verifier and S256 challenge."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return verifier, challenge


def socketio_path_from_server_url(server_url: str) -> str:
    """Build Socket.IO path from base server URL.

    Examples:
    - `http://localhost:3000` -> `socket.io`
    - `https://host/idra` -> `idra/socket.io`
    """
    try:
        parsed = urlparse(server_url.strip())
        base_path = (parsed.path or "").strip()
    except Exception:
        return "socket.io"
    if not base_path or base_path == "/":
        return "socket.io"
    prefix = base_path.strip("/")
    if not prefix:
        return "socket.io"
    return f"{prefix}/socket.io"


def open_browser_url(url: str) -> bool:
    """Open URL in default browser with platform fallbacks."""
    target = str(url or "").strip()
    if not target:
        return False

    try:
        if webbrowser.open(target):
            return True
    except Exception:
        pass

    try:
        if os.name == "nt":
            os.startfile(target)  # type: ignore[attr-defined]
            return True
    except Exception:
        pass

    try:
        if "WSL_DISTRO_NAME" in os.environ:
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-Command", "Start-Process", target]
            )
            return True
    except Exception:
        pass

    try:
        subprocess.Popen(["xdg-open", target])
        return True
    except Exception:
        return False
