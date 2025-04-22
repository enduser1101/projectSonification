import os
import sys
import glob
import time
import queue
import threading
import argparse
import json
import logging
from datetime import datetime, timezone
import numpy as np
import soundfile as sf # for writing audio files
import sounddevice as sd # for streaming audio
from obspy.clients.seedlink.easyseedlink import EasySeedLinkClient
import resampy # for resampling

# ----------------------------
# Default configuration
DEFAULT_BLOCK_DELAY = 20
DEFAULT_TARGET_FS = 44100
DEFAULT_BLOCKSIZE = 2048
DEFAULT_MAX_WAV_FILES = 100
DEFAULT_MIN_QUEUE_SECONDS = 30.0
DEFAULT_DEVICE_NAME = "BlackHole 64ch"
DEFAULT_TAPER_MS = 0  # Taper duration in milliseconds
STATIONS_FILE = "stations.json"
WAV_DIR = "wav_blocks"
LOG_FILE = "stream.log"
# ----------------------------

def setup_logging(log_file=LOG_FILE):
    """
    Configures logging for the application.

    Args:
        log_file (str): The name of the log file.
    """
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)  # We set the level back to INFO to disable debug messages
    logger.handlers = []
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger

logger = setup_logging()

# Global variables
audio_queue = queue.Queue()
current_block = None
block_offset = 0
global_max = 1.0
stream_gap_duration = {'total': 0.0}
block_counter = {'count': 0, 'saved_total': 0}

