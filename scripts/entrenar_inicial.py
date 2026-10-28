"""Entrena la versión inicial (v1) del modelo a partir del CSV del portal de datos abiertos.

Uso: python -m scripts.entrenar_inicial
La v1 usa los meses objetivo hasta 2025-06. Los meses de 2025-07 a 2026-01 se reservan como
"datos nuevos etiquetados" para demostrar el flujo de actualización del modelo.
"""
import shutil

import pandas as pd

from app import limpieza, modelo
from app.config import BASE, DIR_MODELOS

CRUDO = next((BASE / "datos" / "crudos").glob("*.csv"))
CORTE_V1 = 2025 * 12 + 5  # 2025-06


def main():
    raw = pd.read_csv(CRUDO, dtype=str)
    variables = limpieza.construir_variables(limpieza.limpiar(raw))
    variables.to_csv(BASE / "datos" / "variables_modelo.csv", index=False)
    base = variables[modelo.periodo(variables) <= CORTE_V1]
    if DIR_MODELOS.exists():
        shutil.rmtree(DIR_MODELOS)
    version, meta = modelo.entrenar_version(base, estado="activo", nota="Versión inicial (meses objetivo hasta 2025-06)",
                                            comparacion_algoritmos=True)
    print(f"{version} entrenada con {meta['registros']} registros ({meta['periodo_datos']})")
    print("Validación:", meta["estrategia_validacion"])
    print("Métricas:", meta["metricas_validacion"])
    print("Comparación de algoritmos (MAE log):", meta["comparacion_algoritmos"])


if __name__ == "__main__":
    main()
