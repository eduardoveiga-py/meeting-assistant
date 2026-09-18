import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    # Create QApplication before any service QObject and keep it alive for the suite.
    app = QApplication.instance() or QApplication([])
    yield app
