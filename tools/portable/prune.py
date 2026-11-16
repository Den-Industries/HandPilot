"""Strip everything HandPilot does not use from the bundled site-packages (run once after install)."""
import fnmatch
import os
import shutil
import sys

SP = os.path.join(sys.argv[1], "Lib", "site-packages")


def rm(path):
    if os.path.isdir(path):
        shutil.rmtree(path)
    elif os.path.exists(path):
        os.remove(path)


def size(path):
    total = 0
    for root, _, files in os.walk(path):
        total += sum(os.path.getsize(os.path.join(root, f)) for f in files)
    return total


before = size(SP)

# ---- PySide6: keep Core / Gui / Widgets and the few plugins the app needs --------------------
ps = os.path.join(SP, "PySide6")
keep_root = ["__init__.py", "_config.py", "_git_pyside_version.py", "QtCore.pyd", "QtGui.pyd", "QtWidgets.pyd",
             "pyside6.abi3.dll", "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll",
             "msvcp140*.dll", "vcruntime140*.dll", "concrt140.dll"]
for name in os.listdir(ps):
    p = os.path.join(ps, name)
    if os.path.isfile(p) and not any(fnmatch.fnmatch(name, k) for k in keep_root):
        os.remove(p)
keep_plugins = {"platforms": ["qwindows.dll", "qoffscreen.dll"], "styles": ["qmodernwindowsstyle.dll"],
                "imageformats": ["qico.dll", "qjpeg.dll", "qgif.dll"]}
plugins = os.path.join(ps, "plugins")
for d in os.listdir(plugins):
    p = os.path.join(plugins, d)
    if d not in keep_plugins:
        rm(p)
        continue
    for f in os.listdir(p):
        if f not in keep_plugins[d]:
            rm(os.path.join(p, f))
for d in ("translations", "qml", "typesystems", "include", "glue", "resources", "scripts", "support",
          "metatypes", "lib", "examples", "doc"):
    rm(os.path.join(ps, d))

# ---- OpenCV: no ffmpeg (camera capture uses DirectShow), no bundled cascades ------------------
cv = os.path.join(SP, "cv2")
for f in os.listdir(cv):
    if f.startswith("opencv_videoio_ffmpeg"):
        rm(os.path.join(cv, f))
rm(os.path.join(cv, "data"))

# ---- MediaPipe: legacy "solutions" models/graphs and tooling the Tasks API does not need -----
mp = os.path.join(SP, "mediapipe")
for r, _, fs in os.walk(os.path.join(mp, "modules")):   # keep the .py protos, drop the model data
    for f in fs:
        if f.endswith((".tflite", ".binarypb", ".pbtxt", ".txt")):
            os.remove(os.path.join(r, f))
rm(os.path.join(mp, "model_maker"))

# ---- generic junk ----------------------------------------------------------------------------
for root, dirs, files in os.walk(SP):
    for d in list(dirs):
        if d in ("tests", "test", "__pycache__"):
            rm(os.path.join(root, d))
            dirs.remove(d)
    for f in files:
        if f.endswith((".pyi", ".pyc", ".h", ".hpp", ".lib", ".c", ".cpp", ".pxd", ".typed")):
            os.remove(os.path.join(root, f))

after = size(SP)
print(f"site-packages: {before / 2**20:.0f} MB -> {after / 2**20:.0f} MB")


