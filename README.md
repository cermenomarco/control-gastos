# Control de gastos

App web personal para llevar el control de gastos (Flask + SQLite).

## Correrla en tu computadora

    pip install -r requirements.txt
    python app.py

Abre http://localhost:5000 (contraseña local: `gastos`).

## Estructura

- `app.py`: rutas de la web (qué hace cada pestaña y cada formulario).
- `db.py`: base de datos SQLite (`gastos.db`); crea y actualiza las tablas solas.
- `logica.py`: constantes y cálculos (cuotas por resumen, proyección mensual).
- `templates/`: las páginas HTML. `base.html` es el marco común (menú y estilos).

## En el servidor (PythonAnywhere)

La contraseña y la clave secreta se definen en el archivo WSGI como
`APP_PASSWORD` y `SECRET_KEY`. Para actualizar: `git pull` en la consola y *Reload*.
