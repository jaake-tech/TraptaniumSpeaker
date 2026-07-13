import sys, os, time, threading, queue, argparse
import sounddevice as sd
import numpy as np
from scipy.signal import resample_poly
from math import gcd
import usb.backend.libusb1

_backend = usb.backend.libusb1.get_backend(find_library=lambda x: os.path.expanduser(
    r'~\AppData\Local\Programs\Python\Python311\Lib\site-packages\libusb\_platform\windows\x86_64\libusb-1.0.dll'))
import usb.core, usb.util

VID, PID = 0x1430, 0x0150
CHUNK, RATE = 64, 8000
CMD_SZ = 32
CMD_R, CMD_A, CMD_M, CMD_C = ord('R'), ord('A'), ord('M'), ord('C')
CTRL = 0x21

class Portal:
    def __init__(self, dev, ep_in, iface, ep_out=None):
        self.dev = dev; self.ep_in = ep_in; self.ep_out = ep_out; self.iface = iface
    def cmd(self, p, t=1000):
        try: self.dev.ctrl_transfer(CTRL, 0x09, 0x0200, self.iface, p, timeout=t)
        except usb.core.USBError as e: raise IOError(f"cmd: {e}")
    def write(self, p, t=1000):
        try:
            if self.ep_out: self.ep_out.write(p, timeout=t)
            else: self.cmd(p, t)
        except usb.core.USBError as e: raise IOError(f"write: {e}")
    def read(self, t=100):
        try: return bytes(self.ep_in.read(self.ep_in.wMaxPacketSize, timeout=t)) or None
        except: return None
    def close(self):
        try: usb.util.dispose_resources(self.dev)
        except: pass

def pkt(*b):
    buf = bytearray(CMD_SZ)
    for i, v in enumerate(b):
        if i < CMD_SZ: buf[i] = v & 0xFF
    return bytes(buf)

def resp(p, exp, t=1000):
    deadline = time.monotonic() + t / 1000
    while time.monotonic() < deadline:
        r = p.read(max(1, int((deadline - time.monotonic()) * 1000)))
        if r and r[0] == exp: return r

def ready(p):
    p.cmd(pkt(CMD_R))
    if not resp(p, CMD_R): raise IOError("no response")

def activate(p, on=True):
    p.cmd(pkt(CMD_A, 0x01 if on else 0x00))
    return resp(p, CMD_A)

def music(p, on=True):
    p.cmd(pkt(CMD_M, 0x01 if on else 0x00))
    return resp(p, CMD_M, 2000)

def color(p, r, g, b):
    p.cmd(pkt(CMD_C, r, g, b))

def open_portal():
    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=_backend)
    if not dev: raise IOError("Portal not found")
    try: dev.set_configuration()
    except: pass
    intf = dev.get_active_configuration()[(0, 0)]
    try: usb.util.claim_interface(dev, intf.bInterfaceNumber)
    except: pass
    ep_in = usb.util.find_descriptor(intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN)
    ep_out = usb.util.find_descriptor(intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
    if not ep_in: raise IOError("no IN endpoint")
    return Portal(dev, ep_in, intf.bInterfaceNumber, ep_out)

class Drainer:
    def __init__(self, p):
        self.p = p; self._s = threading.Event(); self._t = threading.Thread(target=self._run, daemon=True)
    def start(self): self._t.start()
    def stop(self): self._s.set(); self._t.join(1)
    def _run(self):
        while not self._s.is_set():
            try: self.p.read(20)
            except: break
            time.sleep(0.005)

def find_cable():
    for i, dev in enumerate(sd.query_devices()):
        if 'cable output' in dev['name'].lower() and dev['max_input_channels'] > 0:
            return i
    return None

class SystemAudio:
    def __init__(self, p, dev_id=None, vol=0.5, viz=True):
        self.p = p; self.dev_id = dev_id; self.vol = vol; self.viz = viz
        self.running = False; self.q = queue.Queue(30)
        self.d = Drainer(p)

    def _cb(self, indata, frames, time_info, status):
        if indata.shape[1] > 1: mono = indata.mean(axis=1)
        else: mono = indata.flatten()
        self.q.put(mono.copy())

    def run(self, dur=None):
        if self.dev_id is None: self.dev_id = find_cable()
        if self.dev_id is None: print("VB-Cable not found"); return
        info = sd.query_devices(self.dev_id)
        sr = int(info['default_samplerate'])
        ch = min(2, info['max_input_channels'])
        if ch == 0: ch = 2
        g = gcd(sr, RATE)
        up, down = RATE // g, sr // g
        self.running = True; self.d.start()
        color(self.p, 0, 100, 255)
        try:
            with sd.InputStream(samplerate=sr, device=self.dev_id, channels=ch,
                                blocksize=int(sr * 0.05), callback=self._cb, dtype='float32'):
                start = time.monotonic(); viz_c = 0
                while self.running:
                    if dur and time.monotonic() - start >= dur: break
                    try: blk = self.q.get(timeout=0.5)
                    except queue.Empty: continue
                    rs = resample_poly(blk, up, down)
                    rs = np.clip(rs * self.vol * 0.3, -1.0, 1.0)
                    raw = (rs * 32767).astype(np.int16).tobytes()
                    off = 0
                    while off < len(raw):
                        c = raw[off:off + CHUNK]
                        if len(c) < CHUNK: c += bytes(CHUNK - len(c))
                        try: self.p.write(c, 100)
                        except: self.running = False; break
                        off += CHUNK
                    viz_c += 1
                    if self.viz and viz_c % 4 == 0:
                        rms = float(np.sqrt(np.mean(blk**2)))
                        if rms < 0.01: color(self.p, 0, int(30 * rms / 0.01), int(80 * (1 - rms / 0.01)))
                        elif rms < 0.05: color(self.p, 0, int(255 * (rms - 0.01) / 0.04), 0)
                        elif rms < 0.15: color(self.p, int(200 * (rms - 0.05) / 0.1), 255, 0)
                        else: color(self.p, 255, max(0, int(255 * (1 - (rms - 0.15) / 0.85))), 0)
        except sd.PortAudioError as e: print(f"audio err: {e}")
        except KeyboardInterrupt: pass
        finally:
            self.running = False; self.d.stop()
            try: color(self.p, 0, 0, 0); music(self.p, False); activate(self.p, False)
            except: pass

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--v", type=float, default=0.5)
    ap.add_argument("--dev", type=int)
    ap.add_argument("--no-viz", action="store_true")
    ap.add_argument("--dur", type=float)
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, dev in enumerate(sd.query_devices()):
            if dev['max_output_channels'] > 0 and 'wasapi' in sd.query_hostapis(dev['hostapi'])['name'].lower():
                print(f"  [{i}] {dev['name']}")
        sys.exit(0)
    p = open_portal()
    try:
        for _ in range(20):
            if p.read(20) is None: break
        ready(p); activate(p, True); music(p, True)
        s = SystemAudio(p, dev_id=a.dev, vol=a.v, viz=not a.no_viz)
        s.run(dur=a.dur)
    except KeyboardInterrupt: pass
    finally:
        try: color(p, 0, 0, 0); music(p, False); activate(p, False)
        except: pass
        p.close()
