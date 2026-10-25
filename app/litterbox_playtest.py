"""Write preview files, launch and hook our game process, and manage hotloads and display commands..."""
from app.litterbox_language import tr
from pathlib import Path
import ctypes as c
from ctypes import wintypes as w
import json
import hashlib
import os
import struct
import subprocess
import threading
import re
from app.litterbox_dlls import DllPlaytestConfig

# Only use the game version these hooks were made for...
SUPPORTED_SHA256 = '4127cd6a792ae528bca6f65a8873dd61789591937d87656c2b586a5e30eb77ea'
_dll_cleanup_thread = None

def normal_display_settings(directory=None):
    directory = Path(directory) if directory else Path(os.environ.get('APPDATA', '')) / 'Glaiel Games/Mewgenics'
    files = [p for p in directory.glob('*/settings.txt') if p.parent.name.isdigit()]
    result = {'mode': 'borderless', 'width': -1, 'height': -1}

    if files:
        try:
            text = max(files, key=lambda p: p.stat().st_mtime_ns).read_text(encoding='utf-8-sig')
        except (OSError, UnicodeError):
            return result

        for field, key in [('screen_mode', 'mode'), ('window__width', 'width'), ('window_height', 'height')]:
            match = re.search(r'^\s*' + field + r'\s+"?([\w-]+)', text, re.M)

            if match:
                value = match.group(1)

                if key == 'mode':
                    if value in ('windowed', 'fullscreen', 'borderless'):
                        result[key] = value
                else:
                    try:
                        result[key] = int(value)
                    except ValueError:
                        pass

    return result

def frame_hook(image_base, remote, address, original):
    """Build main thread hook for hotloads and display changes..."""

    # Keep the original game code nearby so we can still run it...
    trampoline = address + 0x200
    # Save what the game was doing before running our extra code...
    code = bytearray.fromhex('53 48 83 ec 30 48 b8')
    # Run the original event handler and keep its result...
    code += struct.pack('<Q', trampoline) + bytes.fromhex('ff d0 89 44 24 28 48 bb') + struct.pack('<Q', remote)

    # Skip window changes unless the editor requested them...
    code += bytes.fromhex('83 bb 20 09 00 00 00 0f 84')
    skip = len(code)
    code += bytes(4)
    # Find the running game application...
    code += bytes.fromhex('48 b8') + struct.pack('<Q', image_base + 0x13c4a30)
    # Keep the application and game window handy for the display changes...
    code += bytes.fromhex('48 8b 00 48 89 83 38 09 00 00 48 8b 88 d0 0d 00 00 48 89 8b 30 09 00 00')

    def window_call(rva, arguments=''):
        # Ask the game to change its own window on its main thread...
        code.extend(bytes.fromhex('48 8b 8b 30 09 00 00 ' + arguments + ' 48 b8'))
        code.extend(struct.pack('<Q', image_base + rva))
        code.extend(bytes.fromhex('ff d0'))

    # Turn fullscreen on only for fullscreen requests...
    window_call(0xba8630, '31 d2 83 bb 20 09 00 00 02 0f 94 c2')
    # Remember whether the window change succeeded...
    code += bytes.fromhex('0f b6 c0 89 83 24 09 00 00')
    # Leave fullscreen sizing to the game...
    code += bytes.fromhex('83 bb 20 09 00 00 02 0f 84')
    fullscreen_skip = len(code)
    code += bytes(4)
    # Apply the requested window size...
    window_call(0xba8730, '8b 93 28 09 00 00 44 8b 83 2c 09 00 00')
    # Center the game window on screen...
    window_call(0xba86f0, 'ba 00 00 ff 2f 41 b8 00 00 ff 2f')

    # Show borders and allow resizing only in windowed mode...
    for rva in (0xba8710, 0xba8610):
        window_call(rva, '31 d2 83 bb 20 09 00 00 01 0f 94 c2')

    # Fill in where fullscreen requests should skip ahead to...
    struct.pack_into('<i', code, fullscreen_skip, len(code) - fullscreen_skip - 4)
    # Tell the game which display mode is now active...
    code += bytes.fromhex('48 8b 8b 38 09 00 00 8b 83 20 09 00 00 ff c8 89 81 f0 0d 00 00 48 b8')
    # Refresh the window size the game uses internally...
    code += struct.pack('<Q', image_base + 0x9b71d0) + bytes.fromhex('ff d0')
    # Bring the game window to the front...
    window_call(0xba7870)
    # Mark the window change as handled...
    code += bytes.fromhex('c7 83 20 09 00 00 00 00 00 00')
    struct.pack_into('<i', code, skip, len(code) - skip - 4)
    # If a reload was requested, mark it busy and prepare to rebuild the battle...
    code += bytes.fromhex('83 bb 10 09 00 00 01 75 1d c7 83 10 09 00 00 02 00 00 00 48 8b 8b 18 09 00 00 48 b8')
    # Reload the battle, then let the game carry on as before...
    code += struct.pack('<Q', remote) + bytes.fromhex('ff d0 8b 44 24 28 48 83 c4 30 5b c3')

    if len(code) > 0x200:
        raise ValueError(tr('display_hook_too_large'))

    # Keep a copy of the replaced instructions so the original game function still works...
    return bytes(code) + bytes(0x200 - len(code)) + original + bytes.fromhex('ff2500000000') + struct.pack('<Q', image_base + 0x9b83fe)

