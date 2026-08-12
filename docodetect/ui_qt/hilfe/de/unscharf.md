# Bild unscharf

Symptom: Das Livebild wirkt unscharf. Eventuell steht rechts in der
Statuszeile „Fokus-Lock nicht verfügbar – Messbetrieb nur unter Windows
verlässlich.“

## Was ist los?

Der Fokus der Kamera ist bewusst FEST eingestellt — der Autofokus ist
für reproduzierbare Messungen abgeschaltet, der feste Fokuswert wird
beim Verbinden der Kamera gesetzt. Die Statuszeilen-Warnung bedeutet:
Auf diesem Rechner lässt sich der Fokus nicht fest verriegeln. Am
Entwicklungs-Mac ist das erwartbar und kein Fehler; der verlässliche
Messbetrieb ist an der Windows-Box vorgesehen. Dieselbe Einordnung
zeigt Admin → Diagnose → Kamera.

## Was tun?

- 🟡 **GELB** — App neu starten: Beim Verbinden wird das Kameraprofil samt Fokuswert neu gesetzt.
- 🟡 **GELB** — Bleibt das Bild unscharf: Technik informieren — der feste Fokuswert (aktuell {{config:camera.focus_value}}) wird beim Kalibrieren ermittelt und gehört zur Messgrundlage.
- 🔴 **ROT** — Fokus, Kamera-Einstellungen oder Kalibrierung zu verändern ist Technik-Arbeit (→ [Einrichtung](hilfe:einrichtung#kalibrieren)).
