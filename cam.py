#!/usr/bin/env python3
"""
Entry point for cam, all code is in src\cam.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from cam.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
