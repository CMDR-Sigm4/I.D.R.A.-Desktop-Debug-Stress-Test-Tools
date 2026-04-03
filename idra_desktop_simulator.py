#!/usr/bin/env python3
"""I.D.R.A. Desktop Debug Simulator.

Desktop alternative to the `/debug` web page for high-connection simulations.
- No browser websocket fan-out bottleneck for simulated clients.
- Supports target URL override.
- Supports Frontier OAuth flow for the selected client.
"""

from __future__ import annotations

import json
import queue
import random
import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Optional

from simulator_models import SimClient
from simulator_utils import (
    generate_pkce,
    open_browser_url,
    parse_code_input,
    socketio_path_from_server_url,
)

EVENT_TYPES = ["interdiction", "weapon_attack", "player_kill", "ramming_kill"]


class DesktopSimulatorApp:
    """Desktop simulator that emulates multiple plugin clients over Socket.IO."""

    def __init__(self, root: tk.Tk) -> None:
        """Initialize runtime state, variables, and user interface."""
        self.root = root
        self.root.title("I.D.R.A. Desktop Debug Simulator")
        self.root.geometry("1320x860")
        self.palette = {
            "bg": "#0f131a",
            "surface": "#151c27",
            "surface_alt": "#1b2433",
            "border": "#30435e",
            "text": "#d7e2f0",
            "muted": "#8fb5ff",
            "accent": "#f7b267",
            "accent_hover": "#ffbf7f",
            "input_bg": "#0f1622",
            "log_bg": "#0d1117",
        }
        self._apply_elite_theme()

        self.ui_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self.clients: dict[str, SimClient] = {}
        self.selected_client_name: str = ""
        self.load_running = False
        self.load_stop_token = 0
        self.fake_client_names: set[str] = set()
        self.created_channels: set[str] = set()
        self.preview_window: Optional[tk.Toplevel] = None
        self.preview_hide_job: Optional[str] = None

        self.server_url_var = tk.StringVar(value="http://localhost:3000")
        self.channel_var = tk.StringVar(value="global")
        self.password_var = tk.StringVar(value="")
        self.target_var = tk.StringVar(value="TestGanker")
        self.system_var = tk.StringVar(value="Sol")
        self.auth_code_var = tk.StringVar(value="")
        self.use_test_login_for_bots_var = tk.IntVar(value=1)
        self.fake_batch_size_var = tk.StringVar(value="10")

        self._build_ui()
        self.root.after(60, self._drain_ui_queue)

    def _apply_elite_theme(self) -> None:
        """Apply simulator-wide ttk theme and color palette."""
        self.root.configure(background=self.palette["bg"])
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(
            ".",
            background=self.palette["bg"],
            foreground=self.palette["text"],
            fieldbackground=self.palette["input_bg"],
            bordercolor=self.palette["border"],
        )
        style.configure("TFrame", background=self.palette["bg"])
        style.configure(
            "TLabelframe",
            background=self.palette["surface"],
            foreground=self.palette["accent"],
            bordercolor=self.palette["border"],
            relief="solid",
            borderwidth=1,
        )
        style.configure(
            "TLabelframe.Label",
            background=self.palette["surface"],
            foreground=self.palette["accent"],
        )
        style.configure("TLabel", background=self.palette["bg"], foreground=self.palette["text"])
        style.configure(
            "TButton",
            background=self.palette["surface_alt"],
            foreground=self.palette["accent"],
            bordercolor=self.palette["border"],
            focuscolor=self.palette["border"],
            relief="flat",
            padding=5,
        )
        style.map(
            "TButton",
            background=[("active", self.palette["surface"]), ("pressed", self.palette["surface"])],
            foreground=[("active", self.palette["accent_hover"]), ("pressed", self.palette["accent_hover"])],
        )
        style.configure("TCheckbutton", background=self.palette["surface"], foreground=self.palette["text"])
        style.map("TCheckbutton", foreground=[("active", self.palette["accent_hover"])])
        style.configure(
            "TEntry",
            fieldbackground=self.palette["input_bg"],
            foreground=self.palette["text"],
            insertcolor=self.palette["accent"],
            bordercolor=self.palette["border"],
        )
        style.configure(
            "TPanedwindow",
            background=self.palette["bg"],
            sashrelief="flat",
            sashwidth=8,
        )

    def _build_ui(self) -> None:
        """Build all visible controls for connection, auth, actions, and load."""
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        cfg = ttk.LabelFrame(outer, text="Connection")
        cfg.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(cfg, text="Target URL:").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(cfg, textvariable=self.server_url_var, width=70).grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(cfg, text="Connect selected", command=self.connect_selected).grid(row=0, column=2, padx=6, pady=6)
        ttk.Button(cfg, text="Disconnect selected", command=self.disconnect_selected).grid(row=0, column=3, padx=6, pady=6)
        cfg.grid_columnconfigure(1, weight=1)

        split = ttk.Panedwindow(outer, orient=tk.HORIZONTAL)
        split.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(split, padding=(0, 0, 8, 0))
        right = ttk.Frame(split)
        split.add(left, weight=1)
        split.add(right, weight=2)

        clients_box = ttk.LabelFrame(left, text="Simulated Clients")
        clients_box.pack(fill=tk.BOTH, expand=True)

        top_actions = ttk.Frame(clients_box)
        top_actions.pack(fill=tk.X, padx=6, pady=6)
        self.new_client_entry = ttk.Entry(top_actions)
        self.new_client_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.new_client_entry.insert(0, "CMDR name")
        ttk.Button(top_actions, text="Create client", command=self.create_manual_client).pack(side=tk.LEFT, padx=(6, 0))

        self.clients_list = tk.Listbox(clients_box, height=18, exportselection=False)
        self.clients_list.configure(
            background=self.palette["input_bg"],
            foreground=self.palette["text"],
            selectbackground=self.palette["surface_alt"],
            selectforeground=self.palette["accent"],
            highlightbackground=self.palette["border"],
            highlightcolor=self.palette["accent"],
            relief="flat",
            borderwidth=1,
        )
        self.clients_list.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self.clients_list.bind("<<ListboxSelect>>", self._on_client_selected)

        load_frame = ttk.LabelFrame(clients_box, text="Load")
        load_frame.pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Label(load_frame, text="Batch:").grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Entry(load_frame, textvariable=self.fake_batch_size_var, width=6).grid(row=0, column=1, padx=(0, 6), pady=6, sticky="w")
        ttk.Checkbutton(load_frame, text="Use auth:test_login for fake bots", variable=self.use_test_login_for_bots_var).grid(row=0, column=2, padx=6, pady=6, sticky="w")
        self.btn_add_fake = ttk.Button(load_frame, text="Add fake users", command=self.add_fake_users)
        self.btn_add_fake.grid(row=1, column=0, columnspan=2, padx=6, pady=6, sticky="ew")
        ttk.Button(load_frame, text="Blast report from all connected", command=self.blast_report).grid(row=1, column=2, padx=6, pady=6, sticky="ew")
        ttk.Button(load_frame, text="Cleanup fake users", command=self.cleanup_fake_users).grid(row=2, column=0, columnspan=3, padx=6, pady=6, sticky="ew")

        actions = ttk.LabelFrame(right, text="Selected Client Actions")
        actions.pack(fill=tk.X, pady=(0, 8))

        row0 = ttk.Frame(actions)
        row0.pack(fill=tk.X, padx=6, pady=6)
        ttk.Label(row0, text="Channel").pack(side=tk.LEFT)
        ttk.Entry(row0, textvariable=self.channel_var, width=26).pack(side=tk.LEFT, padx=(6, 8))
        ttk.Label(row0, text="Password").pack(side=tk.LEFT)
        ttk.Entry(row0, textvariable=self.password_var, show="*", width=22).pack(side=tk.LEFT, padx=(6, 8))
        self.public_on_create_var = tk.IntVar(value=1)
        ttk.Checkbutton(row0, text="Public on create", variable=self.public_on_create_var).pack(side=tk.LEFT)

        row1 = ttk.Frame(actions)
        row1.pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Button(row1, text="Join", command=self.action_join).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(row1, text="Leave", command=self.action_leave).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(row1, text="List public", command=self.action_list).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(row1, text="Subscriptions", command=self.action_subs).pack(side=tk.LEFT, padx=(0, 6))

        row2 = ttk.Frame(actions)
        row2.pack(fill=tk.X, padx=6, pady=(0, 8))
        ttk.Label(row2, text="Target attacker").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.target_var, width=24).pack(side=tk.LEFT, padx=(6, 8))
        ttk.Label(row2, text="System").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.system_var, width=24).pack(side=tk.LEFT, padx=(6, 8))
        ttk.Button(row2, text="Send report", command=self.action_send_report).pack(side=tk.LEFT)

        row3 = ttk.Frame(actions)
        row3.pack(fill=tk.X, padx=6, pady=(0, 8))
        ttk.Button(row3, text="Request context (network)", command=self.action_request_context).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(row3, text="Show mock context (local)", command=self.action_show_mock_context).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(row3, text="Show mock watchlist (local)", command=self.action_show_mock_watchlist).pack(side=tk.LEFT)

        auth = ttk.LabelFrame(right, text="Frontier OAuth (selected client)")
        auth.pack(fill=tk.X, pady=(0, 8))
        a0 = ttk.Frame(auth)
        a0.pack(fill=tk.X, padx=6, pady=6)
        ttk.Button(a0, text="Start auth (open browser)", command=self.action_auth_start).pack(side=tk.LEFT)
        ttk.Button(a0, text="Auth status", command=self.action_auth_status).pack(side=tk.LEFT, padx=(6, 0))

        a1 = ttk.Frame(auth)
        a1.pack(fill=tk.X, padx=6, pady=(0, 6))
        ttk.Label(a1, text="Code or callback URL").pack(side=tk.LEFT)
        ttk.Entry(a1, textvariable=self.auth_code_var, width=74).pack(side=tk.LEFT, padx=(6, 8), fill=tk.X, expand=True)
        ttk.Button(a1, text="Complete auth", command=self.action_auth_complete).pack(side=tk.LEFT)

        logs_frame = ttk.LabelFrame(right, text="Event log")
        logs_frame.pack(fill=tk.BOTH, expand=True)
        toolbar = ttk.Frame(logs_frame)
        toolbar.pack(fill=tk.X, padx=6, pady=(6, 0))
        ttk.Button(toolbar, text="Clear log", command=self.clear_log).pack(side=tk.RIGHT)
        log_body = ttk.Frame(logs_frame)
        log_body.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.log_text = tk.Text(log_body, height=26, wrap="word")
        self.log_text.configure(
            background=self.palette["log_bg"],
            foreground=self.palette["text"],
            insertbackground=self.palette["accent"],
            selectbackground=self.palette["surface_alt"],
            selectforeground=self.palette["accent"],
            highlightbackground=self.palette["border"],
            highlightcolor=self.palette["accent"],
            relief="flat",
            borderwidth=1,
        )
        log_scroll = ttk.Scrollbar(log_body, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    # ---------- utilities ----------

    def enqueue_ui(self, fn: Callable[[], None]) -> None:
        """Schedule a callback to be executed on the Tk main thread."""
        self.ui_queue.put(fn)

    def _drain_ui_queue(self) -> None:
        """Execute pending UI callbacks and continue polling the queue."""
        while True:
            try:
                fn = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception as exc:
                self._log(f"ui_error: {exc}")
        self.root.after(60, self._drain_ui_queue)

    def _log(self, text: str) -> None:
        """Append one timestamped message to the event log."""
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        self.log_text.insert("end", f"[{ts}] {text}\n")
        self.log_text.see("end")

    def clear_log(self) -> None:
        """Clear all content from the event log widget."""
        self.log_text.delete("1.0", "end")

    def _selected_client(self) -> Optional[SimClient]:
        """Return the currently selected client, if any."""
        if not self.selected_client_name:
            return None
        return self.clients.get(self.selected_client_name)

    def _refresh_clients_list(self) -> None:
        """Refresh listbox rows while keeping previous selection when possible."""
        cur = self.selected_client_name
        self.clients_list.delete(0, "end")
        names = sorted(self.clients.keys())
        for idx, name in enumerate(names):
            client = self.clients[name]
            state = "ON" if client.connected else "OFF"
            auth = "auth" if client.authenticated else "anon"
            fake = "bot" if client.is_fake else "user"
            self.clients_list.insert("end", f"{name} [{state}|{auth}|{fake}]")
            if name == cur:
                self.clients_list.selection_set(idx)

    def _on_client_selected(self, _event: Any) -> None:
        """Handle listbox selection updates."""
        sel = self.clients_list.curselection()
        if not sel:
            self.selected_client_name = ""
            return
        idx = int(sel[0])
        names = sorted(self.clients.keys())
        if 0 <= idx < len(names):
            self.selected_client_name = names[idx]

    # ---------- client lifecycle ----------

    def _attach_handlers(self, client: SimClient) -> None:
        """Bind socket event handlers for one simulated client."""
        sio = client.sio

        @sio.on("connect")
        def _on_connect() -> None:
            client.connected = True
            self.enqueue_ui(lambda: self._log(f"{client.name} connected [{sio.sid}]"))
            self.enqueue_ui(self._refresh_clients_list)

        @sio.on("disconnect")
        def _on_disconnect(reason: Any) -> None:
            client.connected = False
            client.authenticated = False
            self.enqueue_ui(lambda: self._log(f"{client.name} disconnected: {reason}"))
            self.enqueue_ui(self._refresh_clients_list)

        @sio.on("connect_error")
        def _on_connect_error(err: Any) -> None:
            message = getattr(err, "message", str(err))
            self.enqueue_ui(lambda: self._log(f"{client.name} connect_error: {message}"))

        @sio.on("auth:start")
        def _on_auth_start(payload: Any) -> None:
            data = payload if isinstance(payload, dict) else {}
            client.flow_id = str(data.get("flow_id") or "")
            client.flow_state = str(data.get("state") or "")
            auth_url = str(data.get("auth_url") or "")

            def _ui() -> None:
                self._log(f"{client.name} auth:start: {json.dumps(data, ensure_ascii=False)}")
                if auth_url:
                    opened = open_browser_url(auth_url)
                    if opened:
                        self._log(f"Opening browser: {auth_url}")
                    else:
                        self._log(f"Failed to open browser automatically. Open this URL manually: {auth_url}")

            self.enqueue_ui(_ui)

        @sio.on("auth:status")
        def _on_auth_status(payload: Any) -> None:
            data = payload if isinstance(payload, dict) else {}
            status = str(data.get("status") or "").lower()
            client.authenticated = status == "authenticated"
            token = str(data.get("session_token") or "").strip()
            if token:
                client.session_token = token
            self.enqueue_ui(lambda: self._log(f"{client.name} auth:status -> {json.dumps(data, ensure_ascii=False)}"))
            self.enqueue_ui(self._refresh_clients_list)

        # Core network events
        for ev in (
            "report:accepted",
            "report:rejected",
            "pvp:alert",
            "channel:join:response",
            "channel:leave:response",
            "channel:list:response",
            "channel:subscriptions:response",
            "channel:set_prefs:response",
            "channel:set_visibility:response",
            "server:stats:response",
            "system:context:response",
        ):
            @sio.on(ev)  # type: ignore[misc]
            def _on_generic(payload: Any, event_name: str = ev) -> None:
                self.enqueue_ui(
                    lambda en=event_name, p=payload: self._log(
                        f"{client.name} {en}: {json.dumps(p if isinstance(p, dict) else {'value': str(p)}, ensure_ascii=False)}"
                    )
                )

    def _create_client(self, name: str, is_fake: bool = False, spoof_ip: str = "") -> SimClient:
        """Create, configure, and register one simulated client."""
        url = self.server_url_var.get().strip()
        socketio_path = socketio_path_from_server_url(url)
        client = SimClient(
            name=name,
            server_url=url,
            socketio_path=socketio_path,
            is_fake=is_fake,
            spoof_ip=str(spoof_ip or "").strip(),
        )
        self._attach_handlers(client)
        self.clients[name] = client
        self._refresh_clients_list()
        return client

    def create_manual_client(self) -> None:
        """Create one user-defined client from the CMDR input field."""
        raw = self.new_client_entry.get().strip()
        if not raw or raw.lower() == "cmdr name":
            self._log("Create client failed: CMDR name required")
            return
        if raw in self.clients:
            self._log(f"Client already exists: {raw}")
            return
        self._create_client(raw, is_fake=False)
        self.selected_client_name = raw
        self._refresh_clients_list()
        self._log(f"Client created: {raw}")

    def connect_selected(self) -> None:
        """Connect the selected client to the configured server."""
        client = self._selected_client()
        if not client:
            self._log("No client selected")
            return
        if client.connected:
            self._log(f"{client.name} already connected")
            return
        self._log(f"Connecting {client.name} -> {client.server_url} [{client.socketio_path}]")

        def _run() -> None:
            try:
                connect_kwargs: dict[str, Any] = {
                    "transports": ["websocket", "polling"],
                    "socketio_path": client.socketio_path,
                }
                if client.spoof_ip:
                    connect_kwargs["headers"] = {"x-forwarded-for": client.spoof_ip}
                client.sio.connect(client.server_url, **connect_kwargs)
            except Exception as exc:
                self.enqueue_ui(lambda: self._log(f"{client.name} connect failed: {exc}"))

        threading.Thread(target=_run, daemon=True).start()

    def disconnect_selected(self) -> None:
        """Disconnect currently selected client."""
        client = self._selected_client()
        if not client:
            self._log("No client selected")
            return
        try:
            client.sio.disconnect()
        except Exception as exc:
            self._log(f"{client.name} disconnect error: {exc}")

    def _emit_client(self, client: SimClient, event: str, payload: dict[str, Any]) -> bool:
        """Safely emit one socket event for a client.

        Returns True only when the emit was submitted to a connected namespace.
        This prevents Tk callbacks from crashing on BadNamespaceError.
        """
        if not client.connected or not client.sio.connected:
            self._log(f"{client.name} not connected: cannot emit {event}")
            return False
        try:
            client.sio.emit(event, payload)
            return True
        except Exception as exc:
            client.connected = False
            self._refresh_clients_list()
            self._log(f"{client.name} emit failed [{event}]: {exc}")
            return False

    # ---------- selected actions ----------

    def action_join(self) -> None:
        """Emit `channel:join` for selected client."""
        client = self._selected_client()
        if not client:
            self._log("No client selected")
            return
        self._emit_client(
            client,
            "channel:join",
            {
                "channel_name": self.channel_var.get().strip(),
                "password": self.password_var.get(),
                "public_on_create": bool(self.public_on_create_var.get()),
            },
        )

    def action_leave(self) -> None:
        """Emit `channel:leave` for selected client."""
        client = self._selected_client()
        if not client:
            self._log("No client selected")
            return
        self._emit_client(client, "channel:leave", {"channel_name": self.channel_var.get().strip()})

    def action_list(self) -> None:
        """Emit `channel:list` for selected client."""
        client = self._selected_client()
        if not client:
            self._log("No client selected")
            return
        self._emit_client(client, "channel:list", {})

    def action_subs(self) -> None:
        """Emit `channel:subscriptions` for selected client."""
        client = self._selected_client()
        if not client:
            self._log("No client selected")
            return
        self._emit_client(client, "channel:subscriptions", {})

    def action_send_report(self) -> None:
        """Emit one randomized `report:create` event for selected client."""
        client = self._selected_client()
        if not client:
            self._log("No client selected")
            return
        attacker = self.target_var.get().strip() or "TestGanker"
        system = self.system_var.get().strip() or "Sol"
        event_type = random.choice(EVENT_TYPES)
        if self._emit_client(
            client,
            "report:create",
            {
                "reporter_cmdr": client.name,
                "attacker_cmdr": attacker,
                "ship_model": "Sidewinder",
                "ship_name": "DesktopSim",
                "system": system,
                "event_type": event_type,
                "event_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        ):
            self._log(f"{client.name} report:create sent [{event_type}]")

    def action_request_context(self) -> None:
        """Request real system context from the server for selected client/system."""
        client = self._selected_client()
        if not client:
            self._log("No client selected")
            return
        system = self.system_var.get().strip() or "Sol"
        if self._emit_client(client, "system:context", {"system": system}):
            self._log(f"{client.name} system:context requested [{system}]")

    def action_show_mock_context(self) -> None:
        """Render a local context preview window without network/plugin dependency."""
        system = self.system_var.get().strip() or "Sol"
        lines = [
            ("System context", "#FFD166"),
            (f"System: {system} | Risk: HIGH", "#FF6B6B"),
            ("Reports 2h: 17 | Unique attackers 24h: 9", "#E6EDF3"),
            ("Last activity: 2 min ago | Types: Player kill, Weapon attack", "#A9B4C0"),
            ("Safe visitors: 1h 4 | 12h 27 | 24h 61 | 7d 402", "#55D17A"),
        ]
        self._show_overlay_preview(lines)
        self._log("Mock context preview opened")

    def action_show_mock_watchlist(self) -> None:
        """Render a local watchlist preview window without network/plugin dependency."""
        attacker = self.target_var.get().strip() or "TestGanker"
        system = self.system_var.get().strip() or "Sol"
        lines = [
            ("Watchlist match", "#FFD166"),
            (f"Attacker in watchlist: {attacker}", "#FFB347"),
            ("Reported by: CMDR Ally", "#A9B4C0"),
            (f"System: {system} | Type: Weapon attack", "#E6EDF3"),
        ]
        self._show_overlay_preview(lines)
        self._log("Mock watchlist preview opened")

    def _show_overlay_preview(self, lines: list[tuple[str, str]]) -> None:
        """Show a transient themed preview window used for context/watchlist mocks."""
        if self.preview_window and self.preview_window.winfo_exists():
            win = self.preview_window
            for child in win.winfo_children():
                child.destroy()
        else:
            win = tk.Toplevel(self.root)
            win.title("Overlay preview")
            win.attributes("-topmost", True)
            win.resizable(False, False)
            self.preview_window = win

        win.configure(background="#0f131b")
        container = tk.Frame(
            win,
            background="#11161f",
            highlightthickness=1,
            highlightbackground="#2D3A4D",
            highlightcolor="#2D3A4D",
            padx=12,
            pady=10,
        )
        container.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        for idx, (text, color) in enumerate(lines):
            lbl = tk.Label(
                container,
                text=text,
                anchor="w",
                justify="left",
                foreground=color,
                background="#11161f",
                font=("Segoe UI", 11),
            )
            lbl.grid(row=idx, column=0, sticky="w", pady=(0, 4 if idx < len(lines) - 1 else 0))

        win.update_idletasks()
        sw = int(win.winfo_screenwidth() or 1280)
        ww = int(win.winfo_reqwidth() or 620)
        x = max(8, (sw - ww) // 2)
        y = 80
        win.geometry(f"+{x}+{y}")
        win.lift()

        if self.preview_hide_job:
            try:
                self.root.after_cancel(self.preview_hide_job)
            except Exception:
                pass
        self.preview_hide_job = self.root.after(5000, self._hide_overlay_preview)

    def _hide_overlay_preview(self) -> None:
        """Hide preview overlay if currently visible."""
        self.preview_hide_job = None
        if self.preview_window and self.preview_window.winfo_exists():
            self.preview_window.destroy()
        self.preview_window = None

    # ---------- auth ----------

    def action_auth_start(self) -> None:
        """Start OAuth PKCE flow for selected client."""
        client = self._selected_client()
        if not client:
            self._log("No client selected")
            return
        if not client.connected:
            self._log("Client not connected")
            return
        verifier, challenge = generate_pkce()
        client.code_verifier = verifier
        self._emit_client(
            client,
            "auth:start",
            {
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )

    def action_auth_complete(self) -> None:
        """Complete OAuth flow using pasted code/callback data."""
        client = self._selected_client()
        if not client:
            self._log("No client selected")
            return
        if not client.connected:
            self._log("Client not connected")
            return
        if not client.flow_id or not client.code_verifier:
            self._log("Run auth:start first")
            return
        code, callback_state = parse_code_input(self.auth_code_var.get())
        if not code:
            self._log("Missing OAuth code")
            return
        payload = {
            "flow_id": client.flow_id,
            "code": code,
            "code_verifier": client.code_verifier,
            "state": callback_state or client.flow_state,
        }
        self._emit_client(client, "auth:complete", payload)

    def action_auth_status(self) -> None:
        """Request latest authentication status for selected client."""
        client = self._selected_client()
        if not client:
            self._log("No client selected")
            return
        self._emit_client(client, "auth:status", {})

    # ---------- load ----------

    def add_fake_users(self) -> None:
        """Create/connect a batch of fake users for load scenarios."""
        if self.load_running:
            self._log("Load run already in progress")
            return
        try:
            # Allow large batches for stress tests (kept bounded to avoid accidental runaway input).
            batch = max(1, min(10000, int(self.fake_batch_size_var.get().strip() or "10")))
        except Exception:
            batch = 10
        self.load_running = True
        self.load_stop_token += 1
        token = self.load_stop_token
        self.btn_add_fake.configure(state=tk.DISABLED, text="Running...")

        def _run() -> None:
            now = int(time.time() * 1000)
            success = 0
            failed = 0
            for i in range(batch):
                if token != self.load_stop_token:
                    break
                name = f"loadbot_{now}_{i}"
                spoof_ip = f"10.77.{(i // 240) % 250}.{(i % 240) + 10}"
                self.created_channels.add(f"loadtest_pub_{random.randint(1, 24)}")
                ch_pool = ["global", *sorted(self.created_channels)]
                ch = random.choice(ch_pool)
                c = self._create_client(name, is_fake=True, spoof_ip=spoof_ip)
                self.fake_client_names.add(name)
                ok = self._connect_and_wait(c, timeout=8.0)
                if not ok:
                    failed += 1
                    self._remove_client(name)
                    continue
                if self.use_test_login_for_bots_var.get():
                    self._emit_client(c, "auth:test_login", {"cmdr": name, "frontier_account_id": f"acct-{name}"})
                    authed = self._wait_for(lambda: c.authenticated, timeout=5.0)
                    if not authed:
                        failed += 1
                        self._remove_client(name)
                        continue
                if c.authenticated:
                    self._emit_client(c, "channel:join", {"channel_name": ch, "public_on_create": True, "password": ""})
                    success += 1
                else:
                    # If test-login is disabled, keep connected fake user but mark it as not blast-eligible.
                    success += 1
                if i % 5 == 0:
                    self.enqueue_ui(lambda s=success, f=failed, n=i + 1, b=batch: self.btn_add_fake.configure(text=f"Running {n}/{b} (ok:{s} fail:{f})"))
                time.sleep(0.03)

            def _done() -> None:
                self.load_running = False
                self.btn_add_fake.configure(state=tk.NORMAL, text="Add fake users")
                self._log(f"Fake batch complete. Success={success}, Failed={failed}")
                self._refresh_clients_list()

            self.enqueue_ui(_done)

        threading.Thread(target=_run, daemon=True).start()

    def blast_report(self) -> None:
        """Send one report from every connected simulated client."""
        sent = 0
        sent_auth = 0
        sent_unauth = 0
        for c in list(self.clients.values()):
            if not c.connected:
                continue
            event_type = random.choice(EVENT_TYPES)
            if self._emit_client(
                c,
                "report:create",
                {
                    "reporter_cmdr": c.name,
                    "attacker_cmdr": "LoadTestEnemy",
                    "ship_model": "Anaconda",
                    "ship_name": "LoadTest",
                    "system": "LoadTestSystem",
                    "event_type": event_type,
                    "event_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
            ):
                sent += 1
                if c.authenticated:
                    sent_auth += 1
                else:
                    sent_unauth += 1
        self._log(f"Blast sent from {sent} connected clients (auth: {sent_auth}, unauth: {sent_unauth})")

    def cleanup_fake_users(self) -> None:
        """Stop load run and remove all fake users from runtime."""
        self.load_stop_token += 1
        self.load_running = False
        self.btn_add_fake.configure(state=tk.NORMAL, text="Add fake users")
        removed = 0
        for name in list(self.fake_client_names):
            if name in self.clients:
                self._remove_client(name)
                removed += 1
            self.fake_client_names.discard(name)
        self.created_channels.clear()
        self._refresh_clients_list()
        self._log(f"Cleanup complete. Removed fake clients: {removed}")

    def _remove_client(self, name: str) -> None:
        """Disconnect and remove one client from registry."""
        client = self.clients.pop(name, None)
        if not client:
            return
        try:
            client.sio.disconnect()
        except Exception:
            pass
        if self.selected_client_name == name:
            self.selected_client_name = ""

    def _connect_and_wait(self, client: SimClient, timeout: float = 6.0) -> bool:
        """Connect one client and wait until connected or timeout."""
        done = threading.Event()

        def _run() -> None:
            try:
                connect_kwargs: dict[str, Any] = {
                    "transports": ["websocket", "polling"],
                    "socketio_path": client.socketio_path,
                }
                if client.spoof_ip:
                    connect_kwargs["headers"] = {"x-forwarded-for": client.spoof_ip}
                client.sio.connect(client.server_url, **connect_kwargs)
            except Exception:
                pass
            finally:
                done.set()

        threading.Thread(target=_run, daemon=True).start()

        start = time.time()
        while time.time() - start < timeout:
            if client.connected:
                return True
            if done.is_set() and not client.connected:
                time.sleep(0.05)
            time.sleep(0.05)
        return client.connected

    def _wait_for(self, predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
        """Wait until predicate returns True or timeout expires."""
        start = time.time()
        while time.time() - start < timeout:
            if predicate():
                return True
            time.sleep(0.05)
        return False


def main() -> None:
    """Entrypoint for launching the desktop simulator app."""
    root = tk.Tk()
    app = DesktopSimulatorApp(root)
    app._log("Desktop simulator ready")
    root.mainloop()


if __name__ == "__main__":
    main()
