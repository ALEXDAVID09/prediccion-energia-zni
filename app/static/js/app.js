// Sitio web del sistema ZNI. Todo lo consume de la API (/api/...).
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmt = (v, d = 0) => typeof v === 'number' ? v.toLocaleString('es-CO', {maximumFractionDigits: d}) : esc(v);
const clase = e => e === 'Compatible' ? 'ok' : e === 'Compatible con advertencias' ? 'adv' : 'err';
const cargando = t => `<div class="cargando"><span class="giro"></span>${esc(t)}</div>`;
const error = m => `<div class="msg err">${esc(m)}</div>`;
const PAGINAS = ['inicio', 'analizar', 'predecir', 'preparar', 'modelo', 'reportes', 'ejemplos', 'acerca'];
const NOMBRES_REPORTE = {eda: 'Reporte EDA', compatibilidad: 'Compatibilidad', compatibilidad_json: 'Compatibilidad (JSON)',
  predicciones_csv: 'Predicciones CSV', predicciones_xlsx: 'Predicciones Excel', predicciones_html: 'Reporte de predicciones',
  actualizacion: 'Reporte de actualización'};
const TIPOS_PROCESO = {eda: 'Análisis exploratorio', validacion: 'Validación', prediccion: 'Predicción', actualizacion: 'Actualización del modelo'};

// ---------------------------------------------------------------- navegación
function ir() {
  const p = PAGINAS.includes(location.hash.slice(1)) ? location.hash.slice(1) : 'inicio';
  PAGINAS.forEach(x => $(`#p-${x}`).classList.toggle('activa', x === p));
  document.querySelectorAll('.lateral a.nav').forEach(a => a.toggleAttribute('aria-current', a.getAttribute('href') === `#${p}`));
  document.querySelectorAll('.lateral a.nav[aria-current]').forEach(a => a.setAttribute('aria-current', 'page'));
  $('#lateral').classList.remove('abierta');
  window.scrollTo(0, 0);
  if (p === 'reportes') cargarReportes();
  if (p === 'ejemplos') cargarEjemplos();
}
window.addEventListener('hashchange', ir);
$('#abrir-menu').onclick = e => { e.stopPropagation(); $('#lateral').classList.toggle('abierta'); };
document.addEventListener('click', e => { if (!e.target.closest('#lateral')) $('#lateral').classList.remove('abierta'); });

// ---------------------------------------------------------------- zonas de carga
const archivos = {};
function prepararZona(z) {
  const id = z.dataset.zona;
  z.innerHTML = `<input type="file" accept=".csv,.xlsx,.xls"><b>Arrastre aquí un archivo CSV o Excel</b><span>o haga clic para elegirlo</span>`;
  const input = z.querySelector('input');
  const fijar = f => { archivos[id] = f; z.classList.add('lista');
    z.querySelector('b').textContent = f.name; z.querySelector('span').textContent = `${(f.size / 1024).toFixed(0)} KB · clic para cambiarlo`; };
  z.onclick = () => input.click();
  input.onchange = () => input.files[0] && fijar(input.files[0]);
  z.ondragover = e => { e.preventDefault(); z.classList.add('encima'); };
  z.ondragleave = () => z.classList.remove('encima');
  z.ondrop = e => { e.preventDefault(); z.classList.remove('encima'); e.dataTransfer.files[0] && fijar(e.dataTransfer.files[0]); };
  z.fijar = fijar;
}
document.querySelectorAll('.zona').forEach(prepararZona);
const zona = id => document.querySelector(`.zona[data-zona="${id}"]`);

async function enviar(url, archivo, extra = {}) {
  const fd = new FormData();
  if (archivo) fd.append('archivo', archivo);
  for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  const r = await fetch(url, {method: 'POST', body: fd});
  let j = {};
  try { j = await r.json(); } catch { j = {detalle: 'Respuesta no válida del servidor.'}; }
  return {ok: r.ok, status: r.status, j};
}
const detalle = j => j.detalle || (typeof j.detail === 'string' ? j.detail : 'No se pudo completar la operación.');
async function conBoton(btn, fn) { btn.disabled = true; try { await fn(); } catch { /* el mensaje ya se mostró */ } finally { btn.disabled = false; } }

