"""Cuentas de usuario de Marquito.

- Las cuentas se guardan en usuarios.db; las contraseñas, solo cifradas (hash), nunca en texto.
- El administrador crea las cuentas con una contraseña temporal; al entrar, cada uno la cambia.
- 5 intentos fallidos bloquean la cuenta 10 minutos.
- Cada usuario tiene su propio archivo de datos (ver db.py).
"""
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

from db import BASE

USUARIOS_DB = os.path.join(BASE, "usuarios.db")
CARPETA_DATOS = os.path.join(BASE, "datos")
MAX_INTENTOS = 5
BLOQUEO = timedelta(minutes=10)
MIN_CLAVE = 8
PATRON_USUARIO = re.compile(r"^[a-z0-9._-]{3,30}$")
_HASH_FALSO = generate_password_hash("para-igualar-tiempos")


def _con():
    con = sqlite3.connect(USUARIOS_DB)
    con.row_factory = sqlite3.Row
    con.execute(
        """CREATE TABLE IF NOT EXISTS usuarios (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               usuario TEXT NOT NULL UNIQUE COLLATE NOCASE,
               nombre TEXT NOT NULL,
               hash TEXT NOT NULL,
               es_admin INTEGER NOT NULL DEFAULT 0,
               archivo TEXT NOT NULL DEFAULT '',
               debe_cambiar INTEGER NOT NULL DEFAULT 1,
               intentos INTEGER NOT NULL DEFAULT 0,
               bloqueado_hasta TEXT,
               sesion_ver INTEGER NOT NULL DEFAULT 1,
               creado TEXT NOT NULL,
               ultimo_acceso TEXT
           )"""
    )
    return con


def _ahora():
    return datetime.now().replace(microsecond=0)


def hay_usuarios():
    con = _con()
    hay = con.execute("SELECT 1 FROM usuarios LIMIT 1").fetchone() is not None
    con.close()
    return hay


def por_id(uid):
    if not uid:
        return None
    con = _con()
    fila = con.execute("SELECT * FROM usuarios WHERE id = ?", (uid,)).fetchone()
    con.close()
    return dict(fila) if fila else None


def todos():
    con = _con()
    filas = [dict(f) for f in con.execute("SELECT * FROM usuarios ORDER BY es_admin DESC, nombre COLLATE NOCASE")]
    con.close()
    return filas


def ruta_datos(usuario):
    """Ruta del archivo de datos del usuario (siempre armada por la app, nunca con texto del usuario)."""
    return os.path.join(BASE, usuario["archivo"])


def generar_clave():
    """Contraseña temporal fácil de dictar: tres grupos de 4 (sin 0/O ni 1/l)."""
    letras = "abcdefghijkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(letras) for _ in range(4)) for _ in range(3))


def validar_usuario(usuario):
    if not PATRON_USUARIO.match(usuario):
        return "El usuario va en minúsculas, de 3 a 30 caracteres: letras, números, punto, guion o guion bajo."
    return None


def validar_clave(clave, repetida):
    if len(clave) < MIN_CLAVE:
        return f"La contraseña tiene que tener al menos {MIN_CLAVE} caracteres."
    if clave != repetida:
        return "Las dos contraseñas no coinciden."
    return None


