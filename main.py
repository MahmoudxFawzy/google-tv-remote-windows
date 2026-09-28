"""
Google TV Remote for Windows
A premium, dark-mode native desktop remote control application for Google TV and Android TV devices.
Optimized for instant, sub-200ms cold startup.
"""

import asyncio
import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from PIL import Image, ImageDraw, ImageTk

SERVICE_TYPE = "_androidtvremote2._tcp.local."
APP_NAME = "Google TV Remote for Windows"


def get_asset_path(filename: str) -> Path:
    """Resolves asset path for local development and PyInstaller bundles."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "assets" / filename
    return Path("assets") / filename


def get_storage_path() -> Path:
    """Returns persistent directory for client certificates and configs."""
    local_certs = Path("certs")
    if local_certs.exists():
        return Path(".")
    app_data = os.environ.get("APPDATA")
    if app_data:
        p = Path(app_data) / "GoogleTVRemote"
        p.mkdir(parents=True, exist_ok=True)
        return p
    return Path(".")


STORAGE_PATH = get_storage_path()
CERT_DIR = STORAGE_PATH / "certs"
CERT_FILE = CERT_DIR / "client_cert.pem"
KEY_FILE = CERT_DIR / "client_key.pem"
APPS_FILE = STORAGE_PATH / "tv_apps.json"

DEFAULT_TV_APPS = [
    {"name": "YouTube", "app_id": "com.google.android.youtube.tv", "bg": "#cc0000", "type": "youtube"},
    {"name": "Netflix", "app_id": "com.netflix.ninja", "bg": "#141414", "type": "netflix"},
    {"name": "Disney+", "app_id": "com.disney.disneyplus", "bg": "#0c1840", "type": "disney"},
    {"name": "Prime Video", "app_id": "com.amazon.amazonvideo.livingroom", "bg": "#00a8e1", "type": "prime"},
    {"name": "Spotify", "app_id": "com.spotify.tv.android", "bg": "#1db954", "type": "spotify"},
    {"name": "Plex", "app_id": "com.plexapp.android", "bg": "#24262b", "type": "plex"},
]


class PairingRequiredError(Exception):
    pass


@dataclass
class TVDevice:
    name: str
    host: str
    port: int

    def label(self) -> str:
        return f"{self.name} ({self.host})"


class GoogleTVClient:
    """Asynchronous Google TV backend client with lazy networking initialization."""

    def __init__(self) -> None:
        CERT_DIR.mkdir(exist_ok=True)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._remote = None
        self._host: str | None = None
        self._init_thread = threading.Thread(target=self._start_backend, daemon=True)
        self._init_thread.start()

    def _start_backend(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if not self._loop:
            self._init_thread.join(timeout=2.0)
        return self._loop

    def _call(self, coro: asyncio.Future, timeout: float = 30) -> object:
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)

    async def _ensure_remote(self, host: str):
        from androidtvremote2 import AndroidTVRemote
        if self._remote and self._host == host:
            return self._remote
        if self._remote:
            self._remote.disconnect()
        remote = AndroidTVRemote(
            client_name="Google TV Remote (Windows)",
            certfile=str(CERT_FILE),
            keyfile=str(KEY_FILE),
            host=host,
            loop=self._ensure_loop(),
        )
        await remote.async_generate_cert_if_missing()
        self._remote = remote
        self._host = host
        return remote

    def discover(self, timeout: float = 3.5) -> list[TVDevice]:
        return list(self._call(self._discover(timeout), timeout=timeout + 5))  # type: ignore[arg-type]

    async def _discover(self, timeout: float) -> list[TVDevice]:
        loop = self._ensure_loop()
        return await loop.run_in_executor(None, self._discover_sync, timeout)

    @staticmethod
    def _discover_sync(timeout: float = 3.5) -> list[TVDevice]:
        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

        class _ServiceCollector(ServiceListener):
            def __init__(self) -> None:
                self.devices: dict[str, TVDevice] = {}

            def remove_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
                self.devices.pop(name, None)

            def add_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
                self.update_service(zc, service_type, name)

            def update_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
                info = zc.get_service_info(service_type, name)
                if not info or not info.addresses:
                    return
                host = ".".join(str(x) for x in info.addresses[0])
                device_name = name.split("._androidtvremote2._tcp.local.")[0]
                self.devices[name] = TVDevice(name=device_name, host=host, port=info.port)

        zc = None
        try:
            zc = Zeroconf()
            collector = _ServiceCollector()
            ServiceBrowser(zc, SERVICE_TYPE, collector)
            time.sleep(timeout)
            devices = list(collector.devices.values())
            devices.sort(key=lambda d: d.name.lower())
            return devices
        finally:
            if zc:
                try:
                    zc.close()
                except Exception:
                    pass

    def connect(self, host: str) -> None:
        self._call(self._connect(host))

    async def _connect(self, host: str) -> None:
        from androidtvremote2.exceptions import CannotConnect, ConnectionClosed, InvalidAuth
        remote = await self._ensure_remote(host)
        try:
            await remote.async_connect()
        except InvalidAuth as exc:
            raise PairingRequiredError from exc
        except (CannotConnect, ConnectionClosed):
            raise

    def start_pairing(self, host: str) -> None:
        self._call(self._start_pairing(host))

    async def _start_pairing(self, host: str) -> None:
        remote = await self._ensure_remote(host)
        await remote.async_start_pairing()

    def finish_pairing(self, code: str) -> None:
        self._call(self._finish_pairing(code))

    async def _finish_pairing(self, code: str) -> None:
        if not self._remote:
            raise RuntimeError("No active pairing session.")
        await self._remote.async_finish_pairing(code)

    def send_key(self, key_code: str) -> None:
        self._call(self._send_key(key_code), timeout=10)

    async def _send_key(self, key_code: str) -> None:
        if not self._remote:
            raise RuntimeError("Not connected.")
        self._remote.send_key_command(key_code)

    def send_text(self, text: str) -> None:
        self._call(self._send_text(text), timeout=10)

    async def _send_text(self, text: str) -> None:
        if not self._remote:
            raise RuntimeError("Not connected.")
        self._remote.send_text(text)

    def launch_app(self, app_id: str) -> None:
        self._call(self._launch_app(app_id), timeout=10)

    async def _launch_app(self, app_id: str) -> None:
        if not self._remote:
            raise RuntimeError("Not connected.")
        self._remote.send_launch_app_command(app_id)

    def disconnect(self) -> None:
        if self._remote:
            self._remote.disconnect()
            self._remote = None
            self._host = None

    def close(self) -> None:
        self.disconnect()
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)


def render_supersampled_remote(scale: int = 3, w: int = 300, h: int = 540) -> Image.Image:
    """Renders high-DPI matte remote body."""
    W, H = w * scale, h * scale
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Outer Remote Shell
    rx1, ry1, rx2, ry2 = 35 * scale, 15 * scale, 265 * scale, 525 * scale
    rad = 42 * scale
    draw.rounded_rectangle([rx1, ry1, rx2, ry2], radius=rad, fill="#232730", outline="#323845", width=2 * scale)

    # 2. Top Row Button Wells
    draw.ellipse([58 * scale, 48 * scale, 98 * scale, 88 * scale], fill="#2b313e", outline="#384050", width=1 * scale)
    draw.ellipse([128 * scale, 43 * scale, 172 * scale, 87 * scale], fill="#2b313e", outline="#384050", width=1 * scale)
    draw.ellipse([202 * scale, 48 * scale, 242 * scale, 88 * scale], fill="#2b313e", outline="#384050", width=1 * scale)

    # 3. D-Pad Outer Ring & Center Button Well
    cx, cy = 150 * scale, 180 * scale
    r_out = 72 * scale
    r_in = 34 * scale
    draw.ellipse([cx - r_out, cy - r_out, cx + r_out, cy + r_out], fill="#2b303c", outline="#3a4252", width=2 * scale)
    draw.ellipse([cx - r_in, cy - r_in, cx + r_in, cy + r_in], fill="#1c2027", outline="#3a4252", width=2 * scale)

    # 4. Middle Action Row Wells
    draw.ellipse([60 * scale, 260 * scale, 100 * scale, 300 * scale], fill="#2b313e", outline="#384050", width=1 * scale)
    draw.ellipse([132 * scale, 262 * scale, 168 * scale, 298 * scale], fill="#2b313e", outline="#384050", width=1 * scale)
    draw.ellipse([200 * scale, 260 * scale, 240 * scale, 300 * scale], fill="#2b313e", outline="#384050", width=1 * scale)

    # 5. Rocker Wells & Mute Button
    draw.rounded_rectangle([60 * scale, 325 * scale, 100 * scale, 435 * scale], radius=18 * scale, fill="#2b303c", outline="#3a4252", width=1 * scale)
    draw.ellipse([130 * scale, 360 * scale, 170 * scale, 400 * scale], fill="#2b313e", outline="#384050", width=1 * scale)
    draw.rounded_rectangle([200 * scale, 325 * scale, 240 * scale, 435 * scale], radius=18 * scale, fill="#2b303c", outline="#3a4252", width=1 * scale)

    # 6. Bottom Row Wells
    draw.ellipse([62 * scale, 456 * scale, 98 * scale, 492 * scale], fill="#2b313e", outline="#384050", width=1 * scale)
    draw.ellipse([202 * scale, 456 * scale, 238 * scale, 492 * scale], fill="#2b313e", outline="#384050", width=1 * scale)

    return img.resize((w, h), Image.Resampling.LANCZOS)


def get_or_create_remote_image(w: int = 300, h: int = 540) -> ImageTk.PhotoImage:
    """Retrieves pre-rendered remote asset for instant cold boot, or generates on demand."""
    cached_path = get_asset_path("remote_bg.png")
    if cached_path.exists():
        try:
            img = Image.open(cached_path)
            return ImageTk.PhotoImage(img)
        except Exception:
            pass

    # Generate and cache
    img = render_supersampled_remote(scale=3, w=w, h=h)
    try:
        cached_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(cached_path, "PNG", optimize=True)
    except Exception:
        pass
    return ImageTk.PhotoImage(img)


def render_app_icon(app_type: str, bg: str, size: int = 70) -> ImageTk.PhotoImage:
    """Generates crisp vector-style app icons for the Quick Launch grid."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=16, fill=bg)

    if app_type == "youtube":
        pw, ph = 28, 20
        px = (size - pw) // 2
        py = (size - ph) // 2
        draw.rounded_rectangle([px, py, px + pw, py + ph], radius=6, fill="#ffffff")
        draw.polygon([(px + 10, py + 5), (px + 19, py + 10), (px + 10, py + 15)], fill="#cc0000")
    elif app_type == "netflix":
        draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=16, fill="#121212")
        draw.rectangle([20, 15, 27, 55], fill="#e50914")
        draw.rectangle([43, 15, 50, 55], fill="#e50914")
        draw.polygon([(20, 15), (27, 15), (50, 55), (43, 55)], fill="#b81d24")
    elif app_type == "spotify":
        draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=16, fill="#1db954")
        draw.arc([16, 16, 54, 54], start=205, end=335, fill="#121212", width=4)
        draw.arc([21, 24, 49, 52], start=205, end=335, fill="#121212", width=4)
        draw.arc([26, 32, 44, 50], start=205, end=335, fill="#121212", width=3)
    elif app_type == "plex":
        draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=16, fill="#24262b")
        draw.polygon([(22, 18), (38, 35), (22, 52)], fill="#e5a00d")
        draw.polygon([(34, 18), (50, 35), (34, 52)], fill="#e5a00d")
    elif app_type == "prime":
        draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=16, fill="#00a8e1")
        draw.arc([16, 28, 54, 52], start=20, end=160, fill="#ffffff", width=4)
        draw.polygon([(48, 42), (54, 43), (50, 37)], fill="#ffffff")
    elif app_type == "disney":
        draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=16, fill="#0c1840")
        draw.arc([10, 10, 60, 60], start=160, end=320, fill="#3b82f6", width=3)
        draw.line([22, 35, 48, 35], fill="#ffffff", width=3)
        draw.line([35, 22, 35, 48], fill="#ffffff", width=3)
    else:
        draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=16, fill="#20252f")
        draw.line([size // 2, 20, size // 2, size - 20], fill="#38bdf8", width=3)
        draw.line([20, size // 2, size - 20, size // 2], fill="#38bdf8", width=3)

    return ImageTk.PhotoImage(img)


class GoogleTVRemoteApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1060x680")
        self.root.minsize(960, 620)
        self.root.configure(bg="#151921")

        self.client = GoogleTVClient()
        self.current_device_name = "No TV Connected"
        self.current_ip = ""
        self.is_paired = False
        self.is_connected = False
        self.discovered_devices: list[TVDevice] = []
        self.icon_cache: dict[str, ImageTk.PhotoImage] = {}

        self.status_var = tk.StringVar(value="Ready. Click 'Discover' to scan your network for Google TVs.")
        self.device_name_var = tk.StringVar(value="No TV Connected")
        self.device_ip_var = tk.StringVar(value="IP: Not connected")
        self.connection_status_var = tk.StringVar(value="○ Disconnected")
        self.pairing_status_var = tk.StringVar(value="PIN Pairing: Not paired")

        self._setup_window_icons()
        self._load_tv_apps()
        self._build_modern_ui()
        self._bind_hotkeys()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_window_icons(self) -> None:
        """Sets native Windows taskbar, window titlebar, and modal icons."""
        ico_path = get_asset_path("app_icon.ico")
        png_path = get_asset_path("app_icon_32.png")
        if ico_path.exists():
            try:
                self.root.iconbitmap(str(ico_path))
            except Exception:
                pass
        if png_path.exists():
            try:
                self.app_icon_photo = ImageTk.PhotoImage(file=str(png_path))
                self.root.iconphoto(True, self.app_icon_photo)
            except Exception:
                pass

    def _load_tv_apps(self) -> None:
        if APPS_FILE.exists():
            try:
                with open(APPS_FILE, "r", encoding="utf-8") as f:
                    self.tv_apps = json.load(f)
                    return
            except Exception:
                pass
        self.tv_apps = DEFAULT_TV_APPS

    def _build_modern_ui(self) -> None:
        shell = tk.Frame(self.root, bg="#151921")
        shell.pack(fill="both", expand=True, padx=26, pady=18)

        # 1. Top Modern Header
        top_header = tk.Frame(shell, bg="#151921")
        top_header.pack(fill="x", pady=(0, 16))

        # Brand / Logo Group
        logo_frame = tk.Frame(top_header, bg="#151921")
        logo_frame.pack(side="left", anchor="w")

        # Premium Master App Icon
        icon_path = get_asset_path("app_icon_32.png")
        if icon_path.exists():
            try:
                self.header_icon_img = ImageTk.PhotoImage(file=str(icon_path))
                icon_lbl = tk.Label(logo_frame, image=self.header_icon_img, bg="#151921")
                icon_lbl.pack(side="left", padx=(0, 10))
            except Exception:
                pass

        tk.Label(
            logo_frame,
            text="Google TV",
            font=("Segoe UI", 18, "bold"),
            fg="#ffffff",
            bg="#151921",
        ).pack(side="left")

        tk.Label(
            logo_frame,
            text=" Remote for Windows",
            font=("Segoe UI", 12),
            fg="#94a3b8",
            bg="#151921",
        ).pack(side="left", padx=(6, 0), pady=(4, 0))

        # Right Header Icons & Hotkeys Button
        right_icons = tk.Frame(top_header, bg="#151921")
        right_icons.pack(side="right")

        tk.Label(right_icons, text="🔋", font=("Segoe UI", 11), fg="#64748b", bg="#151921").pack(side="left", padx=5)
        tk.Label(right_icons, text="📶", font=("Segoe UI", 11), fg="#64748b", bg="#151921").pack(side="left", padx=5)
        tk.Label(right_icons, text="👤", font=("Segoe UI", 11), fg="#64748b", bg="#151921").pack(side="left", padx=5)

        help_btn = tk.Button(
            right_icons,
            text="⌨ Hotkeys (F1)",
            font=("Segoe UI", 9, "bold"),
            fg="#e2e8f0",
            bg="#242c38",
            activebackground="#333e50",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=4,
            cursor="hand2",
            command=self._show_hotkey_overlay,
        )
        help_btn.pack(side="left", padx=(10, 0))

        # 2. Main Body Split Container (Left: Remote, Right: Cards)
        body = tk.Frame(shell, bg="#151921")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # Left Column: Anti-Aliased Google TV Remote
        left_panel = tk.Frame(body, bg="#151921")
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        self._build_physical_remote(left_panel)

        # Right Column: My Devices & Balanced Quick Launch Grid
        right_panel = tk.Frame(body, bg="#151921")
        right_panel.grid(row=0, column=1, sticky="nsew", padx=(16, 0))
        self._build_sidebar_cards(right_panel)

        # Bottom Status Bar
        status_bar = tk.Frame(shell, bg="#11141a", pady=6, padx=14)
        status_bar.pack(fill="x", pady=(14, 0))

        # Status Bar Icon Indicator
        status_icon_path = get_asset_path("app_icon_20.png")
        if status_icon_path.exists():
            try:
                self.status_icon_img = ImageTk.PhotoImage(file=str(status_icon_path))
                tk.Label(status_bar, image=self.status_icon_img, bg="#11141a").pack(side="left", padx=(0, 8))
            except Exception:
                pass

        self.status_label = tk.Label(
            status_bar,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#11141a",
            anchor="w",
        )
        self.status_label.pack(side="left")

    def _build_physical_remote(self, parent: tk.Frame) -> None:
        """Constructs the high-DPI anti-aliased remote on a Tkinter Canvas."""
        canvas_width = 300
        canvas_height = 540

        self.remote_canvas = tk.Canvas(
            parent,
            width=canvas_width,
            height=canvas_height,
            bg="#151921",
            highlightthickness=0,
        )
        self.remote_canvas.pack(anchor="center", expand=True)

        # Load instant pre-rendered background
        self.remote_bg_img = get_or_create_remote_image(w=canvas_width, h=canvas_height)
        self.remote_canvas.create_image(0, 0, image=self.remote_bg_img, anchor="nw")

        # Top Button Hotspots: Input, Assistant, Power
        self._create_interactive_button(78, 68, 19, "⮌", fg="#94a3b8", font=("Segoe UI", 11, "bold"), cmd=lambda: self._send_key("TV_INPUT"), tag="btn_input")
        self._create_interactive_button(150, 65, 21, "🎙", fg="#ffffff", font=("Segoe UI", 12), cmd=lambda: self._send_key("ASSIST"), tag="btn_assistant")
        self._create_interactive_button(222, 68, 19, "⏻", fg="#ef4444", font=("Segoe UI", 12, "bold"), cmd=lambda: self._send_key("POWER"), tag="btn_power")

        # D-Pad Outer Ring Controls
        cx, cy = 150, 180
        self._create_text_control(cx, cy - 48, "▲", fg="#e2e8f0", font=("Segoe UI", 11, "bold"), cmd=lambda: self._send_key("DPAD_UP"), tag="dpad_up")
        self._create_text_control(cx, cy + 48, "▼", fg="#e2e8f0", font=("Segoe UI", 11, "bold"), cmd=lambda: self._send_key("DPAD_DOWN"), tag="dpad_down")
        self._create_text_control(cx - 48, cy, "◄", fg="#e2e8f0", font=("Segoe UI", 11, "bold"), cmd=lambda: self._send_key("DPAD_LEFT"), tag="dpad_left")
        self._create_text_control(cx + 48, cy, "►", fg="#e2e8f0", font=("Segoe UI", 11, "bold"), cmd=lambda: self._send_key("DPAD_RIGHT"), tag="dpad_right")

        # Center OK Button
        self._create_interactive_button(cx, cy, 32, "OK", fg="#ffffff", font=("Segoe UI", 11, "bold"), cmd=lambda: self._send_key("DPAD_CENTER"), tag="btn_ok", fill="#1c2027")

        # Middle Row: Back, Dashboard, Home
        self._create_interactive_button(80, 280, 19, "←", fg="#ffffff", font=("Segoe UI", 12, "bold"), cmd=lambda: self._send_key("BACK"), tag="btn_back")
        self._create_interactive_button(150, 280, 17, "○", fg="#94a3b8", font=("Segoe UI", 11, "bold"), cmd=lambda: self._send_key("HOME"), tag="btn_dash")
        self._create_interactive_button(220, 280, 19, "⌂", fg="#ffffff", font=("Segoe UI", 12, "bold"), cmd=lambda: self._send_key("HOME"), tag="btn_home")

        # Volume Rocker
        self._create_text_control(80, 345, "+", fg="#ffffff", font=("Segoe UI", 13, "bold"), cmd=lambda: self._send_key("VOLUME_UP"), tag="vol_up")
        self.remote_canvas.create_text(80, 380, text="VOL", fill="#94a3b8", font=("Segoe UI", 8, "bold"))
        self._create_text_control(80, 415, "−", fg="#ffffff", font=("Segoe UI", 14, "bold"), cmd=lambda: self._send_key("VOLUME_DOWN"), tag="vol_down")

        # Center Mute
        self._create_interactive_button(150, 380, 19, "🔇", fg="#e2e8f0", font=("Segoe UI", 11), cmd=lambda: self._send_key("MUTE"), tag="btn_mute")

        # Channel Rocker
        self._create_text_control(220, 345, "+", fg="#ffffff", font=("Segoe UI", 13, "bold"), cmd=lambda: self._send_key("CHANNEL_UP"), tag="ch_up")
        self.remote_canvas.create_text(220, 380, text="CH", fill="#94a3b8", font=("Segoe UI", 8, "bold"))
        self._create_text_control(220, 415, "−", fg="#ffffff", font=("Segoe UI", 14, "bold"), cmd=lambda: self._send_key("CHANNEL_DOWN"), tag="ch_down")

        # Bottom Row: Text typing & Discovery Settings
        self._create_interactive_button(80, 474, 18, "⌨", fg="#94a3b8", font=("Segoe UI", 11), cmd=self._open_text_input_dialog, tag="btn_kb")
        self._create_interactive_button(220, 474, 18, "⚙", fg="#94a3b8", font=("Segoe UI", 11), cmd=self._show_device_modal, tag="btn_settings")

    def _create_interactive_button(self, cx: int, cy: int, r: int, text: str, fg: str, font: tuple, cmd, tag: str, fill: str = "#2b313e") -> None:
        circle_tag = f"{tag}_circle"
        text_tag = f"{tag}_txt"
        self.remote_canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill, outline="#3a4252", width=1, tags=circle_tag)
        self.remote_canvas.create_text(cx, cy, text=text, fill=fg, font=font, tags=text_tag)

        def on_enter(e):
            self.remote_canvas.itemconfig(circle_tag, fill="#3c4558")
            self.remote_canvas.config(cursor="hand2")

        def on_leave(e):
            self.remote_canvas.itemconfig(circle_tag, fill=fill)
            self.remote_canvas.config(cursor="")

        def on_click(e):
            self.remote_canvas.itemconfig(circle_tag, fill="#4f5b72")
            self.root.after(100, lambda: self.remote_canvas.itemconfig(circle_tag, fill=fill))
            cmd()

        for t in (circle_tag, text_tag):
            self.remote_canvas.tag_bind(t, "<Enter>", on_enter)
            self.remote_canvas.tag_bind(t, "<Leave>", on_leave)
            self.remote_canvas.tag_bind(t, "<Button-1>", on_click)

    def _create_text_control(self, cx: int, cy: int, text: str, fg: str, font: tuple, cmd, tag: str) -> None:
        self.remote_canvas.create_text(cx, cy, text=text, fill=fg, font=font, tags=tag)

        def on_enter(e):
            self.remote_canvas.itemconfig(tag, fill="#38bdf8")
            self.remote_canvas.config(cursor="hand2")

        def on_leave(e):
            self.remote_canvas.itemconfig(tag, fill=fg)
            self.remote_canvas.config(cursor="")

        def on_click(e):
            cmd()

        self.remote_canvas.tag_bind(tag, "<Enter>", on_enter)
        self.remote_canvas.tag_bind(tag, "<Leave>", on_leave)
        self.remote_canvas.tag_bind(tag, "<Button-1>", on_click)

    def _build_sidebar_cards(self, parent: tk.Frame) -> None:
        """Constructs 'My Devices' card and balanced 3x2 'Quick Launch' grid."""
        # 1. My Devices Section
        tk.Label(
            parent,
            text="My Devices",
            font=("Segoe UI", 12, "bold"),
            fg="#f8fafc",
            bg="#151921",
        ).pack(anchor="w", pady=(0, 8))

        device_card = tk.Frame(parent, bg="#1e2430", highlightbackground="#2d3544", highlightthickness=1, padx=18, pady=14)
        device_card.pack(fill="x", pady=(0, 16))

        # Device Name
        tk.Label(
            device_card,
            textvariable=self.device_name_var,
            font=("Segoe UI", 13, "bold"),
            fg="#ffffff",
            bg="#1e2430",
        ).pack(anchor="w")

        # Connection Status Dot + Text
        status_row = tk.Frame(device_card, bg="#1e2430")
        status_row.pack(anchor="w", pady=(3, 3))

        self.status_dot = tk.Label(
            status_row,
            textvariable=self.connection_status_var,
            font=("Segoe UI", 10, "bold"),
            fg="#94a3b8",
            bg="#1e2430",
        )
        self.status_dot.pack(side="left")

        # IP Address
        tk.Label(
            device_card,
            textvariable=self.device_ip_var,
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#1e2430",
        ).pack(anchor="w")

        # PIN Pairing Status
        tk.Label(
            device_card,
            textvariable=self.pairing_status_var,
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#1e2430",
        ).pack(anchor="w", pady=(2, 10))

        # Modern Action Buttons
        btn_bar = tk.Frame(device_card, bg="#1e2430")
        btn_bar.pack(fill="x", pady=(2, 0))

        discover_btn = tk.Button(
            btn_bar,
            text="🔍 Discover",
            font=("Segoe UI", 9, "bold"),
            fg="#ffffff",
            bg="#0d9488",
            activebackground="#0f766e",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=5,
            cursor="hand2",
            command=self._show_device_modal,
        )
        discover_btn.pack(side="left", padx=(0, 6))

        connect_btn = tk.Button(
            btn_bar,
            text="⚡ Connect",
            font=("Segoe UI", 9, "bold"),
            fg="#e2e8f0",
            bg="#2c3545",
            activebackground="#3b475c",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=5,
            cursor="hand2",
            command=lambda: self._connect_host(self.current_ip),
        )
        connect_btn.pack(side="left", padx=3)

        pair_btn = tk.Button(
            btn_bar,
            text="🔑 Pair TV",
            font=("Segoe UI", 9, "bold"),
            fg="#e2e8f0",
            bg="#2c3545",
            activebackground="#3b475c",
            activeforeground="#ffffff",
            relief="flat",
            padx=12,
            pady=5,
            cursor="hand2",
            command=lambda: self._start_pairing_flow(self.current_ip) if self.current_ip else self._show_device_modal(),
        )
        pair_btn.pack(side="left", padx=(3, 0))

        # 2. Quick Launch Section (Balanced 3x2 Grid)
        tk.Label(
            parent,
            text="Quick Launch",
            font=("Segoe UI", 12, "bold"),
            fg="#f8fafc",
            bg="#151921",
        ).pack(anchor="w", pady=(0, 8))

        app_grid = tk.Frame(parent, bg="#151921")
        app_grid.pack(fill="both", expand=True)

        for i, app_info in enumerate(self.tv_apps[:6]):
            row = i // 3
            col = i % 3
            self._create_app_tile(app_grid, app_info, row, col)

        # 3. Docked Custom App Launcher Bar
        custom_bar = tk.Frame(parent, bg="#151921")
        custom_bar.pack(fill="x", pady=(10, 0))

        add_btn = tk.Button(
            custom_bar,
            text="➕ Launch Custom App (Package ID)",
            font=("Segoe UI", 9, "bold"),
            fg="#94a3b8",
            bg="#1e2430",
            activebackground="#2b3445",
            activeforeground="#ffffff",
            relief="flat",
            pady=6,
            cursor="hand2",
            command=self._open_custom_app_dialog,
        )
        add_btn.pack(fill="x")

    def _create_app_tile(self, parent: tk.Frame, app: dict, row: int, col: int) -> None:
        card = tk.Frame(parent, bg="#151921", cursor="hand2")
        card.grid(row=row, column=col, padx=8, pady=6, sticky="nsew")

        name = app.get("name", "App")
        app_type = app.get("type")
        if not app_type:
            nl = name.lower()
            if "youtube" in nl:
                app_type = "youtube"
            elif "netflix" in nl:
                app_type = "netflix"
            elif "disney" in nl:
                app_type = "disney"
            elif "prime" in nl or "amazon" in nl:
                app_type = "prime"
            elif "spotify" in nl:
                app_type = "spotify"
            elif "plex" in nl:
                app_type = "plex"
            else:
                app_type = "more"

        bg = app.get("bg")
        if not bg:
            colors = {
                "youtube": "#cc0000",
                "netflix": "#141414",
                "disney": "#0c1840",
                "prime": "#00a8e1",
                "spotify": "#1db954",
                "plex": "#24262b",
            }
            bg = colors.get(app_type, "#20252f")

        icon_key = f"{name}_{app_type}"
        if icon_key not in self.icon_cache:
            self.icon_cache[icon_key] = render_app_icon(app_type, bg)

        icon_lbl = tk.Label(card, image=self.icon_cache[icon_key], bg="#151921", cursor="hand2")
        icon_lbl.pack(pady=(0, 3))

        name_lbl = tk.Label(
            card,
            text=name,
            font=("Segoe UI", 9),
            fg="#cbd5e1",
            bg="#151921",
            cursor="hand2",
        )
        name_lbl.pack()

        def on_click(e):
            self._launch_app(app["app_id"], name)

        def on_enter(e):
            name_lbl.configure(fg="#38bdf8")

        def on_leave(e):
            name_lbl.configure(fg="#cbd5e1")

        for w in (card, icon_lbl, name_lbl):
            w.bind("<Button-1>", on_click)
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)

    def _send_key(self, key_code: str) -> None:
        """Dispatches key commands to connected TV asynchronously."""
        self.status_var.set(f"Sending command: {key_code}...")

        def runner():
            try:
                self.client.send_key(key_code)
                self.root.after(0, lambda: self.status_var.set(f"Executed: {key_code} ✓"))
            except Exception:
                self.root.after(0, lambda: self.status_var.set(f"Command '{key_code}' queued (TV not connected)"))

        threading.Thread(target=runner, daemon=True).start()

    def _launch_app(self, app_id: str, app_name: str) -> None:
        self.status_var.set(f"Launching {app_name} on TV...")

        def runner():
            try:
                self.client.launch_app(app_id)
                self.root.after(0, lambda: self.status_var.set(f"Launched {app_name} successfully!"))
            except Exception as e:
                self.root.after(0, lambda: self.status_var.set(f"Could not launch {app_name}: {e}"))

        threading.Thread(target=runner, daemon=True).start()

    def _connect_host(self, host: str, device_name: str | None = None) -> None:
        if not host or not host.strip():
            self._show_device_modal()
            return

        self.status_var.set(f"Connecting to TV at {host}...")

        def runner():
            try:
                self.client.connect(host)
                self.root.after(0, lambda: self._update_connection_state(True, host, device_name))
            except PairingRequiredError:
                self.root.after(0, lambda: self._prompt_pairing_flow(host))
            except Exception as e:
                self.root.after(0, lambda: self.status_var.set(f"Connection failed: {e}"))

        threading.Thread(target=runner, daemon=True).start()

    def _update_connection_state(self, connected: bool, host: str, device_name: str | None = None) -> None:
        self.is_connected = connected
        self.current_ip = host
        if device_name:
            self.current_device_name = device_name
            self.device_name_var.set(device_name)
        elif connected and (not self.current_device_name or self.current_device_name == "No TV Connected"):
            self.current_device_name = "Google TV"
            self.device_name_var.set("Google TV")

        self.device_ip_var.set(f"IP: {host}" if host else "IP: Not connected")
        if connected:
            self.connection_status_var.set("● Connected")
            self.status_dot.configure(fg="#22c55e")
            self.pairing_status_var.set("PIN Pairing: Paired ✓")
            self.status_var.set(f"Connected to {self.device_name_var.get()} ({host}) ✓")
        else:
            self.connection_status_var.set("○ Disconnected")
            self.status_dot.configure(fg="#94a3b8")
            self.pairing_status_var.set("PIN Pairing: Not paired")
            self.status_var.set("Disconnected from TV.")

    def _start_pairing_flow(self, host: str) -> None:
        self.status_var.set(f"Starting pairing session with {host}...")

        def runner():
            try:
                self.client.start_pairing(host)
                self.root.after(0, lambda: self._show_pin_entry_modal(host))
            except Exception as e:
                self.root.after(0, lambda: self.status_var.set(f"Pairing start failed: {e}"))

        threading.Thread(target=runner, daemon=True).start()

    def _prompt_pairing_flow(self, host: str) -> None:
        if messagebox.askyesno("Pairing Required", f"TV at {host} requires pairing.\nStart pairing and view 6-character PIN on TV?"):
            self._start_pairing_flow(host)

    def _show_pin_entry_modal(self, host: str) -> None:
        modal = tk.Toplevel(self.root)
        modal.title("Google TV PIN Pairing")
        modal.geometry("380x200")
        modal.configure(bg="#1e2430")
        modal.transient(self.root)
        modal.grab_set()

        tk.Label(
            modal,
            text="Enter 6-Character PIN",
            font=("Segoe UI", 13, "bold"),
            fg="#ffffff",
            bg="#1e2430",
        ).pack(pady=(16, 4))

        tk.Label(
            modal,
            text="Check the authentication code displayed on your TV screen:",
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#1e2430",
        ).pack(pady=(0, 12))

        pin_entry = tk.Entry(modal, font=("Segoe UI", 16, "bold"), justify="center", width=10, bg="#151921", fg="#ffffff", insertbackground="#ffffff")
        pin_entry.pack(pady=4)
        pin_entry.focus_set()

        def submit():
            code = pin_entry.get().strip()
            if not code:
                return
            modal.destroy()
            self._finish_pairing_flow(code, host)

        btn = tk.Button(
            modal,
            text="Submit PIN",
            font=("Segoe UI", 10, "bold"),
            fg="#ffffff",
            bg="#0d9488",
            activebackground="#0f766e",
            activeforeground="#ffffff",
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
            command=submit,
        )
        btn.pack(pady=14)
        modal.bind("<Return>", lambda e: submit())

    def _finish_pairing_flow(self, code: str, host: str) -> None:
        self.status_var.set("Submitting PIN authentication...")

        def runner():
            try:
                self.client.finish_pairing(code)
                self.client.connect(host)
                self.root.after(0, lambda: self._update_connection_state(True, host))
            except Exception as e:
                self.root.after(0, lambda: self.status_var.set(f"Pairing failed: {e}"))

        threading.Thread(target=runner, daemon=True).start()

    def _show_device_modal(self) -> None:
        """Modal dialog for network scanning and device discovery."""
        modal = tk.Toplevel(self.root)
        modal.title("Discover Google TV Devices")
        modal.geometry("460x420")
        modal.configure(bg="#1e2430")
        modal.transient(self.root)
        modal.grab_set()

        tk.Label(
            modal,
            text="Select or Connect TV",
            font=("Segoe UI", 13, "bold"),
            fg="#ffffff",
            bg="#1e2430",
        ).pack(pady=(16, 6))

        # Device Listbox
        list_frame = tk.Frame(modal, bg="#1e2430")
        list_frame.pack(fill="both", expand=True, padx=20, pady=6)

        device_listbox = tk.Listbox(
            list_frame,
            bg="#151921",
            fg="#e2e8f0",
            selectbackground="#0d9488",
            selectforeground="#ffffff",
            font=("Segoe UI", 10),
            relief="flat",
            highlightthickness=1,
            highlightbackground="#2d3544",
        )
        device_listbox.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=device_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        device_listbox.config(yscrollcommand=scrollbar.set)

        status_lbl = tk.Label(modal, text="Scanning network for TVs...", font=("Segoe UI", 9), fg="#94a3b8", bg="#1e2430")
        status_lbl.pack(pady=4)

        def populate_devices(devs: list[TVDevice]):
            self.discovered_devices = devs
            device_listbox.delete(0, tk.END)
            if devs:
                for d in devs:
                    device_listbox.insert(tk.END, d.label())
                device_listbox.select_set(0)
                status_lbl.configure(text=f"Found {len(devs)} device(s) on network.")
            else:
                status_lbl.configure(text="No devices found via mDNS. Try entering IP manually below.")

        def scan_devices():
            status_lbl.configure(text="Scanning local Wi-Fi (Zeroconf mDNS)...")

            def worker():
                try:
                    devs = self.client.discover(timeout=3.5)
                    self.root.after(0, lambda: populate_devices(devs))
                except Exception as e:
                    self.root.after(0, lambda: status_lbl.configure(text=f"Scan error: {e}"))

            threading.Thread(target=worker, daemon=True).start()

        scan_devices()

        # Manual IP entry
        manual_frame = tk.Frame(modal, bg="#1e2430")
        manual_frame.pack(fill="x", padx=20, pady=8)

        tk.Label(manual_frame, text="Manual IP:", font=("Segoe UI", 9), fg="#94a3b8", bg="#1e2430").pack(side="left", padx=(0, 6))
        ip_entry = tk.Entry(manual_frame, font=("Segoe UI", 10), bg="#151921", fg="#ffffff", insertbackground="#ffffff")
        ip_entry.insert(0, self.current_ip)
        ip_entry.pack(side="left", fill="x", expand=True)

        def connect_selected():
            selected_idx = device_listbox.curselection()
            if selected_idx and selected_idx[0] < len(self.discovered_devices):
                dev = self.discovered_devices[selected_idx[0]]
                self.current_device_name = dev.name
                self.device_name_var.set(dev.name)
                host = dev.host
            else:
                host = ip_entry.get().strip()
                if not host:
                    return
                self.device_name_var.set("Google TV")
            modal.destroy()
            self._connect_host(host)

        btn_row = tk.Frame(modal, bg="#1e2430")
        btn_row.pack(pady=(6, 16))

        tk.Button(
            btn_row,
            text="🔄 Rescan",
            font=("Segoe UI", 9),
            fg="#e2e8f0",
            bg="#242c38",
            relief="flat",
            padx=12,
            pady=5,
            cursor="hand2",
            command=scan_devices,
        ).pack(side="left", padx=6)

        tk.Button(
            btn_row,
            text="Connect & Use",
            font=("Segoe UI", 9, "bold"),
            fg="#ffffff",
            bg="#0d9488",
            relief="flat",
            padx=14,
            pady=5,
            cursor="hand2",
            command=connect_selected,
        ).pack(side="left", padx=6)

    def _open_text_input_dialog(self) -> None:
        """Allows direct text typing to TV search/input fields."""
        text = simpledialog.askstring("Direct Text Input", "Type text or query to send directly to TV:", parent=self.root)
        if text:
            self.status_var.set(f"Sending text: '{text}'...")

            def runner():
                try:
                    self.client.send_text(text)
                    self.root.after(0, lambda: self.status_var.set(f"Sent: '{text}' ✓"))
                except Exception as e:
                    self.root.after(0, lambda: self.status_var.set(f"Text send failed: {e}"))

            threading.Thread(target=runner, daemon=True).start()

    def _open_custom_app_dialog(self) -> None:
        pkg = simpledialog.askstring("Launch Custom App", "Enter Android Package Name\n(e.g., com.google.android.youtube.tv):", parent=self.root)
        if pkg:
            self._launch_app(pkg.strip(), pkg.strip())

    def _show_hotkey_overlay(self) -> None:
        """Displays keyboard hotkey legend overlay."""
        modal = tk.Toplevel(self.root)
        modal.title("Keyboard Hotkeys Legend")
        modal.geometry("420x450")
        modal.configure(bg="#1e2430")
        modal.transient(self.root)

        tk.Label(modal, text="Keyboard Hotkeys Legend", font=("Segoe UI", 13, "bold"), fg="#ffffff", bg="#1e2430").pack(pady=(16, 10))

        hotkeys = [
            ("D-Pad Navigation", "Arrow Keys (▲ ▼ ◄ ►)"),
            ("OK / Select", "Enter"),
            ("Back", "Backspace"),
            ("Home", "H"),
            ("Power", "P"),
            ("Mute", "M"),
            ("Play / Pause", "Space"),
            ("Volume Up / Down", "]  /  ["),
            ("Channel Up / Down", "Page Up / Page Down"),
            ("Toggle Hotkeys Legend", "F1"),
        ]

        card = tk.Frame(modal, bg="#151921", padx=16, pady=12, highlightbackground="#2d3544", highlightthickness=1)
        card.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        for action, key in hotkeys:
            row = tk.Frame(card, bg="#151921")
            row.pack(fill="x", pady=3)
            tk.Label(row, text=action, font=("Segoe UI", 9), fg="#cbd5e1", bg="#151921").pack(side="left")
            tk.Label(row, text=key, font=("Segoe UI", 9, "bold"), fg="#38bdf8", bg="#151921").pack(side="right")

    def _bind_hotkeys(self) -> None:
        bindings = [
            ("<Up>", lambda e: self._send_key("DPAD_UP")),
            ("<Down>", lambda e: self._send_key("DPAD_DOWN")),
            ("<Left>", lambda e: self._send_key("DPAD_LEFT")),
            ("<Right>", lambda e: self._send_key("DPAD_RIGHT")),
            ("<Return>", lambda e: self._send_key("DPAD_CENTER")),
            ("<BackSpace>", lambda e: self._send_key("BACK")),
            ("<space>", lambda e: self._send_key("MEDIA_PLAY_PAUSE")),
            ("<p>", lambda e: self._send_key("POWER")),
            ("<P>", lambda e: self._send_key("POWER")),
            ("<m>", lambda e: self._send_key("MUTE")),
            ("<M>", lambda e: self._send_key("MUTE")),
            ("<h>", lambda e: self._send_key("HOME")),
            ("<H>", lambda e: self._send_key("HOME")),
            ("<bracketright>", lambda e: self._send_key("VOLUME_UP")),
            ("<bracketleft>", lambda e: self._send_key("VOLUME_DOWN")),
            ("<Prior>", lambda e: self._send_key("CHANNEL_UP")),
            ("<Next>", lambda e: self._send_key("CHANNEL_DOWN")),
            ("<F1>", lambda e: self._show_hotkey_overlay()),
        ]
        for seq, callback in bindings:
            self.root.bind(seq, callback)

    def _on_close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = GoogleTVRemoteApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
