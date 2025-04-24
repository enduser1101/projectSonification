# projectSonification


## Prerequisites

Go to the folder "...projectSonification/Stream/", install and activate python virtual environment:
```
cd ...projectSonification/Stream/
python3 -m venv venv

source venv/bin/activate
```

Install required packages:
```
pip install -r requirements.txt
```

Install "Blackhole 64" either by downloading it from the BlackHole Github page (https://github.com/ExistentialAudio/BlackHole) or use Homebrew to install it in the command line:
```
brew install blackhole-64ch
```

Install Max (https://cycling74.com/downloads).


## HOW TO USE
### Concept
The Python script connects to a SEEDLink server from which blocks of data are received. These blocks are converted and saved to WAV files in a folder. Old blocks are deleted regularly. The blocks are then streamed through "Blackhole 64ch" and can be received in MaxMSP or anywhere else for further processing --> sonification. To compensate for the instability of received data, the audio stream is delayed. Depending on your settings, this means that the audio stream will take a while to start after running the script. You can use two other Python scripts to get information about available stations and get status information for the currently running stream.

### Get info on available stations
Go to Terminal, change directory to "...projectSonification/Stream/", activate python virtual environment and use another Python script to view the contents of "stations.json" and get information about available stations.
```
cd ...projectSonification/Stream/
source venv/bin/activate
python stationmonitor1.3.py
```
Manually stop script by pressing "control + c"

### Run the stream
Go to another Terminal tab or window, change directory to "...projectSonification/Stream/" (if you're not already there), activate python virtual environment (if it's not already activated) and run the Python script. Use the argument "--station xx" to choose a station from the list in "stations.json".
```
cd ...projectSonification/Stream/
source venv/bin/activate
python streamplayer3.py --station 01
```
Manually stop script by pressing "control + c"

Use "--help" to see command line arguments for this script.
```
python streamplayer3.py --help
```

### See status information for currently running stream
Go to yet another Terminal tab or window, change directory to "...projectSonification/Stream/" (if you're not already there), activate python virtual environment (if it's not already activated) and run the Python script.
```
cd ...projectSonification/Stream/
source venv/bin/activate
python statusviewer.py
```

### Receive audio in Max
Open the included Max patch "monitor.maxpat" which is located in "projectSonification/Stream/wav_blocks". In the Max menu bar, go to "Options" --> "Audio Status" and choose "BlackHole 64" as input device. Make sure audio is turned on in Max. If the Python script is connected to a SEEDLink station, you should be receiving the audio stream in Max now. You can also view "stations.json" and "status.json" in the Max patch.



