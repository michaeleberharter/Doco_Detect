# Design: Crash-sichere Einlern-Session

**Datum:** 2026-08-05 · **Art:** Design/Spec, freigegeben abschnittsweise ·
**Status:** entworfen, **nicht umgesetzt** · **Bestand:** bestandsunabhängig
(Artikelnummern kommen in diesem Dokument nur als Beispiele vor).

Ablage- und Fassadenentwurf für ein Einlernen, das einen Absturz übersteht,
plus zwei Robustheitslücken im Kamerapfad. Dauerregeln stehen in
[../../../CLAUDE.md](../../../CLAUDE.md), Architektur in
[../../architektur.md](../../architektur.md).

> **Zum Lesen in sechs Monaten:** Abschnitt 9 listet, was verworfen wurde und
> warum. Wer eine der dortigen Ideen neu vorschlägt, sollte zuerst die
> Begründung entkräften — mehrere davon sind erst im zweiten Anlauf als falsch
> erkannt worden.

---

## 1. Ausgangslage

Am **2026-08-01** ist beim Speichern des Enrollments von LOEFFEL-15 ein
QThread-Segfault aufgetreten; **die 12 Shots waren danach nicht in der DB**
([fixpunkt-test-scoring.md:308-310](../../2026-08-01-fixpunkt-test-scoring.md)).
Das ist die vollständige Aktenlage: kein Trace, kein Log, kein Stack.

Die Ursache ist strukturell, nicht zufällig. `EnrollDialog._shots`
([enroll_dialog.py:102](../../../docodetect/ui_qt/widgets/enroll_dialog.py))
hält alle N Frames und Features **ausschließlich im Arbeitsspeicher**, vom
ersten Shot bis `_job_save` durch ist. Jeder Absturz dazwischen kostet die
gesamte Session. Bemerkenswerterweise schreibt der *Verwerfen*-Pfad auf Platte
([`discard_enrollment`](../../../docodetect/pipeline.py)), der Normalpfad
nicht.

**Warum das jetzt zählt:** vor der Windows-Box stehen 40 Artikel × 12 Shots.
Ein Absturz bei Artikel 35 ist teurer als alles andere auf der Liste.

**Das Design hängt nicht davon ab, dass die Absturzursache je gefunden wird.**
Es macht den Verlust unmöglich, unabhängig vom Auslöser.

---

## 2. Ansatz: Session-Journal in `pipeline.py`

Die Platte wird zur Wahrheit, `self._shots` nur noch ihr Abbild. Neue Fassaden
neben `save_enrollment`/`discard_enrollment`; der Dialog ruft ausschließlich
`pipeline.py` (Architekturregel), und dieselben Fassaden sind von der CLI aus
nutzbar — der Rettungsfall ist genau der, in dem Qt das kaputte Teil ist.

Verworfene Alternativen B und C: siehe Abschnitt 9.

---

## 3. Ablage-Layout

### 3.1 Leitsatz

**Kein Statusfeld, und keine Datei wird je zweimal geschrieben.** Jeder
Zwischenzustand ist aus dem Tripel (Journal, Dateisystem, DB) *ableitbar*. Ein
Statusfeld müsste bei jedem Übergang neu geschrieben werden; was nie
überschrieben wird, kann nicht halb überschrieben sein. Das gilt für den
JSON-Block wie für das PNG.

### 3.2 Config-Key und Verzeichnis

Neu in `config.yaml`:

```yaml
paths:
  enroll_sessions_dir: data/enroll_sessions   # laufende Einlern-Sessions
```

Aufgenommen in `config.sandbox_cfg` als **fünftes** umgelenktes Ziel
(`data/sandbox/<name>/enroll_sessions`) und in `sandbox_pfade`. Die
Sandbox-Umleitung bleibt damit an der einen Stelle, an der sie heute steht.

```
<enroll_sessions_dir>/<artikel>/<ts>/
    session.json          einmalig, atomar (temp+rename+fsync), nie wieder angefasst
    journal.jsonl         append-only, eine Zeile je Shot, flush+fsync
    optik/calibration.json    Kopie des Optikzustands (~200 Byte)
    optik/background.png      Kopie des Optikzustands (~1,26 MB gemessen)
    raw_000.png           Roh-Shots, laufende Nummer, NIE wiederverwendet
    raw_001.png
    raw_002.png           ← Retake von i=1: neue Datei, alte bleibt
```

### 3.3 Dateinamen: laufende Nummer, Endname erst beim Umzug

`raw_<NNN>` zählt **monoton über die gesamte Session** und ist von der
logischen Shot-Position `i` entkoppelt. Ein Retake von Shot 1 schreibt
`raw_002.png` und lässt `raw_001.png` unangetastet. Damit wird **nie ein PNG
überschrieben**, der verworfene Versuch **überlebt** (move-don't-delete, und
beim Retake ist genau das das interessante Material), und die Zuordnung
`i → Datei` steht **explizit im Journal** statt implizit im Dateinamen.

Der Endname `{ts}_{i:02d}.png` wird **beim Umzug** vergeben, aus der
Journal-Reihenfolge.

**Warum nicht schon beim Aufnehmen** (ursprünglicher Entwurf, verworfen):
`references_with_meta` sortiert über den **in der DB gespeicherten**
`image_path` (`database.py:251`, `ORDER BY created_unix ASC, image_path ASC`).
Der entsteht beim Buchen. Weil alle N Zeilen in **einer** Transaktion
geschrieben werden, tragen sie dieselbe `created_unix` — `image_path` ist damit
der *einzige* Diskriminator und muss in Shot-Reihenfolge sortieren. Die
Vergabe aus der Journal-Reihenfolge beim Umzug leistet das explizit; die
Vergabe beim Aufnehmen leistete es nur, weil ein Retake dieselbe Datei
überschrieb.

### 3.4 `session.json` — einmalig, unveränderlich

```json
{
  "article_number": "LOEFFEL-15",
  "ts": 1754312400123,
  "created": "2026-08-05T14:20:00.123456",
  "target_shots": 12,
  "fingerprint": {
    "calibration_sha256":  "a3f1…",
    "background_sha256":   "9c02…",
    "features_cfg_sha256": "5e77…",
    "mm_per_px": 0.1042,
    "camera_height_mm": 300.0
  },
  "owner": { "pid": 48213, "host": "MacBook-Mike" },
  "sandbox": null
}
```

**Fingerabdruck:** SHA-256 über die **Bytes** von `calibration.json` und
`background.png` — Rohdateien, nicht abgeleitete Werte; eine neu geschriebene
Kalibrierung mit zufällig gleichem `mm_per_px` ist trotzdem ein anderer
Optikzustand. `mm_per_px` und `camera_height_mm` stehen zusätzlich im Klartext
daneben, damit eine Verweigerungsmeldung die Abweichung **beziffern** kann.

**`features_cfg_sha256`** über `json.dumps(cfg["features"], sort_keys=True)` —
kanonisiert, damit YAML-Umformatierung ohne Wertänderung nicht anschlägt. Der
Block ist **vollständig**: `features.extract` liest aus `cfg` ausschließlich
`features.ring_zones` und `features.hs_hist_bins`
([features.py:228-232](../../../docodetect/features.py)), sonst nichts.
`matching` bleibt draußen — es parametrisiert das Scoring, nicht die
Merkmalsberechnung.

**`owner`** ist ausdrücklich **nur Warnhinweis**, nie Sperre: eine PID kann
nach einem Absturz neu vergeben sein, und eine als autoritativ behandelte PID
blockierte genau die Rettung, für die das Ganze gebaut wird.

**Kein `st_dev`.** Der Wert ist über Reboot und Remount nicht stabil und
erzeugte auf einer externen Platte Fehlalarme genau dann, wenn nichts kaputt
ist. Die Mount-Prüfung ist eine reine Laufzeitprüfung (3.6).

### 3.5 `journal.jsonl` — append-only

```jsonl
{"i":0,"file":"raw_000.png","t":"2026-08-05T14:20:31.004","d_mm":213.8,"features":{…}}
{"i":1,"file":"raw_001.png","t":"2026-08-05T14:20:58.771","d_mm":214.1,"features":{…}}
{"i":1,"file":"raw_002.png","t":"2026-08-05T14:21:44.019","d_mm":213.9,"features":{…}}
```

Schreibvorgang: `open("a")` → `write(zeile + "\n")` → `flush()` → `os.fsync()`.

**Leseregeln:** eine nicht parsebare **letzte** Zeile wird stillschweigend
verworfen (abgeschnittener Schreibvorgang); eine nicht parsebare Zeile *in der
Mitte* ist ein Befund (`ValueError`) und wird nicht übersprungen. Bei mehreren
Zeilen mit gleichem `i` gilt **die letzte** — Retake ohne Rewrite.

> **N = Zahl der distinkten `i`**, nachdem je `i` die letzte Zeile gewonnen
> hat. **Nicht** die Zeilenzahl. Drei Zeilen mit `i ∈ {0,1,1}` sind **zwei**
> Shots. Daran hängen „Aufnahme 9 von 12", die Thumbnail-Leiste, die
> Vollständigkeitsprüfung und die Zahl der zu verschiebenden Dateien.

Die `features` im Journal sind **Beleg und Buchungsquelle**, nicht bloß
Anzeige — siehe 4.6.

### 3.6 Mount-Voraussetzung: dokumentiert *und* geprüft

