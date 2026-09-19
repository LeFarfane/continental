"""El cálculo del pedido sugerido: lo que se vendió, pieza por pieza.

**Función pura y nada más.** Entran ventas y catálogo y sale un pedido
sugerido. No recibe el almacén, no abre una conexión y no lee configuración. La
razón no es purismo: quien decide *qué ventas* entran es la ruta, que las pide
al almacén anclándose en `max(fecha)`, y meter esa decisión aquí abriría la
puerta a resolverla con el reloj. Aquí no hay reloj que mirar.

**Nada se filtra.** Un producto que no está en el catálogo sale igual, marcado;
uno que se vendió con el anaquel lleno también, solo que hasta abajo. Filtrar
sería meter la lógica de la tarjeta O2 de Metabase por la puerta de atrás, y el
dueño pidió explícitamente no usarla como fuente del pedido (ADR 0002). Cada
renglón **dice** si es medicamento, abarrote o algo sin clasificar, y eso es
justo lo contrario de filtrar: quien lea la lista decide, la lista no decide
por él. El interruptor entre vistas es el ticket 06. Qué ventana de ventas
entra —lo acumulado desde el corte del último cerrado, y no el último día con
datos— lo decide `almacenamiento.ventana_de_reposicion` y lo resuelve la ruta:
aquí las ventas llegan ya elegidas.

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
from continental.clasificacion import (
    SIN_CLASIFICAR,
    ReglasDeClasificacion,
    clasificar,
)

#: Decimales a los que se redondea la suma de piezas antes de subirla al entero
#: siguiente. `1.1 + 2.2 + 0.7` da `4.000000000000001` en coma flotante, y sin
#: este paso el sugerido propondría **5** piezas de algo de lo que salieron 4:
#: un error que nadie sabría explicar mirando el ticket. Tres decimales sobran
#: para gramos y mililitros, que es todo lo que se vende a granel aquí (5
#: artículos con `granel = 1`, medido sobre el respaldo del 2026-07-27).
_DECIMALES_DE_GRANEL = 3

#: Decimales con los que se guarda y se muestra la cobertura. Uno: "2.7 días" y
#: "2.68 días" llevan a la misma decisión, y el segundo aparenta una precisión
#: que el dato no tiene —las ventas llegan con hasta 2.5 días de retraso—. Se
#: redondea al construir el renglón, no al pintarlo, para que el número que se
#: ve sea exactamente el que se usó para ordenar y el que mañana se guarde
#: (ticket 08).
_DECIMALES_DE_COBERTURA = 1

#: Días de venta con los que se mide el ritmo para la cobertura. **No es la
#: ventana de reposición** —esa es lo acumulado desde el corte del último
#: cerrado—: es cuánta historia se mira para estimar "a este ritmo, ¿cuánto
#: dura lo que queda?".
#:
#: 28 y no 30 porque son **cuatro semanas exactas**: cada día de la semana entra
#: el mismo número de veces, así que el promedio no depende de en qué día haya
#: caído el corte. Eso importa aquí más que en otros negocios: la farmacia
#: cierra los domingos —ni una venta en domingo en 33 meses— así que una
#: ventana de 30 días mete cinco veces un día de la semana y cuatro veces los
#: demás, y mueve el ritmo ~3% según el día en que se corra, sin que haya
#: pasado nada.
#:
#: Y 28 y no 90 —los que usa la tarjeta O2 de Metabase— a propósito: la O2
#: responde "qué se está agotando" con tres meses de historia, y el dueño pidió
#: explícitamente no usarla como fuente del pedido (ADR 0002). Cuatro semanas
#: reaccionan a un cambio de demanda dentro del mes y siguen siendo suficientes
#: para que un producto de rotación lenta no salga con el ritmo de un solo día.
#: Medido sobre el respaldo del 2026-07-27: 21,035 líneas de venta en 33 meses
#: son ~640 al mes, así que leer 28 días es del orden de 600 filas — nada para
#: Postgres. Sigue siendo **una sola consulta**: la ruta lee el rango que cubre
#: a las dos ventanas y las recorta en memoria (ver `web/app.py::_armar`). Ojo
#: con eso: desde el ticket 09 la de reposición puede ser **más larga** que
#: ésta —una lista cerrada hace dos meses—, así que la del ritmo hay que
#: recortarla de verdad y no suponer que la lectura ya es ella.
DIAS_DE_RITMO = 28


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

    `clasificacion` es `medicamento`, `abarrote` o `sin clasificar`, y viaja
    **dentro del renglón** por la misma razón que la existencia: se decidió con
    el anaquel que el catálogo tenía cuando se propuso, y quien pinte la lista
    no tiene que volver a deducirla. Un producto fuera del catálogo no tiene
    anaquel que mirar, así que queda `sin clasificar` — que es una respuesta y
    nunca un descarte: se muestra igual, marcado.

    **`existencia` y `dias_de_cobertura` son las del momento en que se propuso
    el renglón, y viajan aquí dentro a propósito.** El renglón se lleva el
    número copiado: no guarda una referencia al catálogo ni forma de volver a
    preguntarle, así que la pantalla no puede mostrar uno distinto del que se
    usó para ordenar la lista. El día que el renglón se guarde (ticket 08),
    **ese número se guarda con él** —igual que el costo congelado de las
    Órdenes de Doyle—, y resolverlo con un `join` contra `dim_producto` al
    leerlo sería reescribir la historia: diría lo que hay hoy, no lo que se vio
    al proponerlo.

    Las dos valen `None` cuando **no se sabe**, que no es lo mismo que cero
    (regla 4 de CLAUDE.md):

    - `existencia is None` — el producto no está en el catálogo. Un cero ahí lo
      mandaría a lo más urgente de la lista mintiendo.
    - `dias_de_cobertura is None` — no se sabe cuánto dura: o no se sabe qué
      queda, o no se vendió en la ventana del ritmo y no hay entre qué dividir.
      **Nunca cero**, que se leería "agotado" justo cuando es lo contrario.
    """

    producto_id: int
    clave: str  # EAN de 13 dígitos; vacío si el producto no está en el catálogo
    descripcion: str
    piezas_vendidas: float
    cantidad_propuesta: int
    esta_en_el_catalogo: bool
    existencia: float | None
    dias_de_cobertura: float | None
    clasificacion: str

    @property
    def esta_agotado(self) -> bool:
        """Que el anaquel esté vacío **y que eso se sepa**.

        Existencia negativa cuenta como agotado: SICAR la permite cuando se
        vendió más de lo que el inventario decía, y ahí tampoco hay nada que
        sacar del anaquel. Sin catálogo esto es falso, no verdadero: no
        sabemos que se acabó.
        """
        return self.existencia is not None and self.existencia <= 0


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

    @property
    def sin_clasificar(self) -> int:
        """Cuántos renglones se quedaron sin anaquel conocido.

        Es la respuesta a "¿vale la pena ponerles anaquel en SICAR?" (historia
        12 del spec), y por eso se cuenta sobre **la lista completa** y no
        sobre lo que el interruptor deje ver: la pregunta es sobre el catálogo,
        no sobre lo que hay en pantalla en este momento. Un número que bajara
        al mover un interruptor se leería como que hay menos productos sin
        anaquel, que es justo lo contrario de lo que este conteo existe para
        decir.

        Que las dos vistas den el mismo número no es casualidad y conviene
        saberlo: `sin clasificar` aparece en las dos (ver `vistas.py`), así
        que el conteo de la vista y el de la lista completa **coinciden
        siempre**. El día que dejen de coincidir, la causa solo puede ser que
        alguien empezó a esconder los sin anaquel — y hay una prueba que se
        pone roja justo ahí.

        No es lo mismo que `sin_catalogo` y los dos se cuentan aparte: un
        producto fuera del catálogo también cae aquí —sin catálogo no hay
        anaquel que mirar—, pero uno que sí está en el catálogo y no tiene
        ubicación capturada solo cae aquí. Se arreglan en dos lugares
        distintos de SICAR, así que se cuentan en dos números distintos.
        """
        return sum(1 for r in self.renglones if r.clasificacion == SIN_CLASIFICAR)


