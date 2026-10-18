import csv
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

LIGAS = {
    'col.1': 'Liga BetPlay',
    'eng.1': 'Premier League',
    'esp.1': 'LaLiga',
    'uefa.nations': 'Uefa Nationals League',
    'ger.1': 'Bundesliga Alemania',
    'ita.1': 'Italia Seria A',
    'fra.1': 'Francia Liga 1',
    'uefa.champions': 'UEFA Champions League',
    'ned.1': 'Eredivisie Paises Bajos',
    'por.1': 'Portugal Liga 1',
    'bra.1': 'Brasil Seria A',
    'usa.1': 'Usa Mls',
}

# Colombia no tiene horario de verano: UTC-5 fijo (no requiere librerías extra)
TZ_LOCAL = timezone(timedelta(hours=-5))

HILOS = 6
BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer'
SALIDA = r'G:\Mi unidad\PROYECTO_ESPN\PARTIDOS_HOY.csv'

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://www.espn.com/',
})


def get_json(url, intentos=4):
    for i in range(intentos):
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(3 * (i + 1))
                continue
            return None
        except requests.RequestException:
            time.sleep(2 * (i + 1))
    return None


def marcador(c):
    s = c.get('score')
    return s.get('displayValue') if isinstance(s, dict) else s


def a_hora_local(fecha_iso):
    # ESPN entrega fechas como 2026-10-02T23:00Z
    dt = datetime.strptime(fecha_iso, '%Y-%m-%dT%H:%MZ').replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ_LOCAL)


def partidos_liga(codigo, nombre, hoy):
    """Partidos de la liga cuya hora local (Bogotá) cae en la fecha 'hoy'."""
    partidos = {}
    # Se consultan ayer, hoy y mañana (UTC) porque un partido nocturno en Bogotá
    # puede estar registrado con otra fecha en ESPN.
    for delta in (-1, 0, 1):
        dia = hoy + timedelta(days=delta)
        data = get_json(f"{BASE}/{codigo}/scoreboard?dates={dia:%Y%m%d}")
        if not data:
            continue
        for e in data.get('events', []):
            if e['id'] in partidos:
                continue
            try:
                inicio = a_hora_local(e['date'])
            except ValueError:
                continue
            if inicio.date() != hoy:
                continue
            comp = e['competitions'][0]
            comps = comp['competitors']
            local = next((c for c in comps if c.get('homeAway') == 'home'), None)
            visita = next((c for c in comps if c.get('homeAway') == 'away'), None)
            if not local or not visita:
                continue
            status = comp.get('status') or e.get('status') or {}
            tipo = status.get('type', {})
            partidos[e['id']] = {
                'liga': nombre,
                'event_id': e['id'],
                'fecha': inicio.strftime('%Y-%m-%d'),
                'hora': inicio.strftime('%H:%M'),
                'estado': tipo.get('description', ''),
                'local': local['team']['displayName'],
                'goles_local': marcador(local) if tipo.get('state') != 'pre' else '',
                'goles_visita': marcador(visita) if tipo.get('state') != 'pre' else '',
                'visita': visita['team']['displayName'],
                'estadio': (comp.get('venue') or {}).get('fullName', ''),
            }
    return list(partidos.values())


def ruta_salida():
    carpeta = os.path.dirname(SALIDA)
    try:
        os.makedirs(carpeta, exist_ok=True)
        return SALIDA
    except OSError as e:
        alterna = os.path.join(os.getcwd(), os.path.basename(SALIDA))
        print(f'No se pudo usar {carpeta} ({e}). Se guardará en {alterna}')
        return alterna


def main():
    hoy = datetime.now(TZ_LOCAL).date()
    print(f'Buscando partidos del {hoy} (hora Bogotá)...', flush=True)

    ligas = list(LIGAS.items())
    with ThreadPoolExecutor(max_workers=HILOS) as ex:
        resultados = list(ex.map(lambda x: partidos_liga(x[0], x[1], hoy), ligas))

    todos = [p for lista in resultados for p in lista]
    todos.sort(key=lambda p: (p['hora'], p['liga']))

    destino = ruta_salida()
    with open(destino, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['Liga', 'ID', 'Fecha', 'Hora', 'Estado', 'Local',
                    'Goles Local', 'Goles Visita', 'Visita', 'Estadio'])
        for p in todos:
            w.writerow([p['liga'], p['event_id'], p['fecha'], p['hora'], p['estado'],
                        p['local'], p['goles_local'], p['goles_visita'], p['visita'],
                        p['estadio']])

    for p in todos:
        print(f"{p['hora']}  [{p['liga']}] {p['local']} vs {p['visita']}  ({p['estado']})")
    print(f'\nListo: {len(todos)} partidos hoy -> {destino}')


if __name__ == '__main__':
    main()
