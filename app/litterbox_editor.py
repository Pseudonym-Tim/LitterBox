"""Main level editor functionality..."""
import argparse
import tkinter as tk
from pathlib import Path

from app import litterbox_dialogs as messagebox
from app.litterbox_format import Level, representative
from app.litterbox_language import load_language, tr
from app.litterbox_metadata import palette
from app.litterbox_config import DEFAULT_ICONS, ROOT, read_settings, needs_setup
from app.litterbox_layout import EditorLayout
from app.litterbox_dialogs import EditorDialogs, SetupDialog
from app.litterbox_ui import apply_dark_theme, configure_app_window
from app.litterbox_playtest_ui import PlaytestControls
from app.litterbox_board import BoardView
from app.litterbox_palette import PaletteControls
from app.litterbox_editing import EditingControls
from app.litterbox_files import LevelFiles

class Editor(EditorLayout, EditorDialogs, PlaytestControls, BoardView, PaletteControls, EditingControls, LevelFiles):
    def __init__(self, root, resources=None, icons=DEFAULT_ICONS):
        self.initialize_editor(root, resources, icons)

    def close(self):
        if self.discard():
            self.set_side_by_side(False)
            self.disable_global_playtest_hotkey()
            self.root.destroy()

def audit(resources):
    files = list((resources / 'levels').rglob('*.lvl'))
    errors = []
    defs = {'spawns': palette(resources / 'data/spawns.gon'), 'tiles': palette(resources / 'data/tiles.gon')}
    unknown_spawn = set()
    unknown_tile = set()

    for path in files:
        try:
            original = path.read_bytes()
            level = Level.decode(original)
            assert level.encode() == original, 'Round trip changed bytes'
            unknown_spawn.update(representative(i) for x, y, i in level.spawns if representative(i) not in defs['spawns'])
            unknown_tile.update(representative(i) for i in level.tiles if representative(i) not in defs['tiles'])
        except Exception as exc:
            errors.append(f'{path}: {exc}')

    print(tr('audited_levels_failures', value0=len(files), value1=len(errors)))
    print(tr('definition_counts', value0=len(defs['spawns']), value1=len(defs['tiles'])))
    print(tr('unknown_spawn_ids'), sorted(unknown_spawn))
    print(tr('unknown_tile_ids'), sorted(unknown_tile))

    if errors:
        print('\n'.join(errors[:10]))
        raise SystemExit(1)

def main():
    load_language(ROOT, read_settings(ROOT).get('language', 'en'))
    parser = argparse.ArgumentParser()
    parser.add_argument('--resources', type=Path)
    parser.add_argument('--icons', type=Path, default=DEFAULT_ICONS)
    parser.add_argument('--audit', action='store_true')
    args = parser.parse_args()

    if args.audit:
        audit(args.resources or ROOT / 'app/cache/vanilla_resources')
    else:
        root = tk.Tk()
        root.withdraw()

        try:
            if args.resources is None and needs_setup(read_settings(ROOT)):
                configure_app_window(root)
                root._litterbox_style = apply_dark_theme(root)
                prepared = SetupDialog(root, ROOT).run()

                if prepared is None:
                    root.destroy()
                    return

                root._prepared_resources = prepared

            root.resizable(True, True)
            editor = Editor(root, args.resources, args.icons)
            root.deiconify()
            root.update_idletasks()
            root.geometry(f'+{max(0, (root.winfo_screenwidth() - root.winfo_width()) // 2)}+{max(0, (root.winfo_screenheight() - root.winfo_height()) // 2)}')
            editor.fit_board()
            root.mainloop()
        except Exception as exc:
            root.deiconify()
            messagebox.showerror(tr('editor_startup_failed'), tr(str(exc)))
            root.destroy()
            raise

if __name__ == '__main__':
    main()