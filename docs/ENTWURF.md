# Controme Insights – Entwurf v1

Ergänzung zur offiziellen Controme-Integration für Home Assistant.
Stand: 17.11.2026 · Grundlage: Daten der eigenen Anlage (NOVA 27, Mini-Server 4)

---

## 1. Überblick

| Teil | Name | Inhalt |
|---|---|---|
| API-Bibliothek | `aiocontrome` (PyPI, eigenes Repo) | async-Client für die Controme-API, ohne HA-Bezug, mit Tests |
| HA-Integration | Repo `ha-controme-insights`, Domain `controme_insights`, Anzeigename „Controme Insights“ | nutzt `aiocontrome`, ergänzt die offizielle Integration |
| Lizenz | GPL-3.0 (beide Repos) | kompatibel mit flame4ever |

**Abgrenzung:** Raum-Klima, Temperaturszenen, Heizprogramm und Betriebsart übernimmt die offizielle
Integration. Controme Insights baut das nicht nach.

---

## 2. Grundprinzipien

- **Raum-Entitäten hängen an den Raum-Geräten der offiziellen Integration**
  (Geräte-Kennung `("controme", "room_<ID>")`). Ist die offizielle Integration nicht installiert,
  legt Controme Insights eigene Raum-Geräte an.
- **Haus- und System-Entitäten** liegen auf einem eigenen Gerät „Heizung“ (Entitäts-IDs z. B. `sensor.heizung_heizende_raume`; bewusst nicht „Controme …“, siehe unten).
- **Unique IDs** nach flame4ever-Muster: `{haus}_{etage}_{raum}_{schlüssel}` bzw. `{haus}_{schlüssel}`.
- **Namen** über Übersetzungen (Deutsch/Englisch), keine fest eingetragenen Texte.
- **Entitäts-IDs beginnen nicht mit `controme_`**: Das NOVA-Modul „Home Assistant“ blendet mit
  „Controme-eigene Sensoren ausblenden“ alle `sensor.controme_*` aus. Unsere Entitäten folgen dem
  Gerätenamen (z. B. `sensor.wohnzimmer_ventil_eg_2`), Haus-/Gateway-Geräte heißen „Heizung …“ /
  „Gateway …“ statt „Controme …“. Damit bleiben sie in Controme auswählbar (z. B. für FPS).
- **Selten genutzte Entitäten sind standardmäßig deaktiviert.**
- **Räume ohne eigene Regelung** (keine Ausgänge, keine Raumtemperatur) bekommen keine Raum-Entitäten.
  Ihre Fühler werden aber als System-Fühler angeboten (z. B. `hk_verteiler`).
- **Schreibzugriffe nur über die dokumentierte API** und nur nach Freigabe in den Einstellungen.

---

## 3. Datenquellen

| Endpunkt | Doku | Anmeldung | Intervall | Wofür |
|---|---|---|---|---|
| `get/json/v1/{h}/outs/` | dokumentiert | nein | 60 s | Ventilstellung % je Ausgang |
| `get/json/v1/{h}/temps/` | dokumentiert | nein | 60 s | alle Fühler je Raum inkl. letzter Übertragung |
| `get/json/v1/{h}/room_details/` | **undokumentiert** (nutzt die offizielle Integration) | nein (Live-Test 20.11.2026; Rückfall Basic Auth bei 401/403) | 60 s | Offsets je Quelle, nächster Wechsel, Smart Timing, Timer, Gateway offline |
| `get/json/v1/{h}/upcomingoffsets/` | dokumentiert | nein | 5 min | nächster Heizprogramm-Wechsel (Haus) |
| `get/json/v1/{h}/info/` | dokumentiert | nein | beim Start | Software, Branch, Hardware → Geräteinfo |
| `get/json/v1/{h}/vtr/`, `fps/`, `wetter_pro/` | dokumentiert | nein | 5 min | nur wenn die Anlage Daten liefert (bei dir: leer) |
| `set/json/v1/{h}/roomoffset/…` | dokumentiert | ja | bei Bedarf, Erneuerung alle 5 min | API-Offset, Boost |
| `set/json/v1/{h}/quickui/` | dokumentiert | ja | bei Bedarf | Standarddauer Schnellbedienung |
| `set/json/v1/{h}/roomoffset/99999/` | Endpunkt dokumentiert; Verhalten bei unbekanntem Raum nur live beobachtet (20.11.2026, nicht als Fixture) | ja | nur in Einrichtung, Reauth, Reconfigure | Prüfung der Zugangsdaten (`verify_credentials()`, siehe 4b) |

