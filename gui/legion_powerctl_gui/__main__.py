# SPDX-License-Identifier: MIT

import sys

from PySide6.QtWidgets import QApplication

from . import scheme
from .app import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("legion-powerctl")
    app.setDesktopFileName("legion-powerctl")
    scheme.install(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
