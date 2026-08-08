"""Qt-Schicht der crash-sicheren Einlern-Session – Schritt 7.

Design: docs/superpowers/specs/2026-08-05-crashsichere-einlern-session-design.md
Abschnitt 5.

Schwerpunkte, weil sie sonst nur im Code stehen wuerden:
  * der Dialog fuer unterbrochene Sessions (Auswahl, mehrere je Artikel,
    abgeblendetes „Fortsetzen“ bei geaenderter Optik)
  * die Artikel-Combo ist gesperrt, sobald die erste Journalzeile steht
  * Abbrechen fragt zurueck, VORBELEGT mit Verwerfen
  * der Schliessschutz ist eine SCHWELLE, kein Schloss: nach 30 s gibt es
    „Trotzdem schliessen“, und erzwungenes Schliessen kostet keine Aufnahme

Run (EINZELN, nicht am Stueck – siehe docs/ui-qt-testsuite-segfault.md):
    QT_QPA_PLATFORM=offscreen pytest tests/test_ui_enroll_session.py
"""

import os
import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox  # noqa: E402

from docodetect.calibration import Calibration  # noqa: E402
from docodetect.pipeline import (append_shot, begin_enroll_session,  # noqa: E402
                                 list_enroll_sessions, stage_frame)
from docodetect.ui_qt.app import make_app  # noqa: E402
from docodetect.ui_qt.widgets import enroll_dialog as ed  # noqa: E402
from docodetect.ui_qt.widgets.open_sessions_dialog import (  # noqa: E402
    OpenSessionsDialog)
from test_enroll_session import (ARTIKEL, _artikel_anlegen, _feats,  # noqa: E402
                                 _frame, _optik_anlegen, make_cfg)


@pytest.fixture
def qapp():
    return make_app()


@pytest.fixture
def cfg(tmp_path):
    c = make_cfg(tmp_path)
    c["matching"]["diameter_tolerance_mm"] = 6.0     # der Dialog zeigt sie an
    _optik_anlegen(c)
    _artikel_anlegen(c)
    return c


class _Quelle:
    """Frame-Quelle wie CameraWorker/DemoSource, ohne Kamera und ohne Thread.
    `liefern` steuert, ob auf request_full_frame ueberhaupt ein Bild kommt –
    genau der Fall, den der 6-s-Timer abfangen muss."""

    def __init__(self, liefern=True):
        self.liefern = liefern
        self.angefordert = 0
        self._slots = []

    class _Sig:
        def __init__(self, quelle):
            self.quelle = quelle

        def connect(self, slot):
            self.quelle._slots.append(slot)

    @property
    def full_frame_ready(self):
        return _Quelle._Sig(self)

    def request_full_frame(self):
        self.angefordert += 1
        if self.liefern:
            for slot in self._slots:
                slot(_frame(120))


def _ui(cfg):
    return {"enroll_shots": 3, "preview_max_width": 320, "preview_fps": 15}


