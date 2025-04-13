import os
import sys
import glob
import time
import queue
import threading
import argparse # For command-line arguments
from datetime import datetime, timezone

import numpy as np
import soundfile as sf
import sounddevice as sd
import resampy # For high-quality resampling
from obspy.clients.seedlink.easyseedlink import EasySeedLinkClient
from obspy import Trace # To potentially use Trace methods like taper

# --- Configuration ---
WAV_DIR = "wav_blocks"
os.makedirs(WAV_DIR, exist_ok=True)

# Default values (can be overridden by command-line args)
DEFAULT_DEVICE_NAME = "BlackHole 64ch"
DEFAULT_TARGET_FS = 44100
DEFAULT_BLOCKSIZE = 2048 # Affects sounddevice callback frequency
DEFAULT_MAX_WAV_FILES = 100 # Max number of temp files
DEFAULT_MIN_QUEUE_SECONDS = 2 # Increased default buffer before playback
DEFAULT_TAPER_MS = 5 # Duration of fade-in/out taper in milliseconds

# Global variables for audio playback
current_block = None
block_offset = 0
audio_queue = queue.Queue()
playback_lock = threading.Lock() # To safely access current_block/offset

# --- Helper Functions ---

def delete_all_wav_files():
    """Clears the WAV directory on startup."""
    print(f"🧹 Clearing temporary WAV directory: {WAV_DIR}")
    for f in glob.glob(os.path.join(WAV_DIR, "*.wav")):
        if f.endswith(".wav"):
            try:
                os.remove(f)
                # print(f"🗑️ Deleted on startup: {os.path.basename(f)}")
            except Exception as e:
                print(f"⚠️ Error deleting {f}: {e}")
    print("✅ WAV directory cleared.")

def enforce_max_wav_files(limit):
    """Keeps only the most recent 'limit' WAV files."""
    try:
        wav_files = sorted(glob.glob(os.path.join(WAV_DIR, "*.wav")), key=os.path.getmtime)
        while len(wav_files) > limit:
            file_to_delete = wav_files.pop(0) # Get the oldest file
            try:
                os.remove(file_to_delete)
                # print(f"♻️ Max files reached – deleted: {os.path.basename(file_to_delete)}")
            except Exception as e:
                print(f"⚠️ Error deleting old file {os.path.basename(file_to_delete)}: {e}")
    except Exception as e:
         print(f"⚠️ Error enforcing max WAV files: {e}")


def apply_taper(data, sample_rate, taper_ms):
    """Applies a Hann taper to the start and end of the data."""
    if taper_ms <= 0:
        return data
    taper_len = int(sample_rate * taper_ms / 1000)
    if taper_len == 0 or taper_len * 2 >= len(data):
        print(f"⚠️ Taper length ({taper_len} samples) too long or zero, skipping taper.")
        return data

    taper_window = np.hanning(taper_len * 2) # Hann window shape
    fade_in = taper_window[:taper_len]
    fade_out = taper_window[taper_len:]

    tapered_data = data.copy() # Work on a copy
    tapered_data[:taper_len] *= fade_in
    tapered_data[-taper_len:] *= fade_out
    return tapered_data

# --- Seedlink Client ---

