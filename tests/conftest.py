import gc

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    # Create QApplication before any service QObject and keep it alive for the suite.
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def collect_qt_objects_between_tests(qt_application):
    # Dispose cycles from signal callbacks before another widget is constructed.
    # Collection during a PySide widget constructor can destroy older Qt wrappers.
    gc.collect()
    yield
    gc.collect()
