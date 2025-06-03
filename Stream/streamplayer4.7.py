import os
import shutil
import logging
import argparse
import threading
import time
from obspy.clients.seedlink.easyseedlink import EasySeedLinkClient
from obspy import UTCDateTime, Stream, read
from obspy.core import Trace
from multiprocessing import Process
import pandas as pd
import numpy as np
import wave
import resampy
import scipy.signal as pysignal
from datetime import datetime, timezone
from scipy.io.wavfile import write as write_wav

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

MAX_BLOCKS = 100

class MSEEDToWavConverter(threading.Thread):
    def __init__(self, stream_id, raw_dir, wav_dir, target_sr=44100, x=1000, y=100, filter_order=1, cutoff=1.0, att=0.5):
        super().__init__(daemon=True)
        self.stream_id = stream_id
        self.raw_dir = raw_dir
        self.wav_dir = wav_dir
        self.target_sr = target_sr
        self.x = x
        self.y = y
        self.filter_order = filter_order
        self.cutoff = cutoff
        self.att = att

    def run(self):
        logging.info(f"🔁 WAV converter thread started for stream {self.stream_id}.")
        processed = set()

        while True:
            try:
                files = sorted(f for f in os.listdir(self.raw_dir) if f.startswith("block_") and f.endswith(".mseed"))
                if not files:
                    time.sleep(1)
                    continue

                indices = sorted(int(f.split("_")[1]) for f in files)

                for idx in indices:
                    if idx in processed or idx == 0:
                        continue

                    def fname(i):
                        match = [f for f in files if f.startswith(f"block_{i:04d}_")]
                        return match[0] if match else None

                    f_prev = fname(idx - 1)
                    f_mid = fname(idx)
                    f_next = fname(idx + 1)
                    if not f_prev or not f_mid or not f_next:
                        continue

                    tr_prev = read(os.path.join(self.raw_dir, f_prev))[0].data[-self.x:]
                    tr_mid = read(os.path.join(self.raw_dir, f_mid))[0]
                    tr_next = read(os.path.join(self.raw_dir, f_next))[0].data[:self.x]

                    data_combined = np.concatenate([tr_prev, tr_mid.data, tr_next])
                    resampled = resampy.resample(data_combined.astype(np.float32), tr_mid.stats.sampling_rate, self.target_sr)

                    sos = pysignal.butter(self.filter_order, self.cutoff, btype='highpass', fs=self.target_sr, output='sos')
                    resampled = pysignal.sosfilt(sos, resampled)

                    pad_samples = int((self.x - self.y) * self.target_sr / 1000)
                    segment = resampled[pad_samples : -pad_samples] * self.att  # apply attenuation

                    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                    npts = len(segment)
                    station_code = tr_mid.stats.station
                    wav_path = os.path.join(self.wav_dir, f"block_{idx:04d}_{station_code}_{ts}_{npts}.wav")
                    write_wav(wav_path, self.target_sr, segment.astype(np.float32))

                    logging.info(f"🎵 [stream_{self.stream_id}] Saved WAV: {os.path.basename(wav_path)}")
                    processed.add(idx)
                    self.enforce_max_blocks(self.wav_dir, MAX_BLOCKS)



                time.sleep(1)

            except Exception as e:
                logging.error(f"⚠️ [stream_{self.stream_id}] Error: {e}")
                time.sleep(1)

    def enforce_max_blocks(self, directory, limit):
        files = sorted(
            [f for f in os.listdir(directory) if f.endswith(".wav")],
            key=lambda f: os.path.getmtime(os.path.join(directory, f))
        )
        while len(files) > limit:
            oldest = files.pop(0)
            os.remove(os.path.join(directory, oldest))
            logging.info(f"🗑️ Deleted old WAV file: {oldest}")

import sounddevice as sd
import soundfile as sf

class AudioStreamer(threading.Thread):
    def __init__(self, stream_id, wav_dir, samplerate=44100, y=100, channel=0):
        super().__init__(daemon=True)
        self.stream_id = stream_id
        self.wav_dir = wav_dir
        self.samplerate = samplerate
        self.y = y
        self.channel = channel
        self.played = set()

    def run(self):
        logging.info(f"🔊 Audio streamer started for stream {self.stream_id} on channel {self.channel}.")
        blocksize = int(self.samplerate * (2 * self.y) / 1000)  # 2*y ms in samples

        while True:
            try:
                files = sorted(
                    [f for f in os.listdir(self.wav_dir) if f.endswith(".wav")],
                    key=lambda f: os.path.getmtime(os.path.join(self.wav_dir, f))
                )
                files = [f for f in files if f not in self.played]

                if len(files) < 2:
                    time.sleep(0.1)
                    continue

                f1, f2 = files[0], files[1]
                path1 = os.path.join(self.wav_dir, f1)
                path2 = os.path.join(self.wav_dir, f2)
                data1, _ = sf.read(path1, dtype='float32')
                data2, _ = sf.read(path2, dtype='float32')

                if len(data1) < blocksize or len(data2) < blocksize:
                    logging.warning(f"⚠️ [stream_{self.stream_id}] WAV blocks too short for crossfade")
                    time.sleep(0.5)
                    continue

                fade_out = np.linspace(1, 0, blocksize)
                fade_in = np.linspace(0, 1, blocksize)

                pre = data1[:-blocksize]
                cross = data1[-blocksize:] * fade_out + data2[:blocksize] * fade_in
                post = data2[blocksize:]

                full = np.concatenate([pre, cross, post])

                channels_total = 64
                output = np.zeros((len(full), channels_total), dtype=np.float32)
                output[:, self.channel] = full

                sd.play(output, samplerate=self.samplerate, device="BlackHole 64ch")
                sd.wait()

                self.played.add(f1)

            except Exception as e:
                logging.error(f"⚠️ [stream_{self.stream_id}] Audio error: {e}")
                time.sleep(1)


