import json
import threading
import time
import logging
from datetime import datetime, timedelta
from obspy.clients.seedlink.easyseedlink import EasySeedLinkClient
from obspy import UTCDateTime
from rich.console import Console
from rich.table import Table
from rich.live import Live

STATIONS_FILE = "stations.json"
REPORT_FILE = "station_monitor_report.json"

# In-memory structure for station info
station_stats = {}

# Lock for thread-safe writing
lock = threading.Lock()
console = Console()

# Track script start time for uptime display
script_start_time = datetime.utcnow()

# Log handler to catch "bad packet" messages
class BadPacketCounter(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        if "bad packet" in msg:
            with lock:
                for sid, s in station_stats.items():
                    if s["code"] in msg or s["server"] in msg:
                        s["bad_packets"] += 1
                        break

# Attach handler to obspy logger
logger = logging.getLogger("obspy")
logger.setLevel(logging.ERROR)
logger.addHandler(BadPacketCounter())

class MonitorClient(EasySeedLinkClient):
    def __init__(self, station_id, conf):
        super().__init__(conf["server"])
        self.station_id = station_id
        self.conf = conf
        self.key = f"{conf['network']}.{conf['station']}.{conf['channel']}"
        self.select_stream(conf["network"], conf["station"], conf["channel"])

        # Initialize station metrics
        station_stats[station_id] = {
            "name": conf.get("name", ""),
            "code": self.key,
            "server": conf["server"],
            "connected": False,
            "sample_rate": None,
            "min_samples": None,
            "max_samples": None,
            "blocks_last_10min": [],
            "data_minutes_last_60min": [],
            "timeouts": 0,
            "last_data_time": None,
            "bad_packets": 0
        }

    def on_data(self, trace):
        now = datetime.utcnow()
        data_len = len(trace.data)
        fs = trace.stats.sampling_rate
        duration_min = data_len / fs / 60

        with lock:
            s = station_stats[self.station_id]
            s["connected"] = True
            s["sample_rate"] = fs
            s["min_samples"] = min(s["min_samples"] or data_len, data_len)
            s["max_samples"] = max(s["max_samples"] or 0, data_len)
            s["last_data_time"] = now
            s["blocks_last_10min"].append((now, 1))
            s["data_minutes_last_60min"].append((now, duration_min))


def cleanup_stats():
    now = datetime.utcnow()
    for s in station_stats.values():
        s["blocks_last_10min"] = [(t, c) for t, c in s["blocks_last_10min"] if t > now - timedelta(minutes=10)]
        s["data_minutes_last_60min"] = [(t, m) for t, m in s["data_minutes_last_60min"] if t > now - timedelta(minutes=60)]

        if s["last_data_time"] is not None:
            if now - s["last_data_time"] > timedelta(seconds=60):
                if s["connected"]:
                    s["timeouts"] += 1
                s["connected"] = False


def format_uptime():
    delta = datetime.utcnow() - script_start_time
    days = delta.days
    hours, rem = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{days:03}:{hours:02}:{minutes:02}:{seconds:02}"


def generate_table():
    uptime_str = format_uptime()
    table = Table(title=f"📡 Station Monitoring — Uptime {uptime_str}", show_lines=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name")
    table.add_column("Code")
    table.add_column("Server")
    table.add_column("Connected", style="green")
    table.add_column("SR (Hz)", justify="right")
    table.add_column("Min/Max Samples", justify="right")
    table.add_column("Blocks 10min", justify="right")
    table.add_column("Data 60min (min)", justify="right")
    table.add_column("Timeouts", justify="right", style="red")
    table.add_column("Bad Packets", justify="right", style="magenta")

    with lock:
        cleanup_stats()
        for sid, s in station_stats.items():
            table.add_row(
                sid,
                s['name'],
                s['code'],
                s['server'],
                "✅" if s['connected'] else "❌",
                str(s['sample_rate'] or "-"),
                f"{s['min_samples'] or '-'} / {s['max_samples'] or '-'}",
                str(len(s['blocks_last_10min'])),
                f"{round(sum(m for _, m in s['data_minutes_last_60min']), 2)}",
                str(s['timeouts']),
                str(s['bad_packets'])
            )

    return table


def report_loop():
    with Live(generate_table(), refresh_per_second=1, console=console) as live:
        while True:
            time.sleep(5)
            with lock:
                with open(REPORT_FILE, "w", encoding="utf-8") as f:
                    json.dump(station_stats, f, indent=2, default=str)
            live.update(generate_table())


def start_monitoring():
    with open(STATIONS_FILE, "r", encoding="utf-8") as f:
        stations = json.load(f)

    for sid, conf in stations.items():
        client = MonitorClient(sid, conf)
        thread = threading.Thread(target=client.run, daemon=True)
        thread.start()

    threading.Thread(target=report_loop, daemon=True).start()

    while True:
        time.sleep(1)


if __name__ == "__main__":
    console.print("🚀 Starting station monitoring... (Press Ctrl+C to exit)", style="bold yellow")
    start_monitoring()
