"""Marquito: control de gastos personal (Flask).

Uso local:  python app.py   y abre http://localhost:5000
Archivos:   app.py (rutas) · db.py (base de datos) · logica.py (cálculos y constantes)
            templates/ (las páginas HTML)
"""
import hmac
import os
import secrets
import time

# Hora de Argentina: los servidores (PythonAnywhere incluido) usan UTC, y después de las 21 h
# la app creía que ya era el día siguiente.
os.environ["TZ"] = os.environ.get("MARQUITO_TZ", "America/Argentina/Buenos_Aires")
if hasattr(time, "tzset"):
    time.tzset()
from datetime import date, timedelta

from markupsafe import Markup
from flask import Flask, abort, g, redirect, render_template, request, session, url_for

import cotizacion
import cuentas
from db import conectar
from logica import (
    CATEGORIAS,
    ERRORES,
    FRECUENCIAS,
    MESES,
    MEDIOS,
    MODALIDADES,
    MONEDAS_TARJETA,
    ROLES,
    TIPOS_FIJO,
    TIPOS_TARJETA,
    a_int,
    a_monto,
    cobra_en,
    cobros_fijo,
    cobros_pendientes,
    cuotas_prestamo,
    en_pesos,
    eventos_calendario,
    etiqueta_tarjeta,
    fecha_dia,
    gajos,
    monto_vigente,
    periodo_de,
    proximo_cobro,
    proyeccion,
    resumen_objetivo,
    resumenes_tarjetas,
    sumar_meses,
    texto_medio,
    uso_limites,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.permanent_session_lifetime = timedelta(days=30)  # no pide clave todos los días
app.config.update(SESSION_COOKIE_SAMESITE="Lax")
app.jinja_env.globals["zip"] = zip


@app.template_filter("peso")
def peso(valor):
    # Como pide la marca: punto de miles y sin decimales salvo que importen.
    # 184250 -> $ 184.250 · 1500.5 -> $ 1.500,50
    valor = round(valor or 0, 2)
    formato = ",.0f" if valor == int(valor) else ",.2f"
    texto = f"{valor:{formato}}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "$ " + texto


@app.template_filter("numero")
def numero_filtro(valor):
    # Para precargar campos: 35000 -> "35.000" · 1480 -> "1.480" · 10.5 -> "10,50" (la app los lee igual)
    return peso(valor)[2:]


@app.template_filter("usd")
def usd(valor):
    # 10 -> US$ 10 · 10.5 -> US$ 10,50
    return "US" + peso(valor)


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


@app.template_filter("dias_hasta")
def dias_hasta(valor):
    return (valor - date.today()).days


@app.template_filter("fecha_corta")
def fecha_corta(valor):
    # 2026-12-05 -> "5 dic"
    return f"{valor.day} {MESES[valor.month - 1][:3].lower()}"


@app.template_filter("fecha")
def fecha_filtro(valor):
    return valor.strftime("%d/%m/%Y")


DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


@app.template_filter("dia")
def dia_txt(texto):
    """'2026-11-03' -> 'Hoy' / 'Ayer' / 'lun 2 nov' (encabezados de la lista de gastos)."""
    f = date.fromisoformat(texto)
    diferencia = (date.today() - f).days
    if diferencia == 0:
        return "Hoy"
    if diferencia == 1:
        return "Ayer"
    texto = f"{DIAS[f.weekday()]} {f.day} {MESES[f.month - 1][:3].lower()}"
    return texto if f.year == date.today().year else f"{texto} {f.year}"


# Los 8 gajos del símbolo (del brandbook), con el agujero central del medidor.
GAJO_PATHS = [
    "M54.81 10.79A39.5 39.5 0 0 1 74.32 18.87L64.78 31.09A24 24 0 0 0 52.92 26.18Z",
    "M81.13 25.68A39.5 39.5 0 0 1 89.21 45.19L73.82 47.08A24 24 0 0 0 68.91 35.22Z",
    "M89.21 54.81A39.5 39.5 0 0 1 81.13 74.32L68.91 64.78A24 24 0 0 0 73.82 52.92Z",
    "M74.32 81.13A39.5 39.5 0 0 1 54.81 89.21L52.92 73.82A24 24 0 0 0 64.78 68.91Z",
    "M45.19 89.21A39.5 39.5 0 0 1 25.68 81.13L35.22 68.91A24 24 0 0 0 47.08 73.82Z",
    "M18.87 74.32A39.5 39.5 0 0 1 10.79 54.81L26.18 52.92A24 24 0 0 0 31.09 64.78Z",
    "M10.79 45.19A39.5 39.5 0 0 1 18.87 25.68L31.09 35.22A24 24 0 0 0 26.18 47.08Z",
    "M25.68 18.87A39.5 39.5 0 0 1 45.19 10.79L47.08 26.18A24 24 0 0 0 35.22 31.09Z",
]


SIMBOLO_PATHS = [
    ("M54.81 10.79A39.5 39.5 0 0 1 74.32 18.87L58.00 39.76A13 13 0 0 0 51.58 37.10Z", 1),
    ("M81.13 25.68A39.5 39.5 0 0 1 89.21 45.19L62.90 48.42A13 13 0 0 0 60.24 42.00Z", 0.28),
    ("M89.21 54.81A39.5 39.5 0 0 1 81.13 74.32L60.24 58.00A13 13 0 0 0 62.90 51.58Z", 1),
    ("M74.32 81.13A39.5 39.5 0 0 1 54.81 89.21L51.58 62.90A13 13 0 0 0 58.00 60.24Z", 1),
    ("M45.19 89.21A39.5 39.5 0 0 1 25.68 81.13L42.00 60.24A13 13 0 0 0 48.42 62.90Z", 1),
    ("M18.87 74.32A39.5 39.5 0 0 1 10.79 54.81L37.10 51.58A13 13 0 0 0 39.76 58.00Z", 1),
    ("M10.79 45.19A39.5 39.5 0 0 1 18.87 25.68L39.76 42.00A13 13 0 0 0 37.10 48.42Z", 1),
    ("M25.68 18.87A39.5 39.5 0 0 1 45.19 10.79L48.42 37.10A13 13 0 0 0 42.00 39.76Z", 1),
]


@app.template_global()
def simbolo(clase="simbolo"):
    """El símbolo de Marquito (rodaja con el gajo que falta), en el color del texto que lo rodea."""
    caminos = "".join(
        f'<path d="{d}" fill="currentColor" stroke="currentColor" stroke-width="5" stroke-linejoin="round" opacity="{o}"/>'
        for d, o in SIMBOLO_PATHS
    )
    return Markup(f'<svg class="{clase}" viewBox="0 0 100 100" aria-hidden="true">{caminos}</svg>')


@app.template_global()
def medidor(apagados, etiqueta=""):
    """SVG del medidor de gajos: los primeros `apagados` (desde arriba a la derecha) quedan al 22%."""
    caminos = "".join(
        f'<path d="{d}" fill="currentColor" stroke="currentColor" stroke-width="5" '
        f'stroke-linejoin="round" opacity="{0.22 if k < apagados else 1}"/>'
        for k, d in enumerate(GAJO_PATHS)
    )
    return Markup(f'<svg viewBox="0 0 100 100" role="img" aria-label="{etiqueta}">{caminos}</svg>')


@app.context_processor
def datos_comunes():
    return {"usuario": g.get("usuario"), "mes_nombre": MESES[date.today().month - 1]}


ABIERTAS = {"login", "static", "configurar"}


@app.before_request
def exigir_login():
    """Cada pedido: valida la sesión y elige el archivo de datos del usuario."""
    if request.endpoint == "static":
        return None
    if not cuentas.hay_usuarios():  # primera vez: crear la cuenta del administrador
        return None if request.endpoint == "configurar" else redirect(url_for("configurar"))
    if request.endpoint == "configurar":
        return redirect(url_for("login"))
    usuario = cuentas.por_id(session.get("uid"))
    # La sesión deja de valer si la cuenta se borró o se cambió/restableció la contraseña
    if not usuario or session.get("ver") != usuario["sesion_ver"]:
        session.clear()
        return None if request.endpoint == "login" else redirect(url_for("login"))
    if request.endpoint == "login":
        return redirect(url_for("inicio"))
    g.usuario = usuario
    g.db_ruta = cuentas.ruta_datos(usuario)
    if usuario["debe_cambiar"] and request.endpoint not in ("mi_cuenta", "salir"):
        return redirect(url_for("mi_cuenta"))
    return None


def iniciar_sesion(usuario, recordar=True):
    session.clear()
    session["uid"] = usuario["id"]
    session["ver"] = usuario["sesion_ver"]
    session.permanent = recordar  # "recordarme": 30 días; si no, hasta cerrar el navegador
    cuentas.registrar_acceso(usuario["id"])


@app.route("/login", methods=["GET", "POST"])
def login():
    error, nombre_usuario = None, ""
    if request.method == "POST":
        nombre_usuario = request.form.get("usuario", "")
        usuario, error = cuentas.verificar(nombre_usuario, request.form.get("clave", ""))
        if usuario:
            iniciar_sesion(usuario, bool(request.form.get("recordar")))
            return redirect(url_for("inicio"))
    return render_template("login.html", error=error, nombre_usuario=nombre_usuario)


@app.route("/configurar", methods=["GET", "POST"])
def configurar():
    """Solo la primera vez: crea la cuenta del administrador, que sigue usando gastos.db (tus datos)."""
    clave_servidor = os.environ.get("APP_PASSWORD", "")
    error = None if clave_servidor else "Falta APP_PASSWORD en el servidor: sin eso no se puede hacer la configuración inicial."
    form = request.form
    if request.method == "POST" and clave_servidor:
        if not hmac.compare_digest(form.get("clave_servidor", "").encode(), clave_servidor.encode()):
            error = "La contraseña actual de la app no es correcta."
        else:
            error = cuentas.validar_clave(form.get("clave", ""), form.get("clave2", ""))
        if not error:
            usuario, error = cuentas.crear(form.get("nombre", ""), form.get("usuario", ""), form["clave"],
                                           es_admin=True, debe_cambiar=False, archivo="gastos.db")
            if usuario:
                iniciar_sesion(usuario)
                return redirect(url_for("inicio"))
    return render_template("configurar.html", error=error, form=form)


@app.route("/salir")
def salir():
    session.clear()
    return redirect(url_for("login"))


@app.route("/cuenta", methods=["GET", "POST"])
def mi_cuenta():
    error = ok = None
    if request.method == "POST":
        form = request.form
        error = cuentas.cambiar_clave(g.usuario["id"], form.get("actual", ""), form.get("nueva", ""), form.get("nueva2", ""))
        if not error:
            era_temporal = g.usuario["debe_cambiar"]
            iniciar_sesion(cuentas.por_id(g.usuario["id"]), session.permanent)  # sigue adentro en este dispositivo
            if era_temporal:
                return redirect(url_for("inicio"))
            g.usuario = cuentas.por_id(g.usuario["id"])
            ok = "Listo, cambiaste tu contraseña. Se cerró la sesión en tus otros dispositivos."
    error = error or ERRORES.get(request.args.get("error"))
    return render_template("cuenta.html", error=error, ok=ok, ccl=cotizacion.ccl_de(date.today()), hoy=date.today().isoformat())


def solo_admin():
    if not g.usuario["es_admin"]:
        abort(404)


@app.route("/usuarios", methods=["GET", "POST"])
def ver_usuarios():
    """Administración: crear cuentas para la familia con una contraseña temporal."""
    solo_admin()
    error = nueva = None
    if request.method == "POST":
        clave = cuentas.generar_clave()
        creado, error = cuentas.crear(request.form.get("nombre", ""), request.form.get("usuario", ""), clave)
        if creado:
            nueva = {"nombre": creado["nombre"], "usuario": creado["usuario"], "clave": clave, "accion": "creada"}
    return render_template("usuarios.html", usuarios=cuentas.todos(), error=error, nueva=nueva, form=request.form)


@app.post("/usuarios/<int:uid>/restablecer")
def restablecer_usuario(uid):
    solo_admin()
    destino = cuentas.por_id(uid)
    if not destino or destino["id"] == g.usuario["id"]:
        return redirect(url_for("ver_usuarios"))
    clave = cuentas.restablecer(uid)
    nueva = {"nombre": destino["nombre"], "usuario": destino["usuario"], "clave": clave, "accion": "restablecida"}
    return render_template("usuarios.html", usuarios=cuentas.todos(), error=None, nueva=nueva, form={})


@app.post("/usuarios/<int:uid>/borrar")
def borrar_usuario(uid):
    solo_admin()
    if uid != g.usuario["id"]:
        cuentas.borrar(uid)
    return redirect(url_for("ver_usuarios"))


def armar_calendario(compras, tarjetas_det, pagados, fijos, cuotas_por_prestamo, filas_prestamos, objetivos,
                     pagos=(), ccl_hoy=None, registrados=None):
    """Datos de la pestaña Calendario: vista mes o semana, anclada en ?fecha=, con el día elegido en ?dia=."""
    hoy = date.today()
    modo = "semana" if request.args.get("vista") == "semana" else "mes"
    try:
        ancla = date.fromisoformat(request.args.get("fecha", ""))
    except ValueError:
        ancla = hoy
    if modo == "mes":
        primero = ancla.replace(day=1)
        ultimo = fecha_dia(primero.year, primero.month, 31)
        desde = primero - timedelta(days=primero.weekday())        # lunes de la primera semana
        hasta = ultimo + timedelta(days=6 - ultimo.weekday())      # domingo de la última
        anterior = fecha_dia(*sumar_meses(primero.year, primero.month, -1), 1)
        siguiente = fecha_dia(*sumar_meses(primero.year, primero.month, 1), 1)
        titulo = f"{MESES[primero.month - 1]} {primero.year}"
        en_rango = lambda d: d.month == primero.month
    else:
        desde = ancla - timedelta(days=ancla.weekday())
        hasta = desde + timedelta(days=6)
        anterior, siguiente = desde - timedelta(days=7), desde + timedelta(days=7)
        mes_a, mes_b = MESES[desde.month - 1][:3].lower(), MESES[hasta.month - 1][:3].lower()
        titulo = (f"{desde.day} – {hasta.day} {mes_b} {hasta.year}" if desde.month == hasta.month
                  else f"{desde.day} {mes_a} – {hasta.day} {mes_b} {hasta.year}")
        en_rango = lambda d: True
    try:
        elegido = date.fromisoformat(request.args.get("dia", ""))
    except ValueError:
        elegido = hoy if desde <= hoy <= hasta and en_rango(hoy) else (ancla.replace(day=1) if modo == "mes" else desde)

    cortos = {t["id"]: f"{t['tipo']} ••{t['ultimos4']}" for t in tarjetas_det}
    resumenes = resumenes_tarjetas(compras, cortos, pagados, desde, ccl_hoy)
    for r in resumenes:
        r["corto"] = r["tarjeta"]
    personas = {pid: (rol, persona) for pid, persona, rol, *_ in filas_prestamos}
    cuotas = [(personas[pid][0], personas[pid][1], c["vence"], c["monto"], c["pagada"])
              for pid, lista in cuotas_por_prestamo.items() if pid in personas for c in lista]
    con = conectar()
    gastos_por_dia = {
        date.fromisoformat(f): (n, s) for f, n, s in con.execute(
            "SELECT fecha, COUNT(*), SUM(monto) FROM gastos WHERE fecha BETWEEN ? AND ? GROUP BY fecha",
            (desde.isoformat(), hasta.isoformat()))
    }
    con.close()
    con_fecha = [(date.fromisoformat(p["fecha"]), p["tarjeta"], p["total"]) for p in pagos if p["fecha"]]
    eventos = eventos_calendario(desde, hasta, hoy, fijos, resumenes, cuotas, gastos_por_dia, objetivos, con_fecha,
                                 registrados, ccl_hoy)

    dias = []
    d = desde
    while d <= hasta:
        dias.append({"fecha": d, "eventos": eventos.get(d, []), "fuera": not en_rango(d), "hoy": d == hoy})
        d += timedelta(days=1)
    visibles = [e for dia in dias if not dia["fuera"] for e in dia["eventos"]]
    sale = sum(e["monto"] or 0 for e in visibles
               if e["tipo"] in ("fijo", "resumen", "debo") and e["estado"] not in ("pagado", "pagada"))
    entra = sum(e["monto"] or 0 for e in visibles if e["tipo"] == "cobro" and e["estado"] != "cobrada")
    return {"modo": modo, "titulo": titulo, "dias": dias, "elegido": elegido, "hoy": hoy,
            "anterior": anterior, "siguiente": siguiente, "sale": sale, "entra": entra}


def renderizar(vista):
    cotizacion.actualizar()  # trae el CCL si hace falta (como mucho una consulta por hora)
    ccl = cotizacion.ccl_de(date.today())
    ccl_hoy = ccl["valor"] if ccl else None
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
        (id_, fecha, monto, cat, desc, texto_medio(*resto), moneda or "ARS", usd, cot)
        for id_, fecha, monto, cat, desc, moneda, usd, cot, *resto in con.execute(
            """SELECT g.id, g.fecha, g.monto, g.categoria, g.descripcion, g.moneda, g.monto_usd, g.cotizacion,
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
    tarjetas, sin_fechas, limites, tarjetas_det = [], [], [], []
    for tid, tipo, ultimos4, banco, modalidad, cierre, venc, limite, moneda_t, banco_id in con.execute(
        """SELECT t.id, t.tipo, t.ultimos4, b.nombre, t.modalidad, t.dia_cierre, t.dia_vencimiento, t.limite,
                  COALESCE(t.moneda, 'ARS'), t.banco_id
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
        tarjetas_det.append({"id": tid, "tipo": tipo, "ultimos4": ultimos4, "banco": banco, "modalidad": modalidad,
                             "cierre": cierre, "vence": venc, "limite": limite, "etiqueta": etiqueta,
                             "moneda": moneda_t, "banco_id": banco_id})
    bancos = con.execute("SELECT id, nombre FROM bancos ORDER BY nombre").fetchall()
    fila = con.execute(
        """SELECT t.tipo, t.ultimos4, SUM(g.monto) FROM gastos g
           JOIN tarjetas t ON t.id = g.tarjeta_id
           WHERE g.fecha LIKE ? GROUP BY t.id ORDER BY SUM(g.monto) DESC LIMIT 1""",
        (mes + "%",),
    ).fetchone()
    tarjeta_top = (f"{fila[0]} •••• {fila[1]}", fila[2]) if fila else None
    presupuesto = con.execute("SELECT valor FROM ajustes WHERE clave = 'presupuesto'").fetchone()
    medidor_mes = gajos(total, float(presupuesto[0]) if presupuesto else None)
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
                  t.dia_cierre, t.dia_vencimiento, COALESCE(g.moneda, 'ARS'), g.monto_usd
           FROM gastos g JOIN tarjetas t ON t.id = g.tarjeta_id
           WHERE g.medio = 'tarjeta' AND t.modalidad = 'credito'
             AND t.dia_cierre IS NOT NULL AND t.dia_vencimiento IS NOT NULL"""
    ).fetchall()
    montos = {}
    for fid, desde, monto in con.execute("SELECT fijo_id, desde, monto FROM fijos_montos ORDER BY desde"):
        montos.setdefault(fid, []).append((desde, monto))
    filas_fijos = con.execute(
        """SELECT f.id, f.nombre, f.tipo, f.dia_cobro, f.frecuencia, f.mes_inicio,
                  t.tipo, t.ultimos4, b.nombre, t.modalidad, f.cancelado_en, f.activo_hasta,
                  COALESCE(f.moneda, 'ARS'), f.confirmar_desde, f.tarjeta_id, t.dia_cierre, t.dia_vencimiento
           FROM fijos f
           LEFT JOIN tarjetas t ON t.id = f.tarjeta_id
           LEFT JOIN bancos b ON b.id = t.banco_id
           ORDER BY f.dia_cobro, f.nombre"""
    ).fetchall()
    pagados = set(con.execute("SELECT tarjeta_id, periodo FROM resumenes_pagados").fetchall())
    registrados = {(fid, fecha): estado for fid, fecha, estado in
                   con.execute("SELECT fijo_id, fecha, estado FROM fijo_cobros")}
    # Historial de pagos de tarjeta (los resúmenes pagados antes de esta versión no tienen detalle)
    pagos = [dict(zip(("tarjeta_id", "periodo", "fecha", "pesos", "usd", "metodo", "precio", "costo_usd", "usd_ref"), f))
             for f in con.execute(
                 """SELECT r.tarjeta_id, r.periodo, p.fecha, p.pesos, p.usd, p.metodo_usd, p.precio_usd,
                           p.costo_usd, p.usd_ref
                    FROM resumenes_pagados r
                    LEFT JOIN pagos_tarjeta p ON p.tarjeta_id = r.tarjeta_id AND p.periodo = r.periodo
                    ORDER BY COALESCE(p.fecha, r.periodo) DESC""")]
    ultimo_precio = con.execute(
        "SELECT precio_usd FROM pagos_tarjeta WHERE precio_usd IS NOT NULL ORDER BY fecha DESC, id DESC LIMIT 1"
    ).fetchone()
    usd_mes = con.execute(
        "SELECT COALESCE(SUM(monto_usd), 0) FROM gastos WHERE moneda = 'USD' AND fecha LIKE ?", (mes + "%",)
    ).fetchone()[0]
    cuotas_por_prestamo = {}
    for pid, numero, vence, monto, pagada in con.execute(
        "SELECT prestamo_id, numero, vence, monto, pagada FROM prestamo_cuotas ORDER BY prestamo_id, numero"
    ):
        cuotas_por_prestamo.setdefault(pid, []).append(
            {"numero": numero, "vence": date.fromisoformat(vence), "monto": monto, "pagada": bool(pagada)}
        )
    items_por_objetivo = {}
    for iid, oid, nombre_i, estimado, real, cubierto in con.execute(
        "SELECT id, objetivo_id, nombre, estimado, real, cubierto FROM objetivo_items ORDER BY cubierto, id"
    ):
        items_por_objetivo.setdefault(oid, []).append(
            {"id": iid, "nombre": nombre_i, "estimado": estimado, "real": real, "cubierto": bool(cubierto)}
        )
    filas_objetivos = con.execute("SELECT id, nombre, fecha_meta FROM objetivos ORDER BY id").fetchall()
    filas_prestamos = con.execute(
        "SELECT id, persona, rol, monto, total, fecha, cuotas, descripcion FROM prestamos ORDER BY fecha DESC, id DESC"
    ).fetchall()
    con.close()
    proximos = resumenes_tarjetas(compras, {t[0]: t[1] for t in tarjetas}, pagados, date.today(), ccl_hoy)
    cortos = {t["id"]: f"{t['tipo']} ••{t['ultimos4']}" for t in tarjetas_det}
    for pago in pagos:
        pago["tarjeta"] = cortos.get(pago["tarjeta_id"], "Tarjeta borrada")
        pago["total"] = (pago["pesos"] or 0) + (pago["costo_usd"] or 0)
        pago["diferencia"] = (pago["costo_usd"] - pago["usd_ref"]) if pago["costo_usd"] and pago["usd_ref"] else None
    uso_credito = uso_limites(limites, proximos)
    hoy_ = date.today()
    mes_actual = periodo_de(hoy_.year, hoy_.month)
    fijos = []
    for (fid, nombre, tipo_f, dia, frec, inicio, tipo, ultimos4, banco, modalidad, cancelado_en, activo_hasta,
         moneda_f, confirmar_desde, tarjeta_f, cierre_t, venc_t) in filas_fijos:
        historial = montos.get(fid, [])
        fijo = {
            "id": fid, "nombre": nombre, "tipo": TIPOS_FIJO.get(tipo_f, tipo_f), "dia": dia,
            "frecuencia": frec, "frecuencia_txt": FRECUENCIAS.get(frec, f"cada {frec} meses"),
            "mes_inicio": inicio, "montos": historial,
            "tarjeta": etiqueta_tarjeta(tipo, ultimos4, banco, modalidad) if tipo else "",
            # Cancelado: sigue activo hasta la fecha del próximo cobro, que ya no se hace
            "cancelado": bool(cancelado_en),
            "cancelado_en": date.fromisoformat(cancelado_en) if cancelado_en else None,
            "hasta": date.fromisoformat(activo_hasta) if activo_hasta else None,
            "moneda": moneda_f, "tarjeta_id": tarjeta_f,
            "desde": date.fromisoformat(confirmar_desde) if confirmar_desde else hoy_,
            # con tarjeta de crédito, lo cobrado se paga cuando vence el resumen
            "cierre": cierre_t if modalidad == "credito" else None,
            "venc": venc_t if modalidad == "credito" else None,
        }
        fijo["cobros"] = sorted(((date.fromisoformat(f), e) for (i, f), e in registrados.items() if i == fid),
                                reverse=True)[:4]
        fijo["terminado"] = bool(fijo["hasta"] and fijo["hasta"] <= hoy_)
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
    total_mensual = sum(en_pesos(f, f["monto"], ccl_hoy) / f["frecuencia"] for f in fijos if not f["cancelado"])
    primero, ultimo = hoy_.replace(day=1), fecha_dia(hoy_.year, hoy_.month, 31)
    este_mes = sum(en_pesos(f, monto, ccl_hoy) for f in fijos for fecha, monto in cobros_fijo(f, primero, ultimo)
                   if registrados.get((f["id"], fecha.isoformat())) != "fallido")
    pendientes = cobros_pendientes([f for f in fijos], hoy_, registrados)
    for pend in pendientes:
        if pend["fijo"]["moneda"] == "USD":
            dato = cotizacion.ccl_de(pend["fecha"])
            pend["ccl"] = dato["valor"] if dato else None
    prestamos = {"acreedor": [], "deudor": []}
    vencidas = 0
    impagas = []
    for pid, persona, rol, monto, total_p, fecha, n_cuotas, desc in filas_prestamos:
        cuotas = cuotas_por_prestamo.get(pid, [])
        pendientes = [c for c in cuotas if not c["pagada"]]
        for c in cuotas:
            c["vencida"] = not c["pagada"] and c["vence"] < hoy_
        vencidas += sum(c["vencida"] for c in cuotas)
        impagas += [(rol, c["vence"], c["monto"]) for c in pendientes]
        prestamos.setdefault(rol, []).append({
            "id": pid, "persona": persona, "monto": monto, "total": total_p, "intereses": total_p - monto,
            "fecha": date.fromisoformat(fecha), "descripcion": desc, "cuotas": cuotas,
            "pagadas": len(cuotas) - len(pendientes), "pendiente": sum(c["monto"] for c in pendientes),
            "proxima": pendientes[0] if pendientes else None,
            "vencidas": sum(c["vencida"] for c in cuotas),
        })
    objetivos = []
    for oid, nombre_o, meta in filas_objetivos:
        items = items_por_objetivo.get(oid, [])
        fecha_meta = date.fromisoformat(meta) if meta else None
        objetivos.append({"id": oid, "nombre": nombre_o, "fecha_meta": fecha_meta, "lista": items,
                          **resumen_objetivo(items, fecha_meta, hoy_)})
    objetivos.sort(key=lambda o: o["completo"])  # los terminados al final
    saldo_rol = {rol: sum(p["pendiente"] for p in lista) for rol, lista in prestamos.items()}
    proyeccion_meses = proyeccion(fijos, proximos, hoy_, impagas, registrados=registrados, ccl=ccl_hoy)
    cats = sorted({f[3] for f in filas} | set(CATEGORIAS))
    cal = None
    if vista == "calendario":
        cal = armar_calendario(compras, tarjetas_det, pagados, fijos, cuotas_por_prestamo, filas_prestamos, objetivos,
                               pagos, ccl_hoy, registrados)
    return render_template(
        f"{vista}.html", mes=mes, total=total, cantidad=cantidad, por_cat=por_cat, medidor_mes=medidor_mes,
        mes_nombre=MESES[date.today().month - 1],
        filas=filas, cats=cats, hoy=date.today().isoformat(),
        tarjetas=tarjetas, bancos=bancos, tipos=TIPOS_TARJETA, medios=MEDIOS,
        modalidades=MODALIDADES, tarjetas_det=tarjetas_det, tarjeta_top=tarjeta_top, banco_top=banco_top,
        vista=vista, filtros=filtros, total_filtrado=total_filtrado,
        proximos=proximos, sin_fechas=sin_fechas, uso_credito=uso_credito,
        fijos=fijos, total_mensual=total_mensual, este_mes=este_mes, mes_actual=mes_actual,
        tipos_fijo=TIPOS_FIJO, frecuencias=FRECUENCIAS, proyeccion=proyeccion_meses,
        objetivos=objetivos, prestamos=prestamos, saldo_rol=saldo_rol, vencidas=vencidas, roles=ROLES, cal=cal,
        ccl=ccl, ccl_hoy=ccl_hoy, usd_mes=usd_mes, pagos=pagos, monedas_tarjeta=MONEDAS_TARJETA, pendientes=pendientes,
        precio_sugerido=(ultimo_precio[0] if ultimo_precio else ccl_hoy),
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


@app.route("/prestamos")
def ver_prestamos():
    return renderizar("prestamos")


@app.route("/objetivos")
def ver_objetivos():
    return renderizar("objetivos")


@app.route("/calendario")
def ver_calendario():
    return renderizar("calendario")


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
        fecha_gasto = date.fromisoformat(form["fecha"])
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
    # Moneda: la tarjeta manda (solo pesos o solo dólares); si admite las dos o no es tarjeta, elegís vos
    moneda = "USD" if form.get("moneda") == "USD" else "ARS"
    if tarjeta_id:
        fila = con.execute("SELECT COALESCE(moneda, 'ARS') FROM tarjetas WHERE id = ?", (tarjeta_id,)).fetchone()
        if fila and fila[0] in ("ARS", "USD"):
            moneda = fila[0]
    monto_usd = cotizacion_usada = None
    if moneda == "USD":
        monto_usd = monto
        try:  # cotización: la que escribiste o, si la dejaste vacía, el CCL de la fecha del gasto
            cotizacion_usada = a_monto(form["cotizacion"]) if form.get("cotizacion", "").strip() else None
        except ValueError:
            cotizacion_usada = 0
        if cotizacion_usada is None:
            dato = cotizacion.ccl_de(fecha_gasto)
            if not dato:  # todavía no se buscó nunca: buscarla ahora
                cotizacion.actualizar()
                dato = cotizacion.ccl_de(fecha_gasto)
            cotizacion_usada = dato["valor"] if dato else None
        if not cotizacion_usada or cotizacion_usada <= 0:
            con.close()
            return redirect(url_for("inicio", error="sin_ccl" if cotizacion_usada is None else "ccl"))
        monto = round(monto_usd * cotizacion_usada, 2)  # el gasto en pesos de referencia
    credito = tarjeta_id and moneda == "ARS" and con.execute(
        "SELECT 1 FROM tarjetas WHERE id = ? AND modalidad = 'credito'", (tarjeta_id,)
    ).fetchone()
    if credito:  # cuotas e interés solo en pesos (los consumos en dólares van en un pago)
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
                               cuotas, con_interes, total_con_interes, moneda, monto_usd, cotizacion)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (form["fecha"], monto, categoria, descripcion, medio, tarjeta_id, banco_id,
         cuotas, con_interes, total, moneda, monto_usd, cotizacion_usada),
    )
    con.commit()
    con.close()
    return redirect(url_for("inicio"))


@app.post("/eliminar/<int:id_>")
def eliminar(id_):
    con = conectar()
    con.execute("DELETE FROM gastos WHERE id = ?", (id_,))
    con.execute("DELETE FROM fijo_cobros WHERE gasto_id = ?", (id_,))
    con.commit()
    con.close()
    return redirect(url_for("ver_gastos", **{k: request.args.get(k) for k in ("mes", "dia", "tarjeta_id", "banco_id")}))


def leer_tarjeta(form):
    """Valida el formulario de tarjeta (sirve para agregar y para editar). Devuelve un dict o None."""
    tipo = form.get("tipo")
    ultimos4 = form.get("ultimos4", "").strip()
    modalidad = form.get("modalidad")
    moneda = "AMBAS"  # la moneda se elige en cada gasto
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
        return None
    return {"tipo": tipo, "ultimos4": ultimos4, "modalidad": modalidad, "dia_cierre": cierre,
            "dia_vencimiento": venc, "banco_id": a_int(form.get("banco_id")), "limite": limite, "moneda": moneda}


COLUMNAS_TARJETA = ("tipo", "ultimos4", "modalidad", "dia_cierre", "dia_vencimiento", "banco_id", "limite", "moneda")


@app.post("/tarjetas")
def agregar_tarjeta():
    datos = leer_tarjeta(request.form)
    if not datos:
        return redirect(url_for("ver_tarjetas", error="tarjeta"))
    con = conectar()
    existente = con.execute(
        "SELECT id FROM tarjetas WHERE tipo = ? AND ultimos4 = ?", (datos["tipo"], datos["ultimos4"])
    ).fetchone()
    if existente:  # ya estaba cargada: se actualiza en vez de duplicarla
        con.execute(f"UPDATE tarjetas SET {', '.join(c + ' = ?' for c in COLUMNAS_TARJETA)} WHERE id = ?",
                    tuple(datos[c] for c in COLUMNAS_TARJETA) + (existente[0],))
    else:
        con.execute(f"INSERT INTO tarjetas ({', '.join(COLUMNAS_TARJETA)}) VALUES ({', '.join('?' * len(COLUMNAS_TARJETA))})",
                    tuple(datos[c] for c in COLUMNAS_TARJETA))
    con.commit()
    con.close()
    return redirect(url_for("ver_tarjetas"))


@app.post("/tarjetas/<int:id_>/editar")
def editar_tarjeta(id_):
    """Edita una tarjeta en el lugar: sus gastos, resúmenes y pagos siguen asociados."""
    datos = leer_tarjeta(request.form)
    if not datos:
        return redirect(url_for("ver_tarjetas", error="tarjeta", editar=id_))
    con = conectar()
    otra = con.execute("SELECT 1 FROM tarjetas WHERE tipo = ? AND ultimos4 = ? AND id != ?",
                       (datos["tipo"], datos["ultimos4"], id_)).fetchone()
    if otra:
        con.close()
        return redirect(url_for("ver_tarjetas", error="tarjeta_repetida", editar=id_))
    con.execute(f"UPDATE tarjetas SET {', '.join(c + ' = ?' for c in COLUMNAS_TARJETA)} WHERE id = ?",
                tuple(datos[c] for c in COLUMNAS_TARJETA) + (id_,))
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
    con.execute("DELETE FROM pagos_tarjeta WHERE tarjeta_id = ?", (id_,))
    con.commit()
    con.close()
    return redirect(url_for("ver_tarjetas"))


@app.post("/tarjetas/<int:id_>/resumen/<periodo>")
def marcar_resumen(id_, periodo):
    """Registra el pago de un resumen: fecha, parte en pesos y parte en dólares (con cómo la pagaste).
    Pagar la tarjeta NO es un gasto: el gasto ya se contó al comprar. Esto solo salda la deuda
    y guarda cuánto te costaron de verdad los dólares. Con accion=deshacer vuelve a pendiente."""
    try:
        date.fromisoformat(periodo + "-01")
    except ValueError:
        return redirect(url_for("ver_tarjetas"))
    form = request.form
    con = conectar()
    if form.get("accion") == "deshacer":
        con.execute("DELETE FROM resumenes_pagados WHERE tarjeta_id = ? AND periodo = ?", (id_, periodo))
        con.execute("DELETE FROM pagos_tarjeta WHERE tarjeta_id = ? AND periodo = ?", (id_, periodo))
        con.commit()
        con.close()
        return redirect(url_for("ver_tarjetas"))
    try:
        fecha = date.fromisoformat(form.get("fecha", ""))
        pesos = a_monto(form["pesos"]) if form.get("pesos", "").strip() else 0.0
        usd = a_monto(form["usd"]) if form.get("usd", "").strip() else 0.0
        usd_ref = float(form.get("usd_ref") or 0)
        metodo = precio = costo = None
        if usd > 0:
            metodo = form.get("metodo_usd")
            if metodo == "compra":
                precio = a_monto(form.get("precio_usd", ""))
                costo = round(usd * precio, 2)
            elif metodo == "pesos":
                costo = a_monto(form.get("pesos_usd", ""))
                precio = round(costo / usd, 2)
            else:
                raise ValueError
            if precio <= 0 or costo <= 0:
                raise ValueError
        if pesos < 0 or usd < 0:
            raise ValueError
    except (ValueError, KeyError, ZeroDivisionError):
        con.close()
        return redirect(url_for("ver_tarjetas", error="pago"))
    con.execute("INSERT OR IGNORE INTO resumenes_pagados (tarjeta_id, periodo) VALUES (?, ?)", (id_, periodo))
    con.execute(
        """INSERT OR REPLACE INTO pagos_tarjeta
               (tarjeta_id, periodo, fecha, pesos, usd, metodo_usd, precio_usd, costo_usd, usd_ref)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (id_, periodo, fecha.isoformat(), pesos, usd, metodo, precio, costo, usd_ref or None),
    )
    con.commit()
    con.close()
    return redirect(url_for("ver_tarjetas"))


@app.post("/cotizacion")
def guardar_cotizacion():
    """Carga a mano el CCL de un día (solo el administrador: la cotización es de todos)."""
    solo_admin()
    try:
        fecha = date.fromisoformat(request.form.get("fecha", ""))
        valor = a_monto(request.form.get("valor", ""))
        if valor <= 0:
            raise ValueError
    except ValueError:
        return redirect(url_for("mi_cuenta", error="ccl"))
    cotizacion.cargar_manual(fecha, valor)
    return redirect(url_for("mi_cuenta"))


@app.post("/cotizacion/automatica")
def cotizacion_automatica():
    """Saca la cotización manual de hoy y vuelve a pedirla a las APIs."""
    solo_admin()
    cotizacion.borrar_manual(date.today())
    cotizacion.actualizar()
    return redirect(url_for("mi_cuenta"))


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
    moneda = "USD" if form.get("moneda") == "USD" else "ARS"
    con = conectar()
    cur = con.execute(
        """INSERT INTO fijos (nombre, tipo, dia_cobro, frecuencia, mes_inicio, tarjeta_id, moneda, confirmar_desde)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (nombre, tipo, dia, frecuencia, inicio, a_int(form.get("tarjeta_id")), moneda, hoy.isoformat()),
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


@app.post("/fijos/<int:id_>/cancelar")
def cancelar_fijo(id_):
    """Cancela hoy: queda activo hasta la fecha del próximo cobro, que ya no se hace."""
    con = conectar()
    fila = con.execute("SELECT dia_cobro, frecuencia, mes_inicio FROM fijos WHERE id = ?", (id_,)).fetchone()
    if fila:
        hoy = date.today()
        hasta = proximo_cobro({"dia": fila[0], "frecuencia": fila[1], "mes_inicio": fila[2]}, hoy)
        con.execute("UPDATE fijos SET cancelado_en = ?, activo_hasta = ? WHERE id = ?",
                    (hoy.isoformat(), hasta.isoformat(), id_))
        con.commit()
    con.close()
    return redirect(url_for("ver_fijos"))


@app.post("/fijos/<int:id_>/reactivar")
def reactivar_fijo(id_):
    con = conectar()
    con.execute("UPDATE fijos SET cancelado_en = NULL, activo_hasta = NULL WHERE id = ?", (id_,))
    con.commit()
    con.close()
    return redirect(url_for("ver_fijos"))


CATEGORIA_FIJO = {"suscripcion": "suscripciones", "servicio": "servicios", "impuesto": "impuestos",
                  "alquiler": "alquiler", "otro": "otros"}


@app.post("/fijos/<int:id_>/cobro/<fecha>")
def confirmar_cobro(id_, fecha):
    """El día del cobro la app pregunta si se cobró:
    - cobrado: se registra el gasto (con la tarjeta del gasto fijo, si tiene) y entra a su resumen.
    - fallido: queda anotado que no se cobró y no se registra ningún gasto.
    - deshacer: vuelve a quedar para confirmar (y se borra el gasto, si se había registrado)."""
    form = request.form
    volver = "inicio" if form.get("volver") == "inicio" else "ver_fijos"
    try:
        dia = date.fromisoformat(fecha)
    except ValueError:
        return redirect(url_for(volver))
    con = conectar()
    accion = form.get("accion")
    if accion == "deshacer":
        fila = con.execute("SELECT gasto_id FROM fijo_cobros WHERE fijo_id = ? AND fecha = ?", (id_, fecha)).fetchone()
        if fila and fila[0]:
            con.execute("DELETE FROM gastos WHERE id = ?", (fila[0],))
        con.execute("DELETE FROM fijo_cobros WHERE fijo_id = ? AND fecha = ?", (id_, fecha))
    elif accion == "fallido":
        con.execute("INSERT OR REPLACE INTO fijo_cobros (fijo_id, fecha, estado) VALUES (?, ?, 'fallido')", (id_, fecha))
    elif accion == "cobrado":
        fijo = con.execute(
            """SELECT f.nombre, f.tipo, COALESCE(f.moneda, 'ARS'), f.tarjeta_id,
                      (SELECT monto FROM fijos_montos WHERE fijo_id = f.id AND desde <= ? ORDER BY desde DESC LIMIT 1)
               FROM fijos f WHERE f.id = ?""", (fecha[:7], id_)).fetchone()
        if not fijo or con.execute("SELECT 1 FROM fijo_cobros WHERE fijo_id = ? AND fecha = ?", (id_, fecha)).fetchone():
            con.close()
            return redirect(url_for(volver))
        nombre, tipo, moneda, tarjeta_id, vigente = fijo
        try:  # el monto que vino de verdad (si no lo cambiaste, el vigente)
            monto = a_monto(form["monto"]) if form.get("monto", "").strip() else vigente
        except ValueError:
            monto = 0
        if not monto or monto <= 0:
            con.close()
            return redirect(url_for(volver, error="datos"))
        monto_usd = cotizacion_usada = None
        if moneda == "USD":
            dato = cotizacion.ccl_de(dia)
            if not dato:
                cotizacion.actualizar()
                dato = cotizacion.ccl_de(dia)
            if not dato:
                con.close()
                return redirect(url_for(volver, error="sin_ccl"))
            monto_usd, cotizacion_usada = monto, dato["valor"]
            monto = round(monto_usd * cotizacion_usada, 2)
        cur = con.execute(
            """INSERT INTO gastos (fecha, monto, categoria, descripcion, medio, tarjeta_id, cuotas, con_interes,
                                   moneda, monto_usd, cotizacion, fijo_id)
               VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?, ?)""",
            (fecha, monto, CATEGORIA_FIJO.get(tipo, "otros"), nombre, "tarjeta" if tarjeta_id else "transferencia",
             tarjeta_id, moneda, monto_usd, cotizacion_usada, id_),
        )
        con.execute("INSERT INTO fijo_cobros (fijo_id, fecha, estado, gasto_id) VALUES (?, ?, 'cobrado', ?)",
                    (id_, fecha, cur.lastrowid))
    con.commit()
    con.close()
    return redirect(url_for(volver))


@app.post("/fijos/<int:id_>/eliminar")
def eliminar_fijo(id_):
    con = conectar()
    con.execute("DELETE FROM fijos WHERE id = ?", (id_,))
    con.execute("DELETE FROM fijos_montos WHERE fijo_id = ?", (id_,))
    con.execute("DELETE FROM fijo_cobros WHERE fijo_id = ?", (id_,))  # los gastos ya registrados se conservan
    con.commit()
    con.close()
    return redirect(url_for("ver_fijos"))


@app.post("/prestamos")
def agregar_prestamo():
    form = request.form
    persona = form.get("persona", "").strip()
    rol = form.get("rol")
    cuotas = a_int(form.get("cuotas")) or 1
    try:
        monto = a_monto(form.get("monto", ""))
        fecha = date.fromisoformat(form.get("fecha", ""))
        primer = date.fromisoformat(form.get("primer_vencimiento", ""))
        total = a_monto(form.get("total", "")) if form.get("con_interes") else monto
    except ValueError:
        return redirect(url_for("ver_prestamos", error="prestamo"))
    if not persona or rol not in ROLES or monto <= 0 or not 1 <= cuotas <= 120 or total < monto \
            or (form.get("con_interes") and total == monto):
        return redirect(url_for("ver_prestamos", error="prestamo"))
    con = conectar()
    cur = con.execute(
        """INSERT INTO prestamos (persona, rol, monto, total, fecha, cuotas, descripcion)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (persona, rol, monto, total, fecha.isoformat(), cuotas, form.get("descripcion", "").strip()),
    )
    con.executemany(
        "INSERT INTO prestamo_cuotas (prestamo_id, numero, vence, monto) VALUES (?, ?, ?, ?)",
        [(cur.lastrowid, n, vence.isoformat(), m) for n, vence, m in cuotas_prestamo(total, cuotas, primer)],
    )
    con.commit()
    con.close()
    return redirect(url_for("ver_prestamos"))


