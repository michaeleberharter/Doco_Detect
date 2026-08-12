"""DIE zentrale Zuordnung Fehlerzustand -> Hilfe-Anker (Ebene 1).

Qt-frei. Drei Bestände, ein Vertrag:

- ZUSTAENDE: jeder in der Sichtung vom 2026-08-12 erfasste Zustand, in
  dem der Bediener nicht weiterkommt, als Konstante mit Belegstelle.
- ANKER: Zustand -> (thema, abschnitts_slug | None). Call-Sites
  verwenden NUR die Konstanten dieses Moduls, keine String-Literale.
- KEIN_ANKER: Zustand -> Begründung, warum bewusst kein Hilfe-Link
  gesetzt wird. Eine Ausnahme ohne Begründung gibt es nicht.

Der Pflichttest (tests/test_hilfe_inhalte.py) erzwingt:
ANKER und KEIN_ANKER sind disjunkt, decken ZUSAMMEN exakt ZUSTAENDE ab,
und jedes ANKER-Ziel existiert in den Markdown-Quellen (Datei + H2-Slug).
Ein toter Hilfe-Link im Fehlermoment ist schlimmer als kein Link.
"""

from __future__ import annotations

# ---------- Themenregister (Ebene 2) ----------
# Reihenfolge = Navigationsreihenfolge im Hilfe-Fenster. Die Titel kommen
# aus der H1 der jeweiligen Markdown-Datei (eine Quelle, kein Duplikat).
# Der Admin-Block liegt bewusst als eigener, sichtbar abgesetzter Bereich
# am Ende: offen lesbar — geschützt werden AKTIONEN, nicht Wissen.

THEMEN: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Erkennung", ("nicht-gefunden", "fragt-nach", "verwechselt",
                   "bildrand", "neuer-artikel")),
    ("Bild & Kamera", ("keine-kamera", "vorschau-dunkel", "unscharf",
                       "vorschau-steht")),
    ("Messung", ("masse-daneben",)),
    ("Einlernen", ("einlernen-haengt",)),
    ("Nach Störung", ("session-offen",)),
    ("Bedienung", ("schrift-fenster", "kein-ton", "bewertung")),
    ("Admin & Technik", ("admin-passwort", "admin-diagnose",
                         "admin-analyse", "einrichtung", "sandbox",
                         "app-startet-nicht")),
)

ALLE_THEMEN: tuple[str, ...] = tuple(
    thema for _gruppe, themen in THEMEN for thema in themen)


# ---------- Erfasste Zustände (Sichtung 2026-08-12, feature/ui-hilfe) ----------
# Konstantenname = Zustand; Kommentar = Belegstelle der Sichtung.

# Hauptfenster
KEINE_KAMERA = "keine-kamera"                        # main_window.py:427-439
KAMERA_KONFIG = "kamera-konfig"                      # camera_worker.py:100-107
AKTION_ABGEBROCHEN = "aktion-abgebrochen"            # main_window.py:365-372
EINRICHTUNG_NOETIG = "einrichtung-noetig"            # main_window.py:434-437, 548-556
BUSY = "busy"                                        # main_window.py:64-68, 599
VORSCHAU_PAUSIERT = "vorschau-pausiert"              # main_window.py:513
ERGEBNIS_BORDER = "ergebnis-border"                  # main_window.py:986-997
ERGEBNIS_REJECT = "ergebnis-reject"                  # main_window.py:999-1026
ERGEBNIS_AMBIGUOUS = "ergebnis-ambiguous"            # main_window.py:970-984
ERGEBNIS_ACCEPT = "ergebnis-accept"                  # main_window.py:954-968
SIEGER_OHNE_REFERENZEN = "sieger-ohne-referenzen"    # result_card.py:115-120
AKTION_FEHLGESCHLAGEN = "aktion-fehlgeschlagen"      # main_window.py:855-861
BEWERTUNG_NICHT_GESPEICHERT = "bewertung-nicht-gespeichert"  # main_window.py:1082/1112/1142
SANDBOX_GESPERRT = "sandbox-gesperrt"                # main_window.py:592-594, 655-657
FOKUS_WARNUNG = "fokus-warnung"                      # camera_worker.py:35-36 -> status_bar.py:45-48
SKALIERUNG_HINWEIS = "skalierung-hinweis"            # app.py:243-270
SESSION_VERWERFEN_FEHLER = "session-verwerfen-fehler"  # main_window.py:727-728
SESSION_VERWORFEN_OK = "session-verworfen-ok"        # main_window.py:725-726
LEERZUSTAND_START = "leerzustand-start"              # main_window.py:256

