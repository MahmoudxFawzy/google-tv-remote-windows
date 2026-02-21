import asyncio
import json
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from androidtvremote2 import AndroidTVRemote
from androidtvremote2.exceptions import CannotConnect, ConnectionClosed, InvalidAuth
from zeroconf import ServiceBrowser, ServiceListener, Zeroconf


SERVICE_TYPE = "_androidtvremote2._tcp.local."
APP_NAME = "Google TV Remote (Windows)"
CERT_DIR = Path("certs")
CERT_FILE = CERT_DIR / "client_cert.pem"
KEY_FILE = CERT_DIR / "client_key.pem"
APPS_FILE = Path("tv_apps.json")

DEFAULT_TV_APPS = [
    {"name": "YouTube", "app_id": "com.google.android.youtube.tv"},
    {"name": "Netflix", "app_id": "com.netflix.ninja"},
    {"name": "Prime Video", "app_id": "com.amazon.amazonvideo.livingroom"},
    {"name": "Disney+", "app_id": "com.disney.disneyplus"},
    {"name": "Hulu", "app_id": "com.hulu.livingroomplus"},
    {"name": "Spotify", "app_id": "com.spotify.tv.android"},
    {"name": "Plex", "app_id": "com.plexapp.android"},
    {"name": "Kodi", "app_id": "org.xbmc.kodi"},
]

REMOTE_BUTTONS = [
    {"label": "Power", "key_code": "POWER", "hotkey": "P", "sequence": "<p>"},
    {"label": "Mute", "key_code": "MUTE", "hotkey": "M", "sequence": "<m>"},
    {"label": "Home", "key_code": "HOME", "hotkey": "H", "sequence": "<h>"},
    {"label": "Back", "key_code": "BACK", "hotkey": "Backspace", "sequence": "<BackSpace>"},
    {"label": "Up", "key_code": "DPAD_UP", "hotkey": "Up", "sequence": "<Up>"},
    {"label": "Left", "key_code": "DPAD_LEFT", "hotkey": "Left", "sequence": "<Left>"},
    {"label": "OK", "key_code": "DPAD_CENTER", "hotkey": "Enter", "sequence": "<Return>"},
    {"label": "Right", "key_code": "DPAD_RIGHT", "hotkey": "Right", "sequence": "<Right>"},
    {"label": "Down", "key_code": "DPAD_DOWN", "hotkey": "Down", "sequence": "<Down>"},
    {"label": "Play/Pause", "key_code": "MEDIA_PLAY_PAUSE", "hotkey": "Space", "sequence": "<space>"},
    {"label": "Rewind", "key_code": "MEDIA_REWIND", "hotkey": "J", "sequence": "<j>"},
    {"label": "Forward", "key_code": "MEDIA_FAST_FORWARD", "hotkey": "L", "sequence": "<l>"},
    {"label": "Vol +", "key_code": "VOLUME_UP", "hotkey": "]", "sequence": "<bracketright>"},
    {"label": "Vol -", "key_code": "VOLUME_DOWN", "hotkey": "[", "sequence": "<bracketleft>"},
    {"label": "Ch +", "key_code": "CHANNEL_UP", "hotkey": "PageUp", "sequence": "<Prior>"},
    {"label": "Ch -", "key_code": "CHANNEL_DOWN", "hotkey": "PageDown", "sequence": "<Next>"},
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


@dataclass
class TVApp:
    name: str
    app_id: str

    def label(self) -> str:
        return self.name


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


class GoogleTVClient:
    def __init__(self) -> None:
        CERT_DIR.mkdir(exist_ok=True)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._remote: AndroidTVRemote | None = None
        self._host: str | None = None

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _call(self, coro: asyncio.Future, timeout: float = 30) -> object:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    async def _ensure_remote(self, host: str) -> AndroidTVRemote:
        if self._remote and self._host == host:
            return self._remote
        if self._remote:
            self._remote.disconnect()
        remote = AndroidTVRemote(
            client_name=APP_NAME,
            certfile=str(CERT_FILE),
            keyfile=str(KEY_FILE),
            host=host,
            loop=self._loop,
        )
        await remote.async_generate_cert_if_missing()
        self._remote = remote
        self._host = host
        return remote

    def discover(self, timeout: float = 3.0) -> list[TVDevice]:
        return list(self._call(self._discover(timeout), timeout=timeout + 5))  # type: ignore[arg-type]

    async def _discover(self, timeout: float) -> list[TVDevice]:
        return await self._loop.run_in_executor(None, self._discover_sync, timeout)

    @staticmethod
    def _discover_sync(timeout: float) -> list[TVDevice]:
        zc = Zeroconf()
        collector = _ServiceCollector()
        ServiceBrowser(zc, SERVICE_TYPE, collector)
        time.sleep(timeout)
        zc.close()
        devices = list(collector.devices.values())
        devices.sort(key=lambda d: d.name.lower())
        return devices

    def connect(self, host: str) -> None:
        self._call(self._connect(host))

    async def _connect(self, host: str) -> None:
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

    def close(self) -> None:
        self.disconnect()
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)


class GoogleTVRemoteApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1120x720")
        self.root.minsize(980, 640)

        self.client = GoogleTVClient()
        self.devices_by_label: dict[str, TVDevice] = {}
        self.apps: list[TVApp] = []
        self.apps_by_label: dict[str, TVApp] = {}

        self.status_text = tk.StringVar(value="Ready. Discover a Google TV on your network.")
        self.device_var = tk.StringVar()
        self.ip_var = tk.StringVar()
        self.pair_code_var = tk.StringVar()
        self.text_var = tk.StringVar()
        self.app_name_var = tk.StringVar()
        self.app_id_var = tk.StringVar()

        self._configure_styles()
        self._build_ui()
        self._load_apps()
        self._bind_hotkeys()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_styles(self) -> None:
        self.root.configure(bg="#f2f4f8")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI Semibold", 17), background="#f2f4f8", foreground="#0f172a")
        style.configure("SubHeader.TLabel", font=("Segoe UI", 10), background="#f2f4f8", foreground="#475569")
        style.configure("Card.TLabelframe", background="#ffffff", borderwidth=1, relief="solid")
        style.configure("Card.TLabelframe.Label", background="#ffffff", foreground="#0f172a", font=("Segoe UI Semibold", 10))
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("Accent.TButton", foreground="#ffffff", background="#0d9488", borderwidth=0, padding=(10, 8))
        style.map("Accent.TButton", background=[("active", "#0f766e")])
        style.configure("Soft.TButton", foreground="#0f172a", background="#e2e8f0", borderwidth=0, padding=(10, 8))
        style.map("Soft.TButton", background=[("active", "#cbd5e1")])
        style.configure("Key.TButton", font=("Segoe UI Semibold", 10), padding=(8, 12), borderwidth=0, background="#eaf2ff")
        style.map("Key.TButton", background=[("active", "#d6e7ff")])
        style.configure("Muted.TLabel", background="#ffffff", foreground="#64748b")
        style.configure("Status.TLabel", background="#e2e8f0", foreground="#0f172a", padding=(10, 8))

    def _build_ui(self) -> None:
        shell = ttk.Frame(self.root, padding=14)
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="Google TV Remote", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Modern desktop remote with app launcher and full keyboard hotkeys.",
            style="SubHeader.TLabel",
        ).pack(anchor="w")

        body = ttk.Panedwindow(shell, orient="horizontal")
        body.pack(fill="both", expand=True, pady=(2, 8))

        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=4)
        body.add(right, weight=2)

        self._build_connection_card(left)
        self._build_pairing_card(left)
        self._build_remote_card(left)
        self._build_apps_sidebar(right)
        self._build_hotkeys_sidebar(right)

        ttk.Label(shell, textvariable=self.status_text, style="Status.TLabel", anchor="w").pack(fill="x")

    def _build_connection_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text="Connection", style="Card.TLabelframe", padding=12)
        card.pack(fill="x", pady=(0, 10))

        ttk.Label(card, text="Discovered TVs").grid(row=0, column=0, sticky="w")
        self.device_combo = ttk.Combobox(card, textvariable=self.device_var, state="readonly")
        self.device_combo.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 8))

        ttk.Label(card, text="TV IP (manual)").grid(row=2, column=0, sticky="w")
        ttk.Entry(card, textvariable=self.ip_var).grid(row=3, column=0, columnspan=3, sticky="ew", pady=(4, 8))

        ttk.Button(card, text="Discover  (Ctrl+R)", style="Soft.TButton", command=self._discover_devices).grid(
            row=4, column=0, sticky="ew"
        )
        ttk.Button(card, text="Connect  (Ctrl+Shift+C)", style="Accent.TButton", command=self._connect).grid(
            row=4, column=1, sticky="ew", padx=6
        )
        ttk.Button(card, text="Disconnect  (Ctrl+Shift+X)", style="Soft.TButton", command=self._disconnect).grid(
            row=4, column=2, sticky="ew"
        )

        card.grid_columnconfigure(0, weight=1)
        card.grid_columnconfigure(1, weight=1)
        card.grid_columnconfigure(2, weight=1)

    def _build_pairing_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text="Pairing", style="Card.TLabelframe", padding=12)
        card.pack(fill="x", pady=(0, 10))
        ttk.Button(card, text="Start Pairing", style="Soft.TButton", command=self._start_pairing).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Entry(card, textvariable=self.pair_code_var).grid(row=0, column=1, padx=8, sticky="ew")
        ttk.Button(card, text="Submit PIN", style="Accent.TButton", command=self._finish_pairing).grid(
            row=0, column=2, sticky="ew"
        )
        card.grid_columnconfigure(1, weight=1)

    def _build_remote_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text="Remote", style="Card.TLabelframe", padding=12)
        card.pack(fill="both", expand=True)
        self.remote_card = card

        positions = [
            ("POWER", 0, 0),
            ("MUTE", 0, 1),
            ("HOME", 0, 2),
            ("BACK", 0, 3),
            ("DPAD_UP", 1, 1),
            ("DPAD_LEFT", 2, 0),
            ("DPAD_CENTER", 2, 1),
            ("DPAD_RIGHT", 2, 2),
            ("DPAD_DOWN", 3, 1),
            ("MEDIA_PLAY_PAUSE", 4, 0),
            ("MEDIA_REWIND", 4, 1),
            ("MEDIA_FAST_FORWARD", 4, 2),
            ("VOLUME_UP", 5, 0),
            ("VOLUME_DOWN", 5, 1),
            ("CHANNEL_UP", 5, 2),
            ("CHANNEL_DOWN", 5, 3),
        ]
        for key_code, row, col in positions:
            spec = next(x for x in REMOTE_BUTTONS if x["key_code"] == key_code)
            caption = f'{spec["label"]}\n[{spec["hotkey"]}]'
            ttk.Button(
                card,
                text=caption,
                style="Key.TButton",
                command=lambda k=key_code: self._send_key(k),
            ).grid(row=row, column=col, sticky="nsew", padx=5, pady=5)

        text_row = ttk.Frame(card, style="Card.TFrame")
        text_row.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(12, 4))
        self.text_entry = ttk.Entry(text_row, textvariable=self.text_var)
        self.text_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(text_row, text="Send  (Ctrl+Enter)", style="Accent.TButton", command=self._send_text).pack(
            side="left", padx=(8, 0)
        )

        ttk.Label(
            card,
            text="Press F1 for full shortcut list. Hotkeys are disabled while typing in text fields.",
            style="Muted.TLabel",
        ).grid(row=7, column=0, columnspan=4, sticky="w", pady=(6, 0))

        for i in range(4):
            card.grid_columnconfigure(i, weight=1)

    def _build_apps_sidebar(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text="TV Apps", style="Card.TLabelframe", padding=12)
        card.pack(fill="both", expand=True, pady=(0, 10))

        self.apps_listbox = tk.Listbox(
            card,
            height=11,
            activestyle="none",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground="#cbd5e1",
            font=("Segoe UI", 10),
        )
        self.apps_listbox.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.apps_listbox.bind("<<ListboxSelect>>", self._on_app_selected)

        scroll = ttk.Scrollbar(card, orient="vertical", command=self.apps_listbox.yview)
        scroll.grid(row=0, column=2, sticky="ns")
        self.apps_listbox.configure(yscrollcommand=scroll.set)

        ttk.Label(card, text="App Name").grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.app_name_var).grid(row=2, column=0, columnspan=3, sticky="ew", pady=(2, 6))
        ttk.Label(card, text="Package ID").grid(row=3, column=0, columnspan=3, sticky="w")
        ttk.Entry(card, textvariable=self.app_id_var).grid(row=4, column=0, columnspan=3, sticky="ew", pady=(2, 8))

        ttk.Button(card, text="Launch  (Double-click)", style="Accent.TButton", command=self._launch_selected_app).grid(
            row=5, column=0, columnspan=3, sticky="ew", pady=(0, 8)
        )
        ttk.Button(card, text="Add / Update", style="Soft.TButton", command=self._upsert_app).grid(
            row=6, column=0, sticky="ew"
        )
        ttk.Button(card, text="Remove", style="Soft.TButton", command=self._remove_app).grid(
            row=6, column=1, sticky="ew", padx=6
        )
        ttk.Button(card, text="Defaults", style="Soft.TButton", command=self._reset_apps_defaults).grid(
            row=6, column=2, sticky="ew"
        )

        card.grid_rowconfigure(0, weight=1)
        card.grid_columnconfigure(0, weight=1)
        card.grid_columnconfigure(1, weight=1)
        card.grid_columnconfigure(2, weight=1)
        self.apps_listbox.bind("<Double-Button-1>", lambda _: self._launch_selected_app())

    def _build_hotkeys_sidebar(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text="Hotkeys", style="Card.TLabelframe", padding=12)
        card.pack(fill="x")
        self.hotkeys_list = tk.Listbox(
            card,
            height=11,
            activestyle="none",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground="#cbd5e1",
            font=("Consolas", 10),
        )
        self.hotkeys_list.pack(fill="x")
        for spec in REMOTE_BUTTONS:
            self.hotkeys_list.insert("end", f'{spec["hotkey"]:>10}  ->  {spec["label"]}')
        self.hotkeys_list.insert("end", "    Ctrl+R  ->  Discover")
        self.hotkeys_list.insert("end", "Ctrl+Shift+C->  Connect")
        self.hotkeys_list.insert("end", "Ctrl+Shift+X->  Disconnect")
        self.hotkeys_list.insert("end", " Ctrl+Enter ->  Send Text")
        self.hotkeys_list.insert("end", "         F1 ->  Hotkey Help")

    def _run_background(self, fn, on_done=None) -> None:
        def worker() -> None:
            try:
                result = fn()
                if on_done:
                    self.root.after(0, lambda r=result: on_done(r))
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda e=exc: self._set_status(f"Error: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def _set_status(self, message: str) -> None:
        self.status_text.set(message)

    def _selected_host(self) -> str:
        manual = self.ip_var.get().strip()
        if manual:
            return manual
        label = self.device_var.get().strip()
        if label and label in self.devices_by_label:
            return self.devices_by_label[label].host
        raise RuntimeError("Select a discovered TV or enter its IP address.")

    def _load_apps(self) -> None:
        if not APPS_FILE.exists():
            self.apps = [TVApp(**x) for x in DEFAULT_TV_APPS]
            self._save_apps()
        else:
            try:
                data = json.loads(APPS_FILE.read_text(encoding="utf-8"))
                self.apps = [TVApp(name=item["name"], app_id=item["app_id"]) for item in data]
            except Exception:  # noqa: BLE001
                self.apps = [TVApp(**x) for x in DEFAULT_TV_APPS]
                self._save_apps()
        self._refresh_apps_list()

    def _save_apps(self) -> None:
        APPS_FILE.write_text(
            json.dumps([asdict(a) for a in self.apps], indent=2),
            encoding="utf-8",
        )

    def _refresh_apps_list(self) -> None:
        self.apps.sort(key=lambda a: a.name.lower())
        self.apps_by_label = {app.label(): app for app in self.apps}
        self.apps_listbox.delete(0, "end")
        for app in self.apps:
            self.apps_listbox.insert("end", app.label())

    def _on_app_selected(self, _: object) -> None:
        selected = self._selected_app()
        if selected:
            self.app_name_var.set(selected.name)
            self.app_id_var.set(selected.app_id)

    def _selected_app(self) -> TVApp | None:
        selected = self.apps_listbox.curselection()
        if not selected:
            return None
        label = self.apps_listbox.get(selected[0])
        return self.apps_by_label.get(label)

    def _upsert_app(self) -> None:
        name = self.app_name_var.get().strip()
        app_id = self.app_id_var.get().strip()
        if not name or not app_id:
            messagebox.showerror("Missing Data", "Enter both app name and package ID.")
            return
        existing = next((x for x in self.apps if x.name.lower() == name.lower()), None)
        if existing:
            existing.app_id = app_id
        else:
            self.apps.append(TVApp(name=name, app_id=app_id))
        self._save_apps()
        self._refresh_apps_list()
        self._set_status(f"Saved app: {name}")

    def _remove_app(self) -> None:
        selected = self._selected_app()
        if not selected:
            messagebox.showerror("No App Selected", "Choose an app to remove.")
            return
        self.apps = [a for a in self.apps if a.name != selected.name]
        self._save_apps()
        self._refresh_apps_list()
        self.app_name_var.set("")
        self.app_id_var.set("")
        self._set_status(f"Removed app: {selected.name}")

    def _reset_apps_defaults(self) -> None:
        self.apps = [TVApp(**x) for x in DEFAULT_TV_APPS]
        self._save_apps()
        self._refresh_apps_list()
        self._set_status("App list reset to defaults.")

    def _discover_devices(self) -> None:
        self._set_status("Discovering TVs...")

        def work() -> list[TVDevice]:
            return self.client.discover(timeout=3.0)

        def done(devices: list[TVDevice]) -> None:
            self.devices_by_label = {d.label(): d for d in devices}
            labels = list(self.devices_by_label.keys())
            self.device_combo["values"] = labels
            if labels:
                self.device_combo.current(0)
                self._set_status(f"Found {len(labels)} TV(s).")
            else:
                self._set_status("No TVs discovered. Enter TV IP manually.")

        self._run_background(work, done)

    def _connect(self) -> None:
        def work() -> None:
            host = self._selected_host()
            self.client.connect(host)

        self._set_status("Connecting...")

        def worker() -> None:
            try:
                work()
                self.root.after(0, lambda: self._set_status("Connected. Remote ready."))
            except PairingRequiredError:
                self.root.after(0, lambda: self._set_status("Pairing required. Click Start Pairing."))
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda e=exc: self._set_status(f"Connect failed: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def _disconnect(self) -> None:
        self.client.disconnect()
        self._set_status("Disconnected.")

    def _start_pairing(self) -> None:
        def work() -> None:
            host = self._selected_host()
            self.client.start_pairing(host)

        self._set_status("Starting pairing. Check your TV for PIN.")
        self._run_background(work, lambda _: self._set_status("Enter the PIN shown on TV, then click Submit PIN."))

    def _finish_pairing(self) -> None:
        code = self.pair_code_var.get().strip()
        if not code:
            messagebox.showerror("Missing PIN", "Enter the PIN shown on TV.")
            return

        def work() -> None:
            host = self._selected_host()
            self.client.finish_pairing(code)
            self.client.connect(host)

        self._set_status("Submitting PIN...")
        self._run_background(work, lambda _: self._set_status("Pairing successful. Connected."))

    def _send_key(self, key_code: str) -> None:
        self._run_background(lambda: self.client.send_key(key_code))

    def _send_text(self) -> None:
        text = self.text_var.get().strip()
        if not text:
            return

        def work() -> None:
            self.client.send_text(text)

        self._run_background(work, lambda _: self.text_var.set(""))

    def _launch_selected_app(self) -> None:
        app = self._selected_app()
        if not app:
            messagebox.showerror("No App Selected", "Select an app from the list.")
            return

        def work() -> None:
            self.client.launch_app(app.app_id)

        self._set_status(f"Launching {app.name}...")
        self._run_background(work, lambda _: self._set_status(f"Launched {app.name}."))

    def _launch_app_by_name(self, app_name: str) -> None:
        app = next((x for x in self.apps if x.name.lower() == app_name.lower()), None)
        if not app:
            self._set_status(f"App not found: {app_name}")
            return
        self._run_background(lambda: self.client.launch_app(app.app_id))
        self._set_status(f"Launching {app.name}...")

    def _bind_hotkeys(self) -> None:
        for spec in REMOTE_BUTTONS:
            self.root.bind_all(spec["sequence"], lambda e, k=spec["key_code"]: self._handle_hotkey(e, k), add="+")
        self.root.bind_all("<Control-r>", lambda e: self._handle_action_hotkey(e, self._discover_devices), add="+")
        self.root.bind_all("<Control-C>", lambda e: self._handle_action_hotkey(e, self._connect), add="+")
        self.root.bind_all("<Control-X>", lambda e: self._handle_action_hotkey(e, self._disconnect), add="+")
        self.root.bind_all(
            "<Control-Return>",
            lambda e: self._handle_action_hotkey(e, self._send_text, allow_typing_widget=True),
            add="+",
        )
        self.root.bind_all("<F1>", self._show_hotkeys_help, add="+")
        self.root.bind_all(
            "<y>",
            lambda e: self._handle_action_hotkey(e, lambda: self._launch_app_by_name("YouTube")),
            add="+",
        )

    def _is_typing_widget(self, widget: tk.Widget | None) -> bool:
        if widget is None:
            return False
        return widget.winfo_class() in {"Entry", "TEntry", "Text"}

    def _handle_hotkey(self, event: tk.Event, key_code: str):
        if self._is_typing_widget(event.widget):
            return None
        self._send_key(key_code)
        return "break"

    def _handle_action_hotkey(self, event: tk.Event, action, allow_typing_widget: bool = False):
        if not allow_typing_widget and self._is_typing_widget(event.widget):
            return None
        action()
        return "break"

    def _show_hotkeys_help(self, _: tk.Event | None = None):
        lines = [f'{spec["hotkey"]}: {spec["label"]}' for spec in REMOTE_BUTTONS]
        lines.extend(
            [
                "Y: Launch YouTube app",
                "Ctrl+R: Discover TVs",
                "Ctrl+Shift+C: Connect",
                "Ctrl+Shift+X: Disconnect",
                "Ctrl+Enter: Send text",
            ]
        )
        messagebox.showinfo("Keyboard Shortcuts", "\n".join(lines))
        return "break"

    def _on_close(self) -> None:
        self.client.close()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    app = GoogleTVRemoteApp(root)
    app._discover_devices()
    root.mainloop()


if __name__ == "__main__":
    main()