**Rückfall:** Liefert `room_details` im laufenden Betrieb einen Fehler, laufen alle Entitäten aus
`outs`/`temps` weiter. Nur die `room_details`-Entitäten werden „nicht verfügbar“. Das gilt auch
für eine Firmware ohne diesen Endpunkt: Sie lässt sich einrichten, die Zugangsdaten prüft
`verify_credentials()` (siehe 4b).

**Hinweis:** `rltemps` wird nicht gebraucht – `temps` enthält dieselben Rücklauffühler plus alle anderen.

---

## 4. Einrichtung (Config Flow)

1. **Verbindung:** Host, Haus-ID (Standard 1, automatisch erkannt), Benutzer, Passwort.
   Bei `http://` ein Hinweis, dass das Passwort unverschlüsselt übertragen wird. Erst Haus und
   Ausgänge lesen (ohne Zugangsdaten), dann die Zugangsdaten mit `verify_credentials()` prüfen
   (fail closed, siehe 4b). Die getestete Anlage mit einem Haus lieferte für Haus-ID 99
   dieselben Daten wie für 1 (Live-Test 20.11.2026); die Erkennung findet daher 1.
2. **Räume:** Liste der erkannten Räume mit Häkchen (Räume ohne Regelung sind abgewählt).
3. **System-Fühler:** Liste aller Fühler, die keinem Raum als Raum- oder Rücklauffühler dienen,
   mit Wert, Anbindung (siehe 8.) und Häkchen. Bei dir z. B.:
   - `eg_hkv_vl` 23,5 °C · 1-Wire
   - `og_hkv_vl` 31,4 °C · 1-Wire
   - `dg_hkv_vl` 38,4 °C · 1-Wire
   - `ISG_TEMPERATURE_DHW_ACTUAL_522` 42,6 °C · virtuell/Fremdsystem
   Nur angehakte Fühler werden als Entitäten angelegt.
4. **Gateways** (siehe 5a und 6a). Die API nennt keine Gateways, nur Ausgänge je Etage/Raum.
   Darum legt die Einrichtung die Zuordnung fest:
   - **Vorschlag:** ein Gateway je Etage mit Ausgängen (Name z. B. „Gateway EG“, änderbar).
   - **Zusammenlegen:** „Diese Etagen teilen sich ein Gateway“ (z. B. kleines Haus, ein Gateway für DG+OG).
   - **Typ je Gateway:** Auswahl, vorbelegt mit dem Ergebnis der automatischen Erkennung:
   - FBH-Gateway PRO 0–10 V (Stellwert 0–100 %)
   - FBH-Gateway Standard / Mini-Gateway (Relais, an/aus)
   - Automatisch erkennen
   Beispiel eigene Anlage:
   | Etage | erkannt | Vorschlag |
   |---|---|---|
   | Dachgeschoss | Stellwert 29 % gesehen | FBH-Gateway PRO 0–10 V |
   | 1. OG | Stellwert 12 % gesehen | FBH-Gateway PRO 0–10 V |
   | EG | bisher nur 0 – nicht erkennbar | Auswahl nötig (Hinweis: „Welches Gateway versorgt diese Etage?“) |
   Hilfetext: wo man den Typ in Controme findet (Konfiguration → Haus & Geräte → Gateways;
   Abschnitt „Maximale Öffnungswerte für Ausgänge (nur FBH-PRO)“ = PRO).
5. **Schreibfunktionen:** API-Offset/Boost und Schnellbedienung ein/aus (Standard: aus).

Alle Punkte aus 2.–5. lassen sich später unter „Konfigurieren“ ändern.

### 4a. Umsetzung (Präzisierung)

- **Raum ohne Regelung** = Raum ohne Raumtemperaturfühler (`Room.is_controlled` in `aiocontrome`;
  eigene Anlage: nur `hk_verteiler`). **Rücklauffühler** = alle übrigen Fühler eines geregelten
  Raums außer 1-Wire-Feuchte (`Room.return_sensors`, deckt sich mit `rltemps`).
  **System-Fühler** = alle Fühler der Räume ohne Regelung (`House.system_sensors`).
- **Gateways:** ein Formular je Gateway (Etagen, Name, Typ), das sich wiederholt, bis jede Etage mit
  Ausgängen zugeordnet ist. Ist der Typ nicht erkennbar, ist er nicht vorbelegt und muss gewählt
  werden. Kennung des Gateways (Gerät) = erste Etage der Liste.
