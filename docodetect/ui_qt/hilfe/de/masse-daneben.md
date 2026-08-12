# Maße stimmen plötzlich nicht mehr

Symptom: Seit heute oder seit kurzem weichen die gemessenen Maße
durchgängig ab; bekannte Artikel landen im „Kein Treffer“ oder bei
falschen Kandidaten. Vorher stimmte alles.

## Was ist los?

Alle Maße hängen an drei Dingen, die zusammen die MESSGRUNDLAGE bilden:
der Kalibrierung (Maßstab in mm pro Pixel — sichtbar in der Statuszeile
„Kalibriert …“), dem Hintergrund-Referenzbild der leeren Box (dagegen
rechnet die gesamte Objekterkennung) und der festen Geometrie
(Kamerahöhe {{config:geometry.camera_height_mm}} mm über dem Boden —
Grundlage der Höhenkorrektur). Verändert sich eines davon — Kamera oder
Box verschoben, Beleuchtung anders, neu kalibriert, neuer
Hintergrund —, verschieben sich ALLE Messungen systematisch.

## Was tun?

- 🟢 **GRÜN** — Ein bekanntes, eingelerntes Objekt zur Probe identifizieren und das Ergebnis bewerten — das dokumentiert den Fall mit Messwerten im Protokoll.
- 🟡 **GELB** — Admin → Status lesen: Wann wurde zuletzt kalibriert, von wann ist der Hintergrund? Passt das zeitlich zu einer Veränderung an der Box?
- 🟡 **GELB** — Nichts an Kamera oder Box verrücken, den Zustand so lassen und die Technik mit den Beobachtungen informieren.
- 🔴 **ROT** — Der verlockende schnelle Ausweg — Hintergrund neu aufnehmen oder neu kalibrieren — lässt das Symptom verschwinden und verändert dabei STILL die Messgrundlage: Alle Referenzen wurden unter dem alten Zustand eingelernt, offene Einlern-Sessions werden unfortsetzbar. Diese Schritte plant die Technik (→ [Einrichtung](hilfe:einrichtung)).
