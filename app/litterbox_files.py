"""Create, open, restore, save levels, remember picker paths, and handle unsaved changes..."""
from pathlib import Path
from tkinter import filedialog

from app import litterbox_dialogs as messagebox
from app.litterbox_format import Level
from app.litterbox_language import tr
from app.litterbox_config import ROOT, read_settings, save_settings, settings_section, update_settings
from app.litterbox_playtest import mod_folder_path

class LevelFiles:
    def picker_settings(self):
        return settings_section(ROOT, 'file_picker')

    def picker_directory(self, kind, fallback):
        remembered = self.picker_settings().get(kind)

        if isinstance(remembered, str) and Path(remembered).is_dir():
            return Path(remembered)

        fallback = Path(fallback)

        return fallback if fallback.is_dir() else ROOT

    def remember_picker_directory(self, kind, folder):
        settings = self.picker_settings()
        settings[kind] = str(Path(folder).resolve())

        try:
            update_settings(ROOT, 'file_picker', settings)
        except OSError:
            pass

    def discard(self):
        """Ask what to do with unsaved changes before throwing anything away..."""

        if not self.dirty:
            return True

        answer = messagebox.askyesnocancel(tr('unsaved_level'), tr('save_changes_before_continuing'))

        if answer is None:
            return False

        return bool(self.save()) if answer else True

    def new(self):
        if not self.discard():
            return

        self.reset_blank_level()

    def reset_blank_level(self):
        self.clear_target()
        self.random_preview = None
        self.wave_view.set('all_waves')
        self.level = Level.blank()
        self.path = None
        self.dirty = False
        self.undo_stack = []
        self.redo_stack = []
        self.draw()

    def open(self):
        if not self.discard():
            return

        path = filedialog.askopenfilename(initialdir=self.picker_directory('levels', self.path.parent if self.path else self.resources / 'levels'), filetypes=[(tr('mewgenics_levels'), '*.lvl')])

        if not path:
            return

        self.remember_picker_directory('levels', Path(path).parent)

        try:
            self.load_level(path)
        except Exception as exc:
            messagebox.showerror(tr('cannot_open_level'), tr(str(exc)))

    def remember_last_level(self):
        try:
            settings = read_settings(ROOT)
            settings['last_level'] = str(self.path.resolve())
            settings['last_level_mods'] = list(dict.fromkeys(str(mod_folder_path(p).resolve()) for p in self.mod_profiles))
            save_settings(ROOT, settings)
        except OSError:
            pass

    def load_level(self, path):
        level = Level.read(path)

        if level.tables[0] != b'spawns.gon' or (len(level.tables) > 1 and level.tables[1] != b'tiles.gon'):
            raise ValueError(tr('custom_tables_unsupported'))

        self.clear_target()
        self.random_preview = None
        self.wave_view.set('all_waves')
        self.level = level
        self.path = Path(path)
        self.dirty = False
        self.undo_stack = []
        self.redo_stack = []
        self.draw()
        self.remember_last_level()

    def restore_last_level(self):
        try:
            settings = read_settings(ROOT)
            path = settings.get('last_level')

            if not isinstance(path, str) or not path or not Path(path).is_file():
                self.reset_blank_level()

                return

            required = settings.get('last_level_mods', [])
            active = {str(mod_folder_path(p).resolve()) for p in self.mod_profiles}

            if not isinstance(required, list) or any(not isinstance(p, str) or str(Path(p).resolve()) not in active or not Path(p).is_dir() for p in required):
                self.reset_blank_level()

                return

            level = Level.read(path)

            for layer, placements in [('tiles', level.tiles), ('spawns', [s.ident for s in level.spawns])]:
                for placement in placements:
                    ids = [placement] if isinstance(placement, int) else [ident for ident, weight in placement.choices]

                    if any(ident != 0 and ident not in self.defs[layer] for ident in ids):
                        self.reset_blank_level()

                        return

            self.load_level(path)
        except Exception:
            self.reset_blank_level()

    def save(self, save_as=False):
        path = self.path

        if path is None or save_as:
            initial_dir = self.picker_directory('levels', path.parent if path else ROOT)
            initial_file = path.name if path else ''
            default_extension = '.lvl'
            file_types = [(tr('mewgenics_levels'), '*.lvl')]

            chosen = filedialog.asksaveasfilename(initialdir=initial_dir, initialfile=initial_file, defaultextension=default_extension, filetypes=file_types)

            if not chosen:
                return False

            path = Path(chosen)
            self.remember_picker_directory('levels', path.parent)

        try:
            data = self.level.encode()
            Level.decode(data)

            if path.exists():
                path.with_suffix(path.suffix + '.bak').write_bytes(path.read_bytes())

            tmp = path.with_suffix(path.suffix + '.tmp')
            tmp.write_bytes(data)
            tmp.replace(path)
            self.path = path
            self.dirty = False
            self.draw()
            self.remember_last_level()

            return True
        except Exception as exc:
            messagebox.showerror(tr('cannot_save_level'), tr(str(exc)))
            return False