def calcular_pedido_sugerido(
    ventas: Sequence[LineaDeVenta],
    catalogo: Sequence[Producto],
    ventas_del_ritmo: Sequence[LineaDeVenta] | None = None,
    reglas: ReglasDeClasificacion | None = None,
) -> PedidoSugerido:
    """Ventas + catálogo → el pedido sugerido, en reposición 1 a 1 y por urgencia.

    La fecha sale de las ventas recibidas (`max(fecha)`) y **nunca del reloj**:
    el Postgres del contenedor corre en UTC y su `current_date` puede ir dos
    días adelante del último dato —a farmacia-data le costó 11.7 puntos de
    crecimiento inventados—. Derivarla de los datos, en vez de recibirla como
    parámetro, hace que la función no pueda desmentir a la lista que devuelve.

    Un producto vendido varias veces se suma en un solo renglón, y eso vale
    igual dentro de un día que a lo largo de la ventana entera: `fct_ventas`
    tiene grano ticket × artículo, así que el mismo producto aparece una vez
    por cada ticket en que salió, y la suma es sobre todas las líneas
    recibidas. Dos renglones del mismo producto serían pedirlo dos veces, y
    `ux_renglon_producto` los rechaza.

    `ventas` es **lo que se repone** y `ventas_del_ritmo` es **con qué se mide
    la cobertura**: son dos ventanas distintas y por eso son dos argumentos.
    La reposición acumula desde el corte del último cerrado y puede abarcar
    meses; la cobertura necesita una historia de largo fijo, o un producto que
    vendió una pieza hoy y una al mes saldría con el mismo ritmo. Si no se da,
    el ritmo se mide sobre `ventas` — el ritmo siempre sale de ventas que
    entran por argumento, porque aquí no hay reloj ni almacén que consultar.

    **El orden es por urgencia:** primero lo agotado, luego lo de menor
    cobertura, y al final aquello de lo que no se sabe cuánto dura. Ese último
    grupo va al final, no al principio, porque un "no sé" no es evidencia de
    urgencia: ponerlo arriba empujaría hacia abajo lo que de verdad se acabó.
    Sigue estando en la lista, marcado y contado. El desempate es la
    descripción y luego el `producto_id`, los dos completamente determinados
    por los datos: "sin desempate" acaba siendo "el orden en que Python
    recorrió un diccionario", y eso cambia bajo los pies de quien lea la
    pantalla dos días seguidos.

    `reglas` son las listas de anaqueles y categorías con las que se clasifica
    cada renglón, y entran por argumento igual que las ventas: esta función no
    lee `config/continental.yml` ni ningún otro archivo. Sin ellas todo sale
    `sin clasificar`, que se muestra siempre y marcado — el default que menos
    daño hace si alguien despliega con el YAML a medias.
    """
    if not ventas:
        return PedidoSugerido(fecha_de_ventas=None, renglones=())

    por_producto = _piezas_por_producto(ventas)
    ritmo = _ritmo_diario(ventas if ventas_del_ritmo is None else ventas_del_ritmo)
    productos = {p.producto_id: p for p in catalogo}

    renglones = [
        _renglon(
            producto_id,
            piezas,
            productos.get(producto_id),
            ritmo.get(producto_id, 0.0),
            reglas if reglas is not None else ReglasDeClasificacion(),
        )
        for producto_id, piezas in por_producto.items()
    ]
    renglones.sort(key=_urgencia)

    return PedidoSugerido(
        fecha_de_ventas=max(v.fecha for v in ventas),
        renglones=tuple(renglones),
    )


