# App startet nicht (Technik)

Diese Seite richtet sich an die Technik. Im echten Startfehler ist sie
nicht lesbar — für diesen Fall gilt der Aushang an der Box.

## Was ist los?

Startprobleme liegen VOR der Oberfläche: Python-Umgebung,
Konfigurationsdateien, Kommandozeilen-Argumente. Belegt und
dokumentiert sind die folgenden Fälle; eine vollständige
Startfehler-Anleitung existiert im Projekt bisher nicht.

Einen automatischen Start (Autostart/Kiosk) gibt es derzeit NICHT: Die
App wird an der Box von Hand gestartet. Ein automatischer Start ist als
eigener Vorgang vorgemerkt, aber nicht eingerichtet — bis dahin gilt
der Handstart unten.

## Bekannte Fälle

- 🟡 **GELB** — Start im Terminal: `python -m docodetect.ui_qt` (nach Installation auch `docodetect-ui`). Unter Windows: venv über `.venv\Scripts\Activate.ps1` aktivieren und `python -m pip` statt `pip` verwenden (defekter Launcher).
- 🟡 **GELB** — Meldung „--sandbox und --demo schliessen sich aus“: Nur eines von beiden angeben.
- 🟡 **GELB** — Meldung „[sandbox] …“ zu einem ungültigen Namen: Sandbox-Namen korrigieren; ein ungültiger Name legt nichts an.
- 🟡 **GELB** — Die App startet, verbindet aber keine Kamera, und die Meldung nennt die Konfiguration → [Keine Kamera gefunden](hilfe:keine-kamera#konfiguration).

## Config defekt

Zeigt Admin → Diagnose → Config „Config nicht lesbar: …“, ist eine der
Konfigurationsdateien fehlerhaft — die App selbst schreibt diese
Dateien nie. Die Reparatur der YAML-Dateien ist Technik-Arbeit am
Rechner; die Config-Ansicht bleibt strikt lesend.

- 🟡 **GELB** — Die Meldung vollständig notieren (der Text ist markierbar) und die Datei am Rechner prüfen; danach die Ansicht mit „Aktualisieren“ neu laden.
