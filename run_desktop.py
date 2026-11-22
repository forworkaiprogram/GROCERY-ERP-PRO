"""Convenience launcher for development (no installer needed).

Run from the repository root:  python run_desktop.py
(The production entry point remains desktop/app/main.py, executed as a
module by the PyInstaller spec.)
"""

import sys

from desktop.app.main import main

if __name__ == "__main__":
    sys.exit(main())