- **Schritte ohne Inhalt entfallen** (keine System-Fühler, keine Ausgänge).
- **Konfigurieren:** Menü mit Räume, System-Fühler, Gateways, Schreibfunktionen; jeder Punkt wird
  einzeln gespeichert, danach lädt die Integration neu. Nutzt die Daten der laufenden Integration
  (keine zusätzlichen Abfragen); läuft sie nicht, Abbruch mit Hinweis.
- **Gespeichert:** Verbindung in `entry.data`, Auswahl in `entry.options`:
  ```text
  {
    "rooms": [1, 14, ...],                     # Raum-IDs
    "system_sensors": ["<fühler_id>", ...],
    "gateways": [{"name": "Gateway EG", "floors": [6], "type": "position" | "relay" | "auto"}],
    "write_offset": False,                     # API-Offset/Boost
    "write_quickui": False,                    # Schnellbedienung
  }
  ```

### 4b. Zugangsdaten erneuern und Verbindung ändern

- **Prüfung der Zugangsdaten (alle Flows, fail closed):** Kein lesender Endpunkt prüft die
  Zugangsdaten, auch `room_details/` nicht (Live-Test 20.11.2026). Geprüft wird deshalb mit
  `aiocontrome` `verify_credentials()`: POST auf `roomoffset/99999/` (Raum existiert nicht) mit
  Offset 0. Ergebnis → Formular: gültig (404 mit leerem Body) → weiter; abgelehnt (403) →
  `invalid_auth`; nicht erreichbar → `cannot_connect`; jede andere Antwort (z. B. 404 mit
  Django-Debug-Seite, 200, 401, 500) → `cannot_verify` („Zugangsdaten konnten nicht geprüft
  werden, Mini-Server antwortet unerwartet“). In keinem Fehlerfall wird etwas gespeichert. Live
  keine Wirkung beobachtet (Vorher-Nachher-Vergleich 20.11.2026), es bleibt aber ein
  Schreibaufruf: genau einmal pro abgeschicktem Formular, nie im Coordinator oder beim Abruf.
  **Reihenfolge:** Das Passwort geht im Klartext per HTTP hinaus. Einrichtung und Reconfigure
  senden es deshalb erst, nachdem `temps/` unter der Adresse die erwartete Anlage gezeigt hat
  (Einrichtung: ein Haus mit Räumen; Reconfigure: siehe Plausibilität unten); passt `temps/`
  nicht, wird `verify_credentials()` nicht aufgerufen. Reauth prüft gegen den gespeicherten Host.
  **Bewusste Entscheidung: keine periodische Prüfung im Hintergrund.** Sie wäre ein ständiger
  POST auf einen Schreib-Endpunkt.
  **Offene Annahme (Mehrhaus-Anlagen):** Getestet ist nur eine Anlage mit einem Haus (Haus-ID 1,
  Raum 99999). Ob Prüfanfrage, Haus-ID und Raum-IDs sich auf Anlagen mit mehreren Häusern
  genauso verhalten, ist offen. Im ungünstigsten Fall ergibt die Prüfung `cannot_verify`, oder
  eine Anlage antwortet bei fremder Haus- oder Raum-ID mit leerem 404, bevor sie die
  Zugangsdaten prüft; dann würden falsche Zugangsdaten als gültig gespeichert.
- **Passwort:** wird in Reauth und Reconfigure immer neu eingegeben, nie vorbelegt und nach einem
  Formularfehler nie zurückgegeben (nur Host und Benutzer).
- **Reauth** (startet automatisch bei 401/403): fragt Benutzer und Passwort, prüft gegen das Gerät
  unter dem gespeicherten Host und der gespeicherten Haus-ID, speichert nur bei Erfolg. Da kein
  lesender Endpunkt die Zugangsdaten prüft, fällt ein geändertes Passwort erst bei einem
  Schreibaufruf auf (403 → Reauth). Ohne Schreibfunktionen das Passwort über „Neu
  konfigurieren“ ändern.