class PlaytestSession:
    """Keep process handle so recycled PID cannot point at the friggin' game"""

    def __init__(self, pid, remote, staging, configuration):
        self.pid, self.remote, self.staging, self.configuration = pid, remote, Path(staging), configuration
        self.normal_display = normal_display_settings()
        self.k = c.WinDLL('kernel32', use_last_error=True)
        self.k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.k.OpenProcess.restype = w.HANDLE
        self.k.GetExitCodeProcess.argtypes = [w.HANDLE, c.POINTER(w.DWORD)]
        self.k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
        self.k.WriteProcessMemory.argtypes = self.k.ReadProcessMemory.argtypes
        self.k.CloseHandle.argtypes = [w.HANDLE]
        self.k.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
        # Get permission to read, update and stop our playtest process...
        self.handle = self.k.OpenProcess(0x1039, False, pid)

        if not self.handle:
            raise c.WinError(c.get_last_error())

        try:
            # Check that this really is our playtest process...
            if self.read(remote + 0x840, 18) != b'litterbox_preview\0':
                raise RuntimeError(tr('playtest_process_unverified'))
        except Exception:
            self.close()
            raise

    def alive(self):
        # Check whether the game is still running...
        status = w.DWORD()
        return bool(self.handle and self.k.GetExitCodeProcess(self.handle, c.byref(status)) and status.value == 259)

    def read(self, address, length):
        buf = c.create_string_buffer(length)
        done = c.c_size_t()

        if not self.k.ReadProcessMemory(self.handle, address, buf, length, c.byref(done)) or done.value != length:
            raise c.WinError(c.get_last_error())

        return buf.raw

    def ready(self):
        # Ready means our setup finished, the battle may still be loading...
        return self.alive() and self.read(self.remote + 0x910, 4) == struct.pack('<I', 3)

    def request_windowed(self):
        return self.request_display('windowed')

    def request_display(self, mode=None):
        from app.litterbox_windows import game_display_details
        details = game_display_details(self.pid)

        if details is None:
            return False

        if not hasattr(self, 'original_client_size'):
            self.original_client_size = details['client_size']

        mode = mode or self.normal_display['mode']

        if mode == 'borderless':
            width, height = details['monitor_size']
        else:
            width = self.normal_display['width']
            height = self.normal_display['height']

            if width <= 0 or height <= 0:
                width, height = self.original_client_size

        # Send the new window size before asking the game to apply it...
        data = c.create_string_buffer(struct.pack('<ii', width, height))
        done = c.c_size_t()

        if not self.k.WriteProcessMemory(self.handle, self.remote + 0x928, data, 8, c.byref(done)) or done.value != 8:
            raise c.WinError(c.get_last_error())

        self.write_command(0x920, {'windowed': 1, 'fullscreen': 2, 'borderless': 3}[mode])

        return True

    def windowed_ready(self):
        pending, success = struct.unpack('<II', self.read(self.remote + 0x920, 8))
        return pending == 0 and success != 0

    def write_command(self, offset, value):
        data = c.create_string_buffer(struct.pack('<I', value))
        done = c.c_size_t()

        if not self.k.WriteProcessMemory(self.handle, self.remote + offset, data, 4, c.byref(done)) or done.value != 4:
            raise c.WinError(c.get_last_error())

    def reload(self, level):
        if not self.ready():
            raise RuntimeError(tr('playtest_still_loading'))

        path = self.staging / 'levels/litterbox_preview.lvl'
        temporary = path.with_suffix('.tmp')
        temporary.write_bytes(level.encode())
        # Finish saving the preview before telling the game to reload it...
        os.replace(temporary, path)
        self.write_command(0x910, 1)

    def close(self, terminate=False):
        if self.handle:
            if terminate and self.alive():
                self.k.TerminateProcess(self.handle, 0)

            self.k.CloseHandle(self.handle)
            self.handle = None

    def __del__(self):
        if getattr(self, 'handle', None):
            self.close()

