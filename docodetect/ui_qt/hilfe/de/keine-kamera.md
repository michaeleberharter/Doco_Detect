# Keine Kamera gefunden

Symptom: Die Vorschau zeigt „Keine Kamera gefunden – Verbindung wird
gesucht…“, die Statuszeile „Kamera getrennt“, die Live-Anzeige „Kein
Bild“. Lief gerade eine Auswertung: „Aktion abgebrochen – Kamera
getrennt.“

## Was ist los?

Die App findet keine Kamera oder hat die Verbindung verloren. Sie
versucht in kurzen Abständen selbsttätig, die Verbindung neu
aufzubauen — meldet sich die Kamera zurück, steht in der Statuszeile
wieder „Kamera verbunden“. Wichtig: Es kann immer nur EIN Programm die
Kamera halten. Solange diese App läuft, scheitert jedes andere Programm
an der Kamera — und umgekehrt.

## Was tun?

- 🟢 **GRÜN** — Kurz warten: Die Verbindung wird automatisch neu aufgebaut; danach die Aktion einfach erneut auslösen.
- 🟡 **GELB** — USB-Stecker der Kamera prüfen (abgezogen? locker?) und einmal neu einstecken.
- 🟡 **GELB** — Sicherstellen, dass kein anderes Programm die Kamera belegt (auch ein parallel laufendes Kommando der Technik zählt).
- 🟡 **GELB** — Hilft das nicht: App schließen und neu starten.

## Konfiguration

Steht im Ergebnisbereich eine Meldung wie „Kamera kann nicht geöffnet
werden (…). Das ist kein Verbindungsproblem – Konfiguration prüfen“,
versucht die App es NICHT weiter — Warten hilft hier nicht.

- 🟡 **GELB** — Technik informieren: Die Kamera-Einstellungen (konfigurierter Geräte-Index: {{config:camera.index}}) passen nicht zum angeschlossenen Gerät. Das Prüfwerkzeug dafür ist Admin → Diagnose → Kamera (→ [Kamera-Diagnose](hilfe:admin-diagnose#kamera)).
- 🟡 **GELB** — Sobald die Ursache behoben ist: App neu starten.
