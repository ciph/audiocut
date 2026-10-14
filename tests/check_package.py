"""Smoke-test the Windows EXE with a silent fixture and close its own window."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import wave

root = Path(__file__).resolve().parents[1]
executable = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root / "dist" / "AudioCut" / "AudioCut.exe"
fixture = root / "tests" / ("package-silence-" + uuid.uuid4().hex + ".wav")
with wave.open(str(fixture), "wb") as audio:
    audio.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
    audio.writeframes(bytes(48000 * 2 * 2))
startup = subprocess.STARTUPINFO()
startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
startup.wShowWindow = 0
env = os.environ.copy()
env.pop("QT_QPA_PLATFORM", None)
process = subprocess.Popen([str(executable), str(fixture)],
                           startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW, env=env)
user32 = ctypes.windll.user32
callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.SendMessageW.restype = ctypes.c_ssize_t
owned = []

@callback_type
def inspect(hwnd, context):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == process.pid:
        title = ctypes.create_unicode_buffer(1024)
        user32.GetWindowTextW(hwnd, title, len(title))
        if title.value:
            owned.append((hwnd, title.value))
    return True

try:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        owned.clear()
        user32.EnumWindows(inspect, 0)
        if any(fixture.name in title for _, title in owned):
            break
        if process.poll() is not None:
            raise RuntimeError(f"EXE exited early: {process.returncode}")
        time.sleep(0.1)
    else:
        details = []
        @callback_type
        def read_child(hwnd, context):
            text = ctypes.create_unicode_buffer(16000)
            user32.SendMessageW(hwnd, 0x000D, len(text), ctypes.addressof(text))
            if text.value:
                details.append(text.value)
            return True
        for hwnd, title in owned:
            if "exception" in title:
                user32.EnumChildWindows(hwnd, read_child, 0)
        raise RuntimeError(f"EXE failed to load audio: {owned}; details={details}")
    print("Packaged EXE created a native window and loaded the command-line WAV.")
    # The title appears before loading finishes; a busy window ignores close.
    deadline = time.monotonic() + 20
    while process.poll() is None and time.monotonic() < deadline:
        owned.clear()
        user32.EnumWindows(inspect, 0)
        for hwnd, title in owned:
            if fixture.name in title:
                user32.PostMessageW(hwnd, 0x0010, 0, 0)
        time.sleep(0.2)
    assert process.wait(timeout=1) == 0
    print("Packaged EXE closed cleanly with exit code 0.")
finally:
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=5)
    fixture.unlink(missing_ok=True)
