# Analyse-Läufe

Admin → Analyse fasst die gespeicherten Identifikations-Protokolle zu
einem Bericht zusammen (Erfolgsraten, Verwechslungen) und zeigt die
Bewertungs-Übersicht. Ein Lauf liest nur — er verändert weder
Messgrundlage noch Bestand.

## Lauf starten

- 🟡 **GELB** — Quellordner leer lassen (= Standard-Ablage der Protokolle) und „Analyse-Lauf starten“. Der Fortschritt läuft als Balken ohne Prozentanzeige — das ist normal, der Lauf dauert einige Sekunden.
- 🟡 **GELB** — „Noch keine Analyse-Läufe …“: Es wurde schlicht noch keiner gestartet.
- 🟡 **GELB** — „Keine Reports — erst identifizieren und bewerten.“ (Bewertungs-Übersicht): Erst entstehen Protokolle am Hauptfenster, dann gibt es hier etwas zu zählen.

## Lauf bricht ab oder fehlt in der Liste

- 🟡 **GELB** — „Analyse-Lauf fehlgeschlagen: … — Quellordner prüfen, dann erneut starten.“: Existiert der angegebene Ordner, und enthält er Protokoll-Dateien?
- 🟡 **GELB** — Hinweis „ohne metrics.json … zählt der Lauf als ‚ungültig‘ und wird nicht gelistet“: Der Lauf lief, hatte aber nichts auszuwerten (z. B. leerer Quellordner) — Quelle prüfen, erneut starten. Die Zeile „ungültig, … Stück“ unter der Historie zählt solche Ordner offen mit; verschwiegen wird nichts.
- 🟡 **GELB** — „Export fehlgeschlagen: …“: Zielordner und Dateinamen prüfen; vorhandene Dateien werden grundsätzlich NICHT überschrieben.
