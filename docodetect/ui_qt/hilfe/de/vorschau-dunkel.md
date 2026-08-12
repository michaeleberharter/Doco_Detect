# Vorschau schwarz oder ruckelt

Symptom: Das Livebild ist dunkel oder schwarz — oder es läuft sichtbar
stockend.

## Was ist los?

Steht im Bild „Keine Kamera gefunden…“, ist es kein Anzeigeproblem,
sondern die Verbindung → [Keine Kamera gefunden](hilfe:keine-kamera).
Ist das Fadenkreuz über dem Bild zu sehen, liefert die Kamera — das
Bild zeigt dann schlicht eine dunkle Szene.

Zum Ruckeln: Die Vorschau ist bewusst auf etwa
{{config:ui.preview_fps}} Bilder pro Sekunde begrenzt — die
hochauflösenden Kamerabilder sind teuer zu dekodieren. Ein gemächliches
Vorschaubild ist normal und beeinflusst die Messung nicht: Gemessen
wird immer mit einem vollen Einzelbild, nie mit der Vorschau. Die
tatsächliche Bildrate steht in der Statuszeile („Kamera … fps“).

## Was tun?

- 🟢 **GRÜN** — Prüfen, ob das Fadenkreuz im Bild zu sehen ist: ja = Kamera liefert. Nein plus Meldung „Keine Kamera gefunden…“ → [Keine Kamera gefunden](hilfe:keine-kamera).
- 🟡 **GELB** — Bei dauerhaft dunklem Bild: Beleuchtungssituation an der Box in Augenschein nehmen (hat sich etwas verändert, ist etwas verdeckt?) und die Technik informieren — Änderungen an Licht und Aufbau berühren die Messgrundlage (→ [Maße stimmen plötzlich nicht mehr](hilfe:masse-daneben)).
- 🟢 **GRÜN** — Steht das Bild ganz still → [Vorschau steht still](hilfe:vorschau-steht).
