# Nicht gefunden, obwohl vorhanden

Symptom: Die Ergebnisspalte zeigt „Kein Treffer“ und die Karte „Kein
Artikel im Toleranzbereich“ — obwohl der Artikel eingelernt sein müsste.
Darunter stehen der gemessene Durchmesser und die am nächsten liegenden
Kandidaten.

## Was ist los?

Die Messung selbst hat funktioniert, aber kein Artikel der Datenbank
passt zum Messwert: Der Vorfilter akzeptiert nur Kandidaten, deren
hinterlegtes Maß höchstens {{config:matching.diameter_tolerance_mm}} mm
vom gemessenen abweicht (Fläche: {{config:matching.area_tolerance_pct}} %)
— und das anschließende Scoring kann weitere aussortieren. Häufigste
Ursachen: Das Objekt lag ungünstig (schräg, gestapelt, am Rand), der
Artikel ist nicht oder mit anderem Maß angelegt, oder die Messgrundlage
hat sich verändert (dann → [Maße stimmen plötzlich nicht
mehr](hilfe:masse-daneben)).

## Was tun?

- 🟢 **GRÜN** — Objekt einzeln, flach und mittig neu auflegen, dann erneut „Identifizieren“ (Leertaste).
- 🟢 **GRÜN** — Die Liste „Am nächsten liegende Kandidaten“ prüfen: Steht der richtige Artikel dort, antippen — die Auswahl wird im Protokoll vermerkt.
- 🟢 **GRÜN** — Das Ergebnis bewerten („Ablehnung richtig?“): „Richtig“, wenn das Objekt wirklich nicht in der Datenbank ist; „Falsch…“, wenn doch — dann den wahren Artikel wählen. Diese Urteile sind die Datengrundlage für Verbesserungen.
- 🟢 **GRÜN** — In der Statuszeile prüfen, ob der Artikel überhaupt eingelernt ist („… Artikel (… eingelernt)“); Details zeigt Admin → Artikel. Fehlt er → [Neuer Artikel wird nie erkannt](hilfe:neuer-artikel).
- 🔴 **ROT** — Neu einlernen, Hintergrund aufnehmen oder kalibrieren ist KEIN schneller Ausweg: es verändert die Messgrundlage. Diese Schritte plant die Technik (→ [Einrichtung](hilfe:einrichtung)).

## Nichts erkannt

Erscheint stattdessen „Aktion fehlgeschlagen.“ mit einer Detailmeldung
(derzeit auf Englisch, z. B. „No usable object found“), hat die
Erkennung gar kein Objekt gefunden: Box leer, Objekt zu groß fürs Bild,
oder die Beleuchtung hat sich seit der Hintergrund-Aufnahme verändert.

- 🟢 **GRÜN** — Prüfen, ob das Objekt wirklich in der Box liegt; Fremdteile herausnehmen; Objekt mittig platzieren und erneut auslösen.
- 🟡 **GELB** — Hat sich sichtbar etwas an Licht oder Box verändert (verrutscht, verdeckt): Zustand so belassen und die Technik informieren.
- 🔴 **ROT** — Der naheliegende Griff „Hintergrund aufnehmen“ lässt das Symptom verschwinden — und verändert dabei still die Messgrundlage, an der alle eingelernten Referenzen hängen. Nur mit der Technik (→ [Einrichtung](hilfe:einrichtung#hintergrund)).
