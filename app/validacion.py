"""Validación de compatibilidad de un archivo con el esquema del modelo activo.

Las reglas no están escritas aquí sino en los metadatos de la versión (copiados de config/esquema.json
al entrenar). Este módulo solo las aplica, en cuatro niveles: esquema, tipo de dato, contenido y
reglas de dominio. Nunca corrige los datos: si algo no cumple, lo informa.
"""
import io

import numpy as np
import pandas as pd

COMPATIBLE = "Compatible"
CON_ADVERTENCIAS = "Compatible con advertencias"
INCOMPATIBLE = "Incompatible"
MAX_EJEMPLOS = 5


class ArchivoIlegible(Exception):
    pass


def leer_archivo(contenido: bytes, nombre: str) -> pd.DataFrame:
    """Lee CSV (coma o punto y coma, UTF-8 o Latin-1) o Excel, todo como texto."""
    nombre = (nombre or "").lower()
    if not contenido:
        raise ArchivoIlegible("El archivo está vacío.")
    try:
        if nombre.endswith((".xlsx", ".xlsm", ".xls")):
            df = pd.read_excel(io.BytesIO(contenido), dtype=str)
        elif nombre.endswith((".csv", ".txt")):
            texto = None
            for cod in ("utf-8-sig", "latin-1"):
                try:
                    texto = contenido.decode(cod)
                    break
                except UnicodeDecodeError:
                    continue
            primera = texto.splitlines()[0] if texto.strip() else ""
            sep = ";" if primera.count(";") > primera.count(",") else ","
            df = pd.read_csv(io.StringIO(texto), dtype=str, sep=sep, keep_default_na=True)
        else:
            raise ArchivoIlegible("Formato no admitido. Cargue un archivo .csv o .xlsx.")
    except ArchivoIlegible:
        raise
    except Exception as e:  # el usuario ve un mensaje claro, no una traza
        raise ArchivoIlegible(f"No se pudo leer el archivo como tabla ({type(e).__name__}). "
                              "Revise que sea un CSV o Excel con una fila de encabezados.")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _filas(mask):
    """Números de fila tal como se ven en el archivo (la fila 1 es el encabezado)."""
    return [int(i) + 2 for i in np.flatnonzero(np.asarray(mask))[:MAX_EJEMPLOS]]


def tipo_detectado(s: pd.Series) -> str:
    v = s.dropna().astype(str).str.strip()
    v = v[v != ""]
    if v.empty:
        return "vacía (solo faltantes)"
    num = pd.to_numeric(v, errors="coerce")
    if num.notna().all():
        return "entero" if (num % 1 == 0).all() else "numérico decimal"
    if num.notna().mean() > 0.5:
        return "mixto (números y texto)"
    return "texto"


def _vacios(s):
    return s.isna() | (s.astype("string").str.strip() == "")


