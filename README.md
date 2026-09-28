# Google TV Remote for Windows 📺 🎛️

[![GitHub License](https://img.shields.io/github/license/MahmoudxFawzy/google-tv-remote-windows?style=flat-square&color=blue)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python)](https://www.python.org/)
[![Platform Support](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-blue?style=flat-square&logo=windows)](https://www.microsoft.com/windows)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/MahmoudxFawzy/google-tv-remote-windows?style=flat-square&color=orange)](https://github.com/MahmoudxFawzy/google-tv-remote-windows/releases)
[![Download Executable](https://img.shields.io/badge/Download-Portable_.exe-00C853?style=flat-square&logo=windows&logoColor=white)](https://github.com/MahmoudxFawzy/google-tv-remote-windows/releases/latest)
[![GitHub stars](https://img.shields.io/github/stars/MahmoudxFawzy/google-tv-remote-windows?style=flat-square)](https://github.com/MahmoudxFawzy/google-tv-remote-windows/stargazers)

A lightweight, modern, native Windows desktop remote control app for **Google TV** and **Android TV** devices. Control your TV directly from your computer over the local Wi-Fi network with advanced features like keyboard hotkeys, automatic device discovery, custom app launchers, and direct text input.

> [!TIP]
> ### ⚡ Quick Download (No Python Required)
> Want to use the remote right away without installing Python or cloning code?
>
> 🚀 **[⬇️ Download Standalone Portable Windows App (`GoogleTVRemote.exe`)](https://github.com/MahmoudxFawzy/google-tv-remote-windows/releases/latest)**
>
> *Single standalone executable — just download and double-click to run!*

---

## 🌟 Key Features

*   🔍 **Automatic Device Discovery**: Auto-scans and lists Google TV / Android TV devices on your local network using mDNS (Zeroconf).
*   🌐 **Manual IP Fallback**: Direct connection option for hidden networks or stubborn network setups.
*   🔒 **Secure Pairing Flow**: Standard PIN-based pairing protocol (uses the exact same API and security protocol as Google's official Android/iOS Google TV apps).
*   🎨 **Modern Tkinter GUI**: Clean, split-pane layout with responsive cards, scrollable panels, and intuitive controls.
*   ⌨️ **Full Keyboard Hotkeys**: Navigate your TV instantly using your PC keyboard (arrow keys, Backspace, Enter, Space, and more) with an in-app legend overlay (`F1`).
*   📝 **Direct Text Input**: Type search queries, passwords, and URLs on your PC and send them directly to the TV input fields.
*   🚀 **Custom App Sidebar**: Launch preloaded apps (YouTube, Netflix, Prime Video, Disney+, Spotify, Plex, Kodi) or add your own apps using package IDs via `tv_apps.json`.
*   📦 **Single File Build**: Bundle the entire application into a standalone Windows Executable (`.exe`) using PyInstaller.

---

## 📋 System Requirements

*   **Operating System**: Windows 10 or Windows 11.
*   **Python**: Version 3.10 or newer *(only required if running from source)*.
*   **Network**: Both the Windows PC and the Google TV / Android TV must be connected to the same Wi-Fi / LAN network.

---

## 🚀 Quick Start & Installation

### Option A: Standalone Portable App *(Recommended)*

1. Head to the [**Latest Releases**](https://github.com/MahmoudxFawzy/google-tv-remote-windows/releases/latest) page.
2. Download **`GoogleTVRemote.exe`**.
3. Double-click to launch — no installation, Python environment, or terminal commands needed.

---

### Option B: Run from Source *(Developers)*

1. Clone this repository:
   ```powershell
   git clone https://github.com/MahmoudxFawzy/google-tv-remote-windows.git
   cd google-tv-remote-windows
   ```

2. Install dependencies:
   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Start the application:
   ```powershell
   python main.py
   ```

---

## 🔒 Pairing and Connection Guide

1.  **Discover**: Click the **Discover** button to scan for TVs on your network. Alternatively, type your TV's local IP address manually.
2.  **Connect**: Select your device and click **Connect**.
3.  **Start Pairing**: If this is your first time connecting to the device, click **Start Pairing**. A 6-character authentication PIN will pop up on your TV screen.
4.  **Submit PIN**: Enter the PIN into the desktop app and click **Submit PIN**.
5.  **Enjoy**: Once paired, your client certificates are securely saved in the local `certs/` directory, meaning you only need to pair your TV once!

---

## ⌨️ Keyboard Hotkeys Legend

Control your TV like a power user. Press `F1` inside the app to toggle the hotkey legend:

| Remote Button | PC Keyboard Hotkey | Tkinter Event |
| :--- | :--- | :--- |
| **Power** | `P` | Toggle TV power state |
| **Mute** | `M` | Mute/unmute TV audio |
| **Home** | `H` | Go to TV Home screen |
| **Back** | `Backspace` | Go back |
| **OK / Select** | `Enter` | Select active element |
| **D-Pad Up/Down/Left/Right** | `Arrow Keys` | Move navigation cursor |
| **Play / Pause** | `Space` | Toggle media playback |
| **Rewind** | `J` | Rewind media |
| **Fast Forward** | `L` | Fast-forward media |
| **Volume Up / Down** | `]` / `[` | Adjust TV volume |
| **Channel Up / Down** | `PageUp` / `PageDown` | Switch channels |

---

## 🛠️ App Configuration (`tv_apps.json`)

You can edit or extend the quick-launch sidebar by editing the `tv_apps.json` file in the application directory. It maps app names to their Android package identifier:

```json
[
  {
    "name": "YouTube",
    "app_id": "com.google.android.youtube.tv"
  },
  {
    "name": "Netflix",
    "app_id": "com.netflix.ninja"
  }
]
```

Add any custom app by looking up its Android Package Name (e.g., from the Google Play Store URL) and appending it to the list.

---

## 📦 Building a Standalone EXE

You can compile the application into a single `.exe` file that runs on any Windows machine without needing Python installed.

1.  Install PyInstaller:
    ```powershell
    python -m pip install pyinstaller
    ```
2.  Run the build script:
    ```powershell
    pyinstaller --noconfirm --windowed --onefile --name GoogleTVRemote main.py
    ```
3.  Your compiled executable will be located in the `dist/` directory: `dist/GoogleTVRemote.exe`.

---

## 🔧 Troubleshooting

*   **TV Not Discovered**: Ensure that your TV is powered on, connected to the same network, and mDNS/Zeroconf is not blocked by your router's client isolation settings. Try connecting manually by entering the TV's IP address.
*   **Connection Refused**: Check if your PC's firewall blocks UDP port `5353` (for Zeroconf) or TCP port `6466` / `6467` (used by the Google TV pairing protocol).
*   **Re-pairing Needed**: If you reset your TV or wish to pair fresh, delete the files inside the `certs/` directory and reconnect.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
