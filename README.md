# projectSonification


## Prerequisites

Install and activate python virtual environment with
```
python3 -m venv venv

source venv/bin/activate
```

Install required packages:
```
pip install -r requirements.txt
```

Install Blackhole https://github.com/ExistentialAudio/BlackHole
```
brew install blackhole-64ch
```


## HOW TO USE
### Concept
The Python script connects to a SEEDLink stream from which blocks of data are received. These blocks are converted and saved to WAV files. Old blocks are deleted regularly. The blocks are then played through Blackhole 64ch and can be received in MaxMSP or anywhere else for further processing --> sonification.


### Run script
Go to Terminal, change directory to ...projectSonification/Stream/, activate python virtual environment and run the Python script.
```
cd ...projectSonification/Stream/
source venv/bin/activate
python streamplayer18.py --station 01
```
Manually stop script by pressing "control + c"

Use --help to see command line arguments for this script.
```
python streamplayer3.py --help
```

Use the argument --station to choose a SEEDLink server from stations.json
```
python streamplayer18.py --station 03
```