def _piezas_por_producto(ventas: Sequence[LineaDeVenta]) -> dict[int, float]:
    """Cuántas piezas salieron de cada producto en el rango recibido."""
    piezas: dict[int, float] = {}
    for linea in ventas:
        piezas[linea.producto_id] = piezas.get(linea.producto_id, 0.0) + linea.cantidad
    return piezas


def _ritmo_diario(ventas: Sequence[LineaDeVenta]) -> dict[int, float]:
    """Piezas por día de cada producto, sobre la ventana que traen las ventas.

    **Los días salen del dato, no de una constante ni del reloj**: son los que
    van de la primera a la última fecha recibidas, extremos incluidos. Así el
    divisor sigue siendo el correcto cuando la ventana pedida no cabe —una
    farmacia con dos semanas de historia, o el arranque de `fct_ventas`— y
    nadie tiene que mantener sincronizados el rango que se leyó y el número
    entre el que se divide.

    El divisor cuenta **días corridos, no días abiertos**: los domingos, que la
    farmacia cierra, entran como días en los que el anaquel tampoco se vació.
    Es lo que hace que "cuántos días duraría" se pueda leer como días de
    calendario, que es como el encargado los va a contar frente al anaquel.

    El sesgo que queda es conocido y va hacia donde debe: si en los primeros
    días de la ventana no hubo ni una venta en toda la farmacia, el rango se
    encoge, el ritmo sube y la cobertura baja. Errar hacia "más urgente" sube
    un renglón en una lista donde nada se filtra; errar al revés lo escondería
    al fondo.
    """
    if not ventas:
        return {}

    fechas = [v.fecha for v in ventas]
    dias = (max(fechas) - min(fechas)).days + 1
    return {
        producto_id: piezas / dias
        for producto_id, piezas in _piezas_por_producto(ventas).items()
    }


