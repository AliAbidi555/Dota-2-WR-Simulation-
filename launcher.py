"""
Entry point for the packaged exe.

Opens a browser tab automatically and starts the API server.
Users never need to touch a terminal.
"""

import os
import sys
import traceback

# When frozen by PyInstaller, make sure the working directory is the folder
# that contains the exe so relative paths (friends.json, data/) resolve correctly.
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

LOG_FILE = "dota-tracker-error.log"


def _write_error(msg: str) -> None:
    """Write crash details to a log file next to the exe and keep window open."""
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        f.write(msg)
    print(msg)
    print(f"\nError details saved to {LOG_FILE}")
    input("Press Enter to close...")


FRIENDS_FILE  = "friends.json"
TEMPLATE_FILE = "fill_this_first_friends.json"


def _check_friends() -> bool:
    """Return True if friends.json exists and has at least one real entry."""
    if not os.path.exists(FRIENDS_FILE):
        print("=" * 60)
        print("  SETUP REQUIRED — friends.json not found")
        print("=" * 60)
        print(f"""
  1. Open '{TEMPLATE_FILE}' in any text editor.
  2. Replace the placeholder account IDs with your group's
     real Steam account IDs.
     (Find them at https://steamid.io or from your OpenDota
      profile URL: opendota.com/players/<account_id>)
  3. Rename the file to 'friends.json'.
  4. Restart dota-tracker.exe.
""")
        input("Press Enter to close...")
        return False

    try:
        import json
        with open(FRIENDS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        friends = data.get("friends", [])
        real = [fr for fr in friends if fr.get("account_id") not in (None, 123456789, 987654321, 111111111)]
        if not real:
            print("=" * 60)
            print("  SETUP REQUIRED — friends.json has no real entries")
            print("=" * 60)
            print(f"""
  friends.json still contains only the placeholder IDs.

  1. Open 'friends.json' in a text editor.
  2. Replace the placeholder account IDs with your group's
     real Steam account IDs.
  3. Save and restart dota-tracker.exe.
""")
            input("Press Enter to close...")
            return False
    except Exception as e:
        print(f"Could not read friends.json: {e}")
        input("Press Enter to close...")
        return False

    return True


try:
    import threading
    import time
    import webbrowser
    import uvicorn
    from app.main import app  # direct import so PyInstaller bundles app correctly

    HOST = "127.0.0.1"
    PORT = 8000
    URL  = f"http://{HOST}:{PORT}"

    def _open_browser():
        time.sleep(1.5)
        webbrowser.open(URL)

    if __name__ == "__main__":
        if not _check_friends():
            sys.exit(0)
        print(f"Dota 2 Tracker  →  {URL}")
        print("Press Ctrl+C to stop.\n")
        threading.Thread(target=_open_browser, daemon=True).start()
        uvicorn.run(app, host=HOST, port=PORT, log_level="warning")

except Exception:
    _write_error(
        f"Dota 2 Tracker failed to start.\n\n"
        f"Python {sys.version}\n\n"
        f"{traceback.format_exc()}"
    )