def bootstrap(image_base, remote_base, weather=()):
    """Build startup hook that sends the game straight into test battle..."""

    # Save the game state we need before running our battle setup...
    code = bytearray.fromhex('53 56 57 48 83 ec 60 48 89 cb')

    def emit(hexbytes):
        code.extend(bytes.fromhex(hexbytes))

    def call(rva):
        # Call an existing game function at its current memory address...
        emit('48 b8')
        code.extend(struct.pack('<Q', image_base + rva))
        emit('ff d0')

    # Enable the normal combat test settings and use act 1...
    emit('c6 83 8d 07 00 00 01 c6 83 80 07 00 00 01 c7 83 dc 06 00 00 01 00 00 00')

    # Remember the game director so we can reload later...
    emit('49 bb')
    code.extend(struct.pack('<Q', remote_base + 0x918))
    emit('49 89 1b')

    # Reset randomness the same way the game combat test does...
    emit('65 48 8b 04 25 58 00 00 00 48 8b 08 48 81 c1 78 01 00 00')
    call(0x94f0a0)

    def battle_string():
        # Write the Battle scene name in the format the game expects...
        emit('48 b8')
        code.extend(b'Battle\0\0')
        emit('48 89 44 24 20')
        emit('48 c7 44 24 28 00 00 00 00 48 c7 44 24 30 06 00 00 00 48 c7 44 24 38 0f 00 00 00')

    # Remove the previous Battle scene...
    battle_string()
    emit('48 8b 4b 28 48 8d 54 24 20')
    call(0x9d4e00)
    # Create the replacement Battle scene...
    battle_string()
    emit('48 8b 4b 28 48 8d 54 24 20')
    call(0x9d4950)
    # Get the scene object needed to start a combat test...
    emit('48 89 c6 48 89 c1')
    call(0x96b3e0)
    # Pass the scene object and our preview level name to the game...
    emit('48 89 c2 48 89 f1 49 b8')
    code.extend(struct.pack('<Q', remote_base + 0x800))
    # Start the combat test with our preview level...
    call(0x31e6e0)

    # Keep the combat-test object available...
    emit('49 bb')
    code.extend(struct.pack('<Q', remote_base + 0x900))
    emit('49 89 03')

    # Find and remember the battle state needed for weather...
    emit('48 8b c8')
    call(0x049630)
    emit('49 bb')
    code.extend(struct.pack('<Q', remote_base + 0x908))
    emit('49 89 03')

    if weather:
        # Skip weather setup if there is no battle state...
        emit('48 89 c3 48 85 c0 0f 84')
        skip = len(code)
        code.extend(bytes(4))
        # Start with the first weather effect in our list...
        emit('48 be')
        code.extend(struct.pack('<Q', remote_base + 0xa00))
        loop = len(code)

        # Give the game a copy of the weather name so hotloading can reuse the original...
        emit('48 8b d6 48 8d 4c 24 20')
        call(0x052460)
        # Enable this weather effect in the battle...
        emit('48 8d 54 24 20 48 8b cb 41 b8 01 00 00 00')
        call(0x8b0340)
        # Move to the next weather effect until the list ends...
        emit('48 83 c6 20 48 83 7e 10 00 0f 85')
        code.extend(struct.pack('<i', loop - (len(code) + 4)))
        struct.pack_into('<i', code, skip, len(code) - (skip + 4))

    emit('49 bb')
    # Tell the editor that battle setup is finished...
    code.extend(struct.pack('<Q', remote_base + 0x910))
    emit('41 c7 03 03 00 00 00')
    # Restore the saved game state and return to the game...
    emit('48 83 c4 60 5f 5e 5b c3')
    # Leave space between our instructions and the preview data...
    blob = code + bytes(0x800 - len(code))
    # Store the preview name separately because it's too long for the game's short string format...
    blob += struct.pack('<QQQQ', remote_base + 0x840, 0, 17, 17)
    blob += bytes(0x840 - len(blob)) + b'litterbox_preview\0'
    # Leave room for the editor and game to exchange requests...
    blob += bytes(0xa00 - len(blob))
    records = bytearray()
    strings = bytearray()
    # Keep weather names after the list of game strings...
    strings_start = remote_base + 0xa00 + 32 * (len(weather) + 1)

    for name in weather:
        encoded = name.encode('utf-8')

        # Short names fit inside the string itself...
        if len(encoded) <= 15:
            records += encoded + bytes(16 - len(encoded)) + struct.pack('<QQ', len(encoded), 15)
        else:
            # Long names need a separate text buffer...
            records += struct.pack('<QQQQ', strings_start + len(strings), 0, len(encoded), len(encoded))
            strings += encoded + b'\0'

    # Add an empty entry so the game knows where the weather list ends...
    blob += records + bytes(32) + strings
    # Leave the next memory page for the hotload hook...
    blob += bytes((-len(blob)) % 0x1000)

    return bytes(blob)

