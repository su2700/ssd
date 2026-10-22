import os
import sys
import ctypes
import logging
import tempfile
from logging.handlers import RotatingFileHandler

# Add project root to sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

def configure_logging():
    """Work with pythonw/PyInstaller (no stderr) and read-only install folders."""
    logger = logging.getLogger("ext4_mounter")
    logger.setLevel(logging.INFO)
    for base in (os.environ.get("LOCALAPPDATA"), tempfile.gettempdir()):
        if not base:
            continue
        try:
            folder = os.path.join(base, "Ext4-Mounter")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, "app.log")
            handler = RotatingFileHandler(path, maxBytes=1024 * 1024,
                                          backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s"))
            logger.addHandler(handler)
            return path
        except OSError:
            continue
    logger.addHandler(logging.NullHandler())
    return None


def show_startup_error(error, log_path):
    from core.diagnostics import explain_error
    detail = explain_error(error, context="startup", log_path=log_path)
    # A native dialog works even if importing tkinter or creating Tk failed.
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, detail, "Ext4-Mounter", 0x10)
    elif sys.stderr is not None:
        print(detail, file=sys.stderr)

def main():
    log_path = None
    try:
        log_path = configure_logging()
        # Import errors (including a missing Tcl/Tk runtime) belong inside here.
        from gui.app import run_app
        run_app()
        return 0
    except Exception as e:
        logging.getLogger("ext4_mounter").exception("Application startup failed")
        try:
            show_startup_error(e, log_path)
        except Exception:
            logging.getLogger("ext4_mounter").exception("Could not display startup error")
        return 1

if __name__ == "__main__":
    sys.exit(main())
