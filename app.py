"""Control de gastos: aplicación web (Flask).

Uso local:  python app.py   y abre http://localhost:5000
Archivos:   app.py (rutas) · db.py (base de datos) · logica.py (cálculos y constantes)
            templates/ (las páginas HTML)
"""
import hmac
import os
import secrets
from datetime import date, timedelta

from flask import Flask, redirect, render_template, request, session, url_for

from db import conectar
from logica import (
    CATEGORIAS,
    ERRORES,
    FRECUENCIAS,
    MESES,
    MEDIOS,
    MODALIDADES,
    TIPOS_FIJO,
    TIPOS_TARJETA,
    a_int,
    a_monto,
    cobra_en,
    etiqueta_tarjeta,
    fecha_dia,
    monto_vigente,
    periodo_de,
    proyeccion,
    resumenes_tarjetas,
    sumar_meses,
    texto_medio,
    uso_limites,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.permanent_session_lifetime = timedelta(days=30)  # no pide clave todos los días
app.config.update(SESSION_COOKIE_SAMESITE="Lax")


@app.template_filter("peso")
def peso(valor):
    # 1500.5 -> $ 1.500,50
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "$ " + texto


@app.template_filter("corto")
def corto(valor):
    # 85400 -> $ 85,4 mil · 1250000 -> $ 1,3 M (para las etiquetas del gráfico)
    if valor >= 1_000_000:
        texto = f"{valor / 1_000_000:.1f} M"
    elif valor >= 1_000:
        texto = f"{valor / 1_000:.1f} mil"
    else:
        texto = f"{valor:.0f}"
    return "$ " + texto.replace(".0 ", " ").replace(".", ",")


@app.template_filter("mes")
def mes_txt(periodo):
    # "2026-12" -> "dic 2026"
    anio, mes = periodo.split("-")
    return f"{MESES[int(mes) - 1][:3].lower()} {anio}"


@app.template_filter("fecha")
def fecha_filtro(valor):
    return valor.strftime("%d/%m/%Y")


@app.template_filter("color")
def color(categoria):
    return f"hsl({sum(map(ord, categoria)) * 37 % 360}, 65%, 50%)"


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
    return render_template("login.html", error=error)


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
    filtros = {"mes": "", "dia": "", "tarjeta": None, "banco": None}
    clausulas, params = [], []
    if vista == "gastos":
        args = request.args
        filtros["mes"] = args.get("mes", "" if args else mes)  # sin filtros en la URL: mes actual
        filtros["dia"] = args.get("dia", "")
        for clave in ("mes", "dia"):
            try:
                date.fromisoformat(filtros[clave] + ("-01" if clave == "mes" else ""))
            except ValueError:
                filtros[clave] = ""
        filtros["tarjeta"] = a_int(args.get("tarjeta_id"))
        filtros["banco"] = a_int(args.get("banco_id"))
        if filtros["dia"]:  # el día es más específico que el mes
            clausulas.append("g.fecha = ?")
            params.append(filtros["dia"])
        elif filtros["mes"]:
            clausulas.append("g.fecha LIKE ?")
            params.append(filtros["mes"] + "%")
        if filtros["tarjeta"]:
            clausulas.append("g.tarjeta_id = ?")
            params.append(filtros["tarjeta"])
        if filtros["banco"]:  # transferencias desde ese banco + compras con tarjetas de ese banco
            clausulas.append("COALESCE(t.banco_id, g.banco_id) = ?")
            params.append(filtros["banco"])
    donde = "WHERE " + " AND ".join(clausulas) if clausulas else ""
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
               """ + donde + " ORDER BY g.fecha DESC, g.id DESC",
            params,
        )
    ]
    total_filtrado = sum(f[2] for f in filas)
    tarjetas, sin_fechas, limites = [], [], []
    for tid, tipo, ultimos4, banco, modalidad, cierre, venc, limite in con.execute(
        """SELECT t.id, t.tipo, t.ultimos4, b.nombre, t.modalidad, t.dia_cierre, t.dia_vencimiento, t.limite
           FROM tarjetas t LEFT JOIN bancos b ON b.id = t.banco_id ORDER BY t.id"""
    ):
        etiqueta = etiqueta_tarjeta(tipo, ultimos4, banco, modalidad)
        if modalidad != "credito":
            info = ""
        elif cierre and venc:
            info = f"cierra el {cierre} · vence el {venc} · " + (f"límite {peso(limite)}" if limite else "sin límite")
        else:
            info = "falta cierre y vencimiento"
            sin_fechas.append(etiqueta)
        if modalidad == "credito" and limite:
            limites.append((tid, etiqueta, limite))
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
    montos = {}
    for fid, desde, monto in con.execute("SELECT fijo_id, desde, monto FROM fijos_montos ORDER BY desde"):
        montos.setdefault(fid, []).append((desde, monto))
    filas_fijos = con.execute(
        """SELECT f.id, f.nombre, f.tipo, f.dia_cobro, f.frecuencia, f.mes_inicio,
                  t.tipo, t.ultimos4, b.nombre, t.modalidad
           FROM fijos f
           LEFT JOIN tarjetas t ON t.id = f.tarjeta_id
           LEFT JOIN bancos b ON b.id = t.banco_id
           ORDER BY f.dia_cobro, f.nombre"""
    ).fetchall()
    pagados = set(con.execute("SELECT tarjeta_id, periodo FROM resumenes_pagados").fetchall())
    con.close()
    proximos = resumenes_tarjetas(compras, {t[0]: t[1] for t in tarjetas}, pagados, date.today())
    uso_credito = uso_limites(limites, proximos)
    hoy_ = date.today()
    mes_actual = periodo_de(hoy_.year, hoy_.month)
    fijos = []
    for fid, nombre, tipo_f, dia, frec, inicio, tipo, ultimos4, banco, modalidad in filas_fijos:
        historial = montos.get(fid, [])
        fijo = {
            "id": fid, "nombre": nombre, "tipo": TIPOS_FIJO.get(tipo_f, tipo_f), "dia": dia,
            "frecuencia": frec, "frecuencia_txt": FRECUENCIAS.get(frec, f"cada {frec} meses"),
            "mes_inicio": inicio, "montos": historial,
            "tarjeta": etiqueta_tarjeta(tipo, ultimos4, banco, modalidad) if tipo else "",
        }
        # Monto actual: el vigente hoy, o el primero si todavía no empezó a cobrarse
        vigente = monto_vigente(historial, mes_actual)
        fijo["monto"] = vigente if vigente is not None else (historial[0][1] if historial else 0)
        futuros = [(d, m) for d, m in historial if d > mes_actual]
        fijo["empieza"] = historial[0][0] if vigente is None and historial else None
        fijo["aumento"] = (futuros[1] if fijo["empieza"] and len(futuros) > 1
                           else None if fijo["empieza"] else futuros[0] if futuros else None)
        fijo["anteriores"] = [(d, m) for d, m in historial if d < mes_actual][::-1]
        for k in range(13):  # próximo cobro dentro del año
            a, m = sumar_meses(hoy_.year, hoy_.month, k)
            if cobra_en(fijo, a, m) and (k > 0 or dia >= hoy_.day):
                fijo["proximo"] = fecha_dia(a, m, dia).strftime("%d/%m/%Y")
                break
        fijos.append(fijo)
    total_mensual = sum(f["monto"] / f["frecuencia"] for f in fijos)
    este_mes = sum(monto_vigente(f["montos"], mes_actual) or 0 for f in fijos if cobra_en(f, hoy_.year, hoy_.month))
    proyeccion_meses = proyeccion(fijos, proximos, hoy_)
    cats = sorted({f[3] for f in filas} | set(CATEGORIAS))
    return render_template(
        f"{vista}.html", mes=mes, total=total, cantidad=cantidad, por_cat=por_cat,
        filas=filas, cats=cats, hoy=date.today().isoformat(),
        tarjetas=tarjetas, bancos=bancos, tipos=TIPOS_TARJETA, medios=MEDIOS,
        modalidades=MODALIDADES, tarjeta_top=tarjeta_top, banco_top=banco_top,
        vista=vista, filtros=filtros, total_filtrado=total_filtrado,
        proximos=proximos, sin_fechas=sin_fechas, uso_credito=uso_credito,
        fijos=fijos, total_mensual=total_mensual, este_mes=este_mes, mes_actual=mes_actual,
        tipos_fijo=TIPOS_FIJO, frecuencias=FRECUENCIAS, proyeccion=proyeccion_meses,
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


@app.route("/proyeccion")
def ver_proyeccion():
    return renderizar("proyeccion")


@app.route("/fijos")
def ver_fijos():
    return renderizar("fijos")


@app.route("/suscripciones")
def ver_suscripciones():  # dirección vieja: lleva a Gastos fijos
    return redirect(url_for("ver_fijos"))


@app.post("/agregar")
def agregar():
    form = request.form
    try:
        monto = a_monto(form["monto"])
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
                total = a_monto(form.get("total_con_interes", ""))
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
    return redirect(url_for("ver_gastos", **{k: request.args.get(k) for k in ("mes", "dia", "tarjeta_id", "banco_id")}))


@app.post("/tarjetas")
def agregar_tarjeta():
    form = request.form
    tipo = form.get("tipo")
    ultimos4 = form.get("ultimos4", "").strip()
    modalidad = form.get("modalidad")
    cierre, venc = a_int(form.get("dia_cierre")), a_int(form.get("dia_vencimiento"))
    limite = None
    if modalidad == "debito":
        cierre = venc = None
    elif form.get("limite", "").strip():
        try:
            limite = a_monto(form["limite"])
        except ValueError:
            limite = 0
    valida = (
        tipo in TIPOS_TARJETA
        and modalidad in MODALIDADES
        and len(ultimos4) == 4 and ultimos4.isascii() and ultimos4.isdigit()
        and (modalidad == "debito" or (cierre and venc and 1 <= cierre <= 31 and 1 <= venc <= 31))
        and (limite is None or limite > 0)
    )
    if not valida:
        return redirect(url_for("ver_tarjetas", error="tarjeta"))
    con = conectar()
    datos = (modalidad, cierre, venc, a_int(form.get("banco_id")), limite)
    existente = con.execute(
        "SELECT id FROM tarjetas WHERE tipo = ? AND ultimos4 = ?", (tipo, ultimos4)
    ).fetchone()
    if existente:  # misma tarjeta (tipo + 4 dígitos): se actualizan sus datos
        con.execute(
            "UPDATE tarjetas SET modalidad = ?, dia_cierre = ?, dia_vencimiento = ?, banco_id = ?, limite = ? WHERE id = ?",
            datos + (existente[0],),
        )
    else:
        con.execute(
            "INSERT INTO tarjetas (tipo, ultimos4, modalidad, dia_cierre, dia_vencimiento, banco_id, limite) VALUES (?, ?, ?, ?, ?, ?, ?)",
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
                + (SELECT COUNT(*) FROM fijos WHERE tarjeta_id = ?)""",
        (id_, id_),
    ).fetchone()[0]
    if usada:
        con.close()
        return redirect(url_for("ver_tarjetas", error="usado"))
    con.execute("DELETE FROM tarjetas WHERE id = ?", (id_,))
    con.execute("DELETE FROM resumenes_pagados WHERE tarjeta_id = ?", (id_,))
    con.commit()
    con.close()
    return redirect(url_for("ver_tarjetas"))


