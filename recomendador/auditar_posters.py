"""
Revisa lo descargado de Wikipedia: qué películas no tienen póster y cuáles podrían estar
enlazadas a la película equivocada (el año de la sinopsis no coincide con el de MovieLens).

Uso:  py auditar_posters.py
"""
import json
import re
from pathlib import Path

from recomendador import CARPETA_DATOS

WIKI = Path(__file__).parent / "datos" / "wiki"


def main():
    with open(CARPETA_DATOS / "u.item", encoding="latin-1") as f:
        titulos = [linea.split("|")[1] for linea in f]
    vistas = {}
    with open(CARPETA_DATOS / "u.data", encoding="latin-1") as f:
        for linea in f:
            i = int(linea.split("\t")[1]) - 1
            vistas[i] = vistas.get(i, 0) + 1
    orden = sorted(range(len(titulos)), key=lambda i: -vistas.get(i, 0))

    arts = json.loads((WIKI / "articulos.json").read_text(encoding="utf-8"))
    meta = json.loads((WIKI / "meta.json").read_text(encoding="utf-8"))
    imgs = {int(p.stem) for p in (WIKI / "img").iterdir()}

    sin_articulo, sin_poster, pendientes, sospechosas = [], [], [], []
    for pos, i in enumerate(orden, 1):
        t, m = titulos[i], meta.get(str(i), {})
        if not arts.get(str(i), {}).get("en"):
            sin_articulo.append((pos, t))
            continue
        if str(i) not in meta:
            pendientes.append(i)
        elif i not in imgs:
            sin_poster.append((pos, t, arts[str(i)]["en"]))
        anio = re.search(r"\((\d{4})\)\s*$", t)
        anios_txt = {int(a) for a in re.findall(r"\b(1[89]\d\d|20\d\d)\b", m.get("sinopsis", ""))}
        if anio and anios_txt and not any(abs(a - int(anio.group(1))) <= 1 for a in anios_txt):
            sospechosas.append((pos, t, arts[str(i)]["en"], sorted(anios_txt)))

    print(f"Películas: {len(titulos)} · con póster: {len(imgs)} · con ficha: {len(meta)}")
    for corte in (100, 300, 600, 1000, len(titulos)):
        print(f"  top {corte:>4}: {sum(i in imgs for i in orden[:corte])}/{corte} con póster")
    print(f"  pendientes de descargar: {len(pendientes)}")
    print(f"\nSin artículo en Wikipedia ({len(sin_articulo)}):")
    for pos, t in sin_articulo[:40]:
        print(f"  #{pos:<5} {t}")
    print(f"\nYa revisadas en Wikipedia y sin póster ({len(sin_poster)}):")
    for pos, t, a in sin_poster[:40]:
        print(f"  #{pos:<5} {t}  ->  {a}")
    print(f"\nPosible película equivocada: el año no coincide ({len(sospechosas)}):")
    for pos, t, a, anios in sospechosas:
        print(f"  #{pos:<5} {t}  ->  {a}  {anios}")


if __name__ == "__main__":
    main()
