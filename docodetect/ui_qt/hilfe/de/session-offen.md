# Einlern-Session offen (nach Absturz)

Symptom: Beim Öffnen des Einlernens erscheint der Dialog „Unterbrochene
Einlern-Sessions“ — „… Einlern-Session(s) wurden nicht abgeschlossen.
Die Aufnahmen sind gesichert.“

## Was ist los?

Jede Einlern-Aufnahme wird sofort auf der Platte verankert (unter
{{config:paths.enroll_sessions_dir}}). Stürzt die App ab oder wird der
Dialog mit „Für später behalten“ geschlossen, bleibt die Session offen
und wird beim nächsten Einlernen zum Fortsetzen angeboten. Es geht
nichts verloren. Ausgeführt wird immer die in der Liste MARKIERTE
Session; vorausgewählt ist die neueste.

## Was tun?

- 🟢 **GRÜN** — „Fortsetzen“: Die vorhandenen Aufnahmen werden neu vermessen (dauert einen Moment, mit Fortschrittsanzeige), danach geht es normal weiter bis zum Speichern.
- 🟢 **GRÜN** — „Später – neu einlernen“: Die Sessions bleiben unverändert liegen und erscheinen beim nächsten Mal wieder; das Einlernen startet regulär neu.
- 🟢 **GRÜN** — „Verwerfen“: Die markierte Session wird gesichert (data/verworfen/), es entsteht kein Datenbank-Eintrag — gelöscht wird nichts.

## Abweichung

Meldet die Wiederherstellung „⚠ Wiederherstellung: … Aufnahmen weichen
von den gespeicherten Messwerten ab“, unterscheiden sich Neuvermessung
und gespeicherte Werte. Gebucht werden die GESPEICHERTEN Werte aus dem
Journal, nicht die eben neu gemessenen — genau das sagt auch die
Meldung.

- 🟢 **GRÜN** — Speichern wie es ist: Das Diagnoseblatt im nächsten Schritt zeigt die Streuung über alle Aufnahmen und ist die Entscheidungsgrundlage.
- 🟢 **GRÜN** — Oder verwerfen und neu einlernen — die Aufnahmen bleiben unter data/verworfen/ erhalten.

## Kalibrierung geändert

Steht an einer Session „⚠ Kalibrierung geändert“ und „Nicht
fortsetzbar“, entstanden die Aufnahmen unter einem anderen
Optik-Zustand — sie jetzt zu buchen würde zwei Zustände vermischen.
„Fortsetzen“ ist für diese Session deshalb abgeblendet.

- 🟢 **GRÜN** — Verwerfen (wird gesichert) oder den Artikel unter dem aktuellen Zustand neu einlernen.
- 🔴 **ROT** — Die alte Kalibrierung aus der Sicherung der Session zurückzuholen ist ein Eingriff in die Messgrundlage — nur mit der Technik.

## Admin

Dieselben Sessions zeigt Admin → Artikel → Einlern-Sessions. „Verwerfen
…“ nennt vor der Ausführung die betroffenen Pfade und sichert nach
data/verworfen/. „Fortsetzen“ gibt es dort nur, wenn das Hauptfenster
bereit ist (Kamera verbunden und kalibriert) — sonst steht an seiner
Stelle ein Hinweis.

- 🟢 **GRÜN** — „Aktualisieren“ lädt die Liste neu; „Fortsetzen“ öffnet den normalen Einlern-Dialog mit der gewählten Session.
- 🟡 **GELB** — „Verwerfen fehlgeschlagen: …“: Meldung notieren, erneut versuchen; bleibt es dabei, Technik informieren.
