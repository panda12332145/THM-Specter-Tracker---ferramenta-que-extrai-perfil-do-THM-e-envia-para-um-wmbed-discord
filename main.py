#!/usr/bin/env python3
"""Ponto de entrada do THM Specter Tracker (execução a partir da raiz)."""

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.main import main

if __name__ == "__main__":
    sys.exit(main())
