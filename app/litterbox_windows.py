"""Find, focus, arrange, and restore the editor and owned game windows..."""
import ctypes as c
from ctypes import wintypes as w
import os

class WindowPlacement(c.Structure):
    _fields_ = [
        ('length', w.UINT), ('flags', w.UINT), ('show', w.UINT),
        ('minimum', w.POINT), ('maximum', w.POINT), ('normal', w.RECT)
    ]

def game_display_details(pid):
    if os.name != 'nt':
        return None

    user = c.WinDLL('user32', use_last_error=True)
    callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    user.EnumWindows.argtypes = [callback_type, w.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
    user.IsWindowVisible.argtypes = [w.HWND]
    user.GetClientRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
    user.MonitorFromWindow.argtypes = [w.HWND, w.DWORD]
    user.MonitorFromWindow.restype = w.HANDLE

    class MonitorInfo(c.Structure):
        _fields_ = [('size', w.DWORD), ('monitor', w.RECT), ('work', w.RECT), ('flags', w.DWORD)]

    user.GetMonitorInfoW.argtypes = [w.HANDLE, c.POINTER(MonitorInfo)]
    windows = []

    @callback_type
    def visit(hwnd, _):
        owner = w.DWORD()
        user.GetWindowThreadProcessId(hwnd, c.byref(owner))

        if owner.value == pid and user.IsWindowVisible(hwnd):
            windows.append(hwnd)

        return True

    user.EnumWindows(visit, 0)

    if not windows:
        return None

    client = w.RECT()
    info = MonitorInfo()
    info.size = c.sizeof(info)

    if not user.GetClientRect(windows[0], c.byref(client)) or not user.GetMonitorInfoW(user.MonitorFromWindow(windows[0], 2), c.byref(info)):
        return None

    return {
        'hwnd': windows[0], 'client_size': (client.right - client.left, client.bottom - client.top),
        'monitor_size': (info.monitor.right - info.monitor.left, info.monitor.bottom - info.monitor.top)
    }

def focus_playtest(pid):
    details = game_display_details(pid)

    if details:
        user = c.WinDLL('user32', use_last_error=True)
        kernel = c.WinDLL('kernel32')
        kernel.GetCurrentThreadId.restype = w.DWORD
        user.SetForegroundWindow.argtypes = [w.HWND]
        user.GetForegroundWindow.restype = w.HWND
        user.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
        user.AttachThreadInput.argtypes = [w.DWORD, w.DWORD, w.BOOL]
        user.BringWindowToTop.argtypes = [w.HWND]
        user.SetFocus.argtypes = [w.HWND]
        user.SetFocus.restype = w.HWND
        current = kernel.GetCurrentThreadId()
        attached = []
        threads = {
            user.GetWindowThreadProcessId(user.GetForegroundWindow(), None),
            user.GetWindowThreadProcessId(details['hwnd'], None)
        }

        try:
            for thread in threads:
                if thread and thread != current and user.AttachThreadInput(current, thread, True):
                    attached.append(thread)

            user.BringWindowToTop(details['hwnd'])
            user.SetForegroundWindow(details['hwnd'])
            user.SetFocus(details['hwnd'])

            return user.GetForegroundWindow() == details['hwnd']
        finally:
            for thread in reversed(attached):
                user.AttachThreadInput(current, thread, False)

    return False

def restore_playtest(root):
    snapshot = getattr(root, '_litterbox_window_layout', None)

    if snapshot is None or os.name != 'nt':
        return

    user = c.WinDLL('user32', use_last_error=True)
    user.SetWindowPlacement.argtypes = [w.HWND, c.POINTER(WindowPlacement)]
    user.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
    root.minsize(*snapshot['minimum'])
    user.SetWindowPlacement(snapshot['editor'], c.byref(snapshot['editor_placement']))
    owner = w.DWORD()
    user.GetWindowThreadProcessId(snapshot['game'], c.byref(owner))

    if owner.value == snapshot['pid']:
        user.SetWindowPlacement(snapshot['game'], c.byref(snapshot['game_placement']))

    del root._litterbox_window_layout

    if hasattr(root, '_litterbox_normal_minimum'):
        del root._litterbox_normal_minimum

def split_work_area(rect, editor_minimum=None):
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    editor_width = width // 2
    return (left, top, editor_width, height), (left + editor_width, top, width - editor_width, height)

def arrange_playtest(root, pid):
    """Split screen between the editor and game!"""

    if os.name != 'nt':
        return False

    user = c.WinDLL('user32', use_last_error=True)
    callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    user.EnumWindows.argtypes = [callback_type, w.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
    user.IsWindowVisible.argtypes = [w.HWND]
    user.IsWindowVisible.restype = w.BOOL
    user.GetAncestor.argtypes = [w.HWND, w.UINT]
    user.GetAncestor.restype = w.HWND
    user.GetWindowRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
    user.GetClientRect.argtypes = [w.HWND, c.POINTER(w.RECT)]
    user.MonitorFromWindow.argtypes = [w.HWND, w.DWORD]
    user.MonitorFromWindow.restype = w.HANDLE
    user.ShowWindow.argtypes = [w.HWND, c.c_int]
    user.SetWindowPos.argtypes = [w.HWND, w.HWND, c.c_int, c.c_int, c.c_int, c.c_int, w.UINT]
    user.SetWindowPos.restype = w.BOOL

    class MonitorInfo(c.Structure):
        _fields_ = [('size', w.DWORD), ('monitor', w.RECT), ('work', w.RECT), ('flags', w.DWORD)]

    user.GetMonitorInfoW.argtypes = [w.HANDLE, c.POINTER(MonitorInfo)]
    windows = []

    @callback_type
    def visit(hwnd, _):
        owner = w.DWORD()
        user.GetWindowThreadProcessId(hwnd, c.byref(owner))

        if owner.value == pid and user.IsWindowVisible(hwnd):
            windows.append(hwnd)

        return True

    user.EnumWindows(visit, 0)

    if not windows:
        return False

    editor = user.GetAncestor(root.winfo_id(), 2)
    snapshot = getattr(root, '_litterbox_window_layout', None)

    if snapshot is not None and snapshot['pid'] != pid:
        restore_playtest(root)
        snapshot = None

    if snapshot is None:
        user.GetWindowPlacement.argtypes = [w.HWND, c.POINTER(WindowPlacement)]
        editor_placement = WindowPlacement()
        editor_placement.length = c.sizeof(WindowPlacement)
        game_placement = WindowPlacement()
        game_placement.length = c.sizeof(WindowPlacement)

        if not user.GetWindowPlacement(editor, c.byref(editor_placement)) or not user.GetWindowPlacement(windows[0], c.byref(game_placement)):
            return False

        root._litterbox_window_layout = {
            'pid': pid, 'editor': editor, 'game': windows[0],
            'minimum': root.minsize(), 'editor_placement': editor_placement,
            'game_placement': game_placement
        }

    user.ShowWindow(editor, 9)
    user.ShowWindow(windows[0], 9)
    monitor = user.MonitorFromWindow(editor, 2)
    info = MonitorInfo()
    info.size = c.sizeof(info)

    if not user.GetMonitorInfoW(monitor, c.byref(info)):
        return False

    rect = info.work
    outer = w.RECT()
    client = w.RECT()
    user.GetWindowRect(editor, c.byref(outer))
    user.GetClientRect(editor, c.byref(client))
    chrome = max(0, (outer.right - outer.left) - (client.right - client.left))
    left, right = split_work_area((rect.left, rect.top, rect.right, rect.bottom))

    # (Allow proper half screen even if editor minimum is wider...)
    if not hasattr(root, '_litterbox_normal_minimum'):
        root._litterbox_normal_minimum = root.minsize()

    root.minsize(min(root._litterbox_normal_minimum[0], max(1, left[2] - chrome)), min(root._litterbox_normal_minimum[1], left[3] - 40))

    return bool(user.SetWindowPos(editor, None, *left, 0x14) and user.SetWindowPos(windows[0], None, *right, 0x14))