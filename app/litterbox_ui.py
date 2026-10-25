"""Load fonts and button icons, style Tk controls and title bars, and position app windows..."""
import tkinter as tk
import sys
from PIL import Image, ImageDraw, ImageTk
from tkinter import font as tkfont, ttk
from pathlib import Path

from app.litterbox_config import ROOT

COLORS = {
    'bg': '#1c1c1c', 'fg': '#e6e6e6', 'text_bg': '#1c1c1c',
    'select_bg': '#2e62b8', 'select_fg': '#ffffff', 'menu_bg': '#2b2b2b',
    'menu_active_bg': '#3a3a3a', 'muted_fg': '#b5b5b5', 'disabled_fg': '#858585',
    'warning_fg': '#f2c94c', 'error_fg': '#ff6b6b',
    'button_bg': '#343434', 'button_active_bg': '#454545', 'button_pressed_bg': '#292929',
    'scrollbar_bg': '#666666', 'scrollbar_active_bg': '#7a7a7a',
    'scrollbar_trough_bg': '#292929', 'scrollbar_arrow_fg': '#f2f2f2',
}

BUTTON_ICONS = {
    'new': 'file', 'open_lvl': 'folder-open', 'save': 'floppy-disk', 'save_as': 'file-export',
    'mod_assets': 'gear', 'playtest': 'play', 'help': 'info-circle', 'about': 'info-circle', 'undo': 'rotate-left',
    'redo': 'rotate-right', 'fit': 'expand', 'reroll_level_preview': 'arrows-rotate',
    'previous': 'arrow-left', 'next': 'arrow-right', 'edit_choices': 'sliders',
    'add_mod_folder': 'folder-open', 'remove_selected': 'trash-can', 'reload_files': 'arrows-rotate',
    'close': 'xmark', 'browse': 'folder-open', 'cancel': 'xmark',
    'add_choice': 'plus', 'set_weight': 'check', 'remove': 'trash-can', 'use_choices': 'check',
}

def icon_image(widget, name, size=18, disabled=False):
    root = widget._root()
    cache = getattr(root, '_fontawesome_images', None)

    if cache is None:
        root._fontawesome_images = cache = {}

    key = (name, size, disabled)

    if key not in cache:
        path = Path(__file__).resolve().parent.parent / 'assets/icons/fontawesome/dark' / f'{name}.png'
        image = Image.open(path).convert('RGBA').resize((size, size), Image.Resampling.LANCZOS)
        alpha = image.getchannel('A')
        image = Image.new('RGBA', image.size, COLORS['disabled_fg'] if disabled else COLORS['fg'])
        image.putalpha(alpha)
        cache[key] = ImageTk.PhotoImage(image, master=root)

    return cache[key]

def icon_button(parent, *, icon=None, **kwargs):
    if icon:
        normal = icon_image(parent, icon)
        muted = icon_image(parent, icon, disabled=True)
        kwargs.update(image=(normal, 'disabled', muted), compound='left')

    return ttk.Button(parent, **kwargs)

def dark_titlebar(event):
    if sys.platform != 'win32':
        return

    window = event.widget

    if window.winfo_toplevel() != window:
        return

    opening = str(event.type) == '19' # (Window just mapped...)

    def finish_mapping():
        if not window.winfo_exists():
            return

        if opening and str(window.winfo_class()) == 'Toplevel':
            window.lift()
            window.focus_set()

        apply_dark_titlebar(window)

        # Windows can do activation crap after Tk says window is ready...
        if opening:
            window._root().after(50, lambda: apply_dark_titlebar(window) if window.winfo_exists() else None)
            window._root().after(150, lambda: apply_dark_titlebar(window) if window.winfo_exists() else None)

    window._root().after_idle(finish_mapping)

def apply_dark_titlebar(window):
    import ctypes as c
    from ctypes import wintypes as w
    user = c.WinDLL('user32')
    user.GetAncestor.argtypes = [w.HWND, w.UINT]
    user.GetAncestor.restype = w.HWND
    hwnd = user.GetAncestor(window.winfo_id(), 2)
    dwm = c.WinDLL('dwmapi')
    dwm.DwmSetWindowAttribute.argtypes = [w.HWND, w.DWORD, c.c_void_p, w.DWORD]

    for attribute, value in ((20, 1), (35, 0x1c1c1c), (36, 0xe6e6e6)):
        color = w.DWORD(value)
        dwm.DwmSetWindowAttribute(hwnd, attribute, c.byref(color), c.sizeof(color))

    # Windows sometimes keeps stale title bar until activation changes, wtf...
    user.GetForegroundWindow.restype = w.HWND
    user.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    user.SendMessageW.restype = c.c_ssize_t

    if user.GetForegroundWindow() != hwnd:
        return

    user.SendMessageW(hwnd, 0x86, 0, 0) # (WM_NCACTIVATE repaints the frame...)
    user.SendMessageW(hwnd, 0x86, 1, 0)

