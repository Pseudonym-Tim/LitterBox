"""Read editor GON entries, handle descriptions, merge mod definitions, read character footprints..."""
import copy
import re
from pathlib import Path

from app.litterbox_language import tr
from app.litterbox_playtest import mod_folder_path

_ENTRY_TOKENS = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|\#[^\n]*|/\*[\s\S]*?\*/|[{}]|[^\s{}]+?(?=\s|[{}]|$)')

def category_names(path):
    """Use the dev category comments as actual editor metadata..."""
    names = {}
    in_section = False

    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if re.match(r'^\s*//\s*CATEGORIES\s*:', line, re.IGNORECASE):
            in_section = True
            continue

        if not in_section:
            continue

        if not line.strip():
            continue

        if not line.lstrip().startswith('//'):
            break

        match = re.match(r'^\s*//\s*(-?\d+)\s*:\s*(.*?)\s*$', line)

        if match and match[2]:
            names[str(int(match[1]))] = match[2]

    return names

def entry_comments(text):
    """Keep comments above entries as descriptions without mangling the GON..."""
    descriptions = {}
    pending = []
    depth = 0
    previous_end = 0
    clean = list(text)

    for match in _ENTRY_TOKENS.finditer(text):
        token = match[0]

        if text[previous_end:match.start()].count('\n') > 1:
            pending = []

        previous_end = match.end()

        if token.startswith(('//', '#', '/*')):
            for at in range(match.start(), match.end()):
                if clean[at] != '\n':
                    clean[at] = ' '

            if depth == 0 and not text[text.rfind('\n', 0, match.start()) + 1:match.start()].strip():
                content = token[2:-2] if token.startswith('/*') else token[2:] if token.startswith('//') else token[1:]
                lines = [re.sub(r'^\s*\* ?', '', line).strip() for line in content.splitlines()]
                pending.append('\n'.join(lines).strip())

            continue

        if depth == 0 and token.isdigit() and pending:
            descriptions[int(token)] = '\n'.join(pending)

        pending = []

        if token == '{':
            depth += 1
        elif token == '}':
            depth -= 1

    return ''.join(clean), descriptions

def preserve_entry_comments(current, baseline, latest):
    """Carry custom descriptions onto fresh vanilla defs..."""

    def blocks(data):
        text = data.decode('utf-8-sig').replace('\r\n', '\n')
        entries = {}
        pending = None
        depth = 0
        previous_end = 0

        for match in _ENTRY_TOKENS.finditer(text):
            token = match[0]

            if text[previous_end:match.start()].count('\n') > 1:
                pending = None

            previous_end = match.end()

            if token.startswith(('//', '#', '/*')):
                if depth == 0 and not text[text.rfind('\n', 0, match.start()) + 1:match.start()].strip():
                    if pending is None:
                        pending = match.start()

                continue

            if depth == 0 and token.isdigit():
                start = pending if pending is not None else match.start()
                entries[int(token)] = (start, match.start(), text[start:match.start()])

            pending = None

            if token == '{':
                depth += 1
            elif token == '}':
                depth -= 1

        return text, entries

    _, local = blocks(current)
    _, old = blocks(baseline)
    text, new = blocks(latest)
    replacements = []

    for ident, (_, _, comment) in local.items():
        previous = old.get(ident, (0, 0, ''))[2]

        if comment != previous and ident in new:
            start, end, _ = new[ident]
            replacements.append((start, end, comment))

    if not replacements:
        return latest

    for start, end, comment in sorted(replacements, reverse=True):
        text = text[:start] + comment + text[end:]

    newline = '\r\n' if b'\r\n' in latest else '\n'

    return text.replace('\n', newline).encode('utf-8')

def palette(path):
    """Read ID and editor blocks..."""
    text = path.read_text(encoding='utf-8-sig')
    text, descriptions = entry_comments(text)
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[{}\[\]]|[^\s{}\[\],]+', text)

    def block(start):
        depth = 1
        end = start + 1

        while end < len(tokens) and depth:
            depth += (tokens[end] == '{') - (tokens[end] == '}')
            end += 1

        return tokens[start + 1:end - 1], end

    result = {}
    pos = 0

    while pos < len(tokens) - 1:
        if tokens[pos].isdigit() and tokens[pos + 1] == '{':
            ident = int(tokens[pos])
            body, pos = block(pos + 1)

            try:
                ed_start = body.index('editor') + 1
            except ValueError:
                continue

            depth = 1
            end = ed_start + 1

            while end < len(body) and depth:
                depth += (body[end] == '{') - (body[end] == '}')
                end += 1

            ed = body[ed_start + 1:end - 1]

            def scalar(key, default=''):
                return ed[ed.index(key) + 1].strip('"') if key in ed else default

            imgs = []

            if 'image' in ed:
                p = ed.index('image') + 1

                if ed[p] == '[':
                    q = ed.index(']', p)
                    imgs = [s.strip('"') for s in ed[p + 1:q] if s.startswith('"')]
                else:
                    imgs = [ed[p].strip('"')]

            tints = []

            if 'image_tint' in ed:
                p = ed.index('image_tint') + 1

                if ed[p] == '[':
                    depth = 1
                    p += 1

                    while p < len(ed) and depth:
                        t = ed[p]
                        p += 1

                        if t == '[':
                            rgb = []

                            while ed[p] != ']':
                                rgb.append(float(ed[p]))
                                p += 1

                            p += 1
                            tints.append(tuple(round(x * 255) for x in rgb))
                        elif t == ']':
                            depth -= 1
                        else:
                            tints.append(t)
                else:
                    tints = [ed[p]]

            object_names = []

            if 'object' in body:
                at = body.index('object') + 1

                if body[at] == '{':
                    stop = body.index('}', at)
                    object_names = [t for t in body[at + 1:stop] if re.fullmatch(r'[A-Za-z_]\w*', t)]
                else:
                    object_names = [body[at]]

            description = descriptions.get(ident, '')
            name = scalar('name', str(ident))
            category = scalar('category', '0')
            paint = scalar('paint') == 'true'
            early_spawn = 'early_spawn' in body and body[body.index('early_spawn') + 1] == 'true'
            result[ident] = dict(description=description, name=name, images=imgs, tints=tints, objects=object_names, category=category, paint=paint, early_spawn=early_spawn)
        else:
            pos += 1

    return result

