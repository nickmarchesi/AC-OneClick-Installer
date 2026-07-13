"""
Asheron's Call One-Click Installer  (v2)

A user-friendly GUI that automates installing Asheron's Call, the End of
Retail (EoR) client files, and ThwargLauncher.

What's new in v2:
  * Resumable: each step is tracked. If a step fails (or you close the app),
    re-running skips everything that already finished.
  * Verified downloads: files are downloaded with a real progress bar,
    checked against the server's reported size, and retried up to 3 times.
  * Partial-download resume: interrupted downloads pick up where they left
    off instead of starting over (important for the slow Wayback Machine).
  * Zip validation: the EoR zip is integrity-tested and sanity-checked
    (must actually contain AC client files) before anything is extracted.
  * Step checklist UI: users can SEE what succeeded, what failed, and what
    is being skipped -- no more guessing.
  * Log file: everything is written to install_log.txt for easy support.
  * Disk space check before extracting the multi-GB EoR files.

Still 100% Python standard library. Compile the same way as before:
    python -m PyInstaller --onefile --windowed AC_OneClick_Installer.py
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import sys
import json
import time
import shutil
import zipfile
import threading
import webbrowser
import traceback
import urllib.request
import urllib.error

# --------------------------------------------------------------------------
# Configurable URLs and paths
# --------------------------------------------------------------------------

AC1_INSTALLER_URL = ("https://web.archive.org/web/20201121104423/"
                     "http://content.turbine.com/sites/clientdl/ac1/ac1install.exe")

# Mega requires a browser download (encryption / anti-bot), so we intercept.
MEGA_EOR_URL = "https://mega.nz/#!Q98n0BiR!p5IugPS8ZkQ7uX2A_LdN3Un2_wMX4gZBHowgs1Qomng"

THWARG_URL = "http://www.thwargle.com/thwarglauncher/updates/ThwargLauncherInstaller.exe"

DEFAULT_INSTALL_DIR = r"C:\Turbine\Asheron's Call"

TEMP_DIR = os.path.join(os.environ.get("TEMP", "."), "AC_Installer")
STATE_FILE = os.path.join(TEMP_DIR, "install_state.json")
LOG_FILE = os.path.join(TEMP_DIR, "install_log.txt")

# Minimum sane sizes (bytes). Anything smaller = the "download" was actually
# an error page or a truncated file, and must not be treated as success.
MIN_SIZE_AC1 = 20 * 1024 * 1024      # ac1install.exe is ~100+ MB
MIN_SIZE_THWARG = 500 * 1024         # Thwarg installer is a few MB
MIN_SIZE_EOR_ZIP = 200 * 1024 * 1024 # EoR client zip is > 1 GB

# Free space needed on the install drive before extracting EoR (bytes)
REQUIRED_FREE_SPACE = 4 * 1024 ** 3  # 4 GB

DOWNLOAD_RETRIES = 3

# Files that prove the EoR zip is the real deal (checked case-insensitively)
EOR_EXPECTED_FILES = ("acclient.exe", "client_portal.dat")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# Step IDs (order matters)
STEP_BASE_GAME = "base_game"
STEP_EOR_PATCH = "eor_patch"
STEP_THWARG = "thwarg_launcher"

STEP_LABELS = {
    STEP_BASE_GAME: "1. Base game (official Turbine installer)",
    STEP_EOR_PATCH: "2. End of Retail client files",
    STEP_THWARG: "3. ThwargLauncher",
}


# --------------------------------------------------------------------------
# Small helpers (no GUI)
# --------------------------------------------------------------------------

def log(msg):
    """Append a timestamped line to the log file (best-effort)."""
    try:
        os.makedirs(TEMP_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg + "\n")
    except OSError:
        pass


def load_state():
    """Load the saved step-completion state, or an empty dict."""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    try:
        os.makedirs(TEMP_DIR, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except OSError:
        pass


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n / 1.0:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


class InstallError(Exception):
    """An error with a message safe/useful to show the user."""


class Cancelled(Exception):
    """User closed the app / cancelled mid-step."""


# --------------------------------------------------------------------------
# Download engine: resume + verify + retry
# --------------------------------------------------------------------------

def download_file(url, dest, min_size, progress_cb, cancel_event):
    """
    Download `url` to `dest` with:
      * resume of partial files via HTTP Range,
      * verification against Content-Length and `min_size`,
      * up to DOWNLOAD_RETRIES attempts.
    Calls progress_cb(downloaded_bytes, total_bytes_or_None) as it goes.
    Raises InstallError with a user-friendly message on failure.
    """
    part = dest + ".part"
    last_error = None

    for attempt in range(1, DOWNLOAD_RETRIES + 1):
        if cancel_event.is_set():
            raise Cancelled()
        try:
            existing = os.path.getsize(part) if os.path.exists(part) else 0

            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            if existing:
                req.add_header("Range", f"bytes={existing}-")

            with urllib.request.urlopen(req, timeout=60) as resp:
                # If the server ignored our Range request, start over.
                if existing and resp.status != 206:
                    existing = 0

                length = resp.headers.get("Content-Length")
                total = existing + int(length) if length else None

                mode = "ab" if existing else "wb"
                with open(part, mode) as f:
                    downloaded = existing
                    while True:
                        if cancel_event.is_set():
                            raise Cancelled()
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        progress_cb(downloaded, total)

            size = os.path.getsize(part)

            # --- Verification ---
            if total is not None and size < total:
                raise InstallError(
                    f"Download ended early ({human_size(size)} of {human_size(total)})."
                )
            if size < min_size:
                # Tiny file = error page or bad link, not the real installer.
                os.remove(part)
                raise InstallError(
                    f"Downloaded file is too small ({human_size(size)}) -- "
                    "the link may be broken or the server returned an error page."
                )

            os.replace(part, dest)
            log(f"Downloaded OK: {url} -> {dest} ({human_size(size)})")
            return

        except Cancelled:
            raise
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                InstallError) as e:
            last_error = e
            log(f"Download attempt {attempt}/{DOWNLOAD_RETRIES} failed for "
                f"{url}: {e}")
            # Small file / error page: don't resume garbage
            if isinstance(e, InstallError) and "too small" in str(e):
                pass  # .part already removed
            time.sleep(2 * attempt)  # brief backoff before retrying

    raise InstallError(
        f"Download failed after {DOWNLOAD_RETRIES} attempts.\n\n"
        f"URL: {url}\nLast error: {last_error}\n\n"
        "Check your internet connection and try again -- the installer will "
        "resume where it left off."
    )


# --------------------------------------------------------------------------
# GUI application
# --------------------------------------------------------------------------

class ACInstallerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Asheron's Call - One Click Installer")
        self.root.geometry("520x420")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.cancel_event = threading.Event()
        self.worker = None
        self.state = load_state()
        self.install_dir = tk.StringVar(value=DEFAULT_INSTALL_DIR)

        # ---- Title ----
        tk.Label(root, text="Asheron's Call Automated Installer",
                 font=("Helvetica", 14, "bold")).pack(pady=(12, 2))
        tk.Label(root, text="Safe to re-run at any time: finished steps are skipped.",
                 font=("Helvetica", 9), fg="#555").pack()

        # ---- Install folder picker ----
        dir_frame = tk.Frame(root)
        dir_frame.pack(pady=(10, 4), padx=16, fill="x")
        tk.Label(dir_frame, text="Install to:", font=("Helvetica", 9)).pack(side="left")
        self.dir_entry = tk.Entry(dir_frame, textvariable=self.install_dir,
                                  font=("Helvetica", 9))
        self.dir_entry.pack(side="left", fill="x", expand=True, padx=6)
        self.btn_browse = tk.Button(dir_frame, text="Browse...",
                                    command=self.browse_dir)
        self.btn_browse.pack(side="left")

        # ---- Step checklist ----
        steps_frame = tk.LabelFrame(root, text=" Install steps ", padx=10, pady=6)
        steps_frame.pack(pady=8, padx=16, fill="x")
        self.step_labels = {}
        for step_id in (STEP_BASE_GAME, STEP_EOR_PATCH, STEP_THWARG):
            lbl = tk.Label(steps_frame, text="", anchor="w",
                           font=("Helvetica", 10))
            lbl.pack(fill="x", pady=1)
            self.step_labels[step_id] = lbl

        # ---- Status + progress ----
        self.lbl_status = tk.Label(root, text="Ready to install.",
                                   font=("Helvetica", 10), wraplength=480)
        self.lbl_status.pack(pady=(6, 2))
        self.progress = ttk.Progressbar(root, orient="horizontal",
                                        length=440, mode="determinate")
        self.progress.pack(pady=4)

        # ---- Buttons ----
        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=8)
        self.btn_install = tk.Button(
            btn_frame, text="Start Install", font=("Helvetica", 12, "bold"),
            command=self.start_install_thread, bg="#4CAF50", fg="white",
            padx=20)
        self.btn_install.pack(side="left", padx=6)
        self.btn_reset = tk.Button(btn_frame, text="Start Over",
                                   command=self.reset_state)
        self.btn_reset.pack(side="left", padx=6)

        os.makedirs(TEMP_DIR, exist_ok=True)
        self.refresh_checklist()
        if any(self.state.get(s) == "done" for s in STEP_LABELS):
            self.btn_install.config(text="Resume Install")

    # ---------------- GUI plumbing (all GUI updates go through .after) ----

    def ui(self, fn, *args):
        """Schedule a GUI update from the worker thread."""
        self.root.after(0, fn, *args)

    def set_status(self, text, progress_val=None):
        def apply():
            self.lbl_status.config(text=text)
            if progress_val is not None:
                self.progress["value"] = progress_val
        self.ui(apply)

    def refresh_checklist(self):
        marks = {"done": ("[DONE]  ", "#2e7d32"),
                 "failed": ("[FAILED]  ", "#c62828"),
                 "running": ("[WORKING...]  ", "#1565c0")}
        for step_id, lbl in self.step_labels.items():
            status = self.state.get(step_id)
            prefix, color = marks.get(status, ("[  ]  ", "#333"))
            lbl.config(text=prefix + STEP_LABELS[step_id], fg=color)

    def mark_step(self, step_id, status):
        self.state[step_id] = status
        save_state(self.state)
        self.ui(self.refresh_checklist)

    def browse_dir(self):
        chosen = filedialog.askdirectory(title="Choose the Asheron's Call install folder")
        if chosen:
            self.install_dir.set(os.path.normpath(chosen))

    def reset_state(self):
        if messagebox.askyesno(
                "Start Over",
                "Forget all progress and mark every step as not done?\n\n"
                "(This does NOT uninstall anything -- it only makes the "
                "installer run every step again.)"):
            self.state = {}
            save_state(self.state)
            self.refresh_checklist()
            self.btn_install.config(text="Start Install")
            self.set_status("Ready to install.", 0)

    def on_close(self):
        self.cancel_event.set()
        self.root.destroy()

    # ---------------- Worker thread ----------------

    def start_install_thread(self):
        self.btn_install.config(state="disabled")
        self.btn_reset.config(state="disabled")
        self.btn_browse.config(state="disabled")
        self.cancel_event.clear()
        self.progress["value"] = 0
        self.worker = threading.Thread(target=self.run_installation, daemon=True)
        self.worker.start()

    def make_progress_cb(self, label):
        """Returns a throttled callback that shows real download progress."""
        last = [0.0]

        def cb(done, total):
            now = time.time()
            if now - last[0] < 0.2:  # throttle GUI updates
                return
            last[0] = now
            if total:
                pct = done * 100 / total
                self.set_status(f"{label}: {human_size(done)} of "
                                f"{human_size(total)} ({pct:.0f}%)", pct)
            else:
                self.set_status(f"{label}: {human_size(done)} downloaded...",
                                None)
        return cb

    def run_installation(self):
        steps = [
            (STEP_BASE_GAME, self.step_base_game),
            (STEP_EOR_PATCH, self.step_eor_patch),
            (STEP_THWARG, self.step_thwarg),
        ]
        try:
            for step_id, fn in steps:
                if self.state.get(step_id) == "done":
                    log(f"Skipping already-completed step: {step_id}")
                    continue
                self.mark_step(step_id, "running")
                fn()
                self.mark_step(step_id, "done")

            self.set_status("Installation complete!", 100)
            log("Installation complete.")
            self.ui(messagebox.showinfo, "Success",
                    "Asheron's Call has been successfully installed!\n\n"
                    "Open ThwargLauncher, pick a server, and play.")

        except Cancelled:
            log("Installation cancelled by user.")
        except InstallError as e:
            self.handle_failure(str(e))
        except Exception:
            log("Unexpected error:\n" + traceback.format_exc())
            self.handle_failure(
                "An unexpected error occurred.\n\nDetails were saved to:\n"
                + LOG_FILE)
        finally:
            def reenable():
                self.btn_install.config(state="normal", text="Resume Install")
                self.btn_reset.config(state="normal")
                self.btn_browse.config(state="normal")
            self.ui(reenable)

    def handle_failure(self, msg):
        # Mark whichever step was running as failed
        for step_id in STEP_LABELS:
            if self.state.get(step_id) == "running":
                self.mark_step(step_id, "failed")
        self.set_status("Installation paused -- click Resume to try again.", 0)
        self.ui(messagebox.showerror, "Installation Error",
                msg + "\n\nYour progress was saved. Click 'Resume Install' "
                      "to continue from this step.")

    # ---------------- Individual steps ----------------

    def step_base_game(self):
        install_dir = self.install_dir.get()

        # Already installed? (e.g. from a previous manual install)
        if os.path.exists(os.path.join(install_dir, "acclient.exe")):
            log("Base game already present, skipping installer.")
            return

        ac_exe = os.path.join(TEMP_DIR, "ac1install.exe")
        if not os.path.exists(ac_exe):
            self.set_status("Downloading official AC installer "
                            "(archive.org can be slow -- please be patient)...", 0)
            download_file(AC1_INSTALLER_URL, ac_exe, MIN_SIZE_AC1,
                          self.make_progress_cb("Downloading AC installer"),
                          self.cancel_event)

        self.set_status("Running the AC installer -- please follow its "
                        "prompts. (Install to the folder shown above.)", None)
        import subprocess
        result = subprocess.run([ac_exe])
        if result.returncode != 0:
            raise InstallError(
                "The Asheron's Call installer did not finish successfully.\n"
                "If you cancelled it, just click Resume to run it again.")

        if not os.path.exists(os.path.join(install_dir, "acclient.exe")):
            raise InstallError(
                "The installer finished, but the game was not found in:\n"
                f"{install_dir}\n\n"
                "If you installed it somewhere else, use 'Browse...' to point "
                "this tool at that folder, then click Resume.")

    def step_eor_patch(self):
        install_dir = self.install_dir.get()

        # Disk space check before a multi-GB extraction
        free = shutil.disk_usage(os.path.splitdrive(install_dir)[0] + "\\").free
        if free < REQUIRED_FREE_SPACE:
            raise InstallError(
                f"Not enough disk space. About {human_size(REQUIRED_FREE_SPACE)} "
                f"free is needed, but only {human_size(free)} is available on "
                "the install drive.")

        self.set_status("Waiting for the End of Retail zip file...", 50)
        webbrowser.open(MEGA_EOR_URL)

        # messagebox/filedialog must run on the GUI thread; use an event.
        picked = {"path": None}
        done = threading.Event()

        def ask():
            messagebox.showinfo(
                "One manual step needed",
                "Mega.nz blocks automated downloads, so your web browser was "
                "opened to the End of Retail files.\n\n"
                "1. Click 'Download' on the Mega page (it is a large file).\n"
                "2. WAIT for the download to fully finish.\n"
                "3. Click OK here, then select the .zip you downloaded\n"
                "    (usually in your Downloads folder).")
            picked["path"] = filedialog.askopenfilename(
                parent=self.root,
                title="Select the downloaded End of Retail .zip",
                initialdir=os.path.join(os.path.expanduser("~"), "Downloads"),
                filetypes=[("Zip Files", "*.zip")])
            done.set()

        self.ui(ask)
        done.wait()
        eor_zip_path = picked["path"]

        if not eor_zip_path:
            raise InstallError(
                "No zip file was selected.\n\nClick Resume when the Mega "
                "download has finished, and pick the file then.")

        # ---- Validate the zip BEFORE touching the game folder ----
        self.set_status("Checking the zip file (this can take a minute)...", 60)
        size = os.path.getsize(eor_zip_path)
        if size < MIN_SIZE_EOR_ZIP:
            raise InstallError(
                f"That zip is only {human_size(size)} -- the End of Retail "
                "client is much larger. The Mega download may still be in "
                "progress, or the wrong file was selected.")

        try:
            with zipfile.ZipFile(eor_zip_path, "r") as zf:
                names_lower = [n.lower() for n in zf.namelist()]
                if not any(any(n.endswith(exp) for n in names_lower)
                           for exp in EOR_EXPECTED_FILES):
                    raise InstallError(
                        "That zip doesn't look like the End of Retail client "
                        "files (no acclient.exe / client_portal.dat inside). "
                        "Please select the correct zip.")
                bad = zf.testzip()
                if bad is not None:
                    raise InstallError(
                        f"The zip file is corrupted (bad entry: {bad}).\n"
                        "Please delete it and re-download from Mega, then "
                        "click Resume.")

                # ---- Extract ----
                os.makedirs(install_dir, exist_ok=True)
                members = zf.infolist()
                total = len(members)
                for i, member in enumerate(members, 1):
                    if self.cancel_event.is_set():
                        raise Cancelled()
                    zf.extract(member, install_dir)
                    if i % 25 == 0 or i == total:
                        self.set_status(
                            f"Extracting client files... ({i}/{total})",
                            60 + 30 * i / total)
        except zipfile.BadZipFile:
            raise InstallError(
                "That file is not a valid zip (it may be an incomplete "
                "download). Re-download it from Mega and click Resume.")

        log(f"EoR files extracted to {install_dir}")

    def step_thwarg(self):
        thwarg_exe = os.path.join(TEMP_DIR, "ThwargLauncherInstaller.exe")
        if not os.path.exists(thwarg_exe):
            self.set_status("Downloading ThwargLauncher...", 90)
            download_file(THWARG_URL, thwarg_exe, MIN_SIZE_THWARG,
                          self.make_progress_cb("Downloading ThwargLauncher"),
                          self.cancel_event)

        self.set_status("Launching the ThwargLauncher installer...", 95)
        # ThwargLauncher uses a ClickOnce installer that never signals exit,
        # so detach instead of waiting (os.startfile == a double-click).
        os.startfile(thwarg_exe)


if __name__ == "__main__":
    log("=== Installer started ===")
    root = tk.Tk()
    app = ACInstallerGUI(root)
    root.mainloop()
