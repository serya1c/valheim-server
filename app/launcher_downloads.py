"""Public metadata for launcher installers and portable builds in this image."""
from pathlib import Path
import re

NAMES = {'windows': 'Hearth-Launcher-Setup.exe', 'linux': 'Hearth-Launcher-Install-Linux.sh',
         'windows_portable': 'Hearth-Launcher.exe', 'linux_portable': 'Hearth-Launcher-Linux.tar.gz'}
DOWNLOAD_NAMES = frozenset(name + suffix for name in NAMES.values() for suffix in ('', '.sha256'))


def launcher_downloads(folder=None):
    folder = Path(folder) if folder is not None else Path(__file__).parent / 'downloads'
    version_file = folder / 'Hearth-Launcher.version'
    if not version_file.is_file() or version_file.is_symlink() or version_file.stat().st_size > 32:
        return None
    try:
        version = version_file.read_text(encoding='ascii').strip()
    except (OSError, UnicodeError):
        return None
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        return None
    result = {'version': version}
    for platform, name in NAMES.items():
        binary, digest_file = folder / name, folder / (name + '.sha256')
        if (not binary.is_file() or binary.is_symlink() or not 0 < binary.stat().st_size <= 100 * 1024 * 1024
                or not digest_file.is_file() or digest_file.is_symlink() or digest_file.stat().st_size > 256):
            continue
        try:
            fields = digest_file.read_text(encoding='ascii').strip().split()
        except (OSError, UnicodeError):
            continue
        if len(fields) != 2 or not re.fullmatch(r'[a-fA-F0-9]{64}', fields[0]) or fields[1] != name:
            continue
        result[platform] = {'url': '/downloads/' + name, 'sha256': fields[0].lower(),
                            'size': binary.stat().st_size, 'checksum_url': '/downloads/' + name + '.sha256'}
    return result if len(result) > 1 else None
