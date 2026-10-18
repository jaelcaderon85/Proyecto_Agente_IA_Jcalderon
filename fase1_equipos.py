"""Fase 1: prepara la configuracion y la tabla de equivalencia de nombres de equipos.

Uso (desde la carpeta del proyecto):
    python fase1_equipos.py ruta/al/PROYECTO_ESPN.csv

Crea o actualiza en config/:
  ligas.csv                  ligas encontradas en ESPN (tu completas codigos y activas)
  equipos_espn.csv           equipos de ESPN con su numero de partidos
  equivalencias_equipos.csv  emparejamiento de nombres entre ESPN, 1xBet y Zcode

Para emparejar 1xBet y Zcode, deja config/equipos_1xbet.csv y/o config/equipos_zcode.csv
con una columna "equipo". Las filas que marques confirmado = si no se vuelven a tocar.
"""
import argparse
import csv
import io
import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

CONFIG = Path("config")
UMBRAL = 0.80  # desde este puntaje un emparejamiento se considera seguro
RUIDO = {"fc", "cf", "sc", "ac", "as", "afc", "cd", "ud", "fk", "sk", "club", "the"}
FUENTES = ("1xbet", "zcode")
CAMPOS_EQUIV = [
    "liga", "equipo_espn",
    "equipo_1xbet", "puntaje_1xbet",
    "equipo_zcode", "puntaje_zcode",
    "revisar", "confirmado",
]


def leer_csv(ruta):
    for codificacion in ("utf-8-sig", "cp1252"):
        try:
            with open(ruta, newline="", encoding=codificacion) as f:
                texto = f.read()
        except UnicodeDecodeError:
            continue
        primera = texto.split("\n", 1)[0]
        delimitador = max(",\t;", key=primera.count)  # coma, tabulacion o punto y coma
        return list(csv.DictReader(io.StringIO(texto, newline=""), delimiter=delimitador))
    raise SystemExit(f"No pude leer {ruta}: codificacion desconocida")


def escribir_csv(ruta, campos, filas):
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=campos, restval="", extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)


def normalizar(nombre):
    t = unicodedata.normalize("NFKD", nombre)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    palabras = re.findall(r"[a-z0-9]+", t)
    return " ".join(p for p in palabras if p not in RUIDO) or " ".join(palabras)


def puntaje(a, b):
    na, nb = normalizar(a), normalizar(b)
    if not na or not nb:
        return 0.0
    base = SequenceMatcher(None, na, nb).ratio()
    if na in nb or nb in na:
        # un nombre dentro de otro ("Inter" / "Inter Miami") se deja bajo el umbral: lo revisas tu
        base = max(base, 0.75)
    return round(base, 2)


def mejor(nombre, candidatos):
    if not candidatos:
        return "", 0.0
    return max(((c, puntaje(nombre, c)) for c in candidatos), key=lambda x: x[1])


def actualizar_ligas(ligas):
    ruta = CONFIG / "ligas.csv"
    campos = ["liga_espn", "codigo_espn", "id_1xbet", "nombre_zcode",
              "activa", "partidos", "desde", "hasta"]
    filas = {r["liga_espn"]: r for r in leer_csv(ruta)} if ruta.exists() else {}
    for liga, d in sorted(ligas.items()):
        fila = filas.setdefault(liga, {"liga_espn": liga, "activa": "si"})
        fila.update(partidos=d["partidos"], desde=d["desde"], hasta=d["hasta"])
    escribir_csv(ruta, campos, filas.values())
    return ruta


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("csv_espn", help="CSV de estadisticas de ESPN")
    args = ap.parse_args()

    CONFIG.mkdir(exist_ok=True)
    filas = leer_csv(args.csv_espn)
    if not filas:
        raise SystemExit("El CSV de ESPN esta vacio.")
    faltan = {"Liga", "Fecha", "Local", "Visita", "ID"} - set(filas[0])
    if faltan:
        raise SystemExit(f"Faltan columnas en el CSV de ESPN: {sorted(faltan)}")

    ligas = defaultdict(lambda: {"partidos": 0, "desde": "", "hasta": ""})
    equipos = defaultdict(int)
    vistos, duplicados = set(), 0
    for r in filas:
        if r["ID"] in vistos:
            duplicados += 1
            continue
        vistos.add(r["ID"])
        liga, fecha = r["Liga"].strip(), r["Fecha"][:10]  # la fecha de ESPN viene en UTC
        d = ligas[liga]
        d["partidos"] += 1
        d["desde"] = min(d["desde"] or fecha, fecha)
        d["hasta"] = max(d["hasta"], fecha)
        for lado in ("Local", "Visita"):
            equipos[(liga, r[lado].strip())] += 1

    ruta_ligas = actualizar_ligas(ligas)
    escribir_csv(
        CONFIG / "equipos_espn.csv", ["liga", "equipo", "partidos"],
        [{"liga": l, "equipo": e, "partidos": n} for (l, e), n in sorted(equipos.items())],
    )

    fuentes = {}
    for nombre in FUENTES:
        ruta = CONFIG / f"equipos_{nombre}.csv"
        if ruta.exists():
            fuentes[nombre] = sorted({
                r["equipo"].strip() for r in leer_csv(ruta) if r.get("equipo", "").strip()
            })

    ruta_eq = CONFIG / "equivalencias_equipos.csv"
    previas = {}
    if ruta_eq.exists():
        previas = {(r["liga"], r["equipo_espn"]): r for r in leer_csv(ruta_eq)}

    # config/correcciones_1xbet.csv (liga, equipo_espn, equipo_1xbet): tiene prioridad.
    # Si equipo_1xbet va vacio, significa "sin equivalente por ahora".
    ruta_corr = CONFIG / "correcciones_1xbet.csv"
    correcciones = {}
    if ruta_corr.exists():
        correcciones = {
            (r["liga"].strip(), r["equipo_espn"].strip()): (r.get("equipo_1xbet") or "").strip()
            for r in leer_csv(ruta_corr)
        }

    salida = []
    for (liga, equipo) in sorted(equipos):
        if (liga, equipo) in correcciones:
            nombre_1x = correcciones[(liga, equipo)]
            salida.append({
                "liga": liga, "equipo_espn": equipo,
                "equipo_1xbet": nombre_1x, "puntaje_1xbet": 1.0 if nombre_1x else "",
                "revisar": "no", "confirmado": "si",
            })
            continue
        previa = previas.get((liga, equipo))
        if previa and previa.get("confirmado") == "si":
            salida.append(previa)
            continue
        fila = {"liga": liga, "equipo_espn": equipo, "confirmado": "no"}
        dudoso = not fuentes
        for nombre, candidatos in fuentes.items():
            elegido, p = mejor(equipo, candidatos)
            fila[f"equipo_{nombre}"], fila[f"puntaje_{nombre}"] = elegido, p
            dudoso = dudoso or p < UMBRAL
        fila["revisar"] = "si" if dudoso else "no"
        salida.append(fila)
    escribir_csv(ruta_eq, CAMPOS_EQUIV, salida)

    pendientes = sum(1 for f in salida if f["revisar"] == "si")
    print(f"Partidos unicos: {len(vistos)} (duplicados ignorados: {duplicados})")
    print(f"Ligas: {len(ligas)} -> {ruta_ligas}")
    print(f"Equipos: {len(equipos)}")
    if not fuentes:
        print("Aun no hay config/equipos_1xbet.csv ni config/equipos_zcode.csv: "
              "todas las filas quedan por revisar.")
    print(f"Equivalencias por revisar: {pendientes} de {len(salida)} -> {ruta_eq}")


if __name__ == "__main__":
    main()
