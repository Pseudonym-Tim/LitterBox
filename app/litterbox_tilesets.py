"""Read GON includes and mod overlays to list tilesets and infer a level's tileset and innate weather..."""
from app.litterbox_language import tr
from pathlib import Path
import json
import re

def gon_text(path, stack=()):
    path = Path(path).resolve()

    if not path.is_file() or path in stack or len(stack) > 16:
        return ''

    text = path.read_text(encoding='utf-8-sig')

    # (Strip comments without mangling quoted strings...)
    text = re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/', lambda m: m[0] if m[0].startswith('"') else '\n' * m[0].count('\n'), text)

    def include(match):
        return gon_text(path.parent / match[1], stack + (path,)) + '\n'

    text = re.sub(r'^[ \t]*#include\s+"([^"\n]+)"[^\n]*', include, text, flags=re.M)

    return re.sub(r'"(?:\\.|[^"\\])*"|#[^\n]*', lambda m: m[0] if m[0].startswith('"') else '', text)

def read_gon(path, stack=()):
    text = gon_text(path, stack)
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[{}\[\]]|[^\s{}\[\],]+', text)
    pos = 0

    def value():
        nonlocal pos

        if pos >= len(tokens):
            return ''

        token = tokens[pos]
        pos += 1

        if token == '{':
            return block('}')

        if token == '[':
            items = []

            while pos < len(tokens) and tokens[pos] != ']':
                items.append(value())

            if pos < len(tokens):
                pos += 1

            return items

        if token.startswith('"'):
            try:
                return json.loads(token)
            except ValueError:
                return token[1:-1]

        return token

    def block(end=None):
        nonlocal pos
        result = {}

        while pos < len(tokens):
            key = tokens[pos]
            pos += 1

            if key == end:
                break

            if key in ('}', ']'):
                continue

            result[key] = value()

        return result

    return block()

def merge(target, incoming):
    for raw, value in incoming.items():
        key, sep, operation = raw.rpartition('.')

        if not sep or operation not in ('overwrite', 'append', 'delete', 'remove'):
            key = raw
            operation = 'merge'

        if operation in ('delete', 'remove'):
            target.pop(key, None)
        elif operation == 'append' and isinstance(value, list) and isinstance(target.get(key), list):
            target[key] += value
        elif operation != 'overwrite' and isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        elif isinstance(value, dict):
            target[key] = {}
            merge(target[key], value)
        else:
            target[key] = value

    return target

def effective_gon(base, mod=None):
    result = merge({}, read_gon(base))

    if mod:
        mod = Path(mod)

        if mod.is_file():
            result = merge({}, read_gon(mod))

        for suffix in ('.append', '.patch'):
            merge(result, read_gon(Path(str(mod) + suffix)))

    return result

def tileset_names(resources, mod_folder=None):
    mod = Path(mod_folder) / 'data/tilesets.gon' if mod_folder else None
    data = effective_gon(Path(resources) / 'data/tilesets.gon', mod)

    return sorted({'alley'} | {key for key, value in data.items() if isinstance(value, dict)}, key=str.casefold)

def map_metadata(resources, mod_folder=None):
    base_maps = Path(resources) / 'data/maps'
    mod_maps = Path(mod_folder) / 'data/maps' if mod_folder else None
    names = {p.relative_to(base_maps).as_posix() for p in base_maps.rglob('*.gon')}

    if mod_maps and mod_maps.exists():
        for p in mod_maps.rglob('*.gon*'):
            name = p.relative_to(mod_maps).as_posix()

            if name.endswith(('.gon', '.gon.append', '.gon.patch')):
                names.add(re.sub(r'\.(append|patch)$', '', name))

    for name in sorted(names):
        yield name, effective_gon(base_maps / name, mod_maps / name if mod_maps else None)

