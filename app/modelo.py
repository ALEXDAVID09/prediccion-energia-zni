"""Pipeline predictivo, validación temporal y versiones del modelo.

El modelo predice la energía activa del mes siguiente de cada localidad. Todo el preprocesamiento
vive dentro del pipeline de scikit-learn, que se ajusta solo con datos de entrenamiento y se guarda
con joblib; al predecir se carga el archivo y nunca se vuelve a ajustar.
"""
import copy
import json
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, OrdinalEncoder, StandardScaler

from .config import DIR_MODELOS, ESQUEMA_BASE, REGISTRO

OBJETIVO = "energia_objetivo_kwh"
VAR_ENERGIA = ["energia_lag1_kwh", "energia_lag2_kwh", "energia_lag12_kwh"]
VAR_OTRAS = ["horas_dia_lag1", "factor_carga_lag1"]
VAR_CAT = ["departamento"]
VAR_ORD = ["tamano"]
VAR_MES = ["mes_objetivo"]
VAR_BIN = ["sin_servicio_lag1"]
PREDICTORAS = VAR_CAT + VAR_ORD + VAR_MES + VAR_ENERGIA + VAR_OTRAS + VAR_BIN
MESES_PRUEBA = 12  # validación temporal: los últimos 12 meses objetivo se reservan como prueba

CONFIG = {"algoritmo": "HistGradientBoostingRegressor", "loss": "squared_error", "learning_rate": 0.03,
          "max_iter": 300, "max_leaf_nodes": 31, "min_samples_leaf": 20, "l2_regularization": 1.0, "random_state": 42,
          "objetivo_transformado": "log1p / expm1"}


def mes_ciclico(x):
    """Mes 1-12 -> (seno, coseno): diciembre y enero quedan cerca."""
    m = np.asarray(x, dtype=float)
    return np.column_stack([np.sin(2 * np.pi * m[:, 0] / 12), np.cos(2 * np.pi * m[:, 0] / 12)])


def crear_pipeline(algoritmo="hgb", tamanos=None):
    tamanos = tamanos or ESQUEMA_BASE["variables"][1]["categorias"]
    log_imputar = Pipeline([("log", FunctionTransformer(np.log1p, feature_names_out="one-to-one")),
                            ("imputar", SimpleImputer(strategy="median", add_indicator=True))])
    prep = ColumnTransformer([
        ("energia", log_imputar, VAR_ENERGIA),
        ("otras", SimpleImputer(strategy="median", add_indicator=True), VAR_OTRAS),
        ("departamento", OneHotEncoder(handle_unknown="ignore", sparse_output=False), VAR_CAT),
        ("tamano", OrdinalEncoder(categories=[tamanos]), VAR_ORD),
        ("mes", FunctionTransformer(mes_ciclico), VAR_MES),
        ("binaria", "passthrough", VAR_BIN),
    ])
    if algoritmo == "hgb":
        reg = HistGradientBoostingRegressor(**{k: v for k, v in CONFIG.items()
                                               if k not in ("algoritmo", "objetivo_transformado")})
        pasos = [("preprocesamiento", prep), ("regresor", reg)]
    else:  # referencia lineal
        pasos = [("preprocesamiento", prep), ("escalar", StandardScaler()), ("regresor", Ridge(alpha=1.0))]
    return TransformedTargetRegressor(regressor=Pipeline(pasos), func=np.log1p, inverse_func=np.expm1)


def metricas(y_real, y_pred, lag1=None):
    y_real = np.asarray(y_real, float)
    y_pred = np.clip(np.asarray(y_pred, float), 0, None)
    err_log = np.abs(np.log1p(y_pred) - np.log1p(y_real))
    m = {
        "mae_log": round(float(err_log.mean()), 4),
        "mediana_error_relativo_pct": round(float((np.expm1(np.median(err_log))) * 100), 1),
        "wape_pct": round(float(np.abs(y_pred - y_real).sum() / max(y_real.sum(), 1) * 100), 2),
        "mae_kwh": round(float(np.abs(y_pred - y_real).mean()), 1),
        "n": int(len(y_real)),
    }
    if lag1 is not None:
        base = np.abs(np.log1p(np.asarray(lag1, float)) - np.log1p(y_real)).mean()
        m["mae_log_ingenuo"] = round(float(base), 4)
        m["mejora_vs_ingenuo_pct"] = round(float((1 - m["mae_log"] / base) * 100), 1) if base > 0 else None
    return m


