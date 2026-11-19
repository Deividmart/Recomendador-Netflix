"""
Bloque 6: evalúa el filtrado colaborativo contra el baseline de popularidad.
Genera resultados/metricas.csv y resultados/grafica_metricas.png para las diapositivas.

Uso:  py evaluar.py
"""
import csv
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from recomendador import FiltradoColaborativo, Popularidad, a_matriz, cargar_ratings, dividir, evaluar

SALIDA = Path(__file__).parent / "resultados"


def main():
    inicio = time.time()
    ratings = cargar_ratings()
    entrenamiento, prueba = dividir(ratings)
    R = a_matriz(entrenamiento)
    print(f"Entrenamiento: {int((R > 0).sum()):,} ratings | Prueba: {len(prueba):,} ratings")

    modelos = {
        "Filtrado colaborativo": FiltradoColaborativo(k=50).entrenar(R),
        "Baseline (popularidad)": Popularidad().entrenar(R),
    }
    resultados = {nombre: evaluar(m, prueba) for nombre, m in modelos.items()}

    metricas = list(next(iter(resultados.values())))
    print(f"\n{'Métrica':<14}" + "".join(f"{n:>26}" for n in resultados))
    for met in metricas:
        print(f"{met:<14}" + "".join(f"{r[met]:>26.4f}" for r in resultados.values()))
    print(f"\n(Tiempo total: {time.time() - inicio:.1f} s)")

    SALIDA.mkdir(exist_ok=True)
    with open(SALIDA / "metricas.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Métrica", *resultados])
        for met in metricas:
            w.writerow([met, *(f"{r[met]:.4f}" for r in resultados.values())])

    graficar(resultados, metricas)
    print(f"Guardado en {SALIDA}")


def graficar(resultados, metricas):
    colores = {"Filtrado colaborativo": "#E5484D", "Baseline (popularidad)": "#8B8D98"}
    fig, ejes = plt.subplots(1, 2, figsize=(11, 4.6), gridspec_kw={"width_ratios": [1, 1]})
    grupos = [("Error al predecir el rating", metricas[:2], "más bajo es mejor"),
              ("Calidad del top-10", metricas[2:], "más alto es mejor")]

    for eje, (titulo, mets, nota) in zip(ejes, grupos):
        ancho = 0.36
        for j, (nombre, r) in enumerate(resultados.items()):
            xs = [i + (j - 0.5) * ancho for i in range(len(mets))]
            barras = eje.bar(xs, [r[m] for m in mets], ancho, label=nombre, color=colores[nombre])
            eje.bar_label(barras, fmt="%.3f", padding=3, fontsize=10)
        eje.set_xticks(range(len(mets)), mets, fontsize=11)
        eje.set_title(f"{titulo}\n({nota})", fontsize=12)
        eje.spines[["top", "right"]].set_visible(False)
        eje.margins(y=0.15)
    ejes[0].legend(frameon=False, loc="upper right")
    fig.suptitle("Filtrado colaborativo vs. baseline · MovieLens latest-small (80/20)", fontsize=14, weight="bold")
    fig.tight_layout()
    fig.savefig(SALIDA / "grafica_metricas.png", dpi=200)


if __name__ == "__main__":
    main()