@app.post("/prestamos/<int:id_>/cuota/<int:numero>")
def marcar_cuota(id_, numero):
    """Marca una cuota como pagada/cobrada; si ya lo estaba, la vuelve a pendiente."""
    con = conectar()
    con.execute("UPDATE prestamo_cuotas SET pagada = 1 - pagada WHERE prestamo_id = ? AND numero = ?", (id_, numero))
    con.commit()
    con.close()
    return redirect(url_for("ver_prestamos"))


@app.post("/prestamos/<int:id_>/eliminar")
def eliminar_prestamo(id_):
    con = conectar()
    con.execute("DELETE FROM prestamos WHERE id = ?", (id_,))
    con.execute("DELETE FROM prestamo_cuotas WHERE prestamo_id = ?", (id_,))
    con.commit()
    con.close()
    return redirect(url_for("ver_prestamos"))


@app.post("/objetivos")
def agregar_objetivo():
    nombre = request.form.get("nombre", "").strip()
    meta = request.form.get("fecha_meta", "").strip()
    try:
        meta = date.fromisoformat(meta).isoformat() if meta else None
    except ValueError:
        meta = ""
    if not nombre or meta == "":
        return redirect(url_for("ver_objetivos", error="objetivo"))
    con = conectar()
    con.execute("INSERT INTO objetivos (nombre, fecha_meta) VALUES (?, ?)", (nombre, meta))
    con.commit()
    con.close()
    return redirect(url_for("ver_objetivos"))


