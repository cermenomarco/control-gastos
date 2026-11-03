"""Base de datos SQLite (un solo archivo: gastos.db).

conectar() abre la base y se asegura de que existan todas las tablas y columnas,
así una base creada con versiones anteriores se actualiza sola.
"""
import os
import sqlite3

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
]

# Columnas que se fueron agregando a las tablas después de crearlas
COLUMNAS = {
    "gastos": [
        "medio TEXT", "tarjeta_id INTEGER", "banco_id INTEGER",
        "cuotas INTEGER DEFAULT 1", "con_interes INTEGER DEFAULT 0", "total_con_interes REAL",
    ],
    "tarjetas": ["modalidad TEXT DEFAULT 'credito'", "dia_cierre INTEGER", "dia_vencimiento INTEGER"],
}


def conectar():
    con = sqlite3.connect(DB)
    for sql in TABLAS:
        con.execute(sql)
    for tabla, columnas in COLUMNAS.items():
        existentes = {fila[1] for fila in con.execute(f"PRAGMA table_info({tabla})")}
        for columna in columnas:
            if columna.split()[0] not in existentes:
                con.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna}")
    con.commit()
    return con
