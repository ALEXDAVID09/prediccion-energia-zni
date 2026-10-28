"""Limpieza del archivo abierto de ZNI y construcción de la tabla de variables del modelo.

Reproduce las decisiones de la Actividad 3 (notebook Analisis_ZNI_Energia_Completo.ipynb):
números en formato español, pérdida de la coma decimal desde 2025-12, un nombre por código DANE
y corrección de códigos de localidad equivocados. Luego arma, para cada localidad y mes objetivo,
las variables rezagadas que usa el modelo (sin fuga de información del mes que se predice).
"""
import re
import unicodedata

import numpy as np
import pandas as pd

COLUMNAS_CRUDAS = [
    "ID DEPATAMENTO", "DEPARTAMENTO", "ID MUNICIPIO", "MUNICIPIO", "ID LOCALIDAD", "LOCALIDAD",
    "AÑO SERVICIO", "MES SERVICIO", "ENERGÍA ACTIVA", "ENERGÍA REACTIVA", "POTENCIA MÁXIMA",
    "DÍA DE DEMANDA MÁXIMA", "FECHA DE DEMANDA MÁXIMA", "PROMEDIO DIARIO EN HORAS",
]

NOMBRE_DEP = {5: "ANTIOQUIA", 13: "BOLÍVAR", 18: "CAQUETÁ", 19: "CAUCA", 27: "CHOCÓ", 44: "LA GUAJIRA",
              47: "MAGDALENA", 50: "META", 52: "NARIÑO", 76: "VALLE DEL CAUCA", 85: "CASANARE", 86: "PUTUMAYO",
              88: "SAN ANDRÉS Y PROVIDENCIA", 91: "AMAZONAS", 94: "GUAINÍA", 95: "GUAVIARE", 97: "VAUPÉS",
              99: "VICHADA"}

# Tamaño de la localidad según su energía mensual mediana (mismos cortes del notebook, en kWh/mes)
CORTES_TAMANO = [0, 5_000, 50_000, 500_000, np.inf]
TAMANOS = ["Muy pequeña", "Pequeña", "Mediana", "Grande"]

# Desde este periodo (AAAAMM) POTENCIA MÁXIMA y PROMEDIO DIARIO EN HORAS perdieron la coma decimal
PERIODO_FORMATO_PERDIDO = 202512


def num_es(s):
    """'7.768,76' -> 7768.76 ; '1.234.567' -> 1234567.0 (punto = miles, coma = decimal)."""
    s = s.astype("string")
    return pd.to_numeric(s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False), errors="coerce")


def sin_tildes(s):
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()


def limpiar_nombre(s):
    return re.sub(r"\s+", " ", sin_tildes(s).upper().strip())


def _mejor_nombre(s):
    v = s.value_counts()  # prefiere la variante con tildes; a igualdad, la más frecuente
    return sorted(v.index, key=lambda n: (-(n != sin_tildes(n)), -v[n]))[0]


def faltan_columnas_crudas(df):
    return [c for c in COLUMNAS_CRUDAS if c not in df.columns]


def limpiar(df_raw):
    """Devuelve una fila por localidad y mes con energía, horas y factor de carga limpios."""
    df = df_raw[COLUMNAS_CRUDAS].astype("string").drop_duplicates().reset_index(drop=True)
    df["ANIO"] = pd.to_numeric(df["AÑO SERVICIO"], errors="coerce")
    df["MES"] = pd.to_numeric(df["MES SERVICIO"], errors="coerce")
    df = df[df.ANIO.notna() & df.MES.between(1, 12)].copy()
    df["ANIO"] = df.ANIO.astype(int)
    df["MES"] = df.MES.astype(int)
    df["DIAS_MES"] = pd.to_datetime(dict(year=df.ANIO, month=df.MES, day=1)).dt.days_in_month
    df["ID_DEP"] = pd.to_numeric(df["ID DEPATAMENTO"], errors="coerce").fillna(0).astype(int)
    df["ID_MUN"] = pd.to_numeric(df["ID MUNICIPIO"], errors="coerce").fillna(0).astype(int)
    df["ID_LOC"] = pd.to_numeric(df["ID LOCALIDAD"], errors="coerce").fillna(0).astype(int)
    df["EA_KWH"] = num_es(df["ENERGÍA ACTIVA"])

    formato_perdido = (df.ANIO * 100 + df.MES) >= PERIODO_FORMATO_PERDIDO
    pot = num_es(df["POTENCIA MÁXIMA"]).where(~formato_perdido)
    hrs = num_es(df["PROMEDIO DIARIO EN HORAS"]).where(~formato_perdido)
    copia = pot.notna() & (pot == hrs) & (pot > 0)  # valor copiado en el campo equivocado
    df["POT_KW"] = pot.mask(copia)
    df["HORAS_DIA"] = hrs.mask(copia | (hrs > 24))

    # Departamento: un nombre por código DANE (el código 0 se resuelve con el municipio)
    df.loc[df.ID_DEP == 0, "ID_DEP"] = df.loc[df.ID_DEP == 0, "ID_MUN"] // 1000
    df["DEPARTAMENTO_LIMPIO"] = df.ID_DEP.map(NOMBRE_DEP).fillna(df["DEPARTAMENTO"].map(limpiar_nombre))

    # Localidad: el código identifica la localidad, salvo filas con el código equivocado
    loc_txt = df["LOCALIDAD"].str.replace(r"\s*\(.*\)\s*$", "", regex=True).str.strip()
    nombre_n = loc_txt.map(limpiar_nombre)
    t = pd.DataFrame({"m": df.ID_MUN, "n": nombre_n, "id": df.ID_LOC})
    cnt_par = t.groupby(["m", "n", "id"])["id"].transform("size")
    dominante = t.groupby(["m", "n"])["id"].transform(lambda s: s.value_counts().index[0])
    n_dom = t.groupby(["m", "n"])["id"].transform(lambda s: s.value_counts().iloc[0])
    mal_codigo = (t["id"] != dominante) & (cnt_par <= 5) & (n_dom >= 10)
    rep = (df.groupby(["ID_LOC", "ANIO", "MES"])["ID_LOC"].transform("size") > 1) & ~mal_codigo
    df["LOC_KEY"] = np.where(mal_codigo, dominante.astype(str),
                             np.where(rep, df.ID_LOC.astype(str) + "|" + nombre_n, df.ID_LOC.astype(str)))
    df["LOCALIDAD_LIMPIA"] = df.LOC_KEY.map(loc_txt.groupby(df.LOC_KEY).agg(_mejor_nombre))
    df["DEPARTAMENTO_LIMPIO"] = df.LOC_KEY.map(
        df.groupby("LOC_KEY")["DEPARTAMENTO_LIMPIO"].agg(lambda s: s.value_counts().index[0]))

    fc = df.EA_KWH / (df.POT_KW * 24 * df.DIAS_MES)
    df["FACTOR_CARGA"] = fc.where((fc >= 0) & (fc <= 1))  # > 1 es físicamente imposible

    df = df.drop_duplicates(subset=["LOC_KEY", "ANIO", "MES"], keep="first")
    return df[["LOC_KEY", "LOCALIDAD_LIMPIA", "DEPARTAMENTO_LIMPIO", "ANIO", "MES",
               "EA_KWH", "HORAS_DIA", "FACTOR_CARGA"]].reset_index(drop=True)


