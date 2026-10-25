from pathlib import Path
import shutil

project = Path(SPECPATH)

a = Analysis(
    [str(project / 'app/main.py')],
    pathex=[str(project)],
    binaries=[],
    datas=[(str(project / folder), folder) for folder in ('assets', 'data', 'editor_icons', 'languages')],
    hiddenimports=['PIL._imagingtk', 'PIL._tkinter_finder'],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[],
    noarchive=False, optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='LitterBox', console=False, debug=False,
    strip=False, upx=False,
    icon=str(project / 'assets/icons/litterbox.ico'),
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='LitterBox')

# Keep editable resources beside the executable...
distribution = Path(DISTPATH)/'LitterBox'

for folder in ('assets', 'data', 'editor_icons', 'languages'):
    shutil.copytree(project/folder, distribution/folder, dirs_exist_ok=True)