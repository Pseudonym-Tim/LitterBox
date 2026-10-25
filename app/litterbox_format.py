"""Decode/encode .lvl files, validate fields, handle weighted random IDs..."""
from app.litterbox_language import tr
from dataclasses import dataclass
from pathlib import Path
import struct

def uint(value, maximum, label):
    # Reject numbers that won't fit instead of wrapping the damn things...
    if not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError(tr('value_out_of_range', value0=tr(label), value1=maximum))
    return value

@dataclass(frozen=True)
class RandomChoice:
    # Choices are (ID, weight) pairs, matching nonzero roll numbers share one random roll...
    choices: tuple
    roll_index: int = 0

@dataclass
class Spawn:
    x: int
    y: int
    ident: object
    wave: int = 0
    reserved: int = 0 # Keep this extra byte intact even though the editor doesn't use it...

    def __iter__(self):
        return iter((self.x, self.y, self.ident))

def representative(ident):
    if isinstance(ident, int):
        return ident
    # Pick a usable icon for the list, this doesn't actually roll the random choice...
    choices = ident.choices if isinstance(ident, RandomChoice) else ident
    return next((i for i, weight in choices if i and weight > 0), 0)

def roll_choice(ident, shared_rolls, rng):
    if isinstance(ident, int):
        return ident

    choices = ident.choices

    # Linked placements reuse the roll, zero means roll this placement separately...
    if ident.roll_index:
        if ident.roll_index not in shared_rolls:
            shared_rolls[ident.roll_index] = rng.random()

        roll = shared_rolls[ident.roll_index]
    else:
        roll = rng.random()

    # Bigger weights get a bigger slice of the chance, not a guaranteed spawn...
    total = sum(weight for _, weight in choices)
    cumulative = 0.0

    for spawn_id, weight in choices:
        cumulative += weight / total if total else 0

        if roll < cumulative:
            return spawn_id

    # Fall back to the first choice if no weight catches the roll...
    return choices[0][0]

def encode_id(ident):
    if isinstance(ident, int):
        return struct.pack('<H', uint(ident, 65534, 'id'))

    if not isinstance(ident, RandomChoice):
        ident = RandomChoice(tuple(ident))

    if not 1 <= len(ident.choices) <= 255:
        raise ValueError(tr('random_choice_count'))

    # (65535 means a random choice list follows, then its count and shared roll number...)
    data = struct.pack('<HBB', 65535, len(ident.choices), uint(ident.roll_index, 255, 'shared_roll'))

    for spawn_id, weight in ident.choices:
        data += struct.pack('<HH', uint(spawn_id, 65534, 'choice_id'), uint(weight, 65535, 'weight'))

    return data

class Level:
    @classmethod
    def read(cls, path):
        return cls.decode(Path(path).read_bytes())

    @classmethod
    def decode(cls, data):
        obj = cls()
        offset = 0

        def take(n):
            nonlocal offset

            # Bail if the file runs out halfway through this shit...
            if offset + n > len(data):
                raise ValueError(tr('truncated_level_record'))

            part = data[offset:offset + n]
            offset += n

            return part

        def read(fmt):
            return struct.unpack(fmt, take(struct.calcsize(fmt)))

        # The header is nine numbers, starting with version, width, height, layers and spawn count...
        obj.header = list(read('<9I'))
        version, w, h, layers, count = obj.header[:5]

        if version not in (1, 2) or layers != 1 or not (1 <= w <= 128 and 1 <= h <= 128):
            raise ValueError(tr('unsupported_level_header'))

        # Definition filenames have a length before each name, version 2 adds the tiles table...
        obj.tables = [take(read('<I')[0]) for _ in range(1 if version == 1 else 2)]
        # Keep this chunk as is, whatever the hell it means...
        obj.prefix = take(12 if version == 1 else 8)

        def random_id(ident):
            if ident != 65535:
                return ident

            # After the random marker come the choice count, roll number and (ID, weight) pairs...
            n, roll = read('<BB')

            if n == 0:
                raise ValueError(tr('random_placement_has_no_choices'))

            return RandomChoice(tuple(read('<HH') for _ in range(n)), roll)

        # Tiles fill grid in order, spawns are separate list with their own coordinates...
        obj.tiles = [random_id(read('<H')[0]) for _ in range(w * h)]
        obj.spawns = []

        for _ in range(count):
            # Each spawn starts with position, ID, wave and the extra byte, then random choices...
            x, y, ident, wave, reserved = read('<hhHBB')
            obj.spawns.append(Spawn(x, y, random_id(ident), wave, reserved))

        obj.tail = data[offset:]

        # Keep footer untouched, also accept short zero footers left by other editors...
        partial_zero_footer = 0 < len(obj.tail) < 4 and not any(obj.tail)

        if len(obj.tail) not in (0, 4) and not partial_zero_footer:
            raise ValueError(tr('unexpected_trailing_data'))

        return obj

    def encode(self):
        header = self.header.copy()
        # Update spawn count without messing with the other saved header values...
        header[4] = len(self.spawns)

        if len(self.tiles) != header[1] * header[2]:
            raise ValueError(tr('tile_count_does_not_match_the_board'))

        result = struct.pack('<9I', *header)
        result += b''.join(struct.pack('<I', len(table)) + table for table in self.tables)
        result += self.prefix + b''.join(encode_id(ident) for ident in self.tiles)

        for spawn in self.spawns:
            if not -32768 <= spawn.x <= 32767 or not -32768 <= spawn.y <= 32767:
                raise ValueError(tr('invalid_spawn_coordinates'))

            # Wave and the stupid extra byte sit between the ID and random choice data, annoyingly...
            encoded = encode_id(spawn.ident)
            result += struct.pack('<hh', spawn.x, spawn.y) + encoded[:2]
            result += struct.pack('<BB', uint(spawn.wave, 255, 'wave'), uint(spawn.reserved, 255, 'reserved_byte'))
            result += encoded[2:]

        # Put the original footer back instead of making up a replacement...
        return result + self.tail

    @classmethod
    def blank(cls):
        obj = cls()
        # Start with the usual 10x10 board and no placed stuff...
        obj.header = [2, 10, 10, 1, 0, 0, 0, 10, 10]
        obj.tables = [b'spawns.gon', b'tiles.gon']
        obj.prefix = bytes(8)
        obj.tiles = [0] * 100
        obj.spawns = []
        obj.tail = bytes(4)
        return obj