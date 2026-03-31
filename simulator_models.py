"""Data models for the I.D.R.A. desktop simulator."""

from __future__ import annotations

from dataclasses import dataclass, field

import socketio


@dataclass
class SimClient:
    """Represents one simulated plugin client."""

    name: str
    server_url: str
    socketio_path: str
    is_fake: bool = False
    sio: socketio.Client = field(
        default_factory=lambda: socketio.Client(
            logger=False,
            engineio_logger=False,
            reconnection=False,
        )
    )
    connected: bool = False
    authenticated: bool = False
    session_token: str = ""
    flow_id: str = ""
    flow_state: str = ""
    code_verifier: str = ""
    spoof_ip: str = ""
