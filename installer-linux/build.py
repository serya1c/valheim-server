from pathlib import Path
import hashlib
root=Path(__file__).resolve().parent
source=(root/'loki_installer.py').read_text(encoding='utf-8-sig')
wrapper='''#!/bin/sh
# Loki / Steam Proton. Run as your user: bash Loki-Mod-Installer-Linux.sh
if ! command -v python3 >/dev/null 2>&1; then
    echo "Нужен Python 3.9 или новее. Установите python3 средствами своего дистрибутива." >&2
    exit 1
fi
exec python3 -c 'import sys; sys.version_info >= (3,9) or sys.exit("Нужен Python 3.9 или новее"); p=sys.argv[1]; sys.argv=sys.argv[1:]; exec(compile(open(p,encoding="utf-8").read().split("# LOKI_PYTHON_SOURCE\\n",1)[1],p,"exec"))' "$0" "$@"
exit 1
# LOKI_PYTHON_SOURCE
'''
dest=root.parent/'app/downloads/Loki-Mod-Installer-Linux.sh'
dest.write_bytes((wrapper+source).encode('utf-8'))
dest.with_suffix('.sh.sha256').write_text(hashlib.sha256(dest.read_bytes()).hexdigest()+'  '+dest.name+'\n',encoding='ascii')
print('Built:',dest.name)
