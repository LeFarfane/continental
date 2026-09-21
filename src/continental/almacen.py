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
from collections.abc import Callable, Collection
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
    suma `cantidad` sobre el rango. El lote nocturno **no** ordena por
    `utilidad`: ordena por `dim_producto.clase_abc` (ADR 0018 de farmacia-data
    descartó a propósito ordenar por la utilidad de la ventana).

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


#: Los tres valores que toma `marts.dim_producto.clase_abc`, y el orden
#: en que se leen de más a menos importante. Salen del ADR 0018 de
#: farmacia-data: participación acumulada en la utilidad de 12 meses, A hasta
#: 80% y B hasta 95%.
#:
#: Se escriben aquí y no se deducen porque son el vocabulario de otro repo: lo
#: que hay que comparar es **esto** contra lo que dbt escribe (columna
#: materializada el 2026-09-20, farmacia-data `c989ecb`), y una tupla tiene
#: dónde ponerle la comparación.
CLASES_ABC: tuple[str, ...] = ("A", "B", "C")

#: Que un producto no tenga clase conocida. **No es una cuarta clase**: es "no
#: se sabe", igual que `existencia is None` en un renglón.
#:
#: Desde el 2026-09-20 ya no vale esto para todos: vale para los productos que
#: no vendieron nada en los últimos 365 días, que es lo que dbt deja en NULL a
#: propósito. Ver el ADR 0018 — mandarlos a `'C'` ordenaba igual de bien y
#: afirmaba algo que nadie midió.
SIN_CLASE_ABC = ""

#: **El interruptor del bloqueo externo. Se movió el 2026-09-20.**
#:
#: `marts.dim_producto` ya trae `clase_abc`: el ADR 0018 de farmacia-data se
#: implementó ese día —A3 dejó de ser un CTE copiado cuatro veces y pasó a
#: columna, calculada por dbt en la cadena nocturna—. `dbt build` en atlas:
#: 61 de 61.
#:
#: Queda escrito porque el interruptor sigue haciendo falta y la razón no es
#: histórica: **el catálogo es una de las dos lecturas con las que se arma la
#: lista del día**, así que un `select clase_abc` contra una base donde la
#: columna no esté rebota con "column does not exist" y se lleva la lista
#: entera por delante. Si algún día hay un segundo almacén, o alguien apunta
#: Continental a una base sin construir, esto se vuelve a mover a `False` y el
#: módulo sigue funcionando —ordenando por urgencia y diciéndolo en su
#: bitácora— en vez de no funcionar.
#:
#: `continental.verificar` mira las columnas reales en cada despliegue y
#: distingue los dos casos: que la columna falte, y que exista y Continental no
#: la lea. Los dos salen como PENDIENTE y ninguno tumba nada.
LA_CLASE_ABC_ESTA_EN_DIM_PRODUCTO = True


def clase_abc_normalizada(crudo) -> str:
    """Lo que venga en la columna → `"A"`, `"B"`, `"C"` o `SIN_CLASE_ABC`.

    Estricta a propósito y en la dirección segura: un valor que no sea una de
    las tres clases se convierte en "no se sabe" y no en una clase inventada.
    El lote ordena con esto, y un producto que subiera al principio de la noche
    por un `"a "` mal leído se llevaría el tiempo de los que de verdad pesan.

    Se acepta la minúscula y el espacio porque son las dos maneras en que un
    `case` de dbt suele entregar una etiqueta, y rechazarlas costaría el orden
    entero por un detalle de formato.
    """
    texto = ("" if crudo is None else str(crudo)).strip().upper()
    return texto if texto in CLASES_ABC else SIN_CLASE_ABC