class WavDumpClient(EasySeedLinkClient):
    """Connects to Seedlink, processes traces, and saves WAV blocks."""
    def __init__(self, server_url, network, station, channel, target_fs, taper_ms):
        print(f"📡 Connecting to Seedlink: {server_url} for {network}.{station}..{channel}")
        try:
            super().__init__(server_url) # Connect on init
            self.select_stream(network, station, channel)
            print(f"✅ Successfully selected stream: {network}.{station}..{channel}")
        except Exception as e:
            print(f"❌ Failed to connect or select stream: {e}")
            # Consider exiting or raising the exception depending on desired behavior
            raise ConnectionError(f"Seedlink connection failed: {e}") from e

        self.target_fs = target_fs
        self.taper_ms = taper_ms
        self.file_counter = 0
        self.last_data_time = time.monotonic()

    def on_data(self, trace):
        """Processes incoming obspy Trace."""
        self.last_data_time = time.monotonic() # Record time of last data arrival
        print(f"Received trace: {trace.id} ({trace.stats.npts} samples @ {trace.stats.sampling_rate} Hz)")
        try:
            data = trace.data.astype(np.float32)
            fs_in = trace.stats.sampling_rate

            # --- Normalization Removed ---
            # Normalization is removed to prevent level jumps between blocks.
            # Handle gain/dynamics in the receiving application (Max/MSP).
            # If max abs value is zero, skip processing
            max_abs = np.max(np.abs(data))
            if max_abs == 0:
                print("  -> Trace contains only zeros, skipping.")
                return

            # --- High-Quality Resampling (using resampy) ---
            print(f"  Resampling from {fs_in} Hz to {self.target_fs} Hz...")
            if fs_in == self.target_fs:
                resampled_data = data
            else:
                # Use resampy for better quality than np.repeat
                resampled_data = resampy.resample(data, fs_in, self.target_fs, filter='kaiser_best')
            print(f"  Resampled to {len(resampled_data)} samples.")

             # --- Apply Taper ---
            if self.taper_ms > 0:
                print(f"  Applying {self.taper_ms}ms taper...")
                resampled_data = apply_taper(resampled_data, self.target_fs, self.taper_ms)
                print("  Taper applied.")

            # --- Save WAV File ---
            # Use UTC timestamp for unique filenames
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") # Added microseconds
            fname = f"block_{self.file_counter:06d}_{ts}.wav" # Increased padding
            filepath = os.path.join(WAV_DIR, fname)

            # Use soundfile to write float32 data
            sf.write(filepath, resampled_data, samplerate=int(self.target_fs), subtype='FLOAT')
            print(f"💾 Saved: {os.path.basename(filepath)} ({len(resampled_data)} samples)")

            self.file_counter += 1

        except Exception as e:
            print(f"⚠️ Error processing trace {trace.id}: {e}")


    def on_seedlink_error(self):
        """Callback for Seedlink errors."""
        print("❌ Seedlink ERROR response received.")
        # Consider adding logic here, e.g., attempt reconnect or exit

    def on_terminate(self):
        """Callback for connection termination."""
        print("🔌 Seedlink connection terminated.")
        # Consider adding logic here, e.g., cleanup or exit


# --- Playback Logic ---

def playback_loader(block_delay, max_files):
    """Monitors WAV_DIR, loads files into audio_queue with delay."""
    played_files = set()
    file_index_to_play = 0 # Index in the sorted list to target next
    last_file_added = None

    print(f"🎧 Playback loader started. Waiting for {block_delay} blocks...")

    while True:
        try:
            # Get current list of WAV files, sorted by modification time
            wav_files = sorted(glob.glob(os.path.join(WAV_DIR, "*.wav")), key=os.path.getmtime)

            # Clean up excess files *before* adding new ones to queue
            enforce_max_wav_files(max_files)
            if len(wav_files) > max_files: # Update list if files were deleted
                 wav_files = sorted(glob.glob(os.path.join(WAV_DIR, "*.wav")), key=os.path.getmtime)

            available_files = len(wav_files)

            # Only proceed if enough files exist relative to the target index
            if available_files > file_index_to_play:
                target_file = wav_files[file_index_to_play]

                # Check if this file is different from the last one added
                # and hasn't been played (safety check, index should handle this)
                if target_file != last_file_added and target_file not in played_files:
                    print(f"📥 Loading into queue: {os.path.basename(target_file)}")
                    try:
                        data, fs = sf.read(target_file, dtype='float32')
                        if fs != DEFAULT_TARGET_FS: # Use global default here
                             print(f"⚠️ Warning: File {os.path.basename(target_file)} has wrong sample rate ({fs} Hz), expected {DEFAULT_TARGET_FS} Hz. Skipping.")
                        elif len(data) > 0:
                            audio_queue.put(data) # Add the numpy array to the queue
                            played_files.add(target_file) # Mark as played/queued
                            last_file_added = target_file
                            file_index_to_play += 1 # Move to the next file index
                        else:
                             print(f"⚠️ Warning: File {os.path.basename(target_file)} is empty. Skipping.")

                    except Exception as e:
                        print(f"⚠️ Error reading/queuing {os.path.basename(target_file)}: {e}")
                        # Don't advance index if read fails, maybe retry later
                        time.sleep(0.5) # Wait before retrying list
                else:
                    # We are waiting for the next file index to appear
                    time.sleep(0.05) # Shorter sleep when waiting for new files

            else:
                # Not enough files yet compared to the index we want
                if available_files < block_delay:
                     print(f"⏳ Waiting for initial block delay ({available_files}/{block_delay} files)...")
                else:
                     # We have passed the initial delay but are waiting for new files
                     # print(f"⏳ Waiting for new block {file_index_to_play+1}...")
                     pass # Avoid printing too much when caught up
                time.sleep(0.2) # Longer sleep when waiting for files

            # Optional: Clean played_files set periodically to prevent infinite growth
            if len(played_files) > max_files * 2:
                 current_files_set = set(wav_files)
                 played_files.intersection_update(current_files_set) # Keep only existing files


        except Exception as e:
            print(f"⚠️ Error in playback_loader loop: {e}")
            time.sleep(1) # Wait longer after an unexpected error