def validar(df: pd.DataFrame, meta: dict, modo: str = "prediccion"):
    """Devuelve (diagnóstico, datos tipados o None si es incompatible).

    modo='prediccion': archivo para generar predicciones.
    modo='actualizacion': registros nuevos que traen la variable objetivo real.
    """
    esquema = meta["esquema"]
    hallazgos = []

    def agregar(nivel, severidad, variable, mensaje, esperado="", encontrado="", afectados=0, filas=None):
        hallazgos.append({"nivel": nivel, "severidad": severidad, "variable": variable, "mensaje": mensaje,
                          "esperado": esperado, "encontrado": encontrado, "registros_afectados": int(afectados),
                          "filas_ejemplo": filas or []})

    variables = list(esquema["variables"])
    referencias = {r["nombre"]: r for r in esquema["referencias"]}
    objetivo = esquema["objetivo"]
    obligatorias = [v["nombre"] for v in variables]
    if modo == "actualizacion":
        variables.append({**objetivo, "admite_nulos": False})
        for r in referencias.values():
            if modo in r.get("obligatoria_para", []):
                variables.append({**r, "admite_nulos": False})
        obligatorias = [v["nombre"] for v in variables]

    recibidas = list(df.columns)
    conocidas = set(obligatorias) | set(referencias) | {objetivo["nombre"]}
    faltantes = [c for c in obligatorias if c not in recibidas]
    adicionales = [c for c in recibidas if c not in conocidas]
    repetidas = sorted({c for c in recibidas if recibidas.count(c) > 1})

    # ---------------- nivel 1: esquema
    if len(df) == 0:
        agregar("esquema", "error", "(archivo)", "El archivo no tiene registros.", "al menos 1 fila", "0 filas")
    for c in faltantes:
        agregar("esquema", "error", c, f"Falta la columna obligatoria '{c}'. Sin ella el modelo no puede ejecutarse.",
                "columna presente", "ausente")
    for c in repetidas:
        agregar("esquema", "error", c, f"La columna '{c}' aparece más de una vez.", "una sola vez", "repetida")
    if adicionales:
        agregar("esquema", "advertencia", ", ".join(adicionales),
                f"{len(adicionales)} columna(s) adicional(es) que el modelo no usa; se ignoran.",
                "solo columnas del esquema", f"{len(adicionales)} adicional(es)")
    if modo == "prediccion" and objetivo["nombre"] in recibidas:
        agregar("esquema", "advertencia", objetivo["nombre"],
                "El archivo trae la variable objetivo. Para predecir no se envía al modelo; se conserva solo como referencia.",
                "ausente en predicción", "presente")
    if modo == "prediccion" and "id_localidad" not in recibidas:
        agregar("esquema", "advertencia", "id_localidad",
                "No hay identificador de localidad; las predicciones se relacionarán con el número de fila.",
                "id_localidad presente", "ausente")

    tipado = pd.DataFrame(index=df.index)
    tipos = []
    if not repetidas:
        for var in variables:
            nombre = var["nombre"]
            if nombre not in recibidas:
                continue
            s = df[nombre]
            vacio = _vacios(s)
            tipos.append({"variable": nombre, "esperado": var["tipo"], "recibido": tipo_detectado(s)})

            # ---------------- nivel 2: tipo de dato
            if var["tipo"] in ("numerica", "entero"):
                num = pd.to_numeric(s.astype("string").str.strip(), errors="coerce")
                malos = ~vacio & num.isna()
                if malos.any():
                    ej = s[malos].astype(str).unique()[:3].tolist()
                    sugerencia = " Use punto como separador decimal y sin separador de miles." if any(
                        "," in e for e in ej) else ""
                    agregar("tipo", "error", nombre,
                            f"'{nombre}' debe ser {var['tipo']} y contiene valores no numéricos, por ejemplo {ej}.{sugerencia}",
                            var["tipo"], tipo_detectado(s), malos.sum(), _filas(malos))
                if var["tipo"] == "entero":
                    no_ent = num.notna() & (num % 1 != 0)
                    if no_ent.any():
                        agregar("tipo", "error", nombre, f"'{nombre}' debe ser un número entero.",
                                "entero", "decimal", no_ent.sum(), _filas(no_ent))
                tipado[nombre] = num
            else:
                tipado[nombre] = s.astype("string").str.strip().where(~vacio)

            # ---------------- nivel 3: contenido (faltantes y categorías)
            if vacio.any():
                if not var.get("admite_nulos", False):
                    agregar("contenido", "error", nombre,
                            f"'{nombre}' es necesaria para predecir y tiene {vacio.sum()} valor(es) faltante(s).",
                            "sin faltantes", f"{vacio.sum()} faltantes", vacio.sum(), _filas(vacio))
                elif vacio.mean() > 0.5:
                    agregar("contenido", "advertencia", nombre,
                            f"'{nombre}' admite faltantes, pero falta en el {vacio.mean():.0%} de los registros. "
                            "El pipeline usa la mediana del entrenamiento y la predicción pierde esa información.",
                            "pocos faltantes", f"{vacio.mean():.0%} faltantes", vacio.sum(), _filas(vacio))
            if var["tipo"] == "categorica":
                validas = var["categorias"]
                valores = tipado[nombre]
                desconocida = valores.notna() & ~valores.isin(validas)
                if desconocida.any():
                    nuevas = valores[desconocida].unique()[:5].tolist()
                    sev = "error" if var.get("desconocidas") == "error" else "advertencia"
                    agregar("contenido", sev, nombre,
                            f"'{nombre}' tiene categoría(s) que no existían en el entrenamiento: {nuevas}. "
                            f"{var.get('estrategia_desconocidas', '')}",
                            f"una de {len(validas)} categorías conocidas", ", ".join(map(str, nuevas)),
                            desconocida.sum(), _filas(desconocida))

            # ---------------- nivel 4: reglas de dominio
            rango = var.get("rango")
            if rango and var["tipo"] in ("numerica", "entero"):
                lo, hi = rango
                num = tipado[nombre]
                fuera = num.notna() & (((num < lo) if lo is not None else False) | ((num > hi) if hi is not None else False))
                if fuera.any():
                    texto_rango = f"entre {lo} y {hi}" if hi is not None else f"mayor o igual a {lo}"
                    agregar("dominio", "error", nombre,
                            f"'{nombre}' debe estar {texto_rango} ({var.get('descripcion', '')}).",
                            texto_rango, f"mín {num[fuera].min():g}, máx {num[fuera].max():g}",
                            fuera.sum(), _filas(fuera))

        for nombre, r in referencias.items():  # referencias opcionales en predicción: se conservan sin validar
            if nombre in recibidas and nombre not in tipado:
                tipado[nombre] = df[nombre].astype("string").str.strip()
        if objetivo["nombre"] in recibidas and objetivo["nombre"] not in tipado:
            tipado[objetivo["nombre"]] = pd.to_numeric(df[objetivo["nombre"]], errors="coerce")

        # reglas entre variables
        if {"sin_servicio_lag1", "energia_lag1_kwh"} <= set(tipado.columns):
            a, b = tipado["sin_servicio_lag1"], tipado["energia_lag1_kwh"]
            incoh = a.notna() & b.notna() & ((a == 1) != (b == 0))
            if incoh.any():
                agregar("dominio", "error", "sin_servicio_lag1 / energia_lag1_kwh",
                        "sin_servicio_lag1 debe ser 1 exactamente cuando energia_lag1_kwh es 0.",
                        "coherentes", "incoherentes", incoh.sum(), _filas(incoh))
        clave = [c for c in ("id_localidad", "anio_objetivo", "mes_objetivo") if c in tipado.columns]
        if len(clave) == 3:
            dup = tipado.duplicated(subset=clave, keep=False)
            if dup.any():
                agregar("contenido", "advertencia", ", ".join(clave),
                        "Hay registros repetidos para la misma localidad y mes objetivo.",
                        "un registro por localidad y mes", f"{dup.sum()} filas repetidas", dup.sum(), _filas(dup))

    errores = [h for h in hallazgos if h["severidad"] == "error"]
    advertencias = [h for h in hallazgos if h["severidad"] == "advertencia"]
    estado = INCOMPATIBLE if errores else (CON_ADVERTENCIAS if advertencias else COMPATIBLE)
    diag = {
        "estado": estado,
        "modo": modo,
        "version_modelo": meta["version"],
        "filas": int(len(df)),
        "columnas": int(df.shape[1]),
        "columnas_esperadas": obligatorias,
        "columnas_recibidas": recibidas,
        "columnas_faltantes": faltantes,
        "columnas_adicionales": adicionales,
        "tipos": tipos,
        "errores": len(errores),
        "advertencias": len(advertencias),
        "hallazgos": hallazgos,
        "puede_predecir": estado != INCOMPATIBLE,
    }
    return diag, (tipado if estado != INCOMPATIBLE else None)