@app.post("/objetivos/<int:id_>/eliminar")
def eliminar_objetivo(id_):
    con = conectar()
    con.execute("DELETE FROM objetivos WHERE id = ?", (id_,))
    con.execute("DELETE FROM objetivo_items WHERE objetivo_id = ?", (id_,))
    con.commit()
    con.close()
    return redirect(url_for("ver_objetivos"))


def monto_opcional(texto):
    """'' -> None; un monto válido -> número; inválido -> ValueError."""
    texto = (texto or "").strip()
    return a_monto(texto) if texto else None


@app.post("/objetivos/<int:id_>/items")
def agregar_item(id_):
    nombre = request.form.get("nombre", "").strip()
    try:
        estimado = a_monto(request.form.get("estimado", ""))
    except ValueError:
        estimado = 0
    if not nombre or estimado <= 0:
        return redirect(url_for("ver_objetivos", error="item", _anchor=f"objetivo-{id_}"))
    con = conectar()
    con.execute("INSERT INTO objetivo_items (objetivo_id, nombre, estimado) VALUES (?, ?, ?)", (id_, nombre, estimado))
    con.commit()
    con.close()
    return redirect(url_for("ver_objetivos", _anchor=f"objetivo-{id_}"))


@app.post("/objetivos/<int:id_>/items/<int:item_id>/cubrir")
def cubrir_item(id_, item_id):
    """Tacha un ítem como cubierto (con su monto real opcional); si ya lo estaba, lo vuelve a pendiente."""
    try:
        real = monto_opcional(request.form.get("real"))
    except ValueError:
        real = -1
    if real is not None and real <= 0:
        return redirect(url_for("ver_objetivos", error="item", _anchor=f"objetivo-{id_}"))
    con = conectar()
    fila = con.execute("SELECT cubierto FROM objetivo_items WHERE id = ? AND objetivo_id = ?", (item_id, id_)).fetchone()
    if fila:
        if fila[0]:
            con.execute("UPDATE objetivo_items SET cubierto = 0, real = NULL WHERE id = ?", (item_id,))
        else:
            con.execute("UPDATE objetivo_items SET cubierto = 1, real = ? WHERE id = ?", (real, item_id))
        con.commit()
    con.close()
    return redirect(url_for("ver_objetivos", _anchor=f"objetivo-{id_}"))


