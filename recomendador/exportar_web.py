"""
Construye la app web de la demo (bloque 5): mete las calificaciones reales dentro de
app/plantilla.html y genera app/vecinos_de_cine.html + app/posters-N.js (+ app/fondos-N.js).
Abriendo el .html con esos .js al lado funciona sin internet.

Requiere haber corrido antes:  py evaluar.py  y  py descargar_tmdb.py  (datos/tmdb/).
Uso:  py exportar_web.py
"""
import base64
import csv
import io
import json
import re
from pathlib import Path

from PIL import Image, ImageOps

from recomendador import GENEROS, cargar_peliculas, cargar_ratings

APP = Path(__file__).parent / "app"
ARTE = Path(__file__).parent / "datos" / "tmdb"
RESULTADOS = Path(__file__).parent / "resultados" / "metricas.csv"
TAM_POSTER = (180, 270)
TAM_FONDO = (780, 439)
MAX_POR_ARCHIVO = 6_000_000      # caracteres por archivo .js

# Películas conocidas para que el público elija rápido (se buscan por título).
CARTELERA = [
    "Star Wars: Episode IV - A New Hope", "The Matrix", "Forrest Gump", "Titanic", "The Lion King",
    "The Lord of the Rings: The Fellowship of the Ring", "Harry Potter and the Sorcerer's Stone", "Shrek",
    "The Dark Knight", "Inception", "Avatar", "Toy Story", "Finding Nemo", "Pirates of the Caribbean: The Curse of the Black Pearl",
    "Gladiator", "Jurassic Park", "Iron Man", "The Avengers", "Spider-Man", "Up", "WALL·E", "The Incredibles",
    "Pulp Fiction", "The Godfather", "Fight Club", "The Shawshank Redemption", "The Silence of the Lambs", "Seven",
    "The Sixth Sense", "Back to the Future", "Terminator 2: Judgment Day", "Men in Black", "Home Alone",
    "Monsters, Inc.", "Toy Story 3", "Interstellar", "Guardians of the Galaxy", "Django Unchained",
    "The Wolf of Wall Street", "Kill Bill: Vol. 1", "The Departed", "Amelie", "Spirited Away",
    "Ocean's Eleven", "The Shining", "Ice Age", "Casino Royale", "Mean Girls", "It", "Get Out",
]

PERFILES = {
    "Ciencia ficción": ["Star Wars: Episode IV - A New Hope", "Star Wars: Episode V - The Empire Strikes Back",
                        "The Matrix", "Alien"],
    "Infantil": ["Toy Story", "Finding Nemo", "Shrek", "The Lion King"],
    "Terror": ["The Shining", "The Silence of the Lambs", "Seven", "The Sixth Sense"],
    "Crimen": ["Pulp Fiction", "The Godfather", "The Departed", "Reservoir Dogs"],
    "Superhéroes": ["The Dark Knight", "Iron Man", "The Avengers", "Spider-Man"],
}


