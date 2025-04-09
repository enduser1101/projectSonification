from obspy.clients.seedlink.basic_client import Client
from obspy.core import Stream
import numpy as np
import sounddevice as sd
import threading
import queue
import time

# Parameter
fs_audio = 44100       # Audio-Samplingrate
fs_signal = 20         # "Echte" Signalrate (z. B. IMS-Simulation)
blocksize = 1024
amplitude = 1.0
frequency = 0.2        # Testfrequenz in Hz

# Queues
signal_queue = queue.Queue(maxsize=100)
audio_queue = queue.Queue(maxsize=220) # ca. 5 sec at blocksize of 1024

# Beispiel: IRIS streamt z. B. Station ANMO, Kanal BHZ (Broadband High-Gain Vertical)
STATION = "ANMO"
CHANNEL = "BHZ"
NETWORK = "IU"

class MySeedLinkClient(Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.buffer = Stream()

    def on_data(self, trace):
        data = trace.data.astype(np.float32)
        print(f"📡 Empfangen: {len(data)} Samples")
        signal_queue.put(data)  # Ganze Blöcke in die Signal-Queue pushen

# SeedLink-Verbindung starten (läuft in separatem Thread)
def start_seedlink():
    client = MySeedLinkClient()
    client.select_stream(NETWORK, STATION, CHANNEL)
    client.begin("rtserve.iris.washington.edu", 18000)

threading.Thread(target=start_seedlink, daemon=True).start()

# 1️⃣ Signal-Generator mit niedriger Sample-Rate (z. B. 20 Hz)
def signal_generator():
    t = 0.0
    while True:
        val = amplitude * np.sin(2 * np.pi * frequency * t)
        signal_queue.put((t, val))
        t += 1.0 / fs_signal
        time.sleep(1.0 / fs_signal)

# 2️⃣ Interpolator: erzeugt Audio-Blöcke durch Upsampling
def signal_to_audio():
    buffer = []  # Zwischenspeicher für Interpolation
    duration = blocksize / fs_audio
    t_audio = 0.0

    while True:
        # Fülle buffer mit genug Punkten
        while len(buffer) < 2:
            try:
                buffer.append(signal_queue.get(timeout=1))
            except queue.Empty:
                continue

        (t0, y0), (t1, y1) = buffer[0], buffer[1]

        # Interpolation für blocksize Samples
        t_vals = np.linspace(t_audio, t_audio + duration, blocksize, endpoint=False)
        interp_vals = np.interp(t_vals, [t0, t1], [y0, y1])

        # Block senden
        audio_queue.put(interp_vals.astype(np.float32))

        t_audio += duration

        # Wenn Zeit überschritten → alten Punkt verwerfen
        if t_audio >= t1:
            buffer.pop(0)

def audio_callback(outdata, frames, time_info, status):
    try:
        block = audio_queue.get(timeout=0.01)
    except queue.Empty:
        block = np.zeros(frames, dtype=np.float32)
        print(f"⚠️  Audio queue underrun! Queue size: {audio_queue.qsize()}")
    else:
        print(f"✅ Queue ok. Size: {audio_queue.qsize()}")
    
    if len(block) < frames:
        block = np.pad(block, (0, frames - len(block)))
    outdata[:] = block.reshape(-1, 1)

def start_stream():
    threading.Thread(target=signal_generator, daemon=True).start()
    threading.Thread(target=signal_to_audio, daemon=True).start()

    # Warte auf ca. 1–2 Sekunden Puffer
    min_buffer_blocks = int(fs_audio * 2 / blocksize)
    print(f"⏳ Warte auf mindestens {min_buffer_blocks} Blöcke Audio-Daten...")

    while audio_queue.qsize() < min_buffer_blocks:
        time.sleep(0.01)

    print("✅ Genug Audio-Daten gepuffert. Starte Stream.")
    with sd.OutputStream(callback=audio_callback,
                         samplerate=fs_audio,
                         blocksize=blocksize,
                         channels=1,
                         device='BlackHole 64ch'):
        print("🎧 Stream läuft – Drücke Ctrl+C zum Stoppen.")
        while True:
            time.sleep(0.1)


start_stream()

