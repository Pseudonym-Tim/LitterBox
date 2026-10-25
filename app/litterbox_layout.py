"""Build main editor widgets, load definitions and settings, wire up events..."""
import copy
import tkinter as tk
from tkinter import ttk

from app import litterbox_dialogs as messagebox
from app.litterbox_metadata import load_sizes, category_names, merge_mod_assets, palette, preserve_entry_comments
from app.litterbox_format import Level
from app.litterbox_language import UIStringVar, load_language, tr, translated_values
from app.litterbox_config import ROOT, read_settings, settings_section
from app.version import versioned_title
from app.litterbox_resources import find_archive, refresh_vanilla
from app.litterbox_ui import BUTTON_ICONS, COLORS as UI_COLORS, apply_dark_theme, configure_app_window, icon_button, icon_image

class EditorLayout:
    def initialize_editor(self, root, resources, icons):
        self.root, self.resources, self.icons = root, resources, icons

        configure_app_window(root)

        load_language(ROOT, read_settings(ROOT).get('language', 'en'))
        self.style = getattr(root, '_litterbox_style', None) or apply_dark_theme(root)
        use_local_metadata = resources is None

        if use_local_metadata:
            resources = ROOT / 'app/cache/vanilla_resources'

        prepared = getattr(root, '_prepared_resources', None)

        if use_local_metadata and prepared is not None:
            resources = prepared
        elif use_local_metadata:
            archive = find_archive(read_settings(ROOT))

            if archive:
                try:
                    resources = refresh_vanilla(ROOT, archive, preserve_comments=preserve_entry_comments)
                except (OSError, ValueError) as exc:
                    root.after_idle(lambda detail=str(exc): messagebox.showwarning(tr('vanilla_resources_unavailable'), tr('vanilla_refresh_failed', value0=detail)))

        self.resources = resources
        
        metadata = {
            layer: ROOT / 'data' / filename if use_local_metadata and (ROOT / 'data' / filename).exists() else resources / 'data' / filename
            for layer, filename in [('spawns', 'spawns.gon'), ('tiles', 'tiles.gon')]
        }

        self.defs = {}

        for layer, path in metadata.items():
            vanilla_path = resources / 'data' / ('spawns.gon' if layer == 'spawns' else 'tiles.gon')
            self.defs[layer] = palette(vanilla_path) if vanilla_path.is_file() else {}
            self.defs[layer].update(palette(path))

        self.character_sizes = load_sizes(resources)
        self.category_names = {layer: category_names(path) for layer, path in metadata.items()}
        self.base_definitions = copy.deepcopy(self.defs)
        self.base_categories = copy.deepcopy(self.category_names)
        self.mod_profiles = []

        try:
            profiles = settings_section(ROOT, 'mods', list)
            self.defs, self.category_names, conflicts = merge_mod_assets(self.base_definitions, self.base_categories, profiles, icons)
            self.mod_profiles = profiles
        except Exception as exc:
            root.after_idle(lambda detail=str(exc): messagebox.showwarning(tr('mod_assets_unavailable'), tr('using_vanilla_assets', value0=detail)))

        self.category_labels = {}
        self.level = Level.blank()
        self.path = None
        self.dirty = False
        self.undo_stack = []
        self.redo_stack = []
        self.cache = {}
        self.selected = 1
        self.stroke = False

        root.title(versioned_title(tr('litterbox_level_editor')))
        root.geometry('1080x790')

        toolbar = ttk.Frame(root, padding=8)
        toolbar.pack(fill='x')
        file_toolbar = ttk.Frame(toolbar)
        file_toolbar.grid(row=0, column=0, sticky='w')

        toolbar_buttons = [
            ('new', self.new),
            ('open_lvl', self.open),
            ('save', self.save),
            ('save_as', lambda: self.save(True)),
            ('mod_assets', self.show_mod_assets),
            ('playtest', self.show_playtest),
            ('help', self.show_help),
            ('about', self.show_about),
        ]

        for label, command in toolbar_buttons:
            icon_button(file_toolbar, text=tr(label), icon=BUTTON_ICONS.get(label), command=command).pack(side='left', padx=3)

        self.layer = UIStringVar(value='spawns')
        self.tool = UIStringVar(value='paint')
        self.allow_overlaps = tk.BooleanVar(value=False)
        self.wave_view = UIStringVar(value='all_waves')
        self.wave = tk.StringVar(value='0')
        self.spawn_mode = UIStringVar(value='fixed')
        self.shared_roll = tk.StringVar(value='0')
        self.random_choices = ()

        self.target_index = None
        self.target_candidates = []
        self.target_layer = None
        self.target_cell = None
        self.target_position = 0
        self.brush_layer = 'spawns'
        self.brush_states = {}

        self.placement_label = tk.StringVar(value=tr('brush_for_new_placements'))
        self.choice_summary = tk.StringVar()
        self.random_preview = None
        self.hover_cell = None
        self.last_hover_cell = None

        editing_toolbar = ttk.Frame(toolbar)
        editing_toolbar.grid(row=0, column=1, sticky='w', padx=(32, 0))

        for label, command in [('undo', self.undo), ('redo', self.redo)]:
            icon_button(editing_toolbar, text=tr(label), icon=BUTTON_ICONS.get(label), command=command).pack(side='left', padx=3)

        ttk.Label(editing_toolbar, text=tr('mode')).pack(side='left', padx=(12, 4))
        self.mode_selector = ttk.Combobox(editing_toolbar, textvariable=self.tool, values=translated_values(['paint', 'inspect'], self.tool), state='readonly', width=8)
        self.mode_selector.pack(side='left', padx=3)
        self.mode_selector.bind('<<ComboboxSelected>>', self.change_mode)
        self.overlap_checkbox = ttk.Checkbutton(editing_toolbar, text=tr('allow_overlaps'), style='Clean.TCheckbutton', variable=self.allow_overlaps, command=self.draw_placement_preview)
        self.overlap_checkbox.pack(side='left', padx=(12, 3))

        def fit_toolbar(event):
            narrow = event.width < file_toolbar.winfo_reqwidth() + editing_toolbar.winfo_reqwidth() + 48
            row = 1 if narrow else 0

            if int(editing_toolbar.grid_info()['row']) != row:
                editing_toolbar.grid(row=row, column=0 if narrow else 1, columnspan=2 if narrow else 1, padx=0 if narrow else (32, 0), pady=(4, 0) if narrow else 0)

        toolbar.bind('<Configure>', fit_toolbar)
        self.board_origin = (16, 16)
        self.cell_size = 60
        self.resize_job = None
        main = ttk.Frame(root)
        main.pack(fill='both', expand=True)
        left = ttk.Frame(main, padding=(8, 4))
        left.pack(side='left', fill='both', expand=True)
        self.board_frame = left
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)
        self.isometric = tk.BooleanVar(value=False)
        self.projected_icons = {}
        self.drawing_board = False
        self.zoom = tk.DoubleVar(value=1.0)
        self.zoom_text = tk.StringVar(value=tr('zoom_percentage', value0=100))
        zoom_controls = ttk.Frame(left)
        zoom_controls.grid(row=0, column=0, sticky='ew', pady=(0, 4))
        zoom_controls.columnconfigure(5, weight=1)
        ttk.Label(zoom_controls, text=tr('zoom')).grid(row=0, column=0, padx=(0, 8))
        self.zoom_slider = ttk.Scale(zoom_controls, from_=1, to=3, variable=self.zoom, length=175, command=self.change_zoom)
        self.zoom_slider.grid(row=0, column=1, sticky='w')
        self.zoom_slider.bind('<Button-1>', self.drag_zoom)
        self.zoom_slider.bind('<B1-Motion>', self.drag_zoom)
        ttk.Label(zoom_controls, textvariable=self.zoom_text, width=5, anchor='w').grid(row=0, column=2, sticky='w', padx=(6, 6))
        icon_button(zoom_controls, text=tr('fit'), icon='expand', style='Fit.TButton', command=self.fit_board).grid(row=0, column=3, sticky='w')
        ttk.Checkbutton(zoom_controls, text=tr('isometric'), style='Clean.TCheckbutton', variable=self.isometric, command=self.fit_board).grid(row=0, column=4, sticky='w', padx=(12, 0))
        self.inspect_toolbar = ttk.Frame(left, padding=(0, 0, 0, 4))
        self.inspect_toolbar.grid(row=1, column=0, sticky='ew')
        ttk.Label(self.inspect_toolbar, text=tr('show')).pack(side='left', padx=(4, 4))
        self.wavebox = ttk.Combobox(self.inspect_toolbar, textvariable=self.wave_view, values=translated_values(['all_waves', 'wave:0'], self.wave_view), state='readonly', width=12)
        self.wavebox.pack(side='left')
        self.wavebox.bind('<<ComboboxSelected>>', lambda e: self.draw())
        self.randomize_button = icon_button(self.inspect_toolbar, text=tr('reroll_level_preview'), icon='arrows-rotate', command=self.reroll)
        self.board_viewport = ttk.Frame(left)
        self.board_viewport.grid(row=2, column=0, sticky='nsew')
        self.board_viewport.rowconfigure(0, weight=1)
        self.board_viewport.columnconfigure(0, weight=1)
        self.board_viewport.bind('<Configure>', self.resize_board)
        self.canvas = tk.Canvas(self.board_viewport, bg=UI_COLORS['bg'], highlightthickness=0, borderwidth=0, width=1, height=1)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.board_hscroll = ttk.Scrollbar(self.board_viewport, orient='horizontal', command=self.canvas.xview)
        self.board_vscroll = ttk.Scrollbar(self.board_viewport, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.board_hscroll.set, yscrollcommand=self.board_vscroll.set)
        self.canvas.bind('<Configure>', self.resize_board)
        self.canvas.bind('<Button-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<ButtonRelease-1>', lambda e: setattr(self, 'stroke', False))
        self.canvas.bind('<Button-3>', lambda e: self.press(e, erase=True))
        self.canvas.bind('<B3-Motion>', lambda e: self.drag(e, erase=True))
        self.canvas.bind('<ButtonRelease-3>', lambda e: setattr(self, 'stroke', False))
        self.canvas.bind('<Button-2>', self.pick)
        self.canvas.bind('<MouseWheel>', self.wheel_zoom)
        self.canvas.bind('<Motion>', self.hover_board)
        self.canvas.bind('<Leave>', self.leave_board)
        controls = self.spawn_controls = ttk.LabelFrame(left, text=tr('spawn_placement'), padding=(6, 3))
        controls.grid(row=3, column=0, sticky='ew', pady=(4, 0))
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, textvariable=self.placement_label).grid(row=0, column=0, columnspan=4, sticky='w')
        self.target_text = tk.StringVar()
        self.targetbox = ttk.Label(controls, textvariable=self.target_text)
        self.targetbox.grid(row=1, column=0, columnspan=2, sticky='w', pady=(1, 3))
        self.target_nav = ttk.Frame(controls)
        self.target_nav.grid(row=1, column=2, columnspan=2, sticky='e')
        icon_button(self.target_nav, text=tr('previous'), icon='arrow-left', command=lambda: self.cycle_target(-1)).pack(side='left', padx=3)
        icon_button(self.target_nav, text=tr('next'), icon='arrow-right', command=lambda: self.cycle_target(1)).pack(side='left')
        timing = self.timing_controls = ttk.Frame(controls)
        timing.grid(row=2, column=0, sticky='w', padx=(0, 12))
        ttk.Label(timing, text=tr('wave')).pack(side='left')
        self.wave_input = ttk.Spinbox(timing, from_=0, to=255, textvariable=self.wave, width=3, style='Compact.TSpinbox', command=self.placement_setting_changed)
        self.wave_input.pack(side='left', padx=4)
        ttk.Label(timing, text=tr('wave_hint')).pack(side='left')
        choice = self.choice_controls = ttk.Frame(controls)
        choice.grid(row=2, column=1, sticky='w')
        ttk.Label(choice, text=tr('placement')).pack(side='left')
        self.modebox = ttk.Combobox(choice, values=translated_values(['fixed', 'random_choices'], self.spawn_mode), textvariable=self.spawn_mode, state='readonly', width=15)
        self.modebox.pack(side='left', padx=4)
        self.modebox.bind('<<ComboboxSelected>>', self.placement_mode_changed)
        self.choices_button = icon_button(choice, text=tr('edit_choices'), icon='sliders', command=self.edit_choices)
        self.choices_button.pack(side='left', padx=4)
        linking = self.linking_controls = ttk.Frame(controls)
        linking.grid(row=3, column=0, columnspan=2, sticky='w', pady=(3, 0))
        ttk.Label(linking, text=tr('shared_roll')).pack(side='left')
        self.rollbox = ttk.Spinbox(linking, from_=0, to=255, textvariable=self.shared_roll, width=3, style='Compact.TSpinbox', command=self.placement_setting_changed)
        self.rollbox.pack(side='left', padx=4)
        ttk.Label(linking, text=tr('shared_roll_hint')).pack(side='left')
        self.choice_label = ttk.Label(controls, textvariable=self.choice_summary, wraplength=640, justify='left')
        self.choice_label.grid(row=4, column=0, columnspan=4, sticky='w', pady=(3, 0))

        for field in (self.wave_input, self.rollbox):
            field.bind('<Return>', self.placement_setting_changed)
            field.bind('<FocusOut>', self.placement_setting_changed)

        side = ttk.Frame(main, padding=8, width=350)
        side.pack(side='right', fill='y')
        side.pack_propagate(False)
        side.grid_propagate(False)
        side.columnconfigure(0, weight=1)
        side.rowconfigure(4, weight=1)
        search_header = ttk.Frame(side)
        search_header.grid(row=0, column=0, sticky='ew')
        search_header.columnconfigure(1, weight=1)
        self.content_source = UIStringVar(value='all_content')
        self.sourcebox = ttk.Combobox(side, textvariable=self.content_source, values=translated_values(['all_content', 'vanilla_only'], self.content_source), state='readonly')
        self.sourcebox.grid(row=3, column=0, sticky='ew', pady=(6, 0))
        self.sourcebox.bind('<<ComboboxSelected>>', lambda e: self.refresh_palette())
        ttk.Label(search_header, text=tr('layer'), image=icon_image(root, 'layer-group', 16), compound='left').grid(row=0, column=1, sticky='e', padx=(0, 6))
        combo = ttk.Combobox(search_header, textvariable=self.layer, values=translated_values(list(self.defs), self.layer), state='readonly', width=10)
        combo.grid(row=0, column=2, sticky='e')
        combo.bind('<<ComboboxSelected>>', lambda e: self.refresh_palette())
        search_row = ttk.Frame(side)
        search_row.grid(row=1, column=0, sticky='ew', pady=6)
        search_row.columnconfigure(1, weight=1)
        ttk.Label(search_row, text=tr('search'), image=icon_image(root, 'magnifying-glass', 16), compound='left').grid(row=0, column=0, sticky='w', padx=(0, 8))
        self.search = tk.StringVar()
        ttk.Entry(search_row, textvariable=self.search).grid(row=0, column=1, sticky='ew')
        self.search.trace_add('write', lambda *_: self.refresh_palette())
        self.category = UIStringVar(value='all_categories')
        self.catbox = ttk.Combobox(side, textvariable=self.category, state='readonly')
        self.catbox.grid(row=2, column=0, sticky='ew')
        self.catbox.bind('<<ComboboxSelected>>', lambda e: self.refresh_palette(False))
        listing = ttk.Frame(side)
        listing.grid(row=4, column=0, sticky='nsew', pady=6)
        listing.rowconfigure(0, weight=1)
        listing.columnconfigure(0, weight=1)
        ttk.Style(root).configure('Palette.Treeview', rowheight=36)
        self.tree = ttk.Treeview(listing, show='tree', height=12, style='Palette.Treeview')
        self.tree.grid(row=0, column=0, sticky='nsew')
        self.tree.bind('<Configure>', self.fit_search_rows)
        scroll = ttk.Scrollbar(listing, command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(listing, orient='horizontal', command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.tree.bind('<<TreeviewSelect>>', self.select)
        self.tree.bind('<ButtonRelease-1>', self.choose_brush)
        self.tree.bind('<KeyRelease>', self.choose_brush)
        self.tooltip = None
        self.tooltip_after = None
        self.tooltip_row = None
        self.tree.bind('<Motion>', self.hover_palette)
        self.tree.bind('<Leave>', lambda e: self.hide_hint())
        self.tree.bind('<ButtonPress>', lambda e: self.hide_hint(), add='+')
        self.tree.bind('<MouseWheel>', lambda e: self.hide_hint(), add='+')
        self.preview = ttk.Label(side, anchor='center')
        self.preview.grid(row=5, column=0, sticky='ew')
        self.selection_text = tk.StringVar(value=tr('select_a_tile_or_object'))
        ttk.Label(side, textvariable=self.selection_text, wraplength=325, justify='left').grid(row=6, column=0, sticky='ew', pady=4)
        status_row = ttk.Frame(root, padding=8)
        status_row.pack(fill='x')
        self.unsaved_label = ttk.Label(status_row, text=tr('unsaved_changes'), foreground=UI_COLORS['warning_fg'])
        self.status = tk.StringVar()
        self.status_label = ttk.Label(status_row, textvariable=self.status)
        self.status_label.pack(side='left')

        for key, command in [('<Control-o>', self.open), ('<Control-s>', self.save), ('<Control-z>', self.undo), ('<Control-y>', self.redo)]:
            root.bind(key, lambda e, fn=command: fn())

        root.bind('<KeyPress-F6>', self.hotkey_down)
        root.bind('<KeyRelease-F6>', self.hotkey_up)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh_palette()
        self.update_brush_summary()
        self.update_control_visibility()
        self.draw()
        root.update_idletasks()
        # Setup leaves a tiny window, so measure both toolbar groups before that shit wraps...
        toolbar_width = file_toolbar.winfo_reqwidth() + editing_toolbar.winfo_reqwidth() + 64
        minimum_width = max(1080, toolbar_width, controls.winfo_reqwidth() + side.winfo_reqwidth() + 32)
        root.minsize(minimum_width, 720)
        root.geometry(f'{minimum_width}x790')
        self.restore_last_level()
