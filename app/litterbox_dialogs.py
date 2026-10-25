"""Build various themed message dialogs..."""
import tkinter as tk
import queue
import threading
import time
from pathlib import Path
from app.version import APP_VERSION_DISPLAY, versioned_title
from tkinter import filedialog, ttk, font

from app.litterbox_format import uint
from app.litterbox_language import tr
from app.litterbox_metadata import discover_mod_assets, merge_mod_assets
from app.litterbox_config import ROOT, read_settings, save_settings, update_settings
from app.litterbox_metadata import preserve_entry_comments
from app.litterbox_resources import find_archive, refresh_vanilla
from app.litterbox_playtest import mod_folder_path
from app.litterbox_ui import BUTTON_ICONS, icon_button, COLORS, icon_image, apply_dark_titlebar, center_window

def show_message(title, message, *, parent=None, kind='info', choices=None, cancel='ok'):
    """Show a themed modal message thingy..."""

    parent = parent or tk._default_root

    if parent is None:
        raise RuntimeError('Message dialog requires an editor window!')

    parent = parent.winfo_toplevel()
    previous_focus = parent.focus_get()
    previous_grab = parent.grab_current()
    grab_status = previous_grab.grab_status() if previous_grab else None

    dialog = tk.Toplevel(parent)
    dialog.withdraw()
    dialog.title(title)
    dialog.configure(background=COLORS['bg'])
    dialog.transient(parent)
    dialog.resizable(False, False)
    result = cancel

    def finish(value):
        nonlocal result
        result = value
        dialog.destroy()

    content = ttk.Frame(dialog, padding=20)
    content.pack(fill='both', expand=True)
    color = COLORS['error_fg'] if kind == 'error' else COLORS['warning_fg'] if kind == 'warning' else COLORS['fg']

    image = icon_image(dialog, 'info-circle')
    title_font = ('Sour Gummy', 13, 'bold')

    label = ttk.Label(content, text=title, image=image, compound='left', foreground=color, font=title_font, wraplength=520)
    label.pack(anchor='w', pady=(0, 12))

    body = ttk.Frame(content)
    body.pack(fill='both', expand=True)

    text_font = font.nametofont('TkDefaultFont', root=parent)
    lines = sum(max(1, (text_font.measure(line) + 519) // 520) for line in str(message).split('\n'))

    text_width = max(30, 520 // max(1, text_font.measure('0')))
    text_height = min(14, lines)

    bg_color = COLORS['bg']
    fg_color = COLORS['fg']
    select_bg = COLORS['select_bg']
    select_fg = COLORS['select_fg']

    # Oh my fucking godddd this is so long but whatever...
    text = tk.Text(body, width=text_width, height=text_height, wrap='word', font=text_font, background=bg_color, foreground=fg_color, selectbackground=select_bg, selectforeground=select_fg, borderwidth=0, highlightthickness=0, padx=0, pady=0)
    text.pack(side='left', fill='both', expand=True)
    text.insert('1.0', str(message))
    text.configure(state='disabled')

    if lines > 14:
        scrollbar = ttk.Scrollbar(body, orient='vertical', command=text.yview)
        scrollbar.pack(side='right', fill='y', padx=(8, 0))
        text.configure(yscrollcommand=scrollbar.set)

    buttons = ttk.Frame(content)
    buttons.pack(fill='x', pady=(18, 0))

    choices = choices or [('ok', 'ok', 'check')]
    action_buttons = []

    for value, key, icon in choices:
        button = icon_button(buttons, text=tr(key), icon=icon, command=lambda value=value: finish(value))
        button.pack(side='left', padx=(0, 8))
        action_buttons.append(button)

    dialog.protocol('WM_DELETE_WINDOW', lambda: finish(cancel))
    dialog.bind('<Escape>', lambda event: finish(cancel))

    def activate(event):
        focused = dialog.focus_get()
        (focused if focused in action_buttons else action_buttons[0]).invoke()
        return 'break'

    dialog.bind('<Return>', activate)
    dialog.update_idletasks()

    width, height = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
    x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
    x = max(0, min(x, dialog.winfo_screenwidth() - width))
    y = max(0, min(y, dialog.winfo_screenheight() - height))
    dialog.geometry(f'+{x}+{y}')
    dialog.deiconify()

    try:
        dialog.wait_visibility()
        dialog.grab_set()
        action_buttons[0].focus_set()

        if dialog.tk.call('tk', 'windowingsystem') == 'win32':
            apply_dark_titlebar(dialog)

        parent.wait_window(dialog)
    finally:
        if dialog.winfo_exists():
            dialog.destroy()

        if previous_grab is not None and previous_grab.winfo_exists():
            if grab_status == 'global':
                previous_grab.grab_set_global()
            else:
                previous_grab.grab_set()

        if previous_focus is not None and previous_focus.winfo_exists():
            previous_focus.focus_set()

    return result

def showinfo(title, message, *, parent=None):
    return show_message(title, message, parent=parent)

def showwarning(title, message, *, parent=None):
    return show_message(title, message, parent=parent, kind='warning')

def showerror(title, message, *, parent=None):
    return show_message(title, message, parent=parent, kind='error')

def askyesnocancel(title, message, *, parent=None):
    choices = [(True, 'save', 'floppy-disk'), (False, 'discard_changes', 'trash-can'), (None, 'cancel', 'xmark')]
    return show_message(title, message, parent=parent, kind='warning', choices=choices, cancel=None)

class EditorDialogs:
    def set_mod_profiles(self, profiles):
        definitions, categories, conflicts = merge_mod_assets(self.base_definitions, self.base_categories, profiles, self.icons)
        update_settings(ROOT, 'mods', profiles)
        self.mod_profiles = profiles
        self.defs = definitions
        self.category_names = categories
        self.cache.clear()
        self.projected_icons.clear()
        self.clear_target()
        self.refresh_palette()
        self.update_brush_summary()
        self.draw()

        return conflicts

    def show_mod_assets(self):
        """Manage mod folders, reload definitions and icon stuff..."""

        existing = getattr(self, 'mod_window', None)

        if existing is not None and existing.winfo_exists():
            existing.lift()
            return

        dialog = self.mod_window = tk.Toplevel(self.root)
        dialog.title(tr('mod_assets'))
        dialog.transient(self.root)
        dialog.geometry('740x330')
        dialog.minsize(640, 280)
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        ttk.Label(frame, text=tr('mod_folder_hint'), font=('Sour Gummy', 12, 'bold'), wraplength=690, justify='left').grid(row=0, column=0, columnspan=3, sticky='w')
        ttk.Label(frame, text=tr('unique_ids_hint'), wraplength=690).grid(row=1, column=0, columnspan=3, sticky='w', pady=(4, 10))
        folder_rows = {}
        listing = ttk.Frame(frame)
        listing.grid(row=2, column=0, columnspan=3, sticky='nsew', pady=10)
        listing.rowconfigure(0, weight=1)
        listing.columnconfigure(0, weight=1)
        tree = ttk.Treeview(listing, columns=('folder',), show='headings', height=4)
        tree.heading('folder', text=tr('mod_folder'))
        tree.column('folder', width=650, stretch=True)
        tree.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(listing, command=tree.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        tree.configure(yscrollcommand=scrollbar.set)

        def refresh():
            tree.delete(*tree.get_children())
            folder_rows.clear()
            grouped = {}

            for index, profile in enumerate(self.mod_profiles):
                path = str(mod_folder_path(profile))
                grouped.setdefault(path, []).append(index)

            for row, (path, indices) in enumerate(grouped.items()):
                folder_rows[str(row)] = indices
                tree.insert('', 'end', iid=str(row), values=(path,))

        def commit(profiles):
            try:
                conflicts = self.set_mod_profiles(profiles)
            except Exception as exc:
                showerror(tr('cannot_load_mod_assets'), tr(str(exc)), parent=dialog)
                return False

            refresh()

            if conflicts:
                title = tr('duplicate_ids_skipped')
                conflict_list = '\n'.join(conflicts[:20])
                and_more = tr('and_more', value0=len(conflicts) - 20) if len(conflicts) > 20 else ''
                message = tr('duplicate_ids_message', value0=conflict_list, value1=and_more)
                showwarning(title, message, parent=dialog)

            return True

        def remove():
            selected = {index for row in tree.selection() for index in folder_rows[row]}

            if selected:
                commit([profile for index, profile in enumerate(self.mod_profiles) if index not in selected])

        def add_folder():
            folder = filedialog.askdirectory(parent=dialog, title=tr('choose_mod_folder'), initialdir=self.picker_directory('mods', ROOT))

            if folder:
                self.remember_picker_directory('mods', folder)

            if not folder:
                return

            profiles = discover_mod_assets(folder)

            if not profiles:
                showerror(tr('no_definitions'), tr('mod_definitions_missing'), parent=dialog)

                return

            commit(self.mod_profiles + [profile for profile in profiles if profile not in self.mod_profiles])

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, columnspan=3, sticky='ew')
        icon_button(buttons, text=tr('add_mod_folder'), icon='folder-open', command=add_folder).pack(side='left')
        icon_button(buttons, text=tr('remove_selected'), icon='trash-can', command=remove).pack(side='left', padx=8)
        icon_button(buttons, text=tr('reload_files'), icon='arrows-rotate', command=lambda: commit(self.mod_profiles)).pack(side='left')
        icon_button(buttons, text=tr('close'), icon='xmark', command=dialog.destroy).pack(side='right')
        refresh()
        center_window(dialog, self.root, width=740, height=330)

    def show_about(self):
        existing = getattr(self, 'about_window', None)

        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_set()

            return

        dialog = self.about_window = tk.Toplevel(self.root)
        dialog.title(tr('about_litterbox'))
        dialog.transient(self.root)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=(28, 24))
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=tr('litterbox'), font=('Sour Gummy', 24, 'bold')).pack(anchor='w')
        ttk.Label(frame, text=tr('mewgenics_level_editor'), font=('Sour Gummy', 14, 'bold'), foreground=COLORS['muted_fg']).pack(anchor='w', pady=(2, 4))
        ttk.Label(frame, text=tr('version_label', value0=APP_VERSION_DISPLAY), foreground=COLORS['muted_fg']).pack(anchor='w', pady=(0, 18))
        ttk.Label(frame, text=tr('about_description'), wraplength=500, justify='left').pack(anchor='w', pady=(0, 22))
        ttk.Label(frame, text=tr('about_disclaimer'), wraplength=500, justify='left', foreground=COLORS['muted_fg']).pack(anchor='w', pady=(0, 22))
        ttk.Separator(frame, orient='horizontal').pack(fill='x', pady=(0, 18))
        ttk.Label(frame, text=tr('credits_heading'), font=('Sour Gummy', 14, 'bold')).pack(anchor='w', pady=(0, 8))

        for credit in ('credit_developer', 'credit_logo', 'credit_game'):
            ttk.Label(frame, text=tr(credit), wraplength=500, justify='left').pack(anchor='w', pady=2)

        icon_button(frame, text=tr('close'), icon='xmark', command=dialog.destroy).pack(anchor='e', pady=(24, 0))
        dialog.bind('<Escape>', lambda event: dialog.destroy())
        center_window(dialog, self.root, width=556)

    def show_help(self):
        existing = getattr(self, 'help_window', None)

        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_set()

            return

        dialog = self.help_window = tk.Toplevel(self.root)
        dialog.title(tr('litterbox_help'))
        dialog.transient(self.root)
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=tr('using_litterbox'), font=('Sour Gummy', 14, 'bold')).pack(anchor='w', pady=(0, 10))
        text = ('help_controls')
        ttk.Label(frame, text=tr(text), justify='left').pack(anchor='w')
        ttk.Label(frame, text=tr('playtest_hotkey_in_game_hint'), justify='left').pack(anchor='w', pady=(8, 0))
        icon_button(frame, text=tr('close'), icon='xmark', command=dialog.destroy).pack(anchor='e', pady=(12, 0))
        dialog.bind('<Escape>', lambda event: dialog.destroy())
        center_window(dialog, self.root)

    def edit_choices(self):
        layer = self.layer.get()
        dialog = tk.Toplevel(self.root)
        dialog.title(tr('random_choices_title', value0=tr('tile_lowercase') if layer == 'tiles' else tr('spawn_lowercase')))
        dialog.geometry('650x540')
        dialog.transient(self.root)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=tr('choice_weights_hint')).pack(anchor='w')
        search = tk.StringVar()
        ttk.Entry(frame, textvariable=search).pack(fill='x', pady=(10, 4))
        available = tk.StringVar()
        chooser = ttk.Combobox(frame, textvariable=available, state='readonly')
        chooser.pack(fill='x')
        ids = {}

        def filter_choices(*_):
            ids.clear()

            for ident, d in sorted(self.defs[layer].items(), key=lambda item: item[1]['name']):
                label = f'{d["name"]} [{ident}]'

                if search.get().lower() in label.lower():
                    ids[label] = ident

            chooser['values'] = list(ids)
            preferred = next((label for label, ident in ids.items() if ident == self.selected), '')
            chooser.set(preferred or next(iter(ids), ''))

        search.trace_add('write', filter_choices)
        filter_choices()
        controls = ttk.Frame(frame)
        controls.pack(fill='x', pady=8)
        weight = tk.StringVar(value='1')
        ttk.Label(controls, text=tr('weight')).pack(side='left')
        ttk.Spinbox(controls, from_=0, to=65535, textvariable=weight, width=7).pack(side='left', padx=6)
        choices = list(self.random_choices)
        pool = ttk.Treeview(frame, columns=('name', 'weight', 'chance'), show='headings', height=10, selectmode='browse')

        for col, label, width in [('name', 'tile' if layer == 'tiles' else 'spawn', 350), ('weight', 'weight', 80), ('chance', 'chance', 90)]:
            pool.heading(col, text=tr(label))
            pool.column(col, width=width, anchor='w')

        pool.pack(fill='both', expand=True)
        bar = ttk.Scrollbar(pool, orient='vertical', command=pool.yview)
        bar.pack(side='right', fill='y')
        pool.configure(yscrollcommand=bar.set)

        def refresh():
            pool.delete(*pool.get_children())
            total = sum(w for _, w in choices)

            for i, (ident, w) in enumerate(choices):
                pool.insert('', 'end', iid=str(i), values=(f'{self.spawn_name(ident)} [{ident}]', w, f'{w / total:.1%}' if total else '0%'))

        def get_weight():
            return uint(int(weight.get()), 65535, 'weight')

        def add():
            try:
                ident = ids.get(available.get())

                if ident is None:
                    raise ValueError(tr('choose_a_tile_or_spawn_first'))

                if len(choices) >= 255:
                    raise ValueError(tr('choice_limit'))

                choices.append((ident, get_weight()))
                refresh()
            except ValueError as exc:
                showerror(tr('cannot_add_choice'), tr(str(exc)), parent=dialog)

        def update():
            if not pool.selection():
                return

            try:
                i = int(pool.selection()[0])
                choices[i] = (choices[i][0], get_weight())
                refresh()
            except ValueError as exc:
                showerror(tr('invalid_weight'), tr(str(exc)), parent=dialog)

        def remove():
            if pool.selection():
                choices.pop(int(pool.selection()[0]))
                refresh()

        def selected(event):
            if pool.selection():
                weight.set(str(choices[int(pool.selection()[0])][1]))

        pool.bind('<<TreeviewSelect>>', selected)

        for label, fn in [('add_choice', add), ('set_weight', update), ('remove', remove)]:
            icon_button(controls, text=tr(label), icon=BUTTON_ICONS.get(label), command=fn).pack(side='left', padx=4)

        footer = ttk.Frame(frame)
        footer.pack(fill='x', pady=(10, 0))

        def accept():
            if not choices or sum(w for _, w in choices) <= 0:
                showerror(tr('invalid_choices'), tr('positive_choice_required'), parent=dialog)

                return

            self.random_choices = tuple(choices)
            self.spawn_mode.set('random_choices')
            dialog.destroy()
            self.placement_setting_changed()

        ttk.Label(footer, text=tr('use_choices_hint')).pack(side='left')
        icon_button(footer, text=tr('cancel'), icon='xmark', command=dialog.destroy).pack(side='right', padx=4)
        icon_button(footer, text=tr('use_choices'), icon='check', command=accept).pack(side='right')
        refresh()

