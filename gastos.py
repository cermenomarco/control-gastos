"""Control de gastos - Versión 1 (consola + SQLite)

Uso:  python gastos.py
Los datos se guardan en el archivo gastos.db (se crea solo).
"""
import sqlite3
from datetime import date

DB = "gastos.db"


def conectar():
    con = sqlite3.connect(DB)
    con.execute(
        """CREATE TABLE IF NOT EXISTS gastos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            monto REAL NOT NULL,
            categoria TEXT NOT NULL,
            descripcion TEXT
        )"""
    )
    return con


def pedir_monto():
    while True:
        texto = input("Monto: ").strip().replace(",", ".")
        try:
            monto = float(texto)
            if monto > 0:
                return monto
        except ValueError:
            pass
        print("  Ingresa un número mayor a 0 (ej: 1500 o 1500.50)")


def pedir_fecha():
    hoy = date.today().isoformat()
    while True:
        texto = input(f"Fecha AAAA-MM-DD [Enter = {hoy}]: ").strip() or hoy
        try:
            date.fromisoformat(texto)
            return texto
        except ValueError:
            print("  Formato inválido. Ejemplo: 2026-10-15")


def agregar(con):
    monto = pedir_monto()
    categoria = input("Categoría (comida, transporte, ocio...): ").strip().lower() or "otros"
    descripcion = input("Descripción (opcional): ").strip()
    fecha = pedir_fecha()
    con.execute(
        "INSERT INTO gastos (fecha, monto, categoria, descripcion) VALUES (?, ?, ?, ?)",
        (fecha, monto, categoria, descripcion),
    )
    con.commit()
    print("✔ Gasto guardado.")


def listar(con):
    filas = con.execute(
        "SELECT id, fecha, monto, categoria, descripcion FROM gastos ORDER BY fecha DESC, id DESC"
    ).fetchall()
    if not filas:
        print("Todavía no hay gastos cargados.")
        return
    print(f"\n{'ID':<4} {'Fecha':<11} {'Monto':>10}  {'Categoría':<12} Descripción")
    print("-" * 60)
    for id_, fecha, monto, cat, desc in filas:
        print(f"{id_:<4} {fecha:<11} {monto:>10.2f}  {cat:<12} {desc or ''}")


def resumen(con):
    mes = date.today().strftime("%Y-%m")
    total = con.execute(
        "SELECT COALESCE(SUM(monto), 0) FROM gastos WHERE fecha LIKE ?", (mes + "%",)
    ).fetchone()[0]
    print(f"\nTotal gastado en {mes}: {total:.2f}")
    por_cat = con.execute(
        """SELECT categoria, SUM(monto) FROM gastos
           WHERE fecha LIKE ? GROUP BY categoria ORDER BY SUM(monto) DESC""",
        (mes + "%",),
    ).fetchall()
    for cat, suma in por_cat:
        porcentaje = suma / total * 100 if total else 0
        print(f"  {cat:<12} {suma:>10.2f}  ({porcentaje:.0f}%)")


def eliminar(con):
    listar(con)
    try:
        id_ = int(input("\nID a eliminar (0 para cancelar): "))
    except ValueError:
        print("ID inválido.")
        return
    if id_ == 0:
        return
    cur = con.execute("DELETE FROM gastos WHERE id = ?", (id_,))
    con.commit()
    print("✔ Eliminado." if cur.rowcount else "No existe ese ID.")


def menu():
    con = conectar()
    acciones = {"1": agregar, "2": listar, "3": resumen, "4": eliminar}
    while True:
        print(
            "\n=== CONTROL DE GASTOS ===\n"
            "1) Agregar gasto\n2) Ver todos\n3) Resumen del mes\n4) Eliminar\n0) Salir"
        )
        opcion = input("Opción: ").strip()
        if opcion == "0":
            print("¡Hasta luego!")
            break
        accion = acciones.get(opcion)
        if accion:
            accion(con)
        else:
            print("Opción no válida.")
    con.close()


if __name__ == "__main__":
    menu()
