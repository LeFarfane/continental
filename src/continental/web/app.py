"""El backend de Continental.

Dice si está vivo, quién está entrando, si los módulos contestan, y arma el
pedido sugerido del día. Todavía no guarda nada y no trae precios: eso son los
tickets 08 y 12 en adelante.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from continental import __version__
from continental.almacen import LecturaDelAlmacen
from continental.clasificacion import reglas_configuradas
from continental.config import cargar
from continental.doyle import ClienteDeDoyle
from continental.sugerido import DIAS_DE_RITMO, calcular_pedido_sugerido
from continental.vistas import VISTAS
from continental.web.dependencias import obtener_almacen, obtener_doyle

ESTATICOS = Path(__file__).parent / "static"

log = logging.getLogger("continental")

app = FastAPI(title="Continental", version=__version__, docs_url="/docs")


def quien(request: Request) -> str:
    """Quién está entrando, según el encabezado que Cloudflare Access ya validó.

    Es una FIRMA, no un permiso (regla 3 de CLAUDE.md). Si alguien alcanza este
    puerto sin pasar por el túnel, puede escribir el encabezado que quiera: la
    autorización la hace Access, no esto. Sirve para saber quién armó un pedido,
    no para decidir si puede armarlo.
    """
    return request.headers.get("Cf-Access-Authenticated-User-Email") or "sin-identificar"


@app.exception_handler(Exception)
async def error_generico(request: Request, exc: Exception):
    """El detalle va a la consola del servidor; al navegador, un mensaje corto.

    Esto corre detrás de un túnel: un `str(exc)` de SQLAlchemy lleva la cadena
    de conexión con contraseña. Doyle puede darse el lujo de devolver el texto
    del error porque solo escucha en 127.0.0.1; aquí no.
    """
    log.exception("Error atendiendo %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "Algo falló del lado del servidor. Revisa la bitácora."},
    )


@app.get("/api/salud")
async def salud(request: Request):
    """Vivo o no, y contra qué negocio está trabajando. No toca la base."""
    ajustes = cargar()
    return {
        "ok": True,
        "version": __version__,
        "negocio": ajustes.negocio,
        "quien": quien(request),
        "modulos": sorted(ajustes.modulos),
    }


@app.get("/api/modulos")
async def modulos():
    """Le pregunta a cada módulo si está vivo.

    Un módulo caído es un hueco con su motivo, nunca una pantalla colgada: por
    eso cada llamada lleva su timeout y el error se traduce a texto legible.
    """
    ajustes = cargar()
    resultado = []

    for modulo in ajustes.modulos.values():
        entrada = {"nombre": modulo.nombre, "url": modulo.url}
        try:
            async with httpx.AsyncClient(timeout=modulo.timeout_seg) as cliente:
                respuesta = await cliente.get(f"{modulo.url}/api/salud")
            entrada["ok"] = respuesta.status_code == 200
            if not entrada["ok"]:
                entrada["detalle"] = f"contestó {respuesta.status_code}"
        except httpx.TimeoutException:
            entrada["ok"] = False
            entrada["detalle"] = f"no contestó en {modulo.timeout_seg:g} s"
        except httpx.HTTPError as exc:
            entrada["ok"] = False
            entrada["detalle"] = f"no se pudo alcanzar ({type(exc).__name__})"
        resultado.append(entrada)

    return {"modulos": resultado}


@app.get("/api/bordes")
def bordes(
    almacen: LecturaDelAlmacen = Depends(obtener_almacen),
    doyle: ClienteDeDoyle = Depends(obtener_doyle),
):
    """Le pregunta a los dos bordes del proceso si contestan de verdad.

    No es `/api/salud` con otro nombre: salud dice que el proceso vive sin
    tocar nada, y esto hace una lectura real. Sirve para saber, antes de armar
    un pedido, si el rol `continental` sigue pudiendo leer de `marts` —cada
    `dbt build` recrea las tablas y borra sus permisos, y a farmacia-data le
    pasó el 2026-09-07 a las 20:30— y si Doyle tiene sesiones vivas.

    Cada borde se atiende por separado: uno caído es un hueco con su motivo y
    no contagia al otro (regla 4). El motivo es el TIPO de la falla, nunca su
    texto: un `str(exc)` de SQLAlchemy lleva la cadena de conexión con
    contraseña y esto corre detrás de un túnel (regla 5).

    Es `def` y no `async def` a propósito: los dos bordes son síncronos
    —psycopg2 no es asíncrono— y así FastAPI los corre en su pool de hilos sin
    bloquear el bucle de eventos.
    """
    resultado = []

    entrada = {"nombre": "almacen"}
    try:
        entrada["productos"] = len(almacen.catalogo())
        ultima = almacen.ultima_fecha_con_ventas()
        entrada["ultima_venta"] = ultima.isoformat() if ultima else None
        entrada["ok"] = True
    except Exception as exc:  # noqa: BLE001 — cualquier falla del almacén es un hueco, no un 500
        log.exception("El almacén no contestó")
        entrada["ok"] = False
        entrada["detalle"] = f"el almacén no contestó ({type(exc).__name__})"
    resultado.append(entrada)

    entrada = {"nombre": "doyle"}
    try:
        sesiones = doyle.sesiones()
        entrada["sesiones"] = len(sesiones)
        entrada["sin_sesion"] = sorted(
            s.proveedor for s in sesiones if s.estado != "guardada"
        )
        entrada["ok"] = True
    except Exception as exc:  # noqa: BLE001 — Doyle caído no puede tumbar la pantalla
        log.exception("Doyle no contestó")
        entrada["ok"] = False
        entrada["detalle"] = f"Doyle no contestó ({type(exc).__name__})"
    resultado.append(entrada)

    return {"bordes": resultado}


@app.get("/api/pedido-sugerido")
def pedido_sugerido(almacen: LecturaDelAlmacen = Depends(obtener_almacen)):
    """El pedido sugerido del día: un renglón por producto vendido.

    **La ventana se ancla en `max(fecha)` del almacén y nunca en el reloj.**
    Esa es la única decisión que se toma aquí, y por eso se toma aquí: el
    cálculo es una función pura que recibe las ventas ya elegidas, así que no
    tiene reloj que mirar aunque alguien quisiera. El Postgres del contenedor
    corre en UTC y su `current_date` puede ir dos días adelante del último
    dato; a farmacia-data le costó 11.7 puntos de crecimiento inventados.

    Hoy la ventana de reposición es **el último día con datos**. Acumular
    desde el cierre del pedido sugerido anterior —que es lo que ADR 0002
    decide, porque lo del sábado llega hasta el lunes en la noche— necesita que
    el sugerido se guarde, y eso es el ticket 09.

    **Cada renglón dice su clasificación** —medicamento, abarrote o sin
    clasificar—, y eso no filtra nada: la lista sigue trayendo todo lo que se
    vendió. Las listas de anaqueles salen de `config/continental.yml` y se le
    pasan al cálculo, que no lee archivos.

    **La ruta no recibe qué vista está elegida, y eso es a propósito.** Manda
    la lista completa más la definición de las dos vistas (`vistas`), y el
    navegador se queda con los renglones que cada una deja ver. El porqué
    —una lectura, una lista, dos maneras de verla, y la regla probada en
    Python en vez de escrita en el JavaScript— está entero en `vistas.py`.

    **La cobertura se mide sobre otra ventana**, más larga (`DIAS_DE_RITMO`), y
    las dos salen de **una sola lectura**: la de reposición es un subconjunto
    de la del ritmo, así que se recorta aquí en memoria —del orden de 600
    filas— en vez de pedirle dos veces lo mismo a Postgres. El porqué de los 28
    días está junto a la constante, en `sugerido.py`.

    Un almacén caído sale como `ok: false` con su motivo y no como una lista
    vacía (regla 4): "hoy no se vendió nada" y "no pude leer" se ven idénticos
    si el único dato es una lista sin renglones, y el precio de confundirlos es
    que el pedido del día no se hace. El motivo es el **tipo** de la falla,
    nunca su texto: un `str(exc)` de SQLAlchemy lleva la cadena de conexión con
    contraseña y esto corre detrás de un túnel (regla 5).

    Es `def` y no `async def` a propósito: el almacén es síncrono —psycopg2 no
    es asíncrono— y así FastAPI lo corre en su pool de hilos sin bloquear el
    bucle de eventos.
    """
    try:
        ultima = almacen.ultima_fecha_con_ventas()
        # Dos cosas en una lectura. Sin ventas no hay nada que reponer, y leer
        # el catálogo entero (3,429 filas) para descubrirlo sería trabajo
        # tirado; y el `- 1` es el rango completo menos el propio día: de
        # `ultima - 27` a `ultima` son 28 días, porque el almacén incluye los
        # dos extremos.
        ventas_del_ritmo = (
            almacen.ventas(ultima - dt.timedelta(days=DIAS_DE_RITMO - 1), ultima)
            if ultima
            else []
        )
        catalogo = almacen.catalogo() if ultima else []
    except Exception as exc:  # noqa: BLE001 — el almacén caído es un hueco, no un 500
        log.exception("El almacén no contestó al armar el pedido sugerido")
        return {
            "ok": False,
            "detalle": f"el almacén no contestó ({type(exc).__name__})",
            "fecha_de_ventas": None,
            "renglones": [],
            "sin_catalogo": 0,
            "sin_clasificar": 0,
            "vistas": _vistas(),
        }

    # Lo que se repone es solo el último día: se recorta de lo ya leído en vez
    # de hacer una segunda consulta por un subconjunto de las mismas filas.
    ventas = [v for v in ventas_del_ritmo if v.fecha == ultima]
    # Las listas de anaqueles se leen aquí y se pasan hacia adentro: el
    # cálculo es una función pura y no abre archivos, igual que no mira el
    # reloj. `cargar()` está cacheado, así que esto no relee el YAML por
    # petición.
    pedido = calcular_pedido_sugerido(
        ventas=ventas,
        catalogo=catalogo,
        ventas_del_ritmo=ventas_del_ritmo,
        reglas=reglas_configuradas(),
    )

    if pedido.sin_catalogo:
        # A la bitácora con nombre y apellido: el hueco se ve en la pantalla,
        # pero quien vaya a arreglarlo en SICAR necesita los ids.
        log.warning(
            "%d producto(s) vendido(s) del %s no están en marts.dim_producto: %s",
            pedido.sin_catalogo,
            pedido.fecha_de_ventas,
            [r.producto_id for r in pedido.renglones if not r.esta_en_el_catalogo],
        )

    return {
        "ok": True,
        "fecha_de_ventas": (
            pedido.fecha_de_ventas.isoformat() if pedido.fecha_de_ventas else None
        ),
        # `esta_agotado` va explícito porque `asdict` no incluye propiedades, y
        # la regla —existencia conocida y en cero o negativa— tiene que vivir
        # en un solo lugar probado, no repetida en el JavaScript de la
        # pantalla.
        "renglones": [
            {**dataclasses.asdict(r), "esta_agotado": r.esta_agotado}
            for r in pedido.renglones
        ],
        "sin_catalogo": pedido.sin_catalogo,
        # De la lista completa, no de la vista: la pregunta que responde es si
        # vale la pena ir a ponerles anaquel en SICAR. El porqué está en
        # `PedidoSugerido.sin_clasificar`.
        "sin_clasificar": pedido.sin_clasificar,
        "vistas": _vistas(),
    }


def _vistas() -> list[dict]:
    """Las dos vistas como JSON, para que la pantalla no se sepa la regla.

    Viaja en la misma respuesta que la lista y no en una ruta aparte: es lo
    que hace que el interruptor no cueste ni una consulta más, y que la vista
    y los renglones que filtra vengan siempre de la misma lectura.
    """
    return [dataclasses.asdict(v) for v in VISTAS]


@app.get("/")
async def inicio():
    return FileResponse(ESTATICOS / "index.html")


app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")
