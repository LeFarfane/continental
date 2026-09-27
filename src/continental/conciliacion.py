"""Conciliación diaria: lo que la lista propuso contra lo que de verdad se
compró (ticket de la revisión de arquitectura, 2026-09-27, ADR pendiente de
aprobar — el dueño lo redacta como el ADR 0021).

**Funciones puras y nada más.** Reciben lo que ya se leyó —los renglones de
una lista, las compras del almacén, el calendario y el puente de proveedores—
y devuelven la conciliación con sus tres bloques. No abren una conexión, no
llaman a Doyle y no miran el reloj: el `ancla` —el último día con datos
frescos— entra por argumento, igual que en `recepcion.py` y `transito.py`.

## Por qué existe

Medido el 2026-09-27 contra la base real: **883 renglones creados, 0
pedidos, 0 enviados, 0 en tránsito, 0 recibidos.** La encargada pide directo
en el portal de NADRO todos los días, sin pasar por Continental. El dueño
decidió: seguir suponiendo que alguien va a marcar «Enviar», pero con
tolerancia a que se le olvide uno o dos días, deduciendo lo que pasó a partir
de las compras que sí se dan de alta en SICAR.

## La distinción que manda sobre todo este módulo

Son dos preguntas distintas y solo una tiene respuesta (ADR 0002):

- **"¿Lo pidió?"** — no se puede saber. SICAR no tiene pedidos ni órdenes.
- **"¿Llegó?"** — se sabe con certeza. La compra ES la llegada, con
  proveedor, cantidad, fecha y `precio_unitario_pagado`.

Este módulo se ancla en lo segundo y nunca infiere lo primero: no dice "la
encargada sí lo pidió a NADRO", dice "SICAR tiene una compra a NADRO de este
producto, después de que se propuso, y con eso el renglón se puede dar por
recibido".

## Los tres bloques

1. **`coincidencias`** — lo propuesto que sí se compró: con a quién, cuánto y
   a qué precio. Cada una trae la evidencia (`LineaDeCompra`) y si se puede
   crear un pedido retroactivo con ella (`accionable`) — hace falta que la
   compra tenga un solo proveedor y que ese proveedor tenga clave de Doyle
   (`proveedores.puente_configurado`, invertido).
2. **`sin_comprar`** — lo propuesto que no se compró, con **tres motivos que
   no se confunden entre sí** (la trampa que este módulo existe para no
   redescubrir):
   - `MOTIVO_NUNCA_EN_COMPRAS` — este producto nunca ha aparecido en una
     compra de SICAR (606 de 3,429, 17.7%, medido sobre el respaldo del
     2026-07-27): esto no se va a disparar jamás, y decirlo distinto de "no
     se compró" es lo que impide listarlo como pendiente para siempre.
   - `MOTIVO_DATOS_NO_HAN_LLEGADO` — la ventana de tolerancia todavía no se
     cumplió (el respaldo llega hasta 2.5 días tarde): un día reciente sin
     compras no es un día sin compras.
   - `MOTIVO_NO_COMPRADO` — la ventana ya se cumplió y sigue sin aparecer
     una compra: aquí sí se afirma que no se compró.
3. **`compradas_sin_proponer`** — lo comprado que nadie propuso. Es normal,
   no un error, y así se dice. Incluye el caso de un renglón que SÍ se
   propuso y una persona **descartó**, y que aun así se compró: no es "nadie
   lo propuso" en sentido estricto, así que se marca aparte (`fue_descartado`)
   en vez de mentir por omisión.

## La ventana de tolerancia

**Tres días hábiles, configurable, nunca escrita en el código**
(`config/continental.yml`, `pedido.tolerancia_dias_habiles`, leída por
`almacenamiento.tolerancia_dias_habiles_configurada`). **Días hábiles y no
corridos**: el respaldo llega hasta 2.5 días tarde y una ventana de días
corridos se quedaría corta justo los lunes. `marts.dim_fecha` dice qué día es
hábil — `es_cerrado` **solo** marca domingos; los festivos están en
`es_festivo_oficial` (la trampa del ticket de "no domingos ni festivos",
2026-09-27) — y por eso `fecha_limite` recibe las dos banderas ya resueltas
en un `DiaCalendario`, nunca solo `es_cerrado`.

## Lo que NO hace este módulo, a propósito

No decide qué compra corresponde a qué renglón cuando el mismo producto se
compró **a más de un proveedor** dentro de la ventana: no hay con qué
elegir, y elegir el primero en silencio sería exactamente la falla que el
ADR 0014 ya evitó una vez con "una compra confirma un solo renglón". Esas
compras se cuentan en `compradas_sin_proponer`, marcadas `ambiguo`, y una
persona las revisa a mano — no hay botón de un clic para ellas.

No escribe nada. La confirmación por lote —el único clic que sí escribe— es
`almacenamiento.AlmacenamientoDelPedido.confirmar_la_conciliacion`, que
recibe exactamente las `Coincidencia.accionable` que una persona vio y
aceptó, y nunca se dispara sola.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from continental.almacen import DiaCalendario, LineaDeCompra
from continental.almacenamiento import RENGLON_ABIERTO, RenglonGuardado
from continental.comparacion import Ganador, elegir_ganador

if TYPE_CHECKING:  # pragma: no cover - solo para los tipos
    from continental.almacenamiento import PrecioDeProveedor

# ------------------------------------------------------------ los motivos de "no comprado"
#
# Tres, y no una "pendiente" genérica, porque cada uno dice algo distinto y
# se confunden fácil: el primero nunca se resuelve solo, el segundo se
# resuelve con tiempo, y el tercero es la afirmación de verdad.

#: Este producto nunca ha aparecido en una compra de SICAR (606 de 3,429,
#: 17.7%, medido sobre el respaldo del 2026-07-27): entra por otra vía y no
#: deja rastro. Nunca va a tener conciliación, y decirlo es lo que impide que
#: se quede en la lista de "no comprado" para siempre.
MOTIVO_NUNCA_EN_COMPRAS = "nunca en compras"

#: La ventana de tolerancia todavía no se cumplió: el respaldo de SICAR llega
#: hasta 2.5 días tarde (CLAUDE.md), así que un día reciente sin compras no es
#: un día sin compras — es un día cuyos datos no han llegado.
MOTIVO_DATOS_NO_HAN_LLEGADO = "datos no han llegado"

#: La ventana ya se cumplió y sigue sin aparecer una compra que empareje.
#: Aquí sí se afirma que no se compró.
MOTIVO_NO_COMPRADO = "no comprado"

#: Los tres, en el orden en que conviene decirlos: primero lo que nunca se va
#: a resolver solo, luego lo que todavía puede resolverse, al final lo que ya
#: es definitivo.
MOTIVOS_SIN_COMPRAR: tuple[str, ...] = (
    MOTIVO_NUNCA_EN_COMPRAS,
    MOTIVO_DATOS_NO_HAN_LLEGADO,
    MOTIVO_NO_COMPRADO,
)


# --------------------------------------------------------- la ventana de tolerancia


def fecha_limite(
    dia: dt.date,
    tolerancia_dias_habiles: int,
    calendario: Mapping[dt.date, DiaCalendario],
) -> dt.date:
    """`dia` + N días **hábiles**, saltando domingo y festivo oficial.

    `calendario` es un mapa `{fecha: DiaCalendario}` de los días posteriores a
    `dia` — lo que trae `almacen.LecturaDelAlmacen.dias_entre`, ya convertido
    con `calendario_desde_lista`—. **Un día que no está en el mapa se trata
    como hábil**, igual que `AlmacenPostgres.dia` cuando la fecha cae fuera del
    rango 2020-2032 de `dim_fecha`: no se afirma "domingo" ni "festivo" sin
    dato (regla 4 de `CLAUDE.md`).

    Truena si `tolerancia_dias_habiles` no es al menos uno: cero días de
    tolerancia no es "sin tolerancia", es una pregunta sin sentido —la
    ventana tendría que incluir el día mismo de la lista sin dar ni un solo
    día de margen, que ya lo cubre no tener conciliación—.
    """
    if tolerancia_dias_habiles < 1:
        raise ValueError(
            "tolerancia_dias_habiles tiene que ser 1 o más: "
            f"{tolerancia_dias_habiles!r} no dice nada."
        )
    cursor = dia
    contados = 0
    while contados < tolerancia_dias_habiles:
        cursor += dt.timedelta(days=1)
        fila = calendario.get(cursor)
        if fila is None or not fila.es_dia_sin_lista:
            contados += 1
    return cursor


def calendario_desde_lista(dias: Iterable[DiaCalendario]) -> dict[dt.date, DiaCalendario]:
    """`almacen.dias_entre(...)` → el mapa que `fecha_limite` necesita."""
    return {d.fecha: d for d in dias}


# ------------------------------------------------------------------ los datos


@dataclass(frozen=True, slots=True)
class Coincidencia:
    """Un renglón propuesto que sí se compró (bloque 1).

    `proveedor` es la clave de Doyle (`nadro`, `levic`, …), deducida del
    `proveedor_id` de SICAR de la compra a través del puente invertido
    (`proveedores.puente_configurado`). Puede ser `None`: SICAR conoce a un
    proveedor que no es de los cuatro de Doyle, y entonces no hay con qué
    escribir `pedidos.pedido.proveedor` — se cuenta igual como comprado, pero
    `accionable` sale en falso y `motivo_no_accionable` dice por qué.
    """

    renglon: RenglonGuardado
    compras: tuple[LineaDeCompra, ...]
    proveedor: str | None
    proveedor_id: int
    motivo_no_accionable: str | None = None

    @property
    def renglon_id(self) -> int:
        return self.renglon.renglon_id

    @property
    def producto_id(self) -> int:
        return self.renglon.propuesto.producto_id

    @property
    def descripcion(self) -> str:
        return self.renglon.propuesto.descripcion

    @property
    def compras_ids(self) -> tuple[int, ...]:
        return tuple(c.compra_id for c in self.compras)

    @property
    def piezas(self) -> float:
        """Cuántas piezas trae la evidencia. Tres decimales: el granel existe."""
        return round(sum(c.cantidad for c in self.compras), 3)

    @property
    def piezas_pedidas(self) -> int:
        """Lo que de verdad se le iba a pedir: la corrección de la persona, o
        la propuesta del sistema si nadie la tocó — `cantidad_a_pedir` del
        renglón, la misma regla de siempre."""
        return self.renglon.cantidad_a_pedir

    @property
    def accionable(self) -> bool:
        """Si se puede crear el pedido retroactivo con esta evidencia."""
        return self.motivo_no_accionable is None

    @property
    def importe_pagado(self) -> Decimal:
        return sum((Decimal(str(c.importe_pagado)) for c in self.compras), Decimal("0"))


@dataclass(frozen=True, slots=True)
class SinComprar:
    """Un renglón propuesto sin evidencia de compra (bloque 2), con su motivo."""

    renglon: RenglonGuardado
    motivo: str

    @property
    def renglon_id(self) -> int:
        return self.renglon.renglon_id

    @property
    def producto_id(self) -> int:
        return self.renglon.propuesto.producto_id


@dataclass(frozen=True, slots=True)
class CompraSuelta:
    """Una compra que la lista no relacionó con nada pendiente (bloque 3).

    `fue_descartado` distingue el caso de un producto que **sí** tenía
    renglón en esta lista pero una persona lo descartó: no es "nadie lo
    propuso", es "se propuso, se dijo que no, y se compró de todos modos" —
    informativo, y nunca se auto-confirma: la persona ya decidió.

    `ambiguo` marca una compra que sí empareja con un renglón `abierto`, pero
    a **más de un proveedor** dentro de la ventana: no hay con qué elegir
    cuál es la mercancía de ese renglón (ver el docstring del módulo), y una
    persona la revisa a mano.
    """

    compra: LineaDeCompra
    proveedor: str | None
    fue_descartado: bool = False
    ambiguo: bool = False


@dataclass(frozen=True, slots=True)
class Conciliacion:
    """Los tres bloques de un día, ya resueltos."""

    dia: dt.date
    limite: dt.date
    coincidencias: tuple[Coincidencia, ...] = ()
    sin_comprar: tuple[SinComprar, ...] = ()
    compradas_sin_proponer: tuple[CompraSuelta, ...] = ()

    @property
    def accionables(self) -> tuple[Coincidencia, ...]:
        """Las coincidencias que sí se pueden confirmar con un clic."""
        return tuple(c for c in self.coincidencias if c.accionable)


# ------------------------------------------------------------------ la regla


#: Los estados de un renglón que Continental **ya atendió por otra vía** —se
#: envió desde aquí, o ya se recibió, o se canceló—. La conciliación es solo
#: para lo que Continental nunca llegó a tocar: un renglón `en tránsito` ya
#: tiene su propio bloque de "probablemente recibido" (`recepcion.py`), y
#: conciliar encima sería proponer dos veces la misma pregunta con dos reglas
#: distintas.
_YA_ATENDIDOS_POR_OTRA_VIA = ("en tránsito", "recibido", "recibido parcial", "cancelado")


def conciliar(
    dia: dt.date,
    renglones: Sequence[RenglonGuardado],
    compras: Iterable[LineaDeCompra],
    *,
    puente: Mapping[str, int],
    tolerancia_dias_habiles: int,
    calendario: Mapping[dt.date, DiaCalendario],
    ancla: dt.date,
    productos_con_compras: Collection[int] | None = None,
    ya_usadas: Collection[int] = frozenset(),
) -> Conciliacion:
    """La lista de un día + las compras del almacén → los tres bloques.

    - `dia` es `PedidoSugeridoGuardado.fecha_del_pedido`: el día que la lista
      consideró, nunca el día en que se conciliaron.
    - `renglones` son los de esa lista, tal como se guardaron.
    - `compras` son las del almacén, de cualquier proveedor, **sin acotar
      todavía**: se filtran aquí por la ventana `[dia, fecha_limite]`.
    - `puente` es `proveedores.puente_configurado()`: clave de Doyle →
      `proveedor_id` de SICAR. Se invierte aquí para ir de la compra al
      proveedor.
    - `ya_usadas` son los `compra_id` que ya confirmaron algún renglón —de
      esta lista o de otra, y también los que ya sostienen una recepción
      normal (ADR 0014)—: una compra confirma un solo renglón, la misma regla
      de `recepcion.proponer`.
    - `productos_con_compras` es de qué productos SICAR ha visto compra
      **alguna vez**; `None` es "no se pudo saber" y entonces nunca se
      afirma `MOTIVO_NUNCA_EN_COMPRAS` (regla 4).

    El orden de salida es el de entrada: el de la lista.
    """
    limite = fecha_limite(dia, tolerancia_dias_habiles, calendario)
    usadas = frozenset(ya_usadas)
    en_ventana = sorted(
        (c for c in compras if dia <= c.fecha <= limite and c.compra_id not in usadas),
        key=lambda c: (c.fecha, c.compra_id),
    )

    # El puente va de clave de Doyle a `pro_id`; aquí hace falta al revés. El
    # primero que se declare para un `pro_id` gana — dos claves de Doyle
    # apuntando al mismo `pro_id` es un error de `config/continental.yml`
    # ajeno a esta función (`proveedores.leer_el_puente` ya lo avisa al
    # arrancar).
    inverso: dict[int, str] = {}
    for clave, pro_id in puente.items():
        inverso.setdefault(pro_id, clave)

    por_producto: dict[int, list[LineaDeCompra]] = {}
    for c in en_ventana:
        por_producto.setdefault(c.producto_id, []).append(c)

    coincidencias: list[Coincidencia] = []
    sin_comprar: list[SinComprar] = []
    compradas_sin_proponer: list[CompraSuelta] = []
    # Productos que ya se explicaron por otra vía y no deben repetirse en el
    # bloque 3 más abajo: los que ya tiene una `Coincidencia`, los ambiguos
    # (que ya se agregaron a `compradas_sin_proponer` directo) y los que
    # Continental ya atendió con el pedido normal.
    ya_tratados: set[int] = set()

    for r in renglones:
        producto_id = r.propuesto.producto_id
        if r.estado in _YA_ATENDIDOS_POR_OTRA_VIA:
            ya_tratados.add(producto_id)
            continue
        if r.esta_descartado:
            # Se resuelve en el bloque 3, con su marca: se propuso, una
            # persona dijo que no, y no se auto-confirma nada aquí.
            continue
        if r.estado != RENGLON_ABIERTO:
            # No debería quedar ningún otro estado, pero si lo hay, no se
            # inventa una lectura sobre él (regla 4): se deja fuera de los
            # tres bloques en vez de forzarlo en alguno.
            ya_tratados.add(producto_id)
            continue

        candidatas = por_producto.get(producto_id)
        if not candidatas:
            if productos_con_compras is not None and producto_id not in productos_con_compras:
                motivo = MOTIVO_NUNCA_EN_COMPRAS
            elif ancla < limite:
                motivo = MOTIVO_DATOS_NO_HAN_LLEGADO
            else:
                motivo = MOTIVO_NO_COMPRADO
            sin_comprar.append(SinComprar(r, motivo))
            continue

        proveedores_de_la_compra = {c.proveedor_id for c in candidatas}
        if len(proveedores_de_la_compra) > 1:
            # Ambiguo: se compró, pero a más de un proveedor dentro de la
            # ventana. Ver el docstring del módulo — no se elige ninguno.
            for c in candidatas:
                compradas_sin_proponer.append(
                    CompraSuelta(c, inverso.get(c.proveedor_id), ambiguo=True)
                )
            ya_tratados.add(producto_id)
            continue

        (proveedor_id,) = proveedores_de_la_compra
        clave = inverso.get(proveedor_id)
        motivo_no_accionable = None
        if clave is None:
            motivo_no_accionable = (
                f"SICAR conoce a este proveedor con proveedor_id {proveedor_id}, "
                "pero no es uno de los cuatro proveedores de Doyle: no hay clave "
                "con la que armar el pedido retroactivo. Se cuenta como "
                "comprado, y se revisa a mano."
            )
        coincidencias.append(
            Coincidencia(
                renglon=r,
                compras=tuple(candidatas),
                proveedor=clave,
                proveedor_id=proveedor_id,
                motivo_no_accionable=motivo_no_accionable,
            )
        )
        ya_tratados.add(producto_id)

    renglon_por_producto = {r.propuesto.producto_id: r for r in renglones}
    for c in en_ventana:
        if c.producto_id in ya_tratados:
            continue
        renglon_del_producto = renglon_por_producto.get(c.producto_id)
        compradas_sin_proponer.append(
            CompraSuelta(
                c,
                inverso.get(c.proveedor_id),
                fue_descartado=(
                    renglon_del_producto is not None
                    and renglon_del_producto.esta_descartado
                ),
            )
        )

    return Conciliacion(
        dia=dia,
        limite=limite,
        coincidencias=tuple(coincidencias),
        sin_comprar=tuple(sin_comprar),
        compradas_sin_proponer=tuple(compradas_sin_proponer),
    )


# ------------------------------------------------ el precio que de verdad se pagó
#
# Lo que paga el módulo entero: comparar lo que se pagó contra lo más barato
# que la comparación de precios (tickets 12-15) ya había encontrado ese día.
# Responde con dinero real "¿NADRO nos da el mejor precio?", sin depender de
# que nadie marque nada.


@dataclass(frozen=True, slots=True)
class ComparacionDePrecio:
    """Lo pagado contra lo más barato que ya sabíamos, para un renglón.

    `ganador` sale de `comparacion.elegir_ganador` sobre las lecturas
    **congeladas** de ese renglón (`pedidos.precio_de_proveedor`, que solo
    crece — ADR 0004): es el mismo precio que la pantalla de comparación
    enseñaba ese día, no uno recalculado con lo que cueste hoy.
    """

    pagado: Decimal
    proveedor_pagado: str | None
    ganador: Ganador

    @property
    def hubo_mas_barato(self) -> bool:
        """Si de verdad había una opción más barata que la que se pagó.

        Tres condiciones a la vez: que haya ganador, que su precio sea menor
        al pagado, y que el pagado no sea ya ese mismo proveedor —pagarle a
        NADRO lo mismo que NADRO cotizó no es un hallazgo—.
        """
        return (
            self.ganador.hay
            and self.ganador.precio is not None
            and self.ganador.precio < self.pagado
            and (self.proveedor_pagado is None or self.proveedor_pagado not in self.ganador.proveedores)
        )

    @property
    def diferencia_por_pieza(self) -> Decimal | None:
        """Cuánto más caro salió, por pieza. `None` sin ganador con precio."""
        if self.ganador.precio is None:
            return None
        return (self.pagado - self.ganador.precio).quantize(Decimal("0.01"))


def comparar_precio_pagado(
    precio_unitario_pagado: float,
    proveedor_pagado: str | None,
    lecturas: Sequence["PrecioDeProveedor"],
) -> ComparacionDePrecio:
    """El precio de una compra contra el ganador de la comparación ya hecha.

    `lecturas` son las de `almacenamiento.precios_del_renglon(renglon_id)`
    —las mismas con las que la pantalla de comparación arma su fila—, así
    que esta función no vuelve a preguntarle nada a Doyle: compara con lo que
    el módulo ya sabía el día que se propuso el renglón.
    """
    return ComparacionDePrecio(
        pagado=Decimal(str(precio_unitario_pagado)),
        proveedor_pagado=proveedor_pagado,
        ganador=elegir_ganador(lecturas),
    )


# -------------------------------------------------------------- las frases
#
# Compuestas aquí, en Python y con pruebas, y no en el JavaScript — la
# lección del ticket 15, repetida en el 21, el 24, el 25 y el 26.


def _piezas(cantidad: float) -> str:
    return f"{cantidad:g}"


def _con_unidad(cantidad: float) -> str:
    return f"{_piezas(cantidad)} pieza" + ("" if cantidad == 1 else "s")


def frase_de_la_coincidencia(c: Coincidencia) -> str:
    """Con a quién, cuánto y a qué precio — lo que el bloque 1 promete decir."""
    quien = "un proveedor que SICAR conoce pero Doyle no" if c.proveedor is None else c.proveedor
    cuantas = len(c.compras)
    compras = "una compra" if cuantas == 1 else f"{cuantas} compras"
    return (
        f"{c.descripcion}: SICAR tiene {compras} a {quien} desde que se propuso, "
        f"por {_con_unidad(c.piezas)} de las {c.piezas_pedidas} que se iban a pedir."
    )


def frase_del_sin_comprar(s: SinComprar) -> str:
    if s.motivo == MOTIVO_NUNCA_EN_COMPRAS:
        return (
            f"{s.renglon.propuesto.descripcion}: este producto nunca ha aparecido "
            "en una compra de SICAR — le pasa a cerca del 18% del catálogo. Esta "
            "conciliación nunca va a tener nada que decir de él."
        )
    if s.motivo == MOTIVO_DATOS_NO_HAN_LLEGADO:
        return (
            f"{s.renglon.propuesto.descripcion}: todavía no aparece una compra, "
            "pero el respaldo de SICAR puede tardar hasta 2.5 días. Es pronto "
            "para decir que no se compró."
        )
    return (
        f"{s.renglon.propuesto.descripcion}: pasó la ventana de tolerancia y sigue "
        "sin aparecer una compra que lo respalde. No se compró — al menos no de "
        "forma que SICAR lo sepa relacionar con este día."
    )


def frase_de_la_compra_suelta(c: CompraSuelta) -> str:
    quien = "un proveedor sin clave de Doyle" if c.proveedor is None else c.proveedor
    if c.ambiguo:
        return (
            f"Compra a {quien}, {_con_unidad(c.compra.cantidad)}: el mismo "
            "producto se compró a más de un proveedor en la ventana. Revísala "
            "a mano — no hay con qué elegir cuál renglón la sostiene."
        )
    if c.fue_descartado:
        return (
            f"Compra a {quien}, {_con_unidad(c.compra.cantidad)}: se había "
            "propuesto y se descartó, y se compró de todos modos. Es "
            "información, no un error de la lista."
        )
    return (
        f"Compra a {quien}, {_con_unidad(c.compra.cantidad)}: nadie la propuso. "
        "Es normal — no toda compra viene de esta lista."
    )
