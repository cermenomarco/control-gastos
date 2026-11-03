# Marquito

Tus gastos, en gajos. App web personal para llevar el control de gastos (Flask + SQLite).
La identidad visual sigue el brandbook de Marquito v1.0.

## Correrla en tu computadora

    pip install -r requirements.txt
    python app.py

Abre http://localhost:5000 (contraseña local: `gastos`).

## Secciones

- **Inicio**: lo gastado en el mes, el medidor de gajos (con tu presupuesto mensual), agregar gasto, categorías y últimos gastos.
- **Gastos**: lista completa con filtros por mes, día, tarjeta y banco.
- **Tarjetas**: límite usado, próximos resúmenes (con "pagado") y alta de tarjetas y bancos.
- **Gastos fijos**: suscripciones, servicios, impuestos y alquiler, con frecuencia e historial de montos.
- **Préstamos**: lo que debo y lo que me deben, en cuotas, con o sin interés.
- **Objetivos**: presupuestos (ej. un viaje) con ítems que se tachan y ahorro mensual sugerido.
- **Proyección**: gráfico de los próximos 6 meses con fijos, tarjetas y préstamos.

## Estructura

- `app.py`: rutas de la web (qué hace cada pestaña y cada formulario).
- `db.py`: base de datos SQLite (`gastos.db`); crea y actualiza las tablas solas.
- `logica.py`: constantes y cálculos (cuotas por resumen, proyección mensual).
- `templates/`: las páginas HTML. `base.html` es el marco común (colores, tipografías, menú); `_iconos.html` tiene los íconos.
- `static/`: logos, favicon e íconos para agregar la app a la pantalla de inicio del celular.

## En el servidor (PythonAnywhere)

La contraseña y la clave secreta se definen en el archivo WSGI como
`APP_PASSWORD` y `SECRET_KEY`. Para actualizar: `git pull` en la consola y *Reload*.