**Annahme:** `enroll_sessions_dir` und `reference_dir` liegen auf demselben
Dateisystem. Unter `data/` gegeben, ein absolut gesetzter Pfad kann es brechen.

**Prüfung zur Laufzeit** gegen die aktuell aufgelösten Pfade —
`os.stat(a).st_dev == os.stat(b).st_dev` — an **zwei** Stellen: beim Anlegen
der Session (fail-fast, bevor ein Shot existiert) und **unmittelbar vor dem
Umzug** (die Config kann sich zwischen Absturz und Fortsetzen geändert haben).

Umgesetzt wird mit **`os.rename`, ausdrücklich nicht `shutil.move`**:
`shutil.move` fällt bei `EXDEV` still auf copy+delete zurück — nicht atomar,
und das Löschen der Quelle wäre ein verdeckter Regelverstoß. `os.rename`
scheitert dort laut.

**Plattform-Feinheit, weil Windows das Produktionsziel ist:** `os.rename`
überschreibt unter POSIX stillschweigend und scheitert unter Windows bei
existierendem Ziel. Beides ist inakzeptabel. Der Umzug prüft deshalb **je
Datei vorher**, ob das Ziel existiert (3.8) — gleiches Verhalten auf beiden
Plattformen, und eine bestehende Referenz-PNG kann nicht überschrieben werden.

### 3.7 Durabilitäts-Reihenfolge

**Je Shot, in dieser Reihenfolge:**

1. PNG schreiben → `raw_<NNN>.png`
2. `os.fsync(png_fd)` — Inhalt durabel
3. `os.fsync(session_dir_fd)` — Verzeichniseintrag durabel
4. **Fingerabdruck prüfen** (siehe 4.2 — nach dem Schreiben, damit das Rohbild
   auch im Abweichungsfall erhalten bleibt)
5. Journal-Zeile anhängen → `flush()` → `os.fsync(journal_fd)` — Commit-Record

**Einmalig beim Anlegen:** `session.json` als `.tmp` → `fsync` → `os.rename` →
`fsync(dir)`; leeres `journal.jsonl` anlegen → `fsync(dir)`.

**Warum das PNG keinen temp+rename braucht:** die **Journal-Zeile ist der
Commit-Record**, nicht die Existenz der Datei. Ein halb geschriebenes
`raw_<NNN>.png` ohne Journalzeile ist kein Shot, sondern ein Waisenkind — es
zählt nicht, zieht nicht um und fährt beim Aufräumen nach `backups/`. Schritt 5
macht aus einer Datei einen Shot, Schritt 2 stellt sicher, dass sie dann
vollständig ist.

**Schritt 3 ist auf Windows nicht durchführbar** — ein Verzeichnis lässt sich
dort nicht als Dateideskriptor öffnen, `os.fsync` hat kein Ziel. Der Schritt
läuft POSIX-only und wird auf Windows übersprungen. **Die Folge, ausdrücklich
und nicht stillschweigend:** nach einem **Stromausfall** (nicht: nach einem
Prozessabsturz — dafür genügt der Page-Cache) kann auf NTFS ein
Verzeichniseintrag fehlen, dessen Journalzeile schon durabel ist. Der Schaden
ist begrenzt und **erkennbar** — Fall 4 der Tabelle in 3.8, Abbruch mit Befund,
keine stille Falschmessung. NTFS-Metadaten-Journaling macht den Fall
unwahrscheinlich; das Design stützt sich nicht darauf.

### 3.8 Umzug: vier Fälle je Datei, idempotent

`os.rename` ist innerhalb eines Dateisystems atomar gegenüber Beobachtern
(POSIX per Standard, Windows für Verschiebungen innerhalb eines Volumes). Ein
Zustand, in dem Quelle **und** Ziel aus **demselben** Vorgang existieren, kann
nicht auftreten. Die vier Fälle sind vollständig und disjunkt:

| Quelle | Ziel | Deutung | Aktion |
|---|---|---|---|
| da | fehlt | noch nicht verschoben | `os.rename` |
| weg | da | in einem früheren Lauf erledigt | überspringen |
| da | da | **Fremdkollision** | Abbruch, Klartext |
| weg | fehlt | Datei verschwunden | Abbruch, Befund |

Zu Fall 3: der Endname trägt die Session-`ts` und ist über Sessions hinweg
eindeutig — eine Kollision kann nicht von einer anderen Session desselben
Artikels stammen, sondern bedeutet einen fremden Schreibzugriff auf
`reference_dir`.

**Wiederaufnahme des Umzugs als Verfahren:**

1. `session.json` lesen → `ts`
2. `journal.jsonl` lesen, je `i` die **letzte** Zeile, nach `i` sortieren
3. je `i`: Quelle = `<session>/<file>`, Ziel = `<reference_dir>/<artikel>/{ts}_{i:02d}.png`
4. Vier-Fälle-Tabelle je Datei anwenden
5. erst wenn **alle** N Dateien im Ziel liegen: die eine DB-Transaktion

Die Zuordnung `i → Endname` ist eine **reine Funktion von (`session.json`,
`journal.jsonl`)** und wird bei **jedem** Lauf neu gerechnet — nirgends
gemerkt, in keiner Fortschrittsdatei, in keinem Feld. Genau deshalb ist die
Wiederaufnahme idempotent: derselbe Eingang erzeugt dieselbe Zuordnung,
beliebig oft wiederholbar, und die vier Fälle absorbieren jeden Abbruchpunkt.

### 3.9 Invariante U1

> **U1:** Erst werden **alle N Dateien** verschoben, **danach** werden **alle N
> Referenzzeilen und die Neuberechnung von `reference_stats` in genau einer
> Transaktion** geschrieben. Nie umgekehrt, nie verschränkt. Ein Abbruch
> dazwischen rollt die Transaktion vollständig zurück und landet in „Umzug
> vollständig, DB leer" — wiederaufnehmbar.

Die umgekehrte Reihenfolge erzeugt bei einem Absturz dazwischen genau die
Zeilen mit toten `image_path`, gegen die das Paket gerichtet ist.

`reference_stats` **muss** in dieselbe Transaktion: `sigma_enroll` ist der
Wert, an dem die Neu-Einlern-Disziplin hängt; Referenzzeilen ohne passende
Statistik wären schlimmer als keine Referenzzeilen.

### 3.10 Zustände — abgeleitet, plus eine Assertion

| Journal-Dateien liegen in… | DB-Zeilen | Zustand | Angebot |
|---|---|---|---|
| Session-Ordner | keine | **offen** | fortsetzen / verwerfen |
| teils Session, teils `reference_dir` | keine | **Umzug unterbrochen** | `commit` führt zu Ende und bucht |
| `reference_dir` | alle N | **gebucht, Aufräumen offen** | `commit` räumt nur auf |

> **Assertion (kein Zustand):** `k < N` Zeilen für diese `image_path` — **darf
> nicht entstehen**, weil die Buchung transaktional ist. Tritt es auf, ist eine
> Design-Annahme verletzt. Ausgabe: Artikel, Session-Pfad, die k gefundenen
> Zeilen mit `image_path` und `created_unix`, die N erwarteten. **Kein
> Angebot, keine Automatik, kein Selbstheilungsversuch** — jede Reparatur
> rechnete an `reference_stats`, und die kennt keinen Session-Begriff.

**Woran „eigen" von „fremd" unterschieden wird:** rein strukturell über den
Zielpfad `{ts}_{i:02d}.png`. `ts` ist der Millisekunden-Zeitstempel der
Session-Anlage; keine andere Session kann diesen Pfad erzeugen. Es braucht kein
Merkfeld, keine Session-ID in der DB, keine Schema-Änderung.

### 3.11 Lebenszyklus

- **Gebucht** → Shots per `os.rename` nach `reference_dir/<artikel>/`;
  Restordner nach `backups/<datum>-enroll-sessions/<artikel>-<ts>/`.
- **Explizit verworfen** → Rückumzug (4.7), dann der **vollständige** Ordner
  nach `data/verworfen/<artikel>/<ts>/`. Kein `unlink`, nirgends.
- **Offene Sessions auflisten** = zwei Ebenen unter `enroll_sessions_dir`
  globben. Existenz des Ordners *ist* „offen".
- **Alter** aus `ts` und der mtime von `journal.jsonl`, **nur zur Anzeige**.
  Keine Verfallsregel — Wegräumen nach n Tagen wäre Löschen unter anderem
  Namen. Praktisch sortiert der Fingerabdruck alte Sessions aus.
- **Mehrere offene Sessions je Artikel** sind zulässig (zwei `ts`-Ordner).
  Fortsetzen adressiert **immer eine konkrete Session (Artikel + `ts`)**, nie
  „die für diesen Artikel". Kein Automatismus rät bei Mehrdeutigkeit.

### 3.12 Was in `backups/` landet — Regelfall, keine Garantie

**Im Regelfall** einige KB je Session (`session.json` + `journal.jsonl` +
`optik/`), weil die Shots ihr Ziel *erreichen* statt kopiert zu werden.

**Nicht garantiert:** ein Roh-PNG ohne Journalzeile (Absturz zwischen Schritt 1
und 5 aus 3.7, oder verweigerter Fingerabdruck) bleibt liegen und wandert als
Vollbild mit; ebenso jeder Retake-Vorgänger. Bei zwölf Shots mit drei
Wiederholungen sind das drei 4K-PNGs statt null. Kein Defekt, sondern der Preis
von move-don't-delete — aber Megabyte, nicht Kilobyte.

