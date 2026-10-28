"""EDA automático: decide qué analizar y qué graficar según los tipos de variable que encuentra.

Funciona con cualquier tabla (también con archivos incompatibles con el modelo). Criterios:
- Tipo de variable: numérica si >=95% de los valores no vacíos son números (también en formato español
  "1.234,5"); temporal si >=90% se interpretan como fecha; identificador si es texto casi único o un
  código ("ID ..."); categórica si tiene pocos valores distintos; texto libre en otro caso.
- Atípicos: regla de Tukey (fuera de Q1 - 1,5·RIC y Q3 + 1,5·RIC). Si la variable es no negativa y muy
  asimétrica (asimetría > 2), la regla se aplica sobre log(1 + x), porque en escala original marcaría
  como atípicos a todos los valores grandes legítimos.
- Relaciones: correlación de Spearman (robusta a asimetría). Se reporta como asociación, no como causa.
"""
import base64
import io
import re
import warnings

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

AZUL, GRIS, TINTA, TINTA2 = "#2a78d6", "#d8d7d2", "#0b0b0b", "#52514e"
plt.rcParams.update({"font.size": 9, "axes.edgecolor": GRIS, "axes.labelcolor": TINTA2, "xtick.color": TINTA2,
                     "ytick.color": TINTA2, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": "#ecebe7", "grid.linewidth": 0.6, "figure.dpi": 110,
                     "axes.titlesize": 10, "axes.titlecolor": TINTA, "figure.facecolor": "#fcfcfb",
                     "axes.facecolor": "#fcfcfb"})
MAX_NUM_GRAF, MAX_CAT_GRAF = 8, 6
_mpl = tuple(int(x) for x in matplotlib.__version__.split(".")[:2])
_HORIZONTAL = {"orientation": "horizontal"} if _mpl >= (3, 10) else {"vert": False}


def _png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _num_es(s):
    return pd.to_numeric(s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False), errors="coerce")


def clasificar(df):
    """Devuelve {columna: (tipo, serie convertida, nota)}."""
    out = {}
    n = len(df)
    for c in df.columns:
        s = df[c].astype("string").str.strip()
        s = s.where(s != "")
        v = s.dropna()
        if v.empty:
            out[c] = ("vacía", s, "sin valores")
            continue
        nu = v.nunique()
        es_codigo = bool(re.match(r"^(id|cod|código|codigo)[ _]", c.strip().lower())) or c.strip().lower() in ("id", "codigo")
        num = pd.to_numeric(v, errors="coerce")
        nota = ""
        patron_es = r"^-?\d{1,3}(?:\.\d{3})*(?:,\d+)?$"
        if num.notna().mean() < 1 and v.str.fullmatch(patron_es).mean() >= 0.95:
            num, nota = _num_es(v), "formato español (punto de miles, coma decimal)"
        if es_codigo:
            out[c] = ("identificador", s, "código: no se calculan estadísticas")
        elif num.notna().mean() >= 0.95:
            conv = pd.Series(pd.to_numeric(num, errors="coerce").to_numpy(dtype=float, na_value=np.nan),
                             index=v.index).reindex(s.index)
            if nu <= 2:
                out[c] = ("categórica", s, "binaria" if nu == 2 else "")
            else:
                out[c] = ("numérica", conv.astype(float), nota)
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fechas = pd.to_datetime(v, errors="coerce", format="mixed")
            if fechas.notna().mean() >= 0.9 and not v.str.fullmatch(r"\d{1,4}").all():
                conv = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
                conv[v.index] = fechas
                out[c] = ("temporal", conv, "")
            elif nu > 0.9 * len(v) and nu > 50:
                out[c] = ("identificador", s, "casi todos los valores son distintos")
            elif nu <= 50 or nu / max(n, 1) < 0.5:
                out[c] = ("categórica", s, "")
            else:
                out[c] = ("texto", s, "texto libre con muchos valores")
    return out


def _atipicos(x):
    x = x.dropna()
    if len(x) < 8:
        return None
    asim = float(x.skew())
    escala = "original"
    y = x
    if x.min() >= 0 and asim > 2:
        y, escala = np.log1p(x), "log(1 + x)"
    q1, q3 = np.percentile(y, [25, 75])
    ric = q3 - q1
    mask = (y < q1 - 1.5 * ric) | (y > q3 + 1.5 * ric)
    return {"n": int(mask.sum()), "pct": round(float(mask.mean() * 100), 2), "escala": escala,
            "asimetria": round(asim, 2)}


