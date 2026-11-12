# PyInstaller build recipe for macOS (.app) and Windows (folder with .exe).
#   pyinstaller --noconfirm Pin.spec
# Build the screensaver first (saver/mac/build.sh, or the dotnet publish in
# build_windows.bat); it's copied into the app so Pin can install and update it.
import os
import shutil
import subprocess
import sys

root = SPECPATH
version = open(os.path.join(root, "VERSION")).read().strip()

datas = [
    (os.path.join(root, "pin", "ui"), os.path.join("pin", "ui")),
    (os.path.join(root, "VERSION"), "."),
]

a = Analysis(
    [os.path.join(root, "Pin.py")],
    pathex=[root],
    datas=datas,
    hiddenimports=["certifi"],
    excludes=["tkinter", "_tkinter"],
)
pyz = PYZ(a.pure)
icon = os.path.join(root, "assets", "AppIcon.icns" if sys.platform == "darwin" else "icon.ico")

exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Pin", console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, name="Pin")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Pin.app",
        icon=icon,
        bundle_identifier="com.yuvrajgarg.pin",
        version=version,
        info_plist={
            "CFBundleShortVersionString": version,
            "CFBundleVersion": version,
            "CFBundleDisplayName": "Pin",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            "NSRequiresAquaSystemAppearance": False,
            "LSApplicationCategoryType": "public.app-category.lifestyle",
        },
    )
    # The screensaver is its own signed bundle; PyInstaller would take it apart as
    # data, so it goes in afterwards and the app is signed again (ad hoc).
    saver = os.path.join(root, "saver", "mac", "build", "Pin.saver")
    dest_app = os.path.join(DISTPATH, "Pin.app")
    if os.path.isdir(saver):
        dest = os.path.join(dest_app, "Contents", "Resources", "saver", "Pin.saver")
        shutil.rmtree(dest, ignore_errors=True)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        subprocess.check_call(["/usr/bin/ditto", saver, dest])
        subprocess.check_call(["/usr/bin/codesign", "--force", "--sign", "-", dest_app])
    else:
        print("WARNING: saver/mac/build/Pin.saver missing; Pin.app won't include the screensaver")
else:
    scr = os.path.join(root, "saver", "windows", "publish", "Pin.scr")
    if os.path.isfile(scr):
        dest = os.path.join(DISTPATH, "Pin", "_internal", "saver")
        os.makedirs(dest, exist_ok=True)
        shutil.copyfile(scr, os.path.join(dest, "Pin.scr"))
    else:
        print("WARNING: saver/windows/publish/Pin.scr missing; Pin won't include the screensaver")
