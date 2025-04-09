import numpy as np
import sounddevice as sd
import queue
import threading
import time

# Audio-Einstellungen
fs_audio = 44100  # Samplingrate für Audio
blocksize = 256   # Blockgröße für Audio-Stream
ims_data = queue.Queue()

# Beispiel für den Fake-IMS-Stream (wird ersetzt durch echte IMS-Daten)
def fake_ims_stream():
    t = 0
    while True:
        val = np.sin(2 * np.pi * 1 * t) + 0.1 * np.random.randn()
        ims_data.put((t, val))  # Speichert den Zeitpunkt und den Messwert
        t += 1.0
        time.sleep(1.0)

# Die angepasste Callback-Funktion für den Soundstream
def audio_callback(outdata, frames, time_info, status, callback_context):
    # Sicherstellen, dass `callback_context` optional ist
    samples = np.zeros(frames, dtype=np.float32)  # Erstelle ein Array der richtigen Größe
    i = 0
    while i < frames:
        try:
            block = ims_data.get_nowait()  # Hole IMS-Daten
            n = min(len(block), frames - i)
            samples[i:i + n] = block[:n]  # Füge die Daten in den Array ein
            if n < len(block):
                ims_data.put(block[n:])
            i += n
        except queue.Empty:
            break
    outdata[:] = samples.reshape(-1, 1)  # Ausgabepuffer füllen

# Starte die IMS-Daten-Stream-Simulation in einem separaten Thread
threading.Thread(target=fake_ims_stream, daemon=True).start()

# Starte den Audio-Stream, indem wir `callback_context` als `None` explizit angeben
with sd.OutputStream(channels=1, callback=audio_callback, samplerate=fs_audio, blocksize=blocksize):
    print("🎧 Echtzeit-Audio läuft. Drücke Ctrl+C zum Stoppen.")
    while True:
        time.sleep(1)
