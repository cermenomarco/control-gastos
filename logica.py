"""Constantes y cálculos de la app, sin Flask ni base de datos:
reparto de cuotas por resumen de tarjeta, proyección mensual, etiquetas."""
from calendar import monthrange
from datetime import date, timedelta

CATEGORIAS = ["comida", "transporte", "ocio", "hogar", "salud", "otros"]
TIPOS_TARJETA = ["Visa", "Mastercard", "American Express"]
MEDIOS = {"tarjeta": "Tarjeta", "transferencia": "Transferencia", "efectivo": "Efectivo"}
MODALIDADES = {"credito": "Crédito", "debito": "Débito"}
MONEDAS_TARJETA = {"ARS": "Pesos", "USD": "Dólares", "AMBAS": "Pesos y dólares"}
TIPOS_FIJO = {"suscripcion": "Suscripción", "servicio": "Servicio", "impuesto": "Impuesto",
              "alquiler": "Alquiler", "otro": "Otro"}
ROLES = {"acreedor": "Me deben", "deudor": "Debo"}
FRECUENCIAS = {1: "Mensual", 2: "Bimestral", 3: "Trimestral", 6: "Semestral", 12: "Anual"}
ERRORES = {
    "cobro_pasado": "Revisá la fecha del cobro: tiene que ser hoy o un día que ya pasó.",
    "datos": "Revisá el monto (mayor a 0), la fecha y el medio de pago.",
    "tarjeta": "Revisá la tarjeta: tipo, los 4 dígitos y, si es de crédito, el día de cierre y de vencimiento (1 a 31).",
    "cuotas": "Las cuotas van de 1 a 60.",
    "fijo": "Revisá el gasto fijo: nombre, monto mayor a 0, día de cobro (1 a 31), frecuencia y mes del primer cobro.",
    "prestamo": "Revisá el préstamo: persona, monto mayor a 0, fechas, cuotas (1 a 120) y, si hay interés, un total a devolver mayor al monto.",
    "objetivo": "Ponele un nombre al objetivo (la fecha meta es opcional).",
    "item": "Revisá el ítem: nombre y monto estimado mayor a 0 (y el monto real, si lo cargás).",
    "monto_fijo": "Revisá el nuevo monto (mayor a 0) y el mes desde el que rige.",
    "interes": "Si hay interés, poné el total a pagar (mayor al monto).",
    "banco": "Ese banco ya está cargado o el nombre está vacío.",
    "usado": "No se puede borrar: tiene gastos, tarjetas o gastos fijos asociados.",
    "presupuesto": "El presupuesto tiene que ser un monto mayor a 0.",
    "moneda": "Esa tarjeta no admite esa moneda.",
    "tarjeta_repetida": "Ya tenés otra tarjeta con ese tipo y esos 4 dígitos.",
    "sin_ccl": "Todavía no hay cotización del CCL para convertir: cargala a mano en Mi cuenta o poné la cotización en el gasto.",
    "pago": "Revisá el pago: fecha, montos mayores o iguales a 0 y, si hay dólares, cómo los pagaste y a qué precio.",
    "ccl": "La cotización tiene que ser un número mayor a 0.",
}


