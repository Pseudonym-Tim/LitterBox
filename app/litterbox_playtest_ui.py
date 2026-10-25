"""Build the playtest window, handle F6 actions, and handle side-by-side mode..."""
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from app import litterbox_dialogs as messagebox
from app.litterbox_language import UIStringVar, tr, translated_values
from app.litterbox_config import ROOT, read_settings, settings_section, update_settings
from app.litterbox_playtest import PlaytestSession, launch as launch_playtest, mod_folder_path, prepare_preview
from app.litterbox_resources import find_executable
from app.litterbox_tilesets import detect_tileset, detect_weather, tileset_names
from app.litterbox_ui import COLORS as UI_COLORS, icon_button, icon_image, center_window

class PlaytestControls:
    def playtest_hotkey(self, event=None):
        self.show_playtest()
        self.playtest_window.playtest_action()
        return 'break'

    def hotkey_down(self, event=None):
        if getattr(self, 'local_playtest_down', False):
            return 'break'

        self.local_playtest_down = True

        if getattr(self, 'global_playtest_hotkey', None) is not None or getattr(self, 'playtest_ignore', False):
            return 'break'

        if getattr(self, 'local_playtest_job', None) is None:
            self.local_playtest_stopped = False

            def held():
                self.local_playtest_job = None
                self.local_playtest_stopped = True
                session = getattr(self, 'playtest_session', None)

                if session is not None and session.alive():
                    self.stop_playtest()

            self.local_playtest_job = self.root.after(1000, held)

        return 'break'

    def hotkey_up(self, event=None):
        self.local_playtest_down = False
        job = getattr(self, 'local_playtest_job', None)

        if job is not None:
            self.root.after_cancel(job)
            self.local_playtest_job = None

        if getattr(self, 'global_playtest_hotkey', None) is not None or getattr(self, 'playtest_ignore', False):
            return 'break'

        if not getattr(self, 'local_playtest_stopped', False):
            self.playtest_hotkey()

        self.local_playtest_stopped = False

        return 'break'

    def stop_playtest(self):
        hotkey = getattr(self, 'global_playtest_hotkey', None)

        if hotkey is not None and hotkey.key_down():
            self.playtest_ignore = True

            def wait_for_release():
                if hotkey.key_down():
                    self.root.after(25, wait_for_release)
                else:
                    self.playtest_ignore = False
                    self.local_playtest_down = False
                    self.local_playtest_stopped = False

            self.root.after(25, wait_for_release)

        session = getattr(self, 'playtest_session', None)

        if session is not None:
            session.close(terminate=True)

        self.set_side_by_side(False)
        self.disable_global_playtest_hotkey()
        dialog = getattr(self, 'playtest_window', None)

        if dialog is not None and dialog.winfo_exists():
            dialog.refresh_playtest_status()

    def set_side_by_side(self, enabled):
        job = getattr(self, 'side_layout_job', None)

        if job is not None:
            self.root.after_cancel(job)

        self.side_layout_job = None
        from app.litterbox_windows import arrange_playtest, restore_playtest, focus_playtest
        session = getattr(self, 'playtest_session', None)

        if not enabled:
            restore_playtest(self.root)

            if session is None or not session.alive():
                return

            requested = False

            def restore_when_ready(attempt=0):
                nonlocal requested
                self.side_layout_job = None

                try:
                    if session is not getattr(self, 'playtest_session', None) or not session.alive():
                        return

                    if not requested:
                        requested = session.request_display()

                    if requested and session.windowed_ready():
                        focus_playtest(session.pid)

                        return
                except OSError:
                    return

                if attempt < 1200:
                    self.side_layout_job = self.root.after(100, lambda: restore_when_ready(attempt + 1))

            restore_when_ready()

            return

        if session is None or not session.alive():
            return

        requested = False

        def arrange_when_ready(attempt=0):
            nonlocal requested
            self.side_layout_job = None

            try:
                if session is not getattr(self, 'playtest_session', None) or not session.alive():
                    return

                if not requested:
                    requested = session.request_windowed()

                if requested and session.ready() and session.windowed_ready() and arrange_playtest(self.root, session.pid):
                    return
            except OSError:
                return

            if attempt < 1200:
                self.side_layout_job = self.root.after(500, lambda: arrange_when_ready(attempt + 1))

        arrange_when_ready()

    def enable_global_playtest_hotkey(self):
        if getattr(self, 'global_playtest_hotkey', None) is not None:
            return

        from app.litterbox_hotkeys import PlaytestHotkey

        try:
            self.global_playtest_hotkey = PlaytestHotkey()
        except OSError:
            messagebox.showwarning(tr('playtest_hotkey_unavailable'), tr('playtest_hotkey_already_registered'), parent=self.root)

            return

        def poll():
            hotkey = self.global_playtest_hotkey
            session = getattr(self, 'playtest_session', None)

            if hotkey is None:
                return

            if session is None or not session.alive():
                self.disable_global_playtest_hotkey()

                return

            action = hotkey.action()

            if action == 'stop':
                self.stop_playtest()

                return

            if action == 'hotload':
                try:
                    session.reload(self.level)
                except Exception as exc:
                    messagebox.showerror(tr('cannot_start_playtest'), tr(str(exc)), parent=self.root)

            self.global_playtest_hotkey_job = self.root.after(50, poll)

        self.global_playtest_hotkey_job = self.root.after(50, poll)

    def disable_global_playtest_hotkey(self):
        job = getattr(self, 'global_playtest_hotkey_job', None)

        if job is not None:
            self.root.after_cancel(job)
            self.global_playtest_hotkey_job = None

        hotkey = getattr(self, 'global_playtest_hotkey', None)

        if hotkey is not None:
            hotkey.close()
            self.global_playtest_hotkey = None

    def show_playtest(self):
        """Set up playtesting, hotloading, and the game window controls..."""

        existing = getattr(self, 'playtest_window', None)

        if existing is not None and existing.winfo_exists():
            existing.lift()

            return

        dialog = self.playtest_window = tk.Toplevel(self.root)
        dialog.title(tr('playtest_level'))
        dialog.transient(self.root)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        settings = settings_section(ROOT, 'playtest')
        game_executable = find_executable(read_settings(ROOT))
        executable = tk.StringVar(value=str(game_executable) if game_executable else '')
        folders = list(dict.fromkeys(str(mod_folder_path(p)) for p in self.mod_profiles))
        choices = ['vanilla_no_mod'] + folders
        initial = settings.get('mod', '')

        if self.path:
            initial = next((folder for folder in folders if self.path.resolve().is_relative_to(Path(folder).resolve())), initial)

        selected_mod = UIStringVar(value=initial if initial in folders else choices[0])
        ttk.Label(frame, text=tr('playtest_the_current_level'), font=('Sour Gummy', 12, 'bold')).grid(row=0, column=0, columnspan=3, sticky='w')
        ttk.Label(frame, text=tr('unsaved_edits_hint')).grid(row=1, column=0, columnspan=3, sticky='w', pady=(4, 12))
        ttk.Label(frame, text=tr('game')).grid(row=2, column=0, sticky='w', padx=(0, 8))
        ttk.Entry(frame, textvariable=executable, width=64).grid(row=2, column=1, sticky='ew')

        def browse():
            dialog_title = tr('choose_mewgenics_exe')
            game_executable_filter = (tr('game_executable'), 'Mewgenics.exe')
            executables_filter = (tr('executables'), '*.exe')
            file_types = [game_executable_filter, executables_filter]

            executable_directory = Path(executable.get()).parent
            initial_directory = self.picker_directory('executable', executable_directory)

            path = filedialog.askopenfilename(parent=dialog, title=dialog_title, filetypes=file_types, initialdir=initial_directory)

            if path:
                self.remember_picker_directory('executable', Path(path).parent)
                executable.set(path)

        icon_button(frame, text=tr('browse'), icon='folder-open', command=browse).grid(row=2, column=2, sticky='w', padx=(8, 0))
        ttk.Label(frame, text=tr('mod')).grid(row=3, column=0, sticky='w', padx=(0, 8), pady=8)
        combo = ttk.Combobox(frame, textvariable=selected_mod, values=translated_values(choices, selected_mod), state='readonly', width=64)
        combo.grid(row=3, column=1, columnspan=2, sticky='ew', pady=8)
        tileset = tk.StringVar(value=settings.get('tileset', 'alley'))
        automatic = tk.BooleanVar(value=True)
        detection = tk.StringVar()
        ttk.Label(frame, text=tr('tileset')).grid(row=4, column=0, sticky='w', padx=(0, 8))
        tile_combo = ttk.Combobox(frame, textvariable=tileset, state='readonly', width=40)
        tile_combo.grid(row=4, column=1, sticky='ew')

        def update_tilesets(event=None):
            mod = selected_mod.get() if selected_mod.get() in folders else None
            names = tileset_names(self.resources, mod)
            tile_combo.configure(values=translated_values(names))

            if automatic.get():
                chosen, reason = detect_tileset(self.path, self.resources, mod, names)
                tileset.set(chosen)
                detection.set(tr(reason))
            elif tileset.get() not in names:
                tileset.set('alley')
                detection.set(tr('mod_tileset_unavailable'))
            else:
                detection.set(tr('manual_tileset'))

        def choose_tileset(event=None):
            automatic.set(False)
            detection.set(tr('manual_tileset'))

        ttk.Checkbutton(frame, text=tr('auto_detect_tileset'), variable=automatic, command=update_tilesets, style='Clean.TCheckbutton').grid(row=4, column=2, sticky='w', padx=(8, 0))
        ttk.Label(frame, textvariable=detection, wraplength=650).grid(row=5, column=1, columnspan=2, sticky='w', pady=(3, 8))
        combo.bind('<<ComboboxSelected>>', update_tilesets)
        tile_combo.bind('<<ComboboxSelected>>', choose_tileset)
        update_tilesets()
        side_by_side = tk.BooleanVar(value=settings.get('side_by_side', False))
        options = ttk.Frame(frame)
        options.grid(row=6, column=0, columnspan=3, sticky='w')

        def change_side_by_side():
            try:
                self.set_side_by_side(side_by_side.get())
                saved = settings_section(ROOT, 'playtest')
                saved['side_by_side'] = side_by_side.get()
                update_settings(ROOT, 'playtest', saved)
            except Exception as exc:
                messagebox.showerror(tr('cannot_start_playtest'), tr(str(exc)), parent=dialog)

        ttk.Checkbutton(options, text=tr('side_by_side'), variable=side_by_side, command=change_side_by_side, style='Clean.TCheckbutton').pack(side='left')
        ttk.Label(frame, text=tr('playtest_note'), wraplength=650).grid(row=7, column=0, columnspan=3, sticky='w', pady=(8, 0))
        game_status = ttk.Label(frame, text=tr('game_is_not_running'), foreground=UI_COLORS['error_fg'])
        game_status.grid(row=8, column=0, columnspan=3, sticky='w', pady=(10, 0))
        buttons = ttk.Frame(frame)
        buttons.grid(row=9, column=0, columnspan=3, sticky='ew', pady=(12, 0))

        def start():
            try:
                previews = ROOT / 'app/cache/playtests'
                previews.mkdir(parents=True, exist_ok=True)
                mod = selected_mod.get() if selected_mod.get() in folders else None
                weather, reason = detect_weather(self.path, self.resources, mod, tileset.get())
                configuration = (str(Path(executable.get()).resolve()), mod, tileset.get(), tuple(weather))
                session = getattr(self, 'playtest_session', None)

                if session is not None and session.alive() and session.configuration == configuration:
                    session.reload(self.level)
                else:
                    if session is not None:
                        session.close(terminate=True)

                    staging = Path(tempfile.mkdtemp(prefix='preview_', dir=previews))
                    prepare_preview(self.level, staging, tileset.get(), weather)
                    game_status.configure(text=tr('game_is_booting_up'), foreground=UI_COLORS['warning_fg'])
                    dialog.update_idletasks()
                    self.playtest_pid, self.playtest_remote = launch_playtest(executable.get(), staging, mod)
                    session = self.playtest_session = PlaytestSession(self.playtest_pid, self.playtest_remote, staging, configuration)

                self.enable_global_playtest_hotkey()
                self.set_side_by_side(side_by_side.get())
            except Exception as exc:
                refresh_action()
                messagebox.showerror(tr('cannot_start_playtest'), tr(str(exc)), parent=dialog)
                return

            try:
                update_settings(ROOT, 'playtest', {'executable': executable.get(), 'mod': mod or '', 'tileset': tileset.get(), 'side_by_side': side_by_side.get()})
            except OSError:
                pass

            refresh_action()

        action_button = icon_button(buttons, text=tr('start_playtest'), icon='play', command=start)
        dialog.playtest_action = start
        dialog.bind('<KeyPress-F6>', self.hotkey_down)
        dialog.bind('<KeyRelease-F6>', self.hotkey_up)
        action_button.pack(side='left')
        stop_button = icon_button(buttons, text=tr('stop_playtest'), icon='stop', command=self.stop_playtest)

        def refresh_action():
            session = getattr(self, 'playtest_session', None)
            running = session is not None and session.alive()
            ready = False

            if running:
                try:
                    ready = session.ready()
                except OSError:
                    pass

            game_status.configure(text=tr('game_is_running' if ready else 'game_is_booting_up' if running else 'game_is_not_running'), foreground='#7bd88f' if ready else UI_COLORS['warning_fg'] if running else UI_COLORS['error_fg'])

            if running:
                stop_button.pack(side='left', padx=(8, 0), after=action_button)
            else:
                stop_button.pack_forget()

            name = 'arrows-rotate' if running else 'play'
            action_button.configure(text=tr('hotload_changes') if running else tr('start_playtest'), image=(icon_image(dialog, name), 'disabled', icon_image(dialog, name, disabled=True)))

        refresh_job = None
        dialog.refresh_playtest_status = refresh_action

        def watch_game():
            nonlocal refresh_job
            refresh_action()
            refresh_job = dialog.after(500, watch_game)

        def stop_watching(event):
            if event.widget == dialog and refresh_job is not None:
                dialog.after_cancel(refresh_job)

        dialog.bind('<Destroy>', stop_watching, add='+')
        watch_game()
        icon_button(buttons, text=tr('close'), icon='xmark', command=dialog.destroy).pack(side='right')
        dialog.bind('<Escape>', lambda event: dialog.destroy())
        center_window(dialog, self.root)