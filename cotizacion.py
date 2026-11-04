"""Dólar de referencia de Marquito: el CCL (contado con liquidación).

Se alimenta solo:
- CCL de hoy: dolarapi.com (como mucho una consulta por hora).
- CCL de días pasados: el histórico completo de api.argentinadatos.com (se baja una vez y se mantiene).
Las dos están en la lista de sitios permitidos del plan gratis de PythonAnywhere.

Si no hay dato de un día (fin de semana, feriado, API caída) se usa el último anterior conocido.
Una cotización cargada a mano tiene prioridad sobre la automática.
Las cotizaciones son de todos (no son datos personales): viven en cotizaciones.db.
"""
import json
import os
import sqlite3
import urllib.request
from datetime import date, datetime, timedelta

from db import BASE

DB_COTIZACIONES = os.path.join(BASE, "cotizaciones.db")
URL_HOY = "https://dolarapi.com/v1/dolares/contadoconliqui"
URL_HISTORICO = "https://api.argentinadatos.com/v1/cotizaciones/dolares/contadoconliqui"
CADA_CUANTO = timedelta(hours=1)  # reintentos a cada fuente
TIEMPO_MAXIMO = 4  # segundos de espera por consulta: si la API no responde, la página no se cuelga


def _con():
    con = sqlite3.connect(DB_COTIZACIONES)
    con.executescript(
        """CREATE TABLE IF NOT EXISTS ccl (
               fecha TEXT PRIMARY KEY,        -- AAAA-MM-DD
               valor REAL NOT NULL,           -- precio de venta
               fuente TEXT NOT NULL,          -- dolarapi, argentinadatos o manual
               actualizado TEXT NOT NULL
           );
           CREATE TABLE IF NOT EXISTS consultas (
               fuente TEXT PRIMARY KEY,
               cuando TEXT NOT NULL
           );"""
    )
    return con


def _bajar_json(url):
    pedido = urllib.request.Request(url, headers={"User-Agent": "Marquito/1.0 (app personal de gastos)"})
    with urllib.request.urlopen(pedido, timeout=TIEMPO_MAXIMO) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def _valor(dato):
    """Precio de venta (o de compra si no viene la venta) de un registro de las APIs."""
    for campo in ("venta", "compra"):
        try:
            valor = float(dato.get(campo))
            if valor > 0:
                return valor
        except (TypeError, ValueError):
            continue
    return None


def _fecha(dato, por_defecto):
    texto = str(dato.get("fecha") or dato.get("fechaActualizacion") or "")[:10]
    try:
        return date.fromisoformat(texto)
    except ValueError:
        return por_defecto


def _toca_consultar(con, fuente):
    fila = con.execute("SELECT cuando FROM consultas WHERE fuente = ?", (fuente,)).fetchone()
    return not fila or datetime.now() - datetime.fromisoformat(fila[0]) >= CADA_CUANTO


def _anotar_consulta(con, fuente):
    con.execute("INSERT OR REPLACE INTO consultas (fuente, cuando) VALUES (?, ?)",
                (fuente, datetime.now().isoformat(timespec="seconds")))


def _guardar(con, fecha, valor, fuente):
    """Guarda una cotización automática sin pisar una cargada a mano."""
    manual = con.execute("SELECT 1 FROM ccl WHERE fecha = ? AND fuente = 'manual'", (fecha.isoformat(),)).fetchone()
    if not manual:
        con.execute("INSERT OR REPLACE INTO ccl (fecha, valor, fuente, actualizado) VALUES (?, ?, ?, ?)",
                    (fecha.isoformat(), valor, fuente, datetime.now().isoformat(timespec="seconds")))


def actualizar(hoy=None, bajar=None):
    """Trae lo que falte de las APIs, respetando un intento por hora por fuente. Nunca lanza errores."""
    hoy = hoy or date.today()
    bajar = bajar or _bajar_json
    con = _con()
    try:
        tiene_hoy = con.execute("SELECT 1 FROM ccl WHERE fecha = ?", (hoy.isoformat(),)).fetchone()
        if _toca_consultar(con, "dolarapi") and not (tiene_hoy and con.execute(
                "SELECT 1 FROM ccl WHERE fecha = ? AND fuente = 'manual'", (hoy.isoformat(),)).fetchone()):
            _anotar_consulta(con, "dolarapi")
            con.commit()
            try:
                dato = bajar(URL_HOY)
                valor = _valor(dato)
                if valor:
                    _guardar(con, _fecha(dato, hoy), valor, "dolarapi")
            except Exception:
                pass  # sin conexión o formato inesperado: queda el último valor conocido
        # El histórico se baja si falta o si quedó viejo (más de 3 días sin datos)
        ultima = con.execute("SELECT MAX(fecha) FROM ccl WHERE fuente != 'manual'").fetchone()[0]
        viejo = not ultima or date.fromisoformat(ultima) < hoy - timedelta(days=3)
        cantidad = con.execute("SELECT COUNT(*) FROM ccl").fetchone()[0]
        if (viejo or cantidad < 30) and _toca_consultar(con, "argentinadatos"):
            _anotar_consulta(con, "argentinadatos")
            con.commit()
            try:
                for dato in bajar(URL_HISTORICO):
                    valor, fecha = _valor(dato), _fecha(dato, None)
                    if valor and fecha:
                        _guardar(con, fecha, valor, "argentinadatos")
            except Exception:
                pass
        con.commit()
    finally:
        con.close()


def ccl_de(fecha):
    """Cotización para una fecha: la de ese día o, si no hay, la última anterior conocida.
    Devuelve dict con valor, fecha (del dato) y fuente, o None si todavía no hay ninguna."""
    con = _con()
    fila = con.execute("SELECT valor, fecha, fuente, actualizado FROM ccl WHERE fecha <= ? ORDER BY fecha DESC LIMIT 1",
                       (fecha.isoformat(),)).fetchone()
    if not fila:  # fecha anterior a todo el histórico: la más vieja que haya
        fila = con.execute("SELECT valor, fecha, fuente, actualizado FROM ccl ORDER BY fecha LIMIT 1").fetchone()
    con.close()
    if not fila:
        return None
    return {"valor": fila[0], "fecha": date.fromisoformat(fila[1]), "fuente": fila[2], "actualizado": fila[3]}


def cargar_manual(fecha, valor):
    con = _con()
    con.execute("INSERT OR REPLACE INTO ccl (fecha, valor, fuente, actualizado) VALUES (?, ?, 'manual', ?)",
                (fecha.isoformat(), valor, datetime.now().isoformat(timespec="seconds")))
    con.commit()
    con.close()


def borrar_manual(fecha):
    """Vuelve a la cotización automática de ese día."""
    con = _con()
    con.execute("DELETE FROM ccl WHERE fecha = ? AND fuente = 'manual'", (fecha.isoformat(),))
    con.execute("DELETE FROM consultas")  # que vuelva a consultar las APIs
    con.commit()
    con.close()
