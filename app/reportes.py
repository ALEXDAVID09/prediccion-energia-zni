"""Reportes descargables en HTML autocontenido (se abren en cualquier navegador y se imprimen a PDF)."""
import html
from datetime import datetime

CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#0b0b0b;background:#f9f9f7;margin:0}
main{max-width:980px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px;border-bottom:1px solid #e3e2dd;padding-bottom:4px}
.meta{color:#52514e;font-size:13px}table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0;background:#fff}
th,td{border:1px solid #e3e2dd;padding:5px 8px;text-align:left;vertical-align:top}th{background:#f0efec}
td.n{text-align:right;font-variant-numeric:tabular-nums}.estado{display:inline-block;padding:4px 10px;border-radius:6px;font-weight:600}
.ok{background:#dff3df;color:#0a5c0a}.adv{background:#fff1d1;color:#7a5200}.err{background:#fbe0df;color:#8f1d1d}
figure{margin:12px 0;background:#fcfcfb;border:1px solid #e3e2dd;border-radius:8px;padding:10px}
figure img{max-width:100%;height:auto}figcaption{font-size:13px;color:#52514e;margin-bottom:6px}
ul{padding-left:20px}li{margin:3px 0}.nota{font-size:12px;color:#52514e}
"""


def _e(x):
    return html.escape(str(x))


def _pagina(titulo, cuerpo):
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (f"<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' "
            f"content='width=device-width,initial-scale=1'><title>{_e(titulo)}</title><style>{CSS}</style></head>"
            f"<body><main><h1>{_e(titulo)}</h1><p class='meta'>Generado por el sistema ZNI el {fecha}</p>"
            f"{cuerpo}</main></body></html>")


def _tabla(filas, columnas, numericas=()):
    cab = "".join(f"<th>{_e(t)}</th>" for _, t in columnas)
    cuerpo = ""
    for f in filas:
        celdas = ""
        for k, _ in columnas:
            v = f.get(k, "")
            if isinstance(v, float):
                v = f"{v:,.2f}"
            elif isinstance(v, list):
                v = ", ".join(map(str, v))
            celdas += f"<td class='{'n' if k in numericas else ''}'>{_e(v)}</td>"
        cuerpo += f"<tr>{celdas}</tr>"
    return f"<table><thead><tr>{cab}</tr></thead><tbody>{cuerpo}</tbody></table>"


def _clase(estado):
    return {"Compatible": "ok", "Compatible con advertencias": "adv"}.get(estado, "err")


def html_eda(r):
    partes = [f"<p>Archivo: <b>{_e(r['archivo'])}</b> · {r['filas']:,} filas · {r['columnas']} columnas · "
              f"{r['duplicados']} filas duplicadas</p>",
              "<h2>Observaciones generadas por el sistema</h2><ul>" +
              "".join(f"<li>{_e(o)}</li>" for o in r["observaciones"]) + "</ul>",
              "<h2>Variables y calidad de datos</h2>",
              _tabla(r["variables"], [("variable", "Variable"), ("tipo", "Tipo detectado"), ("faltantes", "Faltantes"),
                                      ("pct_faltantes", "% faltantes"), ("unicos", "Valores distintos"), ("nota", "Nota")],
                     ("faltantes", "pct_faltantes", "unicos"))]
    if r["numericas"]:
        filas = []
        for x in r["numericas"]:
            at = x["atipicos"] or {}
            filas.append({**x, "at": f"{at.get('n', '-')} ({at.get('pct', '-')}%) · {at.get('escala', '')}" if at else "-"})
        partes.append("<h2>Estadísticas descriptivas (numéricas)</h2>" + _tabla(
            filas, [("variable", "Variable"), ("n", "n"), ("media", "Media"), ("desv", "Desv."), ("min", "Mín"),
                    ("q1", "Q1"), ("mediana", "Mediana"), ("q3", "Q3"), ("max", "Máx"), ("at", "Atípicos (Tukey)")],
            ("n", "media", "desv", "min", "q1", "mediana", "q3", "max")) +
            "<p class='nota'>Atípicos: valores fuera de Q1 − 1,5·RIC y Q3 + 1,5·RIC. En variables no negativas con "
            "asimetría mayor que 2 la regla se aplica sobre log(1 + x).</p>")
    if r["categoricas"]:
        partes.append("<h2>Frecuencias (categóricas)</h2>")
        for c in r["categoricas"]:
            extra = f" · {c['otras']} registros en otras categorías" if c["otras"] else ""
            partes.append(f"<p><b>{_e(c['variable'])}</b> · {c['categorias']} categorías{extra}</p>" +
                          _tabla(c["top"], [("categoria", "Categoría"), ("n", "Registros"), ("pct", "%")], ("n", "pct")))
    if r["temporales"]:
        partes.append("<h2>Variables temporales</h2>" + _tabla(
            r["temporales"], [("variable", "Variable"), ("desde", "Desde"), ("hasta", "Hasta"), ("dias", "Días")], ("dias",)))
    if r["relaciones"]:
        partes.append("<h2>Relaciones entre variables</h2><ul>" +
                      "".join(f"<li>{_e(x['texto'])}</li>" for x in r["relaciones"]) + "</ul>")
    if r["graficos"]:
        partes.append("<h2>Visualizaciones</h2>")
        for titulo, img in r["graficos"]:
            partes.append(f"<figure><figcaption>{_e(titulo)}</figcaption><img alt='{_e(titulo)}' "
                          f"src='data:image/png;base64,{img}'></figure>")
    return _pagina("Reporte de análisis exploratorio (EDA)", "".join(partes))


def html_compatibilidad(d, archivo):
    clase = _clase(d["estado"])
    partes = [f"<p>Archivo: <b>{_e(archivo)}</b> · {d['filas']:,} filas · {d['columnas']} columnas · "
              f"modelo {d['version_modelo']} · uso: {_e(d['modo'])}</p>",
              f"<p>Estado final: <span class='estado {clase}'>{_e(d['estado'])}</span> · "
              f"{d['errores']} error(es) · {d['advertencias']} advertencia(s)</p>",
              "<p>" + ("Se pueden generar predicciones." if d["puede_predecir"] else
                       "No se generan predicciones. Corrija los problemas marcados como error y cargue de nuevo el archivo.") + "</p>",
              "<h2>Columnas</h2>",
              _tabla([{"a": ", ".join(d["columnas_esperadas"]), "b": ", ".join(d["columnas_recibidas"]),
                       "c": ", ".join(d["columnas_faltantes"]) or "ninguna",
                       "d": ", ".join(d["columnas_adicionales"]) or "ninguna"}],
                     [("a", "Esperadas"), ("b", "Recibidas"), ("c", "Faltantes"), ("d", "Adicionales")]),
              "<h2>Tipos de dato</h2>",
              _tabla(d["tipos"], [("variable", "Variable"), ("esperado", "Tipo esperado"), ("recibido", "Tipo recibido")]),
              "<h2>Errores y advertencias</h2>"]
    if d["hallazgos"]:
        partes.append(_tabla(d["hallazgos"], [("severidad", "Severidad"), ("nivel", "Nivel"), ("variable", "Variable"),
                                             ("mensaje", "Qué pasa"), ("esperado", "Esperado"), ("encontrado", "Encontrado"),
                                             ("registros_afectados", "Registros"), ("filas_ejemplo", "Filas (ejemplo)")],
                             ("registros_afectados",)))
    else:
        partes.append("<p>Sin errores ni advertencias.</p>")
    return _pagina("Reporte de compatibilidad", "".join(partes))


def html_predicciones(res, archivo):
    s = res["resumen"]
    partes = [f"<p>Archivo: <b>{_e(archivo)}</b> · modelo {_e(res['version_modelo'])} · estado de validación: "
              f"<span class='estado {_clase(res['estado_validacion'])}'>{_e(res['estado_validacion'])}</span></p>",
              "<h2>Resumen</h2>",
              _tabla([s], [("registros", "Registros"), ("total_kwh", "Energía total predicha (kWh)"),
                           ("mediana_kwh", "Mediana por localidad (kWh)"), ("min_kwh", "Mínimo"), ("max_kwh", "Máximo")],
                     ("registros", "total_kwh", "mediana_kwh", "min_kwh", "max_kwh")),
              "<p class='nota'>El intervalo del 80% sale de los errores del modelo en la validación temporal, separados por "
              "tamaño de localidad: en esa prueba, 8 de cada 10 valores reales cayeron dentro del rango.</p>",
              "<h2>Por tamaño de localidad</h2>",
              _tabla(res["por_tamano"], [("tamano", "Tamaño"), ("registros", "Registros"), ("total_kwh", "kWh predichos")],
                     ("registros", "total_kwh")),
              "<h2>Predicciones (primeras 200 filas)</h2>",
              _tabla(res["filas"][:200], [("fila", "Fila"), ("id_localidad", "Localidad (código)"), ("localidad", "Localidad"),
                                          ("periodo_objetivo", "Mes objetivo"), ("prediccion_kwh", "Predicción (kWh)"),
                                          ("limite_inferior_80", "Inferior 80%"), ("limite_superior_80", "Superior 80%"),
                                          ("aviso", "Aviso")],
                     ("prediccion_kwh", "limite_inferior_80", "limite_superior_80"))]
    return _pagina("Reporte de predicciones", "".join(partes))


def html_actualizacion(a):
    comp = a["comparacion"]
    partes = [f"<p>Versión activa: <b>{_e(a['version_activa'])}</b> · Versión candidata: <b>{_e(a['version_candidata'])}</b></p>",
              "<h2>Nuevos datos</h2>",
              _tabla([a["nuevos"]], [("archivo", "Archivo"), ("recibidos", "Registros recibidos"),
                                     ("integrados", "Integrados"), ("ya_existian", "Ya existían (no se duplican)"),
                                     ("sin_energia", "Con energía 0 (no se usan para entrenar)"), ("periodo", "Periodo")],
                     ("recibidos", "integrados", "ya_existian", "sin_energia")),
              f"<p>Registros de entrenamiento: {a['registros_antes']:,} antes → {a['registros_despues']:,} después.</p>",
              "<h2>Comparación con la misma métrica principal (MAE en escala log, menor es mejor)</h2>",
              _tabla(comp["tabla"], [("metrica", "Métrica"), ("activa", "Activa"), ("candidata", "Candidata"), ("mejor", "Mejor")]),
              f"<p class='nota'>{_e(comp['nota'])}</p>",
              "<h2>Lectura del sistema</h2>", f"<p>{_e(a['lectura'])}</p>",
              "<h2>Decisión</h2>",
              f"<p>{_e(a.get('decision') or 'Pendiente. La versión activa no se reemplaza automáticamente; ambas se conservan hasta registrar una decisión justificada.')}</p>",
              "<h2>EDA de los registros nuevos</h2><ul>" + "".join(f"<li>{_e(o)}</li>" for o in a["eda_nuevos"]) + "</ul>",
              "<h2>EDA del conjunto actualizado</h2><ul>" + "".join(f"<li>{_e(o)}</li>" for o in a["eda_actualizado"]) + "</ul>"]
    return _pagina("Reporte de actualización del modelo", "".join(partes))