def crear(nombre, usuario, clave, es_admin=False, debe_cambiar=True, archivo=None):
    """Crea la cuenta. Devuelve (dict usuario, None) o (None, mensaje de error)."""
    nombre, usuario = nombre.strip(), usuario.strip().lower()
    if not nombre:
        return None, "Poné un nombre."
    error = validar_usuario(usuario)
    if error:
        return None, error
    con = _con()
    if con.execute("SELECT 1 FROM usuarios WHERE usuario = ?", (usuario,)).fetchone():
        con.close()
        return None, f"Ya existe el usuario «{usuario}»."
    cur = con.execute(
        """INSERT INTO usuarios (usuario, nombre, hash, es_admin, debe_cambiar, creado)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (usuario, nombre, generate_password_hash(clave), int(es_admin), int(debe_cambiar), _ahora().isoformat()),
    )
    uid = cur.lastrowid
    # El archivo de datos lo decide la app: el del administrador inicial es el gastos.db de siempre.
    con.execute("UPDATE usuarios SET archivo = ? WHERE id = ?", (archivo or os.path.join("datos", f"u{uid}.db"), uid))
    con.commit()
    con.close()
    return por_id(uid), None


def verificar(usuario, clave):
    """Login. Devuelve (dict usuario, None) o (None, mensaje). Aplica el bloqueo por intentos."""
    con = _con()
    fila = con.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario.strip().lower(),)).fetchone()
    if not fila:
        check_password_hash(_HASH_FALSO, clave)  # mismo tiempo de respuesta exista o no el usuario
        con.close()
        return None, "Usuario o contraseña incorrectos."
    ahora = _ahora()
    if fila["bloqueado_hasta"] and datetime.fromisoformat(fila["bloqueado_hasta"]) > ahora:
        minutos = max(1, round((datetime.fromisoformat(fila["bloqueado_hasta"]) - ahora).total_seconds() / 60))
        con.close()
        return None, f"Demasiados intentos. Probá de nuevo en {minutos} minuto{'s' if minutos > 1 else ''}."
    if not check_password_hash(fila["hash"], clave):
        intentos = fila["intentos"] + 1
        if intentos >= MAX_INTENTOS:
            con.execute("UPDATE usuarios SET intentos = 0, bloqueado_hasta = ? WHERE id = ?",
                        ((ahora + BLOQUEO).isoformat(), fila["id"]))
            mensaje = "Demasiados intentos. La cuenta queda bloqueada 10 minutos."
        else:
            con.execute("UPDATE usuarios SET intentos = ? WHERE id = ?", (intentos, fila["id"]))
            mensaje = "Usuario o contraseña incorrectos."
        con.commit()
        con.close()
        return None, mensaje
    con.execute("UPDATE usuarios SET intentos = 0, bloqueado_hasta = NULL, ultimo_acceso = ? WHERE id = ?",
                (ahora.isoformat(), fila["id"]))
    con.commit()
    con.close()
    return por_id(fila["id"]), None


def registrar_acceso(uid):
    con = _con()
    con.execute("UPDATE usuarios SET ultimo_acceso = ? WHERE id = ?", (_ahora().isoformat(), uid))
    con.commit()
    con.close()


def cambiar_clave(uid, actual, nueva, repetida):
    """El propio usuario cambia su contraseña. Cierra las sesiones en otros dispositivos."""
    usuario = por_id(uid)
    if not usuario or not check_password_hash(usuario["hash"], actual):
        return "La contraseña actual no es correcta."
    error = validar_clave(nueva, repetida)
    if error:
        return error
    if nueva == actual:
        return "La nueva contraseña tiene que ser distinta de la actual."
    con = _con()
    con.execute("UPDATE usuarios SET hash = ?, debe_cambiar = 0, sesion_ver = sesion_ver + 1 WHERE id = ?",
                (generate_password_hash(nueva), uid))
    con.commit()
    con.close()
    return None


def restablecer(uid):
    """El administrador genera una contraseña temporal nueva (cierra todas las sesiones de esa cuenta)."""
    clave = generar_clave()
    con = _con()
    con.execute(
        """UPDATE usuarios SET hash = ?, debe_cambiar = 1, intentos = 0, bloqueado_hasta = NULL,
                  sesion_ver = sesion_ver + 1 WHERE id = ?""",
        (generate_password_hash(clave), uid),
    )
    con.commit()
    con.close()
    return clave


def borrar(uid):
    """Borra la cuenta. Sus datos no se pierden: el archivo se mueve a datos/borrados/ como respaldo."""
    usuario = por_id(uid)
    if not usuario:
        return
    ruta = ruta_datos(usuario)
    if os.path.exists(ruta) and os.path.abspath(ruta) != os.path.abspath(os.path.join(BASE, "gastos.db")):
        destino = os.path.join(CARPETA_DATOS, "borrados")
        os.makedirs(destino, exist_ok=True)
        os.replace(ruta, os.path.join(destino, f"u{uid}-{usuario['usuario']}-{_ahora():%Y%m%d%H%M%S}.db"))
    con = _con()
    con.execute("DELETE FROM usuarios WHERE id = ?", (uid,))
    con.commit()
    con.close()
