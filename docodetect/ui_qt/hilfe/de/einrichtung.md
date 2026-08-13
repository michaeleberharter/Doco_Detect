# Einrichtung: Hintergrund, Kalibrieren, Einlernen

Diese Seite erklärt die Technik-Aktionen, die die MESSGRUNDLAGE der
Box bestimmen. Sie sind bewusst keine Selbstbedienung: Ein neu
aufgenommener Hintergrund oder eine neue Kalibrierung lässt akute
Symptome oft verschwinden — und verändert dabei still die Grundlage,
auf der ALLE eingelernten Referenzen beruhen. Danach misst die Box
anders als zu dem Zeitpunkt, als sie ihre Artikel gelernt hat. Deshalb
plant und dokumentiert die Technik diese Schritte.

Zeigt das Hauptfenster „Einrichtung nötig“, fehlt einer der beiden
ersten Schritte; die Anzeige führt mit „[offen]/[erledigt]“ durch die
Reihenfolge: erst Hintergrund, dann Kalibrieren.

## Hintergrund

„Hintergrund aufnehmen“ fotografiert die LEERE Box als Referenzbild.
Die gesamte Objekterkennung rechnet als Vergleich gegen dieses Bild —
es ist die Messgrundlage der Erkennung.

- 🔴 **ROT** — Die Technik leert die Box und nimmt den Hintergrund neu auf — nötig nach jeder Änderung an Beleuchtung, Kamera-Einstellungen oder Box-Aufbau. Dabei werden offene Einlern-Sessions unfortsetzbar, und der Vergleich zu bestehenden Referenzen verschiebt sich; deshalb geschieht es geplant, nie als schneller Ausweg.

## Kalibrieren

„Kalibrieren“ legt den Maßstab (mm pro Pixel) der Bodenebene fest —
mit dem gedruckten Marker ({{config:calibration.aruco_dict}}, ID
{{config:calibration.marker_id}}, Kantenlänge
{{config:calibration.marker_size_mm}} mm), flach und mittig auf dem
Boxboden. Der Dialog zeigt die bestehende Kalibrierung samt Datum;
„Kalibrieren“ ersetzt sie. Die Reihenfolge ist Absicht: erst
Hintergrund, dann Kalibrieren — der Dialog weist darauf hin, wenn der
Hintergrund fehlt.

- 🔴 **ROT** — Die Technik legt den Marker flach und mittig ein, kalibriert und prüft das Ergebnis (mm/px) gegen die bisherige Größenordnung — ein Sprung heißt: Marker falsch erkannt. Schlägt der Vorgang fehl, nennt die Meldung die Abhilfe (Druckqualität, Beleuchtung, Marker flach aufliegend) — derzeit auf Englisch.
- 🟡 **GELB** — Bleibt nach dem Klick „Messe…“ stehen, endet das Warten nach kurzer Wartezeit von selbst: „Noch kein Bild von der Kamera erhalten – erneut versuchen.“ Das ist eine Zustandsmeldung, kein Fehler — „Kalibrieren“ ist wieder frei, der Dialog muss dafür nicht geschlossen werden. Zeigt die kleine Vorschau dauerhaft „Warte auf Kamerabild…“, ist die Kamera ausgefallen: Kamera prüfen (→ [Keine Kamera gefunden](hilfe:keine-kamera)).

## Einlernen

Einlernen erzeugt die Referenzaufnahmen eines Artikels (üblich:
{{config:ui.enroll_shots}} Stück). Pflicht zwischen den Aufnahmen:
Objekt anheben, drehen und an eine andere Stelle legen — viele
Aufnahmen derselben Auflage ergeben eine wertlose Referenz. Vor dem
Buchen zeigt der Dialog das Diagnoseblatt zur Sichtprüfung;
„Verwerfen“ sichert die Aufnahmen, ohne die Datenbank anzufassen
(→ [Einlernen hakt](hilfe:einlernen-haengt)).

- 🔴 **ROT** — Einlernen verändert den Referenzbestand und gehört in die Hand der Technik; die Kein-Treffer-Karte bietet dafür bewusst keinen Direkt-Knopf an.

## Einlernen-Qualität

Admin → Artikel zeigt zu jedem Artikel die Streuung der eingelernten
Aufnahmen (Referenz-Kennzahlen). Auffällige Marker dort — etwa „σ=0 …
identische Shots?“ oder eine zu kleine Aufnahmezahl — bedeuten: Das
Enrollment dieses Artikels ist unzuverlässig.

- 🔴 **ROT** — Die Abhilfe ist ein Neu-Einlernen — geplant von der Technik, mit Sichtprüfung des Diagnoseblatts.

## Artikel anlegen

Neue Artikel entstehen nicht in der Oberfläche, sondern über das
Technik-Werkzeug create-article — mit Plausibilitätsprüfung von Maß,
Form (rund oder länglich) und Farbe. Erst danach kann eingelernt
werden. Das Toleranzband der Wiedererkennung liegt bei
±{{config:matching.diameter_tolerance_mm}} mm um das hinterlegte Maß.

- 🔴 **ROT** — Anlegen, Korrigieren und Löschen von Artikeln ist Technik-Arbeit am Rechner; die Artikelliste im Admin-Fenster ist bewusst rein lesend.