// ---------------------------------------------------------------- utilidades de vista
function tabla(filas, cols, nums = [], dec = 2) {
  if (!filas || !filas.length) return '<p class="nota">Sin datos.</p>';
  return `<div class="tabla${filas.length > 15 ? ' alta' : ''}"><table><thead><tr>${cols.map(c => `<th>${esc(c[1])}</th>`).join('')}</tr></thead><tbody>${
    filas.map(f => `<tr>${cols.map(c => { const v = f[c[0]];
      return `<td class="${nums.includes(c[0]) ? 'n' : ''}">${Array.isArray(v) ? esc(v.join(', ')) : c[2] ? c[2](v, f) : fmt(v, dec)}</td>`; }).join('')}</tr>`).join('')
  }</tbody></table></div>`;
}
const enlaces = rep => `<div class="enlaces">${Object.entries(rep || {}).map(([k, u]) =>
  `<a href="${u}" target="_blank" rel="noopener">↓ ${NOMBRES_REPORTE[k] || k}</a>`).join('')}</div>`;

// tooltip compartido de los gráficos SVG
const tip = $('#tip');
document.addEventListener('mousemove', e => {
  const t = e.target.closest('[data-tip]');
  if (!t) { tip.style.display = 'none'; return; }
  tip.innerHTML = t.dataset.tip; tip.style.display = 'block';
  tip.style.left = Math.min(e.clientX + 12, innerWidth - 270) + 'px'; tip.style.top = (e.clientY + 12) + 'px';
});

// Barras horizontales con bigotes opcionales (intervalo). filas: [{etiqueta, valor, lo?, hi?, tip}]
function barrasH(filas, {unidad = '', ancho = 760, log = false} = {}) {
  const alto = 26, izq = 230, der = 80, h = filas.length * alto + 30;
  const max = Math.max(...filas.map(f => f.hi ?? f.valor)) || 1;
  const min = log ? Math.max(1, Math.min(...filas.map(f => f.lo ?? f.valor).filter(v => v > 0))) : 0;
  const escala = v => log ? (Math.log10(Math.max(v, min)) - Math.log10(min)) / (Math.log10(max) - Math.log10(min) || 1) * (ancho - izq - der)
                          : v / max * (ancho - izq - der);
  const filasSvg = filas.map((f, i) => {
    const y = i * alto + 8, w = Math.max(escala(f.valor), 2);
    const big = f.lo != null ? `<line class="bigote" x1="${izq + escala(f.lo)}" x2="${izq + escala(f.hi)}" y1="${y + 9}" y2="${y + 9}"/>
      <line class="bigote" x1="${izq + escala(f.lo)}" x2="${izq + escala(f.lo)}" y1="${y + 5}" y2="${y + 13}"/>
      <line class="bigote" x1="${izq + escala(f.hi)}" x2="${izq + escala(f.hi)}" y1="${y + 5}" y2="${y + 13}"/>` : '';
    return `<g data-tip="${esc(f.tip || `${f.etiqueta}: ${fmt(f.valor)} ${unidad}`)}">
      <rect x="0" y="${y - 3}" width="${ancho}" height="${alto}" fill="transparent"/>
      <text x="${izq - 8}" y="${y + 13}" text-anchor="end">${esc(String(f.etiqueta).slice(0, 34))}</text>
      <rect class="barra-h" x="${izq}" y="${y + 2}" width="${w}" height="14" rx="3"/>${big}
      <text x="${izq + Math.max(w, f.hi != null ? escala(f.hi) : 0) + 6}" y="${y + 13}">${fmt(f.valor, f.valor < 10 ? 3 : 0)}</text></g>`;
  }).join('');
  return `<svg class="svg-graf" viewBox="0 0 ${ancho} ${h}" role="img"><line class="eje" x1="${izq}" x2="${izq}" y1="0" y2="${h - 22}"/>${filasSvg}
    <text x="${izq}" y="${h - 4}">${esc(unidad)}${log ? ' (escala logarítmica)' : ''}</text></svg>`;
}