def periodo(df):
    return df["anio_objetivo"].astype(int) * 12 + df["mes_objetivo"].astype(int) - 1


def separar_temporal(datos):
    t = periodo(datos)
    corte = t.max() - MESES_PRUEBA + 1
    return datos[t < corte], datos[t >= corte], int(corte)


def _texto_periodo(t):
    return f"{t // 12}-{t % 12 + 1:02d}"


def validar(datos, algoritmo="hgb"):
    """Estrategia de validación: entrenar con los meses anteriores y probar en los 12 más recientes."""
    entreno, prueba, corte = separar_temporal(datos)
    modelo = crear_pipeline(algoritmo)
    modelo.fit(entreno[PREDICTORAS], entreno[OBJETIVO])
    pred = modelo.predict(prueba[PREDICTORAS])
    m = metricas(prueba[OBJETIVO], pred, prueba["energia_lag1_kwh"])
    por_tamano = {}
    for tam, g in prueba.assign(_p=pred).groupby("tamano"):
        por_tamano[tam] = metricas(g[OBJETIVO], g["_p"])["mae_log"]
    m["mae_log_por_tamano"] = por_tamano
    residuo_log = np.log1p(prueba[OBJETIVO].to_numpy()) - np.log1p(np.clip(pred, 0, None))
    intervalos = {tam: [round(float(np.quantile(r, 0.1)), 4), round(float(np.quantile(r, 0.9)), 4)]
                  for tam, r in pd.Series(residuo_log).groupby(prueba["tamano"].to_numpy())}
    intervalos["general"] = [round(float(np.quantile(residuo_log, 0.1)), 4),
                             round(float(np.quantile(residuo_log, 0.9)), 4)]
    detalle = {"entrenamiento": f"{_texto_periodo(int(periodo(entreno).min()))} a {_texto_periodo(corte - 1)}",
               "prueba": f"{_texto_periodo(corte)} a {_texto_periodo(int(periodo(prueba).max()))}",
               "registros_entrenamiento": int(len(entreno)), "registros_prueba": int(len(prueba))}
    return modelo, m, intervalos, detalle


# ---------------------------------------------------------------- registro de versiones

def leer_registro():
    if REGISTRO.exists():
        return json.loads(REGISTRO.read_text(encoding="utf-8"))
    return {"versiones": []}


def guardar_registro(reg):
    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    REGISTRO.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


def version_activa():
    for v in leer_registro()["versiones"]:
        if v["estado"] == "activo":
            return v
    return None


def buscar_version(version):
    for v in leer_registro()["versiones"]:
        if v["version"] == version:
            return v
    return None


def cargar_metadatos(v):
    return json.loads((DIR_MODELOS / v["version"] / "metadatos.json").read_text(encoding="utf-8"))


def cargar_pipeline(v):
    return joblib.load(DIR_MODELOS / v["version"] / "pipeline.joblib")


def cargar_datos(v):
    return pd.read_csv(DIR_MODELOS / v["version"] / "datos_entrenamiento.csv", dtype={"id_localidad": str})


def entrenables(datos):
    """Los meses objetivo con energía 0 no se usan para entrenar ni validar: en la fuente un 0 puede ser
    "sin servicio" o "sin dato" (Actividad 3) y no describe la demanda que se quiere anticipar."""
    return datos[datos[OBJETIVO] > 0]


