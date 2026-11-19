"""
Recomendador de películas con filtrado colaborativo user-based (MovieLens latest-small, 1996-2018).

Flujo: cargar datos -> separar entrenamiento/prueba -> construir modelo -> recomendar -> evaluar.
"""
import csv
import heapq
import re
from functools import lru_cache
from pathlib import Path

import numpy as np

CARPETA_DATOS = Path(__file__).parent / "datos" / "ml-latest-small"
MIN_CALIFICACIONES = 5    # se descartan películas casi sin datos (menos de 5 calificaciones)
UMBRAL_GUSTO = 4          # rating >= 4 cuenta como "le gustó" (la escala va de 0,5 a 5)

GENEROS = ["Desconocido", "Acción", "Aventura", "Animación", "Infantil", "Comedia",
           "Crimen", "Documental", "Drama", "Fantasía", "Cine negro", "Terror",
           "Musical", "Misterio", "Romance", "Ciencia ficción", "Suspenso", "Bélica", "Western"]
GENEROS_ML = {"Action": "Acción", "Adventure": "Aventura", "Animation": "Animación", "Children": "Infantil",
              "Comedy": "Comedia", "Crime": "Crimen", "Documentary": "Documental", "Drama": "Drama",
              "Fantasy": "Fantasía", "Film-Noir": "Cine negro", "Horror": "Terror", "Musical": "Musical",
              "Mystery": "Misterio", "Romance": "Romance", "Sci-Fi": "Ciencia ficción", "Thriller": "Suspenso",
              "War": "Bélica", "Western": "Western"}


# ---------------------------------------------------------------- 1. Cargar datos