def main():
    peliculas = cargar_peliculas()
    ratings = cargar_ratings()

    def buscar(titulo):
        exactas = [i for i, p in enumerate(peliculas) if p["titulo"] == titulo]
        if exactas:
            return exactas[0]
        parecidas = [i for i, p in enumerate(peliculas) if p["titulo"].startswith(titulo)]
        if not parecidas:
            raise ValueError(f"No está en el catálogo: {titulo}")
        return parecidas[0]

    entero = lambda r: int(r) if r == int(r) else r
    datos = {
        "generos": GENEROS,
        "peliculas": [[p["titulo"], p["anio"] or 0,
                       sum(1 << GENEROS.index(g) for g in p["generos"])] for p in peliculas],
        # por usuario: [pelicula, rating, pelicula, rating, ...]  (ratings de 0,5 a 5)
        "ratings": [[x for i, r in sorted(ratings[u].items()) for x in (i, entero(r))] for u in sorted(ratings)],
        "cartelera": [buscar(t) for t in CARTELERA],
        "perfiles": {nombre: [buscar(t) for t in ts] for nombre, ts in PERFILES.items()},
    }

    meta = json.loads((ARTE / "meta.json").read_text(encoding="utf-8")) if (ARTE / "meta.json").exists() else {}
    datos["es"] = [titulo_es(meta.get(p["id"], {}).get("es"), p["titulo"]) for p in peliculas]
    datos["sinopsis"] = [meta.get(p["id"], {}).get("sinopsis") or None for p in peliculas]
    with open(RESULTADOS, encoding="utf-8") as f:
        filas = list(csv.reader(f))
    datos["metricas"] = {modelo: {fila[0]: float(fila[k]) for fila in filas[1:]}
                         for k, modelo in enumerate(filas[0][1:], start=1)}

    # las más populares primero: el primer archivo de pósters basta para la cartelera y casi todas las recomendaciones
    vistas = {}
    for calificadas in ratings.values():
        for i in calificadas:
            vistas[i] = vistas.get(i, 0) + 1
    prioridad = {i: -vistas.get(i, 0) for i in range(len(peliculas))}
    for i in datos["cartelera"] + [j for ids in datos["perfiles"].values() for j in ids]:
        prioridad[i] = -10**6

    for viejo in APP.glob("*.js"):
        viejo.unlink()
    indice = {p["id"]: i for i, p in enumerate(peliculas)}
    posters = empaquetar("img", "posters", "POSTERS", TAM_POSTER, 66, (0.5, 0.35), prioridad, indice)
    fondos = empaquetar("fondo", "fondos", "FONDOS", TAM_FONDO, 55, (0.5, 0.5), prioridad, indice)
    js = json.dumps(datos, ensure_ascii=False, separators=(",", ":"))
    plantilla = (APP / "plantilla.html").read_text(encoding="utf-8")
    # el primer archivo se carga antes de arrancar; el resto, en segundo plano ya con la app en pantalla
    etiquetas = f'<script src="{posters[0]}"></script>\n' if posters else ""
    etiquetas += f"<script>window.CARGA_DIFERIDA = {json.dumps(posters[1:] + fondos)};</script>"
    plantilla = plantilla.replace("<!--__POSTERS__-->", etiquetas)
    salida = APP / "vecinos_de_cine.html"
    salida.write_text(plantilla.replace("/*__DATOS__*/null", js), encoding="utf-8")
    print(f"Generado {salida} ({salida.stat().st_size / 1024:.0f} KB)")


def titulo_es(es, original):
    """Usa el título en español solo si de verdad es otro nombre."""
    if not es:
        return None
    es = re.sub(r"\s*\[[^\]]*\]", "", es).strip()        # "Juego sangriento [バトル・ロワイアル]"
    simple = lambda t: "".join(c for c in t.lower() if c.isalnum())
    if simple(es) == simple(original):
        return None
    return es


def empaquetar(carpeta, prefijo, variable, tam, calidad, centro, prioridad, indice):
    """Recorta cada imagen a su proporción, la pasa a WebP y la reparte en <prefijo>-N.js."""
    origen = ARTE / carpeta
    if not origen.exists():
        return []
    trozos, actual, largo = [], {}, 0
    archivos = [a for a in origen.glob("*.jpg") if a.stem in indice]      # solo películas del catálogo
    for archivo in sorted(archivos, key=lambda a: prioridad[indice[a.stem]]):
        try:
            img = ImageOps.fit(Image.open(archivo).convert("RGB"), tam, Image.LANCZOS, centering=centro)
        except Exception as e:
            print(f"  {archivo.name} ignorada: {e}")
            continue
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=calidad, method=6)
        uri = "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
        actual[str(indice[archivo.stem])] = uri
        largo += len(uri)
        if largo > MAX_POR_ARCHIVO:
            trozos.append(actual)
            actual, largo = {}, 0
    if actual:
        trozos.append(actual)
    nombres = []
    for n, trozo in enumerate(trozos, 1):
        nombre = f"{prefijo}-{n}.js"
        (APP / nombre).write_text(f"window.{variable}=Object.assign(window.{variable}||{{}}," +
                                  json.dumps(trozo, separators=(",", ":")) + ");", encoding="utf-8")
        nombres.append(nombre)
    total = sum(len(t) for t in trozos)
    print(f"{prefijo}: {total} imágenes en {len(nombres)} archivos "
          f"({sum((APP / n).stat().st_size for n in nombres) / 1e6:.1f} MB)")
    return nombres


if __name__ == "__main__":
    main()