- **Reconfigure** („Neu konfigurieren“, vor allem nach einem IP-Wechsel): fragt Host, Benutzer und
  Passwort. Ablauf:
  1. Gehört die neue Adresse schon zu einem **anderen** Eintrag (auch einem ignorierten) →
     Abbruch `already_configured`, ohne das Gerät anzusprechen.
  2. **Plausibilität statt Seriennummer** (die API liefert keine), ohne Zugangsdaten und mit der
     gespeicherten Haus-ID: Unter der neuen Adresse muss mindestens einer der ausgewählten Räume
     existieren (ohne Auswahl: irgendein Raum). Die Haus-ID taugt nicht als Merkmal: Die getestete
     Anlage mit einem Haus lieferte für Haus-ID 99 dieselben Daten wie für 1 (Live-Test
     20.11.2026). Antwortet `temps/` mit 404 oder ohne Räume → Abbruch `wrong_device`; die
     Zugangsdaten gehen dann nicht an diese Adresse (z. B. ein anderer Webserver, der auch die
     Prüfanfrage mit leerem 404 beantworten würde). Andere nicht auswertbare Antworten ergeben den
     Formularfehler „kein Haus gefunden“.
  3. Erst danach: Ausgänge lesen und Zugangsdaten über `verify_credentials()` prüfen (wie bei der
     Einrichtung).
  4. Bei Erfolg: neue Verbindungsdaten, **Unique ID folgt der neuen Adresse** (`http://<host>`), ein
     automatisch erzeugter Titel `Controme (<host>)` folgt dem Host, ein umbenannter Titel bleibt.
     Optionen bleiben unverändert; die Integration lädt neu.
- **Formularfehler:** `cannot_connect`, `invalid_auth`, `cannot_verify`, `api_disabled`,
  `no_house`, `unknown`. **Abbrüche:** `reauth_successful`, `reconfigure_successful`,
  `already_configured`, `wrong_device`.

---

## 5. Entitäten pro Raum

Beispiel Wohnzimmer (Raum 19, 2 Ausgänge, 2 Rücklauffühler).

| Entität | Typ | Quelle | Standard | Inhalt / Attribute |
|---|---|---|---|---|
| Ventil Ausgang 2 | Sensor, % | `outs` | an | Stellwert des Ausgangs |
| Ventil Ausgang 3 | Sensor, % | `outs` | an | Stellwert des Ausgangs |
| Ventilöffnung | Sensor, % | `outs` | an | Mittelwert aller Ausgänge des Raums |
| Heizt | Binärsensor (Wärme) | `outs` | an | an, sobald ein Ausgang > 0 % |
| Rücklauf wohnzimmer_rl | Sensor, °C | `temps` | an | ein Sensor je Rücklauffühler; Attribute: Fühler-ID, Anbindung, letzte Übertragung |
| Rücklauf wohnzimmer_rl_randzone | Sensor, °C | `temps` | an | dito |
| Regelabweichung | Sensor, K | berechnet | an | Ist − wirksamer Soll (negativ = zu kalt) |
| Nächster Wechsel | Sensor, Zeitstempel | `room_details` (`nextDueTime`) | an | Attribute: nächste Szene, nächste Temperatur. `nextDueTimeRelative` wird **nicht** genutzt (im Test unzuverlässig, blieb zwischen Abrufen gleich) |
| Smart Timing | Sensor, Aufzählung | `room_details` | an | gesehen: „rechtzeitig“, „vorheizen“; sonst „inaktiv“; Attribute: Zielzeit, Zieltemperatur |
| Offset-Hauptquelle | Sensor, Aufzählung | `room_details` (`dominantOffsetSource`) | an | gesehen: `wetter`, `fps`, `fenster_offen`, `luftfeuchte` und `null` (→ „keine“); unbekannte Werte werden durchgereicht; der API-Offset zählt für Controme **nicht** als Hauptquelle; Attribut: alle Offsets je Quelle |
| Offset Wetter / Luftfeuchte / Fenster offen / Timer / KI / … | Sensor, K | `room_details` | aus | einer je Quelle, die der Raum meldet |
| Fenster-offen-Erkennung | Binärsensor (Fenster) | `room_details` | an | an, solange `offsets["Fenster-offen-Erkennung"].raum` < 0 (Absenkung; getestet 13.11.2026, siehe 10.; `aiocontrome`: `RoomDetails.window_open`) |
| Dauerhafter Sollwert | Sensor, °C | `room_details` | aus | Diagnose |
| Vom Heizprogramm abgekoppelt | Binärsensor (Diagnose) | `room_details` (`sceneControl.ownSchedule`) | an | an, wenn der Raum einen eigenen Zeitplan hat und nicht dem Heizprogramm folgt (Anlass: versehentliches Abkoppeln Wohnzimmer am 13.11.2026) |
| Timer aktiv | Binärsensor | `room_details` | aus | Attribute: Start, Ende, Offset |
| Gateway offline | Binärsensor (Problem) | `room_details` | an | nur wenn Controme `gatewayOfflineMinutes` meldet |
| API-Offset | Zahl, −5…+5 K, Schritt 0,1 | `set-roomoffset` | aus | 0 = aus (Senden von 0 löscht den Offset); Integration erneuert den Offset alle 5 min (Controme verwirft ihn nach 10 min). Aktueller Wert lesbar nur aus `room_details` → `offsets["api"]` (`roomoffsets/` listet API-Offsets nicht, Live-Test 17.11.2026); er ist in `totalOffset` und damit im wirksamen Soll enthalten |