@dataclass(frozen=True, slots=True)
class Producto:
    """Una fila de `marts.dim_producto`, con anaquel y existencia.

    `anaquel` puede venir vacío: 688 de 3,429 artículos no lo tienen
    (medido al 2026-09). Esos productos se muestran marcados *sin clasificar*,
    nunca se esconden — un producto que desaparece de la lista por no tener
    anaquel es mercancía que va a faltar sin que nadie se entere.

    **`clase_abc` es un dato del catálogo y por eso vive aquí**, al lado del
    anaquel y del costo, y no en un mapa suelto que el lote nocturno se pase
    por un lado. Es la columna del ADR 0018 de farmacia-data: A, B o C por
    participación acumulada en la utilidad de 12 meses.

    La columna existe en `marts.dim_producto` desde el 2026-09-20
    (farmacia-data `c989ecb`) y la consulta real la pide — ver
    `LA_CLASE_ABC_ESTA_EN_DIM_PRODUCTO`. **Vale `SIN_CLASE_ABC` en los
    productos sin ventas en los últimos 365 días** (NULL a propósito, el 55%
    del catálogo), y eso no es un valor por omisión inocente: es "no se sabe".
    Nada deduce una clase de otra cosa:
    quien ordena por importancia mira si la sabe y **dice que no la sabe**
    cuando no, en vez de inventarse un orden alterno y llamarlo cumplido. El
    ADR 0018 descartó a propósito "ordenar por la utilidad de la ventana" (su
    opción 2), así que eso no es una alternativa disponible.

    Va al final y con valor por omisión para que las filas que ya se
    construyen en cien sitios —dobles, pruebas, `AlmacenFalso`— sigan
    construyéndose igual.
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
    clase_abc: str = SIN_CLASE_ABC

    @property
    def tiene_clase_abc(self) -> bool:
        """Si de este producto se sabe cuánto pesa (no, si no vendió en 365 días)."""
        return self.clase_abc in CLASES_ABC


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

    Cinco lecturas y ninguna más: las tres que el módulo de Pedido necesitaba,
    el ancla temporal, y desde el ticket 26 la quinta —qué productos han
    aparecido alguna vez en una compra—. Si hace falta una sexta, entra aquí y
    no por una conexión prestada.
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

    def productos_con_compras(self, productos: Collection[int]) -> frozenset[int]:
        """De esos productos, cuáles han aparecido **alguna vez** en una compra.

        La quinta lectura, del ticket 26: para decir que un renglón en camino
        **nunca** va a tener "probablemente recibido" hay que saber que su
        producto nunca ha dejado rastro en `fct_compras` —606 de 3,429
        artículos, 17.7%—. Sobre la misma tabla que `compras_desde`, así que el
        rol no necesita ningún permiso nuevo.
        """
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

#: Las once columnas de `marts.dim_producto` que Continental necesita siempre.
#: `clase_abc` va aparte (`COLUMNA_DE_LA_CLASE_ABC`) y se agrega solo si
#: `LA_CLASE_ABC_ESTA_EN_DIM_PRODUCTO`: existe desde el 2026-09-20
#: (farmacia-data `c989ecb`), pero nombrarla contra una base donde no esté haría
#: que la lista del día entera rebotara con "column clase_abc does not exist".
_COLUMNAS_DEL_CATALOGO = (
    "producto_id",
    "clave",
    "descripcion",
    "categoria",
    "departamento",
    "ubicacion",
    "precio_lista_sin_iva",
    "costo",
    "existencia",
    "esta_activo",
    "es_granel",
)

#: Lo único que se le agrega a la consulta cuando el interruptor está encendido.
COLUMNA_DE_LA_CLASE_ABC = "clase_abc"


def _sql_del_catalogo(con_la_clase: bool) -> str:
    """El `select` del catálogo, con o sin la columna de la clase.

    Se arma y no se escribe dos veces entero por la razón de siempre: dos
    consultas casi iguales se separan al primer cambio, y la que nadie corre
    sería justo la que se quedara vieja. Desde el 2026-09-20 la que corre es la
    que trae la clase; la otra es la de repliegue si el interruptor se apaga.

    No es SQL armado con datos de nadie: los nombres son constantes de este
    archivo y el booleano sale de otra constante de este archivo.
    """
    columnas = list(_COLUMNAS_DEL_CATALOGO)
    if con_la_clase:
        columnas.append(COLUMNA_DE_LA_CLASE_ABC)
    return (
        f"select {', '.join(columnas)}\n"
        "from marts.dim_producto\n"
        "order by producto_id"
    )


_CATALOGO = text(_sql_del_catalogo(LA_CLASE_ABC_ESTA_EN_DIM_PRODUCTO))

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

# Sin `dim_fecha`: la pregunta es "alguna vez", y no hace falta ninguna fecha.
# Acotada a los productos que se preguntan: son los que vienen en camino, unos
# cuantos, no el catálogo entero.
_PRODUCTOS_CON_COMPRAS = text(
    """
    select distinct c.producto_id
    from marts.fct_compras c
    where c.producto_id = any(:productos)
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
                # La consulta pide la columna desde el 2026-09-20
                # (`LA_CLASE_ABC_ESTA_EN_DIM_PRODUCTO = True`); NULL —los
                # productos sin ventas en 365 días— queda en `SIN_CLASE_ABC`.
                # `getattr` y no `f.clase_abc` para que, si el interruptor se
                # apaga y la fila no la trae, esto siga valiendo "no se sabe".
                clase_abc=clase_abc_normalizada(
                    getattr(f, COLUMNA_DE_LA_CLASE_ABC, None)
                ),
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

    def productos_con_compras(self, productos: Collection[int]) -> frozenset[int]:
        if not productos:
            return frozenset()
        return frozenset(
            int(f.producto_id)
            for f in self._filas(_PRODUCTOS_CON_COMPRAS, productos=sorted(productos))
        )

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
