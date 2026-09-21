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

import datetime as dt

from continental.almacen import AlmacenPostgres, LecturaDelAlmacen, motor
from continental.almacenamiento import AlmacenamientoDelPedido, AlmacenamientoPostgres
from continental.config import cargar
from continental.consultas import RegistroDeConsultas
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


#: Las consultas de precio en vuelo, **para todo el proceso**.
#:
#: Es lo único de este archivo que no nace por petición, y la diferencia es el
#: punto: los otros tres bordes no recuerdan nada entre llamadas y éste existe
#: justamente para recordar —que ya se le está preguntando a Doyle por este
#: renglón, y que la consulta anterior terminó mal—. Uno por petición no
#: recordaría nada y el segundo clic volvería a molestar a los cuatro portales.
#:
#: Se construye al importar, y eso no rompe la regla de "nada se conecta al
#: importarse": esto no abre una conexión ni un cliente. Es un diccionario con
#: un candado.
_CONSULTAS = RegistroDeConsultas()


def obtener_consultas() -> RegistroDeConsultas:
    """El registro de consultas de precio. Se sustituye en pruebas.

    En el suite se sustituye por uno cuyo `lanzar` ejecuta la tarea ahí mismo:
    ninguna prueba arranca un hilo, así que no hay nada que sincronizar ni que
    esperar, y una prueba que falle no deja un hilo vivo contaminando a la
    siguiente. Que la espera no duerma de verdad lo resuelven aparte el `dormir`
    y el `ahora` de `consultas.consultar_a_doyle`.
    """
    return _CONSULTAS


def reloj() -> dt.datetime:
    """El instante de ahora, con zona. **El reloj también es un borde.**

    Vive aquí y no en `app.py` a propósito: `app.py` tiene prohibido mirar el
    reloj (`test_sugerido.test_el_calculo_no_menciona_el_reloj_en_ninguna_parte`),
    porque ahí se deciden las **fechas de venta** y ésas salen de `max(fecha)`
    del almacén, nunca de aquí.

    Lo que sí necesita un reloj es decir **hace cuánto pasó algo** — "pedido el
    martes, sin recibir" (ticket 24): compara el instante en que alguien apretó
    "Enviar" contra éste, y los dos son del reloj. `app._ahora` lo envuelve para
    que una prueba lo fije.
    """
    return dt.datetime.now(dt.UTC)
