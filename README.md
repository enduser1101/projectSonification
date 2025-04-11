# projectSonification


## Prerequisites

Install and activate python virtual environment with
```
python3 -m venv venv
. venv/bin/activate
```

Install required packages:
```
pip install -r requirements.txt
```

Install Blackhole https://github.com/ExistentialAudio/BlackHole
```
brew install blackhole-64ch
```

## Prototyping

Run jupyter notebook with
```
jupyter lab Stream/
```

## HOW TO USE
# Concept
The Python script connects to a SEEDLink stream from which blocks of data are received. These blocks are converted and saved to WAV files. Old blocks are deleted regularly. The blocks are then played through Blackhole 64ch and can be received in MaxMSP or anywhere else for further processing --> sonification.


# Run script
Go to Terminal, change directory to ...projectSonification/Stream/ and run the Python script.
n = block delay (1-90)
Audio playback will not start until n blocks have been received and saved as WAV files. Set n according to the stream density.
```
cd ...projectSonification/Stream/
python3 stream_player.py n
```
Manually stop script by pressing "control + c"