def _warte(qapp, bedingung, timeout=20.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        qapp.processEvents()
        if bedingung():
            return True
        time.sleep(0.01)
    return False


def _fake_messung(monkeypatch, d_mm=270.0):
    """measure_shot ersetzen. Die Testframes sind flach (64x96) und damit
    NICHT segmentierbar – ohne Ersatz wirft jede Aufnahme SegmentationError,
    und es entstuende nie eine Journalzeile. Geprueft wird hier der
    Dialogfluss, nicht die Messung; die ist derselbe Aufruf wie bisher und
    anderswo abgedeckt."""
    from docodetect import pipeline as pl

    class _Seg:
        # Kontur fuer das Thumbnail-Overlay (cv2.polylines braucht (N,1,2)).
        contour = np.array([[[5, 5]], [[40, 5]], [[40, 30]], [[5, 30]]],
                           dtype=np.int32)

    monkeypatch.setattr(pl, "measure_shot",
                        lambda bild, c: (_feats(d_mm), _Seg()))


def _sitzung_auf_platte(cfg, n=2, start=270.0):
    s = begin_enroll_session(cfg, ARTIKEL, target_shots=n)
    for k in range(n):
        s = append_shot(cfg, s, stage_frame(cfg, s, _frame(100 + k)),
                        _feats(start + k))
    return s


# ---------- Dialog fuer offene Sessions ----------

def test_offene_sessions_neueste_vorausgewaehlt(qapp, cfg):
    _sitzung_auf_platte(cfg, 1)
    b = _sitzung_auf_platte(cfg, 2)
    dlg = OpenSessionsDialog(list_enroll_sessions(cfg))
    try:
        assert dlg.liste.count() == 2
        assert dlg.aktuelle().ts == b.info.ts, "neueste ist vorausgewaehlt"
        assert dlg.fortsetzen_button.isEnabled()
    finally:
        dlg.deleteLater()


def test_geaenderte_optik_blendet_fortsetzen_ab(qapp, cfg):
    """Der Grund steht in der ZEILE, nicht erst in einer Fehlermeldung nach
    dem Klick."""
    _sitzung_auf_platte(cfg, 2)
    Calibration(mm_per_px=0.25, camera_height_mm=300.0, image_width=1920,
                image_height=1080, marker_size_mm=50.0,
                created_unix=1.0).save(cfg["calibration"]["file"])
    dlg = OpenSessionsDialog(list_enroll_sessions(cfg))
    try:
        assert dlg.aktuelle().fingerprint_ok is False
        assert not dlg.fortsetzen_button.isEnabled(), "Fortsetzen abgeblendet"
        assert dlg.verwerfen_button.isEnabled(), "Verwerfen bleibt moeglich"
        assert "Kalibrierung" in dlg.grund_label.text()
        assert "optik" in dlg.grund_label.text()
        assert "Kalibrierung geändert" in dlg.liste.item(0).text()
    finally:
        dlg.deleteLater()


def test_spaeter_tut_nichts(qapp, cfg):
    """„Später“ ist ausdruecklich KEIN Verwerfen – die Session bleibt offen."""
    s = _sitzung_auf_platte(cfg, 2)
    dlg = OpenSessionsDialog(list_enroll_sessions(cfg))
    try:
        dlg._spaeter()
        assert dlg.entscheidung == OpenSessionsDialog.SPAETER
        assert dlg.gewaehlt is None
        assert s.info.path.is_dir(), "Session unberuehrt"
    finally:
        dlg.deleteLater()


def test_mehrere_sessions_je_artikel_stehen_getrennt(qapp, cfg):
    a = _sitzung_auf_platte(cfg, 1)
    b = _sitzung_auf_platte(cfg, 3)
    dlg = OpenSessionsDialog(list_enroll_sessions(cfg))
    try:
        texte = [dlg.liste.item(i).text() for i in range(dlg.liste.count())]
        assert len(texte) == 2
        assert all(ARTIKEL in t for t in texte)
        assert any("1 von 1" in t for t in texte)
        assert any("3 von 3" in t for t in texte)
        dlg.liste.setCurrentRow(1)
        assert dlg.aktuelle().ts in (a.info.ts, b.info.ts)
    finally:
        dlg.deleteLater()


# ---------- Einlerndialog: Session statt _shots ----------

def test_session_entsteht_erst_beim_ersten_aufnehmen(qapp, cfg, monkeypatch):
    """Ein geoeffneter und wieder geschlossener Dialog darf keinen leeren
    Session-Ordner hinterlassen."""
    _fake_messung(monkeypatch)
    dlg = ed.EnrollDialog(cfg, _ui(cfg), _Quelle(), None)
    try:
        assert list_enroll_sessions(cfg) == [], "nichts angelegt"
        assert dlg._session is None
        assert dlg.article_box.isEnabled()
        dlg._capture()
        assert _warte(qapp, lambda: dlg._session is not None
                      and dlg._session.info.n_shots == 1)
        assert len(list_enroll_sessions(cfg)) == 1
    finally:
        dlg.deleteLater()


def test_artikelwahl_wird_mit_der_ersten_aufnahme_gesperrt(qapp, cfg, monkeypatch):
    _fake_messung(monkeypatch)
    dlg = ed.EnrollDialog(cfg, _ui(cfg), _Quelle(), None)
    try:
        assert dlg.article_box.isEnabled()
        dlg._capture()
        assert _warte(qapp, lambda: dlg._session is not None)
        assert not dlg.article_box.isEnabled(), "Combo gesperrt"
        assert not dlg.shots_spin.isEnabled()
        assert "zum Wechseln Dialog schließen" in dlg.ref_label.text(), \
            "der Weg wird genannt, damit niemand nach einem Knopf sucht"
    finally:
        dlg.deleteLater()


def test_aufnahme_landet_sofort_auf_der_platte(qapp, cfg, monkeypatch):
    """Der Kern des Umbaus: nach dem Klick liegt die Aufnahme im Journal, nicht
    nur im RAM."""
    _fake_messung(monkeypatch)
    dlg = ed.EnrollDialog(cfg, _ui(cfg), _Quelle(), None)
    try:
        dlg._capture()
        assert _warte(qapp, lambda: dlg._session is not None
                      and dlg._session.info.n_shots == 1)
        from docodetect.pipeline import load_enroll_session
        auf_platte = load_enroll_session(cfg, dlg._session.info.path)
        assert auf_platte.info.n_shots == 1
        assert auf_platte.shots[0].raw_path.is_file()
    finally:
        dlg.deleteLater()


# ---------- 6-s-Timer: kein stummes Warten ----------

def test_ausbleibender_frame_entsperrt_und_meldet_zustand(qapp, cfg, monkeypatch):
    """Ohne den Timer bliebe der Dialog dauerhaft „busy“: beide Knoepfe aus,
    keine Meldung – die Bedienlage, aus der heraus jemand die App abschiesst."""
    monkeypatch.setattr(ed, "_FRAME_TIMEOUT_MS", 60)
    quelle = _Quelle(liefern=False)
    dlg = ed.EnrollDialog(cfg, _ui(cfg), quelle, None)
    try:
        dlg._capture()
        assert quelle.angefordert == 1
        assert dlg._awaiting_frame is True
        assert _warte(qapp, lambda: dlg._awaiting_frame is False, timeout=5.0), \
            "der Timer beendet das Warten"
        assert "erneut versuchen" in dlg.hint_label.text().lower()
        assert dlg.capture_button.isEnabled(), "Knopf wieder frei"
    finally:
        dlg.deleteLater()


def test_timer_grenze_ist_ein_vielfaches_der_reconnect_konstante():
    """Als Vielfaches, nicht als Literal: verschiebt sich _RECONNECT_SECS,
    verschiebt sich die Grenze mit."""
    from docodetect.ui_qt.camera_worker import _RECONNECT_SECS
    assert ed._FRAME_TIMEOUT_MS == int(2 * _RECONNECT_SECS * 1000)


# ---------- Abbrechen: Rueckfrage, vorbelegt mit Verwerfen ----------

def _antwort(monkeypatch, rolle: str):
    """QMessageBox.exec abfangen und eine Schaltflaeche waehlen."""
    gemerkt = {}

    def fake_exec(self):
        gemerkt["default"] = self.defaultButton()
        for b in self.buttons():
            if self.buttonRole(b) == rolle:
                gemerkt["gewaehlt"] = b
                self.setClickedButtonForTest = b
                return 0
        return 0

    def fake_clicked(self):
        return gemerkt.get("gewaehlt")

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", fake_clicked)
    return gemerkt


def test_abbrechen_ist_mit_verwerfen_vorbelegt(qapp, cfg, monkeypatch):
    gemerkt = _antwort(monkeypatch, QMessageBox.DestructiveRole)
    _fake_messung(monkeypatch)
    dlg = ed.EnrollDialog(cfg, _ui(cfg), _Quelle(), None)
    try:
        dlg._capture()
        assert _warte(qapp, lambda: dlg._session is not None)
        pfad = dlg._session.info.path

        assert dlg._abbrechen_beantwortet() is True
        assert gemerkt["default"].text() == "Verwerfen", "Vorbelegung"
        assert not pfad.exists(), "Session nach verworfen/ geschoben"
        verworfen = Path(cfg["paths"]["reference_dir"]).parent / "verworfen"
        assert any(verworfen.rglob("raw_*.png")), "Aufnahmen sind erhalten"
    finally:
        dlg.deleteLater()


def test_fuer_spaeter_behalten_laesst_die_session_offen(qapp, cfg, monkeypatch):
    _antwort(monkeypatch, QMessageBox.AcceptRole)
    _fake_messung(monkeypatch)
    dlg = ed.EnrollDialog(cfg, _ui(cfg), _Quelle(), None)
    try:
        dlg._capture()
        assert _warte(qapp, lambda: dlg._session is not None)
        assert dlg._abbrechen_beantwortet() is True
        assert len(list_enroll_sessions(cfg)) == 1, "Session bleibt offen"
    finally:
        dlg.deleteLater()


def test_weiter_aufnehmen_haelt_den_dialog_offen(qapp, cfg, monkeypatch):
    _antwort(monkeypatch, QMessageBox.RejectRole)
    _fake_messung(monkeypatch)
    dlg = ed.EnrollDialog(cfg, _ui(cfg), _Quelle(), None)
    try:
        dlg._capture()
        assert _warte(qapp, lambda: dlg._session is not None)
        assert dlg._abbrechen_beantwortet() is False, "Schliessen abgebrochen"
        assert len(list_enroll_sessions(cfg)) == 1
    finally:
        dlg.deleteLater()


def test_ohne_aufnahme_schliesst_der_dialog_wortlos(qapp, cfg, monkeypatch):
    gerufen = {"n": 0}
    monkeypatch.setattr(QMessageBox, "exec",
                        lambda self: gerufen.__setitem__("n", gerufen["n"] + 1))
    dlg = ed.EnrollDialog(cfg, _ui(cfg), _Quelle(), None)
    try:
        dlg.close()
        assert gerufen["n"] == 0, "keine Rueckfrage ohne Aufnahmen"
    finally:
        dlg.deleteLater()


# ---------- Schliessschutz: Schwelle, kein Schloss ----------

class _Laeuft:
    """Worker-Attrappe: „laeuft noch“, ohne einen Thread zu starten."""

    def __init__(self):
        self.gestoppt = False


def test_schliessschutz_blockt_waehrend_ein_worker_laeuft(qapp, cfg):
    dlg = ed.EnrollDialog(cfg, _ui(cfg), _Quelle(), None)
    try:
        dlg._worker = _Laeuft()
        dlg._worker_start = time.monotonic()          # gerade erst gestartet
        assert dlg._darf_trotzdem_schliessen() is False
        assert "Aufnahmen sind bereits gesichert" in dlg.hint_label.text()
        assert "möglich" in dlg.hint_label.text(), "die Restzeit wird genannt"
    finally:
        dlg._worker = None
        dlg.deleteLater()


def test_nach_30_s_gibt_es_trotzdem_schliessen(qapp, cfg, monkeypatch):
    """DER Sackgassen-Test: liefe ein Worker nie zurueck, waere ein Dialog, der
    sich nicht schliessen laesst, schlimmer als der heutige Zustand."""
    gefragt = {"n": 0}

    def fake_question(parent, titel, text, *a, **kw):
        gefragt["n"] += 1
        gefragt["text"] = text
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))
    dlg = ed.EnrollDialog(cfg, _ui(cfg), _Quelle(), None)
    try:
        dlg._worker = _Laeuft()
        dlg._worker_start = time.monotonic() - (ed._SCHLIESSSCHUTZ_MS / 1000) - 1
        assert dlg._darf_trotzdem_schliessen() is True, "der Ausweg greift"
        assert gefragt["n"] == 1
        assert "Session bleibt offen" in gefragt["text"], \
            "der Text sagt, dass nichts verloren geht"
        assert "laufende Vorgang" in gefragt["text"]
    finally:
        dlg._worker = None
        dlg.deleteLater()


