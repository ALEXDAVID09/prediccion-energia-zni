"""Pruebas obligatorias de la actividad: un caso por escenario. Ejecutar con: pytest -q"""
import os
import shutil
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
ESC = BASE / "pruebas" / "escenarios"


@pytest.fixture(scope="module")
def cliente(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("zni")
    shutil.copytree(BASE / "modelos", tmp / "modelos")  # no se tocan los modelos reales
    os.environ["ZNI_DIR_MODELOS"] = str(tmp / "modelos")
    os.environ["ZNI_DIR_PROCESOS"] = str(tmp / "procesos")
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def enviar(cliente, ruta, archivo, **datos):
    with open(ESC / archivo, "rb") as f:
        return cliente.post(ruta, files={"archivo": (archivo, f, "text/csv")}, data=datos)


def niveles(r):
    return {(h["severidad"], h["nivel"], h["variable"]) for h in r.json()["diagnostico"]["hallazgos"]}


def test_1_compatible_genera_predicciones(cliente):
    r = enviar(cliente, "/api/predecir", "01_compatible.csv")
    assert r.status_code == 200
    j = r.json()
    assert j["diagnostico"]["estado"] == "Compatible"
    assert j["resumen"]["registros"] == len(j["filas"]) > 0
    assert all(f["limite_inferior_80"] <= f["prediccion_kwh"] <= f["limite_superior_80"] for f in j["filas"])
    assert cliente.get(j["reportes"]["predicciones_csv"]).status_code == 200


def test_2_falta_variable_bloquea(cliente):
    r = enviar(cliente, "/api/predecir", "02_falta_variable.csv")
    assert r.status_code == 422
    assert ("error", "esquema", "energia_lag1_kwh") in niveles(r)
    assert "filas" not in r.json()


def test_3_tipo_incompatible(cliente):
    r = enviar(cliente, "/api/predecir", "03_tipo_incompatible.csv")
    assert r.status_code == 422
    assert {("error", "tipo", "mes_objetivo"), ("error", "tipo", "energia_lag1_kwh")} <= niveles(r)


def test_4_faltantes_en_variable_necesaria(cliente):
    r = enviar(cliente, "/api/predecir", "04_faltantes.csv")
    assert r.status_code == 422
    h = [h for h in r.json()["diagnostico"]["hallazgos"] if h["nivel"] == "contenido"][0]
    assert h["variable"] == "energia_lag1_kwh" and h["registros_afectados"] == 5


def test_5_categoria_nueva(cliente):
    r = enviar(cliente, "/api/predecir", "05a_categoria_nueva_departamento.csv")
    assert r.status_code == 200 and r.json()["diagnostico"]["estado"] == "Compatible con advertencias"
    assert sum(1 for f in r.json()["filas"] if f["aviso"]) == 3
    r = enviar(cliente, "/api/predecir", "05b_categoria_fuera_de_escala.csv")
    assert r.status_code == 422 and ("error", "contenido", "tamano") in niveles(r)


def test_6_columnas_adicionales(cliente):
    r = enviar(cliente, "/api/predecir", "06_columnas_adicionales.csv")
    assert r.status_code == 200
    assert r.json()["diagnostico"]["columnas_adicionales"] == ["operador", "observaciones"]


def test_7_no_predice_pero_si_eda(cliente):
    r = enviar(cliente, "/api/predecir", "07_solo_eda_portal_crudo.csv")
    assert r.status_code == 422 and "sugerencia" in r.json()["diagnostico"]
    r = enviar(cliente, "/api/eda", "07_solo_eda_portal_crudo.csv")
    assert r.status_code == 200
    tipos = {v["variable"]: v["tipo"] for v in r.json()["eda"]["variables"]}
    assert tipos["ENERGÍA ACTIVA"] == "numérica" and tipos["FECHA DE DEMANDA MÁXIMA"] == "temporal"
    assert len(r.json()["graficos"]) >= 5
    r = enviar(cliente, "/api/predecir", "07b_reglas_de_dominio.csv")
    assert {h["variable"] for h in r.json()["diagnostico"]["hallazgos"] if h["nivel"] == "dominio"} == {
        "horas_dia_lag1", "factor_carga_lag1", "sin_servicio_lag1 / energia_lag1_kwh"}


def test_8_actualizacion_genera_candidata_sin_reemplazar(cliente):
    r = enviar(cliente, "/api/modelo/actualizar", "08_nuevos_etiquetados.csv")
    assert r.status_code == 200
    j = r.json()
    estados = {v["version"]: v["estado"] for v in cliente.get("/api/modelo/versiones").json()["versiones"]}
    assert estados["v1"] == "activo" and estados[j["version_candidata"]] == "candidato"
    assert cliente.get("/api/modelo").json()["version"] == "v1"  # no se sustituye sola
    r = cliente.post(f"/api/modelo/versiones/{j['version_candidata']}/decision",
                     data={"accion": "activar", "justificacion": "prueba automática del flujo", "proceso": j["proceso"]})
    assert r.status_code == 200
    assert cliente.get("/api/modelo").json()["version"] == j["version_candidata"]
    estados = {v["version"]: v["estado"] for v in cliente.get("/api/modelo/versiones").json()["versiones"]}
    assert estados["v1"] == "historico"


def test_archivo_ilegible_sin_traza(cliente):
    r = cliente.post("/api/eda", files={"archivo": ("x.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code == 400 and "Traceback" not in r.text


def test_sitio_y_recursos(cliente):
    assert cliente.get("/").status_code == 200
    assert cliente.get("/js/app.js").status_code == 200
    esc = cliente.get("/api/escenarios").json()["escenarios"]
    assert len(esc) >= 10 and cliente.get(esc[0]["url"]).status_code == 200
    assert cliente.get("/api/escenarios/../config/esquema.json").status_code == 404
    procesos = cliente.get("/api/procesos").json()["procesos"]
    assert procesos and all("reportes" in p for p in procesos)
