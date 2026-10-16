"""Control de gastos - Versión 2: interfaz web (Flask)

Uso:  python app.py   y abre http://localhost:5000 en el navegador.
Usa la misma base de datos (gastos.db) que gastos.py.
"""
import os
from datetime import date

from flask import Flask, redirect, render_template_string, request, url_for

import gastos  # reutiliza la tabla y la conexión de la versión 1

gastos.DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gastos.db")
app = Flask(__name__)
CATEGORIAS = ["comida", "transporte", "ocio", "hogar", "salud", "otros"]


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
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:16px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:16px}
.stats .card{margin:0}
.lbl{color:var(--mut);font-size:14px}
.big{font-size:26px;font-weight:600}
form.add{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
input,button{font:inherit;padding:9px 11px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--txt)}
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
</style>
</head>
<body>
<main>
  <h1>Control de gastos</h1>
  <p class="sub">Resumen de {{ mes }}</p>
  {% if error %}<div class="err">Revisa el monto (número mayor a 0) y la fecha.</div>{% endif %}

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
      <button class="primary">Guardar</button>
    </form>
  </div>

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
      <tr><th>Fecha</th><th>Categoría</th><th>Descripción</th><th class="num">Monto</th><th></th></tr>
      {% for id, fecha, monto, cat, desc in filas %}
      <tr>
        <td>{{ fecha }}</td>
        <td><span class="tag" style="background:{{ cat|color }}">{{ cat }}</span></td>
        <td>{{ desc }}</td>
        <td class="num">{{ monto|peso }}</td>
        <td><form method="post" action="{{ url_for('eliminar', id_=id) }}" onsubmit="return confirm('¿Eliminar este gasto?')"><button class="del" title="Eliminar">✕</button></form></td>
      </tr>
      {% else %}<tr><td colspan="5" class="lbl">Sin gastos todavía.</td></tr>{% endfor %}
    </table></div>
  </div>
</main>
</body>
</html>"""


@app.route("/")
def inicio():
    con = gastos.conectar()
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
    filas = con.execute(
        "SELECT id, fecha, monto, categoria, descripcion FROM gastos ORDER BY fecha DESC, id DESC"
    ).fetchall()
    con.close()
    cats = sorted({f[3] for f in filas} | set(CATEGORIAS))
    return render_template_string(
        PAGINA, mes=mes, total=total, cantidad=cantidad, por_cat=por_cat,
        filas=filas, cats=cats, hoy=date.today().isoformat(),
        error=request.args.get("error"),
    )


@app.post("/agregar")
def agregar():
    try:
        monto = float(request.form["monto"].strip().replace(",", "."))
        if monto <= 0:
            raise ValueError
        date.fromisoformat(request.form["fecha"])
    except (ValueError, KeyError):
        return redirect(url_for("inicio", error=1))
    categoria = request.form.get("categoria", "").strip().lower() or "otros"
    descripcion = request.form.get("descripcion", "").strip()
    con = gastos.conectar()
    con.execute(
        "INSERT INTO gastos (fecha, monto, categoria, descripcion) VALUES (?, ?, ?, ?)",
        (request.form["fecha"], monto, categoria, descripcion),
    )
    con.commit()
    con.close()
    return redirect(url_for("inicio"))


@app.post("/eliminar/<int:id_>")
def eliminar(id_):
    con = gastos.conectar()
    con.execute("DELETE FROM gastos WHERE id = ?", (id_,))
    con.commit()
    con.close()
    return redirect(url_for("inicio"))


if __name__ == "__main__":
    app.run(debug=True)
