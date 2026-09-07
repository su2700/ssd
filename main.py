import os
import sys

# Add project root to sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from gui.app import run_app

def main():
    try:
        run_app()
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            from tkinter import messagebox
            messagebox.showerror("运行异常", f"程序启动失败: {str(e)}")
        except Exception:
            pass

if __name__ == "__main__":
    main()
