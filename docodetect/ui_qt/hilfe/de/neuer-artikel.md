# Neuer Artikel wird nie erkannt

Symptom: Ein bestimmter Artikel kommt nie als Treffer — oder auf der
Ergebniskarte steht „Keine Referenzen – nur Geometrie, Artikel zuerst
einlernen.“

## Was ist los?

Ein Artikel braucht zweierlei: Er muss in der Datenbank ANGELEGT sein
(Stammdaten mit Maß), und er muss EINGELERNT sein (Referenzaufnahmen,
üblicherweise {{config:ui.enroll_shots}} Stück). Wichtig: Das
Auswahlfeld im Einlern-Dialog legt KEINE neuen Artikel an — es findet
nur bereits angelegte. Beides — Anlegen und Einlernen — verändert den
Referenzbestand und ist Sache der Technik.

## Was tun?

- 🟢 **GRÜN** — Statuszeile lesen: „… Artikel (… eingelernt)“. Admin → Artikel zeigt die Liste mit der Referenz-Zahl je Artikel.
- 🟢 **GRÜN** — Jede Fehl-Erkennung des Artikels bewerten („Falsch…“ + wahren Artikel wählen; steht er nicht in der Liste: „Unbekannt / nicht in der Liste“) — das dokumentiert den Fall.
- 🔴 **ROT** — Artikel anlegen und einlernen ist Technik-Arbeit (→ [Einrichtung](hilfe:einrichtung#artikel-anlegen)). Die Kein-Treffer-Karte bietet dafür bewusst keinen Direkt-Knopf an — beides verändert den Referenzbestand, der Weg führt über die Technik.
