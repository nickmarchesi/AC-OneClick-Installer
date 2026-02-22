"""
Asheron's Call One-Click Installer
A user-friendly GUI to automate the installation of Asheron's Call, 
the End of Retail (EoR) client files, and ThwargLauncher.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import zipfile
import subprocess
import threading
import webbrowser

# --- Configurable URLs and Paths ---
# The Wayback Machine link to the official Turbine AC1 installer
AC1_INSTALLER_URL = "https://web.archive.org/web/20201121104423/http://content.turbine.com/sites/clientdl/ac1/ac1install.exe"

# Mega.nz link for the End of Retail (EoR) client files. 
# Note: Mega requires a browser-based download due to encryption/anti-bot measures.
MEGA_EOR_URL = "https://mega.nz/#!Q98n0BiR!p5IugPS8ZkQ7uX2A_LdN3Un2_wMX4gZBHowgs1Qomng"

# Official Thwargle domain for the launcher installer
THWARG_URL = "http://www.thwargle.com/thwarglauncher/updates/ThwargLauncherInstaller.exe"

# Default installation directory for Asheron's Call
DEFAULT_INSTALL_DIR = r"C:\Turbine\Asheron's Call"

# Temporary directory to store downloaded installers before execution
TEMP_DIR = os.path.join(os.environ["TEMP"], "AC_Installer")


class ACInstallerGUI:
    def __init__(self, root):
        """Initializes the graphical user interface."""
        self.root = root
        self.root.title("Asheron's Call - One Click Installer")
        self.root.geometry("450x200")
        self.root.resizable(False, False)

        # Title Label
        self.lbl_title = tk.Label(root, text="Asheron's Call Automated Installer", font=("Helvetica", 14, "bold"))
        self.lbl_title.pack(pady=10)

        # Status Label (Updates the user on current progress)
        self.lbl_status = tk.Label(root, text="Ready to install.", font=("Helvetica", 10))
        self.lbl_status.pack(pady=5)

        # Progress Bar (Visually tracks the installation steps)
        self.progress = ttk.Progressbar(root, orient="horizontal", length=350, mode="determinate")
        self.progress.pack(pady=10)

        # Install Button
        self.btn_install = tk.Button(root, text="Start 1-Click Install", font=("Helvetica", 12), command=self.start_install_thread, bg="#4CAF50", fg="white")
        self.btn_install.pack(pady=5)

        # Create the temporary download directory if it doesn't already exist
        if not os.path.exists(TEMP_DIR):
            os.makedirs(TEMP_DIR)

    def start_install_thread(self):
        """
        Starts the installation process in a separate background thread.
        This prevents the tkinter GUI from freezing while files are downloading/extracting.
        """
        self.btn_install.config(state="disabled")
        self.progress["value"] = 0
        threading.Thread(target=self.run_installation, daemon=True).start()

    def update_status(self, text, progress_val):
        """Helper method to update the GUI text and progress bar safely."""
        self.lbl_status.config(text=text)
        self.progress["value"] = progress_val
        self.root.update_idletasks()

    def download_file(self, url, dest):
        """
        Downloads a file using Windows' native curl command.
        By using curl, we bypass common Python SSL certificate errors and basic anti-bot blocks.
        """
        try:
            # -f: Fail silently on server errors (like 404)
            # -L: Follow redirects
            # -A: Disguise as a standard Chrome web browser
            # -o: Output file destination
            command = ["curl", "-f", "-L", "-A", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "-o", dest, url]
            
            # creationflags=0x08000000 hides the black console window that curl normally creates
            subprocess.run(command, check=True, creationflags=0x08000000)
        except subprocess.CalledProcessError as e:
            messagebox.showerror("Download Error", f"Failed to download {url}\nCurl Error Code: {e.returncode}")
            raise Exception("Download failed")

    def run_installation(self):
        """The core logic for downloading, extracting, and installing the game components."""
        try:
            # ==========================================
            # Step 1: Download & Install Base Game
            # ==========================================
            ac_exe = os.path.join(TEMP_DIR, "ac1install.exe")
            self.update_status("Downloading official AC Installer (May take a while)...", 10)
            self.download_file(AC1_INSTALLER_URL, ac_exe)
            
            self.update_status("Running AC Installer. PLEASE FOLLOW PROMPTS...", 30)
            # subprocess.run waits for the installer executable to completely finish before moving on
            subprocess.run(ac_exe, check=True)

            # ==========================================
            # Step 2: Mega.nz Manual Intercept
            # ==========================================
            self.update_status("Waiting for End of Retail zip file...", 50)
            
            # Open the default web browser to the Mega URL
            webbrowser.open(MEGA_EOR_URL)
            
            # Pause the script to instruct the user on what to do next
            messagebox.showinfo(
                "Manual Download Required", 
                "Because Mega.nz blocks automated downloads, your web browser has been opened to the End of Retail files.\n\n"
                "1. Click 'Download' on the Mega website.\n"
                "2. When the download finishes, click 'OK' on this box to select the .zip file you just downloaded."
            )
            
            # Open a file dialog so the user can point the script to the downloaded ZIP
            eor_zip_path = filedialog.askopenfilename(
                parent=self.root,
                title="Select the downloaded End of Retail .zip",
                filetypes=[("Zip Files", "*.zip")]
            )
            
            if not eor_zip_path:
                raise Exception("No End of Retail zip file was selected. Installation aborted.")

            # ==========================================
            # Step 3: Extract & Patch Client Files
            # ==========================================
            self.update_status("Extracting and patching client files...", 70)
            
            # Ensure the Turbine directory exists before extracting
            if not os.path.exists(DEFAULT_INSTALL_DIR):
                os.makedirs(DEFAULT_INSTALL_DIR)
                
            # Unzip the EoR files directly into the Asheron's Call folder, overwriting base files
            with zipfile.ZipFile(eor_zip_path, 'r') as zip_ref:
                zip_ref.extractall(DEFAULT_INSTALL_DIR)

            # ==========================================
            # Step 4: Download & Install ThwargLauncher
            # ==========================================
            thwarg_exe = os.path.join(TEMP_DIR, "ThwargLauncherInstaller.exe")
            self.update_status("Downloading ThwargLauncher...", 85)
            self.download_file(THWARG_URL, thwarg_exe)
            
            self.update_status("Running ThwargLauncher Installer (May take a while)...", 95)
            
            # FIX: We use os.startfile() instead of subprocess.run() here. 
            # ThwargLauncher uses a ClickOnce background installer. If we use subprocess.run, 
            # the script will hang indefinitely waiting for an exit signal that never comes.
            # os.startfile detaches the process, acting exactly like a manual mouse double-click.
            os.startfile(thwarg_exe)

            # ==========================================
            # Completion
            # ==========================================
            self.update_status("Installation Complete!", 100)
            messagebox.showinfo("Success", "Asheron's Call has been successfully installed!\n\nYou can now open ThwargLauncher to select a server and play.")

        except Exception as e:
            # If any error occurs during the thread, catch it, zero the progress bar, and show an error box
            self.update_status("Installation aborted.", 0)
            messagebox.showerror("Installation Error", str(e))
        finally:
            # Re-enable the install button in case the user needs to try again
            self.btn_install.config(state="normal")


if __name__ == "__main__":
    # Initialize the tkinter engine and launch the application
    root = tk.Tk()
    app = ACInstallerGUI(root)
    root.mainloop()