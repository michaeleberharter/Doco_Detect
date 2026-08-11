"""Admin-Fenster: Sidebar links, Seiten-Stack rechts (Spec Abschnitt 4).

Nicht-modal, EIN Fenster zur Zeit (das Hauptfenster fokussiert eine
bestehende Instanz). Teilt mit dem Hauptfenster keinen Zustand — die
Meldungen Hauptfenster → Admin sind ausschließlich einseitige Pull-/
Anforderungs-Callables (Spec §4): Kamera-Zustand (+ Warntext),
Voll-Frame auf Anforderung (Stufe 4, Segmentierungs-Test) und die
Fortsetzen-Delegation an den bestehenden Einlern-Dialog (Punkt 13).
Alle sind optional — ohne sie zeigen die Seiten Hinweistexte."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QListWidget, QMainWindow,
                               QStackedWidget, QTabWidget, QWidget)

from .pages.analysis_page import AnalysisPage
from .pages.articles_page import ArticlesPage
from .pages.camera_page import CameraPage
from .pages.config_page import ConfigPage
from .pages.reports_page import ReportsPage
from .pages.segtest_page import SegTestPage
from .pages.sessions_page import SessionsPage
from .pages.status_page import StatusPage

_SEITEN = ("Status", "Reports", "Analyse", "Artikel", "Diagnose")


class AdminWindow(QMainWindow):
    def __init__(self, cfg: dict, camera_status: Callable[[], str],
                 parent=None,
                 frame_anfordern: Optional[Callable] = None,
                 kamera_warnung: Optional[Callable] = None,
                 fortsetzen_pruefen: Optional[Callable] = None,
                 fortsetzen: Optional[Callable] = None):
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
        self.analysis_page = AnalysisPage(cfg)
        self.stack.addWidget(self.analysis_page)
        # Artikel-Sektion: Liste (Teil A + B1) | Einlern-Sessions (Stufe 4)
        # als Tabs — Sidebar bleibt bei fünf Einträgen (Spec §4,
        # Tab-Präzedenz: Reports-Sektion 1b, Analyse-Sektion Stufe 2).
        self.artikel_tabs = QTabWidget()
        self.articles_page = ArticlesPage(cfg)
        self.artikel_tabs.addTab(self.articles_page, "Artikelliste")
        self.sessions_page = SessionsPage(
            cfg, fortsetzen_pruefen=fortsetzen_pruefen,
            fortsetzen=fortsetzen)
        self.artikel_tabs.addTab(self.sessions_page, "Einlern-Sessions")
        self.stack.addWidget(self.artikel_tabs)
        # Diagnose-Sektion (Stufe 4): SegTest | Config | Kamera.
        self.diagnose_tabs = QTabWidget()
        self.segtest_page = SegTestPage(cfg,
                                        frame_anfordern=frame_anfordern)
        self.diagnose_tabs.addTab(self.segtest_page,
                                  "Segmentierungs-Test")
        self.config_page = ConfigPage(cfg)
        self.diagnose_tabs.addTab(self.config_page, "Config")
        self.camera_page = CameraPage(cfg, camera_status,
                                      kamera_warnung=kamera_warnung)
        self.diagnose_tabs.addTab(self.camera_page, "Kamera")
        self.stack.addWidget(self.diagnose_tabs)
        lay.addWidget(self.stack, stretch=1)
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.sidebar.setCurrentRow(0)
        self.setCentralWidget(central)
