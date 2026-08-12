"""Hilfe-Fenster (Ebene 2) und der »Was tun?«-Link (Ebene 1).

NICHT-MODAL, ein eigenes Fenster: der Bediener muss die Anleitung
ausführen können, während er sie liest. Theme, UI-Skalierung und
Touch-Modus greifen wie im Rest der App von selbst (app-weites QSS,
QT_SCALE_FACTOR, QScroller-Polish-Filter aus touch.py — der
QTextBrowser ist eine QAbstractScrollArea).

Modalität: Fast alle Fehlerdialoge der App sind applikationsmodal
(DialogShell). Ein für sich stehendes Hilfe-Fenster wäre hinter ihnen
NICHT bedienbar. Deshalb wird der Sprung aus einem modalen Dialog als
KIND-Fenster dieses Dialogs geöffnet (Kinder modaler Dialoge bleiben
bedienbar; das Hilfe-Fenster schließt dann mit dem Dialog). Außerhalb
modaler Kontexte gilt das Singleton-Muster des Admin-Fensters: EIN
Fenster, erneutes Öffnen fokussiert es.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton,
                               QTextBrowser, QVBoxLayout, QWidget)

from . import anker as anker_mod
from . import texte

_NAV_BREITE = 250
_LINK_SCHEMA = "hilfe"        # interne Querverweise: [Text](hilfe:thema#slug)


class HilfeFenster(QWidget):
    """Themenliste links, QTextBrowser rechts. `zeige_zustand()` ist der
    kontextsensitive Einstieg über die zentrale Anker-Tabelle."""

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowFlag(Qt.Window, True)
        self.setWindowTitle("Doco Detect – Hilfe")
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setMinimumSize(720, 520)
        self.resize(980, 680)
        self.cfg = cfg
        self._thema: str | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.nav = QListWidget(self)
        self.nav.setObjectName("adminSidebar")   # gleiche Optik wie Admin
        self.nav.setFixedWidth(_NAV_BREITE)
        # Feste Breite + Touch-Polster ergäben sonst einen horizontalen
        # Scrollbalken; lange Titel werden schlicht abgeschnitten.
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._baue_navigation()
        self.nav.currentItemChanged.connect(self._nav_gewaehlt)
        lay.addWidget(self.nav)

        self.browser = QTextBrowser(self)
        self.browser.setObjectName("hilfeBrowser")
        self.browser.setOpenLinks(False)          # nur hilfe:-Querverweise
        self.browser.setOpenExternalLinks(False)
        self.browser.anchorClicked.connect(self._link_geklickt)
        lay.addWidget(self.browser, stretch=1)

        erstes = self._erstes_thema_item()
        if erstes is not None:
            self.nav.setCurrentItem(erstes)

    # ---------- Aufbau ----------

    def _baue_navigation(self) -> None:
        """Gruppentitel als nicht wählbare Zeilen, Themen darunter. Titel
        kommen aus der H1 der Markdown-Datei — eine Quelle."""
        for gruppe, themen in anker_mod.THEMEN:
            kopf = QListWidgetItem(gruppe.upper())
            kopf.setFlags(Qt.NoItemFlags)         # reiner Trenner
            self.nav.addItem(kopf)
            for thema in themen:
                text = texte.titel(texte.lade_thema(thema)) or thema
                eintrag = QListWidgetItem("   " + text)
                eintrag.setData(Qt.UserRole, thema)
                self.nav.addItem(eintrag)

    def _erstes_thema_item(self) -> QListWidgetItem | None:
        for i in range(self.nav.count()):
            if self.nav.item(i).data(Qt.UserRole):
                return self.nav.item(i)
        return None

    # ---------- Navigation ----------

    def _nav_gewaehlt(self, aktuell, _vorher) -> None:
        thema = aktuell.data(Qt.UserRole) if aktuell is not None else None
        if thema and thema != self._thema:
            self._lade(thema)

    def _link_geklickt(self, url) -> None:
        if url.scheme() != _LINK_SCHEMA:
            return                        # keine externen Ziele im Hilfetext
        self.zeige_thema(url.path(), url.fragment() or None)

    def zeige_thema(self, thema: str, abschnitt: str | None = None) -> None:
        for i in range(self.nav.count()):
            if self.nav.item(i).data(Qt.UserRole) == thema:
                self.nav.setCurrentItem(self.nav.item(i))
                break
        if thema != self._thema:
            self._lade(thema)
        if abschnitt:
            self._springe_zu(abschnitt)

    def zeige_zustand(self, zustand: str) -> None:
        """Kontextsensitiver Einstieg (Ebene 1) über die zentrale Tabelle."""
        thema, abschnitt = anker_mod.anker_fuer(zustand)
        self.zeige_thema(thema, abschnitt)

    # ---------- Rendern ----------

    def _lade(self, thema: str) -> None:
        from .. import settings as settings_mod

        roh = texte.lade_thema(thema)
        text, _unbekannt = texte.loese_platzhalter(
            roh, self.cfg, settings_mod.effective_ui(self.cfg))
        self.browser.setMarkdown(text)
        self._thema = thema
        self.browser.verticalScrollBar().setValue(0)

    def _springe_zu(self, abschnitt: str) -> None:
        """Zum H2 mit diesem Slug scrollen. Qt übernimmt aus Markdown keine
        HTML-Anker — deshalb Suche über die Heading-Blöcke des Dokuments."""
        doc = self.browser.document()
        block = doc.begin()
        while block.isValid():
            if (block.blockFormat().headingLevel() == 2
                    and texte.slug(block.text()) == abschnitt):
                cursor = QTextCursor(block)
                self.browser.setTextCursor(cursor)
                self.browser.ensureCursorVisible()
                # Überschrift an den oberen Rand, nicht an den unteren.
                rect = self.browser.cursorRect(cursor)
                leiste = self.browser.verticalScrollBar()
                leiste.setValue(leiste.value() + rect.top())
                return
            block = block.next()

    def aktuelles_thema(self) -> str | None:
        return self._thema


# ---------- Öffnen (Singleton + Modal-Kindschaft) ----------

_fenster: HilfeFenster | None = None       # nicht-modales Singleton


def _singleton_weg(*_args) -> None:
    global _fenster
    _fenster = None


def oeffne_hilfe(cfg: dict, zustand: str | None = None,
                 parent=None) -> HilfeFenster:
    """Hilfe öffnen/fokussieren; mit `zustand` am passenden Anker.

    Läuft gerade ein applikationsmodaler Dialog, entsteht das Fenster als
    dessen Kind (sonst wäre es nicht bedienbar) und stirbt mit ihm."""
    app = QApplication.instance()
    modal = app.activeModalWidget() if app is not None else None
    if modal is not None:
        fenster = modal.findChild(HilfeFenster)
        if fenster is None:
            fenster = HilfeFenster(cfg, parent=modal)
    else:
        global _fenster
        if _fenster is None:
            _fenster = HilfeFenster(cfg, parent=parent)
            _fenster.destroyed.connect(_singleton_weg)
        fenster = _fenster
    fenster.show()
    fenster.raise_()
    fenster.activateWindow()
    if zustand is not None:
        fenster.zeige_zustand(zustand)
    return fenster


class HilfeLink(QPushButton):
    """»Was tun?«-Link neben einer Fehlermeldung (Ebene 1).

    Wird mit einer Zustands-Konstante aus anker.py erzeugt bzw. per
    `set_zustand()` umgeschaltet; ein unbekannter Zustand fällt sofort
    (KeyError beim Nachschlagen), nicht erst beim Klick im Fehlermoment.
    `set_zustand(None)` blendet den Link aus."""

    def __init__(self, cfg: dict, zustand: str | None = None,
                 text: str = "Was tun?", parent=None):
        super().__init__(text, parent)
        self.setObjectName("linkButton")
        self.setCursor(Qt.PointingHandCursor)
        self._cfg = cfg
        self._zustand: str | None = None
        self.clicked.connect(self._oeffnen)
        self.set_zustand(zustand)

    def set_zustand(self, zustand: str | None) -> None:
        if zustand is not None:
            anker_mod.anker_fuer(zustand)     # validiert: laut statt tot
        self._zustand = zustand
        self.setVisible(zustand is not None)

    def zustand(self) -> str | None:
        return self._zustand

    def _oeffnen(self) -> None:
        if self._zustand is not None:
            oeffne_hilfe(self._cfg, self._zustand, parent=self.window())
