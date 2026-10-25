"""Register global Windows hotkeys, queue key events, tap/hold playtest actions..."""
import ctypes as c
from ctypes import wintypes as w
import queue
import threading
import time

class PressOrHold:
    def __init__(self):
        self.started = None
        self.consumed = False

    def begin(self, when):
        if self.started is None:
            self.started = when
            self.consumed = False

    def sample(self, down, when):
        if self.started is None:
            return None

        action = None

        if not self.consumed:
            if when - self.started >= 1.0:
                action = 'stop'
                self.consumed = True
            elif not down:
                action = 'hotload'

        if not down:
            self.started = None
            self.consumed = False

        return action

class PlaytestHotkey:
    def __init__(self, key=0x75):
        self.key = key
        self.gesture = PressOrHold()
        self.events = queue.Queue()
        self.ready = threading.Event()
        self.thread_id = None
        self.error = None
        self.user = c.WinDLL('user32', use_last_error=True)
        self.user.RegisterHotKey.argtypes = [w.HWND, c.c_int, w.UINT, w.UINT]
        self.user.UnregisterHotKey.argtypes = [w.HWND, c.c_int]
        self.user.GetMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT]
        self.user.GetMessageW.restype = c.c_int
        self.user.PeekMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
        self.user.PostThreadMessageW.argtypes = [w.DWORD, w.UINT, w.WPARAM, w.LPARAM]
        self.user.GetAsyncKeyState.argtypes = [c.c_int]
        self.user.GetAsyncKeyState.restype = c.c_short
        self.thread = threading.Thread(target=self.listen, args=(key,), name='Playtest F6', daemon=True)
        self.thread.start()
        self.ready.wait()

        if self.error is not None:
            self.thread.join()
            raise self.error

    def listen(self, key):
        kernel = c.WinDLL('kernel32')
        kernel.GetCurrentThreadId.restype = w.DWORD
        self.thread_id = kernel.GetCurrentThreadId()
        message = w.MSG()
        self.user.PeekMessageW(c.byref(message), None, 0, 0, 0)
        registered = self.user.RegisterHotKey(None, 1, 0x4000, key) # (No repeats while held)...

        if not registered:
            self.error = c.WinError(c.get_last_error())

        self.ready.set()

        if not registered:
            return

        try:
            while self.user.GetMessageW(c.byref(message), None, 0, 0) > 0:
                if message.message == 0x312 and message.wParam == 1:
                    self.events.put(time.monotonic())
        finally:
            self.user.UnregisterHotKey(None, 1)

    def key_down(self):
        return bool(self.user.GetAsyncKeyState(self.key) & 0x8000)

    def action(self):
        while True:
            try:
                self.gesture.begin(self.events.get_nowait())
            except queue.Empty:
                break

        return self.gesture.sample(self.key_down(), time.monotonic())

    def close(self):
        if self.thread.is_alive():
            self.user.PostThreadMessageW(self.thread_id, 0x12, 0, 0)
            self.thread.join(timeout=2)