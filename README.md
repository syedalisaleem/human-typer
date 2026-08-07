# Human Typer

A Windows desktop app that types your code into VS Code (or any focused
window) at a realistic, human pace — with natural jitter, thinking pauses,
burst-and-rest flow, and the occasional typo.

## Features

- **Human pacing engine** — log-normal keystroke intervals, burst-and-rest
  flow states, finger hesitations, long-line slowdowns, and reading pauses
  at line starts
- **Floating control bar** — always-on-top Pause / Resume / Stop with live
  progress, even while the app minimizes itself during typing
- **Auto-indent aware** — compensates for the editor's automatic indentation
  so the output matches your code exactly
- **Optional typos & self-fixes** — rare mistakes that get backspaced and
  corrected
- **Privacy first** — no accounts, no telemetry, no network. Your code never
  leaves your machine.
- **No dependencies** — pure Python standard library
- **Settings persistence** — remembers your speed and toggles across launches

## Download

Grab the ready-to-run `HumanTyper.exe` from the
[website](https://syedalisaleem.github.io/human-typer/) — no Python install
required (Windows 10/11).

## Usage

1. Paste your code (or load it from a file / clipboard).
2. Pick a typing speed and toggles: human jitter, thinking pauses, typos.
3. Click **Start Typing** and focus VS Code during the countdown.
4. Use the floating bar to pause, resume or stop — or press **F8** to abort.

## Run from source

```powershell
python human_typer.py
```

Requires Python 3.8+ and the tkinter module (included with the standard
Windows installer).

## Build the exe

```powershell
pip install pyinstaller
python make_icon.py
python -m PyInstaller --noconfirm --onefile --windowed --name HumanTyper --icon app.ico human_typer.py
```

The executable lands in `dist/`; copy it to `website/downloads/` and update
the SHA-256 in `website/index.html` (or use the release assets).

## Important

This tool is meant for creating demo videos, tutorials and screen recordings
of content you own. **Do not use it in proctored exams, coding interviews, or
anywhere automation is prohibited.**

## License

[MIT](LICENSE)
