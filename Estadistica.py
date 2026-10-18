import csv
import json
import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor

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
# Año en que EMPIEZA la temporada: 2026 = 2026-27 (actual), 2025 = 2025-26 (pasada)
TEMPORADAS = [2026, 2025]

# Si ESPN empieza a responder 429, baja estos números
HILOS_CALENDARIO = 6
HILOS_ESTADISTICAS = 5

BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer'
SALIDA = r'G:\Mi unidad\PROYECTO_ESPN\PROYECTO_ESPN.csv'
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cache_espn.json')

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
                espera = 3 * (i + 1)
                print(f'  {r.status_code}, reintento en {espera}s ...{url[-60:]}', flush=True)
                time.sleep(espera)
                continue
            print(f'  {r.status_code} en ...{url[-70:]}', flush=True)
            return None
        except requests.RequestException as e:
            print(f'  error de red: {e}', flush=True)
            time.sleep(2 * (i + 1))
    return None


def marcador(c):
    s = c.get('score')
    return s.get('displayValue') if isinstance(s, dict) else s


def cargar_cache():
    if os.path.exists(CACHE):
        try:
            with open(CACHE, encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            print('Caché ilegible; se empieza de cero.')
    return {}


def guardar_cache(cache):
    with open(CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache, f)


def equipos_liga(liga, temporada):
    data = get_json(f'{BASE}/{liga}/teams?limit=100&season={temporada}')
    if not data:
        data = get_json(f'{BASE}/{liga}/teams?limit=100')
    if not data:
        raise RuntimeError(f'No se pudieron traer los equipos de {liga}')
    teams = data['sports'][0]['leagues'][0]['teams']
    return [{'id': t['team']['id'], 'nombre': t['team']['displayName']} for t in teams]


def partidos_temporada(liga, temporada, equipos):
    """Todos los partidos finalizados de la liga en la temporada, sin duplicados."""
    def calendario(eq):
        return get_json(f"{BASE}/{liga}/teams/{eq['id']}/schedule?season={temporada}")

    with ThreadPoolExecutor(max_workers=HILOS_CALENDARIO) as ex:
        respuestas = list(ex.map(calendario, equipos))

    partidos = {}
    for data in respuestas:
        if not data:
            continue
        for e in data.get('events', []):
            if e['id'] in partidos:
                continue
            comp = e['competitions'][0]
            st = (comp.get('status') or e.get('status') or {}).get('type', {})
            if st.get('state') != 'post':
                continue
            comps = comp['competitors']
            local = next((c for c in comps if c.get('homeAway') == 'home'), None)
            visita = next((c for c in comps if c.get('homeAway') == 'away'), None)
            if not local or not visita:
                continue
            partidos[e['id']] = {
                'liga': liga,
                'temporada': temporada,
                'event_id': e['id'],
                'fecha': e['date'],
                'local_id': local['team']['id'],
                'local': local['team']['displayName'],
                'goles_local': marcador(local),
                'visita_id': visita['team']['id'],
                'visita': visita['team']['displayName'],
                'goles_visita': marcador(visita),
            }
    return list(partidos.values())


def estadisticas_partido(liga, event_id):
    data = get_json(f'{BASE}/{liga}/summary?event={event_id}')
    if data is None:
        return None  # falló la llamada: no se guarda en caché para reintentar después
    por_equipo = {}
    for t in (data.get('boxscore') or {}).get('teams', []):
        por_equipo[t['team']['id']] = {
            (s.get('label') or s.get('name')): s.get('displayValue')
            for s in t.get('statistics', [])
        }
    return por_equipo


def ruta_salida():
    """Crea la carpeta de Drive si hace falta; si Drive no está disponible, guarda en la carpeta actual."""
    carpeta = os.path.dirname(SALIDA)
    try:
        os.makedirs(carpeta, exist_ok=True)
        return SALIDA
    except OSError as e:
        alterna = os.path.join(os.getcwd(), os.path.basename(SALIDA))
        print(f'No se pudo usar {carpeta} ({e}). Se guardará en {alterna}')
        return alterna


def escribir_csv(todos, cache):
    if not todos:
        print('No hay partidos para escribir; no se crea el archivo.')
        return

    # Todas las estadísticas encontradas, en orden de aparición
    cols = []
    for p in todos:
        for eq in cache.get(p['event_id'], {}).values():
            for k in eq:
                if k not in cols:
                    cols.append(k)

    encabezado = (['Liga', 'Temporada', 'ID', 'Fecha', 'Local', 'Goles Local',
                   'Goles Visita', 'Visita']
                  + ['Local_' + c for c in cols] + ['Visita_' + c for c in cols])

    # Orden: liga A-Z, temporada más reciente primero, fecha más reciente primero
    todos.sort(key=lambda p: p['fecha'], reverse=True)
    todos.sort(key=lambda p: p['temporada'], reverse=True)
    todos.sort(key=lambda p: p['liga_nombre'])

    destino = ruta_salida()
    with open(destino, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(encabezado)
        for p in todos:
            st = cache.get(p['event_id'], {})
            sl = st.get(p['local_id'], {})
            sv = st.get(p['visita_id'], {})
            w.writerow(
                [p['liga_nombre'], p['temporada'], p['event_id'], p['fecha'], p['local'],
                 p['goles_local'], p['goles_visita'], p['visita']]
                + [sl.get(c, '') for c in cols]
                + [sv.get(c, '') for c in cols]
            )
    print(f'Listo: {len(todos)} partidos, {len(encabezado)} columnas -> {destino}')


def main():
    cache = cargar_cache()   # cache[event_id] = {team_id: {estadística: valor}}
    todos = []
    vistos = set()

    try:
        for codigo, nombre in LIGAS.items():
            for temporada in TEMPORADAS:
                try:
                    equipos = equipos_liga(codigo, temporada)
                    partidos = partidos_temporada(codigo, temporada, equipos)
                    partidos = [p for p in partidos if p['event_id'] not in vistos]

                    pendientes = [p for p in partidos if p['event_id'] not in cache]
                    print(f'{nombre} {temporada}: {len(partidos)} partidos '
                          f'({len(pendientes)} por descargar)', flush=True)

                    if pendientes:
                        with ThreadPoolExecutor(max_workers=HILOS_ESTADISTICAS) as ex:
                            resultados = list(ex.map(
                                lambda p: estadisticas_partido(codigo, p['event_id']), pendientes))
                        for p, st in zip(pendientes, resultados):
                            if st is not None:
                                cache[p['event_id']] = st
                        guardar_cache(cache)

                    for p in partidos:
                        p['liga_nombre'] = nombre
                        vistos.add(p['event_id'])
                        todos.append(p)
                except Exception as err:
                    print(f'Error en {codigo} {temporada}: {err}', flush=True)
    except KeyboardInterrupt:
        print('Detenido por el usuario; se escribe lo descargado hasta ahora.')
    finally:
        guardar_cache(cache)
        escribir_csv(todos, cache)


if __name__ == '__main__':
    main()