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
        
        
____________-
def audio_callback(outdata, frames, time_info, status, callback_context):
    samples = np.zeros(frames, dtype=np.float32)
    i = 0
    while i < frames:
        try:
            block = audio_buffer.get_nowait()
            n = min(len(block), frames - i)
            samples[i:i+n] = block[:n]
            if n < len(block):
                audio_buffer.put(block[n:])
            i += n
        except queue.Empty:
            break
    outdata[:] = samples.reshape(-1, 1)