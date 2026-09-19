"""El cálculo del pedido sugerido: lo que se vendió, pieza por pieza.

**Función pura y nada más.** Entran dos listas —ventas y catálogo— y sale un
pedido sugerido. No recibe el almacén, no abre una conexión y no lee
configuración. La razón no es purismo: quien decide *qué ventas* entran es la
ruta, que las pide al almacén anclándose en `max(fecha)`, y meter esa decisión
aquí abriría la puerta a resolverla con el reloj. Aquí no hay reloj que mirar.

**Nada se filtra.** Un producto que no está en el catálogo sale igual, marcado;
uno que se vendió con existencia de sobra también. Filtrar sería meter la
lógica de la tarjeta O2 de Metabase por la puerta de atrás, y el dueño pidió
explícitamente no usarla como fuente del pedido (ADR 0002). El orden por
urgencia, la existencia y los días de cobertura son el ticket 04; la
clasificación por anaquel, el 05. Hoy la ventana es **el último día con datos**
y la acumulación desde el corte es el ticket 09.

Reposición 1 a 1: "se vendieron tres, se piden tres". Es aritmética que el
encargado verifica de un vistazo, y eso importa más que ser óptima —una lista
que no se entiende no se usa—.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Sequence
from dataclasses import dataclass

from continental.almacen import LineaDeVenta, Producto

#: Decimales a los que se redondea la suma de piezas antes de subirla al entero
#: siguiente. `1.1 + 2.2 + 0.7` da `4.000000000000001` en coma flotante, y sin
#: este paso el sugerido propondría **5** piezas de algo de lo que salieron 4:
#: un error que nadie sabría explicar mirando el ticket. Tres decimales sobran
#: para gramos y mililitros, que es todo lo que se vende a granel aquí (5
#: artículos con `granel = 1`, medido sobre el respaldo del 2026-07-27).
_DECIMALES_DE_GRANEL = 3


@dataclass(frozen=True, slots=True)
class Renglon:
    """Un producto con su cantidad dentro de un pedido sugerido (CONTEXT.md).

    `cantidad_propuesta` es entera porque a un proveedor no se le piden 2.5
    piezas, y `piezas_vendidas` se conserva al lado para que la propuesta se
    pueda verificar contra el dato (historia 5 del spec). Para todo lo que no
    es granel las dos valen lo mismo.

    `esta_en_el_catalogo` en falso es un producto que se vendió y que
    `marts.dim_producto` no conoce. **No se esconde.** Es el mismo daño que
    esconder los 688 artículos sin anaquel: mercancía que va a faltar sin que
    nadie se entere (regla 4 de CLAUDE.md).
    """

    producto_id: int
    clave: str  # EAN de 13 dígitos; vacío si el producto no está en el catálogo
    descripcion: str
    piezas_vendidas: float
    cantidad_propuesta: int
    esta_en_el_catalogo: bool


@dataclass(frozen=True, slots=True)
class PedidoSugerido:
    """La lista de un día: qué conviene comprar (CONTEXT.md).

    `fecha_de_ventas` es de qué día salió la lista, y va en el mismo objeto que
    los renglones a propósito: una lista sin su fecha se lee igual venga de
    ayer o del viernes pasado, y quien la mire no tiene cómo saberlo
    (historia 7 del spec).

    Vale `None` cuando no hubo ni una venta. **Eso no es un error**: la
    farmacia cierra los domingos y no hay una sola venta en domingo en 33
    meses. Quien lo muestre tiene que distinguirlo de un fallo de lectura, que
    se ve igual de vacío.
    """

    fecha_de_ventas: dt.date | None
    renglones: tuple[Renglon, ...]

    @property
    def sin_catalogo(self) -> int:
        """Cuántos renglones son de productos que el catálogo no conoce.

        Se cuenta para poder decirlo en la pantalla y en la bitácora. Un hueco
        que se cuenta es información; uno que se calla es una lista que miente
        por omisión.
        """
        return sum(1 for r in self.renglones if not r.esta_en_el_catalogo)


def calcular_pedido_sugerido(
    ventas: Sequence[LineaDeVenta], catalogo: Sequence[Producto]
) -> PedidoSugerido:
    """Ventas + catálogo → el pedido sugerido, en reposición 1 a 1.

    La fecha sale de las ventas recibidas (`max(fecha)`) y **nunca del reloj**:
    el Postgres del contenedor corre en UTC y su `current_date` puede ir dos
    días adelante del último dato —a farmacia-data le costó 11.7 puntos de
    crecimiento inventados—. Derivarla de los datos, en vez de recibirla como
    parámetro, hace que la función no pueda desmentir a la lista que devuelve.

    Un producto vendido varias veces en el día se suma en un solo renglón:
    `fct_ventas` tiene grano ticket × artículo, así que el mismo producto
    aparece una vez por cada ticket en que salió.

    El orden es alfabético por descripción, y es **provisional**: el orden por
    urgencia —agotado primero, luego menor cobertura— es el ticket 04. Se
    ordena de todas formas porque "sin orden definido" acaba siendo "el orden
    en que Python recorrió un diccionario", y eso cambia bajo los pies de quien
    lea la pantalla dos días seguidos.
    """
    if not ventas:
        return PedidoSugerido(fecha_de_ventas=None, renglones=())

    por_producto: dict[int, float] = {}
    for linea in ventas:
        por_producto[linea.producto_id] = (
            por_producto.get(linea.producto_id, 0.0) + linea.cantidad
        )

    productos = {p.producto_id: p for p in catalogo}
    renglones = [
        _renglon(producto_id, piezas, productos.get(producto_id))
        for producto_id, piezas in por_producto.items()
    ]
    renglones.sort(key=lambda r: (r.descripcion.casefold(), r.producto_id))

    return PedidoSugerido(
        fecha_de_ventas=max(v.fecha for v in ventas),
        renglones=tuple(renglones),
    )


def _renglon(producto_id: int, piezas: float, producto: Producto | None) -> Renglon:
    """Un renglón, esté o no el producto en el catálogo.

    El producto huérfano **entra igual**. Tronar sería peor: un solo artículo
    que `dim_producto` no conoce dejaría a la farmacia sin pedido del día, y
    esconderlo sería reponer de menos sin que nadie lo note. Así el renglón se
    ve, dice cuál es por su `producto_id` —que es con lo que se busca en
    SICAR— y se cuenta aparte.

    La clave se queda **vacía a propósito**. Es el EAN, lo único que empareja
    con el catálogo de un proveedor; inventar una haría que la comparación de
    precios emparejara con cualquier cosa, que es justo el tropiezo de Marlowe
    con la caja de 60.
    """
    return Renglon(
        producto_id=producto_id,
        clave=producto.clave if producto else "",
        descripcion=(
            producto.descripcion
            if producto
            else f"Producto {producto_id} — no está en el catálogo"
        ),
        piezas_vendidas=piezas,
        cantidad_propuesta=_piezas_a_pedir(piezas),
        esta_en_el_catalogo=producto is not None,
    )


def _piezas_a_pedir(piezas: float) -> int:
    """Las piezas vendidas, subidas al entero siguiente.

    `fct_ventas.cantidad` no siempre es entera: hay 5 artículos con
    `granel = 1` y de ésos salen 2.5 piezas en un ticket. A un proveedor no se
    le piden 2.5, y hacia **arriba** y no hacia abajo porque redondear a la
    baja repone menos de lo que salió, en silencio — y lo silencioso es lo que
    este repo prohíbe. El renglón conserva `piezas_vendidas` para que la
    diferencia se vea.

    El `round` previo no es cosmético: ver `_DECIMALES_DE_GRANEL`.
    """
    return math.ceil(round(piezas, _DECIMALES_DE_GRANEL))
