"""Render board art, labels, footprints, hover previews, zoom, and isometric projection..."""
from PIL import Image, ImageChops, ImageTk
from tkinter import font as tkfont

from app.litterbox_metadata import occupied_offsets
from app.litterbox_format import RandomChoice, representative
from app.litterbox_language import tr, translated_values

COLORS = {
    'blue': (0, 0, 255), 'green': (0, 128, 0), 'red': (255, 0, 0), 'cyan': (0, 255, 255),
    'pink': (255, 128, 180), 'purple': (128, 0, 128), 'black': (0, 0, 0), 'grey': (128, 128, 128),
    'white': (255, 255, 255), 'yellow': (255, 255, 0), 'orange': (255, 128, 0), 'brown': (128, 80, 30)
}

class BoardView:
    def footprint(self, layer, ident):
        """Get all cell offsets a spawn or random choice can occupy..."""

        if layer == 'tiles':
            return {(0, 0)}

        candidates = [ident] if isinstance(ident, int) else [i for i, w in ident.choices if i != 0 and w > 0]
        offsets = set()

        for candidate in candidates:
            names = self.defs['spawns'].get(candidate, {}).get('objects', [])

            if not names:
                offsets.add((0, 0))

            for name in names:
                offsets.update(occupied_offsets(self.character_sizes.get(name, (1, 1))))

        return offsets or {(0, 0)}

    def indicator_position(self, cell, layer, ident):
        """Put our nice little magenta labels at footprint corner..."""

        x, y = cell
        s = self.cell_size
        ox, oy = self.board_origin
        offsets = self.footprint(layer, ident)

        if self.isometric.get():
            corners = {
                (ox + (x + dx + cx) * s, oy + (self.level.header[2] - y - dy - 1 + cy) * s)
                for dx, dy in offsets for cx, cy in ((0, 0), (1, 0), (1, 1), (0, 1))
            }

            return max(corners, key=lambda point: (self.project_point(*point)[0], -self.project_point(*point)[1]))

        return (ox + (x + max(dx for dx, dy in offsets) + 1) * s - 3, oy + (self.level.header[2] - y - max(dy for dx, dy in offsets) - 1) * s + 3)

    def hover_board(self, event):
        hovered = self.cell(event)

        if hovered is not None:
            self.last_hover_cell = hovered

        if hovered != self.hover_cell:
            self.hover_cell = hovered
            self.draw_placement_preview()

    def leave_board(self, event=None):
        if self.hover_cell is not None:
            self.last_hover_cell = self.hover_cell

        self.hover_cell = None
        self.canvas.delete('placement_preview')

    def outline_footprint(self, cell, layer, ident, tag, color='#79db9c'):
        x, y = cell
        ox, oy = self.board_origin
        s = self.cell_size
        w, h = self.level.header[1:3]
        occupied = {(x + dx, y + dy) for dx, dy in self.footprint(layer, ident)}
        edges = set()

        for cx, cy in occupied:
            # Don't draw borders between adjacent occupied cells....
            if (cx, cy - 1) not in occupied:
                edges.add(((cx, cy), (cx + 1, cy)))

            if (cx + 1, cy) not in occupied:
                edges.add(((cx + 1, cy), (cx + 1, cy + 1)))

            if (cx, cy + 1) not in occupied:
                edges.add(((cx + 1, cy + 1), (cx, cy + 1)))

            if (cx - 1, cy) not in occupied:
                edges.add(((cx, cy + 1), (cx, cy)))

        outline_color = color if all(0 <= cx < w and 0 <= cy < h for cx, cy in occupied) else '#ff6868'

        while edges:
            start, current = edges.pop()
            points = [start, current]

            while current != start:
                following = next((edge for edge in edges if edge[0] == current), None)

                if following is None:
                    break

                edges.remove(following)
                current = following[1]
                points.append(current)

            coordinates = [value for px, py in points for value in (ox + px * s, oy + (h - py) * s)]
            self.canvas.create_line(*coordinates, fill=outline_color, width=2, joinstyle='round', tags=tag)

    def draw_placement_preview(self):
        c = self.canvas
        c.delete('placement_preview')

        if self.hover_cell is None:
            return

        layer = self.layer.get()

        if self.tool.get() == 'inspect':
            cell = self.hover_cell

            if layer == 'tiles':
                ident = self.level.tiles[cell[1] * self.level.header[1] + cell[0]]

                if ident == 0:
                    return
            else:
                hits = self.spawn_hits(cell)

                if not hits:
                    return

                shown = self.wave_view.get()
                index = next((i for i in hits if shown == f'wave:{self.level.spawns[i].wave}'), hits[-1])
                spawn = self.level.spawns[index]
                cell, ident = (spawn.x, spawn.y), spawn.ident

            self.outline_footprint(cell, layer, ident, 'placement_preview', '#79db9c')

            if not self.drawing_board:
                self.project_canvas_items(c.find_withtag('placement_preview'))

            return

        try:
            ident = self.brush_ident()
        except ValueError:
            return

        if ident == 0:
            return

        x, y = self.hover_cell
        ox, oy = self.board_origin
        s = self.cell_size
        h = self.level.header[2]
        im = self.icon(layer, representative(ident), s, 0.55)

        if im:
            c.create_image(ox + (x + .5) * s, oy + (h - y - .5) * s, image=im, tags=('placement_preview', 'placement_preview_image'))

            if layer == 'tiles' and c.find_withtag('spawn_art'):
                c.tag_lower('placement_preview_image', 'spawn_art')

        try:
            blocked = self.blocked_brush((x, y)) if layer == 'spawns' else False
        except ValueError:
            blocked = False

        self.outline_footprint((x, y), layer, ident, 'placement_preview', '#ff6868' if blocked else '#79db9c')

        if not self.drawing_board:
            self.project_canvas_items(c.find_withtag('placement_preview'))

    def icon(self, layer, ident, scale, opacity=1.0, brightness=1.0):
        key = (layer, ident, scale, opacity, brightness)

        if key in self.cache:
            return self.cache[key]

        definition = self.defs[layer].get(ident)

        if not definition:
            return None

        source_key = ('source', layer, ident)
        composed = self.cache.get(source_key)

        if composed is None:
            layers = []

            for index, name in enumerate(definition['images']):
                path = next((folder / name for folder in definition.get('_icon_dirs', [self.icons]) if (folder / name).is_file()), None)

                if path is None:
                    continue

                im = Image.open(path).convert('RGBA')
                pixels = list(im.getdata())
                im.putdata([(r, g, b, 0 if (r, g, b) == (255, 0, 255) else a) for r, g, b, a in pixels])
                tint = definition['tints'][index] if index < len(definition['tints']) else 'none'
                color = COLORS.get(tint) if isinstance(tint, str) else tint

                if color:
                    alpha = im.getchannel('A')
                    im = ImageChops.multiply(im.convert('RGB'), Image.new('RGB', im.size, color)).convert('RGBA')
                    im.putalpha(alpha)

                layers.append(im)

            if not layers:
                return None

            composed = Image.new('RGBA', (max(im.width for im in layers), max(im.height for im in layers)))

            for im in layers:
                composed.alpha_composite(im, ((composed.width - im.width) // 2, (composed.height - im.height) // 2))

            self.cache[source_key] = composed

        # Scale, preserve transparency and alignment...
        composed = composed.resize((max(1, round(composed.width * scale / 128)), max(1, round(composed.height * scale / 128))), Image.Resampling.LANCZOS)

        if brightness < 1.0:
            alpha = composed.getchannel('A')
            composed = composed.convert('RGB').point(lambda value: round(value * brightness)).convert('RGBA')
            composed.putalpha(alpha)

        if opacity < 1.0:
            composed.putalpha(composed.getchannel('A').point(lambda alpha: round(alpha * opacity)))

        photo = ImageTk.PhotoImage(composed)
        self.cache[key] = photo

        return photo

    def wheel_zoom(self, event):
        if not event.delta:
            return 'break'

        steps = event.delta / 120
        self.zoom.set(max(1.0, min(3.0, round(self.zoom.get() + steps * 0.1, 2))))
        self.change_zoom()

        return 'break'

    def drag_zoom(self, event):
        slider = self.zoom_slider

        # (Count thumb width so it actually reaches both ends...)
        margin = 7
        fraction = max(0.0, min(1.0, (event.x - margin) / max(1, slider.winfo_width() - 2 * margin)))
        self.zoom.set(float(slider.cget('from')) + fraction * (float(slider.cget('to')) - float(slider.cget('from'))))
        self.change_zoom()

        return 'break'

    def change_zoom(self, value=None):
        factor = self.zoom.get()
        self.zoom_text.set(tr('zoom_percentage', value0=factor * 100))
        self.resize_board(None)

    def fit_board(self):
        self.zoom.set(1.0)
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.change_zoom()

    def board_geometry(self, w, h):
        width = max(1, self.board_viewport.winfo_width())
        height = max(1, self.board_viewport.winfo_height())
        span_w, span_h = (w + h, (w + h) / 2) if self.isometric.get() else (w, h)
        size = max(1, int(min((width - 32) / span_w, (height - 16) / span_h) * self.zoom.get()))
        horizontal = vertical = False

        for _ in range(3):
            available_w = width - (self.board_vscroll.winfo_reqwidth() if vertical else 0)
            available_h = height - (self.board_hscroll.winfo_reqheight() if horizontal else 0)
            horizontal = span_w * size + 32 > available_w
            vertical = span_h * size + 16 > available_h

        if horizontal:
            if self.board_hscroll.winfo_manager() != 'grid':
                self.board_hscroll.grid(row=1, column=0, sticky='ew')
        else:
            if self.board_hscroll.winfo_manager() == 'grid':
                self.board_hscroll.grid_remove()

            self.canvas.xview_moveto(0)

        if vertical:
            if self.board_vscroll.winfo_manager() != 'grid':
                self.board_vscroll.grid(row=0, column=1, sticky='ns')
        else:
            if self.board_vscroll.winfo_manager() == 'grid':
                self.board_vscroll.grid_remove()

            self.canvas.yview_moveto(0)

        content_w = max(available_w, span_w * size + 32)
        content_h = max(available_h, span_h * size + 16)
        self.canvas.configure(scrollregion=(0, 0, content_w, content_h))

        return size, ((content_w - span_w * size) / 2, (content_h - span_h * size) / 2)

    def project_point(self, px, py):
        ox, oy = self.board_origin
        w = self.level.header[1]
        u, v = px - ox, py - oy
        return ox + u + v, oy + (w * self.cell_size - u + v) / 2

    def project_canvas_items(self, items):
        if not self.isometric.get():
            return

        for item in items:
            coordinates = self.canvas.coords(item)

            projected = [
                value for i in range(0, len(coordinates), 2)
                for value in self.project_point(coordinates[i], coordinates[i + 1])
            ]

            self.canvas.coords(item, *projected)

            if set(self.canvas.gettags(item)) & {'spawn_indicator', 'random_indicator'}:
                self.canvas.move(item, -3, 3)

            if self.canvas.type(item) == 'image':
                original = str(self.canvas.itemcget(item, 'image'))

                if original not in self.projected_icons:
                    photo = next((photo for photo in self.cache.values() if str(photo) == original), None) # (Grab the image we already cached)...

                    if photo is None:
                        continue

                    source = ImageTk.getimage(photo)
                    width, height = source.size
                    out_width = width + height
                    out_height = max(1, (width + height) // 2)
                    transformed = source.transform((out_width, out_height), Image.Transform.AFFINE, (0.5, -1, width / 2, 0.5, 1, -width / 2), resample=Image.Resampling.BICUBIC)
                    self.projected_icons[original] = ImageTk.PhotoImage(transformed, master=self.root)

                self.canvas.itemconfigure(item, image=self.projected_icons[original])

    def settle_board_layout(self):
        self.canvas.grid(row=0, column=0, sticky='nsew')

    def resize_board(self, event):
        if self.resize_job is not None:
            self.root.after_cancel(self.resize_job)

        self.resize_job = self.root.after_idle(self.redraw_board)

    def redraw_board(self):
        self.resize_job = None
        self.draw()
        self.root.after_idle(self.settle_board_layout) # (Let the scrollbar geometry finish before fitting the board...)

    def fallback_label(self, layer, ident, size=None):
        name = self.defs[layer].get(ident, {}).get('name', tr('unknown'))
        words = name.split() or ['unknown']
        candidates = set()

        for limit in range(1, len(name) + 1):
            lines = []

            for word in words:
                if lines and len(lines[-1]) + len(word) + 1 <= limit:
                    lines[-1] += ' ' + word
                else:
                    lines.append(word)

            candidates.add('\n'.join(lines + [f'[{ident}]']))

        size = size if size is not None else self.cell_size

        scored = []

        # Pick wrap that lets us use biggest readable text!
        for text in candidates:
            lines = text.split('\n')
            font_size = abs(self.fallback_id_font(text, size).cget('size'))
            score = (font_size, -len(lines), -max(map(len, lines)), text)
            scored.append((score, text))

        return max(scored)[1]

    def fallback_id_font(self, text, size):
        fonts = getattr(self, 'fallback_fonts', None)

        if fonts is None:
            self.fallback_fonts = fonts = {}

        isometric = self.isometric.get()
        pixels = max(1, int(size * (0.4 if isometric else 0.28)))

        while True:
            if pixels not in fonts:
                fonts[pixels] = tkfont.Font(root=self.root, family='Sour Gummy', size=-pixels, weight='bold')

            font = fonts[pixels]
            width = max(font.measure(line) for line in text.split('\n')) + 4
            height = font.metrics('linespace') * len(text.split('\n')) + 4

            # Account for the slanted sides so text doesn't get too close to edges...
            fits = width / 2 + height <= size * 0.9 if isometric else width <= size * 0.85 and height <= size * 0.75

            if pixels == 1 or fits:
                return font

            pixels -= 1

    def draw(self):
        """Draw the whole fucking board and all the shit on it!"""

        self.drawing_board = True
        has_random = any(isinstance(tile, RandomChoice) for tile in self.level.tiles) or any(isinstance(spawn.ident, RandomChoice) for spawn in self.level.spawns)

        if has_random:
            self.randomize_button.pack(side='left', padx=(12, 6))
        else:
            self.randomize_button.pack_forget()

        c = self.canvas
        c.delete('all')
        w, h = self.level.header[1:3]
        tile_brightness = 1.0
        spawn_opacity = 0.5 if self.layer.get() == 'tiles' else 1.0
        tile_indicator_color = '#ff00ff' if self.layer.get() == 'tiles' else '#bf00bf'
        spawn_indicator_color = '#ff00ff' if self.layer.get() == 'spawns' else '#bf00bf'

        # Fade inactive labels toward the board gray...
        tile_label_color = '#202020' if self.layer.get() == 'tiles' else '#353637'
        spawn_label_color = '#202020' if self.layer.get() == 'spawns' else '#353637'
        s, origin = self.board_geometry(w, h)
        self.cell_size = s
        ox, oy = self.board_origin = origin
        c.create_polygon(ox, oy, ox + w * s, oy, ox + w * s, oy + h * s, ox, oy + h * s, fill='#73777d', outline='')

        for y in range(h):
            for x in range(w):
                ident = self.level.tiles[y * w + x]
                shown_id = self.random_preview['tiles'][y * w + x] if self.random_preview else representative(ident)

                if shown_id:
                    im = self.icon('tiles', shown_id, s, brightness=tile_brightness)

                    if im:
                        c.create_image(ox + (x + .5) * s, oy + (h - y - .5) * s, image=im, tags='tile_art')
                    else:
                        text = self.fallback_label('tiles', shown_id, s)
                        text_x = ox + (x + 0.5) * s
                        text_y = oy + (h - y - 0.5) * s
                        formatted_text = tr(text)
                        text_font = self.fallback_id_font(text, s)
                        c.create_text(text_x, text_y, text=formatted_text, justify='center', fill=tile_label_color, font=text_font, tags=('tile_art', 'fallback_label'))

        groups = sorted({0} | {spawn.wave for spawn in self.level.spawns})
        view_groups = set(groups)

        if self.wave_view.get().startswith('wave:'):
            view_groups.add(int(self.wave_view.get()[5:]))

        try:
            brush_wave = int(self.wave.get())

            if 0 <= brush_wave <= 255:
                view_groups.add(brush_wave)
        except ValueError:
            pass

        self.wavebox['values'] = translated_values(['all_waves'] + [f'wave:{group}' for group in sorted(view_groups)], self.wave_view)
        spawn_order = list(enumerate(self.level.spawns))

        if self.isometric.get():
            spawn_order.sort(key=lambda entry: -entry[1].x - entry[1].y)

        for index, spawn in spawn_order:
            x, y, ident = spawn
            brightness = 1.0 if self.wave_view.get() in ('all_waves', f'wave:{spawn.wave}') else 0.35
            shown_id = self.random_preview['spawns'][index] if self.random_preview else representative(ident)
            im = self.icon('spawns', shown_id, s, opacity=spawn_opacity, brightness=brightness) if shown_id else None

            if im:
                c.create_image(ox + (x + .5) * s, oy + (h - y - .5) * s, image=im, tags='spawn_art')
            elif shown_id:
                text = self.fallback_label('spawns', shown_id, s)
                text_x = ox + (x + .5) * s
                text_y = oy + (h - y - .5) * s
                label_text = tr(text)
                label_font = self.fallback_id_font(text, s)
                label_tags = ('spawn_art', 'fallback_label')
                c.create_text(text_x, text_y, text=label_text, justify='center', fill=spawn_label_color, font=label_font, tags=label_tags)

        for y in range(h):
            for x in range(w):
                if self.tool.get() == 'inspect' and isinstance(self.level.tiles[y * w + x], RandomChoice):
                    position = self.indicator_position((x, y), 'tiles', self.level.tiles[y * w + x])
                    indicator_text = tr('random_choice_indicator')
                    indicator_font_size = max(9, min(12, s // 5 + 2))
                    indicator_font = ('Sour Gummy', indicator_font_size, 'normal')
                    c.create_text(*position, text=indicator_text, anchor='ne', fill=tile_indicator_color, font=indicator_font, tags='random_indicator')

        for x in range(w + 1):
            c.create_line(ox + x * s, oy, ox + x * s, oy + h * s, fill='#454a51')

        for y in range(h + 1):
            c.create_line(ox, oy + y * s, ox + w * s, oy + y * s, fill='#454a51')

        for spawn in self.level.spawns:
            x, y, ident = spawn
            text = (tr('random_choice_indicator') if isinstance(ident, RandomChoice) else '')

            if len(groups) > 1:
                text += ' ' + tr('wave_indicator', value0=spawn.wave)

            if text and self.tool.get() == 'inspect':
                position = self.indicator_position((x, y), 'spawns', ident)
                anchor = 'ne'
                spawn_text = tr(text.strip())
                spawn_font_size = max(9, min(12, s // 5 + 2))
                spawn_font = ('Sour Gummy', spawn_font_size, 'normal')
                spawn_tags = 'spawn_indicator'
                c.create_text(*position, text=spawn_text, anchor=anchor, fill=spawn_indicator_color, font=spawn_font, tags=spawn_tags)

        if self.target_cell is not None and self.target_layer == self.layer.get():
            self.outline_footprint(self.target_cell, self.target_layer, self.target_ident(), 'inspection_outline', '#f2cf55')

        c.create_polygon(ox, oy, ox + w * s, oy, ox + w * s, oy + h * s, ox, oy + h * s, fill='', outline='#ba5959', width=3)
        c.tag_raise('inspection_outline')
        tile_count = sum(any(ident != 0 and weight > 0 for ident, weight in tile.choices) if isinstance(tile, RandomChoice) else tile != 0 for tile in self.level.tiles)

        if self.dirty:
            self.unsaved_label.pack(side='left', before=self.status_label, padx=(0, 4))
        else:
            self.unsaved_label.pack_forget()

        self.status.set(tr('level_status_counts', value0=self.path.name if self.path else tr('untitled'), value1=tile_count, value2=len(self.level.spawns)))
        self.draw_placement_preview()
        self.drawing_board = False
        self.project_canvas_items(self.canvas.find_all())

    def cell(self, event):
        s = self.cell_size
        ox, oy = self.board_origin
        px, py = (self.canvas.canvasx(0) + event.x - ox) / s, (self.canvas.canvasy(0) + event.y - oy) / s

        if self.isometric.get():
            py -= self.level.header[1] / 2
            px, py = px / 2 - py, px / 2 + py

        x, y = int(px // 1), int(py // 1)
        w, h = self.level.header[1:3]

        return (x, h - 1 - y) if 0 <= x < w and 0 <= y < h else None