@app.post("/tarjetas/<int:id_>/resumen/<periodo>")
def marcar_resumen(id_, periodo):
    """Marca un resumen como pagado (libera el límite y lo saca de la proyección). Si ya lo estaba, lo desmarca."""
    try:
        date.fromisoformat(periodo + "-01")
    except ValueError:
        return redirect(url_for("ver_tarjetas"))
    con = conectar()
    if con.execute("SELECT 1 FROM resumenes_pagados WHERE tarjeta_id = ? AND periodo = ?", (id_, periodo)).fetchone():
        con.execute("DELETE FROM resumenes_pagados WHERE tarjeta_id = ? AND periodo = ?", (id_, periodo))
    else:
        con.execute("INSERT INTO resumenes_pagados (tarjeta_id, periodo) VALUES (?, ?)", (id_, periodo))
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


def mes_valido(texto):
    try:
        date.fromisoformat(texto + "-01")
        return True
    except (TypeError, ValueError):
        return False


@app.post("/fijos")
def agregar_fijo():
    form = request.form
    nombre = form.get("nombre", "").strip()
    tipo = form.get("tipo")
    try:
        monto = a_monto(form.get("monto", ""))
    except ValueError:
        monto = 0
    dia = a_int(form.get("dia_cobro"))
    frecuencia = a_int(form.get("frecuencia"))
    hoy = date.today()
    inicio = form.get("mes_inicio", "") if frecuencia != 1 else periodo_de(hoy.year, hoy.month)
    if (not nombre or tipo not in TIPOS_FIJO or monto <= 0 or not dia or not 1 <= dia <= 31
            or frecuencia not in FRECUENCIAS or not mes_valido(inicio)):
        return redirect(url_for("ver_fijos", error="fijo"))
    con = conectar()
    cur = con.execute(
        """INSERT INTO fijos (nombre, tipo, dia_cobro, frecuencia, mes_inicio, tarjeta_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (nombre, tipo, dia, frecuencia, inicio, a_int(form.get("tarjeta_id"))),
    )
    con.execute("INSERT INTO fijos_montos (fijo_id, desde, monto) VALUES (?, ?, ?)", (cur.lastrowid, inicio, monto))
    con.commit()
    con.close()
    return redirect(url_for("ver_fijos"))


@app.post("/fijos/<int:id_>/monto")
def actualizar_monto(id_):
    """Registra un monto nuevo que rige desde el mes indicado; los meses anteriores no cambian."""
    form = request.form
    desde = form.get("desde", "")
    try:
        monto = a_monto(form.get("monto", ""))
    except ValueError:
        monto = 0
    if monto <= 0 or not mes_valido(desde):
        return redirect(url_for("ver_fijos", error="monto_fijo"))
    con = conectar()
    con.execute("INSERT OR REPLACE INTO fijos_montos (fijo_id, desde, monto) VALUES (?, ?, ?)", (id_, desde, monto))
    con.commit()
    con.close()
    return redirect(url_for("ver_fijos"))


@app.post("/fijos/<int:id_>/eliminar")
def eliminar_fijo(id_):
    con = conectar()
    con.execute("DELETE FROM fijos WHERE id = ?", (id_,))
    con.execute("DELETE FROM fijos_montos WHERE fijo_id = ?", (id_,))
    con.commit()
    con.close()
    return redirect(url_for("ver_fijos"))


if __name__ == "__main__":
    # Solo para uso local (contraseña: gastos). En el servidor se define APP_PASSWORD.
    os.environ.setdefault("APP_PASSWORD", "gastos")
    app.run(debug=True)
