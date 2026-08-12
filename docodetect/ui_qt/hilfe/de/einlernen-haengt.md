# Einlernen hakt

Symptom: Im Einlern-Dialog geht es nicht weiter — keine Aufnahme
möglich, eine Meldung steht im Weg, oder der Dialog lässt sich nicht
schließen.

## Was ist los?

Der Ablauf zur Erinnerung: Artikel wählen (das Auswahlfeld findet nur
bereits ANGELEGTE Artikel und legt keine neuen an), Objekt auflegen,
„Aufnehmen“ — üblicherweise {{config:ui.enroll_shots}} Aufnahmen,
zwischen den Aufnahmen das Objekt anheben, drehen UND an eine andere
Stelle legen. Jede Aufnahme wird sofort auf der Platte gesichert; ein
Absturz kostet höchstens die laufende Aufnahme. Ein Klick auf ein
Vorschaubild in der Leiste plus erneutes „Aufnehmen“ ersetzt genau
diese eine Aufnahme.

## Kein Bild

„Noch kein Bild von der Kamera erhalten – erneut versuchen.“ (oder
„Kamera nicht verbunden – Verbindung wird gesucht. …“): Die
angeforderte Aufnahme ist nicht angekommen. Das ist eine
Zustandsmeldung, kein Fehler — die Knöpfe sind wieder frei.

- 🟢 **GRÜN** — Erneut „Aufnehmen“ — oft war es nur ein kurzer Aussetzer.
- 🟡 **GELB** — Kommt weiter kein Bild: Kamera prüfen → [Keine Kamera gefunden](hilfe:keine-kamera). Der Dialog bleibt dabei jederzeit schließbar; bereits gemachte Aufnahmen sind gesichert.

## Aufnahme verworfen

„Aufnahme verworfen: …“ mit Detailmeldung (derzeit teils auf Englisch):
Die Aufnahme war nicht messbar — am häufigsten, weil das Objekt den
Bildrand berührt (→ [Objekt berührt den Bildrand](hilfe:bildrand)).

- 🟢 **GRÜN** — Objekt weiter zur Mitte legen und erneut „Aufnehmen“. Die verworfene Aufnahme zählt nicht — es entsteht weder Lücke noch Doppel.
- 🟢 **GRÜN** — Bei „Session nicht angelegt: …“ die Meldung lesen und erneut versuchen; bleibt es dabei, Technik informieren.

## Schließen

Läuft gerade ein Vorgang, schützt der Dialog kurz vor dem Schließen
(„… bitte noch einen Moment. Die Aufnahmen sind bereits gesichert.“);
nach kurzer Wartezeit erscheint die Rückfrage „Trotzdem schließen?“ —
verloren geht dabei nur der laufende Vorgang, nie eine gesicherte
Aufnahme. Liegen noch ungespeicherte Aufnahmen vor, fragt der Dialog
mit drei Wegen:

- 🟢 **GRÜN** — „Weiter aufnehmen“: zurück in den Dialog, nichts passiert.
- 🟢 **GRÜN** — „Für später behalten“: Die Session bleibt offen und erscheint beim nächsten Einlernen zum Fortsetzen (→ [Einlern-Session offen](hilfe:session-offen)).
- 🟢 **GRÜN** — „Verwerfen“: Die Aufnahmen werden GESICHERT (unter data/verworfen/, ohne Eintrag in der Datenbank) — gelöscht wird nichts.

## Diagnoseblatt

Nach „Speichern“ erscheint zuerst das Diagnoseblatt zur Prüfung — zu
diesem Zeitpunkt steht noch NICHTS in der Datenbank.

- 🟢 **GRÜN** — „Übernehmen“ speichert die Referenzen; „Verwerfen“ sichert die Aufnahmen ohne Datenbank-Eintrag; das Fenster einfach zu schließen bricht nur die Prüfung ab („Prüfung abgebrochen – Aufnahmen bleiben, erneut „Speichern“.“).
- 🟡 **GELB** — Erscheint nach dem Speichern die Warnung „Diagnoseblatt nicht gesichert: …“, ist die Buchung selbst in Ordnung — nur die Blatt-Kopie fehlt. Technik informieren.
