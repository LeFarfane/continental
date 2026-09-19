"""Lo único que Continental lee del almacén de `farmacia-data`, esquema `marts`.

Devuelve **datos, no conexiones**: dataclasses congeladas que ya no saben de
qué motor salieron. Es deliberado y contradice el precedente: Marlowe pasa
cursores hacia arriba, y el precio es que una prueba suya necesita un fixture
de ~100 líneas con una URL de Postgres muerta. Aquí las funciones que importan
reciben listas, y por eso el suite entero corre sin Postgres en menos de un
segundo.

**Nada se conecta al importar este archivo.** El motor nace en `motor()`,
detrás de un `lru_cache`, y solo cuando alguien pide una lectura de verdad. Un
módulo que conecta al importarse convierte cada `import` en una dependencia de
red, y eso es exactamente lo que este prefactor viene a evitar.

Solo lectura (regla 6 de `CLAUDE.md`): el rol `continental` tiene `SELECT` sobre
`marts` y nada más. Ese permiso es la garantía; este módulo es el cinturón.

**El anaquel se llama anaquel.** En `marts.dim_producto` la columna es
`ubicacion`; el glosario de `CONTEXT.md` manda sobre el nombre de cualquier
cosa, así que la traducción se hace aquí, una vez, en el borde — y no en cada
consumidor.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol, runtime_checkable

import sqlalchemy
from sqlalchemy import text

# ------------------------------------------------------------------- datos
#
# Congeladas a propósito: un renglón del pedido guarda el precio al que se
# decidió comprar, no el de hoy. Una fila mutable invita a "actualizarla" y a
# perder ese congelado sin que nadie lo note.


@dataclass(frozen=True, slots=True)
class LineaDeVenta:
    """Una línea de `marts.fct_ventas`, con su fecha ya resuelta.

    Grano: ticket × artículo (`detallev` tiene PK `(ven_id, art_id)`), así que
    un producto no aparece dos veces en la misma venta. La reposición 1 a 1
    suma `cantidad` sobre el rango; `utilidad` es lo que ordena el lote
    nocturno mientras `clase_abc` no exista.

    `costo` es **sin IVA**. El de mostrador viene con IVA en otra columna:
    restarlos directo es la equivocación que Marlowe ya cometió, con la flecha
    apuntando al revés.
    """

    fecha: dt.date
    producto_id: int
    cantidad: float
    importe: float
    costo: float
    utilidad: float


@dataclass(frozen=True, slots=True)
class Producto:
    """Una fila de `marts.dim_producto`, con anaquel y existencia.

    `anaquel` puede venir vacío: 688 de 3,429 artículos no lo tienen
    (medido al 2026-09). Esos productos se muestran marcados *sin clasificar*,
    nunca se esconden — un producto que desaparece de la lista por no tener
    anaquel es mercancía que va a faltar sin que nadie se entere.
    """

    producto_id: int
    clave: str  # EAN de 13 dígitos: lo único que empareja con el catálogo de un proveedor
    descripcion: str
    categoria: str
    departamento: str
    anaquel: str  # `dim_producto.ubicacion`, ya normalizada por dbt
    precio_lista_sin_iva: float
    costo: float  # el nuestro, SIN IVA
    existencia: float
    esta_activo: bool
    es_granel: bool


@dataclass(frozen=True, slots=True)
class LineaDeCompra:
    """Una línea de `marts.fct_compras`, con su fecha ya resuelta.

    Es la evidencia con la que se propone "probablemente recibido". Tres cosas
    medidas que hay que tener presentes al usarla:

    - 606 de 3,429 artículos (17.7%) nunca aparecen aquí, 128 de ellos con
      existencia: para ésos el emparejamiento no va a proponer nada nunca.
    - SICAR no tiene pedidos: una compra se captura ya recibida y no existe
      estado parcial.
    - **`folio` tiene semántica no verificada.** Se expone porque sirve como
      evidencia que una persona lee, no para emparejar con él. El
      emparejamiento es por proveedor, producto y fecha posterior al envío
      (ADR 0002).
    """

    compra_id: int
    producto_id: int
    proveedor_id: int
    fecha: dt.date
    cantidad: float
    precio_unitario_pagado: float
    importe_pagado: float
    folio: str


# --------------------------------------------------------------- interfaz


@runtime_checkable
class LecturaDelAlmacen(Protocol):
    """El borde de lectura. Solo `SELECT`, y solo datos de salida.

    Cuatro lecturas y ninguna más: las tres que el módulo de Pedido necesita,
    más el ancla temporal. Si alguna vez hace falta una quinta, entra aquí y no
    por una conexión prestada.
    """

    def ventas(self, desde: dt.date, hasta: dt.date) -> list[LineaDeVenta]:
        """Ventas del rango, ambos extremos incluidos."""
        ...

    def catalogo(self) -> list[Producto]:
        """El catálogo completo, con anaquel y existencia. Sin filtrar.

        Nada se filtra aquí: quien decide qué se muestra es la clasificación,
        y filtrar en el borde escondería mercancía sin dejar rastro.
        """
        ...

    def compras_desde(self, fecha: dt.date) -> list[LineaDeCompra]:
        """Compras con fecha igual o posterior a `fecha`."""
        ...

    def ultima_fecha_con_ventas(self) -> dt.date | None:
        """`max(fecha)` de las ventas, o `None` si no hay ni una.

        Existe para que **nadie de arriba tenga excusa para mirar el reloj**.
        El Postgres del contenedor corre en UTC y su `current_date` puede ir
        dos días adelante del último dato: a farmacia-data le costó 11.7 puntos
        de crecimiento inventados. Además, el respaldo de SICAR sube hacia las
        18:51 de lunes a viernes y lo del sábado llega hasta el lunes en la
        noche — peor caso, 2.5 días de retraso real.
        """
        ...


# --------------------------------------------------------- implementación

_VENTAS = text(
    """
    select f.fecha, v.producto_id, v.cantidad, v.importe, v.costo, v.utilidad
    from marts.fct_ventas v
    join marts.dim_fecha f on f.fecha_id = v.fecha_id
    where f.fecha between :desde and :hasta
    order by f.fecha, v.producto_id
    """
)

_CATALOGO = text(
    """
    select producto_id, clave, descripcion, categoria, departamento,
           ubicacion, precio_lista_sin_iva, costo, existencia,
           esta_activo, es_granel
    from marts.dim_producto
    order by producto_id
    """
)

_COMPRAS = text(
    """
    select c.compra_id, c.producto_id, c.proveedor_id, f.fecha, c.cantidad,
           c.precio_unitario_pagado, c.importe_pagado, c.folio
    from marts.fct_compras c
    join marts.dim_fecha f on f.fecha_id = c.fecha_id
    where f.fecha >= :desde
    order by f.fecha, c.compra_id
    """
)

_ULTIMA_VENTA = text(
    """
    select max(f.fecha)
    from marts.fct_ventas v
    join marts.dim_fecha f on f.fecha_id = v.fecha_id
    """
)


class AlmacenPostgres:
    """`LecturaDelAlmacen` contra el Postgres de `farmacia-data`.

    Recibe la **factoría** del motor, no el motor: `AlmacenPostgres(motor)`, sin
    paréntesis. Construir este objeto no crea nada y no puede fallar, y eso
    importa más de lo que parece — una dependencia de FastAPI que truena lo
    hace *antes* de entrar a la ruta, donde el `try` del manejador ya no la
    alcanza, y una base caída se convertiría en un 500 genérico en vez de un
    hueco con su motivo (regla 4 de `CLAUDE.md`). Así la falla ocurre dentro de
    la lectura, que es donde alguien la puede contar.
    """

    def __init__(self, fabrica_de_motor: Callable[[], sqlalchemy.Engine] | None):
        self._fabrica = fabrica_de_motor

    def _filas(self, consulta, **parametros):
        if self._fabrica is None:
            raise RuntimeError(
                "Este AlmacenPostgres se construyó sin factoría de motor. Úsalo "
                "con `motor` o sustitúyelo por un doble."
            )
        with self._fabrica().connect() as conexion:
            return conexion.execute(consulta, parametros).fetchall()

    def ventas(self, desde: dt.date, hasta: dt.date) -> list[LineaDeVenta]:
        return [
            LineaDeVenta(
                fecha=f.fecha,
                producto_id=int(f.producto_id),
                cantidad=float(f.cantidad or 0),
                importe=float(f.importe or 0),
                costo=float(f.costo or 0),
                utilidad=float(f.utilidad or 0),
            )
            for f in self._filas(_VENTAS, desde=desde, hasta=hasta)
        ]

    def catalogo(self) -> list[Producto]:
        return [
            Producto(
                producto_id=int(f.producto_id),
                clave=(f.clave or "").strip(),
                descripcion=(f.descripcion or "").strip(),
                categoria=(f.categoria or "").strip(),
                departamento=(f.departamento or "").strip(),
                anaquel=(f.ubicacion or "").strip(),
                precio_lista_sin_iva=float(f.precio_lista_sin_iva or 0),
                costo=float(f.costo or 0),
                existencia=float(f.existencia or 0),
                esta_activo=bool(f.esta_activo),
                es_granel=bool(f.es_granel),
            )
            for f in self._filas(_CATALOGO)
        ]

    def compras_desde(self, fecha: dt.date) -> list[LineaDeCompra]:
        return [
            LineaDeCompra(
                compra_id=int(f.compra_id),
                producto_id=int(f.producto_id),
                proveedor_id=int(f.proveedor_id),
                fecha=f.fecha,
                cantidad=float(f.cantidad or 0),
                precio_unitario_pagado=float(f.precio_unitario_pagado or 0),
                importe_pagado=float(f.importe_pagado or 0),
                folio=(f.folio or "").strip(),
            )
            for f in self._filas(_COMPRAS, desde=fecha)
        ]

    def ultima_fecha_con_ventas(self) -> dt.date | None:
        filas = self._filas(_ULTIMA_VENTA)
        return filas[0][0] if filas else None


@lru_cache(maxsize=1)
def motor() -> sqlalchemy.Engine:
    """El motor de SQLAlchemy, creado la primera vez que alguien lo pide.

    Perezoso y cacheado a propósito. `create_engine` no abre socket, pero sí
    exige que `WAREHOUSE_URL` exista, y hacer eso al importar convertiría
    `import continental.almacen` —que hacen hasta las pruebas— en algo que
    falla sin `.env`. `pool_pre_ping` está porque el contenedor de Postgres se
    reinicia con cada `docker compose up` de farmacia-data y las conexiones del
    pool quedan muertas sin avisar.

    Falla con `RuntimeError` y no con `SystemExit` como hace `config.cargar`, y
    la diferencia importa: `cargar` corre al arrancar, cuando morir es lo
    correcto; esto corre **dentro de una petición**, y un `SystemExit` ahí no
    lo atrapa ni el manejador de errores de FastAPI ni el de Starlette —los dos
    filtran por `Exception`—, así que en vez de un hueco con su motivo se
    llevaría por delante al servidor.
    """
    from continental.config import cargar

    url = cargar().warehouse_url
    if not url:
        raise RuntimeError(
            "Falta WAREHOUSE_URL. Copia `.env.example` a `.env` y apúntalo al "
            "Postgres de farmacia-data con el rol `continental`."
        )
    return sqlalchemy.create_engine(url, pool_pre_ping=True)
