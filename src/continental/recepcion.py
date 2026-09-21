"""Recepción sugerida: lo que viene en camino + las compras de SICAR → "probablemente
recibido", con su evidencia (ticket 26, ADR 0014).

**Funciones puras y nada más.** Entran los renglones en tránsito y las compras
que el almacén ya tiene, y salen propuestas con su evidencia, los renglones que
no tienen propuesta con su motivo, y las frases que lo dicen. No abre una
conexión, no lee el YAML y no mira el reloj: el `ahora` entra por argumento,
igual que en `transito.py`.

## La regla del ADR 0002: se sugiere, no se afirma

SICAR no tiene pedidos. Una compra se captura **ya recibida**, sin estado
parcial, no está documentado si su fecha es la de llegada o la de captura, y
el significado de `folio` no está verificado. Con eso, cerrar renglones solos
cerraría algunos en falso, y un renglón cerrado en falso es mercancía que no se
vuelve a pedir. Así que lo que sale de aquí es **una propuesta**, y el renglón
sigue `en tránsito` hasta que una persona la confirma o la rechaza.

## Cómo se empareja

**Por proveedor, producto y fecha posterior al envío. Nunca por folio.**

- **Proveedor**: el `pro_id` de SICAR que el pedido guardó al partirse (ADR
  0008). Un pedido sin puente —QuePharma— no tiene con qué cruzarse, y eso se
  dice: nunca va a haber propuesta.
- **Producto**: el `producto_id`, que en los dos lados es el `art_id` de SICAR.
- **Fecha**: la compra tiene **día**, no hora; el envío es un **instante** con
  zona. "Posterior" se mide en **días de la farmacia** (UTC-6, calculado aquí y
  no en Postgres, donde `at time zone '-06'` es la convención POSIX y se lee
  UTC+6), y **el mismo día cuenta**: un pedido capturado a las 9 y surtido a
  las 15 es el caso de todos los días. Lo que eso deja pasar de más —una compra
  de esa misma mañana que era de otro pedido— lo juzga la persona con la
  evidencia enfrente.
- **El folio se enseña y no se usa.** Sirve para que alguien lo busque en la
  factura; decidir con él sería apostar a un significado que nadie ha medido.

## Lo que no se guarda y lo que sí

La propuesta **se calcula cada vez** que se mira (ADR 0014): si la compra
desaparece del almacén —se canceló en SICAR, o la cadena no corrió— la
propuesta desaparece con ella, en vez de quedar escrita afirmando algo que ya
no tiene evidencia. Lo que **sí** se guarda son las dos decisiones de una
persona: confirmar (el renglón pasa a `recibido`, firmado, con las compras que
lo sostienen) y rechazar (qué compras no son este renglón, firmado, para que no
vuelvan a proponerse mañana). Es la misma línea del ticket 20: lo sugerido no se
guarda, lo decidido sí.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from continental.almacen import LineaDeCompra
from continental.transito import (
    ZONA_DE_LA_FARMACIA,
    fecha_en_palabras,
    frase_del_transito,
)

if TYPE_CHECKING:  # pragma: no cover - solo para los tipos
    from continental.almacenamiento import LoYaPedido, RenglonGuardado

# ------------------------------------------------------------ los motivos
#
# Por qué un renglón en camino NO tiene propuesta. Son seis y no uno porque se
# resuelven de seis maneras distintas: dos no van a tener propuesta nunca (y
# alguien tiene que saberlo para no esperarla), una es lo normal de todos los
# días, y tres son consecuencia de algo que ya decidió una persona.

#: El pedido no tiene `pro_id` de SICAR (ADR 0008): QuePharma hoy.
MOTIVO_SIN_PUENTE = "sin puente"
#: El producto nunca ha aparecido en una compra de SICAR: 606 de 3,429
#: artículos (17.7%, medido sobre el respaldo del 2026-07-27). Entra por otra
#: vía y no deja rastro.
MOTIVO_NUNCA_EN_COMPRAS = "nunca en compras"
#: Lo que encajaba, alguien lo rechazó.
MOTIVO_RECHAZADA = "rechazada"
#: Lo que encajaba ya confirmó otro renglón: una compra confirma uno solo.
MOTIVO_YA_USADA = "ya usada"
#: No quedó la hora del envío, y sin ella no se sabe qué es "posterior".
MOTIVO_SIN_HORA = "sin hora de envío"
#: Todavía no aparece una compra que encaje. **Lo normal.**
MOTIVO_TODAVIA_NO = "todavía no aparece"

#: En este orden se enseñan: primero lo que nunca va a tener propuesta —es lo
#: que alguien tiene que resolver por otro lado—, al final lo que solo espera.
MOTIVOS_SIN_PROPUESTA: tuple[str, ...] = (
    MOTIVO_SIN_PUENTE,
    MOTIVO_NUNCA_EN_COMPRAS,
    MOTIVO_SIN_HORA,
    MOTIVO_RECHAZADA,
    MOTIVO_YA_USADA,
    MOTIVO_TODAVIA_NO,
)

#: **La salida que el ticket 27 va a abrir y que hoy no existe.** Se dice así, y
#: no con un botón que no hay: prometer "márcalo a mano" en una pantalla sin ese
#: botón sería una frase que afirma lo falso. El 27 cambia esta frase.
FALTA_EL_MARCADO_MANUAL = (
    "Su única salida es el recibido a mano, y eso todavía no se puede desde "
    "esta pantalla."
)

#: **Una noche de retraso es normal, no un error** (casilla 6). Viaja siempre
#: con el bloque, también cuando todo tiene propuesta: es cuando alguien recibe
#: la mercancía a las 11 y a las 12 no ve nada que confirmar.
AVISO_DEL_RETRASO = (
    "Una compra aparece aquí hasta la noche siguiente a su captura en SICAR: el "
    "respaldo sube hacia las 18:51 y la cadena corre a las 20:30, de lunes a "
    "viernes, así que lo del sábado aparece hasta el lunes en la noche. Que lo "
    "que llegó hoy todavía no tenga propuesta es normal, no un error."
)

#: Qué declara quien aprieta cada botón, junto a los botones.
ADVERTENCIA_AL_CONFIRMAR = (
    "Confirmar es decir que llegó completo: el renglón pasa a recibido y lo que "
    "se vendió mientras venía vuelve a proponerse en la siguiente lista. "
    "Rechazar es decir que esa compra no es este pedido: el renglón sigue en "
    "camino y esa compra ya no se le vuelve a proponer."
)


# ------------------------------------------------------------------ datos


@dataclass(frozen=True, slots=True)
class Propuesta:
    """Un renglón en tránsito con las compras que encajan: *probablemente recibido*.

    `compras` es **la evidencia entera**, ordenada por fecha: todas las compras
    del mismo proveedor y producto, posteriores al envío, que nadie rechazó
    para este renglón ni usó para confirmar otro. Se suman: un pedido puede
    llegar en dos facturas.

    `tambien_encaja_con` son los otros renglones en camino a los que la misma
    compra también les sirve —dos pedidos del mismo producto al mismo
    proveedor—. No se reparte en silencio: se dice en los dos, y el `WHERE` de
    confirmar impide que la misma compra confirme dos renglones.
    """

    ya: "LoYaPedido"
    compras: tuple[LineaDeCompra, ...]
    tambien_encaja_con: tuple[int, ...] = ()

    @property
    def renglon_id(self) -> int:
        return self.ya.renglon.renglon_id

    @property
    def compras_ids(self) -> tuple[int, ...]:
        return tuple(c.compra_id for c in self.compras)

    @property
    def piezas(self) -> float:
        """Cuántas piezas trae la evidencia. Tres decimales: el granel existe."""
        return round(sum(c.cantidad for c in self.compras), 3)

    @property
    def piezas_pedidas(self) -> int:
        """Lo que de verdad se le pidió: la corrección de la persona o la propuesta."""
        return self.ya.renglon.cantidad_a_pedir

    @property
    def se_puede_confirmar(self) -> bool:
        """**Solo si trae al menos lo pedido.** `recibido` es "llegó completo"
        (`CONTEXT.md`): confirmar menos sería cerrar en falso, y lo que faltó ya
        no se volvería a proponer. Lo parcial es el ticket 27."""
        return self.piezas >= self.piezas_pedidas

    @property
    def motivo_para_no_confirmar(self) -> str | None:
        if self.se_puede_confirmar:
            return None
        return (
            f"La evidencia trae {_piezas(self.piezas)} de las "
            f"{self.piezas_pedidas} piezas que se pidieron: confirmar diría que "
            "llegó completo. Si llegó solo eso, es un recibido parcial, que "
            "todavía no se puede marcar aquí; si falta otra factura, aparecerá."
        )


@dataclass(frozen=True, slots=True)
class SinPropuesta:
    """Un renglón en camino sin propuesta, y por qué (uno de `MOTIVOS_SIN_PROPUESTA`)."""

    ya: "LoYaPedido"
    motivo: str

    @property
    def renglon_id(self) -> int:
        return self.ya.renglon.renglon_id


@dataclass(frozen=True, slots=True)
class Recepcion:
    """Todo lo que viene en camino, repartido: con propuesta y sin ella."""

    propuestas: tuple[Propuesta, ...] = ()
    sin_propuesta: tuple[SinPropuesta, ...] = ()

    def propuesta_de(self, renglon_id: int) -> Propuesta | None:
        return next((p for p in self.propuestas if p.renglon_id == renglon_id), None)


# ------------------------------------------------------------------ la regla


def dia_del_envio(enviado_en: dt.datetime | None) -> dt.date | None:
    """El día **de la farmacia** en que se envió. Sin zona se toma como UTC.

    Un envío del lunes a las 20:30 son las 02:30 del martes en UTC: contado en
    UTC, la compra del lunes quedaría fuera.
    """
    if enviado_en is None:
        return None
    if enviado_en.tzinfo is None:
        enviado_en = enviado_en.replace(tzinfo=dt.UTC)
    return enviado_en.astimezone(ZONA_DE_LA_FARMACIA).date()


def _puede_tener_propuesta(ya: "LoYaPedido") -> bool:
    return ya.esta_en_transito and ya.proveedor_id is not None and ya.enviado_en is not None


def desde_cuando_leer_compras(en_transito: Iterable["LoYaPedido"]) -> dt.date | None:
    """Desde qué día leer compras para que quepa todo lo que puede tener propuesta.

    Una sola lectura desde el envío más viejo, igual que la de ventas del
    ticket 24. `None` si nada puede tener propuesta: entonces no se lee.
    """
    dias = [dia_del_envio(ya.enviado_en) for ya in en_transito if _puede_tener_propuesta(ya)]
    return min(dias) if dias else None


def _encaja(ya: "LoYaPedido", compra: LineaDeCompra, desde: dt.date) -> bool:
    """Proveedor, producto y fecha. **Nada más, y nunca el folio.**"""
    return (
        compra.proveedor_id == ya.proveedor_id
        and compra.producto_id == ya.producto_id
        and compra.fecha >= desde
    )


def proponer(
    en_transito: Iterable["LoYaPedido"],
    compras: Iterable[LineaDeCompra],
    *,
    ya_usadas: Collection[int] = frozenset(),
    productos_con_compras: Collection[int] | None = None,
) -> Recepcion:
    """Lo que viene en camino + las compras → propuestas y motivos.

    - `en_transito`: solo cuenta lo que **está** `en tránsito`; lo demás se
      ignora (ya se recibió, se canceló…).
    - `compras`: las del almacén, de cualquier proveedor. Se filtran aquí.
    - `ya_usadas`: los `compra_id` que ya confirmaron algún renglón. No se
      proponen otra vez: una compra confirma un solo renglón.
    - `productos_con_compras`: de estos productos, cuáles han aparecido alguna
      vez en una compra de SICAR. `None` es "no se pudo saber", y entonces no se
      afirma que un producto no aparezca nunca (regla 4).

    El orden de salida es el de entrada: el de las listas y los renglones.
    """
    compras = sorted(compras, key=lambda c: (c.fecha, c.compra_id))
    usadas = frozenset(ya_usadas)
    propuestas: list[Propuesta] = []
    sin: list[SinPropuesta] = []

    for ya in en_transito:
        if not ya.esta_en_transito:
            continue
        if ya.proveedor_id is None:
            sin.append(SinPropuesta(ya, MOTIVO_SIN_PUENTE))
            continue
        desde = dia_del_envio(ya.enviado_en)
        if desde is None:
            sin.append(SinPropuesta(ya, MOTIVO_SIN_HORA))
            continue

        rechazadas = frozenset(ya.renglon.compras_rechazadas or ())
        encajan = [c for c in compras if _encaja(ya, c, desde)]
        libres = tuple(
            c for c in encajan if c.compra_id not in rechazadas and c.compra_id not in usadas
        )
        if libres:
            propuestas.append(Propuesta(ya, libres))
        elif any(c.compra_id in rechazadas for c in encajan):
            sin.append(SinPropuesta(ya, MOTIVO_RECHAZADA))
        elif encajan:
            sin.append(SinPropuesta(ya, MOTIVO_YA_USADA))
        elif productos_con_compras is not None and ya.producto_id not in productos_con_compras:
            sin.append(SinPropuesta(ya, MOTIVO_NUNCA_EN_COMPRAS))
        else:
            sin.append(SinPropuesta(ya, MOTIVO_TODAVIA_NO))

    # Quién comparte evidencia con quién. Se calcula al final y sobre las
    # propuestas ya hechas: una compra que encaja con dos renglones aparece en
    # los dos, y cada uno lo dice.
    compartidas = []
    for propuesta in propuestas:
        mias = set(propuesta.compras_ids)
        otros = tuple(
            otra.renglon_id
            for otra in propuestas
            if otra is not propuesta and mias & set(otra.compras_ids)
        )
        compartidas.append(Propuesta(propuesta.ya, propuesta.compras, otros))

    return Recepcion(propuestas=tuple(compartidas), sin_propuesta=tuple(sin))


# -------------------------------------------------------------- las frases
#
# Las frases que AFIRMAN algo se componen aquí, en Python y con pruebas, y no en
# el JavaScript: la lección del ticket 15, repetida en el 21, el 24 y el 25.


def _piezas(cantidad: float) -> str:
    """`5` y no `5.0`; `2.5` sí, porque el granel existe."""
    return f"{cantidad:g}"


def _con_unidad(cantidad: float) -> str:
    return f"{_piezas(cantidad)} pieza" + ("" if cantidad == 1 else "s")


def _renglones(cuantos: int) -> str:
    return "1 renglón" if cuantos == 1 else f"{cuantos} renglones"


def _nombre(ya: "LoYaPedido") -> str:
    return ya.nombre_del_proveedor or "un proveedor que no quedó escrito"


def frase_de_la_propuesta(propuesta: Propuesta) -> str:
    """El encabezado: **probablemente**, que es la palabra del glosario."""
    cuantas = len(propuesta.compras)
    compras = "una compra" if cuantas == 1 else f"{cuantas} compras"
    return (
        f"Probablemente ya llegó: SICAR tiene {compras} a {_nombre(propuesta.ya)} "
        "de este producto desde que se envió el pedido. Revisa la evidencia antes "
        "de confirmar."
    )


def _cuando_despues(compra: LineaDeCompra, desde: dt.date | None) -> str:
    if desde is None:
        return "sin saber cuándo se envió"
    dias = (compra.fecha - desde).days
    if dias <= 0:
        return "el mismo día en que se envió"
    if dias == 1:
        return "1 día después de enviarlo"
    return f"{dias} días después de enviarlo"


def frase_de_la_evidencia(ya: "LoYaPedido", compra: LineaDeCompra) -> str:
    """Una compra, dicha para que una persona la juzgue: quién, qué día, cuánto.

    **El folio se enseña diciendo que no se usó** para emparejar: sirve para
    buscarlo en la factura, y nada más (ADR 0002).
    """
    folio = (
        f" Folio {compra.folio} (se enseña para buscarlo en la factura; no se usó "
        "para emparejar)."
        if compra.folio
        else " Sin folio."
    )
    return (
        f"Compra a {_nombre(ya)}, {fecha_en_palabras(compra.fecha)}: "
        f"{_con_unidad(compra.cantidad)}, "
        f"{_cuando_despues(compra, dia_del_envio(ya.enviado_en))}.{folio}"
    )


def frase_de_la_cantidad(propuesta: Propuesta) -> str:
    """Lo que la evidencia trae contra lo que se pidió. **La puerta del 27.**

    Menos no se confirma —sería un recibido completo en falso— y se dice qué
    hacer; más sí, y se dice qué puede significar.
    """
    trae, pedidas = propuesta.piezas, propuesta.piezas_pedidas
    if trae == pedidas:
        if pedidas == 1:
            return "Trae la pieza que se pidió."
        return f"Trae las {_con_unidad(pedidas)} que se pidieron."
    if trae < pedidas:
        return (
            f"Trae {_piezas(trae)} de las {pedidas} piezas que se pidieron. Si "
            "solo llegó eso, es un recibido parcial, que todavía no se puede "
            "marcar aquí: no lo confirmes como completo. Si falta otra factura, "
            "cuando aparezca se sumará."
        )
    return (
        f"Trae {_con_unidad(trae)} y se pidieron {pedidas}: más de lo pedido. "
        "Puede traer también otro pedido del mismo producto, o una bonificación."
    )


def frase_compartida(propuesta: Propuesta) -> str | None:
    """Cuando la misma compra también encaja con otro renglón en camino."""
    if not propuesta.tambien_encaja_con:
        return None
    otros = len(propuesta.tambien_encaja_con)
    cual = "otro renglón" if otros == 1 else f"otros {otros} renglones"
    return (
        f"Esta evidencia también encaja con {cual} en camino del mismo producto y "
        "el mismo proveedor (otro pedido). Una compra confirma un solo renglón: "
        "el primero que se confirme se la queda, y el otro sigue esperando la "
        "suya."
    )


def frase_del_motivo(motivo: str, proveedores: Sequence[str] = (), cuantos: int = 1) -> str:
    """Por qué no hay propuesta, dicho para quien tiene que hacer algo con eso.

    `cuantos` es cuántos renglones comparten el motivo: la frase va debajo de
    ellos y concuerda en número (lo cazó el recorrido del navegador: "siguen en
    camino" debajo de un solo renglón).
    """
    uno = cuantos == 1
    if motivo == MOTIVO_SIN_PUENTE:
        quien = " y ".join(proveedores) if proveedores else "su proveedor"
        con_que = "este pedido" if uno else "estos pedidos"
        return (
            f"Nunca va a haber propuesta: SICAR no conoce a {quien}, así que "
            f"ninguna compra de SICAR se puede cruzar con {con_que}. "
            + FALTA_EL_MARCADO_MANUAL
        )
    if motivo == MOTIVO_NUNCA_EN_COMPRAS:
        cual = (
            "este producto nunca ha aparecido"
            if uno
            else "estos productos nunca han aparecido"
        )
        return (
            f"Lo más probable es que nunca haya propuesta: {cual} en una compra "
            "de SICAR —le pasa a cerca del 18% del catálogo, que entra sin compra "
            "capturada—. " + FALTA_EL_MARCADO_MANUAL
        )
    if motivo == MOTIVO_SIN_HORA:
        return (
            "No quedó la hora del envío, así que no se puede saber qué compra es "
            "posterior a él. " + FALTA_EL_MARCADO_MANUAL
        )
    if motivo == MOTIVO_RECHAZADA:
        return (
            "La compra que encajaba se rechazó: "
            + ("sigue" if uno else "siguen")
            + " en camino, esperando otra que encaje."
        )
    if motivo == MOTIVO_YA_USADA:
        return (
            "La compra que encajaba ya confirmó otro renglón del mismo producto: "
            "una compra confirma un solo renglón. "
            + ("Sigue" if uno else "Siguen")
            + " esperando la suya."
        )
    return (
        "Todavía no aparece una compra que encaje. Es normal, no un error: lo "
        "que se captura en SICAR aparece aquí hasta la cadena de la noche."
    )


def frase_del_bloque(propuestas: int, sin_propuesta: int) -> str:
    """El encabezado del bloque. **Nunca calla**: cero también se dice."""
    if propuestas == 0 and sin_propuesta == 0:
        return "Nada viene en camino: no hay nada que recibir."
    if propuestas == 0:
        return (
            "Ninguna compra del almacén encaja todavía con lo que viene en camino."
        )
    if propuestas == 1:
        return (
            "1 renglón en camino probablemente ya llegó: confírmalo o recházalo "
            "con la evidencia a la vista."
        )
    return (
        f"{propuestas} renglones en camino probablemente ya llegaron: confírmalos "
        "o recházalos uno por uno, con la evidencia a la vista."
    )


def frase_del_confirmado(descripcion: str) -> str:
    """Lo que contesta la ruta al confirmar."""
    return (
        f"{descripcion} quedó recibido. Lo que se vendió mientras venía vuelve a "
        "proponerse en la siguiente lista."
    )


def frase_del_rechazado(descripcion: str) -> str:
    """Lo que contesta la ruta al rechazar."""
    return (
        f"Se rechazó la compra: {descripcion} sigue en camino, y esa compra ya no "
        "se le vuelve a proponer. Si aparece otra que encaje, se propondrá."
    )


def frase_de_lo_recibido(renglon: "RenglonGuardado") -> str | None:
    """La firma de un renglón recibido: quién lo confirmó, cuándo y con qué.

    Es la única frase de este módulo que afirma que llegó, y lo afirma **una
    persona**: se dice quién.
    """
    if not renglon.esta_recibido:
        return None
    quien = renglon.recibido_por or "alguien que no quedó escrito"
    if renglon.recibido_en is None:
        cuando = "sin hora escrita"
    else:
        local = renglon.recibido_en
        if local.tzinfo is None:
            local = local.replace(tzinfo=dt.UTC)
        local = local.astimezone(ZONA_DE_LA_FARMACIA)
        cuando = f"{fecha_en_palabras(local.date())} a las {local:%H:%M}"
    compras = renglon.recibido_con_compras or ()
    con_que = (
        "sin compra de SICAR que lo sostenga"
        if not compras
        else ("con 1 compra de SICAR" if len(compras) == 1 else f"con {len(compras)} compras de SICAR")
    )
    return f"Recibido: lo confirmó {quien} {cuando}, {con_que}."


# ------------------------------------------------------------------ el JSON


def _renglon_como_json(ya: "LoYaPedido") -> dict:
    return {
        "renglon_id": ya.renglon.renglon_id,
        "producto_id": ya.producto_id,
        "clave": ya.renglon.propuesto.clave,
        "descripcion": ya.renglon.propuesto.descripcion,
        "cantidad": ya.renglon.cantidad_a_pedir,
        "proveedor": ya.proveedor,
        "nombre": ya.nombre_del_proveedor,
    }


def recepcion_como_json(recepcion: Recepcion, ahora: dt.datetime) -> dict:
    """El bloque de la recepción, como la pantalla lo lee.

    Las frases viajan **hechas**; los datos van además porque la pantalla los
    usa para acomodar y para mandar de vuelta **qué compras vio** al confirmar
    o rechazar —el servidor vuelve a calcular la propuesta y se niega si ya no
    es la misma—.
    """
    propuestas = []
    for propuesta in recepcion.propuestas:
        ya = propuesta.ya
        propuestas.append(
            {
                **_renglon_como_json(ya),
                "frase": frase_de_la_propuesta(propuesta),
                "frase_del_transito": frase_del_transito(
                    ya.nombre_del_proveedor, ya.enviado_en, ahora
                ),
                "evidencia": [
                    {
                        "compra_id": c.compra_id,
                        "fecha": c.fecha.isoformat(),
                        "cantidad": c.cantidad,
                        "folio": c.folio or None,
                        "frase": frase_de_la_evidencia(ya, c),
                    }
                    for c in propuesta.compras
                ],
                "compras": list(propuesta.compras_ids),
                "piezas": propuesta.piezas,
                "piezas_pedidas": propuesta.piezas_pedidas,
                "frase_de_la_cantidad": frase_de_la_cantidad(propuesta),
                "compartida": frase_compartida(propuesta),
                "tambien_encaja_con": list(propuesta.tambien_encaja_con),
                "se_puede_confirmar": propuesta.se_puede_confirmar,
                "motivo_para_no_confirmar": propuesta.motivo_para_no_confirmar,
            }
        )

    grupos = []
    for motivo in MOTIVOS_SIN_PROPUESTA:
        de_este = [s for s in recepcion.sin_propuesta if s.motivo == motivo]
        if not de_este:
            continue
        nombres = sorted({_nombre(s.ya) for s in de_este}) if motivo == MOTIVO_SIN_PUENTE else ()
        grupos.append(
            {
                "motivo": motivo,
                "frase": frase_del_motivo(motivo, nombres, len(de_este)),
                "renglones": [_renglon_como_json(s.ya) for s in de_este],
            }
        )

    return {
        "ok": True,
        "detalle": None,
        "frase": frase_del_bloque(len(recepcion.propuestas), len(recepcion.sin_propuesta)),
        "aviso_del_retraso": AVISO_DEL_RETRASO,
        "advertencia": ADVERTENCIA_AL_CONFIRMAR,
        "propuestas": propuestas,
        "esperan": grupos,
    }


def recepcion_con_hueco(detalle: str) -> dict:
    """El bloque cuando no se pudo leer algo: un hueco con su motivo (regla 4).

    Nunca "nada que recibir": eso se leería como que no llegó nada, y quizá sí.
    """
    return {
        "ok": False,
        "detalle": detalle,
        "frase": "No se pudo saber qué llegó de lo que viene en camino.",
        "aviso_del_retraso": AVISO_DEL_RETRASO,
        "advertencia": ADVERTENCIA_AL_CONFIRMAR,
        "propuestas": [],
        "esperan": [],
    }
