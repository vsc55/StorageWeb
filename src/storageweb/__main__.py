"""Permite ``python -m storageweb <comando>``."""
import sys

from .cli import main

sys.exit(main())