def analizar(df, nombre_archivo=""):
    tipos = clasificar(df)
    n = len(df)
    res = {"archivo": nombre_archivo, "filas": int(n), "columnas": int(df.shape[1]),
           "duplicados": int(df.duplicated().sum()), "variables": [], "numericas": [], "categoricas": [],
           "temporales": [], "relaciones": [], "graficos": [], "observaciones": []}
    for c, (t, s, nota) in tipos.items():
        falt = int(s.isna().sum())
        res["variables"].append({"variable": c, "tipo": t, "faltantes": falt,
                                 "pct_faltantes": round(falt / max(n, 1) * 100, 2),
                                 "unicos": int(s.nunique()), "nota": nota})

    num_cols = [c for c, (t, _, _) in tipos.items() if t == "numérica"]
    cat_cols = [c for c, (t, _, _) in tipos.items() if t == "categórica"]
    tem_cols = [c for c, (t, _, _) in tipos.items() if t == "temporal"]

    for c in num_cols:
        x = tipos[c][1]
        d = x.describe()
        at = _atipicos(x)
        res["numericas"].append({"variable": c, "n": int(d["count"]), "media": float(d["mean"]),
                                 "desv": float(d["std"]) if d["count"] > 1 else 0.0, "min": float(d["min"]),
                                 "q1": float(d["25%"]), "mediana": float(d["50%"]), "q3": float(d["75%"]),
                                 "max": float(d["max"]), "atipicos": at})
    for c in cat_cols:
        s = tipos[c][1]
        vc = s.value_counts()
        top = [{"categoria": str(k), "n": int(v), "pct": round(v / max(s.notna().sum(), 1) * 100, 2)}
               for k, v in vc.head(10).items()]
        res["categoricas"].append({"variable": c, "categorias": int(len(vc)), "top": top,
                                   "otras": int(vc.iloc[10:].sum()) if len(vc) > 10 else 0})
    for c in tem_cols:
        s = tipos[c][1]
        res["temporales"].append({"variable": c, "desde": str(s.min()), "hasta": str(s.max()),
                                  "dias": int((s.max() - s.min()).days) if s.notna().any() else 0})

    # ------------------------------------------------------------ relaciones (Spearman)
    usar = [c for c in num_cols if tipos[c][1].nunique() > 2][:15]
    if len(usar) >= 2:
        m = pd.DataFrame({c: tipos[c][1] for c in usar})
        corr = m.corr(method="spearman", min_periods=10)
        pares = []
        for i, a in enumerate(usar):
            for b in usar[i + 1:]:
                r = corr.loc[a, b]
                if pd.notna(r):
                    pares.append((a, b, float(r), int(m[[a, b]].dropna().shape[0])))
        pares.sort(key=lambda p: -abs(p[2]))
        for a, b, r, k in pares[:6]:
            fuerza = "muy fuerte" if abs(r) >= 0.8 else "fuerte" if abs(r) >= 0.6 else "moderada" if abs(r) >= 0.4 else "débil"
            sentido = "positiva" if r > 0 else "negativa"
            res["relaciones"].append({"a": a, "b": b, "rho": round(r, 3), "n": k,
                                      "texto": f"{a} y {b}: asociación {fuerza} {sentido} (Spearman ρ = {r:.2f}, n = {k}). "
                                               "Indica que tienden a moverse juntas, no que una cause la otra."})
        res["graficos"].append(("Correlación de Spearman entre variables numéricas", _heatmap(corr)))
        if pares:
            a, b = pares[0][0], pares[0][1]
            res["graficos"].append((f"Dispersión del par más asociado: {a} vs {b}",
                                    _dispersion(tipos[a][1], tipos[b][1], a, b)))

    # ------------------------------------------------------------ gráficos por tipo
    for c in num_cols[:MAX_NUM_GRAF]:
        res["graficos"].append((f"Distribución de {c}", _histograma_caja(tipos[c][1], c)))
    for c in [c for c in cat_cols if 1 < tipos[c][1].nunique()][:MAX_CAT_GRAF]:
        res["graficos"].append((f"Frecuencias de {c}", _barras(tipos[c][1], c)))
    for c in tem_cols[:2]:
        res["graficos"].append((f"Registros por mes según {c}", _serie(tipos[c][1], c)))

    res["observaciones"] = _observaciones(res, tipos)
    return res


