import os
import sys
import glob
import time
import queue
import threading
from datetime import datetime, timezone

import numpy as np
import soundfile as sf
import sounddevice as sd
from obspy.clients.seedlink.easyseedlink import EasySeedLinkClient

# 📁 Ordner für WAV-Dateien
WAV_DIR = "wav_blocks"
os.makedirs(WAV_DIR, exist_ok=True)

# 🎛 Konfiguration
DEVICE_NAME = "BlackHole 64ch"
TARGET_FS = 44100
BLOCKSIZE = 2048
MAX_WAV_FILES = 100
MIN_QUEUE_SECONDS = 1  # min. Sek. Audio, bevor Wiedergabe startet

# Audio-Queue für ganze Blöcke
audio_queue = queue.Queue()

# 🗑 Alte WAV-Dateien beim Start löschen
def delete_all_wav_files():
    for f in glob.glob(os.path.join(WAV_DIR, "*.wav")):
        if f.endswith(".wav"):
            try:
                os.remove(f)
                print(f"🗑️  Gelöscht beim Start: {os.path.basename(f)}")
            except Exception as e:
                print(f"⚠️  Fehler beim Löschen von {f}: {e}")

# 🔁 Max WAV-Dateien im Ordner
def enforce_max_wav_files(limit=MAX_WAV_FILES):
    wav_files = sorted(glob.glob(os.path.join(WAV_DIR, "*.wav")), key=os.path.getmtime)
    if len(wav_files) > limit:
        try:
            os.remove(wav_files[0])
            print(f"♻️  Max erreicht – gelöscht: {os.path.basename(wav_files[0])}")
        except Exception as e:
            print(f"⚠️  Fehler beim Löschen: {e}")

# 📡 Recorder: SeedLink → WAV
class WavDumpClient(EasySeedLinkClient):
    def __init__(self, network, station, channel):
        super().__init__("rtserve.iris.washington.edu:18000")
        self.select_stream(network, station, channel)
        self.file_counter = 0

    def on_data(self, trace):
        data = trace.data.astype(np.float32)
        fs_in = trace.stats.sampling_rate

        if np.max(np.abs(data)) > 0:
            data /= np.max(np.abs(data))  # Normalisieren

        # 🔁 Hochsampeln auf TARGET_FS
        factor = int(TARGET_FS / fs_in)
        if factor > 1:
            data = np.repeat(data, factor)

        # ✅ Zukunftssicherer UTC-Zeitstempel
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        fname = f"block_{self.file_counter:04d}_{ts}.wav"
        filepath = os.path.join(WAV_DIR, fname)

        sf.write(filepath, data, samplerate=TARGET_FS)
        print(f"💾 Gespeichert: {os.path.basename(filepath)} ({len(data)} samples @ {TARGET_FS} Hz)")

        self.file_counter += 1
        enforce_max_wav_files()


# 📥 Lade WAV-Blöcke in Queue (ganz)
def playback_loader(block_delay=1):
    played = set()
    current_index = None

    while True:
        wav_files = sorted(glob.glob(os.path.join(WAV_DIR, "*.wav")), key=os.path.getmtime)

        if len(wav_files) >= block_delay:
            if current_index is None:
                current_index = len(wav_files) - block_delay

            if current_index < len(wav_files):
                target_file = wav_files[current_index]
                if target_file not in played:
                    print(f"📥 Lade in Audio-Queue: {os.path.basename(target_file)}")
                    try:
                        data, fs = sf.read(target_file, dtype='float32')
                        audio_queue.put(data)
                        played.add(target_file)
                        current_index += 1
                    except Exception as e:
                        print(f"⚠️ Fehler beim Lesen: {target_file} → {e}")
                        time.sleep(1)
                else:
                    time.sleep(0.1)
            else:
                time.sleep(0.5)
        else:
            print("⏳ Warte auf genug Blöcke...")
            time.sleep(1)

# 🔊 Audio-Callback (zieht aus Queue Blöcke)
def audio_callback(outdata, frames, time_info, status):
    buffer = []

    while len(buffer) < frames:
        try:
            block = audio_queue.get_nowait()
            buffer.extend(block)
        except queue.Empty:
            # Fülle Rest mit Stille
            buffer.extend([0.0] * (frames - len(buffer)))
            print("⚠️ Audio underrun!")
            break

    outdata[:] = np.array(buffer[:frames], dtype=np.float32).reshape(-1, 1)

# 🚀 Start Recorder & Player
def start(block_delay):
    delete_all_wav_files()

    # 📡 Recorder starten
    threading.Thread(
        target=lambda: WavDumpClient("A2", "AGVN", "HHE").run(),
        daemon=True
    ).start()

    # 🎧 Player/Loader starten
    threading.Thread(
        target=lambda: playback_loader(block_delay),
        daemon=True
    ).start()

    # 🕐 Warte bis Queue gefüllt ist
    print(f"⏳ Warte auf mindestens {MIN_QUEUE_SECONDS}s Audiopuffer...")
    while audio_queue.qsize() * BLOCKSIZE < MIN_QUEUE_SECONDS * TARGET_FS:
        time.sleep(0.1)
    print("✅ Audio-Queue bereit. Starte Wiedergabe...")

    # 🎶 Audio-Ausgabe starten
    with sd.OutputStream(
        samplerate=TARGET_FS,
        channels=1,
        callback=audio_callback,
        blocksize=BLOCKSIZE,
        dtype='float32',
        device=DEVICE_NAME
    ):
        while True:
            time.sleep(0.1)

# 🧪 CLI
if __name__ == "__main__":
    try:
        block_n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    except ValueError:
        print("❌ Ungültiger Wert für n. Bitte gib eine ganze Zahl an.")
        sys.exit(1)

    print(f"🎬 Starte Recorder & Player mit Delay n = {block_n}")
    try:
        start(block_n)
    except KeyboardInterrupt:
        print("\n🛑 Manuell gestoppt.")