def mod_folder_path(profile):
    path = Path(profile.get('spawns') or profile.get('tiles')).parent
    return path.parent if path.name.lower() == 'data' else path

def prepare_preview(level, directory, tileset=None, weather=()):
    """Write current level and preview metadata into staging folder"""

    weather = validate_weather(weather)
    directory = Path(directory)
    (directory / 'levels').mkdir(parents=True, exist_ok=True)
    (directory / 'levels/litterbox_preview.lvl').write_bytes(level.encode())

    if tileset is not None:
        if not isinstance(tileset, str) or not tileset or any(ch in tileset for ch in '\r\n\x00'):
            raise ValueError(tr('invalid_tileset_name'))

        (directory / 'data').mkdir(exist_ok=True)
        (directory / 'data/tilesets.gon.patch').write_text('default_tileset.overwrite ' + json.dumps(tileset) + '\n', encoding='utf-8')

    (directory / 'preview_settings.json').write_text(json.dumps({'weather': weather}, indent=2), encoding='utf-8')

    return directory

def validate_weather(weather):
    if not isinstance(weather, (list, tuple)) or any(not isinstance(name, str) or not name or any(ch in name for ch in '\r\n\x00') for name in weather):
        raise ValueError(tr('invalid_playtest_weather_list'))

    return tuple(dict.fromkeys(weather))

def game_running():
    if os.name != 'nt':
        return False

    class PROCESSENTRY(c.Structure):
        _fields_ = [
            ('size', w.DWORD), ('usage', w.DWORD), ('pid', w.DWORD), ('heap', c.c_size_t),
            ('module', w.DWORD), ('threads', w.DWORD), ('parent', w.DWORD), ('priority', w.LONG),
            ('flags', w.DWORD), ('exe', w.WCHAR * 260)
        ]

    k = c.WinDLL('kernel32', use_last_error=True)
    k.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
    k.CreateToolhelp32Snapshot.restype = w.HANDLE
    k.Process32FirstW.argtypes = [w.HANDLE, c.POINTER(PROCESSENTRY)]
    k.Process32FirstW.restype = w.BOOL
    k.Process32NextW.argtypes = k.Process32FirstW.argtypes
    k.Process32NextW.restype = w.BOOL
    k.CloseHandle.argtypes = [w.HANDLE]
    # List running processes so we can spot an existing game session...
    snapshot = k.CreateToolhelp32Snapshot(2, 0)

    if snapshot == c.c_void_p(-1).value:
        raise c.WinError(c.get_last_error())

    entry = PROCESSENTRY()
    entry.size = c.sizeof(entry)

    try:
        more = k.Process32FirstW(snapshot, c.byref(entry))

        while more:
            if entry.exe.lower() == 'mewgenics.exe':
                return True

            more = k.Process32NextW(snapshot, c.byref(entry))

        return False
    finally:
        k.CloseHandle(snapshot)

