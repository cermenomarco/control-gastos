"""Control de gastos - Versión 3: interfaz web con tarjetas y bancos (Flask)

Uso:  python app.py   y abre http://localhost:5000 en el navegador.
Usa la misma base de datos (gastos.db) que gastos.py.
"""
import hmac
import os
import secrets
from calendar import monthrange
from datetime import date, timedelta

from flask import Flask, redirect, render_template_string, request, session, url_for

import gastos  # reutiliza la tabla y la conexión de la versión 1

gastos.DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gastos.db")
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.permanent_session_lifetime = timedelta(days=30)  # no pide clave todos los días
app.config.update(SESSION_COOKIE_SAMESITE="Lax")
CATEGORIAS = ["comida", "transporte", "ocio", "hogar", "salud", "otros"]
TIPOS_TARJETA = ["Visa", "Mastercard", "American Express"]
MEDIOS = {"tarjeta": "Tarjeta", "transferencia": "Transferencia", "efectivo": "Efectivo"}
MODALIDADES = {"credito": "Crédito", "debito": "Débito"}
ERRORES = {
    "datos": "Revisa el monto (número mayor a 0), la fecha y el medio de pago.",
    "tarjeta": "Revisa la tarjeta: tipo, 4 dígitos y, si es de crédito, día de cierre y de vencimiento (1 a 31).",
    "cuotas": "Las cuotas deben ser un número entre 1 y 60.",
    "suscripcion": "Revisa la suscripción: nombre, monto mayor a 0 y día de cobro entre 1 y 31.",
    "interes": "Si hay interés, indica el total a pagar (mayor al monto).",
    "banco": "El nombre del banco está vacío o ya existe.",
    "usado": "No se puede eliminar: tiene gastos o tarjetas asociados.",
}


def conectar():
    """Abre la base y crea las tablas/columnas de la versión 3 si faltan."""
    con = gastos.conectar()
    con.executescript(
        """CREATE TABLE IF NOT EXISTS bancos (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               nombre TEXT NOT NULL UNIQUE
           );
           CREATE TABLE IF NOT EXISTS tarjetas (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               tipo TEXT NOT NULL,
               ultimos4 TEXT NOT NULL,
               banco_id INTEGER
           );"""
    )
    existentes = {fila[1] for fila in con.execute("PRAGMA table_info(gastos)")}
    for columna in ("medio TEXT", "tarjeta_id INTEGER", "banco_id INTEGER", "cuotas INTEGER DEFAULT 1", "con_interes INTEGER DEFAULT 0", "total_con_interes REAL"):
        if columna.split()[0] not in existentes:
            con.execute(f"ALTER TABLE gastos ADD COLUMN {columna}")
    existentes = {fila[1] for fila in con.execute("PRAGMA table_info(tarjetas)")}
    for columna in ("modalidad TEXT DEFAULT 'credito'", "dia_cierre INTEGER", "dia_vencimiento INTEGER"):
        if columna.split()[0] not in existentes:
            con.execute(f"ALTER TABLE tarjetas ADD COLUMN {columna}")
    con.execute(
        """CREATE TABLE IF NOT EXISTS suscripciones (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               nombre TEXT NOT NULL,
               monto REAL NOT NULL,
               dia_cobro INTEGER NOT NULL,
               tarjeta_id INTEGER
           )"""
    )
    con.commit()
    return con


