"""Report interpreter compatibility without importing application dependencies."""

import json
import struct
import sys


def runtime_info(version_info=None, bits=None):
    version_info = sys.version_info if version_info is None else version_info
    bits = struct.calcsize("P") * 8 if bits is None else bits
    major, minor, micro, releaselevel, serial = version_info
    return {
        "version": f"{major}.{minor}.{micro}",
        "bits": bits,
        "releaselevel": releaselevel,
        "compatible": (major, minor) == (3, 12) and releaselevel == "final" and bits == 64,
    }


if __name__ == "__main__":
    print(json.dumps(runtime_info()))
