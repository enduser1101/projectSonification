import json
import time
import os
import argparse

REFRESH_INTERVAL = 1  # Sekunden

def clear():
    os.system("cls" if os.name == "nt" else "clear")

def show_json(filename):
    try:
        with open(filename, "r") as f:
            data = json.load(f)
        clear()
        print(f"📄 {filename} (updated every {REFRESH_INTERVAL}s)")
        print("-" * 50)
        for key, value in data.items():
            print(f"{key:30}: {value}")
        print("-" * 50)
    except FileNotFoundError:
        print(f"⏳ Waiting for {filename} ...")
    except json.JSONDecodeError:
        print(f"⚠️  Invalid JSON format in {filename}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Live viewer for a JSON file")
    parser.add_argument("filename", nargs="?", default="status.json", help="Path to JSON file (default: status.json)")
    args = parser.parse_args()

    try:
        while True:
            show_json(args.filename)
            time.sleep(REFRESH_INTERVAL)
    except KeyboardInterrupt:
        print("\n🛑 Viewer exited.")
