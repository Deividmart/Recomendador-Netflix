"""
Descarga de TMDB (themoviedb.org) el póster, el título y la sinopsis en español latino de cada
película del catálogo, y un fondo horizontal sin texto para las más populares (billboard).
Resultado: datos/tmdb/meta.json, datos/tmdb/img/<movieId>.jpg y datos/tmdb/fondo/<movieId>.jpg

La clave de API se lee de la variable TMDB_API_KEY o del archivo datos/.tmdb_key.
Uso:  py descargar_tmdb.py
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from recomendador import cargar_peliculas, cargar_ratings

DATOS = Path(__file__).parent / "datos"
SALIDA = DATOS / "tmdb"
API = "https://api.themoviedb.org/3"
IMAGENES = "https://image.tmdb.org/t/p"
FONDOS_TOP = 400            # fondos horizontales solo para las más populares
CLAVE = os.environ.get("TMDB_API_KEY") or (DATOS / ".tmdb_key").read_text().strip()


def pedir(url, crudo=False):
    for intento in range(6):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                contenido = r.read()
            return contenido if crudo else json.loads(contenido)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(int(e.headers.get("Retry-After") or 0) or 1 + 2 * intento)
        except Exception:
            time.sleep(1 + 2 * intento)
    return None


def ficha(tmdb_id, idioma):
    q = urllib.parse.urlencode({"api_key": CLAVE, "language": idioma, "append_to_response": "images",
                                "include_image_language": "null,es,en"})
    return pedir(f"{API}/movie/{tmdb_id}?{q}")


def por_imdb(imdb):
    """Para ids de TMDB rotos o series de TV que MovieLens trata como películas."""
    q = urllib.parse.urlencode({"api_key": CLAVE, "external_source": "imdb_id", "language": "es-MX"})
    return pedir(f"{API}/find/{imdb}?{q}") or {}


def procesar(item):
    i, peli, con_fondo = item
    d = ficha(peli["tmdb"], "es-MX") if peli["tmdb"] else None
    if not d or not d.get("poster_path"):
        hallado = por_imdb(peli["imdb"])
        if hallado.get("movie_results"):
            peli = {**peli, "tmdb": str(hallado["movie_results"][0]["id"])}
            d = ficha(peli["tmdb"], "es-MX")
        elif hallado.get("tv_results") or hallado.get("tv_episode_results"):
            tv = (hallado.get("tv_results") or hallado.get("tv_episode_results"))[0]
            m = {"es": tv.get("name")}
            if tv.get("overview"):
                m["sinopsis"] = recortar(tv["overview"])
            ruta = tv.get("poster_path") or tv.get("still_path")
            if ruta:
                guardar(f"{IMAGENES}/w342{ruta}", SALIDA / "img" / f"{i}.jpg")
                m["img"] = True
            return i, m
    if not d:
        return i, {}
    m = {"es": d.get("title")}
    sinopsis = d.get("overview")
    if not sinopsis:                                     # sin sinopsis latina: España y luego inglés
        for idioma in ("es-ES", "en-US"):
            otra = ficha(peli["tmdb"], idioma)
            if otra and otra.get("overview"):
                sinopsis = otra["overview"]
                break
    if sinopsis:
        m["sinopsis"] = recortar(sinopsis)
    if d.get("poster_path"):
        guardar(f"{IMAGENES}/w342{d['poster_path']}", SALIDA / "img" / f"{i}.jpg")
        m["img"] = True
    if con_fondo:
        # el fondo oficial; si no hay, el fondo sin texto mejor votado y en alta resolución
        sin_texto = sorted((b for b in (d.get("images") or {}).get("backdrops", [])
                            if b.get("iso_639_1") is None and b.get("width", 0) >= 1280),
                           key=lambda b: -b.get("vote_average", 0))
        ruta = d.get("backdrop_path") or (sin_texto[0]["file_path"] if sin_texto else None)
        if ruta:
            guardar(f"{IMAGENES}/w780{ruta}", SALIDA / "fondo" / f"{i}.jpg")
            m["fondo"] = True
    return i, m


def guardar(url, destino):
    if not destino.exists():
        contenido = pedir(url, crudo=True)
        if contenido:
            destino.write_bytes(contenido)


def recortar(txt, maximo=340):
    if len(txt) <= maximo:
        return txt
    corte = txt[:maximo].rsplit(". ", 1)[0]
    return corte + "." if len(corte) > 120 else txt[:maximo].rsplit(" ", 1)[0] + "…"


def main():
    for carpeta in ("img", "fondo"):
        (SALIDA / carpeta).mkdir(parents=True, exist_ok=True)
    peliculas = cargar_peliculas()
    vistas = {}
    for calificadas in cargar_ratings().values():
        for i in calificadas:
            vistas[i] = vistas.get(i, 0) + 1
    orden = sorted(range(len(peliculas)), key=lambda i: -vistas.get(i, 0))
    archivo = SALIDA / "meta.json"
    meta = json.loads(archivo.read_text(encoding="utf-8")) if archivo.exists() else {}

    # archivos y fichas se guardan por movieId de MovieLens: no dependen del filtro de calificaciones
    pendientes = [(peliculas[i]["id"], peliculas[i], pos < FONDOS_TOP)
                  for pos, i in enumerate(orden) if peliculas[i]["id"] not in meta]
    print(f"Pendientes: {len(pendientes)} de {len(peliculas)}")
    with ThreadPoolExecutor(8) as ex:
        for n, (i, m) in enumerate(ex.map(procesar, pendientes), 1):
            meta[i] = m
            if n % 200 == 0:
                archivo.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
                print(f"  {n}/{len(pendientes)}")
    archivo.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    print(f"Listo: {sum(bool(m.get('img')) for m in meta.values())} pósters, "
          f"{sum(bool(m.get('fondo')) for m in meta.values())} fondos, "
          f"{sum(bool(m.get('sinopsis')) for m in meta.values())} sinopsis de {len(peliculas)} películas")


if __name__ == "__main__":
    main()
