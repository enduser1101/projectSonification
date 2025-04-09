import numpy as np
import queue
import threading
import sounddevice as sd
from obspy.clients.seedlink.easyseedlink import EasySeedLinkClient

# 🔧 Konfiguration
SEEDLINK_SERVER = "rtserve.iris.washington.edu:18000"
STATION = "A2"
NETWORK = "AGVN"
CHANNEL = "HHE"
SAMPLERATE_IN = 100
SAMPLERATE_OUT = 44100
AUDIO_BLOCKSIZE = 1024
AUDIO_BUFFERSIZE_SECONDS = 60  # wie viele Sekunden gepuffert werden

# 📦 Ringbuffer für die Audiodaten
audio_queue = queue.Queue(maxsize=int(SAMPLERATE_OUT * AUDIO_BUFFERSIZE_SECONDS))

# 🔊 Audio-Callback
def audio_callback(outdata, frames, time, status):
    if status:
        print(f"⚠️ {status}")

    try:
        samples = np.array([audio_queue.get_nowait() for _ in range(frames)], dtype=np.float32)
    except queue.Empty:
        print("⚠️ Audio queue underrun!")
        samples = np.zeros(frames, dtype=np.float32)

    outdata[:] = samples.reshape(-1, 1)
    
import math

def dummy_filler():
    t = 0
    while True:
        if audio_queue.qsize() < SAMPLERATE_OUT * AUDIO_BUFFERSIZE_SECONDS:
            sample = math.sin(2 * math.pi * 440 * t / SAMPLERATE_OUT)
            audio_queue.put(sample)
            t += 1
        else:
            sd.sleep(100)


# 🧪 Upsampling mit "Sample and Hold"
def upsample(data, fs_in, fs_out):
    repeat_factor = int(fs_out / fs_in)
    return np.repeat(data, repeat_factor).astype(np.float32) / np.max(np.abs(data) + 1e-9)

# 🌐 SeedLink-Client
class StreamClient(EasySeedLinkClient):
    def on_data(self, trace):
        print(f"📡 {trace.id} | {len(trace.data)} samples @ {trace.stats.sampling_rate} Hz")

        if trace.stats.sampling_rate != SAMPLERATE_IN:
            print("⚠️ Unerwartete Eingabesamplerate!")
            return

        upsampled = upsample(trace.data, SAMPLERATE_IN, SAMPLERATE_OUT)

        # 🌀 Daten in Queue schieben (wenn Platz da ist)
        for sample in upsampled:
            try:
                audio_queue.put_nowait(sample)
            except queue.Full:
                break  # Verwerfe neue Daten, wenn der Puffer voll ist
                
def on_data(self, trace):
    print("✅ Datenpaket empfangen!")


# 🚀 Starte Audio-Thread
def start_audio_stream():
    stream = sd.OutputStream(
        samplerate=SAMPLERATE_OUT,
        channels=1,
        callback=audio_callback,
        blocksize=AUDIO_BLOCKSIZE,
        dtype='float32',
        latency='low'
    )
    stream.start()
    return stream

# 🌍 Starte SeedLink-Thread
def start_seedlink():
    client = StreamClient(SEEDLINK_SERVER)
    client.select_stream(NETWORK, STATION, CHANNEL)
    print("🌐 Verbunden mit SeedLink Server, warte auf Daten...")
    client.run()

# 🧩 Main
if __name__ == "__main__":
    try:
        threading.Thread(target=start_seedlink, daemon=True).start()
        stream = start_audio_stream()
        print("🎧 Audio läuft...")
        
        
        # Dann im main():
        threading.Thread(target=dummy_filler, daemon=True).start()

        while True:
            sd.sleep(1000)

    except KeyboardInterrupt:
        print("⛔️ Manuell gestoppt.")
