"""`python -m cc_warehouse` entry point: the detached render child is spawned this way
(SPEC section 2.5). Thin wrapper; all logic lives in cli.main."""

import sys

from cc_warehouse.cli import main

if __name__ == "__main__":
    sys.exit(main())
