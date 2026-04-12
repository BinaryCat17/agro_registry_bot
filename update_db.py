#!/usr/bin/env python3
"""Обновление базы данных реестра Минсельхоза."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.importer import run_import

if __name__ == "__main__":
    run_import()
