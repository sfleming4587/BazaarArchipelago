"""
Build bazaar.apworld into the repo root and releases/, the same way Archipelago's "Build APWorlds" launcher
command does, but without opening a file explorer window afterwards.

Run from the repo root with the dev venv:
    .venv/Scripts/python.exe tools/build_apworld.py
"""
import importlib
import json
import os
import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
AP = ROOT / "Archipelago"
WORLD = "bazaar"


def main() -> None:
    os.chdir(AP)
    sys.path.insert(0, str(AP))
    importlib.import_module("ModuleUpdate")  # same environment checks the launcher does
    from Utils import local_path, read_apignore
    from worlds.Files import APWorldContainer

    world_directory = pathlib.Path("worlds", WORLD)
    with open(world_directory / "archipelago.json", encoding="utf-8") as f:
        manifest = json.load(f)
    out = ROOT / f"{WORLD}.apworld"
    container = APWorldContainer(str(out))
    container.game = manifest["game"]
    manifest.update(container.get_manifest())

    ignores = read_apignore(local_path("data", "GLOBAL.apignore"))
    local = read_apignore(world_directory / ".apignore")
    if local:
        ignores = ignores + local
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for file in ignores.match_tree_files(str(world_directory), negate=True):
            zf.write(world_directory / file, pathlib.Path(WORLD, file))
        zf.writestr(f"{WORLD}/archipelago.json", json.dumps(manifest))
    release = ROOT / "releases" / out.name  # the copy players download from GitHub
    release.parent.mkdir(exist_ok=True)
    release.write_bytes(out.read_bytes())
    print(f"built {out} and {release} (world_version {manifest.get('world_version')})")


if __name__ == "__main__":
    main()
