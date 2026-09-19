"""Las tres dependencias que FastAPI inyecta, y la única costura de pruebas.

Todo lo que Continental no controla entra por aquí, y por eso una prueba solo
necesita `app.dependency_overrides[obtener_almacen] = lambda: doble`. La
alternativa —la de Marlowe— es parchear módulos con `monkeypatch` porque la
conexión nace al importar, y cuesta un fixture de ~100 líneas.

**Las tres funciones son perezosas.** Se ejecutan cuando llega una petición, no
cuando alguien importa este archivo: sin eso, `import continental.web.app`
exigiría `.env`, un Postgres vivo y un Doyle despierto solo para recolectar
pruebas.
"""

from __future__ import annotations

from continental.almacen import AlmacenPostgres, LecturaDelAlmacen, motor
from continental.almacenamiento import AlmacenamientoDelPedido, AlmacenamientoPostgres
from continental.config import cargar
from continental.doyle import ClienteDeDoyle, DoylePorHttp


def obtener_almacen() -> LecturaDelAlmacen:
    """El borde de lectura del almacén. Se sustituye en pruebas.

    Pasa `motor` sin paréntesis: la factoría, no el motor. Una dependencia que
    truena lo hace **antes** de entrar a la ruta, donde el `try` del manejador
    ya no la alcanza, y una base caída se vería como un 500 genérico en vez de
    un hueco con su motivo. Así esta función no puede fallar y la falla aparece
    donde alguien la puede contar.
    """
    return AlmacenPostgres(motor)


def obtener_doyle() -> ClienteDeDoyle:
    """El borde hacia Doyle. Se sustituye en pruebas.

    El `timeout_seg` del YAML cubre estas llamadas cortas —pedir una búsqueda,
    consultar su estado, listar sesiones—, nunca la espera del resultado: eso
    tarda ~9 s por proveedor y se consulta después con el `job_id`.
    """
    ajustes = cargar()
    doyle = ajustes.modulos.get("doyle")
    if doyle is None:
        # Aquí sí se truena, y la diferencia con el almacén es deliberada. Un
        # Doyle apagado es operación: falla dentro de `sesiones()` y se ve como
        # un hueco con su motivo. Un `config/continental.yml` sin la entrada
        # `doyle` es un despliegue roto —el archivo está versionado y siempre la
        # trae—, y eso tiene que doler: sale como el 500 genérico del manejador,
        # con el detalle en la bitácora.
        #
        # `RuntimeError` y no `SystemExit`, igual que en `almacen.motor()`: los
        # dos manejadores de errores filtran por `Exception`, así que un
        # `SystemExit` dentro de una petición se les escapa y se lleva al
        # servidor por delante.
        raise RuntimeError(
            "Falta el módulo `doyle` en config/continental.yml. Sin él no hay "
            "precios de proveedor, y adivinar el puerto sería justo la falla "
            "silenciosa que este repo prohíbe."
        )
    return DoylePorHttp(url=doyle.url, timeout_seg=doyle.timeout_seg)


def obtener_almacenamiento() -> AlmacenamientoDelPedido:
    """El borde de escritura del pedido. Se sustituye en pruebas.

    Es una dependencia **aparte** de `obtener_almacen` aunque las dos acaben en
    el mismo Postgres, y esa separación es el punto: leer `marts` y escribir
    `pedidos` son dos permisos distintos que pueden fallar por separado —cada
    `dbt build` recrea `marts` y se lleva sus GRANT por delante, y a
    farmacia-data le pasó el 2026-09-07 a las 20:30—. Con una sola dependencia,
    una prueba no podría tumbar uno sin tumbar el otro y la pantalla no podría
    distinguirlos.

    Pasa `motor` sin paréntesis, igual que el almacén: la factoría, no el
    motor. Así esta función no puede fallar y la falla aparece dentro de la
    escritura, donde el `try` de la ruta la convierte en un hueco con su motivo
    en vez de un 500 genérico.
    """
    return AlmacenamientoPostgres(motor)
