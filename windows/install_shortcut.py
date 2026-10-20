#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Install per-user Windows Start Menu and desktop shortcuts.

The Windows implementation lives in windows_shortcut so installation and the
console-free shortcut bootstrap share one launcher configuration format.
"""


def main(argv=None):
    from windows_shortcut import main as windows_main
    return windows_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
