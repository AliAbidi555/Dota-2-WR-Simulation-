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


FRIENDS_FILE = "friends.json"
PLACEHOLDER_IDS = {123456789, 987654321, 111111111}
STEAM_64_OFFSET = 76561197960265728  # subtract from a 64-bit ID to get the 32-bit account_id


def _needs_setup() -> bool:
    """True if friends.json is missing, malformed, or contains only placeholders."""
    if not os.path.exists(FRIENDS_FILE):
        return True
    try:
        import json
        with open(FRIENDS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        friends = data.get("friends", [])
        real = [fr for fr in friends if fr.get("account_id") not in PLACEHOLDER_IDS]
        return len(real) == 0
    except Exception:
        return True


def _interactive_setup() -> None:
    """Prompt the user for friend IDs and write friends.json next to the exe."""
    import json

    print()
    print("=" * 70)
    print("  Dota 2 Tracker  -  First-time setup")
    print("=" * 70)
    print("""
  Add the players you want to track.  Each player needs a Steam account ID.

  How to find a Steam account ID:
    - Paste the player's Steam profile URL at https://steamid.io
    - Or copy the number from their OpenDota URL:
      opendota.com/players/<account_id>

  You can paste either the 32-bit ID (e.g. 185602862) or the 64-bit ID
  (starts with 7656...).  64-bit IDs will be converted automatically.

  Add at least one player.  Press Enter on a blank line to finish.
""")

    friends: list[dict] = []
    while True:
        prompt = f"  [{len(friends) + 1}] Steam ID (blank = done): "
        try:
            raw = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Setup cancelled.")
            sys.exit(0)

        if not raw:
            if not friends:
                print("  Please add at least one player.\n")
                continue
            break

        # Parse numeric ID, ignoring any "/" or non-digit suffixes from URLs
        digits = "".join(c for c in raw if c.isdigit())
        if not digits:
            print(f"  '{raw}' isn't a valid Steam ID.  Try again.\n")
            continue
        account_id = int(digits)

        # Auto-convert 64-bit -> 32-bit
        if account_id > STEAM_64_OFFSET:
            converted = account_id - STEAM_64_OFFSET
            print(f"      converted 64-bit -> 32-bit: {converted}")
            account_id = converted

        if account_id <= 0 or account_id in PLACEHOLDER_IDS:
            print(f"  {account_id} isn't a real account ID.  Try again.\n")
            continue
        if any(f["account_id"] == account_id for f in friends):
            print(f"  Already added {account_id}.  Try again.\n")
            continue

        try:
            label = input(f"      Nickname (blank = '{account_id}'): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Setup cancelled.")
            sys.exit(0)
        if not label:
            label = str(account_id)

        friends.append({"account_id": account_id, "label": label})
        print(f"      Added {label} ({account_id})\n")

    with open(FRIENDS_FILE, "w", encoding="utf-8") as f:
        json.dump({"friends": friends}, f, indent=2)

    print("=" * 70)
    print(f"  Saved {len(friends)} player(s) to {FRIENDS_FILE}")
    print(f"  You can edit this file later to add or remove players.")
    print("=" * 70)
    print()


def _stratz_setup() -> str | None:
    """Prompt for a Stratz API key, verify it, and persist to .env.  Returns key or None if skipped."""
    print()
    print("=" * 70)
    print("  Step 2 - Stratz API key (recommended, free)")
    print("=" * 70)
    print("""
  Stratz provides bracket-specific hero meta data (e.g. Legend/Ancient
  win rates per position) that powers the global meta signal in the
  draft predictor.  Without it, the predictor falls back to OpenDota's
  global stats, which mix all skill brackets together.

  How to get a free key:
    1. Go to:  https://stratz.com/api
    2. Sign in with Steam.
    3. Click "API Key" in your profile dropdown.
    4. Copy the key shown there.

  Press Enter on a blank line to skip (the predictor will still work,
  just with a less precise meta signal).
""")

    from app.data_pipeline import verify_stratz_key, write_env_file

    while True:
        try:
            raw = input("  Stratz API key (or blank to skip): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Setup cancelled.")
            sys.exit(0)

        if not raw:
            print("  Skipped.  You can add a key later by editing .env.\n")
            write_env_file(None)
            return None

        print("  Verifying...", end=" ", flush=True)
        ok, msg = verify_stratz_key(raw)
        if ok:
            print("OK")
            write_env_file(raw)
            print(f"  Saved to .env\n")
            return raw
        else:
            print(f"FAILED ({msg})")
            print("  Try again, or press Enter on a blank line to skip.\n")


def _run_initial_data_pull() -> None:
    """Run the full first-time data pipeline (matches, baselines, parquet, etc.)."""
    import asyncio
    import json as _json

    from app.data_pipeline import run_full_pipeline

    with open(FRIENDS_FILE, encoding="utf-8") as f:
        friends = _json.load(f)["friends"]

    try:
        asyncio.run(run_full_pipeline(friends))
    except KeyboardInterrupt:
        print("\n  Data pull interrupted.  Re-run the exe to resume; finished files are kept.")
        sys.exit(0)
    except Exception as e:
        print(f"\n  Data pull failed: {type(e).__name__}: {e}")
        print("  The server will still start.  You can re-run later via the CLI:")
        print("     python cli.py refresh-matches  &&  python cli.py refresh-data")
        input("\n  Press Enter to continue anyway...")


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
        first_run = _needs_setup()
        if first_run:
            _interactive_setup()
            _stratz_setup()

        # Even on subsequent runs, fetch any missing data files (e.g. user deleted data/).
        from app.data_pipeline import needs_data_pull
        if first_run or needs_data_pull():
            _run_initial_data_pull()

        print(f"Dota 2 Tracker  ->  {URL}")
        print("Press Ctrl+C to stop.\n")
        threading.Thread(target=_open_browser, daemon=True).start()
        uvicorn.run(app, host=HOST, port=PORT, log_level="warning")

except Exception:
    _write_error(
        f"Dota 2 Tracker failed to start.\n\n"
        f"Python {sys.version}\n\n"
        f"{traceback.format_exc()}"
    )
