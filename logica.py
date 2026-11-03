"""Constantes y cálculos de la app, sin Flask ni base de datos:
reparto de cuotas por resumen de tarjeta, proyección mensual, etiquetas."""
from calendar import monthrange
from datetime import date

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