---

## 4. Fassaden in `pipeline.py`

### 4.1 Datentypen

```python
@dataclass
class SessionShot:
    i: int                    # logische Shot-Position (Retake ersetzt sie)
    raw_path: Path
    d_mm: float
    features: Features

@dataclass
class SessionInfo:
    """Kopf einer Session OHNE Journal-Inhalt – für Listen und Dialoge."""
    path: Path
    article_number: str
    ts: int
    created: str
    target_shots: int
    n_shots: int              # DISTINKTE i, nicht Zeilen
    zustand: str              # "offen" | "umzug_unterbrochen" | "gebucht_aufraeumen_offen"
    fingerprint: dict         # der in session.json gespeicherte Abdruck
    fingerprint_ok: bool
    age_secs: float

@dataclass
class EnrollSession:
    info: SessionInfo
    shots: list[SessionShot]  # je i die LETZTE Journalzeile, nach i sortiert
```

> **Nachgetragen 2026-08-05 aus der Umsetzung (Schritt 2):** `fingerprint: dict`
> stand ursprünglich nicht in `SessionInfo` — ohne den gespeicherten Abdruck
> lässt sich `fingerprint_ok` weder berechnen noch die Abweichung in der
> Verweigerungsmeldung **beziffern**. `zustand` trägt nach Schritt 2 stets
> `"offen"`: die beiden anderen Werte setzen die Berechnung der Zielpfade
> voraus, und die gehört zum Umzug (Schritt 3). Solange es kein `commit` gibt,
> kann kein anderer Zustand entstehen.

### 4.2 Neue Fassaden

Bestehend und **unverändert**: `measure_shot` (pipeline.py:111 — Korpus-Runner
und fünf Analyse-Skripte hängen an seiner Signatur), `list_articles`,
`persist_enrollment_sheet`.

```python
def begin_enroll_session(cfg, article_number, *, target_shots) -> EnrollSession:
    """Neue Session anlegen und auf Platte verankern: Verzeichnis, session.json
    (temp+rename+fsync), leeres journal.jsonl, optik/-Kopien.
    Prüft VOR dem Anlegen: Artikel existiert (KeyError), Mount-Gleichheit
    (EnrollSessionError kind='mount'). Fail-fast, bevor ein Shot existiert."""

def stage_frame(cfg, session, frame) -> Path:
    """Rohbild verankern, BEVOR es vermessen wird. PNG schreiben, fsync(Datei),
    fsync(Verzeichnis, POSIX), DANN Fingerabdruck prüfen.
    Erzeugt noch KEINEN Shot: ohne Journalzeile ist die Datei ein Waisenkind.
    Bei Fingerabdruck-Abweichung (kind='fingerprint') bleibt das Bild als
    Material liegen – dieselbe Behandlung wie bei SegmentationError.
    Kosten der Prüfung: 0,5 ms gemessen, gegen ~1 s Segmentierung je Aufnahme."""

def append_shot(cfg, session, raw_path, feats, *, i=None) -> EnrollSession:
    """Vermessenen Shot ins Journal übernehmen – der Commit-Record. Hängt EINE
    Zeile an, flush+fsync. i=None -> nächste freie Position, i=k -> Retake
    (neue Zeile, alte Zeile und alte Datei bleiben).
    Prüft vorher (ValueError): raw_path liegt im Session-Ordner
    (is_relative_to), Name passt auf raw_<NNN>.png, Datei existiert und ist
    nicht leer. Die Namensprüfung ist NICHT redundant – ohne sie ließe sich
    <session>/optik/background.png übergeben."""

def list_enroll_sessions(cfg, *, article_number=None) -> list[SessionInfo]:
    """Alle OFFENEN Sessions, neueste zuerst. Liest nur session.json +
    journal.jsonl, misst nichts nach. Mehrere je Artikel werden alle
    zurückgegeben."""

def load_enroll_session(cfg, path) -> EnrollSession:
    """Eine konkrete Session laden (Artikel + ts stehen im Pfad). Billig.
    Misst NICHT nach. Kaputte LETZTE Journalzeile wird verworfen, kaputte
    Zeile in der MITTE ist ein Befund (ValueError)."""

def remeasure_session(cfg, session, progress=None) -> tuple[EnrollSession, list[dict]]:
    """Fortsetzen: jeden Shot aus seinem PNG NEU vermessen (~1 s je Shot).
    LESEND – schreibt NICHTS, weder ins Journal noch sonstwohin (siehe 4.6).
    Prüft zuerst den Fingerabdruck. Gibt die Session mit den neu gemessenen
    Werten zurück, ausschliesslich ZUR ANZEIGE, plus die bezifferten
    Abweichungen gegenüber dem Journal. Abweichung ist WARNUNG, nie Abbruch.
    progress(i, n) wird je Shot gerufen."""

def commit_enroll_session(cfg, session) -> int:
    """Buchen unter U1. Liest das Journal von der Platte NEU und benutzt das
    übergebene Objekt nur für den Pfad.
    Prüfungen vor dem ersten Schreibzugriff, in dieser Reihenfolge:
      1. Lückenlosigkeit: distinkte i == {0..N-1}, N >= 1
      2. Mount-Gleichheit
      3. Fingerabdruck (der kritische Moment – hier entsteht sigma_enroll)
      4. Buchungsstand (leer / vollständig / dazwischen -> kind='invariante')
    Dann der idempotente Umzug, dann die Transaktion, dann backups/.
    Bei Buchungsstand 'vollständig' (Zustand 3): Umzug und Transaktion werden
    übersprungen, es folgt nur das Aufräumen. Rückgabe in beiden Wegen N."""

def discard_enroll_session(cfg, session, *, sheet_png=None) -> Path:
    """Verwerfen: Rückumzug (4.7), dann der VOLLSTÄNDIGE Ordner nach
    data/verworfen/<artikel>/<ts>/. Protokolliert in info.json beide Orte vor
    dem Aufräumen, jede Entscheidung je i, jede verlorene Datei.
    Löscht nichts."""
```

**`_move_session_files` ist intern**, nicht öffentlich — Begründung in
Abschnitt 9.

### 4.3 Wer prüft was — jede Prüfung genau einmal

| Prüfung | Implementierung | Aufgerufen von |
|---|---|---|
| Artikel existiert | `Database.get_article` (bestehend) | `begin_enroll_session` |
| Mount-Gleichheit | `_pruefe_mount(cfg)` | `begin`, `commit` |
| Fingerabdruck | `_pruefe_fingerabdruck(cfg, session)` | `begin` (setzt), **`stage_frame`**, `remeasure_session`, `commit` |
| Lückenlosigkeit `i` | `_pruefe_luecken(session)` | `commit` |
| Zeile je Zielpfad | `_zeilen_je_pfad(db, pfade)` (abfragend) | `_pruefe_buchungsstand`, Rückumzug |
| Buchungsstand | `_pruefe_buchungsstand(db, pfade)` (werfend) | `commit` |
| Vier Fälle je Datei | `_move_session_files` / `_reverse_move` | `commit` / `discard` |

**Der Fingerabdruck sitzt in `stage_frame`, nicht nur an den
Session-Grenzen.** Sonst prüft für Shots, die einer *fortgesetzten* Session
hinzugefügt werden, niemand mehr etwas — und zwischen Fortsetzen und der
nächsten Aufnahme kann beliebig viel Zeit liegen; ein `calibrate` in dieser
Lücke ist an der Box kein Randfall. Gemessene Kosten: **0,5 ms** (sha256 über
`calibration.json` + `background.png`, 1,26 MB) gegen ~1 s Segmentierung — 0,05 %.
Keine Abkürzung, kein `os.stat`-Vorfilter.

**Dem Aufrufer bleibt ausschließlich:** Frame beschaffen, `measure_shot` rufen,
Benutzerentscheidungen einholen, anzeigen. **Keine Pfadkonstruktion, keine
wiederholte Prüfung.** Dialog und CLI rufen dieselben Fassaden.

### 4.4 Fehlerverhalten

**Bestehende Typen, wiederverwendet:**

| Befund | Typ | Präzedenz |
|---|---|---|
| Unbekannte `article_number` | `KeyError` | `database.py:226` |
| Session-Ordner / `session.json` / Journal fehlt | `FileNotFoundError` | `config.py:68`, `pipeline.py:209` |
| Kaputte Journalzeile in der Mitte; ungültiger `raw_path` | `ValueError` | `database.py:123`, `config.py:54` |
| Randberührung beim Vermessen | `SegmentationError` | `segmentation.py:126` |

**Ein neuer Typ:**

```python
class EnrollSessionError(RuntimeError):
    """Session-Befund, den der Aufrufer dem Menschen erklären muss.
    `kind` wählt die Behandlung, `detail` trägt die Zahlen für die Meldung."""
    def __init__(self, message, *, kind: str, detail: dict | None = None):
        super().__init__(message)
        self.kind = kind
        self.detail = detail or {}
```

`kind` ∈ `mount` · `fingerprint` · `kollision` · `datei_fehlt` · `luecke` ·
`invariante`.

**Warum ein Typ mit `kind` statt sechs Unterklassen:** Hausform ist Nutzlast
auf einem Typ — `SegmentationError` trägt `.segmentation`
(`segmentation.py:126-134`) statt in `BorderTouchError`/`NoObjectError` zu
zerfallen. Jeder Aufrufer fängt ohnehin die ganze Familie und verzweigt für die
Abhilfe.

