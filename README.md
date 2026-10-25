# LitterBox
A Mewgenics level editor with built-in mod support, in-game playtesting, and hot reloading!

<img width="960" height="540" alt="image" src="https://github.com/user-attachments/assets/0e1d461a-3878-4d5f-8ab2-91425cd3723a" />

## Features

- Create, open, and save `.lvl` files.
- Paint tiles and spawns with placement previews, footprint outlines, and overlap protection.
- Search by name or ID and filter by category, vanilla content, or a specific mod.
- Switch between a flat board and an isometric view, with zoom and automatic fitting.
- Inspect placements to configure weighted random choices, linked rolls, and spawn waves.
- Load mod definitions and custom editor icons alongside vanilla content.
- Launch the game directly into a level and hotload any edits while the playtest is running, including unsaved changes!
- Use optional side-by-side mode to arrange the editor and game alongside eachother for faster iteration.
- Faithful to how the original developer level editor may have functioned!

## Getting started

Run `LitterBox.exe`. On first launch, LitterBox looks for your Steam installation of Mewgenics. If it cannot find the game, browse to the folder containing `Mewgenics.exe` and `resources.gpak`.

The required vanilla definitions that the program uses and keeps track of are extracted automatically. Once preparation finishes, just click **Confirm** to open the editor! Setup is remembered for future launches.

Select **New** to start from a blank level layout, or **Load** to open an existing `.lvl` file. 

Choose the "Tiles" or "Spawns" layer, select an entry, and paint it onto the board. 

Switch over to **Inspect** and click on any placement to edit it's settings.

## Controls

| Control | Action |
| --- | --- |
| Left mouse button in Paint mode | Place the selected tile or spawn |
| Right mouse button in Paint mode | Erase a placement |
| Middle mouse button in Paint mode | Pick a tile or spawn from the board |
| Left mouse button in Inspect mode | Select a placement for editing |
| Mouse wheel over the board | Zoom |
| Ctrl+Z / Ctrl+Y | Undo / redo |
| Ctrl+O | Open a level |
| Ctrl+S | Save |
| F6 | Start a playtest or hotload changes |
| Hold F6 | Stop the playtest |

## Mod support

Mod support has been made super streamlined for convenience!

Just open **Mod assets**, choose **Add mod folder**, and locate the mod folder to add. LitterBox automatically finds `spawns.gon` and `tiles.gon` definitions, (including `.gon.append` and `.gon.patch` files) and includes them, it also pulls custom icons for your entries from the mod's `editor_icons` folder if it provides one.

Example layout:

```text
MyMod/
├── data/
│   ├── spawns.gon.append
│   └── tiles.gon.append
└── editor_icons/
    └── my_spawn_or_tile_icon_1.png
```

Unmodified vanilla game entries always will remain available. It's recommended to always use unique numeric IDs for entries in your mods, definitions that conflict with vanilla or previously loaded entries are skipped! 

The content filter in the editor lets you show just vanilla entries, only modded entries, or even entries that are just from a particular mod!

Single-line or multiline comments immediately above the numeric spawns or tiles GON entry appear as a description in the editor's info area, so modders can add their own editor exposed context for stuff!

## Playtesting

Open **Playtest** and choose the mod you want to test the level out for (if applicable, otherwise just use vanilla), then select **Start playtest**. LitterBox will launch the game directly into a temporary copy of the level without requiring you to save your changes first.

While the playtest is running, use **Hotload changes** or press **F6** to reload your edits. The F6 shortcut also works while you are in-game, and the playtest window does not need to stay open. Hold F6 or use **Stop playtest** to end the session.

Tileset detection uses available map definitions, including those from the selected mod, and falls back to alley when it cannot determine a tileset for whatever reason. You can also specify one manually. Associated map weather is applied when it can be resolved as well.

**Side-by-side mode** switches the game to windowed mode and arranges it right beside the editor. This makes things more convenient for iteration, since you can make a change in a level you're playtesting and easily hotload to immediately see the result. Turning this off will restore the game's normal display settings, so don't worry about that.

NOTE: The playtesting feature may require an update of the editor when the game releases an substantial update, so don't be surprised if this feature remains broken for a while. 

Playtesting also handles the loading of DLL mods, and for that, Mewjector's chainloader (`version.dll` and `chainloader.ini`) must already be installed!

## Running from source

From the project folder:

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m app.main
```

After installing dependencies, you can just use `Start Editor.bat` for convenience.

## Building for Windows

After setting up the environment, run:

```bat
"Build Windows.bat"
```

The PyInstaller build is created at `dist\LitterBox\LitterBox.exe`.

The application version is set in `app/version.py`.