Rund 9–11 aktive Entitäten pro Raum, abhängig von Ausgängen und Rücklauffühlern.

### 5a. Ausgangstyp (Relais oder Stellwert)

Was `outs` bedeutet, hängt von der Hardware ab (siehe flame4ever #33):

| Typ | `outs` meldet | Ventil Ausgang N | Raum-Wert |
|---|---|---|---|
| Relais-Gateway (Schaltausgänge) | nur 0 / 1 | 0 % / 100 % | „Anteil offener Ausgänge“ |
| Stellwert (PWM / 0–10 V) | 0–100 | Wert direkt | „Ventilöffnung“ (Mittelwert) |

- **Einstellung je Etage**, weil `outs` nur nach Etage und Raum gruppiert und die Ausgangsnummern
  je Gateway neu beginnen (eigene Anlage: Ausgang 1 in DG, OG und EG → vermutlich ein Gateway je Etage).
  Die API nennt das Gateway eines Ausgangs nicht.
- **Automatisch:** Sobald ein Ausgang der Etage einmal einen Wert > 1 meldet, gilt sie als Stellwert-Etage
  (wird gespeichert, Hinweis im Log). Solange nur 0/1 vorkamen: Status „unbekannt“, nur „Heizt“ aktiv,
  Hinweis im Reparaturbereich „Gateway-Typ für Etage X festlegen“.
- Eigene Anlage: FBH-Gateway PRO 0–10 V (bestätigt), meldet 12 und 29.
- Unique IDs der Ausgangs-Sensoren enthalten die Etage (`{haus}_{etage}_{raum}_valve_{ausgang}`),
  da Ausgangsnummern sich zwischen Etagen wiederholen.
- „Heizt“ (Ausgang > 0) ist bei beiden Typen korrekt.
- Logik liegt in `aiocontrome`, damit andere Integrationen (flame4ever) sie mitnutzen können.

---

## 6. Entitäten fürs Haus (Gerät „Heizung“)

| Entität | Typ | Quelle | Standard |
|---|---|---|---|
| Heizende Räume | Sensor, Anzahl | `outs` | an |
| Mittlere Ventilöffnung | Sensor, % | `outs` | an |
| Räume unter Soll | Sensor, Anzahl | `room_details` (`temperatureState`) | an |
| Nächster Heizprogramm-Wechsel | Sensor, Zeitstempel; Attribut: Ziel-Szene | `upcomingoffsets` | an |
| Letzte Übertragung | Sensor, Zeitstempel (Diagnose) | `temps` | an |
| Fühler ohne Übertragung | Sensor, Anzahl (Diagnose); Attribut: Liste mit Name, Raum, Anbindung, seit wann | `temps` | an |
| Übertragungsproblem | Binärsensor (Problem) | `temps` | an |
| Haus-Offsets je Quelle | Sensor, K | `room_details` | aus |
| Standarddauer Schnellbedienung | Zahl, Minuten | `set-quickui` | aus (nur wenn Schreiben freigegeben) |
| Vorlauf / Mischer / Wetter Pro | Sensoren | `vtr`, `wetter_pro` | nur wenn Daten vorhanden (eigene Anlage: leer) |

Geräteinfo aus `info` (eigene Anlage):
- Software: `controme-core`, Branch `uiv2`, Stand 2026-11-02, Commit `00744075` → „uiv2 · 2026-11-02 (00744075)“
- Hardware: Raspberry Pi 4 Model B Rev 1.4 · Debian 11
- Diagnose-Attribute: Services-Paket aktiv, App-kompatibel

---

## 6b. FPS-Bausteine (Formel-Programm-System)

`fps` liefert alle FPS-Bausteine mit Formel, ausgewerteten Variablen und Ergebnis. Eigene Anlage: 10 Bausteine
(Logik „WP überheizen“ mit evcc-Freigabe, Warmwasser-Bereitschaft aus dem ISG, PV-Prognose aus HA,
Raum-Offsets im PV-Boost).

Ein Gerät „FPS“ (verbunden mit „Heizung“), je Baustein:

| Entität | Typ | Wann | Standard |
|---|---|---|---|
| FPS <Name> | Binärsensor | `mode = output` und Ergebnis nur 0/1 (z. B. „WP überheizen A evcc-Freigabe“) | an |
| FPS <Name> | Sensor, K | `mode = offset` (z. B. „WP überheizen“ = 0 oder 2 K, „WP überheizen Bad“) | an |

Attribute je Baustein: Formel, ausgewertete Variablen (M1, M2, A1 …, V1), Eingänge mit Namen
(z. B. „M1 = ISG_TEMPERATURE_DHW_ACTUAL_522“), Schieberegler-Werte mit Min/Max, Handbetrieb
(an/aus, Modus, bis wann), letzte Auswertung, Beschreibung für Nutzer.

Diagnose (Haus): „FPS Handbetrieb aktiv“ (Anzahl Bausteine mit `override_enabled`), „FPS letzte Auswertung“.

**Nur lesen in v1:** Für FPS gibt es keinen dokumentierten Schreib-Endpunkt. Schieberegler (z. B.
„Mindest-PV-Prognose“, „Obergrenze“) und Handbetrieb erscheinen deshalb nur als Attribute.
Schreiben ggf. später, falls Controme einen offiziellen Weg bietet.

---

## 6a. Gateway-Geräte

Ein HA-Gerät je in der Einrichtung festgelegtem Gateway, z. B. „Gateway EG“
(Hersteller Controme, Modell „FBH-Gateway PRO 0–10 V“, verbunden mit dem Gerät „Heizung“).

| Entität | Typ | Quelle | Standard |
|---|---|---|---|
| Aktive Ausgänge | Sensor, Anzahl (Attribut: Liste Ausgang → Raum → Wert) | `outs` | an |
| Mittlere Öffnung | Sensor, % (nur PRO) | `outs` | an |
| Belegte Ausgänge | Sensor, Anzahl (Diagnose) | `outs` | aus |
| Gateway offline | Binärsensor (Problem) | `room_details` (`gatewayOfflineMinutes` der Räume dieses Gateways) | an |

Eigene Anlage:
- Gateway DG: Büro (Ausgänge 1, 2)
- Gateway OG: Schlafzimmer 1, Gästezimmer 2, Kinderzimmer 3, Bad 4
- Gateway EG: Küche 1, Wohnzimmer 2+3, Flur 4, Gästeklo 5

Die Ventil-Sensoren je Ausgang bleiben am **Raum**-Gerät (dort sucht man sie); im Namen bzw. Attribut
steht das Gateway (z. B. „Ventil EG-2“). Hinweise im Reparaturbereich nennen ebenfalls das Gateway.

---

## 7. System-Fühler (Punkte 1 + 3)

Nur die bei der Einrichtung angehakten Fühler (siehe 4.3).

| Entität | Typ | Beispiel |
|---|---|---|
| Vorlauf EG / OG / DG | Sensor, °C | `eg_hkv_vl`, `og_hkv_vl`, `dg_hkv_vl` |
| Warmwasser-Ist | Sensor, °C | `ISG_TEMPERATURE_DHW_ACTUAL_522` |
| weitere nicht zugeordnete Fühler | Sensor, Einheit nach Wert | – |

Name = Controme-Beschreibung (umbenennbar in HA). Attribute: Fühler-ID, Anbindung, letzte Übertragung.

---

## 8. Anbindung der Fühler (zu Punkt 7)

Jede Fühler-Entität und jede Meldung zeigt, wie der Fühler angebunden ist. Erkennung aus der Fühler-ID:

| ID-Muster | Anbindung | Beispiele bei dir | sicher? |
|---|---|---|---|
| `28_xx_xx_xx_xx_xx_xx_xx` | 1-Wire, Temperatur (DS18B20) | Rücklauf-, Raum-, Vorlauffühler | ja |
| `26_xx_…` | 1-Wire, Feuchte (DS2438) | `schlafzimmer_rf`, `kueche_rf` | ja |
| `aa:bb:cc:dd:ee:ff` (6 Byte) | Controme-Raumcontroller (Funk) | `raumcontroller_lf_bad_neu` | wahrscheinlich |
| `aa:bb:cc:dd` (4 Byte) | Controme-Funkfühler | `gaesteklo_rt`, `keller_vorratsraum` | ja (bestätigt: original Controme-Funksensor) |
| Nullen-ID / Name mit Fremdsystem (z. B. `ISG_…`) | virtuell / Fremdsystem (Modbus/Uniconnect) | `ISG_TEMPERATURE_DHW_ACTUAL_522` | wahrscheinlich |

---

## 9. Hinweise im Reparaturbereich (Punkt 7)

| Hinweis | Auslöser | Text enthält |
|---|---|---|
| Fühler sendet nicht | keine Übertragung seit > Schwelle (Standard 15 min, einstellbar) oder noch nie | Fühlername, Raum, Anbindung, seit wann; Tipp je Anbindung (1-Wire: Verkabelung/Bus; Funk: Batterie/Reichweite) |
| Gateway offline | `gatewayOfflineMinutes` gesetzt | betroffene Räume, Dauer |
| room_details nicht verfügbar | Fehler beim undokumentierten Endpunkt | welche Entitäten betroffen sind |

Hinweise verschwinden automatisch, sobald das Problem behoben ist.
Bei dir würde sofort einer erscheinen: `keller_vorratsraum` meldet keine aktuelle Übertragung.
Hinweis: `letzte_uebertragung: null` bedeutet „kein aktueller Wert“, nicht „nie übertragen“ – der Text lautet
dann „sendet derzeit nicht, letzte Übertragung unbekannt“. Die Integration merkt sich den letzten gesehenen
Zeitpunkt selbst, sobald sie einmal einen Wert erhalten hat.

---

## 10. Fenster (Punkt 10 – Entscheidung offen)

Es gibt zwei Welten: die **Fenster-offen-Erkennung von Controme** (erkennt Temperaturabfall, setzt einen
Offset) und **echte Fensterkontakte in Home Assistant**.

**Variante A – nur anzeigen (in v1 enthalten, getestet):**
Binärsensor „Fenster-offen-Erkennung“ je Raum aus dem Controme-Offset (siehe 5.).

Test 13.11.2026, Gästeklo (Raum 23, Funkfühler):

| Abruf | Raumtemp. | Fenster-Offset | Ziel | Hauptquelle |
|---|---|---|---|---|
| vorher | 19,1 °C | 0 | 21,3 °C | fps |
| +10 min offen | 15,8 °C | −10 K | 11,3 °C | fenster_offen |
| +20 min offen | 15,8 °C | −10 K | 11,3 °C | fenster_offen |
| +10 min zu | 18,7 °C | 0 | 19,2 °C | wetter |

Erkennung ≤ 10 min nach Öffnen, Rücknahme ≤ 10 min nach Schließen, Absenkung −10 K.
Funkfühler sendet seltener (Wert bei +10 und +20 min identisch).
Testdaten zugleich als Fixture nutzen (inkl. aktivem PV-Boost „WP überheizen“ mit FPS-Offsets +2…+5 K).

**Variante B – HA-Fensterkontakte an Controme weitergeben (später):**
Pro Raum in den Einstellungen einen oder mehrere HA-Fensterkontakte wählen. Ist ein Fenster offen,
setzt Controme Insights einen API-Offset (z. B. −5 K, einstellbar) und nimmt ihn beim Schließen
wieder weg. Fragen dabei: Zusammenspiel mit der Controme-eigenen Erkennung, Verzögerung (z. B. erst nach
2 min), Verhalten bei Neustart.

**Variante C – NOVA-Plugin „Home Assistant“ (vorhanden, dokumentiert):**
Doku: https://support.controme.com/homeassistant-plugin/ (Stand 09/2026).
- Controme holt Werte per REST aus HA (Langzeit-Token, Abfrage 60 s, Cache bei Verbindungsabbruch).
- **Nur numerische `sensor.*`** – kein `binary_sensor.*`, kein `input_number.*`, keine Textwerte.
  Fensterkontakte direkt: **nicht möglich**.
- Freigeschaltete Entität = System-Sensor mit SSN (z. B. `12_00_00_00_ha_a1b_2c3`), kostet je eine
  Sensor-Lizenz (gemeinsamer Pool mit UniConnect/KNX); Zuordnung als Raumtemperaturfühler möglich.
- Token: eigener HA-Benutzer ohne Administratorrechte (Doku nennt keine Rechte; Lesen genügt).

**Umweg für Fensterkontakte über C:** HA-Template-Sensor `sensor.fenster_<raum>` (1 = offen, 0 = zu)
→ als System-Sensor freischalten → FPS-Baustein „offset“ (z. B. −10 K, solange Wert = 1).
Prüfen: kann ein FPS-Baustein System-Sensoren als Eingang nutzen (`variables_details.sensors`)?

Hinweis für Controme Insights: Unsere numerischen Sensoren (z. B. Rücklauf, Vorlauf) sind über
dieses Plugin in Controme nutzbar, sofern die Entitäts-ID nicht mit `controme_` beginnt (siehe 2.).

**Variante D – UniConnect + FPS (sofort möglich, Muster existiert schon):**
Die eigene Anlage holt bereits Werte aus HA per UniConnect HTTP_GET (`/local/pv_prognose_3h.json`) und
verarbeitet sie in einem FPS-Baustein. Genauso ginge es für Fenster: HA schreibt den Fensterzustand je Raum
als JSON nach `/local/`, UniConnect liest ihn, ein FPS-Baustein im Modus „offset“ setzt z. B. −5 K für den Raum.
Vorteil: Logik läuft in Controme, auch wenn HA kurz ausfällt (letzter Wert/Fehlerwert). Nachteil: zählt ggf.
aufs Smart-Home-Connect-Kontingent, Einrichtung je Raum in Controme.

Empfehlung: A in v1. Für echte Fensterkontakte: C mit Template-Sensor + FPS (kein JSON-Umweg nötig)
oder D (bewährtes Muster bei dir); B nur falls beides nicht passt.

---

## 11. Services

| Service | Parameter | Wirkung |
|---|---|---|
| `controme_insights.boost` | Raum, Offset K (z. B. +1), Dauer min | setzt API-Offset, erneuert ihn, nimmt ihn nach Ablauf zurück; Restzeit als Attribut am API-Offset |
| `controme_insights.set_room_offset` | Raum, Offset K | wie die Zahl-Entität, für Automationen |
| `controme_insights.clear_room_offset` | Raum (oder alle) | Offset sofort entfernen |

Nur verfügbar, wenn Schreibfunktionen freigegeben sind.

---

## 12. Diagnose-Download (Punkt 8)

Über „Diagnose herunterladen“ an der Integration: Rohantworten aller Endpunkte, erkannte Räume, Fühler,
Anbindungen, Fehlerzähler. Automatisch geschwärzt: Host, Benutzer, Passwort, MAC-/Fühler-IDs.

**Ist-Stand:** Eintrag (Titel, Host, Benutzer, Passwort geschwärzt; Optionen mit Fühler-IDs als
Platzhalter), System-Info, je Coordinator letzter Erfolg (Zeitpunkt) und letzter Fehler (ohne Host
und Zugangsdaten, auch nicht in HTML-/URL-kodierter Form) sowie die **geparsten Modelle** aller
Coordinators. Options, Info und Daten laufen in einem Aufruf durch `aiocontrome.redact()`, damit
derselbe Fühler überall denselben Platzhalter bekommt.
**Folgt mit den Entitäten:** Rohantworten über `client.get_raw()` (zeigen auch Schlüssel, die der
Parser verwirft) und Fehlerzähler.

---

## 13. Beispiel-Dashboard (Punkt 11)

Im Repo unter `examples/dashboard.yaml`:
- Raumkacheln mit Ist/Soll (offizielle Integration), Ventilöffnung, Rücklauf, Nächster Wechsel
- Systemkarte: Vorlauf je Etage, Warmwasser, Heizende Räume, Übertragungsstatus
- Verlaufsdiagramm Ventilöffnung + Rücklauf je Raum

Nur Standardkarten von HA, keine Zusatz-Karten nötig.

---

## 14. Später (nicht in v1)

- **Spreizung Vorlauf–Rücklauf je Raum** (Etagen-Zuordnung über `eg_`/`og_`/`dg_`, einstellbar)
- **Fenster Variante B** (siehe 10.)
- **Undokumentierte Schreib-Endpunkte** (Heizprogramm, Betriebsart, resettemp) – nur falls die
  offizielle Integration sie nicht mehr abdeckt
- **Interne API `/api/v1/…`** – nur falls Controme sie offiziell freigibt

---

## 15. Offene Punkte

- [x] 4-Byte-Fühler = Funkfühler (Gästeklo bestätigt)
- [x] `fps.json` und `info.json` geliefert (→ 6, 6b)
- [x] Fenster-offen-Offset geprüft (Gästeklo, 13.11.2026): −10 K, Erkennung und Rücknahme je ≤ 10 min
- [x] Variante C: NOVA-Plugin „Home Assistant“ verbunden (13.11.2026, Status grün, HA-Benutzer ohne Adminrechte)
- [ ] Bei Bedarf: prüfen, ob FPS System-Sensoren als Eingang nutzen kann (Voraussetzung Fenster-Umweg)
- [x] PyPI-Name `aiocontrome` frei (13.11.2026)
- [ ] Fühler Vorratsraum: sendet derzeit nicht (früher schon) – Batterie/Reichweite prüfen
- [x] Wohnzimmer: versehentlich abgekoppelt, wieder angekoppelt (→ neuer Binärsensor „Vom Heizprogramm abgekoppelt“)
- [x] Gateway-Typ der eigenen Anlage: FBH-Gateway PRO 0–10 V
- [x] Ein Gateway je Etage (DG, OG, EG) – bestätigt
