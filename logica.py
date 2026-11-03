"""Constantes y cálculos de la app, sin Flask ni base de datos:
reparto de cuotas por resumen de tarjeta, proyección mensual, etiquetas."""
from calendar import monthrange
from datetime import date

CATEGORIAS = ["comida", "transporte", "ocio", "hogar", "salud", "otros"]
TIPOS_TARJETA = ["Visa", "Mastercard", "American Express"]
MEDIOS = {"tarjeta": "Tarjeta", "transferencia": "Transferencia", "efectivo": "Efectivo"}
MODALIDADES = {"credito": "Crédito", "debito": "Débito"}
TIPOS_FIJO = {"suscripcion": "Suscripción", "servicio": "Servicio", "impuesto": "Impuesto",
              "alquiler": "Alquiler", "otro": "Otro"}
ROLES = {"acreedor": "Me deben", "deudor": "Debo"}
FRECUENCIAS = {1: "Mensual", 2: "Bimestral", 3: "Trimestral", 6: "Semestral", 12: "Anual"}
ERRORES = {
    "datos": "Revisa el monto (número mayor a 0), la fecha y el medio de pago.",
    "tarjeta": "Revisa la tarjeta: tipo, 4 dígitos y, si es de crédito, día de cierre y de vencimiento (1 a 31).",
    "cuotas": "Las cuotas deben ser un número entre 1 y 60.",
    "fijo": "Revisa el gasto fijo: nombre, monto mayor a 0, día de cobro (1 a 31), frecuencia y mes del primer cobro.",
    "prestamo": "Revisa el préstamo: persona, monto mayor a 0, fechas, cuotas (1 a 120) y, si hay interés, un total a devolver mayor al monto.",
    "monto_fijo": "Revisa el nuevo monto (mayor a 0) y el mes desde el que rige.",
    "interes": "Si hay interés, indica el total a pagar (mayor al monto).",
    "banco": "El nombre del banco está vacío o ya existe.",
    "usado": "No se puede eliminar: tiene gastos o tarjetas asociados.",
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


def resumenes_tarjetas(compras, nombres, pagados, hoy):
    """Reparte las cuotas de cada compra en el resumen (cierre) que le toca.
    Una compra hasta el día de cierre entra a ese resumen; después, al siguiente.
    El vencimiento es la primera fecha con el día de vencimiento posterior al cierre.
    pagados: conjunto de (tarjeta_id, "AAAA-MM del cierre") ya marcados como pagados.
    Devuelve, ordenados por vencimiento, los resúmenes que aún no vencieron (lista de dicts)."""
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
            periodo = f"{a:04d}-{m:02d}"
            filas.append({
                "tarjeta_id": tid, "tarjeta": nombres.get(tid, "—"), "periodo": periodo,
                "cierra": cierra, "vence": vence, "a_pagar": pagar, "intereses": intereses,
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
    """True si el gasto fijo se cobra ese mes, según su primer mes de cobro y su frecuencia."""
    ia, im = map(int, fijo["mes_inicio"].split("-"))
    meses = (anio * 12 + mes) - (ia * 12 + im)
    return meses >= 0 and meses % fijo["frecuencia"] == 0


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


def proyeccion(fijos, proximos, hoy, prestamos=(), meses=6):
    """Por mes: gastos fijos (según frecuencia, día de cobro y monto vigente) + resúmenes de tarjeta
    pendientes (según su vencimiento) + cuotas de préstamos que debo. Aparte, lo que me tienen que pagar.
    En el mes actual los fijos solo cuentan si falta cobrarlos; las cuotas de préstamo impagas
    de meses anteriores (vencidas) se suman al mes actual.
    fijos: dicts con dia, frecuencia, mes_inicio y montos. prestamos: (rol, vence, monto) impagas.
    Devuelve dicts: mes, fijos, tarjetas, debo, total (lo que sale), cobrar."""
    filas = []
    for k in range(meses):
        anio, mes = sumar_meses(hoy.year, hoy.month, k)
        subs = sum(
            monto_vigente(f["montos"], periodo_de(anio, mes)) or 0
            for f in fijos
            if cobra_en(f, anio, mes) and (k > 0 or f["dia"] >= hoy.day)
        )
        tarjetas = sum(p["a_pagar"] for p in proximos
                       if not p["pagado"] and (p["vence"].year, p["vence"].month) == (anio, mes))
        debo = cobrar = 0.0
        for rol, vence, monto in prestamos:
            del_mes = (vence.year, vence.month) == (anio, mes) or (k == 0 and vence < date(anio, mes, 1))
            if del_mes:
                if rol == "deudor":
                    debo += monto
                else:
                    cobrar += monto
        filas.append({"mes": f"{MESES[mes - 1]} {anio}", "fijos": subs, "tarjetas": tarjetas,
                      "debo": debo, "total": subs + tarjetas + debo, "cobrar": cobrar})
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
