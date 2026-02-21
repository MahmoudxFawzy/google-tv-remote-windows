import asyncio
import threading
import time
from dataclasses import dataclass
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


class PairingRequiredError(Exception):
    pass


@dataclass
class TVDevice:
    name: str
    host: str
    port: int

    def label(self) -> str:
        return f"{self.name} ({self.host})"


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
        self.root.geometry("430x690")
        self.root.minsize(390, 640)

        self.client = GoogleTVClient()
        self.devices_by_label: dict[str, TVDevice] = {}

        self.status_text = tk.StringVar(value="Ready. Discover a Google TV on your network.")
        self.device_var = tk.StringVar()
        self.ip_var = tk.StringVar()
        self.pair_code_var = tk.StringVar()
        self.text_var = tk.StringVar()

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")

        top = ttk.Frame(self.root, padding=12)
        top.pack(fill="x")

        ttk.Label(top, text="Discovered TVs").grid(row=0, column=0, sticky="w")
        self.device_combo = ttk.Combobox(top, textvariable=self.device_var, state="readonly")
        self.device_combo.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 8))

        ttk.Label(top, text="TV IP (optional manual)").grid(row=2, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.ip_var).grid(row=3, column=0, columnspan=3, sticky="ew", pady=(4, 8))

        ttk.Button(top, text="Discover", command=self._discover_devices).grid(row=4, column=0, sticky="ew")
        ttk.Button(top, text="Connect", command=self._connect).grid(row=4, column=1, sticky="ew", padx=6)
        ttk.Button(top, text="Disconnect", command=self._disconnect).grid(row=4, column=2, sticky="ew")

        top.grid_columnconfigure(0, weight=1)
        top.grid_columnconfigure(1, weight=1)
        top.grid_columnconfigure(2, weight=1)

        pair = ttk.LabelFrame(self.root, text="Pairing", padding=12)
        pair.pack(fill="x", padx=12, pady=(0, 10))

        ttk.Button(pair, text="Start Pairing", command=self._start_pairing).grid(row=0, column=0, sticky="ew")
        ttk.Entry(pair, textvariable=self.pair_code_var).grid(row=0, column=1, padx=8, sticky="ew")
        ttk.Button(pair, text="Submit PIN", command=self._finish_pairing).grid(row=0, column=2, sticky="ew")
        pair.grid_columnconfigure(1, weight=1)

        remote = ttk.LabelFrame(self.root, text="Remote", padding=12)
        remote.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        # Top row
        self._make_key_button(remote, "Power", "POWER", 0, 0)
        self._make_key_button(remote, "Mute", "MUTE", 0, 1)
        self._make_key_button(remote, "Home", "HOME", 0, 2)
        self._make_key_button(remote, "Back", "BACK", 0, 3)

        # D-pad
        self._make_key_button(remote, "▲", "DPAD_UP", 1, 1)
        self._make_key_button(remote, "◀", "DPAD_LEFT", 2, 0)
        self._make_key_button(remote, "OK", "DPAD_CENTER", 2, 1)
        self._make_key_button(remote, "▶", "DPAD_RIGHT", 2, 2)
        self._make_key_button(remote, "▼", "DPAD_DOWN", 3, 1)

        # Media row
        self._make_key_button(remote, "Play/Pause", "MEDIA_PLAY_PAUSE", 4, 0)
        self._make_key_button(remote, "Rewind", "MEDIA_REWIND", 4, 1)
        self._make_key_button(remote, "Forward", "MEDIA_FAST_FORWARD", 4, 2)
        self._make_key_button(remote, "YouTube", "PROG_RED", 4, 3)

        # Volume/channel
        self._make_key_button(remote, "Vol +", "VOLUME_UP", 5, 0)
        self._make_key_button(remote, "Vol -", "VOLUME_DOWN", 5, 1)
        self._make_key_button(remote, "Ch +", "CHANNEL_UP", 5, 2)
        self._make_key_button(remote, "Ch -", "CHANNEL_DOWN", 5, 3)

        # Text input
        text_frame = ttk.Frame(remote)
        text_frame.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        ttk.Entry(text_frame, textvariable=self.text_var).pack(side="left", fill="x", expand=True)
        ttk.Button(text_frame, text="Send Text", command=self._send_text).pack(side="left", padx=(8, 0))

        for i in range(4):
            remote.grid_columnconfigure(i, weight=1)

        status = ttk.Label(
            self.root,
            textvariable=self.status_text,
            relief="sunken",
            anchor="w",
            padding=(10, 8),
        )
        status.pack(fill="x", side="bottom")

    def _make_key_button(self, parent: ttk.Widget, label: str, key_code: str, row: int, col: int) -> None:
        ttk.Button(parent, text=label, command=lambda: self._send_key(key_code)).grid(
            row=row, column=col, sticky="nsew", padx=4, pady=4, ipady=8
        )

    def _run_background(self, fn, on_done=None) -> None:
        def worker() -> None:
            try:
                result = fn()
                self.root.after(0, lambda: on_done(result) if on_done else None)
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

        def done(_: object) -> None:
            self._set_status("Connected. Remote ready.")

        def worker() -> None:
            try:
                work()
                self.root.after(0, lambda: done(None))
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
            messagebox.showerror("Missing PIN", "Enter the 6-digit PIN shown on TV.")
            return

        def work() -> None:
            host = self._selected_host()
            self.client.finish_pairing(code)
            self.client.connect(host)

        self._set_status("Submitting PIN...")
        self._run_background(work, lambda _: self._set_status("Pairing successful. Connected."))

    def _send_key(self, key_code: str) -> None:
        def work() -> None:
            self.client.send_key(key_code)

        self._run_background(work)

    def _send_text(self) -> None:
        text = self.text_var.get()
        if not text:
            return

        def work() -> None:
            self.client.send_text(text)

        self._run_background(work, lambda _: self.text_var.set(""))

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
