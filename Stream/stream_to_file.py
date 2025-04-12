import os
import glob
import numpy as np
import soundfile as sf
from obspy.clients.seedlink.easyseedlink import EasySeedLinkClient
from datetime import datetime

# Ordner für WAV-Dateien
OUTPUT_DIR = "wav_blocks"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ✅ Alle .wav-Dateien beim Start löschen (nicht andere Dateien)
def delete_all_wav_files():
    wav_files = glob.glob(os.path.join(OUTPUT_DIR, "*.wav"))
    for f in wav_files:
        try:
            os.remove(f)
            print(f"🗑️  Gelöscht beim Start: {os.path.basename(f)}")
        except Exception as e:
            print(f"⚠️  Fehler beim Löschen von {f}: {e}")

# ✅ Ältestes WAV löschen, wenn mehr als 100 Dateien vorhanden
def enforce_max_wav_files(limit=100):
    wav_files = sorted(
        glob.glob(os.path.join(OUTPUT_DIR, "*.wav")),
        key=os.path.getmtime
    )
    if len(wav_files) > limit:
        oldest = wav_files[0]
        try:
            os.remove(oldest)
            print(f"♻️  Max erreicht – gelöscht: {os.path.basename(oldest)}")
        except Exception as e:
            print(f"⚠️  Fehler beim Löschen von {oldest}: {e}")

# 📡 SeedLink-Client
class WavDumpClient(EasySeedLinkClient):
    def __init__(self, network, station, channel):
        super().__init__("rtserve.iris.washington.edu:18000")
        self.select_stream(network, station, channel)
        self.file_counter = 0

    def on_data(self, trace):
        data = trace.data.astype(np.float32)
        fs = trace.stats.sampling_rate

        if np.max(np.abs(data)) > 0:
            data /= np.max(np.abs(data))  # optional normalisieren

        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        fname = f"block_{self.file_counter:04d}_{ts}.wav"
        filepath = os.path.join(OUTPUT_DIR, fname)

        sf.write(filepath, data, samplerate=int(fs))
        print(f"💾 Gespeichert: {os.path.basename(filepath)} ({len(data)} samples @ {fs} Hz)")

        self.file_counter += 1
        enforce_max_wav_files(limit=100)

# 🚀 Start
if __name__ == "__main__":
    delete_all_wav_files()

    print("🌐 Starte SeedLink → WAV Recorder...")
    client = WavDumpClient("A2", "AGVN", "HHE")

    try:
        client.run()
    except KeyboardInterrupt:
        print("🛑 Manuell gestoppt.")
