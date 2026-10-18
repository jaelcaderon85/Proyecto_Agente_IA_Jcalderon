import csv
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

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

# Segundos entre actualizaciones. 0 = consulta una sola vez y termina.
# También se puede pasar por consola:  python Estadistica_EnVivo.py 60
INTERVALO = 0

HILOS = 6
BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer'
SALIDA = r'G:\Mi unidad\PROYECTO_ESPN\PARTIDOS_EN_VIVO.csv'

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://www.espn.com/',
})


def get_json(url, intentos=3):
    for i in range(intentos):
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 * (i + 1))
                continue
            return None
        except requests.RequestException:
            time.sleep(2 * (i + 1))
    return None


def marcador(c):
    s = c.get('score')
    return s.get('displayValue') if isinstance(s, dict) else s


def partidos_en_vivo(codigo, nombre):
    """Partidos de la liga que están en juego ahora mismo (state == 'in')."""
    data = get_json(f'{BASE}/{codigo}/scoreboard')
    if not data:
        return []
    vivos = []
    for e in data.get('events', []):
        comp = e['competitions'][0]
        status = comp.get('status') or e.get('status') or {}
        tipo = status.get('type', {})
        if tipo.get('state') != 'in':
            continue
        comps = comp['competitors']
        local = next((c for c in comps if c.get('homeAway') == 'home'), None)
        visita = next((c for c in comps if c.get('homeAway') == 'away'), None)
        if not local or not visita:
            continue
        vivos.append({
            'codigo': codigo,
            'liga': nombre,
            'event_id': e['id'],
            'minuto': status.get('displayClock', ''),
            'periodo': status.get('period', ''),
            'estado': tipo.get('description') or tipo.get('detail') or '',
            'local_id': local['team']['id'],
            'local': local['team']['displayName'],
            'goles_local': marcador(local),
            'visita_id': visita['team']['id'],
            'visita': visita['team']['displayName'],
            'goles_visita': marcador(visita),
        })
    return vivos


def estadisticas_partido(p):
    data = get_json(f"{BASE}/{p['codigo']}/summary?event={p['event_id']}")
    if data is None:
        return {}
    por_equipo = {}
    for t in (data.get('boxscore') or {}).get('teams', []):
        por_equipo[t['team']['id']] = {
            (s.get('label') or s.get('name')): s.get('displayValue')
            for s in t.get('statistics', [])
        }
    return por_equipo


def ruta_salida():
    carpeta = os.path.dirname(SALIDA)
    try:
        os.makedirs(carpeta, exist_ok=True)
        return SALIDA
    except OSError:
        return os.path.join(os.getcwd(), os.path.basename(SALIDA))


def escribir_csv(partidos, stats):
    cols = []
    for p in partidos:
        for eq in stats.get(p['event_id'], {}).values():
            for k in eq:
                if k not in cols:
                    cols.append(k)

    encabezado = (['Actualizado', 'Liga', 'ID', 'Minuto', 'Estado', 'Local',
                   'Goles Local', 'Goles Visita', 'Visita']
                  + ['Local_' + c for c in cols] + ['Visita_' + c for c in cols])
    ahora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    destino = ruta_salida()
    try:
        with open(destino, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(encabezado)
            for p in partidos:
                st = stats.get(p['event_id'], {})
                sl = st.get(p['local_id'], {})
                sv = st.get(p['visita_id'], {})
                w.writerow(
                    [ahora, p['liga'], p['event_id'], p['minuto'], p['estado'], p['local'],
                     p['goles_local'], p['goles_visita'], p['visita']]
                    + [sl.get(c, '') for c in cols]
                    + [sv.get(c, '') for c in cols]
                )
        return destino
    except OSError as e:
        print(f'No se pudo escribir {destino}: {e} (¿archivo abierto en Excel?)')
        return None


def imprimir(partidos, stats):
    if not partidos:
        print('No hay partidos en vivo en estas ligas en este momento.')
        return
    for p in partidos:
        print(f"\n[{p['liga']}] {p['local']} {p['goles_local']} - {p['goles_visita']} "
              f"{p['visita']}  |  {p['minuto']} ({p['estado']})")
        st = stats.get(p['event_id'], {})
        sl = st.get(p['local_id'], {})
        sv = st.get(p['visita_id'], {})
        for k in sl.keys() | sv.keys():
            print(f"   {k:<28} {sl.get(k, '-'):>8}  |  {sv.get(k, '-'):<8}")


def ciclo():
    ligas = list(LIGAS.items())
    with ThreadPoolExecutor(max_workers=HILOS) as ex:
        resultados = list(ex.map(lambda x: partidos_en_vivo(*x), ligas))
    partidos = [p for lista in resultados for p in lista]

    stats = {}
    if partidos:
        with ThreadPoolExecutor(max_workers=HILOS) as ex:
            for p, st in zip(partidos, ex.map(estadisticas_partido, partidos)):
                stats[p['event_id']] = st

    print(f"\n===== {datetime.now():%H:%M:%S} · {len(partidos)} partido(s) en vivo =====")
    imprimir(partidos, stats)
    destino = escribir_csv(partidos, stats)
    if destino:
        print(f'\nCSV actualizado -> {destino}')


def main():
    intervalo = INTERVALO
    if len(sys.argv) > 1:
        try:
            intervalo = int(sys.argv[1])
        except ValueError:
            print('Uso: python Estadistica_EnVivo.py [segundos_entre_actualizaciones]')
            return

    try:
        ciclo()
        while intervalo > 0:
            time.sleep(intervalo)
            ciclo()
    except KeyboardInterrupt:
        print('\nDetenido por el usuario.')


if __name__ == '__main__':
    main()