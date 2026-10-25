"""Manage app settings and paths, setup validation..."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent
DEFAULT_ICONS = ROOT / 'editor_icons'

def read_settings(root):
    """Read settings.json, fall back to empty settings if missing or busted"""
    root = Path(root)
    path = root / 'settings.json'

    try:
        settings = json.loads(path.read_text(encoding='utf-8-sig'))

        if not isinstance(settings, dict):
            settings = {}
    except (OSError, ValueError):
        settings = {}

    return settings

def save_settings(root, settings):
    """Save settings.json without potentially leaving a broken/half written file"""

    path = Path(root) / 'settings.json'
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    os.replace(temporary, path)

def settings_section(root, name, kind=dict):
    value = read_settings(root).get(name)
    return value if isinstance(value, kind) else kind()

def update_settings(root, name, value):
    settings = read_settings(root)
    settings[name] = value
    save_settings(root, settings)

def needs_setup(settings):
    """Ask again if setup was never confirmed or the game folder is messed up..."""
    folder = settings.get('game_folder')

    if not settings.get('setup_complete') or not isinstance(folder, str) or not folder:
        return True

    folder = Path(folder)
    return not (folder / 'Mewgenics.exe').is_file() or not any((folder / name).is_file() for name in ('resources.gpak',))