def load_program_font(root):
    if sys.platform == 'win32':
        import ctypes

        for name in ('SourGummy-Regular.ttf', 'SourGummy-Bold.ttf'):
            path = ROOT / 'assets/fonts' / name

            if path.exists():
                ctypes.windll.gdi32.AddFontResourceExW(str(path), 0x10, 0)

    for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont', 'TkCaptionFont', 'TkSmallCaptionFont', 'TkIconFont', 'TkTooltipFont'):
        font = tkfont.nametofont(name, root=root)
        font.configure(family='Sour Gummy', weight='bold', size=11 if name != 'TkTooltipFont' else 10)

    root.option_add('*Font', 'TkDefaultFont')

def apply_dark_theme(root):
    """Give Tk controls and child windows the same damn theme..."""
    load_program_font(root)

    for name in ('Tk', 'Toplevel'):
        root.bind_class(name, '<Map>', dark_titlebar, add='+')
        root.bind_class(name, '<FocusIn>', dark_titlebar, add='+')

    background = COLORS['bg']
    field = COLORS['text_bg']
    foreground = COLORS['fg']
    border = COLORS['menu_active_bg']
    selected = COLORS['select_bg']
    muted = COLORS['disabled_fg']
    root.configure(background=background)
    root.option_add('*Background', background)
    root.option_add('*Foreground', foreground)
    root.option_add('*Listbox.background', field)
    root.option_add('*Listbox.foreground', foreground)
    root.option_add('*Listbox.highlightBackground', border)
    root.option_add('*Listbox.selectBackground', selected)
    root.option_add('*Listbox.selectForeground', '#ffffff')
    root.option_add('*TCombobox*Listbox.background', COLORS['menu_bg'])
    root.option_add('*TCombobox*Listbox.foreground', foreground)
    root.option_add('*TCombobox*Listbox.selectBackground', COLORS['menu_active_bg'])
    root.option_add('*TCombobox*Listbox.selectForeground', '#ffffff')
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font='TkDefaultFont', background=background, foreground=foreground, bordercolor=border, lightcolor=border, darkcolor=border, troughcolor=field, selectbackground=selected, selectforeground='#ffffff')
    style.configure('TButton', width=0, background=COLORS['button_bg'], foreground=COLORS['select_fg'], padding=(8, 5), focusthickness=0, focuscolor=background)
    style.map('TButton', background=[('disabled', background), ('pressed', COLORS['button_pressed_bg']), ('active', COLORS['button_active_bg'])], foreground=[('disabled', muted)])

    for name in ('TEntry', 'TCombobox', 'TSpinbox'):
        style.configure(name, background=field, fieldbackground=field, foreground=foreground, bordercolor=border, lightcolor=border, darkcolor=border, insertcolor=foreground, arrowcolor=foreground, padding=3)
        style.map(name, background=[('disabled', background), ('active', COLORS['button_active_bg']), ('readonly', field), ('!disabled', field)], bordercolor=[('focus', '#686868'), ('!focus', border)], lightcolor=[('!disabled', border), ('disabled', border)], darkcolor=[('!disabled', border), ('disabled', border)], arrowcolor=[('disabled', muted), ('!disabled', foreground)], fieldbackground=[('disabled', background), ('readonly', field), ('!disabled', field)], foreground=[('disabled', muted), ('readonly', foreground)], selectbackground=[('!disabled', selected)], selectforeground=[('!disabled', '#ffffff')])

    for name in ('TRadiobutton', 'TCheckbutton'):
        style.configure(name, indicatorbackground=field, indicatorforeground=foreground)
        style.map(name, background=[('active', COLORS['button_bg'])], foreground=[('disabled', muted)], indicatorbackground=[('selected', selected), ('active', COLORS['button_active_bg'])])

    def without_focus(layout):
        result = []

        for element, options in layout:
            options = dict(options)
            children = without_focus(options.pop('children', []))

            if element.endswith('.focus'):
                result.extend(children)
            else:
                if children:
                    options['children'] = children

                result.append((element, options))

        return result

    for name in ('TButton', 'TRadiobutton', 'TCheckbutton'):
        style.layout(name, without_focus(style.layout(name)))
        style.configure(name, focusthickness=0, focuscolor=background)

    style.map('TButton', bordercolor=[('!disabled', border), ('disabled', border)], lightcolor=[('!disabled', border), ('disabled', border)], darkcolor=[('!disabled', border), ('disabled', border)])

    def release_button_focus(event):
        widget = event.widget

        def clear():
            if widget.winfo_exists():
                widget.state(['!focus'])

                if root.focus_get() == widget:
                    root.focus_set()

        root.after_idle(clear)

    for name in ('TButton', 'TRadiobutton', 'TCheckbutton'):
        root.bind_class(name, '<ButtonRelease-1>', release_button_focus, add='+')

    style.configure('Horizontal.TProgressbar', background='#7bd88f', troughcolor=COLORS['scrollbar_trough_bg'], bordercolor=border, lightcolor='#7bd88f', darkcolor='#7bd88f')
    style.configure('Fit.TButton', width=0, padding=(5, 2))
    style.configure('TSpinbox', arrowsize=22, padding=(6, 5))
    style.configure('Compact.TSpinbox', arrowsize=16, padding=(3, 2))
    style.configure('TCombobox', arrowsize=18)
    style.configure('TCombobox', background=COLORS['button_bg'], fieldbackground=COLORS['button_bg'])
    style.map('TCombobox', background=[('disabled', background), ('!disabled', COLORS['button_bg'])], fieldbackground=[('disabled', background), ('!disabled', COLORS['button_bg'])], selectbackground=[('!disabled', COLORS['button_bg'])], selectforeground=[('!disabled', foreground)])

    def clear_dropdown_selection(event):
        widget = event.widget
        widget.after_idle(lambda: widget.selection_clear() if widget.winfo_exists() else None)

    for event in ('<<ComboboxSelected>>', '<ButtonRelease-1>', '<FocusIn>'):
        root.bind_class('TCombobox', event, clear_dropdown_selection, add='+')

    style.configure('Treeview', background=field, fieldbackground=field, foreground=foreground, borderwidth=0, rowheight=28)
    style.map('Treeview', background=[('selected', selected)], foreground=[('selected', '#ffffff')])
    style.configure('Treeview.Heading', background=COLORS['button_bg'], foreground=foreground)
    style.map('Treeview.Heading', background=[('active', COLORS['button_active_bg'])])
    style.configure('TLabelframe', bordercolor=border)
    style.configure('TLabelframe.Label', foreground=foreground)
    style.configure('TScrollbar', background=COLORS['scrollbar_bg'], troughcolor=COLORS['scrollbar_trough_bg'], arrowcolor=COLORS['scrollbar_arrow_fg'], borderwidth=0, arrowsize=16, width=16)
    style.map('TScrollbar', background=[('active', COLORS['scrollbar_active_bg']), ('pressed', COLORS['button_pressed_bg'])])

    # Flat thumbs so the scrollbars stop looking crusty...
    def thumb(name, size, border):
        images = [ImageTk.PhotoImage(Image.new('RGBA', size, color), master=root)
                  for color in (COLORS['scrollbar_bg'], COLORS['scrollbar_active_bg'], COLORS['button_active_bg'])]

        if not hasattr(root, '_slider_images'):
            root._slider_images = []

        root._slider_images.extend(images)

        if name not in style.element_names():
            style.element_create(name, 'image', images[0], ('pressed', images[2]), ('active', images[1]), border=border, sticky='nsew')

    thumb('LitterBox.Scale.slider', (12, 20), 2)
    thumb('LitterBox.Horizontal.thumb', (32, 16), 3)
    thumb('LitterBox.Vertical.thumb', (16, 32), 3)

    arrow_points = {
        'uparrow': [(4, 10), (8, 5), (12, 10)],
        'downarrow': [(4, 6), (8, 11), (12, 6)],
        'leftarrow': [(10, 4), (5, 8), (10, 12)],
        'rightarrow': [(6, 4), (11, 8), (6, 12)]
    }

    for direction, points in arrow_points.items():
        images = []

        for color in (COLORS['scrollbar_bg'], COLORS['scrollbar_active_bg'], COLORS['button_pressed_bg']):
            image = Image.new('RGBA', (16, 16), color)
            ImageDraw.Draw(image).polygon(points, fill=COLORS['scrollbar_arrow_fg'])
            images.append(ImageTk.PhotoImage(image, master=root))

        root._slider_images.extend(images)
        name = 'LitterBox.' + direction

        if name not in style.element_names():
            style.element_create(name, 'image', images[0], ('pressed', images[2]), ('active', images[1]), sticky='nsew')

    style.layout('Horizontal.TScale', [
        ('Horizontal.Scale.trough', {
            'sticky': 'ew',
            'children': [
                ('LitterBox.Scale.slider', {'side': 'left', 'sticky': 'ns'})
            ]
        })
    ])
    
    style.configure('Horizontal.TScale', troughcolor=COLORS['scrollbar_trough_bg'], bordercolor=border, lightcolor=border, darkcolor=border, background=background)

    def replace_thumb(layout, element):
        result = []

        for name, options in layout:
            options = dict(options)

            if 'children' in options:
                options['children'] = replace_thumb(options['children'], element)

            if name.rsplit('.', 1)[-1] in arrow_points:
                name = 'LitterBox.' + name.rsplit('.', 1)[-1]
                options['sticky'] = 'ew' if 'Vertical' in element else 'ns'

            result.append((element if name.endswith('.thumb') else name, options))

        return result

    for orientation in ('Horizontal', 'Vertical'):
        name = orientation + '.TScrollbar'
        style.layout(name, replace_thumb(style.layout(name), 'LitterBox.' + orientation + '.thumb'))

    def scrollbar_drag(event):
        widget = event.widget
        horizontal = str(widget.cget('orient')) == 'horizontal'
        coordinate = event.x if horizontal else event.y
        length = widget.winfo_width() if horizontal else widget.winfo_height()
        element = widget.identify(event.x, event.y)

        if event.type == tk.EventType.ButtonPress:
            if 'arrow' in element:
                return

            widget._track_drag = True

        if not getattr(widget, '_track_drag', False):
            return

        # Put the thumb under the mouse and keep it inside the damn track...
        arrow = int(float(ttk.Style(widget).lookup('TScrollbar', 'arrowsize') or 16))
        first, last = widget.get()
        span = last - first
        position = (coordinate - arrow) / max(1, length - 2 * arrow) - span / 2
        position = max(0.0, min(max(0.0, 1 - span), position))
        command = widget.cget('command')

        if command:
            widget.tk.call(*widget.tk.splitlist(command), 'moveto', position)

        return 'break'

    def scrollbar_release(event):
        if getattr(event.widget, '_track_drag', False):
            event.widget._track_drag = False

            return 'break'

    # Get in before Tk does its jumping crap...
    root.bind_class('LitterBoxScrollbar', '<Button-1>', scrollbar_drag)
    root.bind_class('LitterBoxScrollbar', '<B1-Motion>', scrollbar_drag)
    root.bind_class('LitterBoxScrollbar', '<ButtonRelease-1>', scrollbar_release)

    def prepare_scrollbar(event):
        widget = event.widget
        tags = widget.bindtags()

        if 'LitterBoxScrollbar' not in tags:
            widget.bindtags((tags[0], 'LitterBoxScrollbar', *tags[1:]))

    root.bind_class('TScrollbar', '<Map>', prepare_scrollbar, add='+')
    checkbox_images = []

    for checked, hover in ((False, False), (False, True), (True, False), (True, True)):
        image = Image.new('RGBA', (96, 80), (0, 0, 0, 0))
        pen = ImageDraw.Draw(image)
        pen.rounded_rectangle((2, 6, 66, 70), radius=8, fill=COLORS['button_active_bg'] if checked else COLORS['button_bg'], outline='#b0b0b0' if hover else '#727272', width=4)

        if checked:
            pen.line([(16, 37), (29, 50), (53, 24)], fill='#eeeeee', width=8, joint='curve')

        checkbox_images.append(ImageTk.PhotoImage(image.resize((24, 20), Image.Resampling.LANCZOS), master=root))

    root._slider_images.extend(checkbox_images)
    indicator = 'LitterBox.Checkbutton.indicator'

    if indicator not in style.element_names():
        style.element_create(indicator, 'image', checkbox_images[0], ('selected', 'active', checkbox_images[3]), ('selected', checkbox_images[2]), ('active', checkbox_images[1]))

    style.layout('Clean.TCheckbutton', [('Checkbutton.padding', {'sticky': 'nswe', 'children': [
        (indicator, {'side': 'left', 'sticky': 'w'}),
        ('Checkbutton.label', {'side': 'left', 'sticky': 'w'})]})])
    style.configure('Clean.TCheckbutton', padding=(2, 3))
    style.map('Clean.TCheckbutton', background=[('active', background)])

    return style

def configure_app_window(root):
    """Give setup and editor windows the same icon and identity..."""
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('LitterBox.LevelEditor')

    app_icon = ROOT / 'assets/icons/litterbox.ico'

    if sys.platform == 'win32' and app_icon.exists():
        root.iconbitmap(default=str(app_icon))
    else:
        app_icon = ROOT / 'assets/icons/litterbox.png'

        if app_icon.exists():
            root._app_icon = tk.PhotoImage(file=str(app_icon), master=root)
            root.iconphoto(True, root._app_icon)

def center_window(window, parent, width=None, height=None):
    """Put child windows over the editor..."""
    window.update_idletasks()
    minimum_width, minimum_height = window.minsize()
    width = max(width or 0, window.winfo_reqwidth(), minimum_width)
    height = max(height or 0, window.winfo_reqheight(), minimum_height)
    x = max(0, min(parent.winfo_rootx() + (parent.winfo_width() - width) // 2, window.winfo_screenwidth() - width))
    y = max(0, min(parent.winfo_rooty() + (parent.winfo_height() - height) // 2, window.winfo_screenheight() - height))
    window.geometry(f'{width}x{height}+{x}+{y}')
    window.deiconify()
    window.lift()
    window.focus_set()