@lru_cache(maxsize=1)
def _indices():
    """Asigna índices 0..n-1 a usuarios y a las películas con al menos MIN_CALIFICACIONES."""
    conteo, usuarios = {}, set()
    with open(CARPETA_DATOS / "ratings.csv", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            conteo[fila["movieId"]] = conteo.get(fila["movieId"], 0) + 1
            usuarios.add(int(fila["userId"]))
    pelis = sorted((m for m, c in conteo.items() if c >= MIN_CALIFICACIONES), key=int)
    return ({u: n for n, u in enumerate(sorted(usuarios))}, {m: n for n, m in enumerate(pelis)})


N_USUARIOS, N_PELICULAS = (len(x) for x in _indices())


def cargar_ratings():
    """Devuelve el diccionario anidado {usuario: {pelicula: rating}} (índices desde 0)."""
    idx_u, idx_p = _indices()
    ratings = {}
    with open(CARPETA_DATOS / "ratings.csv", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            if fila["movieId"] in idx_p:
                ratings.setdefault(idx_u[int(fila["userId"])], {})[idx_p[fila["movieId"]]] = float(fila["rating"])
    return ratings


def _arreglar_titulo(titulo):
    """'Godfather, The (1972)' -> ('The Godfather', 1972)."""
    anio = None
    m = re.search(r"\s*\((\d{4})\)\s*$", titulo)
    if m:
        anio, titulo = int(m.group(1)), titulo[: m.start()].strip()
    while re.search(r"\s\([^()]*\)$", titulo):           # "Amelie (Fabuleux destin...)" -> "Amelie"
        titulo = re.sub(r"\s*\([^()]*\)$", "", titulo)
    for articulo in ("The", "A", "An", "Il", "La", "Le", "Les", "L'", "Das", "Die", "El"):
        sufijo = ", " + articulo
        if titulo.endswith(sufijo):
            titulo = articulo + ("" if articulo.endswith("'") else " ") + titulo[: -len(sufijo)]
    return titulo, anio


def cargar_peliculas():
    """Lista de dicts {titulo, anio, generos, tmdb, imdb} indexada por índice de película."""
    _, idx_p = _indices()
    links = {}
    with open(CARPETA_DATOS / "links.csv", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            links[fila["movieId"]] = (fila["tmdbId"], "tt" + fila["imdbId"])
    peliculas = [None] * len(idx_p)
    with open(CARPETA_DATOS / "movies.csv", encoding="utf-8") as f:
        for fila in csv.DictReader(f):
            if fila["movieId"] not in idx_p:
                continue
            titulo, anio = _arreglar_titulo(fila["title"])
            generos = [GENEROS_ML[g] for g in fila["genres"].split("|") if g in GENEROS_ML]
            tmdb, imdb = links.get(fila["movieId"], ("", ""))
            peliculas[idx_p[fila["movieId"]]] = {"id": fila["movieId"], "titulo": titulo, "anio": anio,
                                                 "generos": generos, "tmdb": tmdb, "imdb": imdb}
    return peliculas


# ---------------------------------------------------------------- 2. Separar entrenamiento / prueba

def dividir(ratings, prop_prueba=0.2, semilla=42):
    """Esconde ~20% de los ratings (el "examen") y entrena con el 80% restante."""
    rng = np.random.default_rng(semilla)
    entrenamiento, prueba = {}, []
    for usuario, vistas in ratings.items():
        for pelicula, rating in vistas.items():
            if rng.random() < prop_prueba:
                prueba.append((usuario, pelicula, rating))
            else:
                entrenamiento.setdefault(usuario, {})[pelicula] = rating
    return entrenamiento, prueba


def a_matriz(ratings):
    """Pasa el diccionario disperso a matriz densa (0 = no calificó) para cálculo vectorizado."""
    R = np.zeros((N_USUARIOS, N_PELICULAS))
    for usuario, vistas in ratings.items():
        for pelicula, rating in vistas.items():
            R[usuario, pelicula] = rating
    return R


# ---------------------------------------------------------------- 3. Modelos

class FiltradoColaborativo:
    """
    User-based CF:
      * similitud = coseno entre los ratings centrados de dos usuarios
        (rating - promedio del usuario: así "le gustó más de lo normal" pesa positivo)
      * vecinos   = los k usuarios más parecidos
      * ranking   = votos ponderados: cada vecino que le puso >= 4 a una película
                    vota por ella con el peso de su similitud
      * penalizacion: divide los votos entre (veces que gustó)^penalizacion para que
                    lo muy popular no tape todo (0 = sin freno; más alto = más diversidad)
      * rating    = promedio propio + desviación ponderada de los vecinos
    """

    def __init__(self, k=50, penalizacion=0.3):
        self.k = k
        self.penalizacion = penalizacion

    def entrenar(self, R):
        self.R = R
        self.vistas = R > 0
        self.promedio = R.sum(1) / np.maximum(self.vistas.sum(1), 1)
        self.centrada = (R - self.promedio[:, None]) * self.vistas
        normas = np.linalg.norm(self.centrada, axis=1) + 1e-9
        self.similitud = (self.centrada @ self.centrada.T) / np.outer(normas, normas)
        np.fill_diagonal(self.similitud, -np.inf)          # nadie es vecino de sí mismo
        self.freno = ((R >= UMBRAL_GUSTO).sum(0) + 5.0) ** self.penalizacion
        return self

    def vecinos(self, usuario):
        """Los k más parecidos con un heap: O(n log k) en vez de ordenar a todos."""
        sims = self.similitud[usuario]
        idx = heapq.nlargest(self.k, range(N_USUARIOS), key=sims.__getitem__)
        return np.array(idx), np.clip(sims[idx], 0, None)

    def predecir_todo(self, usuario):
        """Rating estimado (1-5) para todas las películas."""
        idx, pesos = self.vecinos(usuario)
        num = pesos @ self.centrada[idx]
        den = pesos @ self.vistas[idx]
        desviacion = np.divide(num, den, out=np.zeros(N_PELICULAS), where=den > 0)
        return np.clip(self.promedio[usuario] + desviacion, 1, 5)

    def puntajes(self, usuario):
        idx, pesos = self.vecinos(usuario)
        return (pesos @ (self.R[idx] >= UMBRAL_GUSTO)) / self.freno

    def recomendar(self, usuario, n=10):
        p = np.where(self.vistas[usuario], -np.inf, self.puntajes(usuario))
        return heapq.nlargest(n, range(N_PELICULAS), key=p.__getitem__)

    def recomendar_perfil_nuevo(self, me_gusta, no_me_gusta=(), n=10):
        """
        Usuario que no está en el dataset (el público en la demo).
        Su vector centrado es +1 en lo que le gusta y -1 en lo que no.
        """
        perfil = np.zeros(N_PELICULAS)
        perfil[list(me_gusta)] = 1
        perfil[list(no_me_gusta)] = -1
        normas = np.linalg.norm(self.centrada, axis=1) + 1e-9
        sims = (self.centrada @ perfil) / (normas * np.linalg.norm(perfil))
        idx = np.array(heapq.nlargest(self.k, range(N_USUARIOS), key=sims.__getitem__))
        pesos = np.clip(sims[idx], 0, None)
        p = (pesos @ (self.R[idx] >= UMBRAL_GUSTO)) / self.freno
        p[perfil != 0] = -np.inf
        return heapq.nlargest(n, range(N_PELICULAS), key=p.__getitem__)


class Popularidad:
    """Baseline: recomienda lo más visto; como rating predice el promedio de cada película."""

    def entrenar(self, R):
        self.vistas = R > 0
        conteo = self.vistas.sum(0)
        promedio_global = R[self.vistas].mean()
        self.popularidad = conteo.astype(float)
        self.promedio_peli = np.where(conteo > 0, R.sum(0) / np.maximum(conteo, 1), promedio_global)
        return self

    def predecir_todo(self, usuario):
        return self.promedio_peli

    def recomendar(self, usuario, n=10):
        p = np.where(self.vistas[usuario], -np.inf, self.popularidad)
        return heapq.nlargest(n, range(N_PELICULAS), key=p.__getitem__)


# ---------------------------------------------------------------- 4. Métricas

def evaluar(modelo, prueba, k=10):
    """RMSE y MAE sobre todos los ratings escondidos; Precision@K y Recall@K por usuario."""
    por_usuario = {}
    for usuario, pelicula, rating in prueba:
        por_usuario.setdefault(usuario, []).append((pelicula, rating))

    errores, precisiones, recalls = [], [], []
    for usuario, pares in por_usuario.items():
        predicho = modelo.predecir_todo(usuario)
        errores += [predicho[p] - r for p, r in pares]

        le_gustaron = {p for p, r in pares if r >= UMBRAL_GUSTO}
        if not le_gustaron:
            continue
        aciertos = len(le_gustaron.intersection(modelo.recomendar(usuario, k)))
        precisiones.append(aciertos / k)
        recalls.append(aciertos / len(le_gustaron))

    errores = np.array(errores)
    return {
        "RMSE": float(np.sqrt(np.mean(errores ** 2))),
        "MAE": float(np.mean(np.abs(errores))),
        f"Precision@{k}": float(np.mean(precisiones)),
        f"Recall@{k}": float(np.mean(recalls)),
    }
