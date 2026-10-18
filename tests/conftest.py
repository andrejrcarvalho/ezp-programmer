import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp(tmp_path_factory):
    """One QApplication for all GUI tests, with settings sandboxed away from the user's."""
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from ezp_programmer import theme

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path_factory.mktemp("settings")))
    app = QApplication.instance() or QApplication([])
    theme.apply(app)
    return app


class Dialogs:
    """Records message boxes instead of showing them; answers questions with Yes."""

    def __init__(self) -> None:
        self.info: list[str] = []
        self.warnings: list[str] = []


@pytest.fixture
def dialogs(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    d = Dialogs()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda _p, title, text, *a, **k: d.info.append(f"{title}: {text}")))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda _p, title, text, *a, **k: d.warnings.append(f"{title}: {text}")))
    return d


@pytest.fixture
def window(qapp, dialogs, tmp_path, monkeypatch):
    from ezp_programmer import main_window

    monkeypatch.setattr(main_window.MainWindow, "_backup_dir", lambda self: tmp_path / "backups")
    w = main_window.MainWindow()
    w.show()

    def wait(timeout: float = 30.0) -> None:
        end = time.monotonic() + timeout
        while w.worker is not None:
            if time.monotonic() > end:
                raise TimeoutError("operation did not finish")
            qapp.processEvents()
            time.sleep(0.005)
        qapp.processEvents()

    w.wait = wait
    yield w
    w.programmer = None  # skip the close-on-exit path
    w.close()
    w.deleteLater()
    qapp.processEvents()
