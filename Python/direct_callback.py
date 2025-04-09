import numpy as np
import sounddevice as sd
import queue
import threading
import time

# 🎛️ Audio-Parameter
fs_audio = 44100        # Audio-Samplingrate
blocksize = 1024        # Audio-Blockgröße
upsample_factor = fs_audio  # 1 IMS-Wert pro Sekunde → 44100 Audio-Samples
ims_queue = queue.Queue()
audio_queue = queue.Queue()

# 1️⃣ Fake-IMS-Stream
def fake_ims_stream():
    while True:
        frequency = np.random.uniform(0.1, 5.0)
        amplitude = np.random.uniform(0.1, 0.3)
        val = amplitude * np.sin(2 * np.pi * frequency * time.time()) + 0.05 * np.random.randn()
        print(f"[IMS] {val:.4f}")
        ims_queue.put(val)
        time.sleep(1.0)  # 1 Hz "Sensor"

# 2️⃣ Upsampling-Funktion (Hold)
def upsample_loop():
    while True:
        val = ims_queue.get()  # Warte auf IMS-Wert
        upsampled = np.full(upsample_factor, val, dtype=np.float32)
        for i in range(0, upsampled.size, blocksize):
            block = upsampled[i:i+blocksize]
            audio_queue.put(block)

# 3️⃣ Audio-Callback für Sounddevice
def audio_callback(outdata, frames, time_info, status):
    try:
        block = audio_queue.get_nowait()
    except queue.Empty:
        block = np.zeros(frames, dtype=np.float32)
    if block.shape[0] < frames:
        padded = np.zeros(frames, dtype=np.float32)
        padded[:block.shape[0]] = block
        block = padded
    outdata[:] = block.reshape(-1, 1)

# Threads starten
threading.Thread(target=fake_ims_stream, daemon=True).start()
threading.Thread(target=upsample_loop, daemon=True).start()

# Audio-Ausgabe starten (z. B. an BlackHole)
with sd.OutputStream(channels=1,
                     callback=audio_callback,
                     samplerate=fs_audio,
                     blocksize=blocksize,
                     device='BlackHole 64ch'):
    print("🎧 Echtzeit-Audio läuft. Drücke Ctrl+C zum Stoppen.")
    while True:
        time.sleep(0.1)