// ---------------------------------------------------------------- modelo (inicio, modelo, acerca)
let META = null;
async function cargarModelo() {
  try {
    const r = await fetch('/api/modelo');
    const m = await r.json();
    if (!r.ok) throw new Error(detalle(m));
    META = m;
    $('#chip-modelo').textContent = `Modelo activo ${m.version}`;
    const v = m.metricas_validacion;
    $('#inicio-kpis').innerHTML = `
      <div class="kpi"><b>${esc(m.version)}</b><span>modelo activo · ${fmt(m.registros)} registros</span></div>
      <div class="kpi"><b>${fmt(v.mediana_error_relativo_pct, 1)}%</b><span>error típico por localidad</span></div>
      <div class="kpi"><b>${fmt(v.mejora_vs_ingenuo_pct, 1)}%</b><span>menos error que repetir el mes anterior</span></div>
      <div class="kpi"><b>2020–2025</b><span>datos de entrenamiento (${esc(m.periodo_datos)})</span></div>`;
    pintarModelo(m);
    pintarAcerca(m);
  } catch (e) {
    $('#chip-modelo').textContent = 'Sin modelo activo';
    $('#m-activo').innerHTML = error(e.message || 'No se pudo consultar el modelo.');
  }
  cargarVersiones();
}
function pintarModelo(m) {
  const v = m.metricas_validacion, ev = m.estrategia_validacion;
  const comp = m.comparacion_algoritmos ? barrasH(Object.entries(m.comparacion_algoritmos).map(([k, x]) => ({etiqueta: k, valor: x,
    tip: `${k}: MAE log ${x}`})), {unidad: 'MAE en escala log (menor es mejor)'}) : '';
  const porTam = barrasH(['Grande', 'Mediana', 'Pequeña', 'Muy pequeña'].filter(t => v.mae_log_por_tamano[t] != null)
    .map(t => ({etiqueta: t, valor: v.mae_log_por_tamano[t]})), {unidad: 'MAE log por tamaño de localidad'});
  const vars = m.esquema.variables.map(x => ({nombre: x.nombre, tipo: x.tipo, nulos: x.admite_nulos ? 'sí' : 'no',
    regla: x.rango ? `rango ${x.rango[0]} a ${x.rango[1] ?? '∞'}` : Array.isArray(x.categorias) ? `${x.categorias.length} categorías` : '',
    descripcion: x.descripcion}));
  $('#m-activo').innerHTML = `<div class="panel"><h2>Modelo activo: ${esc(m.version)}</h2>
    <p class="ayuda">${esc(m.algoritmo)} · entrenado el ${esc(m.fecha_entrenamiento.replace('T', ' '))} · ${fmt(m.registros)} registros (${esc(m.periodo_datos)})</p>
    <div class="kpis"><div class="kpi"><b>${fmt(v.mae_log, 3)}</b><span>MAE log (métrica principal)</span></div>
      <div class="kpi"><b>${fmt(v.mediana_error_relativo_pct, 1)}%</b><span>error relativo mediano</span></div>
      <div class="kpi"><b>${fmt(v.wape_pct, 1)}%</b><span>WAPE</span></div>
      <div class="kpi"><b>${fmt(v.mejora_vs_ingenuo_pct, 1)}%</b><span>mejora frente al pronóstico ingenuo</span></div></div>
    <p class="nota">Validación ${esc(ev.tipo)}: entrenamiento ${esc(ev.entrenamiento)} (${fmt(ev.registros_entrenamiento)} registros), prueba ${esc(ev.prueba)} (${fmt(ev.registros_prueba)} registros).</p>
    <h3>Comparación de algoritmos (misma validación)</h3>${comp}<h3>Error según el tamaño de la localidad</h3>${porTam}
    <h3>Variables que usa el modelo</h3>${tabla(vars, [['nombre', 'Variable', v => `<code>${esc(v)}</code>`], ['tipo', 'Tipo'], ['nulos', 'Admite faltantes'], ['regla', 'Regla'], ['descripcion', 'Descripción']])}
    <p class="nota">No se envían al modelo: ${m.esquema.no_enviar_al_modelo.map(x => `<code>${esc(x)}</code>`).join(', ')}.</p></div>`;
}
function pintarAcerca(m) {
  const v = m.metricas_validacion;
  $('#acerca-modelo').innerHTML = `<h2>Metodología</h2><ul class="limpia">
    <li><b>Qué se predice:</b> la energía activa del mes siguiente de cada localidad, a partir de meses anteriores (sin usar información del mes que se predice).</li>
    <li><b>Variables:</b> energía de 1, 2 y 12 meses antes, mes del año, tamaño de la localidad, departamento, horas de servicio y factor de carga del mes anterior.</li>
    <li><b>Algoritmo:</b> ${esc(m.algoritmo)} sobre log(1 + kWh), comparado contra un modelo lineal y contra repetir el mes anterior.</li>
    <li><b>Validación:</b> temporal, nunca aleatoria: se prueba en los 12 meses más recientes. Error típico ${fmt(v.mediana_error_relativo_pct, 1)}%, ${fmt(v.mejora_vs_ingenuo_pct, 1)}% menos error que el pronóstico ingenuo.</li>
    <li><b>Limitaciones:</b> la cobertura de reporte cambia en 2025; desde 2025-12 la fuente perdió la coma decimal de horas y potencia; las localidades muy pequeñas son poco predecibles; los meses con energía 0 no se modelan.</li></ul>`;
}
async function cargarVersiones() {
  try {
    const r = await (await fetch('/api/modelo/versiones')).json();
    const filas = r.versiones.slice().reverse().map(v => ({...v, mae: v.metricas.mae_log, wape: v.metricas.wape_pct,
      dec: v.decision ? `${v.decision.accion}: ${v.decision.justificacion}` : '', fecha: v.fecha_entrenamiento.replace('T', ' ')}));
    const chip = e => `<span class="estado ${e === 'activo' ? 'ok' : e === 'candidato' ? 'adv' : ''}" style="${e === 'historico' ? 'background:var(--panel-2);color:var(--ink-2)' : ''}">${e === 'historico' ? 'histórico' : esc(e)}</span>`;
    $('#m-versiones').innerHTML = tabla(filas, [['version', 'Versión'], ['estado', 'Estado', chip], ['fecha', 'Entrenada'], ['registros', 'Registros'],
      ['mae', 'MAE log'], ['wape', 'WAPE %'], ['nota', 'Nota'], ['dec', 'Decisión']], ['registros', 'mae', 'wape'], 4);
  } catch { $('#m-versiones').innerHTML = error('No se pudieron cargar las versiones.'); }
}

