# Nexus

Nexus is a Windows desktop note application with manual speech-to-text.

Press the Speak button when you want to dictate. Nexus uses the local
Faster-Whisper speech recognition engine to convert your speech into text.

## Requirements

- Windows 10 or Windows 11
- Python 3.11 (64-bit)
- Internet connection for installation and the first Whisper model download
- A microphone for speech-to-text

## Installation

1. Install Python 3.11 (64-bit) if it is not already installed.
2. https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe and tick Add Python to PATH
3. Run `Install_Nexus_Speech.bat`.
4. Wait for the installation to finish. The first model download is
   approximately 1–2 GB.

## Starting Nexus

After installation, double-click `Start_Nexus.vbs` to start Nexus.

**Do not use `Start_Nexus.bat` for normal startup.** It can leave a
black Command Prompt window visible.

`Launch_Nexus.bat` is available for troubleshooting because it shows
console output.

## Speech recognition

Speech recognition is started manually using the Speak button.
Audio is processed locally using Faster-Whisper.

After the Whisper model has been downloaded, speech recognition can
run without an internet connection.

## Included files

- `note.py` – main application
- `speech_engine.py` – local speech recognition
- `Install_Nexus_Speech.bat` – installation script
- `Start_Nexus.vbs` – normal application launcher
- `Start_Nexus.bat` – console-based launcher
- `Launch_Nexus.bat` – troubleshooting launcher
- `note_data.json` – local note data
- `wolf.png` and `wolf1.png` – application images
- `Cara-Delevingne-Voice-open.mp3` and `Cara-Delevingne-Voice-closed.mp3` – application sounds

## Notes

The virtual environment and downloaded speech-recognition model are
created locally and are not included in this repository.
