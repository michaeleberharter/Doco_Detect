# Vorschau steht still

Symptom: Das Livebild bewegt sich nicht mehr. Es gibt drei verschiedene
Fälle — an der Meldung im Bild erkennbar.

## Pausiert

Steht im Bild „Vorschau pausiert – berühren oder Taste drücken, um
fortzusetzen.“, hat die App nach längerer Inaktivität nur die ANZEIGE
angehalten. Kamera und Messbereitschaft laufen unverändert weiter.

- 🟢 **GRÜN** — Bildschirm berühren oder eine Taste drücken — die Vorschau läuft sofort weiter.
- 🟢 **GRÜN** — Die Wartezeit bis zur Pause im Einstellungsdialog anpassen (Zahnrad → Bedienung → „Vorschau pausieren nach Inaktivität“; „nie“ schaltet die Pause ab).

## Ergebnisbild

Nach einer Identifikation bleibt das Ergebnisbild mit Rahmen und
Mess-Chips für {{config:ui.result_overlay_secs}} Sekunden stehen — das
ist Absicht, kein Stillstand.

- 🟢 **GRÜN** — Ein Klick/Tipp auf das Bild wechselt sofort zurück zur Live-Ansicht (und wieder zum Ergebnisbild).
- 🟢 **GRÜN** — Die Standzeit im Einstellungsdialog ändern (Zahnrad → Darstellung → „Ergebnis-Standzeit“).

## Stillstand

Ohne Pause-Meldung und ohne „Keine Kamera gefunden…“-Text stockt die
Verbindung zur Kamera. Die App erkennt ausbleibende Bilder selbst und
baut die Verbindung neu auf — meist erscheint kurz „Kamera getrennt“ in
der Statuszeile und danach wieder „Kamera verbunden“.

- 🟢 **GRÜN** — Kurz warten, dann weiterarbeiten.
- 🟡 **GELB** — Bleibt es dabei: USB prüfen, App neu starten → [Keine Kamera gefunden](hilfe:keine-kamera).
