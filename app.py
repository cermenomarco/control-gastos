"""Control de gastos - Versión 3: interfaz web con tarjetas y bancos (Flask)

Uso:  python app.py   y abre http://localhost:5000 en el navegador.
Usa la misma base de datos (gastos.db) que gastos.py.
"""
import hmac
import os
import secrets
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
ERRORES = {
    "datos": "Revisa el monto (número mayor a 0), la fecha y el medio de pago.",
    "tarjeta": "Revisa la tarjeta: el tipo y exactamente 4 dígitos.",
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
    for columna in ("medio TEXT", "tarjeta_id INTEGER", "banco_id INTEGER"):
        if columna.split()[0] not in existentes:
            con.execute(f"ALTER TABLE gastos ADD COLUMN {columna}")
    con.commit()
    return con


def a_int(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def etiqueta_tarjeta(tipo, ultimos4, banco):
    texto = f"{tipo} •••• {ultimos4}"
    return f"{texto} · {banco}" if banco else texto


def texto_medio(medio, tipo, ultimos4, banco_tarjeta, banco_gasto):
    if medio == "tarjeta" and tipo:
        return etiqueta_tarjeta(tipo, ultimos4, banco_tarjeta)
    if medio == "transferencia":
        return f"Transferencia · {banco_gasto}" if banco_gasto else "Transferencia"
    return MEDIOS.get(medio, "—")


@app.template_filter("peso")
def peso(valor):
    # 1500.5 -> $ 1.500,50
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "$ " + texto


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
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:16px}
.stats .card{margin:0}
.lbl{color:var(--mut);font-size:14px}
.big{font-size:26px;font-weight:600}
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
.hidden{display:none}
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
  <p class="sub">Resumen de {{ mes }} · <a href="{{ url_for('salir') }}">Salir</a></p>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}

  <div class="stats">
    <div class="card"><div class="lbl">Total del mes</div><div class="big">{{ total|peso }}</div></div>
    <div class="card"><div class="lbl">Gastos del mes</div><div class="big">{{ cantidad }}</div></div>
    <div class="card"><div class="lbl">Categoría principal</div><div class="big">{{ por_cat[0][0] if por_cat else '—' }}</div></div>
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
      <select name="tarjeta_id" id="sel-tarjeta">
        <option value="">Elegir tarjeta</option>
        {% for tid, etiqueta in tarjetas %}<option value="{{ tid }}">{{ etiqueta }}</option>{% endfor %}
      </select>
      <select name="banco_id" id="sel-banco" class="hidden">
        <option value="">Elegir banco</option>
        {% for bid, nombre in bancos %}<option value="{{ bid }}">{{ nombre }}</option>{% endfor %}
      </select>
      <button class="primary">Guardar</button>
    </form>
  </div>

  <details class="card">
    <summary>Mis tarjetas y bancos</summary>
    <h2>Tarjetas</h2>
    {% for tid, etiqueta in tarjetas %}
    <div class="item"><span>{{ etiqueta }}</span>
      <form method="post" action="{{ url_for('eliminar_tarjeta', id_=tid) }}" onsubmit="return confirm('¿Eliminar esta tarjeta?')"><button class="del" title="Eliminar">✕</button></form>
    </div>
    {% else %}<p class="lbl">Todavía no cargaste tarjetas.</p>{% endfor %}
    <form class="row" method="post" action="{{ url_for('agregar_tarjeta') }}">
      <select name="tipo">{% for t in tipos %}<option>{{ t }}</option>{% endfor %}</select>
      <input name="ultimos4" placeholder="Últimos 4 dígitos" inputmode="numeric" pattern="[0-9]{4}" maxlength="4" required>
      <select name="banco_id"><option value="">Banco (opcional)</option>{% for bid, nombre in bancos %}<option value="{{ bid }}">{{ nombre }}</option>{% endfor %}</select>
      <button class="primary">Agregar tarjeta</button>
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
    <h2>Por categoría</h2>
    {% for cat, suma in por_cat %}
    <div class="bar">
      <div class="top"><span>{{ cat }}</span><span>{{ suma|peso }} · {{ (suma / total * 100)|round|int }}%</span></div>
      <div class="track"><i style="width:{{ suma / total * 100 }}%;background:{{ cat|color }}"></i></div>
    </div>
    {% else %}<p class="lbl">Todavía no hay gastos este mes.</p>{% endfor %}
  </div>

  <div class="card">
    <h2>Todos los gastos</h2>
    <div class="wrap"><table>
      <tr><th>Fecha</th><th>Categoría</th><th>Descripción</th><th>Medio</th><th class="num">Monto</th><th></th></tr>
      {% for id, fecha, monto, cat, desc, medio in filas %}
      <tr>
        <td>{{ fecha }}</td>
        <td><span class="tag" style="background:{{ cat|color }}">{{ cat }}</span></td>
        <td>{{ desc }}</td>
        <td>{{ medio }}</td>
        <td class="num">{{ monto|peso }}</td>
        <td><form method="post" action="{{ url_for('eliminar', id_=id) }}" onsubmit="return confirm('¿Eliminar este gasto?')"><button class="del" title="Eliminar">✕</button></form></td>
      </tr>
      {% else %}<tr><td colspan="6" class="lbl">Sin gastos todavía.</td></tr>{% endfor %}
    </table></div>
  </div>