### 4.5 `database.add_references`

```python
def add_references(self, article_number: str,
                   items: list[tuple[Features, str | None]]) -> int:
    """Alle Referenzen EINER Einlern-Session in EINER Transaktion.
    N INSERTs + genau ein _recompute_stats + ein Commit (`with self.conn:`).
    Es kann keine Referenzzeile ohne passende reference_stats geben."""
```

Nötig, weil `add_reference` **pro Aufruf** committet (`database.py:234`) und
das von außen nicht zusammenfassbar ist, ohne an `db.conn` vorbeizugreifen —
was `architektur.md` untersagt.

`_recompute_stats` **einmal am Ende** ist semantisch identisch zu N-mal: es
liest per `references_for` **alle** Zeilen des Artikels und schreibt
`reference_stats` neu (`database.py:284-292`, Docstring „Does not commit") —
reihenfolgeunabhängig und idempotent.

- **Leere Liste:** gibt `0` zurück, ohne Transaktion und ohne
  `_recompute_stats`. Die Strenge sitzt eine Schicht höher: `commit` wirft bei
  `N = 0` bereits `kind='luecke'`.
- **Bereits existierende Zeilen für denselben `image_path`:** `add_references`
  erzwingt nichts — es *kann* nicht, denn `reference_features.image_path` trägt
  **keine `UNIQUE`-Bedingung** (`database.py:66-73`, nur
  `idx_ref_article` auf `article_number`). Die Doppelbuchung verhindert
  `_pruefe_buchungsstand` in `commit`, **bevor** eine Datei bewegt wird. Ein
  `UNIQUE`-Index wäre die härtere Absicherung, ist aber eine Schema-Änderung an
  der Tauschschicht und **nicht Teil dieses Pakets**.

**Kosten, benannt:** `database.py` ist ausdrücklich als austauschbare Schicht
für die echte DO&CO-Datenbank gebaut. Die Tauschfläche wächst um eine Methode.
Entschieden: akzeptabel, weil es eine **Methode über bestehendem Schema** ist
(keine Tabelle) und weil eine echte Datenbank ein transaktionales Enrollment
ohnehin anbieten muss.

### 4.6 Woher `commit` seine Werte nimmt

**`commit_enroll_session` liest das Journal von der Platte neu** und benutzt das
übergebene `EnrollSession` nur für den Pfad — dieselbe Regel wie bei der
Zuordnung `i → Endname`: bei jedem Lauf neu aus der Quelle gerechnet, nie aus
mitgereichtem Zustand.

**`remeasure_session` schreibt nichts.** Gebucht werden die **Journalwerte**,
nicht die neu gemessenen. Begründung — die Gegenposition war ursprünglich
meine, siehe Abschnitt 9:

- Fortsetzen ist der Rettungspfad. Eine Operation, die dort schreibt, kann den
  Zustand beschädigen, den sie retten soll. Das Journal ist die einzige Quelle,
  aus der sich nach einem Absturz alles rekonstruieren lässt.
- Die Neumessung hat ungeprüften Determinismus. Driftet sie, wanderte der Drift
  bei jedem Fortsetzen ins Journal; nach dreimaligem Fortsetzen enthielte
  `sigma_enroll` Werte aus drei Segmentierungsläufen — dieselbe Vermischung,
  gegen die der Fingerabdruck gebaut ist, nur innerhalb einer Session.
- Das Argument „die neuen Werte entstanden unter geprüftem Abdruck, die alten
  nur unter vermutlich gleichem" trägt nicht: der Abdruck hasht beim Fortsetzen
  dieselben Dateien wie beim Anlegen. Ist er gleich, war der Zustand
  **nachweislich** derselbe.

**Abweichung über der Toleranz ist ein Befund ohne automatische Reaktion.**
Toleranz je Merkmal: `0,1 × sigma_floor`, bezogen über **`matcher._sigma_floor`**
— nicht über direktes Lesen von `matching.sigma_floors`, weil nur `_sigma_floor`
die `_FLOOR_KEY`-Zuordnung trägt (`delta_e_center`/`_rim` → `delta_e`, beide
Histogramm-Zonen → `hist_bhattacharyya`); direktes Lesen rechnet für diese vier
Merkmale mit Floor 0 — exakt der Fehler, den `analysis.py` gemacht hat und der
am 2026-08-01 gefixt wurde. Prototyp-Merkmale über die L1-Distanz gegen dieselbe
Schwelle.

Größenbegründung: `sigma_floors` sind gemessene Wiederholbarkeits-Böden der
*gesamten* Messkette. Eine Neumessung desselben PNG hat weder Kamera- noch
Platzierungsvarianz; übrig bleibt die Segmentierung. Ein Zehntel des
Betriebsbodens ist niedrig genug, um echte Nichtdeterminismus-Quellen zu
zeigen, und hoch genug, dass Fließkomma-Rauschen nicht dauernd anschlägt. Von
einer gemessenen Größe abgeleitet statt erfunden.

Was der Mensch dann tun kann: 5.3.

### 4.7 Rückumzug beim Verwerfen

| Quelle | Ziel | Zeile zeigt auf Ziel | Aktion |
|---|---|---|---|
| weg | da | **nein** | zurück in die Session |
| weg | da | **ja** | nicht anfassen — gebuchte Referenz, Befund in `info.json` |
| da | da | — | Ziel ist fremd, nicht anfassen |
| da | fehlt | — | nichts zu tun |
| weg | fehlt | — | verloren, in `info.json` vermerken |

Zwei Schranken, damit der Rückumzug nie eine echte Referenz aus
`reference_dir` zieht:

- **Namensschranke:** nur Dateien, deren Name exakt `{ts}_{i:02d}.png` mit
  **dieser** Session-`ts` ist.
- **DB-Schranke (die entscheidende):** nur Dateien, auf die **keine** Zeile
  zeigt. Unter U1 ist die DB in diesem Zustand garantiert leer; findet sich
  doch eine Zeile, ist U1 verletzt und der Rückumzug bricht mit demselben
  Befund ab wie die `k<N`-Assertion, statt an einer gebuchten Referenz zu
  ziehen.

Erst danach wandert der vollständige Ordner nach `verworfen/`.

**Ohne diesen Rückumzug wäre der abgebrochene Umzug eine Sackgasse:** Teile in
`reference_dir`, Rest in der Session, Fortsetzen bricht reproduzierbar wieder
ab, und „ganzen Ordner nach `verworfen/`" verschöbe eine unvollständige
Session.

### 4.8 CLI

Flache Verben wie im Bestand (`list-articles`, `delete-references`):

```
list-enroll-sessions      [--article NR] [--json]
show-enroll-session       <artikel> [--ts TS]
commit-enroll-session     <artikel> [--ts TS] [--dry-run]
discard-enroll-session    <artikel> [--ts TS] [--dry-run]
```

`--ts` ist **verpflichtend, sobald mehr als eine offene Session für den Artikel
existiert** — kein Raten bei Mehrdeutigkeit.

`--dry-run` bei **beiden** schreibenden Befehlen: bei `commit` alle vier
Prüfungen + Umzugsplan; bei `discard` die vollständige Gegenrichtungs-Tabelle
je `i`, ohne eine Datei zu bewegen und ohne `info.json`. Der Rückumzug greift
**aus** `reference_dir` heraus und ist damit die gefährlichere Richtung.

**Vollständigkeit des Rettungspfads:** Auflisten, Ansehen, Buchen und Verwerfen
laufen ohne Qt und **ohne Kamera** — `remeasure_session` liest gespeicherte
PNGs, `commit` bewegt Dateien und schreibt die Transaktion. Nur **zusätzliche
Aufnahmen** brauchen eine Kamera und damit die GUI (oder `enroll --images`).

### 4.9 Sandbox

Zwei Zeilen in `config.py`: `sandbox_cfg` (Zeile 134) bekommt
`out["paths"]["enroll_sessions_dir"] = f"{root}/enroll_sessions"`,
`sandbox_pfade` (Zeile 174) den entsprechenden Eintrag für den Startbanner.
Sonst nirgends. Jede Fassade löst über
`resolve(cfg["paths"]["enroll_sessions_dir"])` auf.

**Keiner der vier neuen Befehle wird unter `--sandbox` gesperrt:** gesperrt ist,
was die *geteilte* Kalibrierung schreibt; Session-Operationen schreiben
ausschließlich in bestandseigene Pfade.

**Bekannte Asymmetrie, benannt statt still erzeugt:** `verworfen/` bleibt aus
`reference_dir.parent` abgeleitet (`pipeline.py:180`) — bestehend, getestet,
dokumentiert, in diesem Paket nicht angefasst. Danach haben zwei benachbarte
Ablagen zwei Auflösungswege.

---

## 5. Dialogfluss

### 5.1 Einstieg: offene Sessions vor dem Einlerndialog

`MainWindow` ruft beim Druck auf „Einlernen" zuerst `list_enroll_sessions` —
billig. Leere Liste → direkt der `EnrollDialog`. Sonst ein **eigener kleiner
Dialog** davor (`ui_qt/widgets/open_sessions_dialog.py`, neu).

**Warum eigener Dialog und kein Banner:** eine unterbrochene Session gehört zu
*ihrem* Artikel, die Artikel-Combo zeigt aber irgendeinen. Ein Banner koppelt
beides sichtbar und legt nahe, „Fortsetzen" bezöge sich auf den gewählten
Artikel.

```
  Unterbrochene Einlern-Sessions

  ● LOEFFEL-15   12 Aufnahmen   vor 4 Minuten     Optik unverändert
  ○ LOEFFEL-15    7 Aufnahmen   vor 2 Tagen       Optik unverändert
  ○ MESSER-3      3 Aufnahmen   vor 9 Tagen       ⚠ Kalibrierung geändert

    [ Fortsetzen ]   [ Verwerfen ]        [ Später – neu einlernen ]
```

Mehrere Sessions je Artikel stehen als getrennte Zeilen, unterschieden durch
**Alter und Aufnahmezahl**. Vorausgewählt ist die neueste; ausgeführt wird die
markierte.

Zeilen mit abweichendem Fingerabdruck sind markiert und **nicht fortsetzbar** —
„Fortsetzen" abgeblendet, nur „Verwerfen" aktiv, Grund in der Zeile statt erst
in einer Fehlermeldung nach dem Klick.

„Später" tut **nichts**: die Sessions bleiben offen. Kein Verwerfen.

### 5.2 Fortsetzen: die Wartezeit

`remeasure_session` misst N Aufnahmen à ~1 s neu — bei zwölf Shots **rund zwölf
Sekunden**, in denen der Dialog nichts anderes tut (Regel: Qt- und
Pipeline-Jobs seriell). Ohne Anzeige sieht das aus wie ein Hänger, und ein
vermuteter Hänger an der Box führt zum Abschießen der App — also genau zu dem
Absturz, gegen den das Paket gebaut ist.

```
  Session wird wiederhergestellt …
  Aufnahme 4 von 12 wird neu vermessen
```

`PipelineWorker` bekommt dafür ein `progress = Signal(int, int)` und ein
explizites `with_progress`-Flag (kein `inspect.signature`-Raten):

```python
def run(self) -> None:
    try:
        if self._with_progress:
            self.finished_ok.emit(self._job(progress=self.progress.emit))
        else:
            self.finished_ok.emit(self._job())
    except Exception as e:
        self.failed.emit(str(e))
```

**Nicht abbrechbar** — zwölf Sekunden rechtfertigen keinen zusätzlichen Zustand
„abgebrochen mitten in der Wiederherstellung"; die Anzeige macht die Wartezeit
erklärbar. Obergrenze zwanzig Sekunden, weil `shots_spin` bei 20 endet.

**Doppelte Wartezeit, benannt:** nach den ~12 s folgt beim Speichern die
Diagnoseblatt-Erstellung, die je Shot erneut segmentiert. Fortsetzen und sofort
speichern kostet **~24 s bei zwölf Shots**. Zusammenlegen wäre ein Eingriff in
`build_enrollment_sheet` — bewusst nicht in diesem Paket (Vormerkliste).

### 5.3 Abweichung über der Toleranz: zwei Auswege

```
  ⚠ Wiederherstellung: 2 von 12 Aufnahmen weichen von den
     gespeicherten Messwerten ab.

     Aufnahme 3:  Ø 213,8 → 214,4 mm   (Δ 0,6 mm, Toleranz 0,15 mm)
     Aufnahme 9:  hu_log 0,412 → 0,455 (Δ 0,043, Toleranz 0,038)

     Gebucht werden die GESPEICHERTEN Werte aus dem Journal, nicht die
     eben neu gemessenen. Die Abweichung heißt: dieselbe Aufnahme ergibt
     heute ein anderes Ergebnis als bei der Aufnahme.

     Sie können
       • speichern wie es ist – das Diagnoseblatt im nächsten Schritt
         zeigt die Streuung über alle 12 Aufnahmen; ist sie unauffällig,
         betrifft die Abweichung die Auswertung, nicht das Enrollment;
       • verwerfen und neu einlernen – die Aufnahmen bleiben unter
         data/verworfen/ als Material erhalten.
```

Der Text muss drei Dinge leisten: sagen **welche Werte gebucht werden** (sonst
nimmt der Leser an, die neuen), sagen **was die Abweichung bedeutet** statt nur
dass sie existiert, und auf das **Diagnoseblatt als Entscheidungshilfe**
verweisen, das ohnehin im nächsten Schritt kommt. Kein neuer Zustand, kein
neuer Dialog.

### 5.4 Normalablauf

**Die Session entsteht lazy — beim ersten „Aufnehmen", nicht beim Öffnen.** Ein
geöffneter und wieder geschlossener Dialog darf keinen leeren Session-Ordner
hinterlassen.

**Ein Klick = ein Worker-Job mit drei Schritten**, seriell:

```python
def _job_capture(frame, cfg, session, i=None) -> dict:
    raw = stage_frame(cfg, session, frame)     # PNG + fsync + Abdruck-Prüfung
    feats, seg = measure_shot(frame, cfg)      # kann SegmentationError werfen
    session = append_shot(cfg, session, raw, feats, i=i)
    return {...}
```

Wirft `measure_shot`, bleibt das PNG als Waise liegen und es entsteht keine
Journalzeile — der bestehende Fehlerpfad (`_job_failed`) bleibt unverändert,
gewinnt aber Material.

**Die Artikel-Combo wird gesperrt, sobald die erste Aufnahme im Journal steht.**
Eine Session ist an ihren Artikel gebunden. **Es gibt keinen eigenen Weg zum
Wechseln** — wer wechseln will, schließt den Dialog und beantwortet die
Rückfrage aus 5.6; beide Antworten führen zum Ziel. Der Sperrhinweis nennt den
Weg ausdrücklich: *„Artikel ist für diese Session festgelegt — zum Wechseln
Dialog schließen."*

**Retake** unverändert in der Bedienung; intern `append_shot(..., i=k)`. Alte
Zeile und alte Datei bleiben.

### 5.5 Speichern

| Schritt | heute | künftig |
|---|---|---|
| Blatt rendern | `_job_sheet` | unverändert, Shots aus der Session |
| Übernehmen | `save_enrollment` + `persist_enrollment_sheet` | **`commit_enroll_session`** + `persist_enrollment_sheet` |
| Verwerfen | `discard_enrollment` | **`discard_enroll_session`** |
| Abbrechen im Blatt | Aufnahmen bleiben | unverändert — Session bleibt offen |

Der Dialog fängt `EnrollSessionError` und zeigt `.detail` als Klartext; er
verzweigt auf `.kind` nur für die angebotene Abhilfe und rechnet nichts nach.

### 5.6 Abbrechen: explizite Rückfrage, Vorbelegung Verwerfen

**Absturz → fortsetzbar. Bewusstes Abbrechen → hinterlässt nur dann eine offene
Session, wenn der Mensch das ausdrücklich wählt.** Kein Zustand entsteht als
Nebenwirkung.

```
  12 Aufnahmen sind noch nicht gespeichert.
    [ Verwerfen ]  ← vorbelegt, hat den Fokus
    [ Für später behalten ]
    [ Weiter aufnehmen ]
```

Bei N = 0 schließt der Dialog wortlos.

### 5.7 Schließschutz während laufender Worker

Nötig, weil `remeasure_session` das Zeitfenster, in dem ein Worker läuft
während sein Elternwidget geschlossen werden kann, von ~1 s auf ~12 s
verbreitert — und genau dieses Fenster beschreibt die Segfault-Notiz
(`QThread: Destroyed while thread '' is still running`).

**Er kann nicht in eine Sackgasse führen:**

1. **Das Warten auf einen Frame ist kein laufender Worker.**
   `_capture` setzt `_awaiting_frame` und fordert an; ein Worker startet erst
   in `_on_full_frame`. Während des Wartens ist der Dialog durchgehend
   schließbar, und der 6-s-Timer (6.3) entsperrt ihn ohnehin.
2. **Alle Worker-Jobs sind begrenzt.** Segmentierung ist CPU-gebunden und
   terminiert; `commit` macht Renames und eine Transaktion, und
   `sqlite3.connect(self.path)` (`database.py:102`) setzt keinen eigenen
   Timeout, läuft also in Pythons Vorgabe von 5 s und wirft dann
   `OperationalError`.
3. **Der Schutz ist eine Schwelle, kein Schloss.** Nach **30 s** erscheint
   zusätzlich „Trotzdem schließen". Wer ihn drückt, verliert nur den laufenden
   Job: die Aufnahmen liegen im Journal, die Session bleibt offen.
   **Das Journal ist der Grund, warum ein erzwungenes Schließen keine Daten
   kostet.**

Der Hinweistext nennt Gegenstand und Restdauer, nicht „bitte warten":
*„Wiederherstellung läuft — Aufnahme 4 von 12 wird neu vermessen, noch etwa
8 s. Die Aufnahmen sind bereits gesichert."*

### 5.8 Betroffene Dateien

| Datei | Änderung |
|---|---|
| `ui_qt/widgets/enroll_dialog.py` | Session statt `self._shots`; drei Jobs umgestellt; Combo-Sperre; Abbrechen-Rückfrage; Schließschutz; 6-s-Timer |
| `ui_qt/widgets/open_sessions_dialog.py` | **neu** |
| `ui_qt/main_window.py` | vor `EnrollDialog` auf offene Sessions prüfen |
| `ui_qt/pipeline_worker.py` | `progress`-Signal + `with_progress` |

---

## 6. Kamera-Fixes

### 6.0 Verhältnis zum Absturz vom 2026-08-01

**Beide Befunde sind Robustheitsverbesserungen, keine Absturzbehebung** — und
die Aktenlage stellt sie **aktiv außerhalb** des Absturzortes: „beim Speichern"
ist der `PipelineWorker` mit `_job_save`, nicht der `CameraWorker`. Beim
Speichern läuft weder eine Kamera-Öffnung noch der Grab-Loop.

**Zu weiteren Kandidaten: nichts Belegtes.** Was möglich wäre, wäre eine
Plausibilitätsliste. **Einen Kandidaten habe ich ausgeschlossen:** `_grab_loop`
liest `self.ui["preview_fps"]` und `["preview_max_width"]` als direkte
Subskripte — das *sieht* nach KeyError aus, kann aber keiner sein, weil
`ui_cfg` (`app.py:33-38`) über `_UI_DEFAULTS` auffüllt.

### 6.1 Befund 2 — nicht-`CameraError` verlässt `QThread.run()`

**Stelle:** `camera_worker.py:72-83` fängt ausschließlich `CameraError`.
`BoxCamera.open()` subskriptiert direkt: `self.cfg["index"]` (camera.py:93),
`["width"]` (102, 114), `["height"]` (103, 114), dazu `camera_cfg["backend"]`
in `capture_backend` (38). Jedes wirft **`KeyError`**. `load_config` prüft nur
die Existenz von **Sektionen** (`config.py:79-81`), nicht einzelner Keys — eine
`camera:`-Sektion ohne `index` lädt sauber.

**Folge:** der KeyError verlässt `run()` — Thread tot, **kein
`camera_error`-Signal**, UI zeigt nichts, `camera_ok` bleibt dauerhaft False,
`stop()` wartet später 8 s auf einen toten Thread.

**Änderung:**

```python
except CameraError as e:
    ...                                    # unverändert: transient -> Reconnect
except Exception as e:                     # noqa: BLE001
    self.camera_ok = False
    self.camera_error.emit(
        f"Kamera kann nicht geöffnet werden ({type(e).__name__}: {e}). "
        "Das ist kein Verbindungsproblem – Konfiguration prüfen "
        "(camera.index / width / height / backend).")
    return                                 # KEIN Reconnect
```

Die Unterscheidung ist der Inhalt: `CameraError` ist vorübergehend und
rechtfertigt den 3-s-Reconnect; ein fehlender Config-Key ist es **nicht** —
alle drei Sekunden erneut daran zu scheitern erzeugt eine Endlosschleife hinter
einer stummen Oberfläche.

### 6.2 Befund 3 — Retrieve-Fehler erreichen die Schwelle nie

**Stelle:** `camera_worker.py:104-125`. `fails = 0` steht in Zeile 115 nach
**jedem** erfolgreichen `grab()`. Ein Retrieve-Fehler erhöht `fails`, springt
zurück, das nächste `grab()` gelingt und setzt zurück. **`_MAX_GRAB_FAILS` ist
auf dem Retrieve-Pfad unerreichbar** — eine Kamera, die greift aber nichts
liefert, friert die Vorschau ein, ohne Fehler und ohne Reconnect.

**Änderung:** zwei getrennte Zähler, jeder auf seinem eigenen Erfolg
zurückgesetzt, beide gegen `_MAX_GRAB_FAILS`. Zwei statt eines geteilten, weil
der bewusste Verwurf überzähliger Frames (Zeile 120, `grab` ohne `retrieve`)
Normalbetrieb ist und einen Retrieve-Zähler weder erhöhen noch zurücksetzen
darf — ein geteilter Zähler bekäme dort wieder eine Sonderregel.

### 6.3 Befund 6 — `request_full_frame` ohne Zeitgrenze

Beide obigen Fehler haben im Einlerndialog **dasselbe Symptom**:
`enroll_dialog.py:226` setzt `_awaiting_frame = True`; zurückgesetzt wird das
**ausschließlich in `_on_full_frame`**. Kommt nie ein Frame — Thread tot (6.1)
oder eingefroren (6.2) —, bleibt der Dialog dauerhaft „busy": beide Knöpfe aus,
**keine Meldung**. Das ist die Bedienlage, aus der heraus jemand die App
abschießt.

**Änderung:** Einzelschuss-`QTimer`, **6 s = 2 × `_RECONNECT_SECS`** (als
Vielfaches der Konstante, nicht als Literal).

Begründung des Werts: der Normalpfad ist nicht das Risiko — ein Frame kostet
ein Intervall (67 ms bei `preview_fps: 15`) plus **9 ms gemessenen
MJPG-Decode** eines 3840×2160-Frames, zusammen **~76 ms**. Das Risiko ist der
Reconnect (`_RECONNECT_SECS = 3.0`, unbegrenzt wiederholt): ein Frame während
eines laufenden Wiederverbindens braucht legitim über 3 s. **Keine endliche
Grenze kann während eines Ausfalls Fehlauslösungen vermeiden** — deshalb ist
die Semantik entscheidend:

- **Der Timer meldet keinen Fehler, sondern einen Zustand**, und gibt den Knopf
  frei. Eine Fehlauslösung ist damit folgenlos: sie behauptet nichts, sie
  beendet nur das stumme Warten.
- **Der Text ist zustandsabhängig** — der Dialog verbindet sich zusätzlich mit
  `camera_error`/`camera_connected`: *„Kamera nicht verbunden — Verbindung wird
  gesucht"* vs. *„Noch kein Bild von der Kamera erhalten — erneut versuchen"*.

### 6.4 Ein Paket, nicht zwei

6.1 und 6.2 stehen technisch unabhängig vom Einlernpfad; 6.3 steht mitten
darin. Alle drei haben **ein gemeinsames beobachtbares Verhalten** —
„Aufnehmen hängt ohne Meldung" — und damit **denselben Test**: eine
Kamera-Attrappe, die nie liefert, prüft alle drei in einem Fall. 6.3 allein
grün zu melden, während der Kamerathread weiter still stirbt, wäre eine halbe
Aussage.

Preis: das Paket berührt mit `camera_worker.py` eine Datei, die mit dem Journal
nichts zu tun hat. Bewusst in Kauf genommen.

### 6.5 Verhältnis zum bekannten QThread-Segfault

**Der eigentliche Segfault-Fix ist NICHT Teil dieses Pakets** (session-scoped
`qapp`-Fixture, deterministisches Teardown mit QThread-Join, ggf. `pytest-qt` —
beschrieben in [ui-qt-testsuite-segfault.md](../../ui-qt-testsuite-segfault.md))
und bleibt Abstimmungsgegenstand mit Timo.

Berührt wird seine Fläche zweifach, und beides gehört in diesen Abstimmungspunkt:
das `progress`-Signal legt N zusätzliche threadübergreifende Zustellungen auf
denselben `PipelineWorker` (von 1 auf N+1), und `remeasure_session` verbreitert
das Worker-Lebensfenster um Faktor zwölf. Der Schließschutz (5.7) entschärft
das zweite — es ist **Verursachung dieses Pakets**, deshalb hier behoben und
nicht delegiert.

---

## 7. Testplan

### 7.1 Trennlinie

**Gegen Sandbox, Temp-Verzeichnisse und Attrappen prüfbar — hier darf „grün"
stehen:** die gesamte Session-Mechanik (Journal, N = distinkte `i`, Vier-Fälle
in beiden Richtungen, U1, Lückenlosigkeit, `k<N`-Assertion, Fingerabdruck an
vier Stellen, Rückumzug mit DB-Schranke), die Absturzsimulation (7.3), die
Dialoglogik gegen eine Frame-Attrappe, die Zählerlogik aus 6.1/6.2 gegen eine
`VideoCapture`-Attrappe.

**Erst an der Windows-Box verifizierbar:** siehe Abschnitt 8 — das ist die
Liste, die abgearbeitet wird, wenn die Box zurück ist.

### 7.2 Invariante → Test

Neue Datei `tests/test_enroll_session.py`, **ohne Qt**, gegen Temp-Verzeichnisse
und Temp-DBs.

| Invariante | Test | Grenze |
|---|---|---|
| **U1** Dateien vor Transaktion | `add_references` per monkeypatch werfen lassen → alle N Dateien im Ziel, DB leer, zweites `commit` vollendet | — |
| **Vier Fälle vorwärts** | vier Dateisystemzustände je `i` konstruieren → erwartete Aktion; Kollision/Verschwinden werfen | — |
| **Vier Fälle rückwärts** | dito für `discard`, inkl. „Zeile zeigt auf Ziel → nicht anfassen" | — |
| **Lückenlosigkeit** | Journal mit `i` = 0,1,3 → `kind='luecke'` | — |
| **N = distinkte `i`** | Journal mit `i` = 0,1,1,2 → `n_shots == 3`, letzte Zeile je `i` gewinnt | — |
| **Retake vernichtet nichts** | nach Retake existiert die alte `raw_<NNN>.png` weiter | — |
| **Fingerabdruck: `begin` SETZT** | die drei Hashes (`calibration.json`, `background.png`, `features`-Block) landen korrekt in `session.json` | `begin` kann nicht prüfen — es gibt keinen Vergleichswert |
| **Fingerabdruck: `stage_frame` PRÜFT** | `calibration.json` bzw. `features`-Block zwischen zwei Aufnahmen ändern → `kind='fingerprint'` | prüft die Hash-Logik, nicht ob sich die Optik real geändert hat |
| **Fingerabdruck: `remeasure_session` PRÜFT** | Abdruck ändern → `kind='fingerprint'`, kein Shot neu vermessen | dito |
| **Fingerabdruck: `commit_enroll_session` PRÜFT** | Abdruck ändern → `kind='fingerprint'`, keine Datei bewegt, DB unverändert | dito |
| **`stage_frame` bewahrt das Rohbild** | Abdruck-Abweichung → wirft, **und** `raw_<NNN>.png` existiert, keine Journalzeile | — |
| **`remeasure` schreibt nicht** | Journal-Bytes vor/nach `remeasure_session` **identisch**; anschließendes `commit` bucht die **ursprünglichen** Werte, nicht die neu gemessenen | — |
| **`append_shot` weist Fremdpfade ab** | `<session>/optik/background.png` übergeben → `ValueError` | — |
| **`k<N`-Assertion** | k Zeilen direkt einfügen, dann `commit` → `kind='invariante'`, keine Datei bewegt | — |
| **Zustand 3** | alle N Zeilen + Dateien im Ziel → `commit` räumt nur auf, bucht nicht doppelt | — |
| **Mehrere Sessions je Artikel** | zwei `ts`-Ordner → beide gelistet, CLI verlangt `--ts` | — |
| **Halbe Journalzeile** | abgeschnittene letzte Zeile → stillschweigend verworfen; kaputte Zeile in der Mitte → `ValueError` | — |
| **Mount-Prüfung** | `os.stat` monkeypatchen (verschiedene `st_dev`) → `kind='mount'` | ⚠ **echtes EXDEV ungeprüft** |
| **Durabilitäts-Reihenfolge** | 7.3 | ⚠ **nur Prozessabsturz** |

Die beiden Tests zu `remeasure` und `append_shot` prüfen Regeln, die **gegen
den ursprünglichen Entwurf** entschieden wurden (Abschnitt 9). Ohne Test würden
sie beim nächsten Umbau unbemerkt zurückgedreht.

**Nicht testbar, und das wird nicht kaschiert:** der eigentliche Zweck von
`fsync` ist der **Stromausfall**, nicht der Prozessabsturz. Ein `SIGKILL`
beendet den Prozess, lässt aber den Page-Cache intakt — die Daten sind danach
da, ob `fsync` lief oder nicht. **Die Reihenfolge aus 3.7 ist entworfen, aber
nicht verifiziert.** Verifikation bräuchte Crash-Consistency-Werkzeug
(`dm-flakey`, VM-Snapshot-Harness), das dieses Projekt nicht hat und das hier
nicht vorgeschlagen wird. Der Testbericht führt diese Zeile als ungeprüft.

### 7.3 Absturzsimulation — der Kern

**(a) Injizierter Abbruch (monkeypatch), deterministisch:** `os.rename` bzw.
`add_references` wirft nach dem k-ten Aufruf. Erreicht jeden Abbruchpunkt exakt
und schnell — beweist aber nichts über die Ablage, weil der Prozess weiterlebt.

**(b) `SIGKILL` auf einen Kindprozess — der eigentliche Test.** Ein
Kindprozess fährt die Session über die Fassaden und meldet Fortschritt über eine
Markerdatei; der Elternprozess schießt ihn an einem definierten Punkt mit
`SIGKILL` ab (kein Handler, kein `finally`, kein Aufräumen) und prüft danach
ausschließlich, was auf der Platte liegt.

| Abschuss nach | Erwarteter Befund | Erwartete Rettung |
|---|---|---|
| PNG geschrieben, **vor** Journalzeile | Waisen-PNG, `n_shots` unverändert | Session offen, fortsetzbar |
| k Journalzeilen | `n_shots == k` | fortsetzbar, weitere Aufnahmen möglich |
| k von N Renames | „Umzug unterbrochen" | `commit` führt zu Ende und bucht |
| alle Renames, **vor** Transaktion | „Umzug vollständig, DB leer" | `commit` bucht, keine Datei bewegt |
| Transaktion durch, **vor** `backups/` | Zustand 3 | `commit` räumt nur auf |

Jeder Punkt prüft zusätzlich: **keine DB-Zeile zeigt ins Leere**, **keine Datei
ist verschwunden**.

### 7.4 Qt-Tests vs. Fassaden-Tests

**Ohne Qt (der weit größere Teil):** alles aus 7.2 und 7.3 plus die CLI-Befehle
über den Argumentparser. Das ist Absicht — die Kernlogik liegt in
`pipeline.py`, der Rettungspfad muss ohne GUI vollständig sein, also ist er auch
ohne GUI vollständig testbar.

**Mit Qt** (`QT_QPA_PLATFORM=offscreen`, neue Datei
`tests/test_ui_enroll_session.py`): Dialog für offene Sessions (Auswahl,
mehrere je Artikel, abgeblendetes „Fortsetzen"), gesperrte Combo,
Abbrechen-Rückfrage mit Vorbelegung, Schließschutz samt „Trotzdem schließen",
Fortschrittsanzeige, 6-s-Timer.

**`camera_worker` ohne Qt-Laufzeit:** `_grab_loop` ist eine gewöhnliche Methode
und wird mit einer `cap`-Attrappe **direkt aufgerufen**, ohne den Thread zu
starten. 6.1/6.2 prüfen damit die Zählerlogik ohne QApplication, ohne
Event-Loop, ohne Segfault-Fläche.

**Laufregel unverändert:** Qt-Module **einzeln** aufrufen, nicht am Stück — der
bekannte Segfault ist nicht Teil dieses Pakets. Der Testbericht nennt die
Einzelaufrufe explizit, damit „grün" nicht aus einem Lauf stammt, in dem ein
Crash echte Fehler maskiert hat.

### 7.5 Korpus

**Berührt dieses Paket den Messpfad? Nein — belegt.** `segmentation.py`,
`features.py`, `matcher.py`, `pipeline.analyze` und `measure_shot` werden nicht
angefasst. Neu sind Session-Fassaden, `add_references`, `camera_worker`, zwei
Dialoge, ein Config-Key.

**Kein Re-Baselining nötig, prüfbar:** `config_fingerprint` speist sich aus
`CONFIG_TEILE_TIER1 = ("features",)` und
`CONFIG_TEILE_TIER2 = ("features", "matching")` (`corpus/runner.py:57-58`).
**`paths` geht nicht ein** — der neue Key ändert keinen Fingerprint.
`add_references` verschiebt nur, *wann* `_recompute_stats` läuft, nicht *was*
es rechnet; `reference_stats` bleibt wertgleich, und Tier 2 spielt ohnehin
gegen eingefrorene Bundle-DBs.

**Erwartung, vor dem Lauf registriert:**

```
corpus-run --tier 1 --check    → Exit 0, kein DRIFT
corpus-run --tier 2 --check    → Exit 0, kein DRIFT, false_accept unverändert
```

Beide **ungefiltert** (`--subset`/`--session`/`--article` enden bewusst mit
Exit 1), beide Stufen (Tier 1 hat leere `quotas`, die
Entscheidungs-Reproduktion läuft dort nicht).

**Zwei erwartbare Störungen, damit sie nicht als Regression gelesen werden:**
das dokumentierte **Tier-1-Flackern** (nichtdeterministisch,
`RuntimeError: vector`, erster Fall `a8d8c8d7`/LOEFFEL-3 — bei Wiederkehr die
Regel aus CLAUDE.md anwenden), und das von
`test_corpus_tier2_decisions_reproduce` bei jedem vollen Lauf hinterlassene
`runs/_invalid/`.

### 7.6 Checkpoint vor dem Suite-Lauf

- **Ausgangsstand:** 680 Tests gesammelt (gemessen auf `ef86abf`).
- **Erwartet nach dem Paket:** 680 + neue Tests, **0 failed**, Skip-Liste
  **unverändert in Zusammensetzung** (mit `-rs` ausgeben und vergleichen, nicht
  nur die Zahl).
- **Laufprofil:** ~20 min, davon 7–8 min scheinbarer Stillstand im Korpus-Block
  bei Test 72/73 — kein Hänger, nicht abbrechen.
- **Qt-Module einzeln**, Ergebnisse getrennt notiert.
- Abweichung von der Erwartung wird **gemeldet, bevor** nachgebessert wird.

---

## 8. Offene Verifikationsliste — erst an der Windows-Box

**Bis diese Liste abgearbeitet ist, bedeutet „Suite grün" NICHT „an der Box
geprüft".** Sie steht hier und nicht nur im Bericht eines Laufs, damit sie ein
Terminal-Scrollback überlebt.

| # | Was | Warum nicht vorher | Status |
|---|---|---|---|
| 1 | `os.rename` auf NTFS bei existierendem Ziel | Plattformverhalten: POSIX überschreibt, Windows scheitert. Die explizite Vorabprüfung ist deswegen da — getestet nur im POSIX-Zweig. | offen |
| 2 | **Übersprungener Verzeichnis-`fsync`** | Der POSIX-only-Zweig aus 3.7 wird auf dem Mac *ausgeführt* und auf Windows *übersprungen*. Der übersprungene Pfad ist auf dem Mac nicht erreichbar. | offen |
| 3 | Mount-Prüfung gegen echtes EXDEV | Braucht zwei Dateisysteme; auf dem Mac nur der monkeypatchte Zweig. | offen |
| 4 | `stage_frame`-Kosten bei echten 4K-Frames | PNG-Schreiben + `fsync` je Aufnahme auf der Platte der Box. Mac nicht repräsentativ. | offen |
| 5 | 6-s-Timer gegen echtes Reconnect-Verhalten | Das reale Gerät bestimmt, wie lange `open()` nach USB-Ausfall dauert. | offen |
| 6 | „Aufnehmen hängt nicht mehr" bei echtem USB-Abzug | Der Befund entstand am Gerät; die Attrappe prüft die Logik, nicht das Gerät. | offen |
| 7 | Die 40-Artikel-Session am Stück | Das eigentliche Ziel des Pakets. | offen |

---

## 9. Verworfene Alternativen

Wer eine davon neu vorschlägt, sollte zuerst die Begründung entkräften.

### 9.1 Ansatz B — der Dialog schreibt selbst

~40 Zeilen kürzer. Verworfen: `enroll_dialog.py` müsste selbst Pfade unter
`reference_dir` bauen — genau die Duplikation, die CLAUDE.md untersagt („UI
ruft nur `pipeline.py`") —, die Sandbox-Umleitung wäre ein zweites Mal
nachzubauen, und **von der CLI aus wäre nichts davon erreichbar**. Der
Rettungsfall ist der, in dem Qt das kaputte Teil ist.

### 9.2 Ansatz C — Staging-Tabelle in SQLite

Transaktional sauber, keine verwaisten Dateien. Verworfen: 4K-Frames gehören
nicht in die DB, die Pfade lägen **trotzdem** auf Platte — es wäre A plus eine
Tabelle. Und `database.py` ist ausdrücklich als austauschbare Schicht für die
echte DO&CO-Datenbank gebaut; eine Staging-**Tabelle** vergrößert genau die
Fläche, die später portiert werden muss.

*(Die später doch beschlossene Methode `add_references` ist davon zu
unterscheiden: eine Methode über bestehendem Schema, keine neue Tabelle — und
eine, die eine echte Datenbank für ein Enrollment ohnehin anbieten muss. Die
Tauschfläche wächst um eine Methode, nicht um ein Schemaelement.)*

### 9.3 Endname `{ts}_{i:02d}.png` bereits beim Aufnehmen

Ursprünglicher Entwurf. Verworfen: ein Retake hätte dieselbe Datei
**überschrieben** — ein Rewrite auf Dateiebene, also derselbe Verstoß gegen die
Append-only-Regel, nur eine Ebene tiefer, plus Vernichtung des verworfenen
Versuchs (move-don't-delete). Die Begründung „der Endname wird für die
Sortierung in `references_with_meta` gebraucht" war **falsch**: sortiert wird
über den in der DB gespeicherten `image_path` (`database.py:251`), und der
entsteht beim Buchen.

### 9.4 `_move_session_files` als öffentliche Fassade

Ausdrücklich angefragt, begründet abgelehnt: eine von außen aufrufbare
Umzugsoperation, die nicht bucht, **erzeugt** absichtlich und wiederholbar den
Zwischenzustand „Dateien umgezogen, DB leer" — aus zwei Aufrufern, die jeder
dort stehenbleiben können. Der Zustand muss *erreichbar und heilbar* sein, weil
Abstürze ihn erzeugen; er muss nicht *anbietbar* sein. `SessionInfo.zustand`
macht ihn sichtbar, `commit_enroll_session` ist idempotent — derselbe Nutzen
ohne die zusätzliche Haltestelle.

### 9.5 `remeasure_session` schreibt die neuen Werte ins Journal

**Mein Vorschlag, verworfen** — Begründung in 4.6. Kurz: Fortsetzen ist der
Rettungspfad und darf nicht schreiben; die Neumessung hat ungeprüften
Determinismus, und ihr Drift würde bei jedem Fortsetzen zur neuen Wahrheit —
nach dreimaligem Fortsetzen enthielte `sigma_enroll` Werte aus drei
Segmentierungsläufen. Mein Gegenargument („die neuen Werte entstanden unter
geprüftem Abdruck") war zirkulär: ist der Abdruck gleich, war der Zustand
nachweislich derselbe.

### 9.6 Zwei getrennte Prüfungen statt einer abfragenden Primitive

Vorgeschlagen war: eine **werfende** Prüfung für `commit`, eine **abfragende**
für `discard`. Verworfen, weil `commit` in **Zustand 3** ebenfalls verzweigen
statt werfen muss. Gebaut wurde deshalb **eine abfragende Primitive**
(`_zeilen_je_pfad`) plus ein **werfender Aufsatz** (`_pruefe_buchungsstand`) —
sonst existierte die Zuordnung Zielpfad → Zeile zweimal.

### 9.7 Fingerabdruck nur an den Session-Grenzen

Verworfen: für Shots, die einer *fortgesetzten* Session hinzugefügt werden,
prüfte dann niemand mehr etwas. Die Prüfung kostet gemessene **0,5 ms** — es
gibt kein Effizienzargument.

### 9.8 Fingerabdruck-Prüfung **vor** dem PNG-Schreiben

Verworfen: der Frame wäre verloren, obwohl die Kamera ausgelöst hat und das
Objekt in der Box liegt. Bei `SegmentationError` wird das Rohbild ausdrücklich
aufgehoben — dieselbe Lage gegenteilig zu behandeln war unbegründet. Und im
Kalibrierungsfall ist der Frame potenziell das interessanteste Material, weil er
nach der Änderung entstanden ist.

### 9.9 Timer bei 5 s, als Fehler gemeldet

5 s war geraten. Verworfen, weil `_RECONNECT_SECS = 3.0` unbegrenzt wiederholt
wird — ein Frame während eines Reconnects braucht legitim über 5 s, und der
Timer meldete einen Fehler, den es nicht gibt. Ersetzt durch **6 s als
Vielfaches der Konstante** und, wichtiger, durch **Zustandsmeldung statt
Fehlermeldung**.

### 9.10 `st_dev` in `session.json` persistieren

Verworfen: über Reboot und Remount nicht stabil, erzeugte auf externen Platten
Fehlalarme genau dann, wenn nichts kaputt ist. Die Mount-Prüfung bleibt eine
reine Laufzeitprüfung gegen die aktuell aufgelösten Pfade.

### 9.11 Automatische Verfallsregel für alte Sessions

Verworfen: Wegräumen nach n Tagen wäre Löschen unter anderem Namen. Alter wird
nur angezeigt; praktisch sortiert der Fingerabdruck alte Sessions aus.

### 9.12 „Abbrechen ist dieselbe Codebahn wie ein Absturz"

Meine ursprüngliche Formulierung, korrigiert: bewusstes Abbrechen darf **keine**
offene Session als Nebenwirkung hinterlassen. Absturz → fortsetzbar; Abbrechen
→ explizite Rückfrage, Vorbelegung Verwerfen.

---

## 10. Verifizierte Codestellen

Alle Zitate dieses Dokuments wurden gegen den Arbeitsbaum auf **`ef86abf`**
geprüft (`git status --short` für `config/` und `docodetect/` leer).

| Stelle | Inhalt |
|---|---|
| `database.py:251` | `ORDER BY created_unix ASC, image_path ASC` |
| `database.py:234` | `self.conn.commit()` — Commit **pro** `add_reference` |
| `database.py:284-292` | `_recompute_stats`, Docstring „Does not commit", liest alle Zeilen → idempotent |
| `database.py:66-73` | `reference_features`: **kein `UNIQUE`** auf `image_path`, nur `idx_ref_article` |
| `database.py:102` | `sqlite3.connect(self.path)` — kein eigener Timeout, Pythons 5 s greifen |
| `features.py:228-232` | liest aus `cfg` **nur** `features.ring_zones` und `features.hs_hist_bins` |
| `pipeline.py:111` | `measure_shot` — bestehend, unverändert |
| `pipeline.py:180` | `verworfen/` aus `reference_dir.parent` |
| `app.py:28` | `"enroll_shots": 12` (Fallback) |
| `config.yaml:136` | `enroll_shots: 12` im Block `ui:` — **einzige** Fundstelle im Baum |
| `config.py:79-81` | `load_config` prüft nur **Sektionen**, nicht einzelne Keys |
| `camera.py:93,102,103,114` | direkte Subskripte `index`/`width`/`height` → `KeyError` |
| `camera_worker.py:72-83` | fängt nur `CameraError` |
| `camera_worker.py:115` | `fails = 0` nach jedem erfolgreichen `grab()` |
| `corpus/runner.py:57-58` | `CONFIG_TEILE_TIER1 = ("features",)`, `TIER2 = ("features","matching")` — **`paths` nicht enthalten** |

**Gemessen** (Mac, Python 3.9.6, warm):

| Größe | Wert |
|---|---|
| `calibration/background.png` | **1,26 MB** (nicht ~10 MB, wie zwischenzeitlich angenommen) |
| sha256 über `calibration.json` + `background.png` | **Median 0,5 ms** (Min 0,5 / Max 1,0) |
| MJPG-Decode 3840×2160 | **Median 9 ms** (Min 9 / Max 10) |
| Frame-Intervall bei `preview_fps: 15` | 67 ms |
| Tests gesammelt auf `ef86abf` | 680 |

**Historischer Hinweis:** `ui.enroll_shots` **war** 8 und wurde am 2026-07-28
mit `fc656ba` auf 12 gezogen („config: enroll_shots 8 -> 12 (Default +
Fallbacks)"). Ältere Kopien der `config.yaml` zeigen deshalb 8 und taugen nicht
als Referenz. Der einzige verbliebene 8er im Repo steht in `README.md`
(Vormerkliste 13d).
