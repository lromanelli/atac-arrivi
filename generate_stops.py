#!/usr/bin/env python3
"""
Genera data/stops/{stop_id}.json dal GTFS statico ATAC Roma.

Ogni file contiene le partenze programmate per il giorno corrente
in formato compatto: { date, name, deps: [[route, "HH:MM", headsign], ...] }
"""

import zipfile
import json
import csv
import os
import io
from datetime import datetime, timezone, timedelta

# Roma è UTC+1 in inverno, UTC+2 in estate. Usiamo +2 come approssimazione
# (lo scarto di un'ora non impatta sul giorno di calendario usato per filtrare)
ROME_TZ = timezone(timedelta(hours=2))


def time_to_secs(t: str) -> int:
    """Converte 'HH:MM:SS' (anche con H>23 per corse notturne) in secondi."""
    parts = t.strip().split(':')
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2] if len(parts) > 2 else 0)


def main():
    now_rome = datetime.now(ROME_TZ)
    today = now_rome.strftime('%Y%m%d')
    dow = now_rome.weekday()  # 0 = lunedì
    dow_fields = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

    print(f"=== Generazione orari per {today} ({dow_fields[dow]}) ===")

    with zipfile.ZipFile('gtfs.zip', 'r') as z:
        all_files = z.namelist()
        print(f"File nel GTFS: {', '.join(sorted(all_files))}\n")

        # ── 1. Servizi attivi oggi ────────────────────────────────────────
        active_services: set[str] = set()

        with z.open('calendar.txt') as f:
            for row in csv.DictReader(io.TextIOWrapper(f, 'utf-8-sig')):
                if row['start_date'] <= today <= row['end_date']:
                    if row.get(dow_fields[dow], '0') == '1':
                        active_services.add(row['service_id'])

        if 'calendar_dates.txt' in all_files:
            with z.open('calendar_dates.txt') as f:
                for row in csv.DictReader(io.TextIOWrapper(f, 'utf-8-sig')):
                    if row['date'] == today:
                        if row['exception_type'] == '1':
                            active_services.add(row['service_id'])
                        elif row['exception_type'] == '2':
                            active_services.discard(row['service_id'])

        print(f"Servizi attivi: {len(active_services)}")

        # ── 2. Route short names ──────────────────────────────────────────
        route_name: dict[str, str] = {}
        with z.open('routes.txt') as f:
            for row in csv.DictReader(io.TextIOWrapper(f, 'utf-8-sig')):
                route_name[row['route_id']] = (
                    row.get('route_short_name') or row.get('route_long_name') or row['route_id']
                )

        # ── 3. Trip → (route_short_name, headsign) per servizi attivi ────
        trip_info: dict[str, tuple[str, str]] = {}
        with z.open('trips.txt') as f:
            for row in csv.DictReader(io.TextIOWrapper(f, 'utf-8-sig')):
                if row['service_id'] in active_services:
                    rname = route_name.get(row['route_id'], row['route_id'])
                    head = row.get('trip_headsign', '')
                    trip_info[row['trip_id']] = (rname, head)

        print(f"Trip attivi: {len(trip_info)}")

        # ── 4. Stop names ─────────────────────────────────────────────────
        stop_name: dict[str, str] = {}
        with z.open('stops.txt') as f:
            for row in csv.DictReader(io.TextIOWrapper(f, 'utf-8-sig')):
                stop_name[row['stop_id']] = row.get('stop_name', '')

        print(f"Fermate nel GTFS: {len(stop_name)}")

        # ── 5. Stop times → accumula per fermata ─────────────────────────
        # Formato interno: (secondi_dalla_mezzanotte, route_name, "HH:MM", headsign)
        stops: dict[str, list] = {}
        processed = 0

        with z.open('stop_times.txt') as f:
            for row in csv.DictReader(io.TextIOWrapper(f, 'utf-8-sig')):
                tid = row['trip_id']
                if tid not in trip_info:
                    continue
                rname, head = trip_info[tid]
                dep = row.get('departure_time') or row.get('arrival_time', '')
                if not dep or ':' not in dep:
                    continue
                dep_clean = dep.strip()
                secs = time_to_secs(dep_clean)
                sid = row['stop_id']
                if sid not in stops:
                    stops[sid] = []
                # Salva HH:MM (i secondi servono solo per l'ordinamento)
                hhmm = dep_clean[:5]
                stops[sid].append((secs, rname, hhmm, head))
                processed += 1
                if processed % 1_000_000 == 0:
                    print(f"  {processed:,} stop_times elaborati...")

    print(f"\nStop_times totali: {processed:,} per {len(stops)} fermate")

    # ── 6. Scrivi JSON per fermata ────────────────────────────────────────
    os.makedirs('data/stops', exist_ok=True)

    for sid, deps in stops.items():
        deps.sort()  # ordina per secondi dalla mezzanotte
        out = {
            'date': today,
            'name': stop_name.get(sid, ''),
            'deps': [[r, t, h] for (_, r, t, h) in deps]
        }
        with open(f'data/stops/{sid}.json', 'w', encoding='utf-8') as fp:
            json.dump(out, fp, ensure_ascii=False, separators=(',', ':'))

    # ── 7. Metadata ───────────────────────────────────────────────────────
    meta = {
        'generated': now_rome.isoformat(),
        'date': today,
        'stops_count': len(stops),
        'trips_count': len(trip_info),
    }
    with open('data/meta.json', 'w', encoding='utf-8') as fp:
        json.dump(meta, fp, separators=(',', ':'))

    print(f"\n✓ Generati {len(stops)} file JSON in data/stops/")
    print(f"✓ Metadata scritto in data/meta.json")


if __name__ == '__main__':
    main()