def launch_arguments(exe, staging, mod_folder=None):
    # Use our startup hook and keep playtest saves separate from normal saves...
    args = [str(exe), '-dev_mode', 'true', '-screen_mode', 'windowed', '-savesuffix', 'litterbox_playtest', '-modpaths']

    if mod_folder:
        args.append(str(Path(mod_folder).resolve()))

    # Load preview last so level and tileset take priority...
    args.append(str(staging))

    return args

def launch(exe, staging, mod_folder=None):
    """Start game process and install playtest hooks"""

    global _dll_cleanup_thread
    exe = Path(exe).resolve()
    staging = Path(staging).resolve()

    if os.name != 'nt' or c.sizeof(c.c_void_p) != 8:
        raise RuntimeError(tr('playtest_requires_64bit'))

    if not exe.is_file():
        raise ValueError(tr('choose_mewgenics_exe_first'))

    if hashlib.sha256(exe.read_bytes()).hexdigest() != SUPPORTED_SHA256:
        raise ValueError(tr('unsupported_game_version'))

    if mod_folder and not Path(mod_folder).is_dir():
        raise ValueError(tr('mod_folder_missing'))

    if game_running():
        raise RuntimeError(tr('close_game_first'))

    if _dll_cleanup_thread is not None:
        _dll_cleanup_thread.join(timeout=5)

        if _dll_cleanup_thread.is_alive():
            raise RuntimeError(tr('playtest_still_closing'))

    if not (staging / 'levels/litterbox_preview.lvl').is_file():
        raise ValueError(tr('playtest_snapshot_missing'))

    settings_path = staging / 'preview_settings.json'
    settings = json.loads(settings_path.read_text(encoding='utf-8')) if settings_path.exists() else {}
    weather = validate_weather(settings.get('weather', ()))
    # Work out how much game memory our code and preview data need...
    payload_size = len(bootstrap(0, 0, weather)) + 0x1000
    args = launch_arguments(exe, staging, mod_folder)
    env = os.environ.copy()
    env.update(SteamAppId='686060', SteamGameId='686060')
    # Package launch environment in the format Windows expects...
    envblock = c.create_unicode_buffer('\0'.join(f'{k}={v}' for k, v in sorted(env.items())) + '\0\0')

    class STARTUPINFO(c.Structure):
        _fields_ = [
            ('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR), ('title', w.LPWSTR),
            ('x', w.DWORD), ('y', w.DWORD), ('xs', w.DWORD), ('ys', w.DWORD), ('xc', w.DWORD), ('yc', w.DWORD),
            ('fill', w.DWORD), ('flags', w.DWORD), ('show', w.WORD), ('reserved2count', w.WORD), ('reserved2', c.c_void_p),
            ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)
        ]

    class PROCESSINFO(c.Structure):
        _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]

    k = c.WinDLL('kernel32', use_last_error=True)
    nt = c.WinDLL('ntdll')
    # Tell Python the Windows argument types (so memory addresses stay intact)...
    k.CreateProcessW.argtypes = [w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p, w.BOOL, w.DWORD, c.c_void_p, w.LPCWSTR, c.POINTER(STARTUPINFO), c.POINTER(PROCESSINFO)]
    k.CreateProcessW.restype = w.BOOL
    k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
    k.ReadProcessMemory.restype = w.BOOL
    k.WriteProcessMemory.argtypes = k.ReadProcessMemory.argtypes
    k.WriteProcessMemory.restype = w.BOOL
    k.VirtualAllocEx.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t, w.DWORD, w.DWORD]
    k.VirtualAllocEx.restype = c.c_void_p
    k.VirtualProtectEx.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t, w.DWORD, c.POINTER(w.DWORD)]
    k.VirtualProtectEx.restype = w.BOOL
    k.FlushInstructionCache.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t]
    k.ResumeThread.argtypes = [w.HANDLE]
    k.ResumeThread.restype = w.DWORD
    k.CloseHandle.argtypes = [w.HANDLE]
    k.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
    nt.NtQueryInformationProcess.argtypes = [w.HANDLE, w.ULONG, c.c_void_p, w.ULONG, c.c_void_p]
    nt.NtQueryInformationProcess.restype = w.LONG
    si = STARTUPINFO()
    si.cb = c.sizeof(si)
    pi = PROCESSINFO()
    dll_config = DllPlaytestConfig(exe.parent, staging, mod_folder)
    watching = False

    try:
        # Start game paused so we can install our hooks before it runs...
        if not k.CreateProcessW(str(exe), c.create_unicode_buffer(subprocess.list2cmdline(args)), None, None, False, 0x404, envblock, str(exe.parent), c.byref(si), c.byref(pi)):
            raise c.WinError(c.get_last_error())
    except Exception:
        dll_config.restore()
        raise

    def read(address, length):
        buf = c.create_string_buffer(length)
        done = c.c_size_t()

        if not k.ReadProcessMemory(pi.process, address, buf, length, c.byref(done)) or done.value != length:
            raise c.WinError(c.get_last_error())

        return buf.raw

    def write(address, data):
        buf = c.create_string_buffer(data)
        done = c.c_size_t()

        if not k.WriteProcessMemory(pi.process, address, buf, len(data), c.byref(done)) or done.value != len(data):
            raise c.WinError(c.get_last_error())

    try:
        # Ask Windows where the game process keeps its startup information...
        info = (c.c_ulonglong * 6)()

        if nt.NtQueryInformationProcess(pi.process, 0, info, c.sizeof(info), None) != 0:
            raise RuntimeError(tr('game_image_missing'))

        # Find where Windows loaded the game, since the address can change each launch...
        image_base = struct.unpack('<Q', read(info[1] + 0x10, 8))[0]
        address = image_base + 0x3af490

        # Check the startup code matches what we expect before replacing it...
        if read(address, 16) != bytes.fromhex('40534883ec40c6818d07000001488d54'):
            raise RuntimeError(tr('startup_hook_signature_mismatch'))

        # Reserve game memory for our runnable code and preview data...
        remote = k.VirtualAllocEx(pi.process, None, payload_size, 0x3000, 0x40)

        if not remote:
            raise c.WinError(c.get_last_error())

        payload = bootstrap(image_base, remote, weather)
        write(remote, payload)
        frame_address = image_base + 0x9b83f0
        # Keep the instructions our hotload hook will replace...
        frame_original = bytes.fromhex('48895c2408555657415441554156')

        if read(frame_address, 14) != frame_original:
            raise RuntimeError(tr('reload_signature_mismatch'))

        frame_remote = remote + len(payload)
        write(frame_remote, frame_hook(image_base, remote, frame_remote, frame_original))
        frame_old = w.DWORD()

        # Temporarily allow writing to the game code...
        if not k.VirtualProtectEx(pi.process, frame_address, 14, 0x40, c.byref(frame_old)):
            raise c.WinError(c.get_last_error())

        # Redirect the event handler through our hotload hook...
        write(frame_address, bytes.fromhex('ff2500000000') + struct.pack('<Q', frame_remote))
        ignored = w.DWORD()
        k.VirtualProtectEx(pi.process, frame_address, 14, frame_old.value, c.byref(ignored))
        old = w.DWORD()

        if not k.VirtualProtectEx(pi.process, address, 14, 0x40, c.byref(old)):
            raise c.WinError(c.get_last_error())

        # Replace debug menu startup with our preview battle setup...
        write(address, bytes.fromhex('ff2500000000') + struct.pack('<Q', remote))
        ignored = w.DWORD()
        k.VirtualProtectEx(pi.process, address, 14, old.value, c.byref(ignored))
        # Make sure the game uses the instructions we just wrote...
        k.FlushInstructionCache(pi.process, None, 0)

        # Let the game run now that the hooks are installed!
        if k.ResumeThread(pi.thread) == 0xffffffff:
            raise c.WinError(c.get_last_error())

        k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        k.WaitForSingleObject.restype = w.DWORD

        def restore_dll_config():
            try:
                # Wait for the game to exit before restoring its DLL settings...
                k.WaitForSingleObject(pi.process, 0xffffffff)
                dll_config.restore()
            finally:
                k.CloseHandle(pi.process)

        # Keep cleanup running even if the editor closes...
        watcher = threading.Thread(target=restore_dll_config, name='Playtest DLL cleanup', daemon=False)
        watcher.start()
        watching = True
        _dll_cleanup_thread = watcher

        return pi.pid, remote
    except Exception:
        k.TerminateProcess(pi.process, 1)
        dll_config.restore()
        raise
    finally:
        k.CloseHandle(pi.thread)

        if not watching:
            k.CloseHandle(pi.process)