// ---------------------------------------------------------------- analizar
function vistaEda(j) {
  const e = j.eda;
  return `<div class="panel"><h2>${esc(e.archivo)}</h2>
    <div class="kpis"><div class="kpi"><b>${fmt(e.filas)}</b><span>filas</span></div><div class="kpi"><b>${e.columnas}</b><span>columnas</span></div>
      <div class="kpi"><b>${fmt(e.duplicados)}</b><span>filas duplicadas</span></div>
      <div class="kpi"><b>${e.numericas.length} · ${e.categoricas.length} · ${e.temporales.length}</b><span>numéricas · categóricas · temporales</span></div></div>
    ${enlaces(j.reportes)}
    <h3>Observaciones del sistema</h3><ul class="limpia">${e.observaciones.map(o => `<li>${esc(o)}</li>`).join('')}</ul>
    <h3>Variables y calidad</h3>${tabla(e.variables, [['variable', 'Variable'], ['tipo', 'Tipo'], ['faltantes', 'Faltantes'], ['pct_faltantes', '% faltantes'], ['unicos', 'Distintos'], ['nota', 'Nota']], ['faltantes', 'pct_faltantes', 'unicos'])}
    ${e.numericas.length ? '<h3>Variables numéricas</h3>' + tabla(e.numericas.map(x => ({...x, at: x.atipicos ? `${x.atipicos.n} (${x.atipicos.pct}%) · ${x.atipicos.escala}` : '-'})),
      [['variable', 'Variable'], ['n', 'n'], ['media', 'Media'], ['mediana', 'Mediana'], ['min', 'Mín'], ['max', 'Máx'], ['at', 'Atípicos (Tukey)']], ['n', 'media', 'mediana', 'min', 'max']) : ''}
    ${e.relaciones.length ? '<h3>Relaciones (asociación, no causalidad)</h3><ul class="limpia">' + e.relaciones.map(r => `<li>${esc(r.texto)}</li>`).join('') + '</ul>' : ''}
    <h3>Visualizaciones</h3><div class="graficos">${j.graficos.map(g => `<figure><figcaption>${esc(g.titulo)}</figcaption><img loading="lazy" alt="${esc(g.titulo)}" src="data:image/png;base64,${g.png}"></figure>`).join('')}</div></div>`;
}
async function analizar() {
  const f = archivos.eda;
  if (!f) { $('#r-eda').innerHTML = error('Elija primero un archivo.'); return; }
  $('#r-eda').innerHTML = cargando('Analizando el archivo…');
  try { const {ok, j} = await enviar('/api/eda', f); $('#r-eda').innerHTML = ok ? vistaEda(j) : error(detalle(j)); }
  catch { $('#r-eda').innerHTML = error('No se pudo conectar con la API.'); }
}
$('#btn-eda').onclick = e => conBoton(e.target, analizar);

