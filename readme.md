<img width="1280" height="640" alt="choronopuls-social-banner" src="https://github.com/user-attachments/assets/98cbb29c-8d97-4caf-a178-4d94c794cce7" />

# ChronoPulse for Windows

A lightweight, offline-first Windows desktop screen-time tracker and multi-profile telemetry dashboard built in Python.

## Key Features
- **Profile Selector on Startup:** Prompts users to select their profile on boot before tracking begins.
- **Zero-Server Architecture:** Uses Python's built-in HTTP server and SQLite—no XAMPP, Apache, Docker, or external database software required.
- **Privacy-First Date-Wise Logging:** Stores only `(log_date, user_name, app_name, seconds)` in a local SQLite file (`screentime.db`). Never records PC boot/shutdown timestamps or window titles.
- **Smart Idle Detection:** Automatically pauses tracking after 3 minutes (180 seconds) of mouse/keyboard inactivity using the native Windows `GetLastInputInfo` API.
- **Background System Tray Mode:** Closing or minimizing the window hides it silently to the Windows System Tray while continuing to track active apps.
- **Modern Bento Web Dashboard:** Live local dashboard with Light/Dark theme toggle, daily profile split ring, app-wise usage bars, and a 7-day rolling trend chart.
- **Minimal Disk Footprint:** Updates one counter row per `(Date + User + App)` rather than inserting rows every second—taking less than **1 MB per year** of daily use.

---

## Project Structure

```text
ChronoPulse/
├── screen_tracker.py   # Desktop tracker, tray icon, SQLite logger & local web server
├── requirements.txt    # Required Windows Python packages
├── README.md           # Setup & usage guide
└── .gitignore          # Excludes local screentime.db from Git
```

---

## 1. Prerequisites (Windows 10 / 11)

1. **Python 3.8 or higher:**
   - Download the official Windows installer from [python.org](https://www.python.org/downloads/).
   - On the first screen of the installer, check **"Add Python to PATH"** and keep **"tcl/tk and IDLE"** checked (provides `tkinter` for the desktop popup).
2. **Database (`sqlite3`):**
   - Built directly into Python—no separate SQLite or database server installation is required.

---

## 2. Installation & First Run

1. **Clone or download this repository:**
   ```bat
   git clone https://github.com/alakhsatsangi/ChronoPulse.git
   cd ChronoPulse
   ```

2. **Install the required Windows Python packages:**
   ```bat
   pip install -r requirements.txt
   ```
   *(Installs `pywin32`, `psutil`, `pystray`, and `pillow`.)*

3. **Run a Quick Test:**
   - **With console output (for verification):**
     ```bat
     python screen_tracker.py
     ```
   - **Silently in the background (no console window):**
     ```bat
     start "" pythonw screen_tracker.py
     ```
   Select a profile in the popup, switch between a couple of apps for 10 seconds, and click **Dashboard** to confirm usage appears. A `screentime.db` file is created automatically in the same folder.

---

## 3. Adding or Customizing User Profiles

ChronoPulse comes configured with 2 profiles (`Work` and `Personal`), and you can rename them or add a 3rd, 4th, or 5th user anytime.

### Edit or Add a User in `USERS`
Open `screen_tracker.py` and locate the `USERS` list near the top of the file (around line 29). Rename existing profiles or append a new dictionary block for each additional user:

```python
USERS = [
    {
        "name": "Work",
        "initial": "1",
        "tag": "Primary Profile",
        "accent": "#2563EB",
        "badge_bg": "#1E3A8A",
        "badge_fg": "#93C5FD",
    },
    {
        "name": "Personal",
        "initial": "2",
        "tag": "Secondary Profile",
        "accent": "#EAB308",
        "badge_bg": "#422006",
        "badge_fg": "#FFEE00",
    },
    {
        "name": "Kids",
        "initial": "3",
        "tag": "Guest Profile",
        "accent": "#10B981",
        "badge_bg": "#064E3B",
        "badge_fg": "#6EE7B7",
    },
]
```

**Restart ChronoPulse** (right-click the system tray icon → **Exit Completely**, then relaunch) to load the new user profile.

---

## 4. Set Up Custom Local URL (`http://chronopulse.local`)

ChronoPulse binds its web dashboard to dedicated loopback IP **`127.0.0.2`** on port **`80`** (falling back to port `8765` if port `80` requires elevated permissions). Using `127.0.0.2` leaves standard `localhost` (`127.0.0.1`) completely untouched for your other local web development projects.

1. **Open Notepad as Administrator:**
   - Press the **Windows Key**, type `Notepad`, right-click **Notepad**, and select **Run as administrator**.
2. **Open the Windows `hosts` file:**
   - In Notepad, press `Ctrl + O` and navigate to:
     ```text
     C:\Windows\System32\drivers\etc
     ```
   - Change the file filter dropdown in the bottom-right corner from **Text Documents (`*.txt`)** to **All Files (`*.*`)**.
   - Select **`hosts`** and click **Open**.
3. **Add the ChronoPulse mapping:**
   - Keep existing `#` comment lines intact, scroll to the bottom, press **Enter**, and paste:
     ```text
     127.0.0.2   chronopulse.local   chronopulse
     ```
4. **Save and test:**
   - Press `Ctrl + S` to save and close Notepad.
   - With ChronoPulse running, open Chrome or Edge and navigate to `http://chronopulse.local` *(include `http://` the first time so your browser treats it as a local URL rather than a web search)*.

---

## 5. Auto-Start Silently When Windows Boots (`shell:startup`)

> **Note:** Do **not** place `screen_tracker.py` directly inside the Startup folder, or Windows may open it in your code editor (such as VS Code) instead of executing it. Use a `.bat` launcher instead.

1. **Open the Windows Startup folder:**
   - Press `Win + R`, type `shell:startup`, and press **Enter**.
2. **Create the launcher batch file:**
   - Right-click inside the Startup folder → **New → Text Document**, and rename it to **`StartChronoPulse.bat`** *(ensure the extension is `.bat`, not `.bat.txt`)*.
3. **Add the silent launch command:**
   - Right-click `StartChronoPulse.bat` → **Edit**, and paste the following (replacing the path with your actual `ChronoPulse` folder path):
     ```bat
     @echo off
     start "" pythonw "C:\full\path\to\ChronoPulse\screen_tracker.py"
     ```
   - *Using Anaconda or a virtual environment?* Point directly to that environment's `pythonw.exe`:
     ```bat
     @echo off
     start "" "C:\Users\YourName\anaconda3\pythonw.exe" "C:\full\path\to\ChronoPulse\screen_tracker.py"
     ```
4. **Save and verify:**
   - Press `Ctrl + S` and close Notepad.
   - Double-click **`StartChronoPulse.bat`** to confirm the profile selector pops up with no terminal or editor window. ChronoPulse will now launch automatically on every Windows boot.

---

## 6. Daily Controls & Data Backup

- **Hide to System Tray:** Click **`✕`** on the selector or **`—`** on the floating tracker card to hide the window to the **ChronoPulse** icon in your bottom-right System Tray while tracking continues in the background.
- **Reopen or Switch Profile:** Click or right-click the **ChronoPulse** System Tray icon anytime to reopen the tracker, launch the dashboard, or switch users.
- **Exit Completely:** Right-click the tray icon and select **Exit Completely** (or click **Exit** on the floating widget) to stop the background tracker and local server cleanly.
- **Back Up Your History:** All usage data is stored in `screentime.db` alongside `screen_tracker.py`. Copy `screentime.db` anytime to back up or migrate your history.