def load_stations_json(stations_file=STATIONS_FILE):
    """
    Loads the station configuration from a JSON file.
    """
    if not os.path.exists(stations_file):
        logging.error(f"Station file not found: {stations_file}")
        sys.exit(1)
    try:
        with open(stations_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON in {stations_file}: {e}")
        sys.exit(1)

def delete_all_wav_files(wav_dir=WAV_DIR):
    """
    Deletes all .wav files in the specified directory.
    """
    deleted_count = 0;
    try:
        for filepath in glob.glob(os.path.join(wav_dir, "*.wav")):
            try:
                os.remove(filepath)
                deleted_count += 1
            except OSError as e:
                logging.warning(f"Could not delete {filepath}: {e}")
        if deleted_count:
            logging.info(f"🗑️  Deleted {deleted_count} existing .wav files at startup")
    except Exception as e:
        logging.error(f"Error deleting WAV files: {e}")

def enforce_max_wav_files(limit, wav_dir=WAV_DIR):
    """
    Enforces a limit on the number of .wav files in the directory.
    """
    try:
        wav_files = sorted(glob.glob(os.path.join(wav_dir, "*.wav")), key=os.path.getmtime)
    except FileNotFoundError:
        logging.warning(f"WAV directory not found: {wav_dir}")
        return

    while len(wav_files) > limit:
        try:
            os.remove(wav_files[0])
            logging.info(f"♻️  Deleted oldest file: {os.path.basename(wav_files[0])}")
            wav_files.pop(0)
        except OSError as e:
            logging.warning(f"Could not delete file: {e}")
            break

def apply_taper(data, sample_rate, taper_ms):
    """
    Applies a Hann taper to the beginning and end of the data.
    """
    if taper_ms <= 0:
        return data
    taper_len = int(sample_rate * taper_ms / 1000)
    if taper_len == 0 or taper_len * 2 >= len(data):
        logging.warning(f"Taper length ({taper_len} samples) too long or zero, skipping taper.")
        return data

    taper_window = np.hanning(taper_len * 2)
    fade_in = taper_window[:taper_len]
    fade_out = taper_window[taper_len:]

    tapered_data = data.copy()
    tapered_data[:taper_len] *= fade_in
    tapered_data[-taper_len:] *= fade_out
    return tapered_data

class WavDumpClient(EasySeedLinkClient):
    """
    A SeedLink client that saves received data as .wav files.
    """

    def __init__(self, server, network, station, channel, target_fs, max_wav_files, block_delay, taper_ms):
        super().__init__(server)
        self.select_stream(network, station, channel)
        self.file_counter = 0
        self.target_fs = target_fs
        self.max_wav_files = max_wav_files
        self.block_delay = block_delay
        self.taper_ms = taper_ms

    def on_data(self, trace):
        """
        Processes received data blocks, resamples them, applies a taper,
        and saves them as .wav files.
        """
        global global_max
        global block_counter

        data = trace.data.astype(np.float32)
        fs_in = trace.stats.sampling_rate

        absmax = np.max(np.abs(data))
        if absmax > global_max:
            global_max = absmax

        if global_max > 0:
            data /= global_max

        # Resample to target_fs
        if fs_in != self.target_fs:
            try:
                data = resampy.resample(data, fs_in, self.target_fs)
            except Exception as e:
                logging.error(f"Resampling failed: {e}")
                return

        # Apply the taper
        data = apply_taper(data, self.target_fs, self.taper_ms)

        logging.info(
            f"📱 Received block with {len(trace.data)} samples @ {fs_in} Hz "
            f"→ {len(data)} samples @ {self.target_fs} Hz"
        )

        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        fname = f"block_{self.file_counter:04d}_{ts}.wav"
        filepath = os.path.join(WAV_DIR, fname)
        try:
            sf.write(filepath, data, samplerate=self.target_fs, subtype='PCM_24')
            logging.info(
                f"📂 Saved: {os.path.basename(filepath)} ({len(data)} samples @ {self.target_fs} Hz) "
                f"({self.file_counter + 1}/{self.block_delay if self.file_counter < self.block_delay else self.block_delay})"
            )
            self.file_counter += 1
            block_counter['saved_total'] += 1

            enforce_max_wav_files(self.max_wav_files)

            if self.file_counter == self.block_delay:
                logging.info(
                    f"✅ {self.block_delay} blocks have been saved and are ready for playback."
                )
        except Exception as e:
            logging.error(f"Error writing WAV file: {e}")

def playback_loader(block_delay, wav_dir=WAV_DIR):
    """
    Loads .wav files from a directory and adds them to the audio queue.
    This function has been revised to avoid race conditions and
    handle deleted files more robustly.
    """
    played = set()
    while True:
        wav_files = sorted(glob.glob(os.path.join(wav_dir, "*.wav")), key=os.path.getmtime)
        # logging.debug(f"Current WAV files: {wav_files}") #debug
        if len(wav_files) >= block_delay:
            for filepath in wav_files:
                if filepath not in played:
                    if os.path.exists(filepath):
                        logging.info(f"📥 Queueing block: {os.path.basename(filepath)}")
                        try:
                            data, _ = sf.read(filepath, dtype='float32')
                            audio_queue.put(data)
                            played.add(filepath)
                        except Exception as e:
                            logging.warning(f"Error reading {filepath}: {e}")
                    else:
                        logging.warning(f"File {filepath} was deleted before being loaded.")
                    break
        else:
            logging.info("⏳ Waiting for more blocks...")
        time.sleep(0.1)

def audio_callback(outdata, frames, time_info, status):
    """
    Callback function for the audio stream.
    """
    global current_block, block_offset
    global stream_gap_duration

    if status:
        logging.warning(f"⚠️ Audio stream status: {status}")
    output = np.zeros((frames, 1), dtype=np.float32)
    i = 0

    while i < frames:
        if current_block is None or block_offset >= len(current_block):
            try:
                current_block = audio_queue.get_nowait()
                block_offset = 0
            except queue.Empty:
                start_gap = time.time()
                while audio_queue.empty():
                    time.sleep(0.01)
                stream_gap_duration['total'] += time.time() - start_gap
                logging.warning("⚠️ Audio queue underrun!")
                output[i:] = 0.0
                break

        remaining = len(current_block) - block_offset
        length = min(frames - i, remaining)
        output[i:i+length, 0] = current_block[block_offset:block_offset+length]
        i += length
        block_offset += length
    outdata[:] = output

def queue_duration_seconds(target_fs):
    """Calculates the current duration of the audio queue in seconds."""
    return sum(len(x) for x in list(audio_queue.queue)) / target_fs

def start(args, station):
    """
    Starts the entire streaming and playback process.
    """
    start_time = time.time()
    global block_counter
    queue_empty_duration = {'total': 0.0}

    def update_status():
        """
        A thread that periodically writes the application status to a JSON file.
        """
        queue_durations = []
        logging.info("📊 Status thread started")
        while True:
            elapsed = int(time.time() - start_time)
            days, rem = divmod(elapsed, 86400)
            hours, rem = divmod(rem, 3600)
            minutes, seconds = divmod(rem, 60)
            uptime_str = f"{days:02}:{hours:02}:{minutes:02}:{seconds:02}"
            queue_duration = queue_duration_seconds(args.target_fs)
            queue_durations.append(queue_duration)
            avg_queue_duration = sum(queue_durations) / len(queue_durations) if queue_durations else 0.0
            try:
                with open("status.json", "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            'args': vars(args),
                            'uptime': uptime_str,
                            'queue_duration_sec': round(queue_duration, 2),
                            'queue_duration_avg_sec': round(avg_queue_duration, 2),
                            'block_count': block_counter['count'],
                            'block_saved_total': block_counter['saved_total'],
                            'queue_empty_time_total_sec': round(queue_empty_duration['total'], 2),
                            'stream_gap_total_sec': round(stream_gap_duration['total'], 2),
                        },
                        f,
                        indent=2,
                    )
                time.sleep(1)
            except Exception as e:
                logging.error(f"❌ Could not write status.json: {e}")

    def track_queue_empty():
        """
        A thread that measures the time the audio queue is empty.
        """
        while queue_duration_seconds(args.target_fs) < args.min_queue_seconds:
            time.sleep(0.1)
        while True:
            if audio_queue.empty():
                start_empty = time.time()
                while audio_queue.empty():
                    time.sleep(0.1)
                queue_empty_duration['total'] += time.time() - start_empty
            time.sleep(1)

    def block_count_monitor():
        """
        A thread that counts the number of WAV files in the output directory.
        """
        while True:
            wav_files = glob.glob(os.path.join(WAV_DIR, "*.wav"))
            block_counter['count'] = len(wav_files)
            time.sleep(2)

    delete_all_wav_files()

    # Start the threads
    threading.Thread(
        target=lambda: WavDumpClient(
            server=station["server"],
            network=station["network"],
            station=station["station"],
            channel=station["channel"],
            target_fs=args.target_fs,
            max_wav_files=args.max_wav_files,
            block_delay=args.block_delay,
            taper_ms=args.taper,
        ).run(),
        daemon=True,
    ).start()

    threading.Thread(
        target=lambda: playback_loader(args.block_delay),
        daemon=True,
    ).start()

    threading.Thread(target=update_status, daemon=True).start()
    threading.Thread(target=track_queue_empty, daemon=True).start()
    threading.Thread(target=block_count_monitor, daemon=True).start()

    logging.info(f"⏳ Waiting for {args.min_queue_seconds}s of audio in queue...")
    while queue_duration_seconds(args.target_fs) < args.min_queue_seconds:
        time.sleep(0.1)
    logging.info("✅ Audio queue filled with minimum required duration. Starting playback...")

    try:
        with sd.OutputStream(
            samplerate=args.target_fs,
            channels=1,
            callback=audio_callback,
            blocksize=args.blocksize,
            dtype='float32',
            device=args.device,
        ):
            while True:
                time.sleep(0.1)
    except sd.PortAudioError as e:
        logging.error(f"Error during audio playback: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logging.info("🛑 Stopped by user.")
    except Exception as e:
        logging.error(f"Unhandled error: {e}")
        sys.exit(1)

def main():
    """
    Main function of the script.
    """
    parser = argparse.ArgumentParser(description="Stream SeedLink data and play as audio")
    parser.add_argument("--station-id", type=str, required=True, help="Station ID from stations.json (e.g. 01)")
    parser.add_argument("--block-delay", type=int, default=DEFAULT_BLOCK_DELAY, help="Number of blocks to buffer before playback")
    parser.add_argument("--target-fs", type=int, default=DEFAULT_TARGET_FS, help="Target sampling rate for audio")
    parser.add_argument("--blocksize", type=int, default=DEFAULT_BLOCKSIZE, help="Audio block size for playback")
    parser.add_argument("--max-wav-files", type=int, default=DEFAULT_MAX_WAV_FILES, help="Maximum number of .wav files to keep")
    parser.add_argument("--min-queue-seconds", type=float, default=DEFAULT_MIN_QUEUE_SECONDS, help="Minimum audio queue duration before playback starts")
    parser.add_argument("--device", type=str, default=DEFAULT_DEVICE_NAME, help="Name of the audio output device")
    parser.add_argument("--taper", type=int, default=DEFAULT_TAPER_MS, help="Taper duration in milliseconds (0 for no taper)")

    args = parser.parse_args()
    all_stations = load_stations_json()

    if args.station_id not in all_stations:
        logging.error(f"Station ID '{args.station_id}' not found in {STATIONS_FILE}")
        sys.exit(1)

    station_conf = all_stations[args.station_id]

    logging.info(f"🎮 Starting stream for station ID {args.station_id}")
    logging.info(f"  🌍 Server: {station_conf['server']}")
    logging.info(f"  📱 Stream: {station_conf['network']}.{station_conf['station']}.{station_conf['channel']}")
    logging.info(f"  🎷 Device: {args.device}")

    start(args, station_conf)

if __name__ == "__main__":
    main()