class SetupDialog:
    """Find the game and prep metadata before the editor shows up..."""

    MIN_LOADING_SECONDS = 1.2

    def __init__(self, root, directory=ROOT, baseline=None):
        self.root = root
        self.directory = Path(directory)
        self.baseline = baseline
        self.events = queue.Queue()
        self.busy = False
        self.closing = False
        self.result = None
        self.prepared = None
        self.folder_job = None
        self.finished = tk.BooleanVar(root, value=False)
        self.poll_job = None
        self.folder = tk.StringVar(root, value=read_settings(directory).get('game_folder', ''))
        self.status = tk.StringVar(root, value=tr('setup_detecting'))
        self.detail = tk.StringVar(root)
        root.title(versioned_title(tr('setup_title')))
        root.resizable(False, False)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.frame = ttk.Frame(root, padding=20)
        self.frame.pack(fill='both', expand=True)
        self.frame.columnconfigure(0, weight=1)

        ttk.Label(self.frame, text=tr('setup_heading'), font=('Sour Gummy', 16, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w')
        ttk.Label(self.frame, text=tr('setup_hint'), wraplength=570).grid(row=1, column=0, columnspan=2, sticky='w', pady=(8,16))
        ttk.Label(self.frame, text=tr('game_folder')).grid(row=2, column=0, columnspan=2, sticky='w', pady=(0,4))
        self.entry = ttk.Entry(self.frame, textvariable=self.folder, width=60)
        self.entry.grid(row=3, column=0, sticky='ew')
        self.browse_button = icon_button(self.frame, text=tr('browse'), icon='folder-open', command=self.browse)
        self.browse_button.grid(row=3, column=1, sticky='w', padx=(8,0))

        self.status_label = ttk.Label(self.frame, textvariable=self.status, wraplength=570)
        self.status_label.grid(row=4, column=0, columnspan=2, sticky='w', pady=(16,6))
        self.progress = ttk.Progressbar(self.frame, maximum=100, mode='determinate')
        self.progress.grid(row=5, column=0, columnspan=2, sticky='ew')
        ttk.Label(self.frame, textvariable=self.detail, foreground=COLORS['muted_fg'], wraplength=570).grid(row=6, column=0, columnspan=2, sticky='w', pady=(4,12))
        self.start_button = icon_button(self.frame, text=tr('confirm'), icon='check', command=self.confirm)
        self.start_button.grid(row=7, column=0, columnspan=2, sticky='e')
        self.start_button.state(['disabled'])
        self.entry.bind('<Return>', lambda event: self.start())
        self.folder.trace_add('write', self.folder_changed)
        self.fit_window(center=True)
        root.deiconify()
        self.detect_job = root.after(50, self.detect)

    def fit_window(self, center=False):
        self.root.update_idletasks()
        width, height = self.frame.winfo_reqwidth(), self.frame.winfo_reqheight()
        x = (self.root.winfo_screenwidth() - width) // 2 if center else self.root.winfo_x()
        y = (self.root.winfo_screenheight() - height) // 2 if center else self.root.winfo_y()
        x = max(0, min(x, self.root.winfo_screenwidth() - width))
        y = max(0, min(y, self.root.winfo_screenheight() - height))
        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def detect(self):
        self.detect_job = None

        if self.busy:
            return

        archive = find_archive(read_settings(self.directory))

        if archive and (archive.parent / 'Mewgenics.exe').is_file():
            self.folder.set(str(archive.parent))
            self.start()
        else:
            self.status.set(tr('setup_choose_folder'))
            self.entry.focus_set()
            self.fit_window()

    def browse(self):
        selected = filedialog.askdirectory(parent=self.root, title=tr('choose_game_folder'), initialdir=self.folder.get() or None)

        if selected:
            self.folder.set(selected)
            self.status.set(tr('setup_choose_folder'))
            self.status_label.configure(foreground=COLORS['fg'])
            self.start()

    def folder_changed(self, *args):
        if self.folder_job is not None:
            self.root.after_cancel(self.folder_job)

        self.prepared = None
        self.start_button.state(['disabled'])
        self.status.set(tr('setup_choose_folder'))
        self.detail.set('')
        self.progress['value'] = 0

        def check():
            self.folder_job = None
            folder = Path(self.folder.get().strip()).expanduser()

            if (folder / 'Mewgenics.exe').is_file() and any((folder / name).is_file() for name in ('resources.gpak',)):
                self.start()

        self.folder_job = self.root.after(350, check)

    def confirm(self):
        if not self.busy and self.prepared is not None:
            try:
                update_settings(self.directory, 'setup_complete', True)
            except OSError as exc:
                self.status.set(tr('setup_failed', value0=str(exc)))
                self.status_label.configure(foreground=COLORS['error_fg'])
                self.fit_window()
                return

            self.finish(self.prepared)

    def start(self):
        if self.busy:
            return

        if self.folder_job is not None:
            self.root.after_cancel(self.folder_job)
            self.folder_job = None

        self.prepared = None
        self.start_button.state(['disabled'])
        folder = Path(self.folder.get().strip()).expanduser()
        archive = next((folder / name for name in ('resources.gpak',) if (folder / name).is_file()), None)

        if not self.folder.get().strip() or not (folder / 'Mewgenics.exe').is_file() or archive is None:
            self.status.set(tr('setup_invalid_folder'))
            self.status_label.configure(foreground=COLORS['error_fg'])
            self.fit_window()
            return

        folder = folder.resolve()
        self.busy = True
        self.loading_started = time.monotonic()
        self.actual_progress = 0
        self.extraction_needed = False
        self.pending_result = None
        self.progress['value'] = 0
        self.status_label.configure(foreground=COLORS['fg'])

        for widget in (self.entry, self.browse_button, self.start_button):
            widget.state(['disabled'])

        def report(value, phase, detail=''):
            self.events.put(('progress', value, phase, detail))

        def prepare():
            try:
                cache = refresh_vanilla(self.directory, archive, self.baseline, preserve_entry_comments, progress=report)
                settings = read_settings(self.directory)
                settings['game_folder'] = str(folder)
                playtest = settings.get('playtest', {})
                playtest = dict(playtest) if isinstance(playtest, dict) else {}
                playtest['executable'] = str(folder / 'Mewgenics.exe')
                settings['playtest'] = playtest
                save_settings(self.directory, settings)
                self.events.put(('done', cache))
            except Exception as exc:
                self.events.put(('error', str(exc)))

        # Keep Tk on its own thread while the archive does shit...
        threading.Thread(target=prepare, name='LitterBox resources', daemon=False).start()
        self.poll_job = self.root.after(30, self.poll)

    def poll(self):
        self.poll_job = None

        while not self.events.empty():
            event = self.events.get_nowait()

            if event[0] == 'progress':
                self.actual_progress = event[1]

                if event[2] in ('setup_reading', 'setup_extracting'):
                    self.extraction_needed = True

                if event[2] != 'setup_ready':
                    self.status.set(tr(event[2]))
                    self.detail.set(event[3])
            elif event[0] == 'done':
                self.pending_result = event[1]
            elif event[0] == 'error':
                self.busy = False

                if self.closing:
                    self.finish(None)
                    return

                self.status.set(tr('setup_failed', value0=event[1]))
                self.status_label.configure(foreground=COLORS['error_fg'])
                self.detail.set('')

                for widget in (self.entry, self.browse_button):
                    widget.state(['!disabled'])

                self.fit_window()
                return

        elapsed = time.monotonic() - self.loading_started
        duration = self.MIN_LOADING_SECONDS if self.extraction_needed else 0

        # Slow down extraction a little so it isn't done TOO quickly, (but still let cached stuff finish straight away...)
        displayed = min(self.actual_progress, 95 * min(1, elapsed / duration)) if duration else self.actual_progress
        self.progress['value'] = max(float(self.progress['value']), displayed)

        if self.pending_result is not None and (self.closing or elapsed >= duration):
            self.busy = False

            if self.closing:
                self.finish(None)
                return

            self.prepared = self.pending_result
            self.progress['value'] = 100
            self.status.set(tr('setup_ready'))
            self.detail.set('')

            for widget in (self.entry, self.browse_button, self.start_button):
                widget.state(['!disabled'])

            self.start_button.focus_set()
            self.fit_window()
            return

        self.fit_window()
        self.poll_job = self.root.after(30, self.poll)

    def finish(self, result):
        if self.folder_job is not None:
            self.root.after_cancel(self.folder_job)
            self.folder_job = None

        if self.detect_job is not None:
            self.root.after_cancel(self.detect_job)
            self.detect_job = None

        if self.poll_job is not None:
            self.root.after_cancel(self.poll_job)
            self.poll_job = None

        self.result = result
        self.root.withdraw()
        self.frame.destroy()
        self.finished.set(True)

    def close(self):
        if self.busy:
            self.closing = True
            self.root.withdraw()
        else:
            self.finish(None)

    def run(self):
        self.root.wait_variable(self.finished)
        return self.result