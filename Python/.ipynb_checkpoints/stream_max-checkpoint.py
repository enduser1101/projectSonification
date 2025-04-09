import numpy as np
import sounddevice as sd
import time
import queue
import threading


fs_audio = 44100  # Samplingrate für Audio
blocksize = 256   # Blockgröße für Audio-Stream

# Callback-Funktion, um Audio zu streamen
def audio_callback(outdata, frames, time_info, status, callback_context=None):
    # Beispiel: Sinuswelle als Audiodaten (kann durch IMS-Daten ersetzt werden)
    t = np.linspace(0, frames / fs_audio, frames, endpoint=False)
    samples = np.sin(2 * np.pi * 540 * t)  # 440 Hz Sinuswelle als Beispiel

    outdata[:] = samples.reshape(-1, 1)  # Ausgabepuffer füllen

# Starten des Audio-Streams mit BlackHole als Output-Device
with sd.OutputStream(channels=1, callback=audio_callback, samplerate=fs_audio, blocksize=blocksize, device='BlackHole 64ch'):
    print("🎧 Echtzeit-Audio läuft. Drücke Ctrl+C zum Stoppen.")
    while True:
        time.sleep(1)
