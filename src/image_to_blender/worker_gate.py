# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows worker waits until its parent has placed it inside a Job Object."""
import subprocess
import sys

if __name__ == "__main__":
    if sys.stdin.readline() != "start\n" or len(sys.argv) < 2:
        raise SystemExit(125)
    raise SystemExit(subprocess.call(sys.argv[1:], stdin=subprocess.DEVNULL))
