import os
import shutil
import logging
import argparse
import threading
import time
from obspy.clients.seedlink.easyseedlink import EasySeedLinkClient
from obspy import UTCDateTime, Stream, read
from obspy.core import Trace
from threading import Thread
import pandas as pd
import numpy as np
import wave
import resampy
import scipy.signal as pysignal
from datetime import datetime, timezone
from scipy.io.wavfile import write as write_wav
import sounddevice as sd
import queue
import soundfile as sf
from scipy.io import wavfile


# Logging Setup
#logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

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

def enforce_max_blocks(directory, limit):
    files = sorted(
        [f for f in os.listdir(directory) if f.endswith(".wav")],
        key=lambda f: os.path.getmtime(os.path.join(directory, f))
    )
    while len(files) > limit:
        oldest = files.pop(0)
        os.remove(os.path.join(directory, oldest))
        logging.info(f"🗑️ Deleted old WAV file: {oldest}")

def stream_station(ref_id, server, network, station, channel, x=1000, y=100, filter_order=1, cutoff=1.0, att=0.5, block_delay=10):
    raw_path, wav_path = prepare_stream_folders(ref_id)
    logging.info(f"[{station}] Connecting to {server}")

    # Starte Konvertierungs-Thread für diesen Stream
    converter = MSEEDToWavConverter(ref_id, raw_path, wav_path, x=x, y=y, filter_order=filter_order, cutoff=cutoff, att=att)
    converter.start()

    client = SeedlinkClient(server, network, station, channel, raw_path, wav_path)
    client.select_stream(network, station, channel)
    client.station = station
    # Starte AudioStreamer parallel zur SeedLink-Verbindung
    streamer = AudioStreamer(
        wav_dir=wav_path,
        y_ms=y,
        samplerate=44100,
        blocksize=512,
        output_channel=ref_id - 1,
        block_delay=block_delay,
        device="BlackHole 64ch"
    )
    streamer.start()

    client.run()



import os
import numpy as np
import soundfile as sf
import sounddevice as sd
import threading
import queue
import time
import logging

MAX_BLOCKS = 100

class AudioStreamer(threading.Thread):
    def __init__(self, wav_dir, y_ms=100, samplerate=44100, blocksize=512, device=None, output_channel=0, block_delay=4):
        super().__init__(daemon=True)
        self.wav_dir = wav_dir
        self.y_ms = y_ms
        self.y_samples = int((y_ms / 1000.0) * samplerate)
        self.samplerate = samplerate
        self.blocksize = blocksize
        self.device = device
        self.output_channel = output_channel
        self.block_delay = block_delay
        self.buffer = np.zeros(0, dtype=np.float32)
        self.file_queue = queue.Queue()
        self.processed = set()
        self.prev_tail = None

    def run(self):
        logging.info(f"▶️ [AudioStreamer-{self.output_channel}] Starting stream")
        threading.Thread(target=self._watch_directory, daemon=True).start()
        self._start_stream()

    def _watch_directory(self):
        while True:
            try:
                files = sorted(f for f in os.listdir(self.wav_dir) if f.endswith(".wav"))
                for f in files:
                    if f not in self.processed:
                        self.file_queue.put(f)
                        self.processed.add(f)
                time.sleep(0.5)
            except Exception as e:
                logging.warning(f"[Streamer-{self.output_channel}] Directory scan error: {e}")

    def _start_stream(self):
        with sd.OutputStream(
            samplerate=self.samplerate,
            blocksize=self.blocksize,
            channels=64,
            dtype='float32',
            callback=self._callback,
            device=self.device
        ):
            while True:
                time.sleep(1)

    def _callback(self, outdata, frames, time_info, status):
        if status:
            logging.warning(f"[Streamer-{self.output_channel}] Audio callback status: {status}")

        outdata[:] = np.zeros((frames, 64), dtype=np.float32)

        while self.file_queue.qsize() >= self.block_delay and len(self.buffer) < 10 * self.blocksize:
            fname = self.file_queue.get()
            path = os.path.join(self.wav_dir, fname)
            try:
                data, sr = sf.read(path, dtype='float32')
                if sr != self.samplerate:
                    logging.warning(f"Sample rate mismatch: {sr} != {self.samplerate} in {fname}")
                    continue
                if data.ndim > 1:
                    data = data[:, 0]

                logging.debug(f"{fname} samples: {len(data)} | prev_tail: {len(self.prev_tail) if self.prev_tail is not None else 0} | fade_len: {self.y_samples}")

                if self.prev_tail is None:
                    self.buffer = np.concatenate((self.buffer, data[:-self.y_samples]))
                    self.prev_tail = data[-self.y_samples:]
                else:
                    fade_out, fade_in = self._raised_cosine_fade(self.y_samples)
                    cross = self.prev_tail * fade_out + data[:self.y_samples] * fade_in
                    body = data[self.y_samples:-self.y_samples] if len(data) > 2 * self.y_samples else np.array([], dtype=np.float32)
                    self.buffer = np.concatenate((self.buffer, cross, body))
                    self.prev_tail = data[-self.y_samples:]

            except Exception as e:
                logging.warning(f"Error loading {fname}: {e}")

        chunk = self.buffer[:frames]
        outdata[:len(chunk), self.output_channel] = chunk
        self.buffer = self.buffer[frames:]

    def _raised_cosine_fade(self, fade_len):
        x = np.linspace(0, np.pi, fade_len)
        fade_out = 0.5 * (1 + np.cos(x))
        fade_in = 0.5 * (1 - np.cos(x))
        return fade_out.astype(np.float32), fade_in.astype(np.float32)







if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Multi-station SeedLink streamer")
    parser.add_argument("--stations", type=int, default=15, help="Number of stations to stream")
    parser.add_argument("--max_blocks", type=int, default=100, help="Max number of mseed/wav blocks to keep")
    parser.add_argument("--x", type=int, default=1000, help="Transition length in ms")
    parser.add_argument("--y", type=int, default=100, help="Trimmed overlap in ms")
    parser.add_argument("--filter_order", type=int, default=2, help="Order of highpass filter")
    parser.add_argument("--cutoff", type=float, default=1.0, help="Cutoff frequency for highpass filter")
    parser.add_argument("--att", type=float, default=0.1, help="Attenuation factor for WAV output")
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
        p = Thread(target=stream_station, args=proc_args)
        p.start()
        processes.append(p)

    for p in processes:
        p.join()
