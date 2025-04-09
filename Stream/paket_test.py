import numpy as np
import sounddevice as sd
import threading
import queue
import time
from obspy.clients.seedlink.easyseedlink import EasySeedLinkClient
from obspy.core import Trace, Stream

fs_audio = 44100
blocksize = 1024
audio_queue = queue.Queue(maxsize=fs_audio * 30)  # 30 Sekunden Audio-Puffer

# ========== SeedLink Client ==========
class MySeedLinkClient(EasySeedLinkClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def on_data(self, trace):
        data = trace.data.astype(np.float32)
        print(f"📡 {trace.id} | {len(data)} samples @ {trace.stats.sampling_rate} Hz")

        # Upsampling
        up_factor = int(fs_audio // trace.stats.sampling_rate)
        if up_factor <= 0:
            up_factor = 1
        upsampled = np.repeat(data, up_factor)

        for sample in upsampled:
            try:
                audio_queue.put_nowait(sample)
            except queue.Full:
                break  # Überlauf ignorieren – nur neueste Daten zählen

# ========== Audio Callback ==========
def audio_callback(outdata, frames, time_info, status):
    if status.output_underflow:
        print("⚠️  Audio underrun!")
    try:
        samples = np.zeros(frames, dtype=np.float32)
        for i in range(frames):
            samples[i] = audio_queue.get_nowait()
        outdata[:] = samples.reshape(-1, 1)
    except queue.Empty:
        print("⚠️  Queue leer – Nullen ausgegeben")
        outdata[:] = np.zeros((frames, 1), dtype=np.float32)

# ========== Start SeedLink Client ==========
def start_seedlink():
    client = MySeedLinkClient()
    client.select_stream("IU", "ANMO", "00", "BHZ")
    client.begin("rtserve.iris.washington.edu", 18000)

threading.Thread(target=start_seedlink, daemon=True).start()

# ========== Warte auf initialen Puffer ==========
def wait_for_data():
    while audio_queue.qsize() < fs_audio * 5:
        print(f"⏳ Warte auf Daten... {audio_queue.qsize()} Samples im Puffer")
        time.sleep(1)
    print("✅ Genug Daten im Puffer – Starte Audio-Stream")

wait_for_data()

# ========== Start Audio-Stream ==========
with sd.OutputStream(callback=audio_callback, channels=1, samplerate=fs_audio,
                     blocksize=blocksize, device="BlackHole 64ch"):
    print("🎧 Echtzeit-Audio läuft. Drücke Ctrl+C zum Stoppen.")
    while True:
        time.sleep(1)
