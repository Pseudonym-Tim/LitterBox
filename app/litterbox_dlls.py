"""Find and order a mod's DLLs and manage temporary chainloader settings for playtesting..."""
from pathlib import Path
import configparser
import io
import json
from app.litterbox_language import tr

def mod_dlls(folder):
    if not folder:
        return []

    root = Path(folder)
    dlls = sorted((p.resolve() for p in root.rglob('*') if p.is_file() and p.suffix.lower() == '.dll'), key=lambda p: (p.name.lower(), str(p).lower()))
    order = []

    for name in ('description.json', 'info.json', 'modinfo.json'):
        path = root / name

        if path.is_file():
            metadata = json.loads(path.read_text(encoding='utf-8-sig'))
            order = metadata.get('dll_order', []) if isinstance(metadata, dict) else []
            break

    if not isinstance(order, list):
        order = []

    ranked = {str(name).lower(): index for index, name in reversed(list(enumerate(order)))}

    return sorted(dlls, key=lambda p: ranked.get(p.relative_to(root.resolve()).as_posix().lower(), ranked.get(p.name.lower(), len(order))))

class DllPlaytestConfig:
    def __init__(self, game, staging, mod=None):
        self.path = Path(game) / 'chainloader.ini'
        self.original = self.applied = None
        dlls = mod_dlls(mod)

        if not self.path.is_file() or not (Path(game) / 'version.dll').is_file():
            if dlls:
                raise RuntimeError(tr('dll_chainloader_required'))

            return

        staging = Path(staging).resolve()
        staging.mkdir(parents=True, exist_ok=True)
        manifest = staging / 'playtest_dll_manifest.txt'
        manifest.write_text(''.join(str(p) + '\n' for p in dlls), encoding='utf-8')
        scan = staging / 'dll_scan'
        scan.mkdir(exist_ok=True)
        original = self.path.read_bytes()
        config = configparser.ConfigParser(interpolation=None, strict=False)
        config.optionxform = str
        config.read_string(original.decode('utf-8-sig'))

        # Load chosen mod, not whatever DLL stuff Mewtator last used...
        for section in list(config.sections()):
            if section.lower() in ('chainloader', 'loadorder'):
                config.remove_section(section)

        config['Chainloader'] = {'Enabled': '1' if dlls else '0', 'ScanPath': str(scan), 'ScanGameDir': '0', 'MewtatorManifest': str(manifest), 'Logging': '1'}
        config['LoadOrder'] = {}
        text = io.StringIO()
        config.write(text, space_around_delimiters=False)
        self.applied = text.getvalue().encode('utf-8')
        self.path.write_bytes(self.applied)
        self.original = original

    def restore(self):
        """Put old chainloader config back"""

        if self.original is not None:
            # Leave it alone if another launcher or whatever changed the config...
            if self.path.is_file() and self.path.read_bytes() == self.applied:
                self.path.write_bytes(self.original)

            self.original = None