def test_erzwungenes_schliessen_kostet_keine_aufnahme(qapp, cfg, monkeypatch):
    """Warum der Schutz eine Schwelle sein DARF: das Journal macht das
    Erzwingen ungefaehrlich."""
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **kw: QMessageBox.Yes))
    _fake_messung(monkeypatch)
    dlg = ed.EnrollDialog(cfg, _ui(cfg), _Quelle(), None)
    try:
        dlg._capture()
        assert _warte(qapp, lambda: dlg._session is not None
                      and dlg._session.info.n_shots == 1)
        dlg._worker = _Laeuft()
        dlg._worker_start = time.monotonic() - 999
        assert dlg._darf_trotzdem_schliessen() is True

        offen = list_enroll_sessions(cfg)
        assert len(offen) == 1 and offen[0].n_shots == 1, \
            "die Aufnahme liegt im Journal und die Session ist fortsetzbar"
    finally:
        dlg._worker = None
        dlg.deleteLater()


def test_warten_auf_einen_frame_ist_kein_laufender_worker(qapp, cfg):
    """Der Fall aus Befund 6 blockiert das Schliessen ausdruecklich NICHT:
    waehrend des Wartens laeuft kein Worker."""
    dlg = ed.EnrollDialog(cfg, _ui(cfg), _Quelle(liefern=False), None)
    try:
        dlg._capture()
        assert dlg._awaiting_frame is True
        assert dlg._worker is None, "ein Worker startet erst mit dem Frame"
    finally:
        dlg.deleteLater()


