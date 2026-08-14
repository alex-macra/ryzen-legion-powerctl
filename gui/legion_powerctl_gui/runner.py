# SPDX-License-Identifier: MIT

from __future__ import annotations

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

TIMED_OUT = 124


class CommandRunner(QObject):
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.processes: list[QProcess] = []

    def run(self, argv: list[str], on_done, timeout_ms: int | None = None) -> None:
        process = QProcess(self)
        self.processes.append(process)

        def finished(code: int, status) -> None:
            if process not in self.processes:
                return
            stdout = bytes(process.readAllStandardOutput()).decode("utf-8", "replace")
            stderr = bytes(process.readAllStandardError()).decode("utf-8", "replace")
            self.processes.remove(process)
            process.deleteLater()
            if status == QProcess.ExitStatus.CrashExit:
                code = code or 1
                stderr = f"{stderr.rstrip()}\n{argv[0]} crashed.".lstrip()
            on_done(code, stdout, stderr)

        def error_occurred(err) -> None:
            if err == QProcess.ProcessError.FailedToStart and process in self.processes:
                self.processes.remove(process)
                process.deleteLater()
                self.failed.emit(f"Could not run {argv[0]}: {process.errorString()}")

        def timed_out() -> None:
            if process not in self.processes:
                return
            stdout = bytes(process.readAllStandardOutput()).decode("utf-8", "replace")
            self.processes.remove(process)
            process.setParent(None)
            process.kill()
            process.waitForFinished(200)
            process.deleteLater()
            on_done(
                TIMED_OUT,
                stdout,
                f"{argv[0]} did not finish within {timeout_ms // 1000} s.",
            )

        process.finished.connect(finished)
        process.errorOccurred.connect(error_occurred)
        if timeout_ms is not None:
            QTimer.singleShot(timeout_ms, timed_out)
        process.start(argv[0], argv[1:])

    def stop_all(self) -> None:
        for process in self.processes:
            process.finished.disconnect()
            process.errorOccurred.disconnect()
            process.setParent(None)
            process.terminate()
            if not process.waitForFinished(200):
                process.kill()
            process.deleteLater()
        self.processes.clear()