def entrenar_version(datos, estado, nota="", comparacion_algoritmos=False):
    """Valida con la estrategia temporal, reajusta con todos los datos y guarda una versión nueva."""
    datos = entrenables(datos).sort_values(["anio_objetivo", "mes_objetivo", "id_localidad"]).reset_index(drop=True)
    _, m, intervalos, detalle = validar(datos)
    final = crear_pipeline()
    final.fit(datos[PREDICTORAS], datos[OBJETIVO])

    reg = leer_registro()
    numero = len(reg["versiones"]) + 1
    nombre = f"v{numero}"
    carpeta = DIR_MODELOS / nombre
    carpeta.mkdir(parents=True, exist_ok=True)
    joblib.dump(final, carpeta / "pipeline.joblib")
    datos.to_csv(carpeta / "datos_entrenamiento.csv", index=False)

    esquema = copy.deepcopy(ESQUEMA_BASE)
    for var in esquema["variables"]:
        if var["nombre"] == "departamento":
            var["categorias"] = sorted(datos["departamento"].dropna().unique().tolist())
    ahora = datetime.now().isoformat(timespec="seconds")
    meta = {
        "version": nombre,
        "fecha_entrenamiento": ahora,
        "registros": int(len(datos)),
        "periodo_datos": f"{_texto_periodo(int(periodo(datos).min()))} a {_texto_periodo(int(periodo(datos).max()))}",
        "variables_predictoras": PREDICTORAS,
        "algoritmo": CONFIG["algoritmo"],
        "configuracion": CONFIG,
        "metrica_principal": {"nombre": "mae_log", "valor": m["mae_log"],
                              "descripcion": "Error absoluto medio en escala log(1 + kWh). 0,20 equivale a equivocarse "
                                             "alrededor de un 22% en una localidad típica; trata igual a localidades "
                                             "grandes y pequeñas."},
        "metricas_validacion": m,
        "estrategia_validacion": {"tipo": "temporal, nunca aleatoria",
                                  "descripcion": f"Se entrena con los meses anteriores y se prueba en los "
                                                 f"{MESES_PRUEBA} meses objetivo más recientes; luego el modelo "
                                                 f"definitivo se reajusta con todos los datos.", **detalle},
        "intervalo_80_residuo_log": intervalos,
        "esquema": esquema,
    }
    if comparacion_algoritmos:
        meta["comparacion_algoritmos"] = {
            "HistGradientBoosting": m["mae_log"],
            "Ridge (lineal)": validar(datos, "ridge")[1]["mae_log"],
            "Ingenuo (repetir el mes anterior)": m["mae_log_ingenuo"],
        }
    (carpeta / "metadatos.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    reg["versiones"].append({
        "version": nombre, "fecha_entrenamiento": ahora, "registros": int(len(datos)),
        "variables": PREDICTORAS, "algoritmo": CONFIG["algoritmo"], "configuracion": CONFIG,
        "metricas": {"mae_log": m["mae_log"], "wape_pct": m["wape_pct"],
                     "mejora_vs_ingenuo_pct": m.get("mejora_vs_ingenuo_pct")},
        "archivo": f"modelos/{nombre}/pipeline.joblib", "estado": estado, "nota": nota, "decision": None,
    })
    guardar_registro(reg)
    return nombre, meta


def predecir(v, entrada):
    """Aplica el pipeline guardado (sin reajustar) y agrega un intervalo del 80% por tamaño."""
    modelo = cargar_pipeline(v)
    meta = cargar_metadatos(v)
    pred = np.clip(modelo.predict(entrada[PREDICTORAS]), 0, None)
    inter = meta["intervalo_80_residuo_log"]
    q = entrada["tamano"].map(lambda t: inter.get(t, inter["general"]))
    lo = np.expm1(np.log1p(pred) + q.map(lambda x: x[0]).to_numpy())
    hi = np.expm1(np.log1p(pred) + q.map(lambda x: x[1]).to_numpy())
    return pred, np.clip(lo, 0, None), hi


def decidir(version, accion, justificacion):
    """accion = 'activar' (la candidata reemplaza a la activa) o 'descartar' (la candidata pasa a histórico)."""
    reg = leer_registro()
    cand = next((v for v in reg["versiones"] if v["version"] == version), None)
    if cand is None or cand["estado"] != "candidato":
        raise ValueError(f"La versión {version} no existe o no está en estado candidato.")
    ahora = datetime.now().isoformat(timespec="seconds")
    if accion == "activar":
        for v in reg["versiones"]:
            if v["estado"] == "activo":
                v["estado"] = "historico"
                v["decision"] = {"fecha": ahora, "accion": f"reemplazada por {version}", "justificacion": justificacion}
        cand["estado"] = "activo"
    else:
        cand["estado"] = "historico"
    cand["decision"] = {"fecha": ahora, "accion": accion, "justificacion": justificacion}
    guardar_registro(reg)
    return cand
