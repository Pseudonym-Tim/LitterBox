"""Handle painting, inspection, overlap checks, random placement previews, and undo/redo..."""
import copy
import random

from app import litterbox_dialogs as messagebox
from app.litterbox_format import RandomChoice, Spawn, representative, roll_choice, uint
from app.litterbox_language import tr

class EditingControls:
    def update_control_visibility(self):
        inspecting = self.tool.get() == 'inspect'
        self.overlap_checkbox.pack(side='left', padx=(12, 3))

        if inspecting:
            self.inspect_toolbar.grid()
        else:
            self.inspect_toolbar.grid_remove()

        self.spawn_controls.configure(text=tr('tile_placement' if self.layer.get() == 'tiles' else 'spawn_placement'))

        if self.layer.get() == 'spawns':
            self.timing_controls.grid()
        else:
            self.timing_controls.grid_remove()

        if inspecting and self.target_cell is not None:
            self.spawn_controls.grid()
        else:
            self.spawn_controls.grid_remove()

        self.update_brush_summary()
        self.draw()

    def occupied_cells(self, cell, ident):
        if ident == 0:
            return set()

        if isinstance(ident, RandomChoice) and not any(i and weight > 0 for i, weight in ident.choices):
            return set()

        return {(cell[0] + dx, cell[1] + dy) for dx, dy in self.footprint('spawns', ident)}

    def overlaps_spawn(self, cell, ident, ignored=()):
        if self.allow_overlaps.get():
            return False

        cells = self.occupied_cells(cell, ident)

        return any(index not in ignored and cells & self.occupied_cells((spawn.x, spawn.y), spawn.ident) for index, spawn in enumerate(self.level.spawns))

    def blocked_brush(self, cell):
        if self.layer.get() != 'spawns' or self.allow_overlaps.get():
            return False

        ident = self.brush_ident()

        return self.overlaps_spawn(cell, ident)

    def spawn_name(self, ident):
        return self.defs[self.layer.get()].get(ident, {}).get('name', tr('unknown_id', value0=ident))

    def target_ident(self):
        if self.target_cell is None:
            return None

        if self.target_layer == 'tiles':
            return self.level.tiles[self.target_index]

        if self.target_index is None:
            return 0

        return self.level.spawns[self.target_index].ident

    def update_brush_summary(self):
        random_mode = self.spawn_mode.get() == 'random_choices'
        self.choices_button.configure(state='normal' if random_mode else 'disabled')
        self.rollbox.configure(state='normal' if random_mode else 'disabled')

        if random_mode:
            total = sum(weight for _, weight in self.random_choices)
            text = ', '.join(f'{self.spawn_name(ident)} {weight / total:.0%}' if total else tr('choice_weight_label', value0=self.spawn_name(ident), value1=weight) for ident, weight in self.random_choices)
            self.choice_summary.set(tr(text or 'choices_required'))
        else:
            self.choice_summary.set(tr('fixed_placement', value0=self.spawn_name(self.selected)))

        candidates = [i for i, weight in self.random_choices if weight > 0] if random_mode else [self.selected]
        self.wave_input.configure(state='disabled' if self.early_spawn_only() else 'normal')

        if self.layer.get() == 'spawns' and any(self.defs['spawns'].get(i, {}).get('early_spawn') for i in candidates):
            self.choice_summary.set(tr(self.choice_summary.get() + '\n' + tr('early_spawn_hint')))

        self.draw_placement_preview()

    def early_spawn_only(self):
        if self.layer.get() != 'spawns':
            return False

        candidates = [ident for ident, weight in self.random_choices if ident != 0 and weight > 0] if self.spawn_mode.get() == 'random_choices' else [self.selected]

        return bool(candidates) and all(self.defs['spawns'].get(ident, {}).get('early_spawn') for ident in candidates)

    def brush_ident(self):
        if self.spawn_mode.get() == 'fixed':
            return self.selected

        if not self.random_choices or sum(weight for _, weight in self.random_choices) <= 0:
            raise ValueError(tr('positive_total_required'))

        return RandomChoice(self.random_choices, uint(int(self.shared_roll.get()), 255, 'shared_roll'))

    def clear_target(self):
        self.target_index = None
        self.target_candidates = []
        self.target_layer = None
        self.target_cell = None
        self.target_position = 0
        self.target_text.set(tr('empty_text'))
        self.target_nav.grid_remove()
        self.placement_label.set(tr('brush_for_new_placements'))
        self.spawn_controls.grid_remove()
        self.update_brush_summary()

    def change_mode(self, event=None):
        if self.tool.get() == 'paint':
            self.enter_paint()
        else:
            self.enter_inspect()

    def enter_inspect(self):
        self.tool.set('inspect')
        self.update_control_visibility()

    def enter_paint(self):
        self.tool.set('paint')
        self.leave_board()
        self.clear_target()
        self.update_control_visibility()

    def spawn_hits(self, cell, preview=False):
        hits = []

        for index, spawn in enumerate(self.level.spawns):
            if preview and self.wave_view.get() not in ('all_waves', f'wave:{spawn.wave}'):
                continue

            ident = self.random_preview['spawns'][index] if preview and self.random_preview else spawn.ident
            offset = (cell[0] - spawn.x, cell[1] - spawn.y)

            if offset == (0, 0) or offset in self.footprint('spawns', ident):
                hits.append(index)

        return hits

    def inspect_cell(self, cell):
        self.target_layer = self.layer.get()
        self.target_cell = cell
        self.placement_label.set(tr('editing_placement_at', value0=cell[0], value1=cell[1]))

        if self.target_layer == 'tiles':
            self.target_index = cell[1] * self.level.header[1] + cell[0]
            self.target_candidates = []
            self.target_nav.grid_remove()
            ident = self.level.tiles[self.target_index]
            self.load_inspected_ident(ident)
            self.target_text.set(tr('random_tile_choices' if isinstance(ident, RandomChoice) else self.spawn_name(ident)))
            self.update_control_visibility()

            return

        self.target_candidates = self.spawn_hits(cell)

        if not self.target_candidates:
            self.target_index = None
            self.target_nav.grid_remove()
            self.wave.set('0')
            self.load_inspected_ident(0)
            self.target_text.set(tr('empty_cell'))
            self.update_control_visibility()

            return

        if len(self.target_candidates) > 1:
            self.target_nav.grid()
        else:
            self.target_nav.grid_remove()

        shown = self.wave_view.get()
        self.target_position = next((j for j, i in enumerate(self.target_candidates) if shown == f'wave:{self.level.spawns[i].wave}'), len(self.target_candidates) - 1)
        self.select_target()

    def cycle_target(self, direction):
        if not self.target_candidates:
            return

        self.target_position = (self.target_position + direction) % len(self.target_candidates)
        self.select_target()

    def select_target(self, event=None):
        choice = self.target_position

        if choice < 0 or choice >= len(self.target_candidates):
            return

        self.target_index = self.target_candidates[choice]
        spawn = self.level.spawns[self.target_index]
        self.target_cell = (spawn.x, spawn.y)
        self.wave.set(str(spawn.wave))
        self.placement_label.set(tr('editing_placement_at', value0=spawn.x, value1=spawn.y))
        label = tr('random_choices') if isinstance(spawn.ident, RandomChoice) else self.spawn_name(spawn.ident)
        suffix = tr('placement_position', value0=choice + 1, value1=len(self.target_candidates)) if len(self.target_candidates) > 1 else ''
        self.target_text.set(tr('wave_placement_label', value0=spawn.wave, value1=label, value2=suffix))
        self.load_inspected_ident(spawn.ident)
        self.update_control_visibility()

    def load_inspected_ident(self, ident):
        if isinstance(ident, RandomChoice):
            self.spawn_mode.set('random_choices')
            self.random_choices = ident.choices
            self.shared_roll.set(str(ident.roll_index))
            self.selected = representative(ident)
        else:
            self.spawn_mode.set('fixed')
            self.selected = ident
            self.random_choices = ((ident, 1),)
            self.shared_roll.set('0')

        if self.selected in self.defs[self.layer.get()] and not self.tree.exists(str(self.selected)):
            self.search.set('')
            self.category.set('all_categories')
            self.refresh_palette(False)

        if self.tree.exists(str(self.selected)):
            self.tree.selection_set(str(self.selected))
            self.tree.see(str(self.selected))

    def placement_setting_changed(self, event=None):
        if self.tool.get() == 'inspect' and self.target_cell is not None:
            self.apply_placement()

        self.update_brush_summary()

    def placement_mode_changed(self, event=None):
        current = None

        if self.target_index is not None:
            if self.target_layer == 'tiles':
                current = self.level.tiles[self.target_index]
            elif self.target_layer == 'spawns':
                current = self.level.spawns[self.target_index].ident

        if self.spawn_mode.get() == 'random_choices' and not isinstance(current, RandomChoice):
            self.random_choices = ((self.selected, 1),)
            self.shared_roll.set('0')

        self.placement_setting_changed()

    def apply_placement(self):
        """Apply inspected placement changes without rerolling unrelated stuff..."""

        if self.target_cell is None:
            return

        spawn = self.level.spawns[self.target_index] if self.target_layer == 'spawns' and self.target_index is not None else None

        try:
            ident = self.brush_ident()
            wave = (spawn.wave if spawn else 0) if self.early_spawn_only() else uint(int(self.wave.get()), 255, 'wave') if self.target_layer == 'spawns' else 0
        except ValueError as exc:
            messagebox.showerror(tr('cannot_apply_placement'), tr(str(exc)))

            return

        if self.target_layer == 'tiles' and self.level.tiles[self.target_index] == ident:
            return

        if spawn is not None and spawn.ident == ident and spawn.wave == wave:
            return

        if self.target_layer == 'spawns' and spawn is None and ident == 0:
            return

        if self.target_layer == 'spawns' and (spawn is None or spawn.ident != ident) and self.overlaps_spawn(self.target_cell, ident, [self.target_index] if spawn else []):
            messagebox.showinfo(tr('overlapping_placement'), tr('footprint_overlap'))
            self.inspect_cell(self.target_cell)

            return

        self.undo_stack.append(copy.deepcopy(self.level))
        self.redo_stack.clear()
        preview_state = self.capture_preview_state()
        cell = self.target_cell

        if self.target_layer == 'tiles':
            self.level.tiles[self.target_index] = ident
        elif spawn:
            spawn.ident = ident
            spawn.wave = wave
        elif ident != 0:
            self.level.spawns.append(Spawn(*cell, ident, wave))

        self.sync_random_preview(preview_state)
        self.dirty = True
        selected_index = self.target_index
        self.inspect_cell(cell)

        if self.target_layer == 'spawns' and selected_index in self.target_candidates:
            self.target_position = self.target_candidates.index(selected_index)
            self.select_target()

    def reroll(self):
        """Reroll preview without touching saved level data..."""

        shared = {}
        rng = random.Random()

        self.random_preview = {
            'tiles': [roll_choice(i, shared, rng) for i in self.level.tiles],
            'spawns': [roll_choice(s.ident, shared, rng) for s in self.level.spawns],
            'shared': shared
        }

        self.draw()

    def capture_preview_state(self):
        """Remember what preview result belongs to which placement..."""

        if self.random_preview is None:
            return None

        return list(self.level.tiles), [(spawn, spawn.ident) for spawn in self.level.spawns]

    def sync_random_preview(self, previous):
        """Keep existing rolls when edits move the spawn list around..."""

        if previous is None:
            return

        tiles, spawns = previous
        preview = self.random_preview
        shared = preview.setdefault('shared', {})
        rng = random.Random()
        old_spawns = {id(spawn): (ident, shown) for (spawn, ident), shown in zip(spawns, preview['spawns'])}
        preview['tiles'] = [shown if ident == old else roll_choice(ident, shared, rng) for ident, old, shown in zip(self.level.tiles, tiles, preview['tiles'])]
        preview['spawns'] = [old_spawns[id(spawn)][1] if id(spawn) in old_spawns and spawn.ident == old_spawns[id(spawn)][0] else roll_choice(spawn.ident, shared, rng) for spawn in self.level.spawns]

    def reset_preview(self):
        self.random_preview = None
        self.draw()

    def press(self, event, erase=False):
        """Start paint stroke or inspect the thing under the mouse..."""

        if self.cell(event) is None:
            return

        self.hover_cell = self.cell(event)

        if self.tool.get() == 'inspect' and not erase:
            self.inspect_cell(self.cell(event))

            return

        if not erase:
            try:
                self.brush_ident()

                if self.layer.get() == 'spawns' and not self.early_spawn_only():
                    uint(int(self.wave.get()), 255, 'wave')

                if self.blocked_brush(self.cell(event)):
                    self.stroke = False
                    self.draw_placement_preview()
                    return
            except ValueError as exc:
                messagebox.showerror(tr('cannot_place_spawn'), tr(str(exc)))
                return

        self.clear_target()
        self.undo_stack.append(copy.deepcopy(self.level))
        self.redo_stack.clear()
        self.stroke = True
        self.place(event, erase)

    def drag(self, event, erase=False):
        self.hover_cell = self.cell(event)
        self.draw_placement_preview()

        if self.stroke and (erase or self.defs[self.layer.get()].get(self.selected, {}).get('paint')):
            self.place(event, erase)

    def place(self, event, erase):
        """Place or erase things..."""

        cell = self.cell(event)

        if cell is None:
            return

        x, y = cell
        ident = 0 if erase else self.selected

        if not erase and self.blocked_brush(cell):
            return

        preview_state = self.capture_preview_state()

        if self.layer.get() == 'tiles':
            self.level.tiles[y * self.level.header[1] + x] = 0 if erase else self.brush_ident()
        else:
            if erase:
                hits = set(self.spawn_hits(cell, preview=True))
                self.level.spawns = [spawn for index, spawn in enumerate(self.level.spawns) if index not in hits]
            else:
                try:
                    wave = 0 if self.early_spawn_only() else uint(int(self.wave.get()), 255, 'wave')
                    ident = self.brush_ident()
                except ValueError:
                    return

                existing = next((s for s in self.level.spawns if (s.x, s.y, s.wave) == (x, y, wave)), None)
                reserved = existing.reserved if existing else 0
                self.level.spawns = [s for s in self.level.spawns if (s.x, s.y, s.wave) != (x, y, wave)]

                if ident:
                    self.level.spawns.append(Spawn(x, y, ident, wave, reserved))

        self.sync_random_preview(preview_state)
        self.dirty = True
        self.draw()

    def pick(self, event):
        if self.tool.get() == 'inspect':
            return

        cell = self.cell(event)

        if cell is None:
            return

        x, y = cell
        self.clear_target()

        if self.layer.get() == 'spawns':
            shown = self.wave_view.get()
            hits = self.spawn_hits(cell, preview=True)
            found = hits[-1] if hits else None
            ident = self.level.spawns[found].ident if found is not None else 0

            if self.random_preview and found is not None:
                ident = self.random_preview['spawns'][found]
        else:
            at = y * self.level.header[1] + x
            ident = self.random_preview['tiles'][at] if self.random_preview else self.level.tiles[at]

        self.spawn_mode.set('fixed')
        self.selected = ident = representative(ident)
        self.random_choices = ((ident, 1),)
        self.shared_roll.set('0')

        if ident in self.defs[self.layer.get()] and not self.tree.exists(str(ident)):
            self.search.set('')
            self.category.set('all_categories')
            self.refresh_palette(False)

        if self.tree.exists(str(ident)):
            self.tree.selection_set(str(ident))
            self.tree.see(str(ident))
            self.select(None)
        else:
            self.preview.configure(image='')
            self.selection_text.set(tr('unknown_id', value0=ident))

        self.update_brush_summary()
        self.draw()

    def undo(self):
        if self.undo_stack:
            self.clear_target()
            self.random_preview = None
            self.redo_stack.append(copy.deepcopy(self.level))
            self.level = self.undo_stack.pop()
            self.dirty = True
            self.draw()

    def redo(self):
        if self.redo_stack:
            self.clear_target()
            self.random_preview = None
            self.undo_stack.append(copy.deepcopy(self.level))
            self.level = self.redo_stack.pop()
            self.dirty = True
            self.draw()