def audio_callback(outdata, frames, time_info, status):
    """Pulls data from audio_queue and feeds it to sounddevice."""
    global current_block, block_offset

    if status:
        print(f"⚠️ Audio stream status: {status}")

    with playback_lock: # Ensure thread-safe access to globals
        try:
            # Calculate how many samples are needed for this callback
            samples_needed = frames
            samples_written = 0

            # Create output buffer for this callback
            output_buffer = np.zeros((frames, outdata.shape[1]), dtype=outdata.dtype) # Handle channels

            while samples_written < samples_needed:
                # Check if we need a new block
                if current_block is None or block_offset >= len(current_block):
                    try:
                        # Get the next block (NumPy array) from the queue
                        current_block = audio_queue.get_nowait()
                        block_offset = 0
                        # print(f"  -> Got block from queue, size: {len(current_block)}")
                    except queue.Empty:
                        # Queue is empty, cannot provide more data for this callback
                        print("⚠️ Audio queue underrun!")
                        # Fill remaining buffer with silence and exit loop
                        # output_buffer[samples_written:] = 0 # Already zeros
                        break # Exit the while loop

                # Determine how many samples to take from the current block
                samples_remaining_in_block = len(current_block) - block_offset
                samples_to_write_now = min(samples_needed - samples_written, samples_remaining_in_block)

                # Copy data from current_block to the output buffer
                # Handle potential mono block -> stereo output case
                block_data_segment = current_block[block_offset : block_offset + samples_to_write_now]
                if outdata.shape[1] == 1: # Mono output
                     output_buffer[samples_written : samples_written + samples_to_write_now, 0] = block_data_segment
                elif outdata.shape[1] == 2 and block_data_segment.ndim == 1: # Stereo output, mono block
                     output_buffer[samples_written : samples_written + samples_to_write_now, 0] = block_data_segment
                     output_buffer[samples_written : samples_written + samples_to_write_now, 1] = block_data_segment
                else: # Assume block channels match output channels
                     output_buffer[samples_written : samples_written + samples_to_write_now] = block_data_segment # Needs reshaping if block isn't (N, C)

                # Update counters
                samples_written += samples_to_write_now
                block_offset += samples_to_write_now

            # Write the potentially partially filled buffer to outdata
            outdata[:] = output_buffer

        except Exception as e:
            print(f"⚠️ Error in audio_callback: {e}")
            outdata[:] = 0 # Output silence on error

# --- Main Execution ---

