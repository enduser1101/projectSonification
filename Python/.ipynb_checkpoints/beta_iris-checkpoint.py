import numpy as np
import sounddevice as sd
import threading
import queue
import time
from obspy.clients.seedlink.easyseedlink import EasySeedLinkClient




# ----------------------------------------
# 🧠 Queues für Kommunikation
signal_queue = queue.Queue()
audio_queue = queue.Queue()

# ----------------------------------------
# 📡 SeedLink-Client für Live-Daten
class MySeedLinkClient(EasySeedLinkClient):
    def __init__(self, network, station, channel):
        super().__init__("rtserve.iris.washington.edu:18000")
        self.select_stream(network, station, channel)

    def on_data(self, trace):
        fs_signal = trace.stats.sampling_rate
        data = trace.data.astype(np.float32)

        # Normalisierung (optional)
        if np.max(np.abs(data)) > 0:
            data /= np.max(np.abs(data))

        print(f"📡 {trace.id} | {len(data)} samples @ {fs_signal} Hz")
        signal_queue.put((data, fs_signal))

# ----------------------------------------
# 🔁 Worker: Upsampling + in Audio-Queue
def upsampler_worker(target_rate=44100):
    while True:
        try:
            data, fs = signal_queue.get(timeout=1)
        except queue.Empty:
            continue

        factor = int(target_rate / fs)
        if factor <= 0:
            continue

        # Einfaches Upsampling durch Wiederholung
        upsampled = np.repeat(data, factor).astype(np.float32)
        audio_queue.put(upsampled)

# ----------------------------------------
# 🔊 Audio-Callback (streamed aus Queue)
def audio_callback(outdata, frames, time_info, status):
    if status:
        print(f"⚠️  Audio-Status: {status}")

    try:
        block = audio_queue.get_nowait()
    except queue.Empty:
        print("⚠️  Audio queue underrun!")
        outdata.fill(0)
        return

    if len(block) < frames:
        out = np.pad(block, (0, frames - len(block)))
    else:
        out = block[:frames]

    outdata[:] = out.reshape(-1, 1)

# ----------------------------------------
# 🧵 Threads starten
def start_all():
    # Starte SeedLink-Client
    threading.Thread(target=lambda: MySeedLinkClient("A2", "AGVN", "HHE").run(), daemon=True).start()

    # Starte Upsampling
    threading.Thread(target=upsampler_worker, daemon=True).start()

    # Starte Audioausgabe
    with sd.OutputStream(
        samplerate=44100,
        channels=1,
        callback=audio_callback,
        blocksize=256,
        dtype="float32",
        device="BlackHole 64ch"  # <- ggf. anpassen
    ):
        print("🎧 Echtzeit-Audio läuft. Drücke Ctrl+C zum Stoppen.")
        while True:
            time.sleep(0.1)

# ----------------------------------------
# 🚀 Los geht's!
if __name__ == "__main__":
    start_all()