// ---------------------------------------------------------------- validar y predecir
function vistaDiag(d, rep) {
  return `<div class="panel"><h2>Validación <span class="estado ${clase(d.estado)}">${esc(d.estado)}</span></h2>
    <p class="ayuda">${fmt(d.filas)} filas · ${d.columnas} columnas · modelo ${esc(d.version_modelo)} · ${d.errores} error(es) · ${d.advertencias} advertencia(s)</p>
    ${d.sugerencia ? `<div class="msg adv">${esc(d.sugerencia)} <a href="#preparar">Ir a Preparar datos</a></div>` : ''}
    ${d.puede_predecir ? '' : '<div class="msg err">No se generaron predicciones. Revise los errores, estudie el archivo en <a href="#analizar">Analizar datos</a>, corríjalo y vuelva a cargarlo.</div>'}
    ${d.hallazgos.length ? tabla(d.hallazgos, [['severidad', 'Severidad', v => `<span class="estado ${v === 'error' ? 'err' : 'adv'}">${esc(v)}</span>`], ['nivel', 'Nivel'], ['variable', 'Variable'], ['mensaje', 'Qué pasa'], ['esperado', 'Esperado'], ['encontrado', 'Encontrado'], ['registros_afectados', 'Registros'], ['filas_ejemplo', 'Filas (ejemplo)']], ['registros_afectados'])
      : '<div class="msg ok">El archivo cumple todas las reglas del modelo.</div>'}
    <h3>Columnas y tipos</h3><p class="nota">Faltantes: ${esc(d.columnas_faltantes.join(', ') || 'ninguna')} · Adicionales: ${esc(d.columnas_adicionales.join(', ') || 'ninguna')}</p>
    ${tabla(d.tipos, [['variable', 'Variable'], ['esperado', 'Tipo esperado'], ['recibido', 'Tipo recibido']])}
    ${enlaces(rep)}</div>`;
}
function vistaPred(j) {
  const s = j.resumen;
  const top = [...j.filas].sort((a, b) => b.prediccion_kwh - a.prediccion_kwh).slice(0, 15).map(f => ({
    etiqueta: f.localidad || f.id_localidad, valor: f.prediccion_kwh, lo: f.limite_inferior_80, hi: f.limite_superior_80,
    tip: `<b>${esc(f.localidad || f.id_localidad)}</b><br>${esc(f.periodo_objetivo)} · ${fmt(f.prediccion_kwh)} kWh<br>80%: ${fmt(f.limite_inferior_80)} a ${fmt(f.limite_superior_80)}`}));
  const orden = ['Grande', 'Mediana', 'Pequeña', 'Muy pequeña'];
  const porTam = barrasH([...j.por_tamano].sort((a, b) => orden.indexOf(a.tamano) - orden.indexOf(b.tamano)).map(t => ({etiqueta: t.tamano, valor: t.total_kwh / 1000,
    tip: `${esc(t.tamano)}: ${t.registros} localidades · ${fmt(t.total_kwh / 1000, 1)} MWh`})), {unidad: 'MWh predichos por tamaño'});
  return `<div class="panel"><h2>Predicciones · modelo ${esc(j.version_modelo)}</h2>
    <div class="kpis"><div class="kpi"><b>${fmt(s.registros)}</b><span>localidades-mes</span></div>
      <div class="kpi"><b>${fmt(s.total_kwh / 1000, 1)}</b><span>MWh predichos en total</span></div>
      <div class="kpi"><b>${fmt(s.mediana_kwh)}</b><span>kWh, mediana por localidad</span></div>
      <div class="kpi"><b>${fmt(s.max_kwh / 1000, 1)}</b><span>MWh, la localidad mayor</span></div></div>
    ${enlaces(j.reportes)}
    <h3>Las 15 localidades con mayor energía predicha</h3>
    <p class="nota">La línea muestra el intervalo del 80%: en la validación, 8 de cada 10 valores reales cayeron dentro de ese rango.</p>
    ${barrasH(top, {unidad: 'kWh'})}
    <h3>Energía predicha por tamaño de localidad</h3>${porTam}
    <h3>Detalle por localidad</h3>
    ${tabla(j.filas.slice(0, 300), [['fila', 'Fila'], ['id_localidad', 'Código'], ['localidad', 'Localidad'], ['periodo_objetivo', 'Mes objetivo'], ['tamano', 'Tamaño'], ['prediccion_kwh', 'Predicción kWh'], ['limite_inferior_80', 'Inferior 80%'], ['limite_superior_80', 'Superior 80%'], ['aviso', 'Aviso']], ['prediccion_kwh', 'limite_inferior_80', 'limite_superior_80'])}
    ${j.filas.length > 300 ? `<p class="nota">Se muestran 300 de ${j.filas.length} filas; descargue el CSV o el Excel para verlas todas.</p>` : ''}</div>`;
}
async function predecir(soloValidar) {
  const f = archivos.pred;
  if (!f) { $('#r-pred').innerHTML = error('Elija primero un archivo.'); return; }
  $('#r-pred').innerHTML = cargando(soloValidar ? 'Validando…' : 'Validando y prediciendo…');
  try {
    const {ok, status, j} = await enviar(soloValidar ? '/api/validar' : '/api/predecir', f, soloValidar ? {modo: 'prediccion'} : {});
    $('#r-pred').innerHTML = j.diagnostico ? vistaDiag(j.diagnostico, soloValidar || !ok ? j.reportes : {compatibilidad: j.reportes.compatibilidad})
      + (ok && j.filas ? vistaPred(j) : '') : error(detalle(j) || `Error ${status}`);
  } catch { $('#r-pred').innerHTML = error('No se pudo conectar con la API.'); }
}
$('#btn-predecir').onclick = e => conBoton(e.target, () => predecir(false));
$('#btn-validar').onclick = e => conBoton(e.target, () => predecir(true));