def a_int(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def etiqueta_tarjeta(tipo, ultimos4, banco, modalidad="credito"):
    texto = f"{tipo} {MODALIDADES.get(modalidad, modalidad)} •••• {ultimos4}"
    return f"{texto} · {banco}" if banco else texto


def texto_medio(medio, tipo, ultimos4, banco_tarjeta, banco_gasto, modalidad, cuotas, con_interes):
    if medio == "tarjeta" and tipo:
        texto = etiqueta_tarjeta(tipo, ultimos4, banco_tarjeta, modalidad)
        if modalidad == "credito":
            n = cuotas or 1
            texto += f" · {n} cuotas" if n > 1 else " · 1 pago"
            if con_interes:
                texto += " con interés"
            elif n > 1:
                texto += " sin interés"
        return texto
    if medio == "transferencia":
        return f"Transferencia · {banco_gasto}" if banco_gasto else "Transferencia"
    return MEDIOS.get(medio, "—")


def sumar_meses(anio, mes, n):
    indice = anio * 12 + (mes - 1) + n
    return indice // 12, indice % 12 + 1


def fecha_dia(anio, mes, dia):
    """Fecha con ese día; si el mes no lo tiene (31 en febrero) usa el último día."""
    return date(anio, mes, min(dia, monthrange(anio, mes)[1]))


def resumenes_tarjetas(compras, nombres, hoy):
    """Reparte las cuotas de cada compra en el resumen (cierre) que le toca.
    Una compra hasta el día de cierre entra a ese resumen; después, al siguiente.
    El vencimiento es la primera fecha con el día de vencimiento posterior al cierre.
    Devuelve los resúmenes que aún no vencieron: (tarjeta, cierre, vence, a pagar, intereses)."""
    acumulado = {}
    for tid, fecha, monto, cuotas, con_interes, total, cierre, venc in compras:
        f = date.fromisoformat(fecha)
        anio, mes = f.year, f.month
        if f > fecha_dia(anio, mes, cierre):
            anio, mes = sumar_meses(anio, mes, 1)
        cuotas = cuotas or 1
        a_pagar = total if con_interes and total else monto
        for k in range(cuotas):
            a, m = sumar_meses(anio, mes, k)
            celda = acumulado.setdefault((tid, a, m), [0.0, 0.0, cierre, venc])
            celda[0] += a_pagar / cuotas
            celda[1] += (a_pagar - monto) / cuotas
    filas = []
    for (tid, a, m), (pagar, intereses, cierre, venc) in acumulado.items():
        cierra = fecha_dia(a, m, cierre)
        va, vm = (a, m) if venc > cierre else sumar_meses(a, m, 1)
        vence = fecha_dia(va, vm, venc)
        if vence >= hoy:
            filas.append((vence, nombres.get(tid, "—"), cierra, pagar, intereses))
    filas.sort(key=lambda fila: (fila[0], fila[1]))
    return [(nombre, cierra, vence, pagar, intereses)
            for vence, nombre, cierra, pagar, intereses in filas]


MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def proyeccion(suscripciones, proximos, hoy, meses=6):
    """Por mes: suscripciones (según su día de cobro) + resúmenes de tarjeta (según su vencimiento).
    suscripciones: lista de (monto, dia_cobro). En el mes actual solo cuenta lo que falta cobrar."""
    filas = []
    for k in range(meses):
        anio, mes = sumar_meses(hoy.year, hoy.month, k)
        subs = sum(monto for monto, dia in suscripciones if k > 0 or dia >= hoy.day)
        tarjetas = sum(pagar for _, _, vence, pagar, _ in proximos
                       if (vence.year, vence.month) == (anio, mes))
        filas.append((f"{MESES[mes - 1]} {anio}", subs, tarjetas, subs + tarjetas))
    return filas


@app.template_filter("peso")
def peso(valor):
    # 1500.5 -> $ 1.500,50
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "$ " + texto


@app.template_filter("fecha")
def fecha_filtro(valor):
    return valor.strftime("%d/%m/%Y")


@app.template_filter("color")
def color(categoria):
    return f"hsl({sum(map(ord, categoria)) * 37 % 360}, 65%, 50%)"


PAGINA = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Control de gastos</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--txt:#1d2430;--mut:#6b7585;--line:#e4e7ec;--acc:#2f6fed}
@media (prefers-color-scheme:dark){:root{--bg:#12151b;--card:#1b2029;--txt:#e8ebf0;--mut:#98a2b3;--line:#2a313d;--acc:#4f7fe8}}
*{box-sizing:border-box}
body{margin:0;font:16px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--txt)}
main{max-width:900px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:24px;margin:0 0 4px}
h2{font-size:17px;margin:0 0 14px}
.sub{color:var(--mut);margin:0 0 20px}
a{color:var(--acc)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:16px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px;margin-bottom:16px}
.stats .card{margin:0}
.lbl{color:var(--mut);font-size:14px}
.big{font-size:21px;font-weight:600;overflow-wrap:anywhere}
form.add{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
input,button,select{font:inherit;padding:9px 11px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--txt)}
button.primary{background:var(--acc);border-color:var(--acc);color:#fff;cursor:pointer}
.bar{margin:12px 0}
.top{display:flex;justify-content:space-between;font-size:14px}
.track{height:8px;background:var(--line);border-radius:4px;overflow:hidden;margin-top:4px}
.track i{display:block;height:100%;border-radius:4px}
.wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:15px}
th,td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
.num{text-align:right}
.tag{display:inline-block;padding:2px 10px;border-radius:99px;font-size:13px;color:#fff}
.del{background:none;border:none;color:var(--mut);cursor:pointer;padding:2px 6px}
.err{background:#fde8e8;color:#9b1c1c;padding:10px 14px;border-radius:8px;margin-bottom:16px}
.hidden{display:none!important}
.chk{display:flex;align-items:center;gap:6px}
.chk input{width:auto;padding:0}
nav{display:flex;gap:8px;overflow-x:auto;margin:0 0 20px;padding-bottom:4px}
nav a{padding:8px 14px;border:1px solid var(--line);border-radius:99px;text-decoration:none;color:var(--txt);background:var(--card);white-space:nowrap}
nav a.activa{background:var(--acc);border-color:var(--acc);color:#fff}
summary{cursor:pointer;font-weight:600;font-size:17px}
details[open] summary{margin-bottom:14px}
details h2{margin-top:18px}
.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:10px 0}
.item{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--line)}
</style>
</head>
<body>
<main>
  <h1>Control de gastos</h1>
  <p class="sub">{% if vista == 'inicio' %}Resumen de {{ mes }} · {% endif %}<a href="{{ url_for('salir') }}">Salir</a></p>
  <nav>
    {% for destino, rotulo in [('inicio', 'Inicio'), ('ver_gastos', 'Gastos'), ('ver_tarjetas', 'Tarjetas'), ('ver_suscripciones', 'Suscripciones')] %}
    <a href="{{ url_for(destino) }}"{% if request.endpoint == destino %} class="activa"{% endif %}>{{ rotulo }}</a>
    {% endfor %}
  </nav>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}

  {% if vista == 'inicio' %}
  <div class="stats">
    <div class="card"><div class="lbl">Total del mes</div><div class="big">{{ total|peso }}</div></div>
    <div class="card"><div class="lbl">Gastos del mes</div><div class="big">{{ cantidad }}</div></div>
    <div class="card"><div class="lbl">Categoría principal</div><div class="big">{{ por_cat[0][0] if por_cat else '—' }}</div></div>
    <div class="card"><div class="lbl">Tarjeta principal</div>{% if tarjeta_top %}<div class="big">{{ tarjeta_top[0] }}</div><div class="lbl">{{ tarjeta_top[1]|peso }}</div>{% else %}<div class="big">—</div>{% endif %}</div>
    <div class="card"><div class="lbl">Banco principal</div>{% if banco_top %}<div class="big">{{ banco_top[0] }}</div><div class="lbl">{{ banco_top[1]|peso }}</div>{% else %}<div class="big">—</div>{% endif %}</div>
  </div>

  <div class="card">
    <h2>Agregar gasto</h2>
    <form class="add" method="post" action="{{ url_for('agregar') }}">
      <input name="monto" placeholder="Monto (ej: 1500,50)" inputmode="decimal" required>
      <input name="categoria" list="cats" placeholder="Categoría" required>
      <datalist id="cats">{% for c in cats %}<option value="{{ c }}">{% endfor %}</datalist>
      <input name="descripcion" placeholder="Descripción (opcional)">
      <input name="fecha" type="date" value="{{ hoy }}" required>
      <select name="medio" id="medio" onchange="cambiarMedio()">
        {% for clave, nombre in medios.items() %}<option value="{{ clave }}">{{ nombre }}</option>{% endfor %}
      </select>
      <select name="tarjeta_id" id="sel-tarjeta" onchange="actualizarCredito()">
        <option value="">Elegir tarjeta</option>
        {% for tid, etiqueta, modalidad, info in tarjetas %}<option value="{{ tid }}" data-modalidad="{{ modalidad }}">{{ etiqueta }}</option>{% endfor %}
      </select>
      <select name="banco_id" id="sel-banco" class="hidden">
        <option value="">Elegir banco</option>
        {% for bid, nombre in bancos %}<option value="{{ bid }}">{{ nombre }}</option>{% endfor %}
      </select>
      <input name="cuotas" id="cuotas" type="number" min="1" max="60" value="1" placeholder="Cuotas" class="hidden">
      <label class="chk hidden" id="lbl-interes"><input type="checkbox" name="con_interes" id="con-interes" onchange="actualizarCredito()"> Con interés</label>
      <input name="total_con_interes" id="total-interes" placeholder="Total a pagar con intereses" inputmode="decimal" class="hidden">
      <button class="primary">Guardar</button>
    </form>
  </div>

  {% endif %}

  {% if vista == 'tarjetas' %}
  <details class="card" open>
    <summary>Mis tarjetas y bancos</summary>
    <h2>Tarjetas</h2>
    {% for tid, etiqueta, modalidad, info in tarjetas %}
    <div class="item"><span>{{ etiqueta }} <small class="lbl">{{ info }}</small></span>
      <form method="post" action="{{ url_for('eliminar_tarjeta', id_=tid) }}" onsubmit="return confirm('¿Eliminar esta tarjeta?')"><button class="del" title="Eliminar">✕</button></form>
    </div>
    {% else %}<p class="lbl">Todavía no cargaste tarjetas.</p>{% endfor %}
    <form class="row" method="post" action="{{ url_for('agregar_tarjeta') }}">
      <select name="tipo">{% for t in tipos %}<option>{{ t }}</option>{% endfor %}</select>
      <input name="ultimos4" placeholder="Últimos 4 dígitos" inputmode="numeric" pattern="[0-9]{4}" maxlength="4" required>
      <select name="banco_id"><option value="">Banco (opcional)</option>{% for bid, nombre in bancos %}<option value="{{ bid }}">{{ nombre }}</option>{% endfor %}</select>
      <select name="modalidad" id="modalidad" onchange="cambiarModalidad()">{% for k, v in modalidades.items() %}<option value="{{ k }}">{{ v }}</option>{% endfor %}</select>
      <input name="dia_cierre" id="dia-cierre" type="number" min="1" max="31" placeholder="Día de cierre">
      <input name="dia_vencimiento" id="dia-venc" type="number" min="1" max="31" placeholder="Día de vencimiento">
      <button class="primary">Guardar tarjeta</button>
    </form>
    <h2>Bancos</h2>
    {% for bid, nombre in bancos %}
    <div class="item"><span>{{ nombre }}</span>
      <form method="post" action="{{ url_for('eliminar_banco', id_=bid) }}" onsubmit="return confirm('¿Eliminar este banco?')"><button class="del" title="Eliminar">✕</button></form>
    </div>
    {% else %}<p class="lbl">Todavía no cargaste bancos.</p>{% endfor %}
    <form class="row" method="post" action="{{ url_for('agregar_banco') }}">
      <input name="nombre" placeholder="Nombre del banco" required>
      <button class="primary">Agregar banco</button>
    </form>
  </details>

  <div class="card">
    <h2>Próximos pagos de tarjetas de crédito</h2>
    {% if sin_fechas %}<p class="lbl">Falta el cierre y vencimiento de: {{ sin_fechas|join(', ') }}. Guarda la tarjeta de nuevo con los mismos datos para completarlos.</p>{% endif %}
    {% if proximos %}
    <div class="wrap"><table>
      <tr><th>Tarjeta</th><th>Cierra</th><th>Vence</th><th class="num">A pagar</th><th class="num">Intereses</th></tr>
      {% for nombre, cierre, vence, pagar, interes in proximos %}
      <tr><td>{{ nombre }}</td><td>{{ cierre|fecha }}</td><td>{{ vence|fecha }}</td><td class="num">{{ pagar|peso }}</td><td class="num">{{ interes|peso }}</td></tr>
      {% endfor %}
    </table></div>
    {% else %}<p class="lbl">Cuando cargues compras con tarjeta de crédito, acá ves cuánto pagas en cada vencimiento.</p>{% endif %}
  </div>

  {% endif %}

  {% if vista == 'suscripciones' %}
  <div class="card">
    <h2>Suscripciones</h2>
    {% if suscripciones %}
    <p class="lbl">{{ suscripciones|length }} activas · {{ total_subs|peso }} por mes</p>
    <div class="wrap"><table>
      <tr><th>Nombre</th><th>Día de cobro</th><th>Tarjeta</th><th class="num">Monto</th><th></th></tr>
      {% for sid, nombre, monto, dia, tarjeta in suscripciones %}
      <tr><td>{{ nombre }}</td><td>{{ dia }}</td><td>{{ tarjeta }}</td><td class="num">{{ monto|peso }}</td>
        <td><form method="post" action="{{ url_for('eliminar_suscripcion', id_=sid) }}" onsubmit="return confirm('¿Eliminar esta suscripción?')"><button class="del" title="Eliminar">✕</button></form></td></tr>
      {% endfor %}
    </table></div>
    {% else %}<p class="lbl">Todavía no cargaste suscripciones.</p>{% endif %}
    <form class="row" method="post" action="{{ url_for('agregar_suscripcion') }}">
      <input name="nombre" placeholder="Nombre (ej: Netflix)" required>
      <input name="monto" placeholder="Monto mensual" inputmode="decimal" required>
      <input name="dia_cobro" type="number" min="1" max="31" placeholder="Día de cobro" required>
      <select name="tarjeta_id"><option value="">Tarjeta (opcional)</option>{% for tid, etiqueta, modalidad, info in tarjetas %}<option value="{{ tid }}">{{ etiqueta }}</option>{% endfor %}</select>
      <button class="primary">Agregar</button>
    </form>
  </div>

  <div class="card">
    <h2>Proyección de los próximos 6 meses</h2>
    <div class="wrap"><table>
      <tr><th>Mes</th><th class="num">Suscripciones</th><th class="num">Tarjetas de crédito</th><th class="num">Total estimado</th></tr>
      {% for etiqueta_mes, de_subs, de_tarjetas, de_total in proyeccion %}
      <tr><td>{{ etiqueta_mes }}</td><td class="num">{{ de_subs|peso }}</td><td class="num">{{ de_tarjetas|peso }}</td><td class="num"><b>{{ de_total|peso }}</b></td></tr>
      {% endfor %}
    </table></div>
    <p class="lbl">Las suscripciones cuentan el mes en que se cobran; las tarjetas, el mes en que vence cada resumen (solo con las compras ya cargadas).</p>
  </div>

  {% endif %}

  {% if vista == 'inicio' %}
  <div class="card">
    <h2>Por categoría</h2>
    {% for cat, suma in por_cat %}
    <div class="bar">
      <div class="top"><span>{{ cat }}</span><span>{{ suma|peso }} · {{ (suma / total * 100)|round|int }}%</span></div>
      <div class="track"><i style="width:{{ suma / total * 100 }}%;background:{{ cat|color }}"></i></div>
    </div>
    {% else %}<p class="lbl">Todavía no hay gastos este mes.</p>{% endfor %}
  </div>

  {% endif %}

  {% if vista in ('inicio', 'gastos') %}
  <div class="card">
    <h2>{% if vista == 'gastos' %}Todos los gastos{% else %}Últimos gastos · <a href="{{ url_for('ver_gastos') }}">ver todos</a>{% endif %}</h2>
    <div class="wrap"><table>
      <tr><th>Fecha</th><th>Categoría</th><th>Descripción</th><th>Medio</th><th class="num">Monto</th>{% if vista == 'gastos' %}<th></th>{% endif %}</tr>
      {% for id, fecha, monto, cat, desc, medio in (filas if vista == 'gastos' else filas[:5]) %}
      <tr>
        <td>{{ fecha }}</td>
        <td><span class="tag" style="background:{{ cat|color }}">{{ cat }}</span></td>
        <td>{{ desc }}</td>
        <td>{{ medio }}</td>
        <td class="num">{{ monto|peso }}</td>
        {% if vista == 'gastos' %}<td><form method="post" action="{{ url_for('eliminar', id_=id) }}" onsubmit="return confirm('¿Eliminar este gasto?')"><button class="del" title="Eliminar">✕</button></form></td>{% endif %}
      </tr>
      {% else %}<tr><td colspan="6" class="lbl">Sin gastos todavía.</td></tr>{% endfor %}
    </table></div>
  </div>
  {% endif %}
</main>
<script>
function cambiarMedio() {
  var medio = document.getElementById('medio').value;
  document.getElementById('sel-tarjeta').classList.toggle('hidden', medio !== 'tarjeta');
  document.getElementById('sel-banco').classList.toggle('hidden', medio !== 'transferencia');
  actualizarCredito();
}
function actualizarCredito() {
  var sel = document.getElementById('sel-tarjeta');
  var op = sel.options[sel.selectedIndex];
  var credito = document.getElementById('medio').value === 'tarjeta' && op && op.dataset.modalidad === 'credito';
  var interes = document.getElementById('con-interes').checked;
  document.getElementById('cuotas').classList.toggle('hidden', !credito);
  document.getElementById('lbl-interes').classList.toggle('hidden', !credito);
  document.getElementById('total-interes').classList.toggle('hidden', !(credito && interes));
}
function cambiarModalidad() {
  var credito = document.getElementById('modalidad').value === 'credito';
  ['dia-cierre', 'dia-venc'].forEach(function (id) {
    var el = document.getElementById(id);
    el.classList.toggle('hidden', !credito);
    el.required = credito;
  });
}
if (document.getElementById('medio')) cambiarMedio();
if (document.getElementById('modalidad')) cambiarModalidad();
</script>
</body>
</html>"""


LOGIN = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Entrar</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;font:16px system-ui,sans-serif;background:#f6f7f9;color:#1d2430}
@media (prefers-color-scheme:dark){body{background:#12151b;color:#e8ebf0}}
form{width:min(320px,90vw);display:grid;gap:12px}
input,button{font:inherit;padding:11px;border-radius:8px;border:1px solid #8886}
button{background:#2f6fed;border-color:#2f6fed;color:#fff;cursor:pointer}
.err{color:#d33}
</style></head><body>
<form method="post">
  <h1>Control de gastos</h1>
  <input type="password" name="clave" placeholder="Contraseña" autofocus required>
  <button>Entrar</button>
  {% if error %}<div class="err">Contraseña incorrecta.</div>{% endif %}
</form></body></html>"""


@app.before_request
def exigir_login():
    # Todo requiere sesión, salvo la pantalla de login
    if request.endpoint in ("login", "static") or session.get("ok"):
        return None
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = False
    if request.method == "POST":
        esperado = os.environ.get("APP_PASSWORD", "").encode()
        recibido = request.form.get("clave", "").encode()
        # Si APP_PASSWORD no está configurada, nadie puede entrar
        if esperado and hmac.compare_digest(recibido, esperado):
            session.permanent = True
            session["ok"] = True
            return redirect(url_for("inicio"))
        error = True
    return render_template_string(LOGIN, error=error)


@app.route("/salir")
def salir():
    session.clear()
    return redirect(url_for("login"))


def renderizar(vista):
    con = conectar()
    mes = date.today().strftime("%Y-%m")
    total, cantidad = con.execute(
        "SELECT COALESCE(SUM(monto), 0), COUNT(*) FROM gastos WHERE fecha LIKE ?",
        (mes + "%",),
    ).fetchone()
    por_cat = con.execute(
        """SELECT categoria, SUM(monto) FROM gastos WHERE fecha LIKE ?
           GROUP BY categoria ORDER BY SUM(monto) DESC""",
        (mes + "%",),
    ).fetchall()
    filas = [
        (id_, fecha, monto, cat, desc, texto_medio(*resto))
        for id_, fecha, monto, cat, desc, *resto in con.execute(
            """SELECT g.id, g.fecha, g.monto, g.categoria, g.descripcion,
                      g.medio, t.tipo, t.ultimos4, bt.nombre, bg.nombre,
                      t.modalidad, g.cuotas, g.con_interes
               FROM gastos g
               LEFT JOIN tarjetas t ON t.id = g.tarjeta_id
               LEFT JOIN bancos bt ON bt.id = t.banco_id
               LEFT JOIN bancos bg ON bg.id = g.banco_id
               ORDER BY g.fecha DESC, g.id DESC"""
        )
    ]
    tarjetas, sin_fechas = [], []
    for tid, tipo, ultimos4, banco, modalidad, cierre, venc in con.execute(
        """SELECT t.id, t.tipo, t.ultimos4, b.nombre, t.modalidad, t.dia_cierre, t.dia_vencimiento
           FROM tarjetas t LEFT JOIN bancos b ON b.id = t.banco_id ORDER BY t.id"""
    ):
        etiqueta = etiqueta_tarjeta(tipo, ultimos4, banco, modalidad)
        if modalidad != "credito":
            info = ""
        elif cierre and venc:
            info = f"cierra el {cierre} · vence el {venc}"
        else:
            info = "falta cierre y vencimiento"
            sin_fechas.append(etiqueta)
        tarjetas.append((tid, etiqueta, modalidad, info))
    bancos = con.execute("SELECT id, nombre FROM bancos ORDER BY nombre").fetchall()
    fila = con.execute(
        """SELECT t.tipo, t.ultimos4, SUM(g.monto) FROM gastos g
           JOIN tarjetas t ON t.id = g.tarjeta_id
           WHERE g.fecha LIKE ? GROUP BY t.id ORDER BY SUM(g.monto) DESC LIMIT 1""",
        (mes + "%",),
    ).fetchone()
    tarjeta_top = (f"{fila[0]} •••• {fila[1]}", fila[2]) if fila else None
    # Banco: transferencias desde ese banco + compras con tarjetas de ese banco
    banco_top = con.execute(
        """SELECT b.nombre, SUM(g.monto) FROM gastos g
           LEFT JOIN tarjetas t ON t.id = g.tarjeta_id
           JOIN bancos b ON b.id = COALESCE(t.banco_id, g.banco_id)
           WHERE g.fecha LIKE ? GROUP BY b.id ORDER BY SUM(g.monto) DESC LIMIT 1""",
        (mes + "%",),
    ).fetchone()
    compras = con.execute(
        """SELECT g.tarjeta_id, g.fecha, g.monto, g.cuotas, g.con_interes, g.total_con_interes,
                  t.dia_cierre, t.dia_vencimiento
           FROM gastos g JOIN tarjetas t ON t.id = g.tarjeta_id
           WHERE g.medio = 'tarjeta' AND t.modalidad = 'credito'
             AND t.dia_cierre IS NOT NULL AND t.dia_vencimiento IS NOT NULL"""
    ).fetchall()
    subs = con.execute(
        """SELECT s.id, s.nombre, s.monto, s.dia_cobro, t.tipo, t.ultimos4, b.nombre, t.modalidad
           FROM suscripciones s
           LEFT JOIN tarjetas t ON t.id = s.tarjeta_id
           LEFT JOIN bancos b ON b.id = t.banco_id
           ORDER BY s.dia_cobro, s.nombre"""
    ).fetchall()
    con.close()
    proximos = resumenes_tarjetas(compras, {t[0]: t[1] for t in tarjetas}, date.today())
    suscripciones = [
        (sid, nombre, monto, dia, etiqueta_tarjeta(tipo, ultimos4, banco, modalidad) if tipo else "—")
        for sid, nombre, monto, dia, tipo, ultimos4, banco, modalidad in subs
    ]
    total_subs = sum(s[2] for s in suscripciones)
    proyeccion_meses = proyeccion([(s[2], s[3]) for s in suscripciones], proximos, date.today())
    cats = sorted({f[3] for f in filas} | set(CATEGORIAS))
    return render_template_string(
        PAGINA, mes=mes, total=total, cantidad=cantidad, por_cat=por_cat,
        filas=filas, cats=cats, hoy=date.today().isoformat(),
        tarjetas=tarjetas, bancos=bancos, tipos=TIPOS_TARJETA, medios=MEDIOS,
        modalidades=MODALIDADES, tarjeta_top=tarjeta_top, banco_top=banco_top,
        vista=vista, proximos=proximos, sin_fechas=sin_fechas,
        suscripciones=suscripciones, total_subs=total_subs, proyeccion=proyeccion_meses,
        error=ERRORES.get(request.args.get("error")),
    )


@app.route("/")
def inicio():
    return renderizar("inicio")


@app.route("/gastos")
def ver_gastos():
    return renderizar("gastos")


@app.route("/tarjetas")
def ver_tarjetas():
    return renderizar("tarjetas")


@app.route("/suscripciones")
def ver_suscripciones():
    return renderizar("suscripciones")


@app.post("/agregar")
def agregar():
    form = request.form
    try:
        monto = float(form["monto"].strip().replace(",", "."))
        if monto <= 0:
            raise ValueError
        date.fromisoformat(form["fecha"])
    except (ValueError, KeyError):
        return redirect(url_for("inicio", error="datos"))
    medio = form.get("medio")
    if medio not in MEDIOS:
        return redirect(url_for("inicio", error="datos"))
    # Solo se guarda la tarjeta o el banco que corresponde al medio elegido
    tarjeta_id = a_int(form.get("tarjeta_id")) if medio == "tarjeta" else None
    banco_id = a_int(form.get("banco_id")) if medio == "transferencia" else None
    con = conectar()
    cuotas, con_interes, total = 1, 0, None
    credito = tarjeta_id and con.execute(
        "SELECT 1 FROM tarjetas WHERE id = ? AND modalidad = 'credito'", (tarjeta_id,)
    ).fetchone()
    if credito:  # cuotas e interés solo existen en tarjetas de crédito
        cuotas = a_int(form.get("cuotas")) or 1
        if not 1 <= cuotas <= 60:
            con.close()
            return redirect(url_for("inicio", error="cuotas"))
        if form.get("con_interes"):
            try:
                total = float(form.get("total_con_interes", "").strip().replace(",", "."))
            except ValueError:
                total = 0
            if total <= monto:
                con.close()
                return redirect(url_for("inicio", error="interes"))
            con_interes = 1
    categoria = form.get("categoria", "").strip().lower() or "otros"
    descripcion = form.get("descripcion", "").strip()
    con.execute(
        """INSERT INTO gastos (fecha, monto, categoria, descripcion, medio, tarjeta_id, banco_id,
                               cuotas, con_interes, total_con_interes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (form["fecha"], monto, categoria, descripcion, medio, tarjeta_id, banco_id,
         cuotas, con_interes, total),
    )
    con.commit()
    con.close()
    return redirect(url_for("inicio"))


@app.post("/eliminar/<int:id_>")
def eliminar(id_):
    con = conectar()
    con.execute("DELETE FROM gastos WHERE id = ?", (id_,))
    con.commit()
    con.close()
    return redirect(url_for("ver_gastos"))


@app.post("/tarjetas")
def agregar_tarjeta():
    form = request.form
    tipo = form.get("tipo")
    ultimos4 = form.get("ultimos4", "").strip()
    modalidad = form.get("modalidad")
    cierre, venc = a_int(form.get("dia_cierre")), a_int(form.get("dia_vencimiento"))
    if modalidad == "debito":
        cierre = venc = None
    valida = (
        tipo in TIPOS_TARJETA
        and modalidad in MODALIDADES
        and len(ultimos4) == 4 and ultimos4.isascii() and ultimos4.isdigit()
        and (modalidad == "debito" or (cierre and venc and 1 <= cierre <= 31 and 1 <= venc <= 31))
    )
    if not valida:
        return redirect(url_for("ver_tarjetas", error="tarjeta"))
    con = conectar()
    datos = (modalidad, cierre, venc, a_int(form.get("banco_id")))
    existente = con.execute(
        "SELECT id FROM tarjetas WHERE tipo = ? AND ultimos4 = ?", (tipo, ultimos4)
    ).fetchone()
    if existente:  # misma tarjeta (tipo + 4 dígitos): se actualizan sus datos
        con.execute(
            "UPDATE tarjetas SET modalidad = ?, dia_cierre = ?, dia_vencimiento = ?, banco_id = ? WHERE id = ?",
            datos + (existente[0],),
        )
    else:
        con.execute(
            "INSERT INTO tarjetas (tipo, ultimos4, modalidad, dia_cierre, dia_vencimiento, banco_id) VALUES (?, ?, ?, ?, ?, ?)",
            (tipo, ultimos4) + datos,
        )
    con.commit()
    con.close()
    return redirect(url_for("ver_tarjetas"))


@app.post("/tarjetas/<int:id_>/eliminar")
def eliminar_tarjeta(id_):
    con = conectar()
    usada = con.execute(
        """SELECT (SELECT COUNT(*) FROM gastos WHERE tarjeta_id = ?)
                + (SELECT COUNT(*) FROM suscripciones WHERE tarjeta_id = ?)""",
        (id_, id_),
    ).fetchone()[0]
    if usada:
        con.close()
        return redirect(url_for("ver_tarjetas", error="usado"))
    con.execute("DELETE FROM tarjetas WHERE id = ?", (id_,))
    con.commit()
    con.close()
    return redirect(url_for("ver_tarjetas"))


@app.post("/bancos")
def agregar_banco():
    nombre = request.form.get("nombre", "").strip()
    con = conectar()
    existe = con.execute("SELECT 1 FROM bancos WHERE nombre = ? COLLATE NOCASE", (nombre,)).fetchone()
    if not nombre or existe:
        con.close()
        return redirect(url_for("ver_tarjetas", error="banco"))
    con.execute("INSERT INTO bancos (nombre) VALUES (?)", (nombre,))
    con.commit()
    con.close()
    return redirect(url_for("ver_tarjetas"))


@app.post("/bancos/<int:id_>/eliminar")
def eliminar_banco(id_):
    con = conectar()
    usos = con.execute(
        """SELECT (SELECT COUNT(*) FROM gastos WHERE banco_id = ?)
                + (SELECT COUNT(*) FROM tarjetas WHERE banco_id = ?)""",
        (id_, id_),
    ).fetchone()[0]
    if usos:
        con.close()
        return redirect(url_for("ver_tarjetas", error="usado"))
    con.execute("DELETE FROM bancos WHERE id = ?", (id_,))
    con.commit()
    con.close()
    return redirect(url_for("ver_tarjetas"))


@app.post("/suscripciones")
def agregar_suscripcion():
    form = request.form
    nombre = form.get("nombre", "").strip()
    try:
        monto = float(form.get("monto", "").strip().replace(",", "."))
    except ValueError:
        monto = 0
    dia = a_int(form.get("dia_cobro"))
    if not nombre or monto <= 0 or not dia or not 1 <= dia <= 31:
        return redirect(url_for("ver_suscripciones", error="suscripcion"))
    con = conectar()
    con.execute(
        "INSERT INTO suscripciones (nombre, monto, dia_cobro, tarjeta_id) VALUES (?, ?, ?, ?)",
        (nombre, monto, dia, a_int(form.get("tarjeta_id"))),
    )
    con.commit()
    con.close()
    return redirect(url_for("ver_suscripciones"))


@app.post("/suscripciones/<int:id_>/eliminar")
def eliminar_suscripcion(id_):
    con = conectar()
    con.execute("DELETE FROM suscripciones WHERE id = ?", (id_,))
    con.commit()
    con.close()
    return redirect(url_for("ver_suscripciones"))


if __name__ == "__main__":
    # Solo para uso local (contraseña: gastos). En el servidor se define APP_PASSWORD.
    os.environ.setdefault("APP_PASSWORD", "gastos")
    app.run(debug=True)