</main>
<script>
function cambiarMedio() {
  var medio = document.getElementById('medio').value;
  document.getElementById('sel-tarjeta').classList.toggle('hidden', medio !== 'tarjeta');
  document.getElementById('sel-banco').classList.toggle('hidden', medio !== 'transferencia');
}
cambiarMedio();
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


@app.route("/")
def inicio():
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
                      g.medio, t.tipo, t.ultimos4, bt.nombre, bg.nombre
               FROM gastos g
               LEFT JOIN tarjetas t ON t.id = g.tarjeta_id
               LEFT JOIN bancos bt ON bt.id = t.banco_id
               LEFT JOIN bancos bg ON bg.id = g.banco_id
               ORDER BY g.fecha DESC, g.id DESC"""
        )
    ]
    tarjetas = [
        (tid, etiqueta_tarjeta(tipo, ultimos4, banco))
        for tid, tipo, ultimos4, banco in con.execute(
            """SELECT t.id, t.tipo, t.ultimos4, b.nombre FROM tarjetas t
               LEFT JOIN bancos b ON b.id = t.banco_id ORDER BY t.id"""
        )
    ]
    bancos = con.execute("SELECT id, nombre FROM bancos ORDER BY nombre").fetchall()
    con.close()
    cats = sorted({f[3] for f in filas} | set(CATEGORIAS))
    return render_template_string(
        PAGINA, mes=mes, total=total, cantidad=cantidad, por_cat=por_cat,
        filas=filas, cats=cats, hoy=date.today().isoformat(),
        tarjetas=tarjetas, bancos=bancos, tipos=TIPOS_TARJETA, medios=MEDIOS,
        error=ERRORES.get(request.args.get("error")),
    )


@app.post("/agregar")
def agregar():
    try:
        monto = float(request.form["monto"].strip().replace(",", "."))
        if monto <= 0:
            raise ValueError
        date.fromisoformat(request.form["fecha"])
    except (ValueError, KeyError):
        return redirect(url_for("inicio", error="datos"))
    medio = request.form.get("medio")
    if medio not in MEDIOS:
        return redirect(url_for("inicio", error="datos"))
    # Solo se guarda la tarjeta o el banco que corresponde al medio elegido
    tarjeta_id = a_int(request.form.get("tarjeta_id")) if medio == "tarjeta" else None
    banco_id = a_int(request.form.get("banco_id")) if medio == "transferencia" else None
    categoria = request.form.get("categoria", "").strip().lower() or "otros"
    descripcion = request.form.get("descripcion", "").strip()
    con = conectar()
    con.execute(
        """INSERT INTO gastos (fecha, monto, categoria, descripcion, medio, tarjeta_id, banco_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (request.form["fecha"], monto, categoria, descripcion, medio, tarjeta_id, banco_id),
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
    return redirect(url_for("inicio"))


@app.post("/tarjetas")
def agregar_tarjeta():
    tipo = request.form.get("tipo")
    ultimos4 = request.form.get("ultimos4", "").strip()
    if tipo not in TIPOS_TARJETA or not (len(ultimos4) == 4 and ultimos4.isascii() and ultimos4.isdigit()):
        return redirect(url_for("inicio", error="tarjeta"))
    con = conectar()
    con.execute(
        "INSERT INTO tarjetas (tipo, ultimos4, banco_id) VALUES (?, ?, ?)",
        (tipo, ultimos4, a_int(request.form.get("banco_id"))),
    )
    con.commit()
    con.close()
    return redirect(url_for("inicio"))


@app.post("/tarjetas/<int:id_>/eliminar")
def eliminar_tarjeta(id_):
    con = conectar()
    usada = con.execute("SELECT COUNT(*) FROM gastos WHERE tarjeta_id = ?", (id_,)).fetchone()[0]
    if usada:
        con.close()
        return redirect(url_for("inicio", error="usado"))
    con.execute("DELETE FROM tarjetas WHERE id = ?", (id_,))
    con.commit()
    con.close()
    return redirect(url_for("inicio"))


@app.post("/bancos")
def agregar_banco():
    nombre = request.form.get("nombre", "").strip()
    con = conectar()
    existe = con.execute("SELECT 1 FROM bancos WHERE nombre = ? COLLATE NOCASE", (nombre,)).fetchone()
    if not nombre or existe:
        con.close()
        return redirect(url_for("inicio", error="banco"))
    con.execute("INSERT INTO bancos (nombre) VALUES (?)", (nombre,))
    con.commit()
    con.close()
    return redirect(url_for("inicio"))


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
        return redirect(url_for("inicio", error="usado"))
    con.execute("DELETE FROM bancos WHERE id = ?", (id_,))
    con.commit()
    con.close()
    return redirect(url_for("inicio"))


if __name__ == "__main__":
    # Solo para uso local (contraseña: gastos). En el servidor se define APP_PASSWORD.
    os.environ.setdefault("APP_PASSWORD", "gastos")
    app.run(debug=True)
