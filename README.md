# Traptanium Speaker
streams system audio through the skylanders trap team portal speaker over usb, no game needed

---

## what's this
so the trap team portal is the only skylanders portal that actually has a speaker in it. the game uses it to play villain voices out of the portal itself which is pretty cool. this just lets you pipe whatever's playing on your pc straight through it in real time.

audio is captured from a virtual cable (VB-Cable), resampled to 8000hz mono, and streamed to the portal in 64-byte chunks. the led ring also reacts to volume levels while it's playing.

---

## requirements

you need the trap team portal specifically (the traptanium one). spyro's adventure, giants, superchargers etc don't have speakers so they won't work.

- python 3.10+
- [VB-Cable](https://vb-audio.com/Cable/) - set it as your default playback device so the script can capture it
- [libusb](https://libusb.info/) - place `libusb-1.0.dll` at `~\AppData\Local\Programs\Python\Python311\Lib\site-packages\libusb\_platform\windows\x86_64\libusb-1.0.dll` or update the path in the script

```
pip install -r requirements.txt
```

---

## files

| file | what it does |
|---|---|
| `portal_speaker.py` | captures system audio and streams it to the portal in real time |
| `requirements.txt` | dependencies |

---

## how to use

**step 1 - set up audio routing**

install VB-Cable and set "CABLE Input" as your default playback device in windows sound settings. whatever plays on your pc will then get captured by the script.

**step 2 - plug in the portal and run**

```
python portal_speaker.py
```

optional flags:

| flag | what it does |
|---|---|
| `--v 0.8` | volume multiplier, default is `0.5` |
| `--dev N` | use a specific audio input device by index |
| `--no-viz` | disable the led volume visualizer |
| `--dur 30` | stop after N seconds |
| `--list` | list available WASAPI input devices and exit |

---

## how it works

the portal is a usb hid device (vid `0x1430`, pid `0x0150`, same across all skylanders portals). you send 32-byte command packets over the control or out endpoint where the first byte is an ascii command character.

to play audio you:

1. send `R` to wake it up and wait for a response
2. send `A 01` to activate the portal
3. send `M 01` to turn the speaker on
4. stream 64-byte raw 16-bit mono 8000hz pcm chunks continuously
5. send `M 00` and `A 00` when done

the led ring responds to `C r g b` commands (0–255 each). the script uses this to show a volume visualizer - blue at silence, green at low volume, yellow at medium, red when loud.

audio from VB-Cable gets resampled from whatever sample rate your system uses down to 8000hz using `resample_poly`, then scaled and clipped before being packed as int16 and chunked.

---

## credits

marijn kneppers did all the reverse engineering - seriously go read his writeup, it's really good

- writeup: https://marijnkneppers.dev/posts/reverse-engineering-skylanders-toys-to-life-mechanics/
- his c# implementation: https://github.com/mandar1jn/SkylandersToolkit
- wireshark dissector: https://github.com/pop-emu/portal-dissector

---

## notes

- built for windows, linux/mac untested
- if the portal isn't detected, make sure the skylanders game isn't running - it holds onto the usb handle
- if you get loud noise instead of audio, try adjusting the volume with `--v` or check that VB-Cable is set as the default device
- a background thread drains incoming usb packets continuously to prevent the portal's buffer from backing up
