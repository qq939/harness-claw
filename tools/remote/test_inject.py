import ctypes
import json
import os
import struct
import subprocess
import sys
import time
from ctypes import wintypes

u = ctypes.windll.user32


class P(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


def pos():
    p = P()
    u.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


here = os.path.dirname(os.path.abspath(__file__))
relay = os.path.join(here, "pipe_relay.py")
before = pos()
p = subprocess.Popen([sys.executable, relay], stdin=subprocess.PIPE,
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
line = p.stdout.readline()
print("relay:", line.decode(errors="replace").strip())
for _ in range(10):
    payload = json.dumps({"t": "m", "dx": 10, "dy": 5}).encode()
    p.stdin.write(struct.pack(">I", len(payload)) + payload)
    p.stdin.flush()
    time.sleep(0.02)
time.sleep(0.2)
p.stdin.close()
p.wait(timeout=5)
after = pos()
print("cursor before:", before)
print("cursor after :", after)
print("delta        :", (after[0] - before[0], after[1] - before[1]))