class SeedlinkClient(EasySeedLinkClient):
    def __init__(self, server_url, network, station, channel, outdir_raw, outdir_wav):
        super().__init__(server_url)
        self.stream = Stream()
        self.network = network
        self.station = station
        self.channel = channel
        self.outdir_raw = outdir_raw
        self.outdir_wav = outdir_wav
        self.counter = 0

    def on_data(self, trace):
        self.counter += 1
        timestamp = UTCDateTime.now().strftime("%Y%m%d_%H%M%S")
        samplerate = int(trace.stats.sampling_rate)
        npts = trace.stats.npts
        base_filename = f"block_{self.counter:04d}_{self.station}_{timestamp}_{samplerate}_{npts}"

        mseed_path = os.path.join(self.outdir_raw, base_filename + ".mseed")
        trace.write(mseed_path, format="MSEED")
        logging.info(f"[{self.station}] Saved block #{self.counter} to {mseed_path}")

        self.cleanup_old_files(self.outdir_raw, ".mseed")

    def cleanup_old_files(self, directory, extension):
        files = sorted(
            [f for f in os.listdir(directory) if f.endswith(extension)],
            key=lambda f: os.path.getmtime(os.path.join(directory, f))
        )
        while len(files) > MAX_BLOCKS:
            oldest = files.pop(0)
            os.remove(os.path.join(directory, oldest))
            logging.info(f"[{self.station}] Deleted old file: {oldest}")

def prepare_stream_folders(ref_id):
    base_path = f"streams/stream_{ref_id}"
    raw_path = os.path.join(base_path, "raw")
    wav_path = os.path.join(base_path, "wav")
    for path in [raw_path, wav_path]:
        if os.path.exists(path):
            shutil.rmtree(path)
        os.makedirs(path)
    return raw_path, wav_path

def stream_station(ref_id, server, network, station, channel, x=1000, y=100, filter_order=1, cutoff=1.0, att=0.5, block_delay=10):
    raw_path, wav_path = prepare_stream_folders(ref_id)
    logging.info(f"[{station}] Connecting to {server}")

    # Starte Konvertierungs-Thread für diesen Stream
    converter = MSEEDToWavConverter(ref_id, raw_path, wav_path, x=x, y=y, filter_order=filter_order, cutoff=cutoff, att=att)
    converter.start()

        # Starte Audio-Streaming-Thread verzögert im Hintergrund
    def delayed_audio_start():
        # nutze block_delay aus Argument
        nonlocal block_delay
        while True:
            ready = [f for f in os.listdir(wav_path) if f.endswith(".wav")]
            if len(ready) >= block_delay:
                streamer = AudioStreamer(ref_id, wav_path, samplerate=44100, y=y, channel=ref_id - 1)
                streamer.start()
                break
            time.sleep(0.5)

    threading.Thread(target=delayed_audio_start, daemon=True).start()

    client = SeedlinkClient(server, network, station, channel, raw_path, wav_path)
    client.select_stream(network, station, channel)
    client.station = station
    client.run()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-station SeedLink streamer")
    parser.add_argument("--stations", type=int, default=3, help="Number of stations to stream")
    parser.add_argument("--max_blocks", type=int, default=100, help="Max number of mseed/wav blocks to keep")
    parser.add_argument("--x", type=int, default=1000, help="Transition length in ms")
    parser.add_argument("--y", type=int, default=100, help="Trimmed overlap in ms")
    parser.add_argument("--filter_order", type=int, default=1, help="Order of highpass filter")
    parser.add_argument("--cutoff", type=float, default=1.0, help="Cutoff frequency for highpass filter")
    parser.add_argument("--att", type=float, default=0.5, help="Attenuation factor for WAV output")
    parser.add_argument("--block_delay", type=int, default=4, help="Number of WAV blocks to delay playback")
    args = parser.parse_args()

    N = args.stations
    MAX_BLOCKS = args.max_blocks

    df = pd.read_excel("stations.ods", engine="odf")
    df = df[["Unnamed: 0", "server", "network", "station", "channel"]]
    df.columns = ["ref_id", "server", "network", "station", "channel"]

    processes = []
    for i, row in df.head(N).iterrows():
        proc_args = (row.ref_id, row.server, row.network, row.station, row.channel, args.x, args.y, args.filter_order, args.cutoff, args.att, args.block_delay)
        p = Process(target=stream_station, args=proc_args)
        p.start()
        processes.append(p)

    for p in processes:
        p.join()