def start_stream_processing(args):
    """Initializes and starts all components."""
    delete_all_wav_files()

    # --- Start Seedlink Client Thread ---
    try:
        client = WavDumpClient(args.server, args.network, args.station, args.channel, args.samplerate, args.taper)
        seedlink_thread = threading.Thread(target=client.run, daemon=True)
        seedlink_thread.start()
    except ConnectionError:
        print("❌ Exiting due to Seedlink connection failure.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error starting Seedlink client: {e}")
        sys.exit(1)


    # --- Start Playback Loader Thread ---
    loader_thread = threading.Thread(
        target=lambda: playback_loader(args.delay, args.max_files),
        daemon=True
    )
    loader_thread.start()

    # --- Wait for Initial Buffer ---
    print(f"⏳ Waiting for minimum buffer ({args.min_buffer}s)...")
    start_wait_time = time.monotonic()
    initial_buffer_samples = args.min_buffer * args.samplerate
    while True:
        # Estimate samples in queue (approximate)
        # A more accurate way would be to sum len(block) for blocks in queue
        queued_samples_approx = audio_queue.qsize() * args.blocksize # Rough estimate
        if queued_samples_approx >= initial_buffer_samples:
            print(f"✅ Buffer ready ({queued_samples_approx / args.samplerate:.1f}s approx). Starting playback...")
            break

        # Check if Seedlink client is still receiving data
        if time.monotonic() - client.last_data_time > 30: # No data for 30 seconds
             print("❌ No data received from Seedlink for 30 seconds. Exiting.")
             # Consider stopping threads more gracefully if needed
             sys.exit(1)

        # Check for timeout on initial buffering
        if time.monotonic() - start_wait_time > 60: # Timeout after 60 seconds
             print(f"❌ Timeout waiting for initial buffer ({args.min_buffer}s).")
             print("   Check Seedlink connection and stream activity.")
             sys.exit(1)

        print(f"   Buffering... ({queued_samples_approx / args.samplerate:.1f}s / {args.min_buffer}s approx)")
        time.sleep(0.5)


    # --- Start Audio Output Stream ---
    try:
        print(f"🎶 Starting audio output stream to device: '{args.device}'")
        with sd.OutputStream(
            samplerate=args.samplerate,
            channels=1, # Outputting mono for now, Max can handle duplication if needed
            callback=audio_callback,
            blocksize=args.blocksize,
            dtype='float32',
            device=args.device
        ):
            print("✅ Playback running. Press Control+C to stop.")
            while True:
                # Keep main thread alive while daemon threads run
                # Check if worker threads are still alive (optional)
                if not seedlink_thread.is_alive():
                    print("❌ Seedlink thread terminated unexpectedly.")
                    break
                if not loader_thread.is_alive():
                    print("❌ Playback loader thread terminated unexpectedly.")
                    break
                time.sleep(0.5)

    except sd.PortAudioError as e:
         print(f"❌ PortAudio Error starting output stream: {e}")
         print(f"   Check if device '{args.device}' is available and supports {args.samplerate} Hz.")
         # List devices if helpful
         # print("\nAvailable devices:")
         # print(sd.query_devices())
         sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error during playback: {e}")
        sys.exit(1)
    finally:
        print("\n Muting audio output (stream closed).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stream seismic data via Seedlink, save as WAV blocks, and play through an audio device.")

    # Seedlink arguments
    parser.add_argument('-s', '--server', default="rtserve.iris.washington.edu:18000", help="Seedlink server address and port (e.g., geofon.gfz-potsdam.de:18000)")
    parser.add_argument('-n', '--network', default="IU", help="Network code (e.g., IU, GE)")
    parser.add_argument('-st', '--station', default="ANMO", help="Station code (e.g., ANMO, CLLA)")
    parser.add_argument('-c', '--channel', default="BHZ", help="Channel code (e.g., BHZ, LHZ)")

    # Playback arguments
    parser.add_argument('-d', '--delay', type=int, default=10, help="Initial block delay before playback starts (number of blocks)")
    parser.add_argument('-dev', '--device', default=DEFAULT_DEVICE_NAME, help="Audio output device name (use 'python -m sounddevice' to list)")
    parser.add_argument('-sr', '--samplerate', type=int, default=DEFAULT_TARGET_FS, help="Target audio sample rate (Hz)")
    parser.add_argument('-bs', '--blocksize', type=int, default=DEFAULT_BLOCKSIZE, help="Audio processing block size (samples)")
    parser.add_argument('-buf', '--min_buffer', type=float, default=DEFAULT_MIN_QUEUE_SECONDS, help="Minimum seconds of audio to buffer before playback starts")

    # Processing arguments
    parser.add_argument('-t', '--taper', type=float, default=DEFAULT_TAPER_MS, help="Fade-in/out taper duration at block edges (milliseconds)")

    # File management arguments
    parser.add_argument('-mf', '--max_files', type=int, default=DEFAULT_MAX_WAV_FILES, help="Maximum number of temporary WAV files to keep")

    args = parser.parse_args()

    # Validate arguments
    if args.delay < 1:
        print("❌ Delay must be at least 1.")
        sys.exit(1)
    if args.taper < 0:
        print("❌ Taper duration cannot be negative.")
        sys.exit(1)

    print("--- Configuration ---")
    print(f"Seedlink Server: {args.server}")
    print(f"Stream:         {args.network}.{args.station}..{args.channel}")
    print(f"Output Device:  {args.device}")
    print(f"Sample Rate:    {args.samplerate} Hz")
    print(f"Block Size:     {args.blocksize} samples")
    print(f"Playback Delay: {args.delay} blocks")
    print(f"Min Buffer:     {args.min_buffer} s")
    print(f"Taper:          {args.taper} ms")
    print(f"Max Temp Files: {args.max_files}")
    print("---------------------")

    try:
        start_stream_processing(args)
    except KeyboardInterrupt:
        print("\n🛑 Manually stopped by user (KeyboardInterrupt).")
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")
    finally:
        print("👋 Exiting script.")
