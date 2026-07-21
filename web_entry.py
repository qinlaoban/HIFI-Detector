"""PyInstaller entry point for the HIFI Detector web server.
Uses absolute imports so PyInstaller can resolve the package correctly.
"""

import sys

from hifi_detector.cli import app

if __name__ == "__main__":
    sys.argv = ["hifi-detect", "web"] + sys.argv[1:]
    app()
