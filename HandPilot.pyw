"""Double-click launcher (no console window): starts HandPilot."""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.chdir(ROOT)


def _report_crash() -> None:
    """Without a console a startup failure would be invisible: log it and tell the user."""
    import traceback
    text = traceback.format_exc()
    try:
        base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
        d = os.path.join(base, "HandPilot")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "crash.log")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, f"HandPilot не смог запуститься.\n\n{text[-700:]}\n\nПодробности: {path}", "HandPilot", 0x10)
    except Exception:
        pass


try:
    from handpilot.__main__ import main
    code = main()
except SystemExit:
    raise
except BaseException:
    _report_crash()
    code = 1
sys.exit(code)
