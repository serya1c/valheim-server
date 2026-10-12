"""Package portable launchers and self-contained, per-user setup distributions."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
from pathlib import Path
import shutil
import tarfile
import zipfile

LAUNCHER_VERSION = "1.1.0"
ASSET_NAMES = ("Hearth-Launcher.exe", "Hearth-Launcher-Windows-x64.zip", "Hearth-Launcher-Linux.tar.gz",
               "Hearth-Launcher-Setup.exe", "Hearth-Launcher-Install-Linux.sh")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as content:
        for block in iter(lambda: content.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def regular(path: Path) -> None:
    if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
        raise RuntimeError(f"Missing regular build asset: {path}")


def linux_payload(launcher: Path, binary: Path) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
        for path, name, mode in ((binary, "Hearth-Launcher", 0o755),
                                (launcher / "Assets/hearth.png", "hearth.png", 0o644),
                                (launcher / "README.md", "README.md", 0o644)):
            regular(path)
            data = path.read_bytes()
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode, entry.mtime = len(data), mode, 0
            archive.addfile(entry, io.BytesIO(data))
    return output.getvalue()


def prepare(launcher: Path, build: Path) -> None:
    windows = build / "publish/win-x64/HearthLauncher.exe"
    regular(windows)
    with zipfile.ZipFile(build / "setup-payload.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, name in ((windows, "Hearth-Launcher.exe"),
                           (launcher / "Assets/hearth.ico", "hearth.ico"),
                           (launcher / "README.md", "README.md")):
            regular(path)
            entry = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, path.read_bytes())
    (build / "setup-payload.sha256").write_text(digest(build / "setup-payload.zip") + "\n", encoding="ascii")
    print("Prepared the setup's embedded Windows launcher payload.")


def finish(launcher: Path, build: Path) -> None:
    windows = build / "publish/win-x64/HearthLauncher.exe"
    linux = build / "publish/linux-x64/HearthLauncher"
    setup = build / "publish/setup-win-x64/Hearth-Launcher-Setup.exe"
    for binary in (windows, linux, setup):
        regular(binary)
    assets = build / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(windows, assets / ASSET_NAMES[0])
    with zipfile.ZipFile(assets / ASSET_NAMES[1], "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(windows, "Hearth-Launcher.exe")
        archive.writestr("README.md", (launcher / "README.md").read_bytes())
        archive.writestr("hearth.ico", (launcher / "Assets/hearth.ico").read_bytes())
    payload = linux_payload(launcher, linux)
    (assets / ASSET_NAMES[2]).write_bytes(payload)
    shutil.copyfile(setup, assets / ASSET_NAMES[3])
    template = (launcher / "setup/linux-install.sh").read_text(encoding="utf-8")
    template = template.replace("@PAYLOAD_SHA256@", hashlib.sha256(payload).hexdigest())
    if not template.endswith("__HEARTH_PAYLOAD__\n"):
        raise RuntimeError("The Linux setup template has an unexpected payload delimiter.")
    (assets / ASSET_NAMES[4]).write_bytes(template.encode("utf-8") + base64.encodebytes(payload))
    (assets / "Hearth-Launcher.version").write_text(LAUNCHER_VERSION + "\n", encoding="ascii")
    sums = []
    for name in ASSET_NAMES:
        path = assets / name
        value = digest(path)
        (assets / (name + ".sha256")).write_text(f"{value}  {name}\n", encoding="ascii")
        sums.append(f"{value}  {name}")
    (assets / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="ascii")
    print("Packaged Windows/Linux portable launchers, offline setup installers, version and SHA-256 sidecars.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-setup", action="store_true")
    args = parser.parse_args()
    launcher = Path(__file__).resolve().parent
    build = launcher / ".build"
    if args.prepare_setup:
        prepare(launcher, build)
    else:
        finish(launcher, build)


if __name__ == "__main__":
    main()
