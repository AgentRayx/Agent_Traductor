"""PyInstaller entry point for subforge.exe."""
import multiprocessing
import sys

from subforge.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
