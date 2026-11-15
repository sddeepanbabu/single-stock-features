"""Allow `python -m sba`."""
import sys

from sba.cli import main

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
