"""Admin-Fenster: Sidebar links, Seiten-Stack rechts (Spec Abschnitt 4).

Nicht-modal, EIN Fenster zur Zeit (das Hauptfenster fokussiert eine
bestehende Instanz). Teilt mit dem Hauptfenster keinen Zustand — die
einzige Meldung Hauptfenster → Admin in 1a ist der Kamera-Zustand als
Callable (Pull, kein gemeinsames Objekt, kein Rückkanal)."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget,
                               QMainWindow, QStackedWidget, QVBoxLayout,
                               QWidget)

from .pages.reports_page import ReportsPage
from .pages.status_page import StatusPage

_SEITEN = ("Status", "Reports", "Analyse", "Artikel", "Diagnose")


def _platzhalter(text: str) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lab = QLabel(text)
    lab.setAlignment(Qt.AlignCenter)
    lab.setWordWrap(True)
    lab.setObjectName("guideLabel")
    lay.addWidget(lab)
    return w


class AdminWindow(QMainWindow):
    def __init__(self, cfg: dict, camera_status: Callable[[], str],
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Doco Detect – Admin")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMinimumSize(900, 600)
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("adminSidebar")
        self.sidebar.setFixedWidth(180)
        self.sidebar.addItems(list(_SEITEN))
        lay.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        self.status_page = StatusPage(cfg, camera_status)
        self.stack.addWidget(self.status_page)
        self.reports_page = ReportsPage(cfg)
        self.stack.addWidget(self.reports_page)
        for name in _SEITEN[2:]:
            self.stack.addWidget(_platzhalter(
                f"„{name}“ kommt mit einer späteren Stufe "
                "(Spec Abschnitt 6)."))
        lay.addWidget(self.stack, stretch=1)
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.sidebar.setCurrentRow(0)
        self.setCentralWidget(central)
