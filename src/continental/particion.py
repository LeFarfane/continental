"""Elegir proveedor por renglón y partir la lista en pedidos. Funciones puras.

El paso donde la comparación se vuelve una decisión (ticket 20). No abre una
conexión, no llama a Doyle, no mira el reloj y no lee un archivo: recibe los
renglones guardados, sus comparaciones ya hechas (`comparacion.comparar`), sus
precios congelados y el puente hacia SICAR (`proveedores.puente_configurado`),
y contesta tres cosas:

1. **a quién se le pide cada renglón** —lo que una persona decidió, y si nadie
   decidió, lo que el sistema sugiere—;
2. **en cuántos pedidos se parte la lista**, uno por proveedor;
3. **cuánto cuesta cada pedido**, o por qué no se puede saber.

## La sugerencia NO se guarda, y la decisión SÍ

Es la misma pregunta del ticket 11 —`cantidad_propuesta` frente a
`cantidad_final`— y **la respuesta es distinta a propósito**:

- `cantidad_propuesta` se guarda porque **no se puede recalcular**. Sale de las
  ventas de una ventana que ya pasó, con un catálogo que ya cambió; releerla
  mañana daría otro número y la lista dejaría de poder explicarse.
- El proveedor sugerido **sí se recalcula**, y exactamente igual: sale de
  `comparacion.elegir_ganador`, que es una función pura sobre
  `pedidos.precio_de_proveedor`, que **solo crece** (ADR 0004). Guardarlo sería
  una segunda copia del mismo hecho, y dos copias de un hecho se separan.

Y hay algo más fuerte que el ahorro: **una sugerencia guardada envejece sin
avisar**. Si a las 8 la sugerencia era NADRO, a las 9 llega un precio de LEVIC
más barato y la columna sigue diciendo NADRO, la pantalla mostraría como
"sugerido" algo que ya no lo es — y nadie podría distinguir esa cifra vieja de
una decisión que alguien tomó. Lo que se guarda es **solo lo que una persona
decidió**, que es lo que no se puede deducir de ningún otro dato.

Así que `renglon.proveedor_elegido IS NULL` quiere decir exactamente *"nadie
eligió"*, igual que `cantidad_final IS NULL` quiere decir *"nadie la tocó"*. La
forma es la misma —columna nullable, sin DEFAULT, con su firma pareada por un
CHECK—; lo que cambia es de cuál de las dos cifras se guarda.

## El empate no se desempata

`comparacion.Ganador.proveedores` es una **tupla** porque un empate son dos
opciones, y su docstring ya lo dejó decidido: *elegir uno por orden alfabético
diría "éste es el más barato" sobre una decisión que el sistema no tomó*. Aquí
se respeta: con empate **no hay sugerencia**, hay un aviso con los empatados a
la vista y el renglón espera a que alguien decida. Es literal el ticket: *la
persona decide; hay razones que el sistema no ve —mínimo de pedido, días de
entrega, crédito con cada proveedor—*.

## Un renglón sin precio de ese proveedor se pide igual

La quinta casilla, y es la que más fácil se hace mal. Que LEVIC no haya dado
precio **no es una razón para no pedirle**: el encargado puede tener mínimo de
pedido con LEVIC, o crédito, o el producto puede estar en su catálogo aunque el
portal no lo haya dicho hoy. El renglón entra al pedido, con su cantidad, y
marcado como **precio desconocido** —nunca un cero, nunca un vacío (regla 4 de
`CLAUDE.md`)—.

Lo que eso le hace al total está en `PedidoPorArmar.total_sin_iva`: **`None`, y
jamás la suma de lo que sí se sabe**. Un total parcial presentado como total es
un número que se compara contra la factura del proveedor y no cuadra, y nadie
sabe por qué. El parcial viaja aparte, con el conteo de cuántos renglones le
faltan, que es información honesta.

## `Decimal` de punta a punta

Igual que en `comparacion.py`, y por lo mismo: en coma flotante `0.1 * 3` es
`0.30000000000000004` y el total de un pedido deja de cuadrar por centavos que
nadie puede explicar. Entra `Decimal` desde `precios.precio_a_numero`, se
multiplica y se suma en `Decimal`, y al navegador sale como **cadena**.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from continental.almacenamiento import PrecioDeProveedor, RenglonGuardado
from continental.comparacion import (
    ORDEN_DE_LA_FILA,
    Ahorro,
    Comparacion,
    Ganador,
)
from continental.precios import explicacion_del_motivo, nombre_del_proveedor
from continental.proveedores import CON_PUENTE, SIN_PUENTE, id_en_sicar

#: Una comparación de un renglón al que nadie le consultó el precio. Se arma
#: una sola vez y se reusa: es inmutable (`frozen=True`) y aparece una vez por
#: renglón sin lecturas, que en una lista recién armada son todos.
SIN_COMPARACION = Comparacion(ganador=Ganador(), ahorro=Ahorro())

#: Los dos decimales de `numeric(12,2)`, los mismos de `comparacion._CENTAVOS`.
_CENTAVOS = Decimal("0.01")


# ------------------------------------------------ por qué a veces no hay a quién

#: Nadie eligió y el sistema no tiene con qué sugerir: el renglón no se ha
#: consultado, o ninguno dio precio, o ninguno de los que lo dieron lo tiene.
#: El motivo fino ya viaja en `Comparacion.ganador.motivo` y no se repite aquí.
NADIE_A_QUIEN_PEDIRLE = "todavía no hay a quién pedírselo"

#: Hay dos o más igual de baratos. **El sistema no desempata**: enseña a los
#: empatados y espera. Un desempate por orden alfabético sería una decisión que
#: nadie tomó, presentada como cálculo.
HAY_EMPATE = "hay empate: la persona decide"


# ----------------------------------------------- por qué una línea no tiene precio

#: Se le preguntó a ese proveedor y no dio precio. El motivo fino —la sesión
#: caducada, el portal caído, "no está en ese catálogo"— viaja al lado.
SIN_PRECIO_DE_ESE_PROVEEDOR = "precio desconocido"

#: Ni siquiera se le preguntó a ese proveedor por este renglón. Distinto del
#: anterior con todas sus letras: uno se arregla mirando el motivo y el otro
#: apretando el botón.
SIN_CONSULTARLE = "no se le ha consultado el precio a ese proveedor"


# ------------------------------------------------------------------- los datos


@dataclass(frozen=True, slots=True)
class Eleccion:
    """A quién se le pide este renglón, y **quién lo decidió**.

    `es_decision` es la mitad que importa y por eso no se deduce comparando
    `proveedor` con `sugerido`: una persona que confirma la sugerencia del
    sistema **está decidiendo**, igual que quien confirma la cantidad propuesta
    del ticket 11. Deducirlo de que las dos cadenas coincidan borraría
    exactamente esa decisión, que es la que después explica por qué se le
    compró a LEVIC habiendo NADRO más barato.

    `sugerido` viaja **siempre** que el sistema tenga una, aunque haya decisión:
    es lo que deja ver en la pantalla "eligió VICMA; el sistema sugería NADRO",
    que es el par de cifras que hace auditable la elección.

    `motivo` solo viene cuando no hay a quién pedirle, y viene siempre que no lo
    hay: una casilla vacía sin explicación se lee como un error de la pantalla.
    """

    renglon_id: int
    proveedor: str | None = None
    es_decision: bool = False
    elegido_por: str | None = None
    sugerido: str | None = None
    certeza: str | None = None
    empatados: tuple[str, ...] = ()
    motivo: str | None = None

    @property
    def hay(self) -> bool:
        """Si este renglón tiene a quién pedírsele."""
        return self.proveedor is not None

    @property
    def es_sugerencia(self) -> bool:
        """Si lo que hay es lo que el sistema propone y nadie ha confirmado."""
        return self.hay and not self.es_decision

    @property
    def difiere_de_la_sugerencia(self) -> bool:
        """Si la persona eligió a alguien distinto del que el sistema sugería.

        Separado de `es_decision` por la misma razón que
        `RenglonGuardado.difiere_de_la_propuesta` lo está de `fue_ajustada`:
        escribir "el sistema sugería NADRO" al lado de un NADRO elegido es
        ruido, y el ruido se deja de leer justo antes del renglón donde la
        diferencia importaba.
        """
        return (
            self.es_decision
            and self.sugerido is not None
            and self.proveedor != self.sugerido
        )

    @property
    def nombre(self) -> str:
        """Cómo se escribe el proveedor elegido, según el glosario."""
        return "" if self.proveedor is None else nombre_del_proveedor(self.proveedor)


@dataclass(frozen=True, slots=True)
class Linea:
    """Un renglón dentro de un pedido: cuántas piezas y a cuánto, si se sabe.

    `precio is None` **siempre viene con `motivo`**, igual que en
    `comparacion.Casilla` y en `pedidos.precio_de_proveedor`: un `None` mudo se
    ve idéntico a un cero en la pantalla, y aquí el cero miente dos veces —haría
    creer que el producto es gratis y que el total del pedido es el total—.

    La línea **existe igual sin precio**, que es la quinta casilla del ticket:
    *un renglón sin precio de ese proveedor se puede pedir igual, marcado como
    precio desconocido*.
    """

    renglon_id: int
    descripcion: str
    cantidad: int
    precio: Decimal | None = None
    motivo: str | None = None
    detalle: str | None = None

    @property
    def tiene_precio(self) -> bool:
        return self.precio is not None

    @property
    def importe(self) -> Decimal | None:
        """`cantidad × precio`, o `None` si no hay precio. **Nunca cero.**"""
        if self.precio is None:
            return None
        return (self.precio * self.cantidad).quantize(_CENTAVOS)


@dataclass(frozen=True, slots=True)
class PedidoPorArmar:
    """Lo que se le va a pedir a **un** proveedor, antes de tener fila.

    Es el dato que `almacenamiento.guardar_la_particion` escribe. Se calcula
    aquí —puro, probado sin Postgres— y no dentro del `INSERT`, por la misma
    razón que `comparacion.py` existe: la regla con la que se decide cuánto
    cuesta un pedido no puede vivir en un `SELECT` que solo se puede probar
    levantando una base.

    `proveedor_id` es `None` cuando el puente hacia SICAR no existe para ese
    proveedor, **y el pedido se arma igual**: hoy es el caso de QuePharma,
    medido contra `marts.dim_proveedor` el 2026-09-19. Ver `proveedores.py`.
    """

    proveedor: str
    proveedor_id: int | None = None
    lineas: tuple[Linea, ...] = ()

    @property
    def nombre(self) -> str:
        return nombre_del_proveedor(self.proveedor)

    @property
    def tiene_puente(self) -> bool:
        """Si a este proveedor le corresponde un `pro_id` de SICAR."""
        return self.proveedor_id is not None

    @property
    def renglones(self) -> int:
        return len(self.lineas)

    @property
    def piezas(self) -> int:
        """Cuántas piezas se le piden en total. Enteras: no hay granel al pedir."""
        return sum(linea.cantidad for linea in self.lineas)

    @property
    def sin_precio(self) -> int:
        """Cuántas líneas van con precio desconocido."""
        return sum(1 for linea in self.lineas if not linea.tiene_precio)

    @property
    def parcial_sin_iva(self) -> Decimal:
        """Lo que suman **las líneas que sí tienen precio**.

        No es el total y no se presenta como tal. Es lo que permite escribir
        "$1,234.50 de 8 renglones; faltan 2 por precio" en vez de un hueco mudo:
        el dato que hay sigue a la vista (regla 4 de `CLAUDE.md`).
        """
        total = sum(
            (linea.importe for linea in self.lineas if linea.importe is not None),
            Decimal("0"),
        )
        return total.quantize(_CENTAVOS)

    @property
    def total_sin_iva(self) -> Decimal | None:
        """Lo que cuesta este pedido, o `None` si no se puede saber.

        **`None` en cuanto una sola línea no tenga precio**, y jamás la suma de
        las demás. `pedidos.pedido.total_sin_iva` es nullable a propósito y su
        comentario lo dice: *NULL = todavía no se sabe, nunca cero*. Un total
        parcial escrito en esa columna es peor que un hueco, porque se compara
        contra la factura del proveedor, no cuadra, y nadie sabe si falta
        mercancía o falta un precio.

        **Un pedido sin líneas también da `None`**, y no `0.00`. Un pedido vacío
        no cuesta nada porque no tiene nada, no porque sea gratis — y `0.00` es
        justo la cifra que pasaría desapercibida en una lista de totales.
        """
        if not self.lineas or self.sin_precio:
            return None
        return self.parcial_sin_iva


@dataclass(frozen=True, slots=True)
class Particion:
    """En cuántos pedidos se parte la lista, y qué se queda fuera.

    `sin_proveedor` son los renglones de trabajo a los que todavía no hay a
    quién pedírseles. **No desaparecen y no se reparten a nadie**: se cuentan y
    se dicen, igual que los renglones sin comparar del ticket 15. Un renglón que
    se cayera de la partición en silencio es mercancía que va a faltar sin que
    nadie se entere, que es el mismo error que `CONTEXT.md` prohíbe para los
    productos sin anaquel.
    """

    pedidos: tuple[PedidoPorArmar, ...] = ()
    sin_proveedor: tuple[Eleccion, ...] = field(default_factory=tuple)

    @property
    def hay(self) -> bool:
        return bool(self.pedidos)

    @property
    def proveedores(self) -> tuple[str, ...]:
        return tuple(pedido.proveedor for pedido in self.pedidos)

    @property
    def renglones_repartidos(self) -> int:
        return sum(pedido.renglones for pedido in self.pedidos)

    @property
    def sin_puente(self) -> tuple[str, ...]:
        """Los proveedores de esta partición que SICAR no conoce, en orden.

        Se dice una vez arriba y no renglón por renglón: es una propiedad de la
        instalación, no del producto.
        """
        return tuple(p.proveedor for p in self.pedidos if not p.tiene_puente)


# --------------------------------------------------------------- las funciones


def sugerir(comparacion: Comparacion) -> tuple[str | None, str | None, tuple[str, ...]]:
    """Qué proveedor sugiere el sistema: `(proveedor, certeza, empatados)`.

    Es `comparacion.elegir_ganador` traducido a "a quién le compro", y la
    traducción tiene una sola regla propia: **con empate no hay sugerencia**.

    | El ganador | Qué sale |
    |---|---|
    | uno solo | ese proveedor, con la `certeza` del ganador |
    | dos o más igual de baratos | ninguno, y los empatados a la vista |
    | ninguno | ninguno, y el motivo vive en `comparacion.ganador.motivo` |

    La `certeza` viaja tal cual —"el más barato con existencia", "el único que
    contestó"— porque es lo que dice **qué se está afirmando** de la sugerencia,
    y el ticket 15 ya pagó por que esa frase no se elija en el JavaScript.
    """
    ganador = comparacion.ganador
    if len(ganador.proveedores) == 1:
        return ganador.proveedores[0], ganador.certeza, ()
    if len(ganador.proveedores) > 1:
        return None, ganador.certeza, ganador.proveedores
    return None, None, ()


def elegir(renglon: RenglonGuardado, comparacion: Comparacion) -> Eleccion:
    """A quién se le pide este renglón: lo decidido, y si no, lo sugerido.

    **La decisión gana siempre**, incluso sobre una sugerencia más barata que
    llegó después. Es literal el ticket: *la persona decide; hay razones que el
    sistema no ve —mínimo de pedido, días de entrega, crédito con cada
    proveedor—*. Lo que el sistema sigue haciendo es **decirlo**: la sugerencia
    viaja al lado y la pantalla escribe las dos, que es lo que permite mirar una
    elección cara y preguntar por qué.

    Una decisión NO se revisa contra la comparación: se puede elegir a un
    proveedor que no dio precio, o al que nadie le preguntó. Eso es la quinta
    casilla del ticket y no un descuido — el renglón entra al pedido con
    `precio desconocido`, que es lo que `armar_lineas` resuelve.
    """
    sugerido, certeza, empatados = sugerir(comparacion)

    if renglon.proveedor_elegido is not None:
        return Eleccion(
            renglon_id=renglon.renglon_id,
            proveedor=renglon.proveedor_elegido,
            es_decision=True,
            elegido_por=renglon.elegido_por,
            sugerido=sugerido,
            certeza=certeza,
            empatados=empatados,
        )

    if sugerido is not None:
        return Eleccion(
            renglon_id=renglon.renglon_id,
            proveedor=sugerido,
            es_decision=False,
            sugerido=sugerido,
            certeza=certeza,
        )

    return Eleccion(
        renglon_id=renglon.renglon_id,
        empatados=empatados,
        certeza=certeza,
        motivo=HAY_EMPATE if empatados else NADIE_A_QUIEN_PEDIRLE,
    )


def _linea(
    renglon: RenglonGuardado,
    proveedor: str,
    lecturas: Sequence[PrecioDeProveedor],
) -> Linea:
    """El renglón como línea de pedido, con el precio de **ese** proveedor.

    La cantidad es `cantidad_a_pedir` —la corrección de la persona si la hubo, y
    si no la propuesta del sistema—. Esa regla no se repite aquí: vive en
    `RenglonGuardado` y una regla escrita dos veces se cambia una sola.
    """
    # `precios_del_renglon` y `precios_de_la_lista` ya devuelven **la más
    # reciente de cada proveedor** (el `DISTINCT ON` de `_LEER_PRECIOS`, y
    # `ultimo_por_proveedor` en el doble). Así que aquí se busca y no se vuelve
    # a desempatar: repetir esa regla sería escribirla dos veces para cambiarla
    # una sola. Es el mismo `next(...)` con el que `comparacion.calcular_ahorro`
    # busca a la referencia.
    lectura = next((l for l in lecturas if l.proveedor == proveedor), None)

    if lectura is None:
        return Linea(
            renglon_id=renglon.renglon_id,
            descripcion=renglon.propuesto.descripcion,
            cantidad=renglon.cantidad_a_pedir,
            motivo=SIN_CONSULTARLE,
        )

    if lectura.precio is None:
        return Linea(
            renglon_id=renglon.renglon_id,
            descripcion=renglon.propuesto.descripcion,
            cantidad=renglon.cantidad_a_pedir,
            motivo=SIN_PRECIO_DE_ESE_PROVEEDOR,
            detalle=explicacion_del_motivo(lectura.motivo),
        )

    return Linea(
        renglon_id=renglon.renglon_id,
        descripcion=renglon.propuesto.descripcion,
        cantidad=renglon.cantidad_a_pedir,
        precio=lectura.precio,
    )


def partir(
    renglones: Sequence[RenglonGuardado],
    comparaciones: Mapping[int, Comparacion],
    precios: Mapping[int, Sequence[PrecioDeProveedor]],
    puente: Mapping[str, int],
) -> Particion:
    """La lista de trabajo → un pedido por proveedor, más lo que se queda fuera.

    **Quién entra**: los renglones que se le pasen, y quien llama ya filtró.
    Lo que la ruta le pasa es `PedidoSugeridoGuardado.de_trabajo` —los
    descartados ya se atendieron, alguien los miró y decidió no pedirlos— y los
    `en tránsito` no vuelven a repartirse porque el `UPDATE` que asigna el
    pedido lleva `estado = 'abierto'` en su `WHERE`.

    **El orden de los pedidos es el de `ORDEN_DE_LA_FILA`** —la referencia
    primero— y dentro de cada uno, el de la lista. Un orden que dependiera de
    cuánto suma cada pedido cambiaría de sitio las columnas entre dos cargas de
    la misma pantalla, que es lo que `comparacion.ORDEN_DE_LA_FILA` ya decidió
    para la fila de precios.

    Un proveedor sin `pro_id` de SICAR **sí** arma su pedido, con
    `proveedor_id = None`. El porqué está en `proveedores.py`; en corto: se le
    pide a quien se le preguntó el precio, y que la farmacia nunca le haya
    comprado no es una razón para no empezar hoy.
    """
    por_proveedor: dict[str, list[Linea]] = {}
    fuera: list[Eleccion] = []

    for renglon in renglones:
        # Un renglón que no está en `comparaciones` es uno que nadie consultó:
        # entra con la comparación vacía y no se salta. Saltarlo lo dejaría
        # fuera de `sin_proveedor` y de la partición a la vez, o sea invisible.
        comparacion = comparaciones.get(renglon.renglon_id, SIN_COMPARACION)
        eleccion = elegir(renglon, comparacion)
        if not eleccion.hay or eleccion.proveedor is None:
            fuera.append(eleccion)
            continue
        por_proveedor.setdefault(eleccion.proveedor, []).append(
            _linea(renglon, eleccion.proveedor, precios.get(renglon.renglon_id, ()))
        )

    return Particion(
        pedidos=tuple(
            PedidoPorArmar(
                proveedor=proveedor,
                proveedor_id=id_en_sicar(proveedor, puente),
                lineas=tuple(por_proveedor[proveedor]),
            )
            for proveedor in _orden(por_proveedor)
        ),
        sin_proveedor=tuple(fuera),
    )


def _orden(por_proveedor: Mapping[str, object]) -> tuple[str, ...]:
    """Los del glosario en su orden fijo, y detrás cualquier otro.

    Mismo criterio que `comparacion._orden_de_la_fila`: nada se cae de la
    pantalla por no reconocerse (regla 4 de `CLAUDE.md`). Un proveedor que Doyle
    estrene y que el mapa de nombres todavía no conozca sale al final, con su
    clave por nombre, en vez de desaparecer.
    """
    conocidos = tuple(c for c in ORDEN_DE_LA_FILA if c in por_proveedor)
    extras = tuple(sorted(set(por_proveedor) - set(ORDEN_DE_LA_FILA)))
    return conocidos + extras


# ---------------------------------------------------------------- al navegador


def _cadena(valor: Decimal | None) -> str | None:
    """Un `Decimal` al navegador: **cadena** o `None`, jamás un número de JSON.

    El JSON de JavaScript solo tiene `double`. Es la misma razón y la misma
    función que `comparacion._cadena`.
    """
    return None if valor is None else str(valor)


def eleccion_como_json(eleccion: Eleccion) -> dict:
    """La elección como la pantalla la lee. Ninguna regla se recalcula allá."""
    return {
        # El id viaja aunque la elección ya cuelgue de su renglón, porque
        # `Particion.sin_proveedor` es una lista suelta: sin él, la pantalla
        # podría CONTAR los renglones que se quedan fuera pero no señalarlos.
        "renglon_id": eleccion.renglon_id,
        "proveedor": eleccion.proveedor,
        "nombre": eleccion.nombre,
        "hay": eleccion.hay,
        # Los dos ejes por separado, como la certeza del ganador: si es una
        # persona quien lo decidió, y si esa persona eligió distinto de lo que
        # el sistema sugería. La pantalla necesita los dos para saber qué
        # escribir y con qué color.
        "es_decision": eleccion.es_decision,
        "es_sugerencia": eleccion.es_sugerencia,
        "difiere_de_la_sugerencia": eleccion.difiere_de_la_sugerencia,
        "elegido_por": eleccion.elegido_por,
        "sugerido": eleccion.sugerido,
        "nombre_sugerido": (
            None
            if eleccion.sugerido is None
            else nombre_del_proveedor(eleccion.sugerido)
        ),
        "certeza": eleccion.certeza,
        "empatados": list(eleccion.empatados),
        "nombres_empatados": [nombre_del_proveedor(p) for p in eleccion.empatados],
        "motivo": eleccion.motivo,
    }


def pedido_por_armar_como_json(pedido: PedidoPorArmar) -> dict:
    """Un pedido de la partición como la pantalla lo lee, con su total y su hueco."""
    return {
        "proveedor": pedido.proveedor,
        "nombre": pedido.nombre,
        "proveedor_id": pedido.proveedor_id,
        "tiene_puente": pedido.tiene_puente,
        "estado_del_puente": CON_PUENTE if pedido.tiene_puente else SIN_PUENTE,
        "renglones": pedido.renglones,
        "piezas": pedido.piezas,
        "sin_precio": pedido.sin_precio,
        # El total y el parcial viajan los DOS, y no uno en lugar del otro. El
        # total es `null` en cuanto falte un precio —nunca la suma de lo demás—
        # y el parcial es lo que sí se sabe, con el conteo de lo que falta al
        # lado. Enseñar solo el total dejaría la pantalla muda sobre dinero que
        # sí está calculado; enseñar solo el parcial lo presentaría como total.
        "total_sin_iva": _cadena(pedido.total_sin_iva),
        "parcial_sin_iva": _cadena(pedido.parcial_sin_iva),
        "hay_total": pedido.total_sin_iva is not None,
        "lineas": [
            {
                "renglon_id": linea.renglon_id,
                "descripcion": linea.descripcion,
                "cantidad": linea.cantidad,
                "precio": _cadena(linea.precio),
                "importe": _cadena(linea.importe),
                "tiene_precio": linea.tiene_precio,
                "motivo": linea.motivo,
                "detalle": linea.detalle,
            }
            for linea in pedido.lineas
        ],
    }


def particion_como_json(particion: Particion) -> dict:
    """La partición entera como la pantalla la lee, con lo que se queda fuera."""
    return {
        "hay": particion.hay,
        "pedidos": [pedido_por_armar_como_json(p) for p in particion.pedidos],
        "renglones_repartidos": particion.renglones_repartidos,
        "sin_puente": list(particion.sin_puente),
        # Los que no se reparten se CUENTAN y se DICEN. Un renglón que se caiga
        # de la partición en silencio es mercancía que va a faltar sin que nadie
        # se entere.
        "sin_proveedor": [eleccion_como_json(e) for e in particion.sin_proveedor],
        "cuantos_sin_proveedor": len(particion.sin_proveedor),
    }
