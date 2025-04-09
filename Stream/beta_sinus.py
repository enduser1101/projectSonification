import numpy as np
import sounddevice as sd
import threading
import queue
import time

# Audio-Parameter
fs = 44100
f = 440
blocksize = 1024
amplitude = 0.3

# Queue größer machen → mehr Puffer
audio_queue = queue.Queue(maxsize=100)

# 🌀 Signal-Generator
def sine_wave_producer():
    phase = 0.0
    phase_inc = 2 * np.pi * f / fs
    while True:
        t = (np.arange(blocksize) + phase) * phase_inc
        block = amplitude * np.sin(t).astype(np.float32)
        phase += blocksize
        phase %= fs
        try:
            audio_queue.put(block, timeout=0.1)
        except queue.Full:
            pass  # Wenn voll: ignoriere (nicht blockieren!)
        # Kein sleep → so schnell wie möglich füllen

# 🔊 Callback – robust gegen leere Queue
def audio_callback(outdata, frames, time_info, status):
    try:
        block = audio_queue.get(timeout=0.01)
    except queue.Empty:
        block = np.zeros(frames, dtype=np.float32)
        print("⚠️  Buffer underrun!")
    if len(block) < frames:
        block = np.pad(block, (0, frames - len(block)))
    outdata[:] = block.reshape(-1, 1)

# 🎛️ Start
def start_stream():
    # Producer-Thread starten
    threading.Thread(target=sine_wave_producer, daemon=True).start()

    with sd.OutputStream(callback=audio_callback,
                         samplerate=fs,
                         blocksize=blocksize,
                         channels=1,
                         device='BlackHole 64ch'):
        print("🔊 Live-Sinus über Queue läuft. Drücke Ctrl+C zum Stoppen.")
        while True:
            time.sleep(0.1)

start_stream()
