# Kamera-Diagnose & Segmentierungs-Test

Beide Werkzeuge liegen im Admin-Fenster unter „Diagnose“. Sie sind rein
lesend beziehungsweise rein diagnostisch — sie verändern keine
Messgrundlage und keinen Bestand.

## Kamera

Die Seite zeigt die konfigurierte Kamera (Index {{config:camera.index}},
Soll-Auflösung {{config:camera.width}} × {{config:camera.height}}), das
Backend, die Focus-Lock-Fähigkeit, den aktuellen Kamera-Zustand des
Hauptfensters und dessen letzte Warnung. Der feste Hinweis dazu: Auf
Mac/AVFoundation ist die Readback-Warnung ERWARTBAR und kein Fehler —
Kamera-Eigenschaften sind dort nicht setzbar; der verlässliche
Messbetrieb ist an der Windows-Box vorgesehen.

- 🟡 **GELB** — „Kameras suchen“ probiert die ersten Geräte-Indizes durch und gibt die Geräte sofort wieder frei. Die Suche ist nur frei, wenn das Hauptfenster KEINE Kamera betreibt — sonst steht dort „Suche gesperrt: …“ mit der Begründung (auch der Getrennt-Zustand verbindet laufend neu; eine parallele Suche würde kollidieren).
- 🟡 **GELB** — „Suche fehlgeschlagen: …“: Die Meldung bleibt bis zur nächsten Suche stehen; erneut suchen, sobald die Ursache (etwa eine belegte Kamera) behoben ist.
- 🟡 **GELB** — „Aktualisieren“ liest Zustand und letzte Warnung neu — zum Beispiel nach einem Umstecken.

## Segmentierungs-Test

Der Test beantwortet die Frage „warum erkennt er nichts?“: eine
Testaufnahme über die Kamera des Hauptfensters, danach Maske,
Kontur-Overlay und Messwerte — ohne Datenbank-Zugriff, ohne Buchung.

- 🟡 **GELB** — „Testaufnahme“ drücken; „Nicht messbar: …“ ist hier das ERWARTETE Diagnose-Ergebnis (etwa bei leerer Box oder Randberührung), kein Absturz.
- 🟡 **GELB** — „Segmentierungs-Test deaktiviert — keine Kamera-Frame-Quelle“: Der Test braucht die verbundene Kamera des Hauptfensters (oder den Demo-Modus); ohne sie bleibt die Seite bewusst aus.
- 🟡 **GELB** — Bleibt „Warte auf Frame vom Hauptfenster …“ stehen (Kamera genau in dem Moment ausgefallen), gibt es derzeit keinen automatischen Abbruch: Kamera prüfen → [Keine Kamera gefunden](hilfe:keine-kamera), dann erneut versuchen.
