"""Find the game archive, maintain GON cache, refresh editable definitions with comment preservation and backups..."""
import hashlib
import os
import re
import struct
import time
from pathlib import Path, PurePosixPath
from app.litterbox_language import tr
from app.litterbox_config import read_settings, update_settings

def required_gon(name):
    """Keep the metadata we actually use and skip the unrelated game crap..."""
    files = {'data/spawns.gon', 'data/tiles.gon', 'data/tilesets.gon', 'data/weather.gon'}
    return name in files or (name.endswith('.gon') and name.startswith(('data/characters/', 'data/maps/')))

def find_archive(settings):
    candidates = []
    state = settings.get('vanilla_resources', {})

    if not isinstance(state, dict):
        state = {}

    configured = state.get('archive')
    playtest = settings.get('playtest', {})

    if not isinstance(playtest, dict):
        playtest = {}

    executables = [playtest.get('executable')]
    directories = [Path(settings['game_folder'])] if isinstance(settings.get('game_folder'), str) and settings['game_folder'] else []
    directories.extend(Path(exe).parent for exe in executables if exe)
    steam_roots = [Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Steam']

    if os.name == 'nt':
        import winreg

        for hive, key, value in ((winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'), (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 686060', 'InstallLocation')):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    location = Path(winreg.QueryValueEx(handle, value)[0])

                if value == 'SteamPath':
                    steam_roots.append(location)
                else:
                    directories.append(location)
            except OSError:
                pass

    for steam in steam_roots:
        libraries = [steam]

        try:
            text = (steam / 'steamapps/libraryfolders.vdf').read_text(encoding='utf-8-sig')
            libraries.extend(Path(value.replace('\\\\', '\\')) for value in re.findall(r'"path"\s+"([^"\n]+)"', text))
        except OSError:
            pass

        directories.extend(library / 'steamapps/common/Mewgenics' for library in libraries)

    for directory in directories:
        candidates.extend(directory / name for name in ('resources.gpak',))

    if configured:
        candidates.append(Path(configured))

    return next((path.resolve() for path in candidates if path.is_file()), None)

def find_executable(settings):
    """Use the saved game location, then Steam discovery, with no personal path crap..."""
    playtest = settings.get('playtest', {})
    saved = playtest.get('executable') if isinstance(playtest, dict) else None
    folder = settings.get('game_folder')
    candidates = [Path(saved)] if isinstance(saved, str) and saved else []

    if isinstance(folder, str) and folder:
        candidates.append(Path(folder) / 'Mewgenics.exe')

    for executable in candidates:
        if executable.is_file():
            return executable.resolve()

    archive = find_archive(settings)
    executable = archive.parent / 'Mewgenics.exe' if archive else None
    return executable.resolve() if executable is not None and executable.is_file() else None

def read_gon_archive(path, requested=None, progress=None):
    """Read entry count, u16 path length, UTF-8 path, u32 size, and raw payloads..."""
    path = Path(path)
    length = path.stat().st_size

    with path.open('rb') as stream:
        def take(count):
            data = stream.read(count)

            if len(data) != count:
                raise ValueError(tr('archive_truncated'))

            return data

        count = struct.unpack('<I', take(4))[0]

        if not 0 < count <= 1000000:
            raise ValueError(tr('archive_unsupported_index'))

        entries = []
        names = set()

        for index in range(count):
            size = struct.unpack('<H', take(2))[0]

            if not 0 < size <= 4096:
                raise ValueError(tr('archive_invalid_path'))

            name = take(size).decode('utf-8').replace('\\', '/')
            relative = PurePosixPath(name)

            if relative.is_absolute() or '..' in relative.parts or ':' in name or '\x00' in name or name in names:
                raise ValueError(tr('archive_invalid_path'))

            names.add(name)
            entries.append((name, struct.unpack('<I', take(4))[0]))

            if progress and (index % 256 == 0 or index + 1 == count):
                progress(20 * (index + 1) / count, 'setup_reading')

        offset = stream.tell()

        if offset + sum(size for _, size in entries) != length:
            raise ValueError(tr('archive_unsupported_layout'))

        result = {}
        total = 0
        selected = sum(name in requested if requested is not None else required_gon(name) for name, size in entries)

        for name, size in entries:
            if (name in requested) if requested is not None else required_gon(name):
                total += size

                if size > 64 * 1024 * 1024 or total > 128 * 1024 * 1024:
                    raise ValueError(tr('archive_metadata_too_large'))

                stream.seek(offset)
                result[name] = take(size)

                if progress:
                    progress(20 + 80 * len(result) / max(1, selected), 'setup_extracting', name)

            offset += size

        if requested is None and not all(name in result for name in ('data/spawns.gon', 'data/tiles.gon')):
            raise ValueError(tr('archive_definitions_missing'))

        return result

def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(data)
    os.replace(temporary, path)

def refresh_vanilla(root, archive, baseline=None, preserve_comments=None, progress=None):
    root = Path(root)
    archive = Path(archive)
    state = read_settings(root).get('vanilla_resources', {})

    if progress:
        progress(0, 'setup_checking')

    if not isinstance(state, dict):
        state = {}

    stat = archive.stat()
    fingerprint = {'path': str(archive.resolve()), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
    cache = root / 'app/cache/vanilla_resources'
    files = state.get('files', {})

    if not isinstance(files, dict):
        files = {}

    payloads = {}

    if state.get('fingerprint') == fingerprint and files:
        for index, (name, digest) in enumerate(files.items()):
            relative = PurePosixPath(name)

            if relative.is_absolute() or '..' in relative.parts or ':' in name or '\\' in name or not name.startswith('data/') or not name.endswith('.gon'):
                payloads = {}
                break

            if not required_gon(name):
                continue

            try:
                data = (cache / name).read_bytes()
            except OSError:
                payloads = {}
                break

            if hashlib.sha256(data).hexdigest() != digest:
                payloads = {}
                break

            payloads[name] = data

            if progress:
                progress(5 + 20 * (index + 1) / len(files), 'setup_checking', name)

    if not all(name in payloads for name in ('data/spawns.gon', 'data/tiles.gon')):
        archive_progress = (lambda value, phase, detail='': progress(25 + value * 0.45, phase, detail)) if progress else None
        payloads = read_gon_archive(archive, progress=archive_progress)

    # (Carry user comments over before replacing old vanilla copies)...
    targets = {}

    if progress:
        progress(70, 'setup_preserving')

    for filename in ('spawns.gon', 'tiles.gon'):
        name = 'data/' + filename
        current = root / name
        latest = payloads[name]

        if current.is_file() and preserve_comments:
            previous = cache / name

            if not previous.is_file() and baseline:
                previous = Path(baseline) / name

            original = previous.read_bytes() if previous.is_file() else latest

            if previous == cache / name and hashlib.sha256(original).hexdigest() != files.get(name):
                fallback = Path(baseline) / name if baseline else None
                original = fallback.read_bytes() if fallback and fallback.is_file() else latest

            latest = preserve_comments(current.read_bytes(), original, latest)

        targets[name] = latest

    for index, (name, data) in enumerate(payloads.items()):
        target = cache / name

        if not target.exists() or target.read_bytes() != data:
            atomic_write(target, data)

        if progress:
            progress(70 + 25 * (index + 1) / len(payloads), 'setup_writing', name)

    for name, data in targets.items():
        target = root / name

        if target.exists() and target.read_bytes() != data:
            backup = root / 'app/cache/vanilla_metadata_backups' / str(time.time_ns()) / Path(name).name
            atomic_write(backup, target.read_bytes())

        if not target.exists() or target.read_bytes() != data:
            atomic_write(target, data)

    # Clear stale metadata from generated cache...
    data_cache = (cache / 'data').resolve()

    for cached in list((cache / 'data').rglob('*.gon')):
        name = cached.relative_to(cache).as_posix()
        stale = cached.resolve()

        if name not in payloads and data_cache.is_relative_to(cache.resolve()) and stale.is_relative_to(data_cache) and stale.is_file():
            stale.unlink()
            directory = stale.parent

            while directory != data_cache and directory.is_relative_to(data_cache):
                try:
                    directory.rmdir()
                except OSError:
                    break

                directory = directory.parent

    update_settings(root, 'vanilla_resources', {'archive': str(archive.resolve()), 'fingerprint': fingerprint, 'files': {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}})

    if progress:
        progress(100, 'setup_ready')

    return cache