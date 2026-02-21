# Google TV Remote for Windows

A native Windows desktop GUI remote for Google TV / Android TV devices on the same Wi-Fi network.

## Features
- Auto-discover Google TV devices on local network
- Manual IP connection fallback
- Pairing PIN flow (same protocol used by Android Google TV remote apps)
- Modern desktop UI (clean cards, split layout, responsive resizing)
- D-pad, navigation, power, volume, media, channel keys
- Text input to TV
- App sidebar with one-click launch (editable app list + package IDs)
- Full keyboard hotkeys for remote buttons with in-app hotkey legend (`F1`)

## Requirements
- Windows 10/11
- Python 3.10+
- Google TV and PC on same Wi-Fi

## Run
```powershell
python -m pip install -r requirements.txt
python main.py
```

## Pairing
1. Click `Discover` (or enter TV IP manually).
2. Click `Connect`.
3. If pairing is required, click `Start Pairing`.
4. Enter the PIN shown on TV and click `Submit PIN`.

Certificates are stored in `certs/` so you usually only pair once.

## Build EXE (optional)
```powershell
python -m pip install pyinstaller
pyinstaller --noconfirm --windowed --onefile --name GoogleTVRemote main.py
```

EXE output: `dist/GoogleTVRemote.exe`
