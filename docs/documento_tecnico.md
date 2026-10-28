# Documento técnico: sistema web de análisis y predicción de energía en ZNI

*Borrador para el entregable 7 (máximo cinco páginas).*

## 1. Problema y modelo

La base abierta «Estado de la prestación del servicio de energía en Zonas No Interconectadas» trae una fila por localidad y mes (enero de 2020 a enero de 2026). El modelo continúa lo propuesto en la sección 11 del análisis: **predecir la energía activa del mes siguiente de cada localidad**, para anticipar la demanda y planear combustible y logística.

- **Unidad de observación:** localidad × mes objetivo. Del CSV limpio salen 5.588 pares utilizables en 218 localidades.
- **Variables predictoras:** solo información de meses anteriores. Son la energía de 1, 2 y 12 meses antes, el mes objetivo (en seno y coseno), el tamaño de la localidad (mediana de su energía positiva antes del mes objetivo), el departamento, las horas de servicio y el factor de carga del mes anterior, y una bandera de mes anterior sin energía.
- **Fuga de información evitada:** la potencia, la energía reactiva, las horas y la fecha de demanda del mismo mes objetivo no entran al modelo. El tamaño se calcula solo con meses anteriores.
- **Meses con energía 0:** no se usan para entrenar ni validar, porque en la fuente un 0 puede ser «sin servicio» o «sin dato» (Actividad 3) y no describe la demanda. Con ellos, cuarenta ceros dominaban el error y ningún modelo superaba al pronóstico ingenuo.
- **Algoritmo:** `HistGradientBoostingRegressor` dentro de un `TransformedTargetRegressor` que aprende log(1 + kWh) y devuelve kWh. Se compararon tres opciones con la misma validación: HistGradientBoosting (MAE log 0,266), Ridge lineal (0,297) y el pronóstico ingenuo, que repite el mes anterior (0,362). Los hiperparámetros se eligieron entre unas pocas configuraciones en esa misma validación, lo cual es una limitación (ver sección 7).

## 2. Estrategia de validación

Es temporal y nunca aleatoria. Se reservan como prueba los **12 meses objetivo más recientes** y se entrena con todos los anteriores. La v1 entrena de 2020-02 a 2024-06 y prueba de 2024-07 a 2025-06 (1.093 registros). Después, el modelo definitivo se reajusta con todos los datos de la versión.

- **Métrica principal:** MAE en escala log(1 + kWh) = **0,266**, es decir, un error relativo mediano del 12,3%. Trata igual a localidades grandes y pequeñas; si no, San Andrés, que concentra cerca de la mitad de la energía, dominaría la métrica.
- **Secundarias:** WAPE del 8,2%, mejora del 26,5% frente al pronóstico ingenuo y MAE log por tamaño (grandes 0,06, medianas 0,09, pequeñas 0,25 y muy pequeñas 0,40).
- **Intervalo del 80%:** se toman los percentiles 10 y 90 de los residuos en escala log de la validación, por tamaño de localidad, y se aplican a cada predicción. No es una probabilidad (el problema es de regresión), sino el rango donde cayeron 8 de cada 10 valores reales en la prueba.

## 3. Arquitectura

Ver `docs/arquitectura.png`. Tiene siete componentes:

1. **Interfaz web** (`app/static/index.html`): HTML y JavaScript sin dependencias, servida por la propia API. Tiene cuatro pestañas: analizar, validar y predecir, modelo y versiones, y preparar.
2. **API** (`app/main.py`, FastAPI): recibe archivos, coordina los módulos y devuelve JSON. Se documenta sola en `/docs`. Un manejador global convierte cualquier error en un mensaje comprensible, sin trazas.
3. **Validación** (`app/validacion.py`): aplica el esquema del modelo activo.
4. **EDA** (`app/eda.py`): análisis dinámico según los tipos detectados.
5. **Pipeline predictivo** (`app/modelo.py`): todo el preprocesamiento (log, imputación por mediana con indicador, one-hot del departamento, codificación ordinal del tamaño, mes cíclico) vive dentro del pipeline de scikit-learn y se guarda con joblib. Al predecir se carga y nunca se reajusta.
6. **Reportes** (`app/reportes.py`): HTML autocontenido, más CSV y Excel para las predicciones y JSON para la compatibilidad. Cada carga crea una carpeta de proceso en `datos/procesos/<id>/`.
7. **Actualización y versiones** (`modelos/registro.json`): cada entrenamiento crea `modelos/vN/` con el pipeline, los metadatos y los datos de entrenamiento.