@app.post("/objetivos/<int:id_>/items/<int:item_id>/eliminar")
def eliminar_item(id_, item_id):
    con = conectar()
    con.execute("DELETE FROM objetivo_items WHERE id = ? AND objetivo_id = ?", (item_id, id_))
    con.commit()
    con.close()
    return redirect(url_for("ver_objetivos", _anchor=f"objetivo-{id_}"))


@app.post("/presupuesto")
def guardar_presupuesto():
    """Presupuesto mensual para el medidor de gajos del inicio. Vacío lo borra."""
    texto = request.form.get("presupuesto", "").strip()
    con = conectar()
    if not texto:
        con.execute("DELETE FROM ajustes WHERE clave = 'presupuesto'")
    else:
        try:
            valor = a_monto(texto)
        except ValueError:
            valor = 0
        if valor <= 0:
            con.close()
            return redirect(url_for("inicio", error="presupuesto"))
        con.execute("INSERT OR REPLACE INTO ajustes (clave, valor) VALUES ('presupuesto', ?)", (str(valor),))
    con.commit()
    con.close()
    return redirect(url_for("inicio"))


if __name__ == "__main__":
    # Solo para uso local: "gastos" es la contraseña de la configuración inicial.
    # En el servidor se define APP_PASSWORD en el archivo WSGI.
    os.environ.setdefault("APP_PASSWORD", "gastos")
    app.run(debug=True)
