# MyGuard

Open-source desktop privacy guard that watches the webcam for onlookers and shields your screen.
All processing is local; no frames or face data leave the machine.

## Features
- **Dynamic Island** capsule at top-centre: `Protected` (idle), green *Trusted viewer* flash, red pulsing *Unauthorized Viewer Detected*.
- **Frosted-glass shield** over every monitor while an unapproved viewer is looking; fades out when they leave.
- **Trusted faces** (owner, colleagues, friends) stored as embeddings only (no images) in `data/trusted_faces.json`.
- **Low resource use**: 640x480 capture, 5 FPS default, single background `QThread`, OpenCV limited to one thread.
- **Two-tier pipeline**: MediaPipe detection counts faces; embeddings (OpenCV SFace) run only when more than one face is present.
- Tray menu: toggle protection, register/manage faces, settings, exit. Optional run-on-startup.

## Install
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py            # or: python -m src.main
```
On first recognition use, the SFace model (~37 MB) is downloaded once to `data/models/`. For offline use, place
`face_recognition_sface_2021dec.onnx` (from the OpenCV Zoo) in that folder.

## Usage
1. Tray icon -> **Register / Manage Faces** -> enter a name, press *Capture face* (5 samples). Register yourself too if you enable *verify main user*.
2. Work normally. The largest face is assumed to be you; any other face that is looking toward the screen and is not whitelisted triggers the configured actions (island / shield / sound).
3. Tune thresholds under **Settings** (`data/settings.json`).

## Layout
```
src/core   camera_stream, face_detector, face_recognizer (+ trusted-face store), vision_worker
src/ui     dynamic_island, frosted_glass, face_enrollment, settings_dialog, tray_manager
src/utils  config_manager, sound_player, autostart
```
Data flow: `main` loads config -> island + tray appear -> `VisionWorker` grabs a frame every ~200 ms ->
`threat_detected` / `threat_cleared` / `trusted_verified` signals drive island, shield and sound.

## Platform notes
- **Windows**: live acrylic blur via `SetWindowCompositionAttribute` (`native_blur`); falls back to a tint if unavailable.
- **macOS**: grant Camera and Screen Recording permission (the blur uses a screen snapshot). Linux/macOS shield is a snapshot taken when the threat starts, so it does not update live.
- **Linux/Wayland**: compositors may ignore always-on-top and positioning hints for the island; X11 works best.

## Limitations
- Face detection is not a security boundary: tune `detection_confidence`, `match_threshold` and `max_yaw` for your camera.
- Embeddings are stored as plain JSON with owner-only file permissions, not encrypted. Use full-disk encryption.
- The "looking at the screen" check is a cheap head-yaw heuristic from facial landmarks, not gaze tracking.

## License
MIT

## Windows installer
Data lives in `%APPDATA%\MyGuard` (settings, trusted faces, log); the install folder is read-only.
Build `Setup.exe` on Windows with Python 3.10-3.12 and Inno Setup 6 installed:
```
build_windows.bat        ->  dist_installer\Setup.exe
```
Without a Windows machine, push the repo to GitHub and run the *Build Windows installer* workflow; download `Setup` from its artifacts.
Uninstalling keeps `%APPDATA%\MyGuard`; delete it manually to remove registered faces.
