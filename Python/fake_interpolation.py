import numpy as np
import sounddevice as sd
from scipy.interpolate import interp1d
import queue
import threading
import time

# Audio rate
fs_audio = 44100
blocksize = 1024

# Queue für IMS-Datenpunkte
ims_data = queue.Queue()

# Hier wird das interpolierte Audio gespeichert
audio_buffer = queue.Queue()

def fake_ims_stream():
    """Simuliert eingehende IMS-Datenpunkte (z. B. 10 Hz)"""
    ims_sampingrate = 1 #sampling rate of fake data stream
    t = 0
    while True:
        val = np.sin(2 * np.pi * 2.3865 * t) + 0.1 * np.random.randn() #noise modulated sine
        ims_data.put((t, val))
        print(f"Time: {t}, Value: {val}")
        t += ims_sampingrate
        time.sleep(ims_sampingrate) #time.sleep is the sampling rate of the function

def interpolate_loop():
    """Nimmt neue IMS-Werte und generiert kontinuierlich Audio-Samples"""
    history = []
    while True:
        t, val = ims_data.get()
        history.append((t, val))
        if len(history) >= 4:
            # Nehme die letzten 4 Punkte
            times, values = zip(*history[-4:])
            interp = interp1d(times, values, kind='cubic')
            # Interpoliere fein zwischen den letzten beiden Zeitpunkten
            t_start = times[-2]
            t_end = times[-1]
            n_samples = int((t_end - t_start) * fs_audio)
            t_interp = np.linspace(t_start, t_end, n_samples)
            samples = interp(t_interp)
            audio_buffer.put(samples.astype(np.float32))

    
def audio_callback(outdata, frames, time_info, status, callback_context):
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
    
# Starte Threads
threading.Thread(target=fake_ims_stream, daemon=True).start()
threading.Thread(target=interpolate_loop, daemon=True).start()

# Setze hier deine Device-Indexe ein:
input_index = 2      # z. B. dein Mikrofon
output_index = 1     # z. B. BlackHole 64ch

# Starte den Duplex-Stream
with sd.Stream(device=(input_index, output_index),
               channels=1,
               samplerate=44100,
               callback=audio_callback):
    print("🎙️ Mic ➝ BlackHole läuft – drücke Ctrl+C zum Stoppen")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("🛑 Stream gestoppt")

# Starte Audio
#with sd.OutputStream(channels=1, callback=audio_callback, samplerate=fs_audio, blocksize=blocksize):
#    print("🎧 Echtzeit-Audio läuft. Drücke Ctrl+C zum Stoppen.")
#    while True:
#       time.sleep(1)
