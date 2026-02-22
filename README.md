# Asheron's Call One-Click Installer

A lightweight, automated GUI tool designed to make installing and setting up [Asheron's Call](https://emulator.ac/) as fast and user-friendly as possible for new players. 

Instead of manually hunting down ancient forum links, extracting ZIP files into specific C:\ drive folders, and figuring out launcher prerequisites, this script automates the standard setup process from start to finish.

## Features
* **Automated Base Game Setup:** Silently fetches the official `ac1install.exe` from the Archive.org Wayback Machine and initiates the Turbine setup.
* **Hybrid EoR File Patching:** Automatically navigates the user past Mega.nz's anti-bot protections to download the End of Retail (EoR) client files, then automatically extracts and patches them directly into the Turbine directory.
* **Launcher Integration:** Downloads and native-launches the official ThwargLauncher setup so players can immediately connect to emulator servers.
* **No Dependencies:** Built entirely with Python's standard library (`tkinter`, `urllib`, `os`, `zipfile`).

## How to Use (For Players)
If you just want to play the game, you do not need to download the source code! 
1. Go to the **Releases** tab on the right side of this GitHub page.
2. Download the latest `.exe` file.
3. Double-click the `.exe` and click **"Start 1-Click Install"**.
4. Follow the on-screen prompts. 

*Note: Because this is a community-made tool, Windows SmartScreen or your web browser might flag the `.exe` as unrecognized. You may need to click "More Info" -> "Run Anyway".*

## How to Compile (For Developers)
If you want to modify the code or compile the `.exe` yourself, follow these steps:

### Prerequisites
* Python 3.x installed
* PyInstaller (`pip install pyinstaller`)

### Build Instructions
1. Clone this repository or download `AC_OneClick_Installer.py`.
2. Open your Command Prompt or PowerShell in the folder containing the script.
3. Run the following command to compile it into a standalone executable:
   ```bash
   python -m PyInstaller --onefile --windowed AC_OneClick_Installer.py

## Disclaimer
Asheron's Call is a registered trademark of Turbine, Inc. and WB Games Inc. This project is a community-driven tool and is not affiliated with, endorsed by, or associated with Turbine, WB Games, or ACEmulator in any official capacity.