def map_candidates(level_path, resources, mod_folder=None):
    if not level_path:
        return []

    path = Path(level_path).resolve()
    roots = ([Path(mod_folder) / 'levels'] if mod_folder else []) + [Path(resources) / 'levels']
    relative = None

    for root in roots:
        try:
            relative = path.relative_to(root.resolve())
            break
        except ValueError:
            pass

    if relative is None:
        parts = path.parts
        positions = [i for i, p in enumerate(parts) if p.lower() == 'levels']

        if positions:
            relative = Path(*parts[positions[-1] + 1:])

    if relative is None:
        return []

    explicit = []
    defaults = []

    for name, data in map_metadata(resources, mod_folder):
        levels = data.get('levels', {})
        folder = levels.get('folder') if isinstance(levels, dict) else None
        folder = str(folder).replace('\\', '/').strip('/') if folder else ''
        rel = relative.as_posix().lower()
        matched = bool(folder and rel.startswith(folder.lower() + '/'))
        default = data.get('tileset')

        if matched and isinstance(default, str):
            defaults.append((len(folder), default, name, data))

        nodes = data.get('nodes', {})

        if not isinstance(nodes, dict):
            continue

        for node in nodes.values():
            if not isinstance(node, dict):
                continue

            refs = node.get('level', [])
            refs = refs if isinstance(refs, list) else [refs]

            for ref in refs:
                if not isinstance(ref, str):
                    continue

                ref = ref.replace('\\', '/').removesuffix('.lvl').lower()
                match = ref == relative.with_suffix('').as_posix().lower() or (matched and (ref == relative.stem.lower() or ref in [part.lower() for part in relative.parent.parts[1:]]))
                chosen = node.get('tileset', default)

                if match and isinstance(chosen, str):
                    explicit.append((chosen, name, data))

    candidates = explicit

    if not candidates and defaults:
        specificity = max(item[0] for item in defaults)
        candidates = [(tile, name, data) for length, tile, name, data in defaults if length == specificity]

    return candidates

def detect_tileset(level_path, resources, mod_folder=None, available=None):
    available = set(available or tileset_names(resources, mod_folder))
    candidates = map_candidates(level_path, resources, mod_folder)
    values = {tile for tile, name, data in candidates}

    if len(values) > 1:
        return 'alley', tr('ambiguous_map_settings_using_alley')

    if values:
        tile = next(iter(values))

        if tile in available:
            return tile, tr('detected_from_maps', value0=candidates[0][1])

        return 'alley', tr('map_tileset_unavailable', value0=tile)

    return 'alley', tr('no_match_using_alley')

def detect_weather(level_path, resources, mod_folder=None, tileset=None):
    candidates = map_candidates(level_path, resources, mod_folder)

    if tileset is not None:
        candidates = [entry for entry in candidates if entry[0] == tileset]

        if not candidates:
            def uses_tileset(data):
                if data.get('tileset') == tileset:
                    return True

                nodes = data.get('nodes', {})

                return isinstance(nodes, dict) and any(isinstance(node, dict) and node.get('tileset') == tileset for node in nodes.values())

            candidates = [
                (tileset, name, data) for name, data in map_metadata(resources, mod_folder)
                if uses_tileset(data)
            ]

    def weather_list(data):
        value = data.get('innate_weather', [])

        if isinstance(value, str):
            value = [value]

        if not isinstance(value, list) or any(not isinstance(item, str) or not item or any(ch in item for ch in '\r\n\x00') for item in value):
            raise ValueError(tr('invalid_map_weather'))

        return tuple(dict.fromkeys(item for item in value if item != 'None'))

    values = {weather_list(data) for tile, name, data in candidates}

    if len(values) > 1:
        return (), tr('ambiguous_weather')

    if not values:
        return (), tr('no_matching_map_no_innate_weather')

    weather = next(iter(values))

    if weather:
        mod = Path(mod_folder) / 'data/weather.gon' if mod_folder else None
        definitions = effective_gon(Path(resources) / 'data/weather.gon', mod)
        missing = [name for name in weather if not isinstance(definitions.get(name), dict)]

        if missing:
            raise ValueError(tr('mod_weather_unavailable', value0=', '.join(missing)))

    return weather, tr('weather_maps', value0=', '.join(weather), value1=candidates[0][1]) if weather else tr('no_innate_weather_maps', value0=candidates[0][1])