// ---------------------------------------------------------------- preparar
async function preparar(usarAhora) {
  const f = archivos.prep;
  if (!f) { $('#r-prep').innerHTML = error('Elija primero el CSV del portal.'); return; }
  const tipo = $('#prep-tipo').value;
  $('#r-prep').innerHTML = cargando('Limpiando y construyendo las variables…');
  try {
    const fd = new FormData(); fd.append('archivo', f); fd.append('tipo', tipo);
    const r = await fetch('/api/preparar', {method: 'POST', body: fd});
    if (!r.ok) { $('#r-prep').innerHTML = error(detalle(await r.json())); return; }
    const nombre = tipo === 'etiquetados' ? 'zni_etiquetados.csv' : 'zni_para_prediccion.csv';
    const archivo = new File([await r.blob()], nombre, {type: 'text/csv'});
    if (usarAhora) {
      const destino = tipo === 'etiquetados' ? 'act' : 'pred';
      zona(destino).fijar(archivo);
      location.hash = tipo === 'etiquetados' ? '#modelo' : '#predecir';
      if (destino === 'pred') predecir(false); else actualizar();
      $('#r-prep').innerHTML = '';
    } else {
      const a = document.createElement('a'); a.href = URL.createObjectURL(archivo); a.download = nombre; a.click();
      $('#r-prep').innerHTML = `<div class="msg ok">Listo: se descargó <b>${nombre}</b>. Ahora puede cargarlo en <a href="#predecir">Validar y predecir</a>.</div>`;
    }
  } catch { $('#r-prep').innerHTML = error('No se pudo conectar con la API.'); }
}
$('#btn-prep').onclick = e => conBoton(e.target, () => preparar(false));
$('#btn-prep-usar').onclick = e => conBoton(e.target, () => preparar(true));

