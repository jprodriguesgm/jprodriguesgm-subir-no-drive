# PyInstaller: monta o "Subir no Drive.app" (Mac, Apple Silicon).
#   python packaging/build_deps.py        (antes: bin/ e models/)
#   pyinstaller --noconfirm packaging/subir.spec
# Resultado em dist/.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(ROOT))
from subir import __version__  # noqa: E402

NAME = "Subir no Drive"

datas = [(str(ROOT / "subir" / "ui"), "subir/ui")]
model = ROOT / "models" / "ggml-small-q5_1.bin"
if model.is_file():
    datas.append((str(model), "models"))
else:
    print("AVISO: sem o modelo do Whisper (a transcrição fica desligada neste pacote)")

binaries = []
for p in sorted((ROOT / "bin").glob("*")):
    if p.is_file() and not p.name.startswith("."):
        if p.suffix.lower() == ".txt":
            datas.append((str(p), "bin"))
        else:
            binaries.append((str(p), "bin"))

a = Analysis(
    [str(ROOT / "packaging" / "app_main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=collect_submodules("subir") + ["AppKit", "Foundation", "WebKit", "objc",
                                                 "PyObjCTools", "PyObjCTools.AppHelper"],
    excludes=["tkinter", "matplotlib", "cv2", "pytest", "playwright", "IPython", "PIL"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=NAME,
    console=False,
    icon=str(ROOT / "packaging" / "icon" / "icon.icns"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)

app = BUNDLE(
    coll,
    name=NAME + ".app",
    icon=str(ROOT / "packaging" / "icon" / "icon.icns"),
    bundle_identifier="br.pucminas.npd.subirnodrive",
    version=__version__,
    info_plist={
        "CFBundleDisplayName": "Subir no Drive",
        "CFBundleName": "Subir no Drive",
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        # aceita arquivos e pastas arrastados para o ícone (sem virar o app padrão de nada)
        "CFBundleDocumentTypes": [{
            "CFBundleTypeName": "Arquivos para subir",
            "CFBundleTypeRole": "Viewer",
            "LSHandlerRank": "Alternate",
            "LSItemContentTypes": ["public.item", "public.folder", "public.movie"],
        }],
        "NSDesktopFolderUsageDescription": "O Subir no Drive lê os vídeos que você escolher para enviar.",
        "NSDocumentsFolderUsageDescription": "O Subir no Drive lê os vídeos que você escolher para enviar.",
        "NSDownloadsFolderUsageDescription": "O Subir no Drive lê os vídeos que você escolher para enviar.",
        "NSRemovableVolumesUsageDescription": "O Subir no Drive lê os vídeos do disco externo que você escolher.",
        "NSNetworkVolumesUsageDescription": "O Subir no Drive lê os vídeos da pasta de rede que você escolher.",
    },
)