def clasificar_tamano(mediana_kwh):
    return pd.cut(pd.Series(mediana_kwh, dtype=float), bins=CORTES_TAMANO, labels=TAMANOS,
                  include_lowest=True).astype("object")


def construir_variables(limpio, con_objetivo=True, siguiente_mes=False):
    """Tabla del modelo: una fila por localidad y mes objetivo, con variables de meses anteriores.

    con_objetivo: filas cuyo mes objetivo está observado (sirven para entrenar o reentrenar).
    siguiente_mes: filas para el mes posterior al último periodo del archivo (sirven para predecir).
    """
    d = limpio.copy()
    d["T"] = d.ANIO * 12 + (d.MES - 1)  # índice mensual continuo
    d = d.sort_values(["LOC_KEY", "T"])
    ea = d.set_index(["LOC_KEY", "T"])["EA_KWH"]
    hrs = d.set_index(["LOC_KEY", "T"])["HORAS_DIA"]
    fc = d.set_index(["LOC_KEY", "T"])["FACTOR_CARGA"]
    info = d.groupby("LOC_KEY")[["LOCALIDAD_LIMPIA", "DEPARTAMENTO_LIMPIO"]].first()

    objetivos = []
    if con_objetivo:
        objetivos.append(d[["LOC_KEY", "T", "EA_KWH"]].rename(columns={"EA_KWH": "energia_objetivo_kwh"}))
    if siguiente_mes:
        ult = d["T"].max()
        activas = d.loc[d["T"] == ult, ["LOC_KEY"]].assign(T=ult + 1, energia_objetivo_kwh=np.nan)
        objetivos.append(activas)
    obj = pd.concat(objetivos, ignore_index=True)

    def rezago(serie, k):
        idx = pd.MultiIndex.from_arrays([obj.LOC_KEY, obj["T"] - k])
        return serie.reindex(idx).to_numpy()

    obj["energia_lag1_kwh"] = rezago(ea, 1)
    obj = obj[pd.notna(obj.energia_lag1_kwh)].copy()  # sin el mes anterior no hay predicción posible
    obj["energia_lag2_kwh"] = rezago(ea, 2)
    obj["energia_lag12_kwh"] = rezago(ea, 12)
    obj["horas_dia_lag1"] = rezago(hrs, 1)
    obj["factor_carga_lag1"] = rezago(fc, 1)
    obj["sin_servicio_lag1"] = (obj.energia_lag1_kwh == 0).astype(int)

    # Tamaño: mediana de la energía positiva en TODOS los meses anteriores al objetivo (sin mirar el futuro)
    pos = {loc: (g["T"].to_numpy(), g.EA_KWH.to_numpy())
           for loc, g in d[d.EA_KWH > 0].groupby("LOC_KEY")}
    medianas = []
    for (loc, t_obj) in obj[["LOC_KEY", "T"]].itertuples(index=False):
        ts, vals = pos.get(loc, (np.array([]), np.array([])))
        h = vals[ts < t_obj]
        medianas.append(float(np.median(h)) if len(h) else 0.0)
    obj["tamano"] = clasificar_tamano(medianas).to_numpy()

    obj["id_localidad"] = obj.LOC_KEY
    obj["localidad"] = obj.LOC_KEY.map(info.LOCALIDAD_LIMPIA)
    obj["departamento"] = obj.LOC_KEY.map(info.DEPARTAMENTO_LIMPIO)
    obj["anio_objetivo"] = (obj["T"] // 12).astype(int)
    obj["mes_objetivo"] = (obj["T"] % 12 + 1).astype(int)
    cols = ["id_localidad", "localidad", "departamento", "anio_objetivo", "mes_objetivo", "tamano",
            "energia_lag1_kwh", "energia_lag2_kwh", "energia_lag12_kwh", "horas_dia_lag1",
            "factor_carga_lag1", "sin_servicio_lag1", "energia_objetivo_kwh"]
    out = obj[cols].sort_values(["anio_objetivo", "mes_objetivo", "id_localidad"]).reset_index(drop=True)
    if not con_objetivo:
        out = out.drop(columns="energia_objetivo_kwh")
    return out
