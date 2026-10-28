import json
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
# Las pruebas automáticas apuntan estas carpetas a un directorio temporal para no tocar los modelos reales.
DIR_MODELOS = Path(os.environ.get("ZNI_DIR_MODELOS", BASE / "modelos"))
REGISTRO = DIR_MODELOS / "registro.json"
DIR_PROCESOS = Path(os.environ.get("ZNI_DIR_PROCESOS", BASE / "datos" / "procesos"))  # resultados y reportes de cada carga
ESQUEMA_BASE = json.loads((BASE / "config" / "esquema.json").read_text(encoding="utf-8"))
MAX_MB = 25