# Dialoge
EINLERNEN_KEIN_BILD = "einlernen-kein-bild"          # enroll_dialog.py:396-412
EINLERNEN_AUFNAHME_VERWORFEN = "einlernen-aufnahme-verworfen"  # enroll_dialog.py:450-455
EINLERNEN_SESSION_FEHLER = "einlernen-session-fehler"  # enroll_dialog.py:376-377
EINLERNEN_SCHLIESSEN = "einlernen-schliessen"        # enroll_dialog.py:546-590
EINLERNEN_BLATT = "einlernen-blatt"                  # enroll_dialog.py:503-510
SESSION_ABWEICHUNG = "session-abweichung"            # enroll_dialog.py:281-296
SESSIONS_OFFEN = "sessions-offen"                    # open_sessions_dialog.py:59-99
SESSION_NICHT_FORTSETZBAR = "session-nicht-fortsetzbar"  # open_sessions_dialog.py:122-131
KALIBRIEREN_DIALOG = "kalibrieren-dialog"            # calibrate_dialog.py:59, 146-158, 187-191
KALIBRIEREN_OHNE_HINTERGRUND = "kalibrieren-ohne-hintergrund"  # calibrate_dialog.py:133-142
SETTINGS_SCALE_ZU_GROSS = "settings-scale-zu-gross"  # settings_dialog.py:246-255
SETTINGS_NEUSTART_HINWEIS = "settings-neustart-hinweis"  # settings_dialog.py:318-330
KORREKTUR_DIALOG = "korrektur-dialog"                # correction_dialog.py:19-56

# Admin-Fenster
ADMIN_PASSWORT = "admin-passwort-zustand"            # auth_dialog.py:56-67
ADMIN_STATUS_UNVOLLSTAENDIG = "admin-status-unvollstaendig"  # status_page.py:84-99
ADMIN_KAMERA = "admin-kamera"                        # camera_page.py:34-39, 117-131, 168-170
ADMIN_SEGTEST = "admin-segtest"                      # segtest_page.py:30-33, 101-111, 162-164
ADMIN_SESSIONS = "admin-sessions"                    # sessions_page.py:99-144, 199-201
ADMIN_ANALYSE = "admin-analyse-zustand"              # analysis_page.py:150-211, 255
ADMIN_ARTIKEL_LEER = "admin-artikel-leer"            # articles_page.py:120-122
ADMIN_ARTIKEL_QUALITAET = "admin-artikel-qualitaet"  # articles_page.py:144-156
ADMIN_CONFIG_DEFEKT = "admin-config-defekt"          # config_page.py:54-57
REPORTS_INFO = "reports-info"                        # reports_page.py:182-185, report_detail.py:157-159/187

# App-Start (Konsole, vor Qt)
START_ARGUMENTE = "start-argumente"                  # __main__.py:25-29, 40-45


# ---------- Zuordnung Zustand -> (thema, abschnitts_slug | None) ----------

