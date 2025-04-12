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

from scipy.interpolate import interp1d


# Configuration
WAV_DIR = "wav_blocks"
DEVICE_NAME = "BlackHole 64ch"
TARGET_FS = 44100
BLOCKSIZE = 2048
MAX_WAV_FILES = 100
MIN_QUEUE_SECONDS = 1  # Minimum seconds of audio before starting playback

# Global audio buffer
audio_queue = queue.Queue()
current_block = None
block_offset = 0
global_max = 1.0  # prevents divide-by-zero in the beginning

# Delete all .wav files at startup
def delete_all_wav_files():
    for f in glob.glob(os.path.join(WAV_DIR, "*.wav")):
        if f.endswith(".wav"):
            try:
                os.remove(f)
                print(f"🗑️  Deleted at startup: {os.path.basename(f)}")
            except Exception as e:
                print(f"⚠️  Could not delete {f}: {e}")

# Limit the number of .wav files to MAX_WAV_FILES
def enforce_max_wav_files(limit=MAX_WAV_FILES):
    wav_files = sorted(glob.glob(os.path.join(WAV_DIR, "*.wav")), key=os.path.getmtime)
    if len(wav_files) > limit:
        try:
            os.remove(wav_files[0])
            print(f"♻️  Deleted oldest file: {os.path.basename(wav_files[0])}")
        except Exception as e:
            print(f"⚠️  Could not delete file: {e}")

# SeedLink client that writes each trace to a .wav file
from scipy.interpolate import interp1d
from datetime import datetime, timezone

# Global variable for normalization
class WavDumpClient(EasySeedLinkClient):
    def __init__(self, network, station, channel):
        super().__init__("rtserve.iris.washington.edu:18000")
        self.select_stream(network, station, channel)
        self.file_counter = 0

    def on_data(self, trace):
        global global_max

        data = trace.data.astype(np.float32)
        fs_in = trace.stats.sampling_rate

        # Update global normalization max
        absmax = np.max(np.abs(data))
        if absmax > global_max:
            global_max = absmax

        if global_max > 0:
            data = data / global_max

        # Interpolate from fs_in to TARGET_FS
        factor = int(TARGET_FS / fs_in)
        if factor > 1:
            t_original = np.linspace(0, 1, len(data), endpoint=False)
            t_target = np.linspace(0, 1, len(data) * factor, endpoint=False)

            interpolator = interp1d(t_original, data, kind='linear')
            data = interpolator(t_target).astype(np.float32)

        # Timestamp and save to file
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        fname = f"block_{self.file_counter:04d}_{ts}.wav"
        filepath = os.path.join(WAV_DIR, fname)

        sf.write(filepath, data, samplerate=TARGET_FS)
        print(f"💾 Saved: {os.path.basename(filepath)} ({len(data)} samples @ {TARGET_FS} Hz)")

        # Optional debug: show start and end values
        print("▶️  First 5 samples:", data[:5])
        print("⏹️  Last 5 samples:", data[-5:])

        self.file_counter += 1
        enforce_max_wav_files()

# Loads blocks into the audio queue in order, starting from the -n-th latest
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
                    print(f"📥 Queueing block: {os.path.basename(target_file)}")
                    try:
                        data, fs = sf.read(target_file, dtype='float32')
                        audio_queue.put(data)
                        played.add(target_file)
                        current_index += 1
                    except Exception as e:
                        print(f"⚠️ Error reading {target_file}: {e}")
                        time.sleep(1)
                else:
                    time.sleep(0.1)
            else:
                time.sleep(0.5)
        else:
            print("⏳ Waiting for more blocks...")
            time.sleep(1)

# Sounddevice callback: fills outdata with audio from the queue
def audio_callback(outdata, frames, time_info, status):
    global current_block, block_offset

    if status:
        print(f"⚠️ Audio stream status: {status}")

    output = np.zeros(frames, dtype=np.float32)
    i = 0

    while i < frames:
        if current_block is None or block_offset >= len(current_block):
            try:
                current_block = audio_queue.get_nowait()
                block_offset = 0
            except queue.Empty:
                output[i:] = 0.0
                print("⚠️ Audio queue underrun!")
                break

        remaining = len(current_block) - block_offset
        length = min(frames - i, remaining)

        output[i:i+length] = current_block[block_offset:block_offset+length]
        i += length
        block_offset += length

    outdata[:] = output.reshape(-1, 1)

# Start everything: recorder, loader, audio
def start(block_delay):
    delete_all_wav_files()

    threading.Thread(
        target=lambda: WavDumpClient("A2", "AGVN", "HHE").run(),
        daemon=True
    ).start()

    threading.Thread(
        target=lambda: playback_loader(block_delay),
        daemon=True
    ).start()

    print(f"⏳ Waiting for {MIN_QUEUE_SECONDS}s of audio in queue...")
    while audio_queue.qsize() * BLOCKSIZE < MIN_QUEUE_SECONDS * TARGET_FS:
        time.sleep(0.1)
    print("✅ Audio buffer ready. Starting playback...")

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

# CLI entry point
if __name__ == "__main__":
    try:
        block_n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    except ValueError:
        print("❌ Invalid argument. Please pass an integer for 'n'.")
        sys.exit(1)

    print(f"🎬 Starting recorder & player with block delay n = {block_n}")
    try:
        start(block_n)
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")
