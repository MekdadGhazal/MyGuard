# PyInstaller spec: pyinstaller --noconfirm MyGuard.spec  (run on Windows)
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [("assets", "assets")], [], []
for pkg in ("mediapipe",):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(["run.py"], pathex=["."], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, excludes=["tkinter"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MyGuard", console=False,
          icon="assets/icons/app.ico", upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="MyGuard", upx=False)