// ---------------------------------------------------------------- actualizar modelo
function vistaAct(j) {
  return `<h3>Candidata ${esc(j.version_candidata)} frente a la activa ${esc(j.version_activa)}</h3>
    <p class="ayuda">${fmt(j.nuevos.integrados)} registros integrados (${esc(j.nuevos.periodo)}), ${fmt(j.nuevos.ya_existian)} ya existían y ${fmt(j.nuevos.sin_energia)} con energía 0 no se usan para entrenar.</p>
    ${tabla(j.comparacion.tabla, [['metrica', 'Métrica'], ['activa', 'Activa'], ['candidata', 'Candidata'], ['mejor', 'Mejor']], ['activa', 'candidata'], 4)}
    <p class="nota">${esc(j.comparacion.nota)}</p><div class="msg adv">${esc(j.lectura)}</div>
    <label class="campo" for="just">Justificación de la decisión</label><textarea id="just" placeholder="Explique por qué conserva o reemplaza el modelo activo"></textarea>
    <div class="acciones"><button class="btn" data-a="activar">Activar la candidata</button><button class="btn sec" data-a="descartar">Conservar la activa</button></div>
    <div id="r-dec"></div>${enlaces(j.reportes)}`;
}
async function actualizar() {
  const f = archivos.act;
  if (!f) { $('#r-act').innerHTML = error('Elija primero un archivo con la energía real.'); return; }
  $('#r-act').innerHTML = cargando('Validando, integrando y reentrenando… puede tardar unos segundos.');
  try {
    const {ok, j} = await enviar('/api/modelo/actualizar', f);
    if (!ok) { $('#r-act').innerHTML = (j.diagnostico ? vistaDiag(j.diagnostico, j.reportes) : '') + error(detalle(j)); return; }
    $('#r-act').innerHTML = vistaAct(j); cargarVersiones();
    $('#r-act').querySelectorAll('button[data-a]').forEach(b => b.onclick = () => conBoton(b, async () => {
      const just = $('#just').value.trim();
      if (just.length < 10) { $('#r-dec').innerHTML = error('Escriba una justificación de al menos 10 caracteres.'); return; }
      const res = await enviar(`/api/modelo/versiones/${j.version_candidata}/decision`, null, {accion: b.dataset.a, justificacion: just, proceso: j.proceso});
      if (!res.ok) { $('#r-dec').innerHTML = error(detalle(res.j)); return; }
      $('#r-dec').innerHTML = `<div class="msg ok">Decisión registrada: ${b.dataset.a === 'activar' ? `se activó ${esc(j.version_candidata)}` : `se conserva ${esc(j.version_activa)}`}. El reporte de actualización ya la incluye.</div>`;
      $('#r-act').querySelectorAll('button[data-a]').forEach(x => x.disabled = true);
      cargarModelo();
    }));
  } catch { $('#r-act').innerHTML = error('No se pudo conectar con la API.'); }
}
$('#btn-act').onclick = e => conBoton(e.target, actualizar);