def merge_mod_assets(base, categories, profiles, icons):
    definitions = copy.deepcopy(base)
    names = copy.deepcopy(categories)
    conflicts = []

    for profile in profiles:
        for layer, key in [('spawns', 'spawns'), ('tiles', 'tiles')]:
            if not profile.get(key):
                continue

            path = Path(profile[key])
            entries = palette(path)

            if not entries:
                raise ValueError(tr('missing_editor_definitions', value0=path))

            for ident, definition in entries.items():
                if not 0 <= ident < 65535:
                    raise ValueError(tr('invalid_definition_id', value0=path.name, value1=ident))

                if ident in definitions[layer]:
                    conflicts.append(tr('duplicate_definition', value0=tr(layer), value1=ident, value2=definition['name'], value3=path.name))
                    continue

                # Check again (in case someone added icons after loading the mod)...
                icon_dirs = mod_icon_directories(mod_folder_path(profile))

                if profile.get('icons'):
                    icon_dirs.append(Path(profile['icons']))

                definition['_icon_dirs'] = list(dict.fromkeys(icon_dirs + [Path(icons)]))
                definition['_source'] = 'mod'
                definition['_mod_folder'] = str(mod_folder_path(profile).resolve())
                definitions[layer][ident] = definition

            for category, name in category_names(path).items():
                names[layer].setdefault(category, name)

    return definitions, names, conflicts

def mod_icon_directories(folder):
    folder = Path(folder)

    if folder.name.lower() == 'data':
        folder = folder.parent

    return [path for path in (folder / 'editor_icons', folder / 'textures/editor_icons', folder / 'data/editor_icons') if path.is_dir()]

def discover_mod_assets(folder):
    folder = Path(folder)

    if folder.name.lower() == 'data':
        folder = folder.parent

    data = folder / 'data' if (folder / 'data').is_dir() else folder
    icons = next((str(path) for path in mod_icon_directories(folder)), '')
    profiles = []

    for suffix in ('', '.append', '.patch'):
        profile = {'icons': icons}

        for layer in ('spawns', 'tiles'):
            path = data / (layer + '.gon' + suffix)
            profile[layer] = str(path) if path.is_file() else ''

        if profile['spawns'] or profile['tiles']:
            profiles.append(profile)

    return profiles

def tokens(path):
    text = path.read_text(encoding='utf-8-sig')
    text = re.sub(r'//[^\n]*|#[^\n]*', '', text)
    return re.findall(r'"(?:\\.|[^"\\])*"|[{}\[\]]|[^\s{}\[\],]+', text)

def fields(items):
    result = {}
    i = 0

    while i + 1 < len(items):
        key, value = items[i:i + 2]
        i += 2

        if value in ('{', '['):
            start = i
            stack = [value]

            while i < len(items) and stack:
                if items[i] in ('{', '['):
                    stack.append(items[i])
                elif items[i] in ('}', ']'):
                    stack.pop()

                i += 1

            value = items[start:i - 1]

        result[key] = value

    return result

def load_sizes(resources):
    definitions = {}

    for path in sorted((Path(resources) / 'data/characters').glob('*.gon')):
        items = tokens(path)
        i = 0

        while i + 1 < len(items):
            if items[i + 1] != '{':
                i += 1
                continue

            name = items[i]
            start = i + 2
            i = start
            depth = 1

            while i < len(items) and depth:
                depth += (items[i] == '{') - (items[i] == '}')
                i += 1

            definitions[name] = fields(items[start:i - 1])

    sizes = {}

    def resolve(name, seen=()):
        if name in sizes:
            return sizes[name]

        if name in seen:
            return (1, 1)

        definition = definitions.get(name, {})
        parent = definition.get('variant_of')
        size = resolve(parent, seen + (name,)) if isinstance(parent, str) else (1, 1)
        props = definition.get('properties', [])
        own = fields(props).get('size') if isinstance(props, list) else None
        match = re.fullmatch(r'(\d+)x(\d+)', own or '')

        if match:
            size = tuple(max(1, int(n)) for n in match.groups())

        sizes[name] = size

        return size

    for name in definitions:
        resolve(name)

    return sizes

def occupied_offsets(size):
    width, height = size
    left, bottom = -((width - 1) // 2), -((height - 1) // 2) # Even dimensions favor positive direction...
    return {(left + x, bottom + y) for y in range(height) for x in range(width)}