"""
Descarga pósters, títulos en español y sinopsis de Wikipedia para las películas del catálogo.
Resultado (con caché por etapa, se puede volver a correr): datos/arte/meta.json y datos/arte/img/<id>.*

Ruta: IMDb id (links.csv de MovieLens) -> Wikidata -> artículos en/es
      -> resumen REST de Wikipedia: póster (inglés) y sinopsis (español si existe).
Uso:  py descargar_posters.py [segundos máximos]
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from recomendador import cargar_peliculas, cargar_ratings

BASE = Path(__file__).parent / "datos"
SALIDA = BASE / "arte"
IMG = SALIDA / "img"
UA = {"User-Agent": "VecinosDeCine/1.0 (proyecto academico de Estructuras de Datos)"}


def pedir(url, params=None, data=None, crudo=False):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    body = urllib.parse.urlencode(data).encode() if data else None
    for intento in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=UA), timeout=60) as r:
                contenido = r.read()
            time.sleep(0.4)                     # ritmo amable con los servidores de Wikimedia
            return contenido if crudo else json.loads(contenido)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            espera = e.headers.get("Retry-After")
            time.sleep(int(espera) if espera and espera.isdigit() else 4 + 6 * intento)
        except Exception:
            time.sleep(3 + 4 * intento)
    return None


def cache(nombre, calcular):
    archivo = SALIDA / nombre
    if archivo.exists():
        return {int(k): v for k, v in json.loads(archivo.read_text(encoding="utf-8")).items()}
    datos = calcular()
    archivo.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return datos


# ------------------------------------------------------------------ 2. artículos en/es
def articulos_imdb(ids):
    print(f"IMDb ids: {len(ids)}")
    por_imdb = {v: k for k, v in ids.items()}
    res, lista = {}, list(por_imdb)
    for k in range(0, len(lista), 250):
        valores = " ".join(f'"{x}"' for x in lista[k:k + 250])
        q = f"""SELECT ?imdb ?en ?es WHERE {{ VALUES ?imdb {{ {valores} }} ?item wdt:P345 ?imdb .
          OPTIONAL {{ ?en schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }}
          OPTIONAL {{ ?es schema:about ?item ; schema:isPartOf <https://es.wikipedia.org/> . }} }}"""
        d = pedir("https://query.wikidata.org/sparql", data={"query": q, "format": "json"})
        for b in d["results"]["bindings"]:
            i = por_imdb[b["imdb"]["value"]]
            res.setdefault(i, {})
            for lang in ("en", "es"):
                if lang in b:
                    res[i][lang] = urllib.parse.unquote(b[lang]["value"].split("/wiki/", 1)[1]).replace("_", " ")
    return res


# ------------------------------------------------------------------ 3. resúmenes REST
def resumen(lang, titulo):
    t = urllib.parse.quote(titulo.replace(" ", "_"), safe="")
    return pedir(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{t}")


def resumenes(arts, meta, orden, limite_seg, top_es=700):
    """De a una petición y en orden de popularidad; guarda cada 25 películas para poder cortar cuando sea."""
    archivo = SALIDA / "meta.json"
    pendientes = [i for i in orden if i in arts and i not in meta]
    print(f"Resúmenes pendientes: {len(pendientes)}")
    inicio, rank = time.time(), {i: n for n, i in enumerate(orden)}
    for n, i in enumerate(pendientes, 1):
        if time.time() - inicio > limite_seg:
            print(f"  pausa en {n - 1}/{len(pendientes)} (se retoma en la siguiente corrida)")
            break
        a, m = arts[i], {}
        en = resumen("en", a["en"]) if a.get("en") else None
        img = (en or {}).get("originalimage") or (en or {}).get("thumbnail")
        if img and img.get("width", 0) > 500:
            img = en.get("thumbnail")
        if img:
            m["img"] = img["source"]
            descargar((i, img["source"]))
        es = resumen("es", a["es"]) if a.get("es") and rank[i] < top_es else None
        if es and es.get("type") == "standard" and es.get("extract"):
            m["sinopsis"] = recortar(es["extract"])
        elif en and en.get("extract"):
            m["sinopsis"] = recortar(en["extract"])
            m["sinopsis_en"] = True
        if a.get("es"):
            m["es"] = titulo_es(a["es"])
        meta[i] = m
        if n % 25 == 0:
            archivo.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            print(f"  resúmenes {n}/{len(pendientes)}")
    archivo.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta


def recortar(txt, maximo=330):
    txt = re.sub(r"\s*\([^()]*\)", "", txt.split("\n")[0]).strip()
    if len(txt) <= maximo:
        return txt
    out = ""
    for f in re.split(r"(?<=[.!?])\s+", txt):
        if len(out) + len(f) > maximo and out:
            break
        out += (" " if out else "") + f
    return out if len(out) <= maximo + 80 else out[:maximo].rsplit(" ", 1)[0] + "…"


def titulo_es(t):
    return re.sub(r"\s*\((película|film|filme)[^)]*\)$", "", t).strip()


# ------------------------------------------------------------------ 4. imágenes
def descargar(item):
    i, url = item
    ext = Path(urllib.parse.urlparse(url).path).suffix.lower() or ".jpg"
    destino = IMG / f"{i}{ext}"
    if destino.exists():
        return True
    contenido = pedir(url, crudo=True)
    if contenido:
        destino.write_bytes(contenido)
    return bool(contenido)


def main():
    SALIDA.mkdir(exist_ok=True)
    IMG.mkdir(exist_ok=True)
    peliculas = cargar_peliculas()
    vistas = {i: len(v) for i, v in _por_pelicula(cargar_ratings()).items()}
    orden = sorted(range(len(peliculas)), key=lambda i: -vistas.get(i, 0))

    arts = cache("articulos.json", lambda: articulos_imdb({i: p["imdb"] for i, p in enumerate(peliculas)}))
    archivo_meta = SALIDA / "meta.json"
    meta = ({int(k): v for k, v in json.loads(archivo_meta.read_text(encoding="utf-8")).items()}
            if archivo_meta.exists() else {})
    meta = resumenes(arts, meta, orden, limite_seg=int(sys.argv[1]) if len(sys.argv) > 1 else 3600)
    print(f"Pósters: {sum('img' in m for m in meta.values())} · títulos ES: {sum('es' in m for m in meta.values())}"
          f" · sinopsis: {sum('sinopsis' in m for m in meta.values())}")


def _por_pelicula(ratings):
    res = {}
    for u, vistas in ratings.items():
        for i in vistas:
            res.setdefault(i, []).append(u)
    return res


if __name__ == "__main__":
    main()