## 4. Esquema y validación

Las reglas viven en `config/esquema.json` y se copian a `metadatos.json` de cada versión al entrenar, con las categorías de departamento aprendidas. El validador solo lee esos metadatos; la interfaz no contiene reglas. Por variable se guarda el nombre, el tipo, si admite faltantes, las categorías válidas y la estrategia para categorías desconocidas, el rango de dominio y una descripción. También se guardan el objetivo, las variables que no se envían al modelo (`id_localidad`, `localidad`, `anio_objetivo` y el objetivo), la versión, la fecha y la métrica.

| Nivel | Qué se revisa | Respuesta |
|---|---|---|
| Esquema | columnas obligatorias, repetidas o adicionales; archivo vacío | falta o repetida: error; adicional: advertencia |
| Tipo | numérico o entero; detecta texto y formato español | error con ejemplos, filas y tipo recibido |
| Contenido | faltantes en variables que no los admiten; categorías nuevas; registros repetidos | faltante: error. Departamento nuevo: advertencia (el codificador lo ignora). Tamaño fuera de escala: error. Faltantes por encima del 50% en una variable que los admite: advertencia |
| Dominio | kWh ≥ 0, mes de 1 a 12, horas de 0 a 24, factor de carga de 0 a 1, coherencia entre `sin_servicio_lag1` y la energía | error con la regla incumplida |

Con al menos un error el estado es **Incompatible** y no se predice. Si solo hay advertencias, el estado es **Compatible con advertencias**. Si no hay hallazgos, es **Compatible**. El sistema nunca corrige datos: informa y el usuario vuelve a cargar el archivo corregido. Si detecta el formato crudo del portal, sugiere usar «Preparar», que aplica la limpieza documentada de la Actividad 3 de forma explícita, en un paso que el usuario decide.

## 5. Flujo de predicción

Archivo → lectura como texto (CSV con coma o punto y coma, o Excel) → validación → solo si es compatible, conversión de tipos → `pipeline.predict` (sin reajustar) → intervalo del 80% → salida con fila, `id_localidad`, mes objetivo, predicción, límites y aviso. Se guardan el CSV, el Excel y el reporte HTML con un resumen total y por tamaño. El identificador acompaña cada predicción, pero no es predictor.

## 6. Actualización del modelo

1. Los registros nuevos con `energia_objetivo_kwh` se validan en modo *actualización*, que exige además el objetivo, `id_localidad` y `anio_objetivo`.
2. Se descartan los que ya existían (misma localidad y mes) y se calcula el EDA de los nuevos y del conjunto actualizado.
3. Se reentrena el mismo pipeline con la misma validación temporal y se guarda como versión **candidata**. La activa no cambia.
4. **Comparación:** se usa la misma métrica principal y las secundarias de la validación de cada versión. Como los periodos de prueba difieren, se agrega el MAE log de ambas sobre los registros nuevos que ninguna usó para entrenar.
5. El usuario registra **activar** o **descartar** con una justificación obligatoria. La activa anterior pasa a *histórico*, y la decisión queda en `registro.json` y en el reporte de actualización.

En la demostración (nuevos meses de 2025-07 a 2026-01), la candidata v2 obtiene un MAE log de 0,302 frente a 0,266 de la v1, y sobre los registros nuevos 0,297 frente a 0,283. Por eso lo justificado es **conservar la v1**. Los meses recientes son más difíciles: hay más localidades reportando desde 2025 y faltan las horas desde 2025-12.

## 7. Limitaciones conocidas

- **Cambio de cobertura de 2025:** el número de localidades que reportan cada mes salta en 2025. El modelo puede aprender patrones de reporte y no solo de consumo.
- **Formato de la fuente:** desde 2025-12 las horas y la potencia perdieron la coma decimal y se dejan como faltantes. Las predicciones de 2026 no usan esa información y el sistema lo advierte.
- **Localidades muy pequeñas:** son poco predecibles (MAE log de 0,40). Su intervalo es amplio y conviene leerlo antes que el valor puntual.
- **Meses con energía 0:** el modelo no anticipa meses sin servicio ni sin dato, porque se excluyeron del entrenamiento.
- **Selección de hiperparámetros:** se eligieron sobre el mismo periodo de prueba que se reporta, así que la métrica puede ser algo optimista.
- **Almacenamiento:** el registro de versiones es un archivo JSON local, adecuado para un solo usuario. Con varios usuarios simultáneos haría falta una base de datos.
- **Unidades:** las unidades de energía y potencia se asumen (kWh y kW), como en el análisis.
