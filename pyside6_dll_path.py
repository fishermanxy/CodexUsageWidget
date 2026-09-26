"""Make PySide6 and shiboken6 DLLs visible in frozen Windows builds."""

import os
import sys


if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _dll_dirs = [
        os.path.join(sys._MEIPASS, "PySide6"),
        os.path.join(sys._MEIPASS, "shiboken6"),
    ]
    os.environ["PATH"] = os.pathsep.join(_dll_dirs + [os.environ.get("PATH", "")])
    if hasattr(os, "add_dll_directory"):
        # QtCore.pyd depends on shiboken6.abi3.dll in a sibling directory.
        # Keep both handles alive for the lifetime of the frozen process.
        sys._pyside6_dll_directories = [
            os.add_dll_directory(path)
            for path in _dll_dirs
            if os.path.isdir(path)
        ]
