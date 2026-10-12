"""Package only the two published executables and the launcher notes. No publishing."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import shutil
import tarfile
import zipfile


def main() -> None:
    launcher = Path(__file__).resolve().parent
    build = launcher / ".build"
    windows = build / "publish/win-x64/HearthLauncher.exe"
    linux = build / "publish/linux-x64/HearthLauncher"
    for binary in (windows, linux):
        if not binary.is_file() or binary.is_symlink() or binary.stat().st_size == 0:
            raise RuntimeError(f"Missing published executable: {binary}")
    notes = (launcher / "README.md").read_bytes()
    assets = build / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    portable = assets / "Hearth-Launcher.exe"
    shutil.copyfile(windows, portable)
    win_zip = assets / "Hearth-Launcher-Windows-x64.zip"
    with zipfile.ZipFile(win_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(windows, "Hearth-Launcher.exe")
        archive.writestr("README.md", notes)
    linux_tar = assets / "Hearth-Launcher-Linux.tar.gz"
    with tarfile.open(linux_tar, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        entry = tarfile.TarInfo("Hearth-Launcher")
        entry.size, entry.mode = linux.stat().st_size, 0o755
        with linux.open("rb") as content:
            archive.addfile(entry, content)
        entry = tarfile.TarInfo("README.md")
        entry.size, entry.mode = len(notes), 0o644
        archive.addfile(entry, io.BytesIO(notes))
    selected = (portable, win_zip, linux_tar)
    sums = []
    for path in selected:
        digest = hashlib.sha256()
        with path.open("rb") as content:
            for block in iter(lambda: content.read(1024 * 1024), b""):
                digest.update(block)
        sums.append(f"{digest.hexdigest()}  {path.name}")
    (assets / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print("Packaged Windows EXE/ZIP and Linux TAR.GZ with executable permissions.")


if __name__ == "__main__":
    main()
