"""Filter tile/spawn search lists, size rows, and show item previews, details, and hover hints..."""
import tkinter as tk
from PIL import Image, ImageTk
from pathlib import Path
from tkinter import font as tkfont, ttk

from app.litterbox_language import display_token, tr, translated_values
from app.litterbox_playtest import mod_folder_path

class PaletteControls:
    def palette_icon(self, layer, ident, size=32):
        key = ('palette', layer, ident, size)

        if key in self.cache:
            return self.cache[key]

        source = self.icon(layer, ident, 128)

        if source is None:
            return None

        im = ImageTk.getimage(source)
        bounds = im.getbbox()

        if bounds:
            im = im.crop(bounds)

        im.thumbnail((size, size), Image.Resampling.LANCZOS)
        slot = Image.new('RGBA', (size, size))
        slot.alpha_composite(im, ((size - im.width) // 2, (size - im.height) // 2))
        photo = ImageTk.PhotoImage(slot)
        self.cache[key] = photo

        return photo

    def fit_search_rows(self, event=None):
        pending = getattr(self, 'search_layout_job', None)

        if pending is not None:
            self.root.after_cancel(pending)

        self.search_layout_job = self.root.after_idle(self.settle_search_rows)

    def settle_search_rows(self):
        self.search_layout_job = None

        # (Wait for sidebar to settle before sizing rows...)
        height = max(1, self.tree.winfo_height() - 4)
        rowheight = min(range(36, 45), key=lambda size: (height % size, abs(size - 36)))

        if int(self.style.lookup('Palette.Treeview', 'rowheight')) != rowheight:
            self.style.configure('Palette.Treeview', rowheight=rowheight)

            # Just punt Tk's stale row layout so it fixes itself...
            self.tree.configure(height=max(1, height // rowheight))

    def hide_hint(self):
        if self.tooltip_after is not None:
            self.root.after_cancel(self.tooltip_after)
            self.tooltip_after = None

        if self.tooltip is not None:
            self.tooltip.destroy()
            self.tooltip = None

        self.tooltip_row = None

    def hover_palette(self, event):
        row = self.tree.identify_row(event.y)

        if row == self.tooltip_row:
            return

        self.hide_hint()

        if not row:
            return

        self.tooltip_row = row
        layer = self.layer.get()
        x, y = event.x_root, event.y_root

        def show():
            self.tooltip_after = None
            d = self.defs[layer][int(row)]
            tip = self.tooltip = tk.Toplevel(self.root)
            tip.overrideredirect(True)
            text = f'{d["name"]}  [{row}]\n{self.category_label(layer, d["category"])}'
            ttk.Label(tip, text=tr(text), padding=8, wraplength=350, relief='solid').pack()
            tip.update_idletasks()
            tip.geometry(f'+{max(0, min(x + 12, tip.winfo_screenwidth() - tip.winfo_reqwidth()))}+{max(0, min(y + 18, tip.winfo_screenheight() - tip.winfo_reqheight()))}')

        self.tooltip_after = self.root.after(400, show)

    def category_label(self, layer, category):
        name = self.category_names[layer].get(category)
        return f'{name} [{category}]' if name else tr('category', value0=category)

    def refresh_source_choices(self):
        folders = {
            definition['_mod_folder'] for defs in self.defs.values()
            for definition in defs.values() if definition.get('_mod_folder')
        }

        folders.update(str(mod_folder_path(profile).resolve()) for profile in self.mod_profiles)
        self.source_mods = {}

        for folder in sorted(folders, key=str.casefold):
            name = Path(folder).name
            label = f'mod:{name}'

            if sum(Path(other).name.casefold() == name.casefold() for other in folders) > 1:
                label += f' ({Path(folder).parent})'

            self.source_mods[label] = folder

        values = ['all_content', 'vanilla_only']

        if self.source_mods:
            values += ['modded_only'] + list(self.source_mods)

        self.sourcebox.configure(values=translated_values(values, self.content_source))

        if self.content_source.get() not in values:
            self.content_source.set('all_content')

    def refresh_palette(self, reset=True):
        self.hide_hint()
        layer = self.layer.get()

        if layer != self.brush_layer:
            self.hover_cell = self.hover_cell or self.last_hover_cell
            self.brush_states[self.brush_layer] = (self.selected, self.spawn_mode.get(), self.random_choices, self.shared_roll.get(), self.wave.get())
            self.target_index = None
            self.target_cell = None
            self.target_layer = None
            state = self.brush_states.get(layer, (0 if layer == 'tiles' else 1, 'fixed', (), '0', '0'))
            self.selected, mode, self.random_choices, roll, wave = state
            self.spawn_mode.set(mode)
            self.shared_roll.set(roll)
            self.wave.set(wave)
            self.brush_layer = layer
            self.clear_target()

        self.update_control_visibility()
        self.refresh_source_choices()
        defs = self.defs[self.layer.get()]
        source = self.content_source.get()

        if source in self.source_mods:
            folder = self.source_mods[source]
            defs = {ident: definition for ident, definition in defs.items() if definition.get('_mod_folder') == folder}
        elif source != 'all_content':
            modded = source == 'modded_only'
            defs = {ident: definition for ident, definition in defs.items()
                    if (definition.get('_source') == 'mod') == modded}

        if reset:
            cats = sorted({d['category'] for d in defs.values()}, key=int)
            self.category_labels = {self.category_label(self.layer.get(), cat): cat for cat in cats}
            self.catbox['values'] = translated_values(['all_categories'] + list(self.category_labels), self.category)

            if display_token(self.category.get()) not in self.catbox['values']:
                self.category.set('all_categories')

        self.tree.delete(*self.tree.get_children())
        query = self.search.get().lower()
        width = 280
        font = tkfont.nametofont('TkDefaultFont')

        for ident, d in sorted(defs.items(), key=lambda item: (int(item[1]['category']), item[1]['name'])):
            if query not in f'{ident} {d["name"]}'.lower():
                continue

            if self.category.get() != 'all_categories' and d['category'] != self.category_labels.get(self.category.get()):
                continue

            icon = self.palette_icon(self.layer.get(), ident)
            args = dict(iid=str(ident), text=tr('choice_name_id', value0=d['name'], value1=ident))

            if icon:
                args['image'] = icon

            self.tree.insert('', 'end', **args)
            width = max(width, font.measure(args['text']) + 64)

        self.tree.column('#0', width=width, minwidth=width, stretch=True)

        if self.tree.exists(str(self.selected)):
            self.tree.selection_set(str(self.selected))
            self.select(None)
        else:
            self.preview.configure(image='')
            self.selection_text.set(tr('select_a_tile_or_object'))

        self.fit_search_rows()
        self.draw()

    def choose_brush(self, event):
        if getattr(event, 'num', None) != 1:
            if event.keysym not in ('Up', 'Down', 'Home', 'End', 'Prior', 'next', 'Return', 'space'):
                return
        elif not self.tree.identify_row(event.y):
            return

        if self.tree.selection():
            self.select(event)
            self.spawn_mode.set('fixed')
            self.random_choices = ((self.selected, 1),)
            self.shared_roll.set('0')

            if self.tool.get() == 'inspect':
                self.enter_paint()
            else:
                self.update_brush_summary()
                self.draw()

    def select(self, event):
        if self.tree.selection():
            self.selected = int(self.tree.selection()[0])
            icon = self.palette_icon(self.layer.get(), self.selected, 80)
            self.preview.configure(image=icon or '')
            d = self.defs[self.layer.get()][self.selected]
            description = f'\n\n{d["description"]}' if d.get('description') else ''
            self.selection_text.set(tr('selection_details', value0=d['name'], value1=self.selected, value2=self.category_label(self.layer.get(), d['category']), value3=description))
            self.update_brush_summary()