def _observaciones(res, tipos):
    obs = []
    if res["filas"] == 0:
        return ["El archivo no tiene registros."]
    if res["duplicados"]:
        obs.append(f"Hay {res['duplicados']} fila(s) idénticas en todas las columnas.")
    for v in res["variables"]:
        if v["pct_faltantes"] >= 20:
            obs.append(f"{v['variable']} tiene {v['pct_faltantes']:.1f}% de valores faltantes.")
        if v["unicos"] == 1 and v["faltantes"] < res["filas"]:
            obs.append(f"{v['variable']} es constante (un solo valor); no aporta información.")
        if v["nota"].startswith("formato español"):
            obs.append(f"{v['variable']} es numérica pero viene en formato español; se convirtió solo para este análisis.")
    for c in res["categoricas"]:
        if c["top"] and c["top"][0]["pct"] >= 50 and c["categorias"] > 1:
            obs.append(f"En {c['variable']} predomina '{c['top'][0]['categoria']}' ({c['top'][0]['pct']:.1f}%).")
    for x in res["numericas"]:
        at = x["atipicos"]
        if at and at["pct"] >= 1:
            obs.append(f"{x['variable']}: {at['n']} posibles atípicos ({at['pct']:.1f}%) según Tukey en escala {at['escala']}.")
        if at and at["asimetria"] > 2:
            obs.append(f"{x['variable']} es muy asimétrica (asimetría {at['asimetria']:.1f}): la media "
                       f"({x['media']:,.1f}) supera mucho a la mediana ({x['mediana']:,.1f}).")
        if x["min"] < 0:
            obs.append(f"{x['variable']} tiene valores negativos (mínimo {x['min']:g}).")
    for r in res["relaciones"]:
        if abs(r["rho"]) >= 0.8:
            obs.append(f"{r['a']} y {r['b']} están muy asociadas (ρ = {r['rho']:.2f}); pueden ser redundantes.")
    return obs or ["No se encontraron problemas de calidad destacables con los criterios aplicados."]


# ---------------------------------------------------------------- gráficos

def _histograma_caja(x, nombre):
    x = x.dropna()
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(6, 3.2), height_ratios=[3, 1], sharex=True)
    log = len(x) and x.min() >= 0 and x.skew() > 2
    y = np.log1p(x) if log else x
    a1.hist(y, bins=30, color=AZUL, edgecolor="#fcfcfb", linewidth=0.6)
    a1.set_ylabel("registros")
    a2.boxplot(y, **_HORIZONTAL, widths=0.5, patch_artist=True,
               boxprops=dict(facecolor="#cde2fb", edgecolor=AZUL), medianprops=dict(color=TINTA),
               whiskerprops=dict(color=AZUL), capprops=dict(color=AZUL),
               flierprops=dict(marker="o", markersize=3, markerfacecolor=TINTA2, markeredgewidth=0, alpha=.5))
    a2.set_yticks([])
    a2.set_xlabel(f"log(1 + {nombre})" if log else nombre)
    return _png(fig)


def _barras(s, nombre):
    vc = s.value_counts()
    top = vc.head(12)[::-1]
    fig, ax = plt.subplots(figsize=(6, 0.25 * len(top) + 0.8))
    ax.barh([str(k)[:40] for k in top.index], top.values, color=AZUL, height=0.7)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("registros" + (f" (se muestran 12 de {len(vc)} categorías)" if len(vc) > 12 else ""))
    return _png(fig)


def _heatmap(corr):
    k = len(corr)
    fig, ax = plt.subplots(figsize=(0.55 * k + 2.4, 0.5 * k + 1.6))
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(k), [c[:22] for c in corr.columns], rotation=45, ha="right")
    ax.set_yticks(range(k), [c[:22] for c in corr.index])
    ax.grid(False)
    for i in range(k):
        for j in range(k):
            v = corr.values[i, j]
            if pd.notna(v):
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=7,
                        color="white" if abs(v) > 0.6 else TINTA)
    fig.colorbar(im, ax=ax, shrink=0.7, label="ρ de Spearman")
    return _png(fig)


def _dispersion(a, b, na, nb):
    d = pd.DataFrame({"a": a, "b": b}).dropna()
    if len(d) > 4000:
        d = d.sample(4000, random_state=0)
    fig, ax = plt.subplots(figsize=(5, 3.6))
    ax.scatter(d.a, d.b, s=9, color=AZUL, alpha=0.45, linewidths=0)
    if (d > 0).all().all() and d.a.max() / max(d.a.min(), 1e-9) > 1e3 and d.b.max() / max(d.b.min(), 1e-9) > 1e3:
        ax.set_xscale("log")
        ax.set_yscale("log")
    ax.set_xlabel(na)
    ax.set_ylabel(nb)
    return _png(fig)


def _serie(s, nombre):
    c = s.dropna().dt.to_period("M").value_counts().sort_index()
    fig, ax = plt.subplots(figsize=(6.5, 2.6))
    ax.plot(c.index.to_timestamp(), c.values, color=AZUL, linewidth=2)
    ax.set_ylabel("registros")
    return _png(fig)