// ---------------------------------------------------------------- reportes
async function cargarReportes() {
  $('#r-reportes').innerHTML = cargando('Cargando historial…');
  try {
    const r = await (await fetch('/api/procesos')).json();
    if (!r.procesos.length) { $('#r-reportes').innerHTML = '<p class="ayuda">Todavía no hay cargas. Pruebe con un <a href="#ejemplos">archivo de prueba</a>.</p>'; return; }
    $('#r-reportes').innerHTML = tabla(r.procesos.map(p => ({...p, fecha: (p.fecha || p.proceso.slice(0, 15)).replace('T', ' ')})),
      [['fecha', 'Fecha'], ['tipo', 'Proceso', v => esc(TIPOS_PROCESO[v] || v)], ['archivo', 'Archivo'],
       ['estado', 'Validación', v => v ? `<span class="estado ${clase(v)}">${esc(v)}</span>` : '—'],
       ['reportes', 'Descargas', v => Object.entries(v).map(([k, u]) => `<a href="${u}" target="_blank" rel="noopener">${NOMBRES_REPORTE[k] || k}</a>`).join(' · ')]]);
  } catch { $('#r-reportes').innerHTML = error('No se pudo cargar el historial.'); }
}
$('#btn-recargar').onclick = cargarReportes;

// ---------------------------------------------------------------- archivos de prueba
const DESTINO = {predecir: ['pred', '#predecir', () => predecir(false)], eda: ['eda', '#analizar', analizar], actualizar: ['act', '#modelo', actualizar]};
async function cargarEjemplos() {
  if ($('#r-ejemplos').dataset.listo) return;
  $('#r-ejemplos').innerHTML = cargando('Cargando archivos…');
  try {
    const r = await (await fetch('/api/escenarios')).json();
    $('#r-ejemplos').innerHTML = tabla(r.escenarios, [['escenario', 'Escenario'], ['descripcion', 'Caso'], ['esperado', 'Resultado esperado'],
      ['archivo', 'Acciones', (v, f) => `<span style="white-space:nowrap"><button class="btn chico" data-probar="${esc(v)}" data-uso="${esc(f.uso)}">Probar</button>
        <a class="btn sec chico" href="${f.url}" download>Descargar</a></span>`]]);
    $('#r-ejemplos').dataset.listo = '1';
    $('#r-ejemplos').querySelectorAll('[data-probar]').forEach(b => b.onclick = () => conBoton(b, async () => {
      const resp = await fetch(`/api/escenarios/${encodeURIComponent(b.dataset.probar)}`);
      const archivo = new File([await resp.blob()], b.dataset.probar, {type: 'text/csv'});
      const [z, hash, accion] = DESTINO[b.dataset.uso];
      zona(z).fijar(archivo); location.hash = hash; accion();
    }));
  } catch { $('#r-ejemplos').innerHTML = error('No se pudieron cargar los archivos de prueba.'); }
}

cargarModelo();
ir();
