import matplotlib.pyplot as plt
import numpy as np
from obspy.clients.seedlink.easyseedlink import EasySeedLinkClient
from collections import deque
import threading

# 📊 Plot-Datenpuffer
BUFFER_SIZE = 2000  # Anzahl der Samples im Plot
data_buffer = deque(maxlen=BUFFER_SIZE)

# 🔄 Matplotlib Live-Plot vorbereiten
plt.ion()
fig, ax = plt.subplots()
line, = ax.plot([], [], lw=1)
ax.set_ylim(-10000, 10000)
ax.set_xlim(0, BUFFER_SIZE)
ax.set_title("Live Seismogramm: A2.AGVN.00.HHE")
ax.set_xlabel("Samples")
ax.set_ylabel("Amplitude")

# 🧠 Client-Klasse
class PlotClient(EasySeedLinkClient):
    def on_data(self, trace):
        global data_buffer
        data_buffer.extend(trace.data)
        print(f"📡 {trace.id} | {len(trace.data)} samples")

# 🔄 Plot-Updater
def update_plot():
    while True:
        if len(data_buffer) > 0:
            ydata = list(data_buffer)
            line.set_ydata(ydata)
            line.set_xdata(np.arange(len(ydata)))
            ax.set_ylim(min(ydata)-100, max(ydata)+100)
            ax.set_xlim(0, len(ydata))
            fig.canvas.draw()
            fig.canvas.flush_events()

# 🎬 Plot-Thread starten
plot_thread = threading.Thread(target=update_plot, daemon=True)
plot_thread.start()

# 📡 SeedLink-Client starten
client = PlotClient("rtserve.iris.washington.edu:18000")
client.select_stream("A2", "AGVN", "HHE")
print("🌐 Verbunden mit SeedLink – starte Datenstream...")
client.run()
