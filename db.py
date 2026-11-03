"""Base de datos SQLite (un solo archivo: gastos.db).

conectar() abre la base y se asegura de que existan todas las tablas y columnas,
así una base creada con versiones anteriores se actualiza sola.
"""
import os
import sqlite3
from datetime import date

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gastos.db")

TABLAS = [
    """CREATE TABLE IF NOT EXISTS gastos (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           fecha TEXT NOT NULL,
           monto REAL NOT NULL,
           categoria TEXT NOT NULL,
           descripcion TEXT
       )""",
    """CREATE TABLE IF NOT EXISTS bancos (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           nombre TEXT NOT NULL UNIQUE
       )""",
    """CREATE TABLE IF NOT EXISTS tarjetas (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           tipo TEXT NOT NULL,
           ultimos4 TEXT NOT NULL,
           banco_id INTEGER
       )""",
    """CREATE TABLE IF NOT EXISTS suscripciones (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           nombre TEXT NOT NULL,
           monto REAL NOT NULL,
           dia_cobro INTEGER NOT NULL,
           tarjeta_id INTEGER
       )""",
    """CREATE TABLE IF NOT EXISTS resumenes_pagados (
           tarjeta_id INTEGER NOT NULL,
           periodo TEXT NOT NULL,
           PRIMARY KEY (tarjeta_id, periodo)
       )""",
    """CREATE TABLE IF NOT EXISTS fijos (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           nombre TEXT NOT NULL,
           tipo TEXT NOT NULL,
           dia_cobro INTEGER NOT NULL,
           frecuencia INTEGER NOT NULL DEFAULT 1,
           mes_inicio TEXT NOT NULL,
           tarjeta_id INTEGER
       )""",
    # Historial de montos: cada fila rige desde ese mes (AAAA-MM) hasta el próximo cambio
    """CREATE TABLE IF NOT EXISTS fijos_montos (
           fijo_id INTEGER NOT NULL,
           desde TEXT NOT NULL,
           monto REAL NOT NULL,
           PRIMARY KEY (fijo_id, desde)
       )""",
    """CREATE TABLE IF NOT EXISTS prestamos (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           persona TEXT NOT NULL,
           rol TEXT NOT NULL,            -- 'acreedor' (yo presté) o 'deudor' (yo debo)
           monto REAL NOT NULL,          -- lo prestado
           total REAL NOT NULL,          -- lo que se devuelve (con intereses, si hay)
           fecha TEXT NOT NULL,
           cuotas INTEGER NOT NULL DEFAULT 1,
           descripcion TEXT
       )""",
    """CREATE TABLE IF NOT EXISTS prestamo_cuotas (
           prestamo_id INTEGER NOT NULL,
           numero INTEGER NOT NULL,
           vence TEXT NOT NULL,
           monto REAL NOT NULL,
           pagada INTEGER NOT NULL DEFAULT 0,
           PRIMARY KEY (prestamo_id, numero)
       )""",
    """CREATE TABLE IF NOT EXISTS objetivos (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           nombre TEXT NOT NULL,
           fecha_meta TEXT
       )""",
    """CREATE TABLE IF NOT EXISTS objetivo_items (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           objetivo_id INTEGER NOT NULL,
           nombre TEXT NOT NULL,
           estimado REAL NOT NULL,
           real REAL,                     -- lo que costó de verdad, si fue distinto
           cubierto INTEGER NOT NULL DEFAULT 0
       )""",
]

# Columnas que se fueron agregando a las tablas después de crearlas
COLUMNAS = {
    "gastos": [
        "medio TEXT", "tarjeta_id INTEGER", "banco_id INTEGER",
        "cuotas INTEGER DEFAULT 1", "con_interes INTEGER DEFAULT 0", "total_con_interes REAL",
    ],
    "tarjetas": ["modalidad TEXT DEFAULT 'credito'", "dia_cierre INTEGER", "dia_vencimiento INTEGER", "limite REAL"],
}


def conectar():
    con = sqlite3.connect(DB)
    habia_fijos = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'fijos'"
    ).fetchone()
    for sql in TABLAS:
        con.execute(sql)
    for tabla, columnas in COLUMNAS.items():
        existentes = {fila[1] for fila in con.execute(f"PRAGMA table_info({tabla})")}
        for columna in columnas:
            if columna.split()[0] not in existentes:
                con.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna}")
    if not habia_fijos:
        migrar_suscripciones(con)
    con.commit()
    return con


def migrar_suscripciones(con):
    """Una sola vez: pasa las suscripciones de versiones anteriores a gastos fijos (tipo suscripción, mensual)."""
    mes = date.today().strftime("%Y-%m")
    for nombre, monto, dia, tarjeta_id in con.execute(
        "SELECT nombre, monto, dia_cobro, tarjeta_id FROM suscripciones ORDER BY id"
    ).fetchall():
        cur = con.execute(
            """INSERT INTO fijos (nombre, tipo, dia_cobro, frecuencia, mes_inicio, tarjeta_id)
               VALUES (?, 'suscripcion', ?, 1, ?, ?)""",
            (nombre, dia, mes, tarjeta_id),
        )
        con.execute("INSERT INTO fijos_montos (fijo_id, desde, monto) VALUES (?, ?, ?)",
                    (cur.lastrowid, mes, monto))
