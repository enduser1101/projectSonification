import numpy as np
import sounddevice as sd
import queue
import threading
import time
from obspy.clients.syngine import Client

# Audio-Einstellungen
fs_audio = 44100  # Samplingrate für Audio
blocksize = 1024  # Blockgröße für Audio-Stream

# Queue zur Zwischenspeicherung der Audio-Daten
audio_queue = queue.Queue()

# SeedLink Client und Verbindungsparameter
client = Client()

# Beispiel für SeedLink-Stream: 'IU.ANMO.00.BHZ'
network = "A2"#"IU"
station = "AGVN"#"ANMO"
channel = "HHE"#"BHZ"

def fetch_seedlink_data():
    """
    Funktion zum Abrufen der SeedLink-Daten und zum Umwandeln in Audio-Samples.
    """
    while True:
        try:
            # Abrufen der letzten 10 Sekunden von SeedLink
            # Das 'model' Argument wird jetzt hinzugefügt
            st = client.get_waveforms(network=network, station=station, starttime=None, endtime=None, units="displacement", model="displacement")
            
            # Umwandeln der Rohdaten in ein numpy-Array
            # Wir extrahieren die Daten des ersten Kanals der Station
            data = np.array([tr.data for tr in st])
            
            # Normalisieren oder auf Audio-Werte umskalieren (optional)
            audio_data = data / np.max(np.abs(data), axis=1, keepdims=True)
            
            # Füge die Daten in die Queue ein
            audio_queue.put(audio_data)
            time.sleep(0.1)  # Warten, um den Stream nicht zu überlasten
        except Exception as e:
            print(f"Fehler beim Abrufen der SeedLink-Daten: {e}")
            time.sleep(1)  # Bei Fehlern 1 Sekunde warten

def audio_callback(outdata, frames, time, status):
    """
    Audio-Callback, der Audio-Daten aus der Queue entnimmt und an 'outdata' übergibt.
    """
    if not audio_queue.empty():
        # Hole den Audio-Block aus der Queue
        audio_block = audio_queue.get()
        # Achte darauf, dass das Array die richtige Form hat (1024, 1)
        outdata[:] = audio_block.reshape(-1, 1)  # Ändere hier die Form, wenn nötig
    else:
        outdata[:] = np.zeros((frames, 1), dtype=np.float32)  # Falls keine Daten da sind, Stille

# Starte die SeedLink-Datenabholung in einem separaten Thread
threading.Thread(target=fetch_seedlink_data, daemon=True).start()

# Audio-Stream starten und Callback nutzen
with sd.OutputStream(channels=1, callback=audio_callback, samplerate=fs_audio, blocksize=blocksize, device='BlackHole 64ch'):
    print("🎧 Echtzeit-Audio läuft. Drücke Ctrl+C zum Stoppen.")
    while True:
        time.sleep(0.01)
