import numpy as np
import sounddevice as sd
import queue
import threading
import time

# Audio-Einstellungen
fs_audio = 44100  # Samplingrate für Audio
blocksize = 256   # Blockgröße für Audio-Stream
ims_data = queue.Queue()
        
def fake_ims_stream():
    t = 0
    while True:
        # simulation of signal
        frequency = np.random.uniform(0.1, 5.0)  # random frequency in Hz
        amplitude = np.random.uniform(0.1, 0.3)  # random amplitude
        val = amplitude * np.sin(2 * np.pi * frequency * t) + 0.1 * np.random.randn()  # sine noise
        print(f"Time: {t}, Value: {val}")
        ims_data.put(t, val)  # caching of data points
        t += 1.0
        time.sleep(1.0)  # sampling rate for this function as frequency in seconds


# Beispiel: Blocks von IMS-Daten generieren
#def fake_ims_stream():
    t = 0
    while True:
        frequency = np.random.uniform(0.1, 5.0)
        amplitude = np.random.uniform(0.1, 0.3)
        duration = 0.01  # 10 ms Block
        block_size = int(fs_audio * duration)
        t_vals = np.linspace(t, t + duration, block_size, endpoint=False)
        block = amplitude * np.sin(2 * np.pi * frequency * t_vals) + 0.05 * np.random.randn(block_size)
        ims_data.put(block.astype(np.float32))
        t += duration
        time.sleep(duration)

def direct_callback(outdata, frames, time_info, status):
    samples = np.zeros(frames, dtype=np.float32)
    for i in range(frames):
        try:
            samples[i] = ims_data.get_nowait()
        except queue.Empty:
            break
    outdata[:] = samples.reshape(-1, 1)

# Starte die IMS-Daten-Stream-Simulation in einem separaten Thread
threading.Thread(target=fake_ims_stream, daemon=True).start()


with sd.OutputStream(channels=1,
                     callback=direct_callback,
                     samplerate=fs_audio,
                     blocksize=blocksize,
                     device='BlackHole 64ch'):
    print("🎧 Echtzeit-Audio läuft. Drücke Ctrl+C zum Stoppen.")
    while True:
        time.sleep(0.01)