def _renglon(
    producto_id: int,
    piezas: float,
    producto: Producto | None,
    ritmo: float,
    reglas: ReglasDeClasificacion,
) -> Renglon:
    """Un renglón, esté o no el producto en el catálogo.

    El producto huérfano **entra igual**. Tronar sería peor: un solo artículo
    que `dim_producto` no conoce dejaría a la farmacia sin pedido del día, y
    esconderlo sería reponer de menos sin que nadie lo note. Así el renglón se
    ve, dice cuál es por su `producto_id` —que es con lo que se busca en
    SICAR— y se cuenta aparte.

    La clasificación de un huérfano es `sin clasificar` por lo mismo: sin
    catálogo no hay anaquel ni categoría que leer, y adivinar "será
    medicamento" lo metería a la vista de farmacia sin una sola evidencia.

    La clave se queda **vacía a propósito**. Es el EAN, lo único que empareja
    con el catálogo de un proveedor; inventar una haría que la comparación de
    precios emparejara con cualquier cosa, que es justo el tropiezo de Marlowe
    con la caja de 60. La existencia se queda en `None` por la misma razón: un
    cero inventado no es un dato faltante, es un dato falso.
    """
    existencia = producto.existencia if producto else None
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
        existencia=existencia,
        dias_de_cobertura=_dias_de_cobertura(existencia, ritmo),
        clasificacion=(
            clasificar(producto.anaquel, producto.categoria, reglas)
            if producto
            else SIN_CLASIFICAR
        ),
    )


def _dias_de_cobertura(existencia: float | None, ritmo: float) -> float | None:
    """Cuántos días duraría la existencia actual al ritmo al que se ha vendido.

    La definición es la de `CONTEXT.md` y el glosario manda. Sirve para ordenar
    la lista por urgencia, **no para decidir si un producto entra a ella**.

    Tres casos que no son el mismo y que sería fácil aplanar en un cero:

    - **No se sabe qué queda** (`existencia is None`, producto fuera del
      catálogo) → `None`. Regla 4 de CLAUDE.md.
    - **No se vendió en la ventana del ritmo** → `None`, no cero: hay
      mercancía y no se está moviendo, que es lo contrario de urgente.
      Dividir entre cero daría infinito, que ni se serializa a JSON ni se lee
      en una pantalla.
    - **Agotado** (existencia cero o negativa, que SICAR permite cuando se
      vendió más de lo que el inventario decía) → `0.0` de verdad: no dura
      nada. Se fija en cero en vez de dejar salir un negativo, porque "-1.5
      días" no significa nada frente al anaquel.
    """
    if existencia is None:
        return None
    if existencia <= 0:
        return 0.0
    if ritmo <= 0:
        return None
    return round(existencia / ritmo, _DECIMALES_DE_COBERTURA)


def _urgencia(renglon: Renglon) -> tuple[int, float, str, int]:
    """La llave del orden: agotado primero, luego menor cobertura, sin empates vivos.

    Tres grupos, y el tercero es el que hay que explicar: lo que no tiene
    cobertura calculable va al **final**. Un "no sé" arriba se leería como una
    urgencia que nadie midió y empujaría hacia abajo lo que de verdad se
    acabó; abajo sigue estando en la lista, marcado y contado, que es lo que
    la regla 4 de CLAUDE.md exige. Y nada se filtra: el de 900 días de
    cobertura también aparece, solo que hasta el fondo.

    El agotado es su propio grupo y no "cobertura cero" por un caso real: un
    producto agotado que además no se vendió en la ventana del ritmo no tiene
    cobertura calculable, y aun así sigue siendo lo más urgente de la lista.

    Los dos últimos elementos son el desempate, y son deterministas a
    propósito: la descripción y, si dos productos se llaman igual, el
    `producto_id`, que es único. Dos corridas con los mismos datos dan el mismo
    orden aunque el almacén devuelva las filas al revés.
    """
    if renglon.esta_agotado:
        grupo, cobertura = 0, 0.0
    elif renglon.dias_de_cobertura is not None:
        grupo, cobertura = 1, renglon.dias_de_cobertura
    else:
        grupo, cobertura = 2, 0.0
    return (grupo, cobertura, renglon.descripcion.casefold(), renglon.producto_id)


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