# ---------- Fortsetzen ----------

def test_fortsetzen_stellt_die_session_wieder_her(qapp, cfg, monkeypatch):
    """Die Testframes sind flach und nicht segmentierbar – measure_shot wird
    ersetzt. Geprueft wird der Dialogfluss, nicht die Messung."""
    s = _sitzung_auf_platte(cfg, 2, start=270.0)
    from docodetect import pipeline as pl
    monkeypatch.setattr(pl, "measure_shot",
                        lambda bild, c: (_feats(270.0), None))

    info = list_enroll_sessions(cfg)[0]
    dlg = ed.EnrollDialog(cfg, _ui(cfg), _Quelle(), None, fortsetzen=info)
    try:
        assert _warte(qapp, lambda: dlg._worker is None and dlg._session is not None)
        assert dlg._session.info.n_shots == 2
        assert not dlg.article_box.isEnabled(), "auf den Artikel festgelegt"
        assert dlg.thumbs.count() == 2
        journal = (s.info.path / "journal.jsonl").read_bytes()
        assert journal, "Journal existiert"
        assert dlg._session.info.path == s.info.path
    finally:
        dlg.deleteLater()


def test_fortsetzen_meldet_abweichung_mit_beiden_auswegen(qapp, cfg, monkeypatch):
    s = _sitzung_auf_platte(cfg, 2, start=270.0)
    vorher = (s.info.path / "journal.jsonl").read_bytes()
    from docodetect import pipeline as pl
    monkeypatch.setattr(pl, "measure_shot",
                        lambda bild, c: (_feats(299.0), None))

    info = list_enroll_sessions(cfg)[0]
    dlg = ed.EnrollDialog(cfg, _ui(cfg), _Quelle(), None, fortsetzen=info)
    try:
        assert _warte(qapp, lambda: dlg._worker is None
                      and "weichen" in dlg.hint_label.text())
        text = dlg.hint_label.text()
        assert "GESPEICHERTEN Werte aus dem Journal" in text, \
            "der Text sagt, WELCHE Werte gebucht werden"
        assert "verwerfen und neu einlernen" in text, "zweiter Ausweg"
        assert (s.info.path / "journal.jsonl").read_bytes() == vorher, \
            "remeasure hat das Journal nicht angefasst"
    finally:
        dlg.deleteLater()
