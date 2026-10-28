"""Genera los archivos de los escenarios de prueba obligatorios en pruebas/escenarios/.

Uso: python -m scripts.generar_escenarios  (después de scripts.entrenar_inicial)
"""
import pandas as pd

from app import limpieza, modelo
from app.config import BASE

SALIDA = BASE / "pruebas" / "escenarios"
CRUDO = next((BASE / "datos" / "crudos").glob("*.csv"))


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(CRUDO, dtype=str)
    limpio = limpieza.limpiar(raw)
    variables = limpieza.construir_variables(limpio)
    t = modelo.periodo(variables)
    sin_obj = [c for c in variables.columns if c != modelo.OBJETIVO]

    # 1. Compatible: localidades con mes objetivo 2025-10 (no usado por la v1), sin la variable objetivo
    base = variables[(t == 2025 * 12 + 9) & variables.horas_dia_lag1.notna()][sin_obj].reset_index(drop=True)
    base.to_csv(SALIDA / "01_compatible.csv", index=False)

    # 2. Falta una variable obligatoria
    base.drop(columns=["energia_lag1_kwh"]).to_csv(SALIDA / "02_falta_variable.csv", index=False)

    # 3. Tipos incompatibles: texto en un entero y números con formato español
    x = base.astype(object).copy()
    x.loc[:3, "mes_objetivo"] = "octubre"
    x.loc[5:9, "energia_lag1_kwh"] = x.loc[5:9, "energia_lag1_kwh"].map(lambda v: f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", "."))
    x.to_csv(SALIDA / "03_tipo_incompatible.csv", index=False)

    # 4. Faltantes en una variable necesaria
    x = base.copy()
    x.loc[[2, 7, 11, 20, 33], "energia_lag1_kwh"] = None
    x.to_csv(SALIDA / "04_faltantes.csv", index=False)

    # 5. Categoría no vista: departamento nuevo (advertencia) y tamaño fuera de la escala (error)
    x = base.copy()
    x.loc[:2, "departamento"] = "BOGOTÁ D.C."
    x.to_csv(SALIDA / "05a_categoria_nueva_departamento.csv", index=False)
    x = base.copy()
    x.loc[:4, "tamano"] = "Enorme"
    x.to_csv(SALIDA / "05b_categoria_fuera_de_escala.csv", index=False)

    # 6. Columnas adicionales que el modelo no usa
    x = base.copy()
    x["operador"] = "Operador local"
    x["observaciones"] = "sin novedad"
    x.to_csv(SALIDA / "06_columnas_adicionales.csv", index=False)

    # 7. Solo EDA: el CSV crudo del portal (2025). No sirve para predecir, pero sí se puede analizar
    raw[raw["AÑO SERVICIO"] == "2025"].to_csv(SALIDA / "07_solo_eda_portal_crudo.csv", index=False)
    # 7b. Reglas de dominio incumplidas
    x = base.copy()
    x.loc[:2, "horas_dia_lag1"] = 30
    x.loc[3:4, "factor_carga_lag1"] = 1.4
    x.loc[5, "sin_servicio_lag1"] = 1
    x.to_csv(SALIDA / "07b_reglas_de_dominio.csv", index=False)

    # 8. Nuevos datos etiquetados: meses objetivo 2025-07 a 2026-01 (posteriores a la v1)
    variables[t > 2025 * 12 + 5].to_csv(SALIDA / "08_nuevos_etiquetados.csv", index=False)

    # 9. Pronóstico real: febrero de 2026 a partir de todo el archivo (horas faltan por el cambio de formato)
    limpieza.construir_variables(limpio, con_objetivo=False, siguiente_mes=True).to_csv(
        SALIDA / "09_pronostico_2026_02.csv", index=False)
    for f in sorted(SALIDA.iterdir()):
        print(f.name, sum(1 for _ in open(f, encoding="utf-8")) - 1, "filas")


if __name__ == "__main__":
    main()
