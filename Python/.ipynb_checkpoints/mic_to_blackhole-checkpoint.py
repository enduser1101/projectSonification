import sounddevice as sd
import numpy as np
import time

def callback(indata, outdata, frames, time_info, status):
    if status:
        print("⚠️", status)
    volume = np.linalg.norm(indata)
    outdata[:] = indata

# Setze hier deine Device-Indexe ein:
input_index = 2      # z. B. dein Mikrofon
output_index = 1     # z. B. BlackHole 64ch

# Starte den Duplex-Stream
with sd.Stream(device=(input_index, output_index),
               channels=1,
               samplerate=44100,
               callback=callback):
    print("🎙️ Mic ➝ BlackHole läuft – drücke Ctrl+C zum Stoppen")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("🛑 Stream gestoppt")