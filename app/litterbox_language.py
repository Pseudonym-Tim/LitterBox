"""Load language JSON, format translated text, etc..."""
import json
import tkinter as tk
from pathlib import Path

_catalog = {}

def load_language(root, language='en'):
    global _catalog
    root = Path(root)
    _catalog = {}

    for code in dict.fromkeys(('en', language)):
        if not isinstance(code, str) or Path(code).name != code:
            continue

        try:
            data = json.loads((root / 'languages' / f'{code}.json').read_text(encoding='utf-8-sig'))

            if isinstance(data, dict):
                _catalog.update({key: value for key, value in data.items() if isinstance(key, str) and isinstance(value, str)})
        except (OSError, ValueError):
            pass

def tr(key, **values):
    if not isinstance(key, str):
        return key

    template = _catalog.get(key, key)

    if values:
        try:
            return template.format(**values)
        except (KeyError, ValueError, IndexError):
            return template

    return template

def display_token(key):
    if not isinstance(key, str):
        return key

    if key.startswith('wave:') and key[5:].isdigit():
        return tr('wave_label', value0=key[5:])

    if key.startswith('mod:'):
        return tr('mod_filter_label', value0=key[4:])

    return tr(key)

def translated_values(values, variable=None):
    if variable is not None:
        return variable.display_values(values)

    return [display_token(value) for value in values]

class UIStringVar(tk.StringVar):
    def __init__(self, master=None, value=None, name=None):
        self._labels = {}
        super().__init__(master, name=name)

        if value is not None:
            self.set(value)

    def display_values(self, values):
        labels = [display_token(value) for value in values]
        self._labels = dict(zip(labels, values))
        return labels

    def set(self, key):
        label = display_token(key)
        self._labels[label] = key
        super().set(label)

    def get(self):
        value = super().get()
        return self._labels.get(value, value)