def a_int(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def a_monto(texto):
    """Convierte un monto escrito a la argentina en número: 1500,50 · 1.500,50 · 1.500.000 · 1500.50.
    Lanza ValueError si no es un número."""
    texto = texto.strip().replace(" ", "")
    if "," in texto:  # la coma es el decimal y los puntos son separadores de miles
        texto = texto.replace(".", "").replace(",", ".")
    elif texto.count(".") > 1 or (
        texto.count(".") == 1 and len(texto.split(".")[1]) == 3
    ):  # 1.500.000 o 300.000: los puntos son separadores de miles
        texto = texto.replace(".", "")
    valor = float(texto)
    if valor != valor or valor in (float("inf"), float("-inf")):
        raise ValueError(texto)
    return valor


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


def resumenes_tarjetas(compras, nombres, pagados, hoy, ccl_hoy=None):
    """Reparte las cuotas de cada compra en el resumen (cierre) que le toca.
    Una compra hasta el día de cierre entra a ese resumen; después, al siguiente.
    El vencimiento es la primera fecha con el día de vencimiento posterior al cierre.
    Cada resumen tiene dos saldos, como el del banco: en pesos y en dólares.
    compras: (tarjeta_id, fecha, monto en pesos, cuotas, con_interes, total, cierre, vencimiento, moneda, monto_usd).
    pagados: conjunto de (tarjeta_id, "AAAA-MM del cierre") ya pagados.
    a_pagar: estimación en pesos (los dólares, al CCL de hoy si se conoce).
    Devuelve, ordenados por vencimiento, los resúmenes que aún no vencieron (lista de dicts)."""
    acumulado = {}
    for tid, fecha, monto, cuotas, con_interes, total, cierre, venc, moneda, monto_usd in compras:
        f = date.fromisoformat(fecha)
        anio, mes = f.year, f.month
        if f > fecha_dia(anio, mes, cierre):
            anio, mes = sumar_meses(anio, mes, 1)
        en_usd = moneda == "USD" and monto_usd
        cuotas = 1 if en_usd else (cuotas or 1)
        a_pagar = total if con_interes and total and not en_usd else monto
        for k in range(cuotas):
            a, m = sumar_meses(anio, mes, k)
            c = acumulado.setdefault((tid, a, m), {"pesos": 0.0, "intereses": 0.0, "usd": 0.0, "usd_ref": 0.0,
                                                   "cierre": cierre, "venc": venc})
            if en_usd:
                c["usd"] += monto_usd
                c["usd_ref"] += monto  # el gasto en pesos al CCL de su día
            else:
                c["pesos"] += a_pagar / cuotas
                c["intereses"] += (a_pagar - monto) / cuotas
    filas = []
    for (tid, a, m), c in acumulado.items():
        cierra = fecha_dia(a, m, c["cierre"])
        va, vm = (a, m) if c["venc"] > c["cierre"] else sumar_meses(a, m, 1)
        vence = fecha_dia(va, vm, c["venc"])
        if vence >= hoy:
            periodo = f"{a:04d}-{m:02d}"
            usd_estimado = c["usd"] * ccl_hoy if ccl_hoy else c["usd_ref"]
            filas.append({
                "tarjeta_id": tid, "tarjeta": nombres.get(tid, "—"), "periodo": periodo,
                "cierra": cierra, "vence": vence, "pesos": c["pesos"], "usd": c["usd"], "usd_ref": c["usd_ref"],
                "a_pagar": c["pesos"] + usd_estimado, "intereses": c["intereses"],
                "pagado": (tid, periodo) in pagados,
            })
    filas.sort(key=lambda f: (f["vence"], f["tarjeta"]))
    return filas


MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def periodo_de(anio, mes):
    return f"{anio:04d}-{mes:02d}"


def monto_vigente(montos, periodo):
    """montos: lista de (desde "AAAA-MM", monto). Devuelve el que rige en ese período, o None si aún no empezó."""
    vigente = None
    for desde, monto in sorted(montos):
        if desde <= periodo:
            vigente = monto
    return vigente


def cobra_en(fijo, anio, mes):
    """True si el gasto fijo se cobra ese mes, según su primer mes de cobro y su frecuencia.
    Si está cancelado, no se cobra desde su fecha de fin ("hasta") en adelante."""
    ia, im = map(int, fijo["mes_inicio"].split("-"))
    meses = (anio * 12 + mes) - (ia * 12 + im)
    if meses < 0 or meses % fijo["frecuencia"]:
        return False
    hasta = fijo.get("hasta")
    return not (hasta and fecha_dia(anio, mes, fijo["dia"]) >= hasta)


def proximo_cobro(fijo, despues_de):
    """Primera fecha de cobro estrictamente posterior a `despues_de` (sin mirar si está cancelado).
    Es la fecha hasta la que sigue activo un gasto fijo que se cancela ese día."""
    sin_fin = {**fijo, "hasta": None}
    for k in range(0, 13 * 12):
        a, m = sumar_meses(despues_de.year, despues_de.month, k)
        if cobra_en(sin_fin, a, m) and fecha_dia(a, m, fijo["dia"]) > despues_de:
            return fecha_dia(a, m, fijo["dia"])
    return despues_de


def cuotas_prestamo(total, cuotas, primer_vencimiento):
    """Calendario de un préstamo: una cuota por mes desde el primer vencimiento, mismo día.
    La última absorbe el redondeo para que la suma dé exactamente el total."""
    base = round(total / cuotas, 2)
    filas = []
    for k in range(cuotas):
        a, m = sumar_meses(primer_vencimiento.year, primer_vencimiento.month, k)
        monto = base if k < cuotas - 1 else round(total - base * (cuotas - 1), 2)
        filas.append((k + 1, fecha_dia(a, m, primer_vencimiento.day), monto))
    return filas


def vencimiento_resumen(fecha, cierre, venc):
    """Fecha de vencimiento del resumen en el que entra una compra de ese día."""
    a, m = fecha.year, fecha.month
    if fecha > fecha_dia(a, m, cierre):
        a, m = sumar_meses(a, m, 1)
    va, vm = (a, m) if venc > cierre else sumar_meses(a, m, 1)
    return fecha_dia(va, vm, venc)


def cobros_fijo(fijo, desde, hasta):
    """Cobros de un gasto fijo entre dos fechas: (fecha, monto en la moneda del fijo)."""
    a, m = desde.year, desde.month
    while (a, m) <= (hasta.year, hasta.month):
        if cobra_en(fijo, a, m):
            fecha = fecha_dia(a, m, fijo["dia"])
            monto = monto_vigente(fijo["montos"], periodo_de(a, m))
            if desde <= fecha <= hasta and monto:
                yield fecha, monto
        a, m = sumar_meses(a, m, 1)


def en_pesos(fijo, monto, ccl):
    """Monto de un gasto fijo en pesos (los de dólares, al CCL indicado; sin CCL no se pueden estimar)."""
    if fijo.get("moneda") == "USD":
        return monto * ccl if ccl else 0.0
    return monto


VENTANA_PENDIENTES = timedelta(days=92)  # cobros sin confirmar más viejos que esto no se piden


def cobros_pendientes(fijos, hoy, registrados):
    """Cobros que ya tocaron (hasta hoy) y todavía no confirmaste ni marcaste como fallidos.
    registrados: {(fijo_id, "AAAA-MM-DD"): estado}."""
    pendientes = []
    for f in fijos:
        desde = max(f.get("desde") or hoy, hoy - VENTANA_PENDIENTES)
        for fecha, monto in cobros_fijo(f, desde, hoy):
            if (f["id"], fecha.isoformat()) not in registrados:
                pendientes.append({"fijo": f, "fecha": fecha, "monto": monto})
    pendientes.sort(key=lambda p: (p["fecha"], p["fijo"]["nombre"]))
    return pendientes


def compromisos_fijos(fijos, hoy, meses, registrados, ccl, detalle=None):
    """Lo que falta pagar de gastos fijos, por mes: cobros futuros y pendientes de confirmar.
    Los que se pagan con tarjeta de crédito cuentan en el mes en que vence su resumen.
    Los ya confirmados no cuentan acá: son gastos (y si fueron con tarjeta, ya están en el resumen)."""
    por_mes = {}
    este_mes = date(hoy.year, hoy.month, 1)
    limite = fecha_dia(*sumar_meses(hoy.year, hoy.month, meses - 1), 31)
    for f in fijos:
        desde = max(f.get("desde") or hoy, hoy - VENTANA_PENDIENTES)
        for fecha, monto in cobros_fijo(f, desde, limite):
            if (f["id"], fecha.isoformat()) in registrados:
                continue
            cuando = vencimiento_resumen(fecha, f["cierre"], f["venc"]) if f.get("cierre") and f.get("venc") else fecha
            cuando = max(cuando, este_mes)
            clave = (cuando.year, cuando.month)
            pesos = en_pesos(f, monto, ccl)
            por_mes[clave] = por_mes.get(clave, 0.0) + pesos
            if detalle is not None:  # para mostrar qué hay en cada mes
                detalle.setdefault(clave, []).append({
                    "tipo": "fijos", "nombre": f["nombre"], "monto": pesos, "fecha": fecha,
                    "moneda": f.get("moneda"), "monto_original": monto,
                    "tarjeta": f.get("tarjeta") if f.get("cierre") and f.get("venc") else None,
                    "vence": cuando if f.get("cierre") and f.get("venc") else None,
                })
    return por_mes


def proyeccion(fijos, proximos, hoy, prestamos=(), meses=6, registrados=None, ccl=None):
    """Por mes: gastos fijos por pagar + resúmenes de tarjeta pendientes (según su vencimiento)
    + cuotas de préstamos que debo. Aparte, lo que me tienen que pagar.
    Las cuotas de préstamo impagas de meses anteriores (vencidas) se suman al mes actual.
    fijos: dicts de gastos fijos. prestamos: (rol, vence, monto) impagas.
    Devuelve dicts: mes, fijos, tarjetas, debo, total (lo que sale), cobrar."""
    detalle_fijos = {}
    fijos_por_mes = compromisos_fijos(fijos, hoy, meses, registrados or {}, ccl, detalle_fijos)
    filas = []
    for k in range(meses):
        anio, mes = sumar_meses(hoy.year, hoy.month, k)
        subs = fijos_por_mes.get((anio, mes), 0.0)
        resumenes = [p for p in proximos if not p["pagado"] and (p["vence"].year, p["vence"].month) == (anio, mes)]
        tarjetas = sum(p["a_pagar"] for p in resumenes)
        items = sorted(detalle_fijos.get((anio, mes), []), key=lambda i: i["fecha"])
        items += [{"tipo": "tarjetas", "nombre": p["tarjeta"], "monto": p["a_pagar"], "fecha": p["vence"],
                   "usd": p.get("usd")} for p in resumenes]
        debo = cobrar = 0.0
        for prestamo in prestamos:
            rol, vence, monto = prestamo[:3]
            persona = prestamo[3] if len(prestamo) > 3 else ""
            del_mes = (vence.year, vence.month) == (anio, mes) or (k == 0 and vence < date(anio, mes, 1))
            if del_mes:
                if rol == "deudor":
                    debo += monto
                items.append({"tipo": "debo" if rol == "deudor" else "cobrar", "nombre": persona, "monto": monto,
                              "fecha": vence, "vencida": vence < hoy})
                if rol != "deudor":
                    cobrar += monto
        filas.append({"mes": f"{MESES[mes - 1]} {anio}", "fijos": subs, "tarjetas": tarjetas,
                      "debo": debo, "total": subs + tarjetas + debo, "cobrar": cobrar, "lista": items})
    return filas


def uso_limites(limites, proximos):
    """Uso del límite de cada tarjeta de crédito = lo que falta pagar (resúmenes pendientes que
    no están marcados como pagados). limites: lista de (tarjeta_id, etiqueta, limite)."""
    debe = {}
    for p in proximos:
        if not p["pagado"]:
            debe[p["tarjeta_id"]] = debe.get(p["tarjeta_id"], 0.0) + p["a_pagar"]
    filas = []
    for tid, etiqueta, limite in limites:
        usado = debe.get(tid, 0.0)
        porcentaje = usado / limite * 100
        nivel = "alto" if porcentaje >= 90 else "medio" if porcentaje >= 70 else "ok"
        filas.append({
            "tarjeta": etiqueta, "limite": limite, "usado": usado, "disponible": limite - usado,
            "porcentaje": porcentaje, "ancho": min(porcentaje, 100), "nivel": nivel,
        })
    return filas


def resumen_objetivo(items, fecha_meta, hoy, ccl=None):
    """Totales de un objetivo. items: dicts con estimado, real, cubierto, moneda y cotizacion.
    Lo cubierto vale el monto real si se cargó; lo que falta, el estimado.
    Los ítems en dólares se pasan a pesos: los cubiertos al CCL del día en que se cubrieron, los pendientes al CCL de hoy.
    Con fecha meta calcula cuánto ahorrar por mes (contando el mes actual), separado en pesos y en dólares."""
    def a_pesos(i, monto):
        if i.get("moneda") != "USD":
            return monto
        cot = (i.get("cotizacion") if i["cubierto"] else None) or ccl
        return monto * cot if cot else 0

    for i in items:
        i["pesos"] = a_pesos(i, i["real"] if i["cubierto"] and i["real"] is not None else i["estimado"])
    cubierto = sum(i["pesos"] for i in items if i["cubierto"])
    falta = sum(i["pesos"] for i in items if not i["cubierto"])
    falta_ars = sum(i["estimado"] for i in items if not i["cubierto"] and i.get("moneda") != "USD")
    falta_usd = sum(i["estimado"] for i in items if not i["cubierto"] and i.get("moneda") == "USD")
    total = cubierto + falta
    meses = ahorro = ahorro_ars = ahorro_usd = None
    vencida = False
    if fecha_meta and (falta_ars or falta_usd):
        meses = (fecha_meta.year * 12 + fecha_meta.month) - (hoy.year * 12 + hoy.month) + 1
        if fecha_meta < hoy or meses <= 0:
            vencida, meses = True, None
        else:
            ahorro, ahorro_ars, ahorro_usd = falta / meses, falta_ars / meses, falta_usd / meses
    return {
        "presupuesto": total, "cubierto": cubierto, "falta": falta, "falta_ars": falta_ars, "falta_usd": falta_usd,
        "avance": cubierto / total * 100 if total else 0, "meses": meses, "ahorro_mensual": ahorro,
        "ahorro_ars": ahorro_ars, "ahorro_usd": ahorro_usd, "vencida": vencida,
        "completo": bool(items) and not (falta_ars or falta_usd),
        "tiene_usd": any(i.get("moneda") == "USD" for i in items),
    }


GAJOS = 8


def gajos(total, presupuesto):
    """Medidor de la marca: el presupuesto del mes son 8 gajos y cada uno gastado se apaga.
    Devuelve dict con gastados, libres, lo que queda y lo que se pasó (si se pasó)."""
    if not presupuesto:
        return None
    gastados = min(GAJOS, round(total / presupuesto * GAJOS))
    queda = presupuesto - total
    return {"gastados": gastados, "libres": GAJOS - gastados, "presupuesto": presupuesto,
            "queda": max(queda, 0), "excedido": max(-queda, 0)}


def eventos_calendario(desde, hasta, hoy, fijos, resumenes, cuotas, gastos_por_dia, objetivos, pagos=(),
                       registrados=None, ccl=None):
    """Todo lo que pasa cada día entre `desde` y `hasta` (inclusive), para el calendario.
    fijos: dicts de gastos fijos (con montos, dia, frecuencia, mes_inicio, hasta).
    resumenes: dicts de resumenes_tarjetas (con 'corto', el nombre breve de la tarjeta).
    cuotas: (rol, persona, vence, monto, pagada). gastos_por_dia: {fecha: (cantidad, total)}.
    Devuelve {fecha: [evento, ...]}; cada evento es un dict con tipo, titulo, monto, estado y url."""
    dias = {}

    def sumar(fecha, **evento):
        if desde <= fecha <= hasta:
            evento.setdefault("monto", None)
            evento.setdefault("estado", "")
            dias.setdefault(fecha, []).append(evento)

    # Gastos fijos: un evento por cobro, con su estado (cobrado, falló, a confirmar)
    registrados = registrados or {}
    for f in fijos:
        for fecha, monto in cobros_fijo(f, desde, hasta):
            estado = {"cobrado": "cobrado", "fallido": "falló"}.get(registrados.get((f["id"], fecha.isoformat())), "")
            if not estado and fecha <= hoy:
                estado = "a confirmar" if fecha >= (f.get("desde") or hoy) else "cobrado"
            titulo = f["nombre"] + (f" · US$ {monto:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".").replace(",00", "")
                                    if f.get("moneda") == "USD" else "")
            sumar(fecha, tipo="fijo", titulo=titulo, monto=en_pesos(f, monto, ccl) or None, estado=estado, url="/fijos")
    for f in fijos:
        if f.get("hasta"):
            sumar(f["hasta"], tipo="fin", titulo=f"Termina {f['nombre']}", estado="sin cobro", url="/fijos")

    # Tarjetas: cierre y vencimiento de cada resumen
    for r in resumenes:
        sumar(r["cierra"], tipo="cierre", titulo=f"Cierra {r['corto']}", url="/tarjetas")
        sumar(r["vence"], tipo="resumen", titulo=f"Vence {r['corto']}", monto=r["a_pagar"],
              estado="pagado" if r["pagado"] else ("vencido" if r["vence"] < hoy else ""), url="/tarjetas")

    # Pagos de resúmenes, el día en que pagaste (pagos: (fecha, tarjeta, total en pesos reales))
    for fecha, tarjeta, total in pagos:
        sumar(fecha, tipo="pago", titulo=f"Pagaste {tarjeta}", monto=total, url="/tarjetas")

    # Préstamos: cuotas que pago y cuotas que cobro
    for rol, persona, vence, monto, pagada in cuotas:
        deudor = rol == "deudor"
        estado = ("pagada" if deudor else "cobrada") if pagada else ("vencida" if vence < hoy else "")
        sumar(vence, tipo="debo" if deudor else "cobro",
              titulo=f"Cuota a {persona}" if deudor else f"Te paga {persona}",
              monto=monto, estado=estado, url="/prestamos")

    # Lo que ya gastaste ese día
    for fecha, (cantidad, total) in gastos_por_dia.items():
        sumar(fecha, tipo="gasto", titulo=f"{cantidad} gasto{'s' if cantidad != 1 else ''}", monto=total,
              url=f"/gastos?dia={fecha.isoformat()}")

    # Fechas meta de objetivos
    for o in objetivos:
        if o["fecha_meta"] and not o["completo"]:
            sumar(o["fecha_meta"], tipo="meta", titulo=f"Meta: {o['nombre']}", monto=o["falta"],
                  estado="falta", url="/objetivos")

    orden = {"resumen": 0, "pago": 1, "debo": 2, "fijo": 3, "cobro": 4, "gasto": 5, "cierre": 6, "fin": 7, "meta": 8}
    for lista in dias.values():
        lista.sort(key=lambda e: (orden[e["tipo"]], e["titulo"]))
    return dias
