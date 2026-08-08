# Der Streamlit-Config-Tab konnte Schwellen setzen und die gemergte Config zurückschreiben

**Datum:** 2026-08-01 · **Art:** Befund. Auslöser der vollständigen Entfernung
der Streamlit-UI.
**Betrifft:** `app.py`, Tab „Config" (Zeilen 684–699 im Stand vor der Entfernung).

> **Warum dieses Dokument existiert, obwohl der Code weggeht:** Die Entfernung
> löscht den Fehler, nicht die Erkenntnis. Hier steht, *warum* aus einer
> geplanten Teilsperre zweier Einlern-Knöpfe eine vollständige Entfernung
> wurde — auffindbar, wenn der Code längst nur noch in der Git-Historie liegt.

---

## Befund

Der Tab bot Schieberegler direkt auf `cfg["matching"]`:

```python
m = cfg["matching"]
m["diameter_tolerance_mm"] = st.slider("diameter_tolerance_mm", 0.0, 30.0, …)
m["area_tolerance_pct"]    = st.slider("area_tolerance_pct",    0.0, 50.0, …)
m["max_z_accept"]          = st.slider("max_z_accept …",        1.0,  6.0, …)
m["min_llr_margin"]        = st.slider("min_llr_margin …",      0.0, 10.0, …)
m["adaptive_weight_alpha"] = st.slider("adaptive_weight_alpha", 0.0,  5.0, …)
```

und darunter:

```python
if st.button("Dauerhaft in config.yaml speichern"):
    with open(st.session_state.cfg_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, allow_unicode=True, sort_keys=False)
```

`st.session_state.cfg_path` steht per Default auf `config.DEFAULT_CONFIG_PATH`,
also auf der **versionierten, geteilten** `config/config.yaml`.

---

## Zwei Probleme, beide gegen ausdrückliche Projektregeln

### 1. `min_llr_margin` per Schieberegler

`min_llr_margin` ist laut [CLAUDE.md](../CLAUDE.md) „der einzige wirksame Schutz
gegen Fehlbuchungen bei baugleichen Artikeln — nicht lockern", und Schwellen
dürfen nur „mit Datenbegründung UND explizitem Auftrag" geändert werden. Ein
Schieberegler von 0,0 bis 10,0 plus Speichern-Knopf ist die Umgehung beider
Sätze in zwei Klicks. `matching` geht zudem in den `config_fingerprint` des
Regressions-Korpus ein: ein verstelltes Gate entwertet die Baseline still.

### 2. `safe_dump(cfg)` schreibt die GEMERGTE Config zurück

`cfg` kommt aus `load_config()`, und das legt per Deep-Merge die
unversionierte `config.local.yaml` über die Haupt-Config
([config.py:73-77](../docodetect/config.py)). Dem Ergebnis ist nicht mehr
anzusehen, welcher Wert von wo kam.

Gespeichert wurde also der **gemischte** Stand: `camera.index` und die
rig-spezifische `geometry.camera_height_mm` des jeweiligen Rechners landen in
der geteilten `config.yaml` — genau die Trennung, die CLAUDE.md als
Maschinen-Spezifisches ausdrücklich in `config.local.yaml` verortet. Am nächsten
Rechner zeigt der Kamera-Index dann ins Leere, und der Fehler sieht aus wie ein
Hardware-Problem.

Verschärfend: `config.local.yaml` ist gitignored. Der Weg
lokal → geteilt ist damit **einseitig** — einmal zurückgeschrieben, ist nicht
mehr rekonstruierbar, welcher Wert ursprünglich lokal war.

---

## Warum daraus die Entfernung folgte

Der ursprüngliche Auftrag war eng: zwei Einlern-Knöpfe sperren, die
`reference_features`-Zeilen ohne `image_path` erzeugten und damit zweimal die
Forensik blockiert hatten. Der Config-Tab ist ein anderer, schärferer
Fehlermodus — er berührt nicht die Nachvollziehbarkeit, sondern die
Entscheidungsschwelle selbst.

Beides zusammen mit dem Umstand, dass die Streamlit-UI beim Einlernen ohnehin
von Qt und CLI überholt worden war, ergab: ein zweites, halb abgelöstes UI
kostet bei jedem Umbau an `pipeline.py` oder `database.py` Prüfaufwand und muss
von jedem Mitarbeitenden mitgelernt werden — für Funktionen, die es anderswo
besser gibt.

---

## Was NICHT betroffen war

- **Der Messpfad.** Der Tab schrieb Config, keine Messwerte.
- **Der Korpus.** `corpus/runner.py` liest `config.yaml` über `load_config`;
  eine verstellte Schwelle wäre als geänderter `config_fingerprint` aufgefallen
  — aber erst beim nächsten Lauf und ohne Hinweis auf die Ursache.
- **Es gibt keinen Beleg, dass der Knopf je gedrückt wurde.** Die
  `config.yaml` in der Git-Historie zeigt keine unerklärte Schwellenänderung.
  Der Befund ist eine offene Tür, kein nachgewiesener Schaden.

---

## Regel, die daraus folgt

**Eine UI, die Schwellen schreiben kann, braucht dieselbe Begründungspflicht
wie ein Commit.** Wo das nicht durchsetzbar ist, gehört der Schreibweg nicht in
die UI. Lesen und Anzeigen von Parametern ist unproblematisch; das Zurückschreiben
einer per Deep-Merge entstandenen Config ist es nie — es vermischt zwei Quellen,
die bewusst getrennt sind.

## Verwandt

- [2026-08-01-analysis-floor-key-befund.md](2026-08-01-analysis-floor-key-befund.md)
  — dieselbe Klasse: eine Nebenschicht verändert still, was die Hauptschicht
  richtig macht.
- [CLAUDE.md](../CLAUDE.md) — Abschnitte „Architektur-Invarianten" (config.local)
  und „Schwellen/Gewichte".
