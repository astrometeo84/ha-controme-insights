# Controme Insights – Projektregeln für Claude Code

Home-Assistant-Integration (Domain `controme_insights`), die die **offizielle Controme-Integration
ergänzt**: Ventilstellungen, Rücklauf, Offsets je Quelle, nächster Wechsel, Smart Timing, FPS,
System-Fühler, Übertragungsüberwachung, API-Offset/Boost. Nutzt die Bibliothek `aiocontrome`.
Lizenz: GPL-3.0. **Die verbindliche Spezifikation ist `docs/ENTWURF.md`.**

## Sprache
- Mit dem Nutzer: **Deutsch**.
- Code, Kommentare, README, Commits, PRs: **Englisch**. Übersetzungen: `en.json` und `de.json`.

## Sicherheitsregeln (nicht verhandelbar)
1. **Niemals echte Geräte ansprechen** (Controme, Home Assistant, sonstiges im Heimnetz).
   Tests nur mit `tests/fixtures/` und Mocks. Live-Tests macht der Nutzer auf seinem Test-HA.
2. **Keine Zugangsdaten** anlegen, erfragen oder speichern. Details: Skill `security-secrets`.
3. **Keine echten Kennungen ins Repo** (Namen, MACs, Fühler-IDs, IPs) – nur pseudonymisiert.
4. **GitHub:** nur Feature-Branches, Pushes nach Rückfrage, PRs mit `ghb pr create`;
   nie `main`, nie Force-Push, nie Tags/Releases, `.github/workflows/` nicht ändern.
5. **Nichts aus dem Code der offiziellen Controme-Integration übernehmen** (keine Lizenz).
   Wir kennen nur deren Geräte-Kennung `("controme", "room_<ID>")` – das ist eine Schnittstelle,
   kein Code.
6. **Keine Funktionen nachbauen, die die offizielle Integration abdeckt** (Raum-Klima, Szenen-Auswahl,
   Heizprogramm, Betriebsart).

## Architektur (Kurzfassung, Details in docs/ENTWURF.md)
- Alle Controme-Logik (Parsen, Ausgangstyp, Fühler-Anbindung, Veraltung) gehört in `aiocontrome`,
  nicht hierher. Fehlt dort etwas: im Bibliotheks-Repo ergänzen, nicht hier nachbauen.
- `DataUpdateCoordinator` je Datenquelle mit eigenem Intervall (outs/temps/room_details 60 s,
  upcomingoffsets/fps 5 min, info beim Start). Fällt `room_details` aus, laufen die anderen weiter.
- `entry.runtime_data`, `has_entity_name = True`, `translation_key` für alle Namen.
- Unique IDs: `{haus}_{etage}_{raum}_{schlüssel}` (flame4ever-kompatibel), Ausgänge
  `{haus}_{etage}_{raum}_valve_{ausgang}`.
- Raum-Entitäten an Geräte mit `identifiers={("controme", f"room_{id}")}` hängen (Gerät der
  offiziellen Integration); existiert es nicht, eigenes Gerät mit eigener Kennung anlegen.
- **Entitäts-IDs dürfen nicht mit `controme_` beginnen** (NOVA-Plugin blendet `sensor.controme_*`
  aus). Haus-Gerät heißt „Heizung“, Gateways „Gateway <Etage>“.
- Config Flow + Options Flow wie in `docs/ENTWURF.md` Abschnitt 4 (Räume, System-Fühler,
  Gateways je Etage mit Typ, Schreibfunktionen).
- Diagnose-Download mit Schwärzung, Hinweise im Reparaturbereich, Services nur bei freigegebenen
  Schreibfunktionen.

## Qualität
- Tests mit `pytest-homeassistant-custom-component` (passend zur HA-Version des Nutzers), Config Flow
  vollständig getestet, Ziel ≥ 90 % Abdeckung.
- `ruff`, `mypy`; keine blockierenden Aufrufe im Event-Loop.
- HA-Qualitätsstufen (Integration Quality Scale) als Leitlinie, mind. Bronze/Silber.
- Skill `ha-integration-dev` beachten.

## Befehle
```bash
uv sync --all-extras
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy custom_components
```

## Arbeitsweise
- Vor größeren Schritten Plan zeigen, auf Freigabe warten.
- Spezifikation ändern nur nach Rückfrage; Abweichungen in `docs/ENTWURF.md` nachziehen.
- Während der Entwicklung `aiocontrome` als lokale Pfad-Abhängigkeit (`../aiocontrome`) nutzen;
  vor einem Release die PyPI-Version eintragen.
- Vor jedem Push die Subagents `test-manager` und – bei Bezug zu Endpunkten, Parsern, Modellen,
  Schreibaufrufen oder Unique IDs – `api-expert` aufrufen. Befunde unter BLOCKIERT beheben,
  die Berichte im PR-Text kurz zusammenfassen.
- Gegenproben (läuft der Test ohne den Fix rot?) mit `git stash` oder `git worktree`,
  nie mit `git checkout --` oder `git restore`.