ANKER: dict[str, tuple[str, str | None]] = {
    KEINE_KAMERA: ("keine-kamera", None),
    KAMERA_KONFIG: ("keine-kamera", "konfiguration"),
    AKTION_ABGEBROCHEN: ("keine-kamera", None),
    EINRICHTUNG_NOETIG: ("einrichtung", None),
    ERGEBNIS_BORDER: ("bildrand", None),
    ERGEBNIS_REJECT: ("nicht-gefunden", None),
    ERGEBNIS_AMBIGUOUS: ("fragt-nach", None),
    AKTION_FEHLGESCHLAGEN: ("nicht-gefunden", "nichts-erkannt"),
    BEWERTUNG_NICHT_GESPEICHERT: ("bewertung", "nicht-gespeichert"),
    SANDBOX_GESPERRT: ("sandbox", None),
    FOKUS_WARNUNG: ("unscharf", None),
    SKALIERUNG_HINWEIS: ("schrift-fenster", None),
    SESSION_VERWERFEN_FEHLER: ("session-offen", None),
    EINLERNEN_KEIN_BILD: ("einlernen-haengt", "kein-bild"),
    EINLERNEN_AUFNAHME_VERWORFEN: ("einlernen-haengt", "aufnahme-verworfen"),
    EINLERNEN_SESSION_FEHLER: ("einlernen-haengt", None),
    EINLERNEN_SCHLIESSEN: ("einlernen-haengt", "schliessen"),
    EINLERNEN_BLATT: ("einlernen-haengt", "diagnoseblatt"),
    SESSION_ABWEICHUNG: ("session-offen", "abweichung"),
    SESSIONS_OFFEN: ("session-offen", None),
    SESSION_NICHT_FORTSETZBAR: ("session-offen", "kalibrierung-geaendert"),
    KALIBRIEREN_DIALOG: ("einrichtung", "kalibrieren"),
    KALIBRIEREN_OHNE_HINTERGRUND: ("einrichtung", "hintergrund"),
    SETTINGS_SCALE_ZU_GROSS: ("schrift-fenster", None),
    KORREKTUR_DIALOG: ("verwechselt", None),
    ADMIN_PASSWORT: ("admin-passwort", None),
    ADMIN_STATUS_UNVOLLSTAENDIG: ("einrichtung", None),
    ADMIN_KAMERA: ("admin-diagnose", "kamera"),
    ADMIN_SEGTEST: ("admin-diagnose", "segmentierungs-test"),
    ADMIN_SESSIONS: ("session-offen", "admin"),
    ADMIN_ANALYSE: ("admin-analyse", None),
    ADMIN_ARTIKEL_LEER: ("neuer-artikel", None),
    ADMIN_ARTIKEL_QUALITAET: ("einrichtung", "einlernen-qualitaet"),
    ADMIN_CONFIG_DEFEKT: ("app-startet-nicht", "config-defekt"),
}

# Bewusste Ausnahmen: Zustand -> Begründung, warum kein Link gesetzt wird.
KEIN_ANKER: dict[str, str] = {
    BUSY: "Transient; endet von selbst über _on_job_done/_on_job_failed — "
          "ein Link während der Wartezeit hätte kein Handlungsangebot.",
    VORSCHAU_PAUSIERT: "Die Meldung nennt den Ausweg wörtlich (berühren "
          "oder Taste drücken); jede Berührung — auch auf einen Link — "
          "höbe die Pause ohnehin auf. Thema vorschau-steht über Ebene 2.",
    ERGEBNIS_ACCEPT: "Erfolgsanzeige; ein Hilfe-Link auf jeder Übernahme "
          "wäre Dauer-Rauschen. Der Falsch-Fall führt in den Korrektur-"
          "Dialog, und DER trägt den Link (KORREKTUR_DIALOG).",
    SIEGER_OHNE_REFERENZEN: "Hinweis auf einer Erfolgs-Karte; der Text "
          "nennt die Abhilfe selbst (Artikel zuerst einlernen). Thema "
          "neuer-artikel über Ebene 2.",
    SESSION_VERWORFEN_OK: "Erfolgsmeldung mit Sicherungsort — kein "
          "Feststecken.",
    LEERZUSTAND_START: "»Noch kein Ergebnis.« vor der ersten Aktion — "
          "kein Feststecken; die Hilfe ist über die Icon-Schiene "
          "erreichbar.",
    SETTINGS_NEUSTART_HINWEIS: "Die Box erklärt sich selbst (welche "
          "Änderung, wann wirksam) und verlangt nur OK.",
    REPORTS_INFO: "Erklärende Info-/Leerzustände der Reports-Sektion; die "
          "Texte nennen die Sachlage selbst, es gibt keinen Handlungsstau.",
    START_ARGUMENTE: "Konsolenfehler VOR dem Qt-Start — es existiert kein "
          "UI-Ort für einen Link. Inhaltlich behandelt in "
          "app-startet-nicht.",
}

ZUSTAENDE: frozenset[str] = frozenset(ANKER) | frozenset(KEIN_ANKER)


def anker_fuer(zustand: str) -> tuple[str, str | None]:
    """Anker eines Zustands; unbekannter Zustand ist ein Programmierfehler
    und fällt laut, nicht leise (toter Link im Fehlermoment)."""
    try:
        return ANKER[zustand]
    except KeyError:
        raise KeyError(
            f"Kein Hilfe-Anker für Zustand '{zustand}'. Registriert in "
            f"ANKER: {sorted(ANKER)}") from None
