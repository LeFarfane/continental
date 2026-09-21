"""Elegir proveedor por renglón, partir la lista en pedidos, y enviarlos.

El paso donde la comparación se vuelve una decisión (ticket 20) y donde esa
decisión se declara hecha (ticket 21). Funciones puras: no abre una conexión, no
llama a Doyle, no mira el reloj y no lee un archivo. Recibe los renglones
guardados, sus comparaciones ya hechas (`comparacion.comparar`), sus precios
congelados y el puente hacia SICAR (`proveedores.puente_configurado`), y
contesta cuatro cosas:

1. **a quién se le pide cada renglón** —lo que una persona decidió, y si nadie
   decidió, lo que el sistema sugiere—;
2. **en cuántos pedidos se parte la lista**, uno por proveedor;
3. **cuánto cuesta cada pedido**, o por qué no se puede saber;
4. **qué significa enviarlo**, y cuándo no se puede (ticket 21).

## "Enviar" no es enviar

La cuarta es la que más fácil se lee mal, y por eso está aquí arriba:
**Continental no le manda el pedido a ningún proveedor**. No entra a los
portales y no va a entrar (regla 1 de `CLAUDE.md`; el ADR 0002 lo dejó fuera de
alcance). Lo que se guarda al enviar es la **declaración** de una persona —*yo
ya lo capturé en el portal*—, firmada con el correo que verificó Access. El ADR
0009 lo razona entero. Las frases que lo dicen viven aquí, hechas, porque una
afirmación compuesta en el JavaScript es una afirmación sin pruebas.

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

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from continental.almacenamiento import (
    PedidoGuardado,
    PrecioDeProveedor,
    RenglonGuardado,
)
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


# ------------------------------------------------- qué significa enviar (21)
#
# La palabra "enviar" tiene un significado obvio que aquí **es falso**, y ésa es
# la quinta casilla del ticket 21. Continental no entra a los portales de los
# proveedores y no va a entrar: lo prohíbe la regla 1 de `CLAUDE.md` y el ADR
# 0002 lo dejó fuera de alcance con su razón. Lo que se guarda al apretar el
# botón es la **declaración** de una persona: *yo ya lo capturé en el portal*.
#
# Las frases viven aquí —en Python, probadas— y no en el JavaScript, y eso es
# la lección del ticket 15 aplicada al sitio donde más caro sale: una afirmación
# compuesta en el único archivo que ninguna prueba de Python mira es una
# afirmación sin pruebas, y ésta es la que impide que el encargado crea que
# Continental le mandó el pedido a NADRO.

#: Qué declara quien aprieta el botón. Va entre comillas en la pantalla porque
#: es literalmente lo que esa persona está diciendo.
ENVIAR_ES_UNA_DECLARACION = "yo ya lo capturé en el portal del proveedor"

#: Y el desmentido, en la misma frase y no en una nota al pie.
CONTINENTAL_NO_PIDE_EN_PORTALES = (
    "Continental no entra a los portales y no le manda el pedido a nadie"
)

#: El segundo clic de un botón que ya viajó, o dos pestañas abiertas en el
#: mostrador. No es un error de nadie y por eso se dice con palabras.
YA_ESTA_ENVIADO = "ese pedido ya está enviado: no se vuelve a enviar"

#: Un pedido cancelado (ticket 25, ADR 0013) no vuelve a enviarse: cancelar es
#: un final, no una vuelta a `borrador`. Lo que no llegó vuelve a proponerse en
#: la siguiente lista, y ahí se pide otra vez si hace falta.
YA_ESTA_CANCELADO = (
    "ese pedido se canceló: no se vuelve a enviar, y lo suyo vuelve a "
    "proponerse en la siguiente lista"
)

#: El pedido que se quedó sin renglones al volver a partir (ticket 20). Sigue
#: existiendo —el rol no tiene `DELETE`— con su total en `NULL`. Enviarlo diría
#: "capturé esto en el portal" sobre nada, y sus renglones ya se fueron a otro
#: pedido, así que ni siquiera hay qué pasar a `en tránsito`.
SIN_RENGLONES_QUE_ENVIAR = (
    "ese pedido se quedó sin renglones: no hay nada que capturar"
)

#: El total envejeció: alguien corrigió la cantidad de un renglón **después** de
#: armar el pedido, y `pedido.total_sin_iva` solo se reescribe al partir (hilo
#: abierto 13 de `HANDOVER.md`, que le dejó este caso a este ticket).
#:
#: Se NIEGA el envío en vez de recalcular en silencio, y las dos cosas se
#: consideraron. Recalcular cambiaría el número **después** de que el encargado
#: leyó el del botón: enviaría un total que nadie vio, que es peor que enseñar
#: uno viejo. Negarse manda a apretar "Volver a partir", que es un botón que ya
#: existe, cuesta un clic y deja el total y la hora de armado coherentes.
#:
#: Un total viejo importa porque es la cifra contra la que alguien va a comparar
#: la factura del proveedor: si no cuadra, nadie sabe si falta mercancía o si el
#: número estaba rancio.
TOTAL_ENVEJECIDO = (
    "alguien corrigió una cantidad después de armar este pedido, así que su "
    "total es de antes: vuelve a partir y se pone al día"
)


# --------------------------------------------- capturar en el portal (22)
#
# El modo real de trabajo: el portal del proveedor en una ventana, esta pantalla
# en otra, y el encargado tachando renglones conforme los teclea allá. Dónde
# vive ese avance —en `pedidos.renglon` y no en el navegador— es el ADR 0010.
#
# Las dos frases de abajo son la quinta casilla del ticket entera, y viven aquí
# por la lección del ticket 15: la frase que dice si tachar **condiciona** o
# **lleva** a enviar es justo la que se escribiría mal en el JavaScript.

#: Todo tachado: el siguiente paso es enviar. Es el empujón que la quinta
#: casilla pide —*marcar todo es lo que habilita enviar*— dicho con palabras
#: junto al botón, que la pantalla además resalta.
CAPTURA_COMPLETA = (
    "Ya está todo tachado. Si el carrito del portal quedó igual, el siguiente "
    "paso es enviar el pedido: es lo que evita que mañana se vuelva a proponer"
)

#: Y la otra mitad de la misma casilla —*sin obligar a ello*—, que es la que se
#: hace mal sola: un botón al lado de una lista a medio tachar se lee como
#: condicionado aunque no lo esté. Enviar sin haber tachado es legítimo (ADR
#: 0009 y 0010): quien capturó todo en el portal sin ir tachando aquí, o tachó
#: en una pestaña que ya cerró, no tiene por qué tachar cuarenta renglones para
#: poder decir que ya lo hizo.
CAPTURA_NO_OBLIGA = (
    "Tachar sirve para no perder la cuenta, no es requisito: si ya capturaste "
    "todo en el portal, puedes enviar el pedido aunque aquí falten marcas"
)


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
    #: El EAN, que es lo que se pega en el buscador del portal (ticket 22).
    #: `""` cuando el producto no está en el catálogo: se busca por nombre.
    clave: str = ""
    #: La firma de la captura (ticket 22, ADR 0010). `None` = nadie la tachó.
    capturado_por: str | None = None
    capturado_en: dt.datetime | None = None

    @property
    def tiene_precio(self) -> bool:
        return self.precio is not None

    @property
    def tiene_clave(self) -> bool:
        return bool(self.clave)

    @property
    def esta_capturado(self) -> bool:
        """Si alguien dijo ya haberla tecleado en el portal. Es una firma."""
        return self.capturado_por is not None

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

    # Lo que la línea es sin importar el precio. Desde el ticket 22 son también
    # la clave —lo que se pega en el buscador del portal— y la firma de la
    # captura; escritas una vez aquí y no tres veces abajo, que es como se
    # olvida una en el camino que menos se prueba.
    comunes = {
        "renglon_id": renglon.renglon_id,
        "descripcion": renglon.propuesto.descripcion,
        "cantidad": renglon.cantidad_a_pedir,
        "clave": renglon.propuesto.clave,
        "capturado_por": renglon.capturado_por,
        "capturado_en": renglon.capturado_en,
    }

    if lectura is None:
        return Linea(**comunes, motivo=SIN_CONSULTARLE)

    if lectura.precio is None:
        return Linea(
            **comunes,
            motivo=SIN_PRECIO_DE_ESE_PROVEEDOR,
            detalle=explicacion_del_motivo(lectura.motivo),
        )

    return Linea(**comunes, precio=lectura.precio)


def partir(
    renglones: Sequence[RenglonGuardado],
    comparaciones: Mapping[int, Comparacion],
    precios: Mapping[int, Sequence[PrecioDeProveedor]],
    puente: Mapping[str, int],
) -> Particion:
    """La lista de trabajo → un pedido por proveedor, más lo que se queda fuera.

    **Quién entra**: los renglones que se le pasen, y quien llama ya filtró.
    Lo que la ruta le pasa es `PedidoSugeridoGuardado.por_repartir` —los
    `abierto`—, y eso deja fuera dos cosas por razones distintas: un descartado
    ya se atendió —alguien lo miró y decidió no pedirlo— y uno `en tránsito` ya
    se pidió, porque su pedido se envió (ticket 21).

    Que los `en tránsito` no entren **no es solo higiene**: el `UPDATE` que
    asigna el pedido lleva `estado = 'abierto'` en su `WHERE`, así que si
    entraran, esta vista previa prometería mover renglones que la base no va a
    mover — y el mismo dinero saldría contado dos veces, en el pedido que ya se
    envió y en el que se está por armar.

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


# ------------------------------------------------------------- enviar (21)


def frase_del_envio(pedido: PedidoGuardado) -> str:
    """Qué dice la pantalla sobre el envío de **este** pedido.

    Dos frases y no una bandera, porque las dos tienen que desmentir lo mismo:

    - **borrador** — qué va a declarar quien apriete el botón, y que Continental
      no le va a mandar nada a nadie. Va donde está el botón, no en una nota al
      pie: quien no lea la nota es exactamente quien necesitaba leerla.
    - **enviado** — **quién** lo capturó, en voz activa y con su correo. El
      hecho ocurrió en otra pantalla, con otras credenciales, y Continental no
      lo vio; escribir "se envió" en voz pasiva sería afirmar algo que este
      programa no sabe. Y se vuelve a desmentir, porque un pedido que dice
      "enviado" es justo donde alguien leería que se lo mandamos al proveedor.

    El nombre del proveedor entra en las dos: *"ya lo capturé en el portal"* sin
    decir en cuál es media frase, y el encargado tiene cuatro portales abiertos.

    **La hora no se escribe aquí**: viaja aparte, en ISO con zona, y la pantalla
    la pinta con `instanteEnPalabras`. Formatear una fecha no es componer una
    afirmación — lo que no puede vivir allá es la frase, no el reloj.
    """
    if pedido.fue_enviado:
        return (
            f"{pedido.enviado_por} ya lo capturó en el portal de {pedido.nombre}. "
            f"Continental no se lo mandó a nadie: solo guarda quién lo dice y "
            f"cuándo lo dijo."
        )
    # CANCELADO (ticket 25, ADR 0013). Las dos firmas en voz activa: quién dijo
    # haberlo capturado y quién dijo después que no está en el portal. Y el
    # desmentido, igual que al enviar: Continental no canceló nada allá.
    if pedido.fue_cancelado:
        return (
            f"{pedido.cancelado_por} lo canceló: dijo que no está en el portal de "
            f"{pedido.nombre} (antes, {pedido.enviado_por} lo había marcado como "
            f"enviado). Continental no canceló nada en ningún portal. Sus "
            f"renglones vuelven a proponerse en la siguiente lista."
        )
    return (
        f"Enviar quiere decir «{ENVIAR_ES_UNA_DECLARACION}», el de "
        f"{pedido.nombre}. {CONTINENTAL_NO_PIDE_EN_PORTALES}: lo captura una "
        f"persona con la cuenta del dueño, y aquí se firma con su correo."
    )


def frase_sin_nada_por_repartir(
    en_transito: int, cancelados: int, recibidos: int = 0, sin_proveedor: int = 0
) -> str | None:
    """Por qué una lista ya no tiene nada que partir, cuando es porque se atendió.

    **Nació del recorrido del navegador del ticket 25** —la sexta vez que el
    recorrido caza lo que el suite no: 14, 15, 21, 22, 24 y 25—: con todo el
    pedido de hoy cancelado, la pantalla decía *"Todavía no hay en qué partir
    esta lista · Elige a quién se le pide cada renglón"* sobre renglones que ya
    no se pueden repartir. Es el mismo tropiezo del ticket 21 con otro estado.

    Desde el ticket 26 cuenta también lo que ya **llegó**: un renglón de hoy
    que se pidió en la mañana y se recibió en la tarde tampoco se reparte.

    `None` cuando no hay nada ya pedido ni cancelado: entonces "no hay en qué
    partir" quiere decir otra cosa —faltan precios o elecciones— y la pantalla
    dice lo suyo. Quien llama la pide cuando **la partición no tiene nada que
    partir**.

    **Desde el ticket 27, también en el caso mixto** (hilo abierto 18 de
    `HANDOVER.md`): algo ya se pidió —o llegó— y `sin_proveedor` renglones
    siguen sin a quién pedírselos. Hasta aquí la pantalla caía en su texto de
    reserva —"esta lista ya se pidió entera… sus renglones están en
    tránsito"—, que con lo recibido del 27 mentía dos veces. Ahora lo dice
    Python, y no afirma "ya se puede cerrar": falta elegir.
    """
    partes = []
    if en_transito == 1:
        partes.append("1 renglón ya se pidió y viene en camino")
    elif en_transito:
        partes.append(f"{en_transito} renglones ya se pidieron y vienen en camino")
    if recibidos == 1:
        partes.append("1 renglón ya se pidió y llegó")
    elif recibidos:
        partes.append(f"{recibidos} renglones ya se pidieron y llegaron")
    if cancelados == 1:
        partes.append(
            "1 renglón se dejó de esperar y vuelve a proponerse en la siguiente lista"
        )
    elif cancelados:
        partes.append(
            f"{cancelados} renglones se dejaron de esperar y vuelven a proponerse "
            "en la siguiente lista"
        )
    if not partes:
        return None
    if sin_proveedor:
        quedan = (
            "Queda 1 renglón sin proveedor"
            if sin_proveedor == 1
            else f"Quedan {sin_proveedor} renglones sin proveedor"
        )
        # Sin "no queda nada por repartir" ni "ya se puede cerrar": las dos
        # serían falsas mientras falte elegir.
        return f"{'; '.join(partes)}. {quedan}: elige a quién se le pide."
    return f"No queda nada por repartir: {'; '.join(partes)}. Ya se puede cerrar."


def motivo_para_no_enviar(
    pedido: PedidoGuardado,
    renglones_dentro: int,
    total_envejecido: bool = False,
) -> str | None:
    """Por qué no se puede enviar este pedido, o `None` si sí se puede.

    Es la **misma decisión** que el `WHERE` de `almacenamiento._ENVIAR_EL_PEDIDO`
    y no la garantía: la garantía vive en la sentencia, porque comprobar en
    Python y escribir después tiene una carrera en medio. Lo que esto hace es
    poder **decirlo antes** —un botón apagado con su motivo al lado, en vez de
    un 409 que llega cuando ya se apretó—, y decirlo con las mismas dos
    condiciones para que las dos respuestas no se separen.

    **Que el total sea `None` no está en la lista, y es deliberado.** Un pedido
    con una línea sin precio se envía igual: la quinta casilla del ticket 20 dice
    que ese renglón se pide igual, y el precio de verdad lo ve el encargado en el
    portal mientras lo captura. Negarlo aquí volvería el precio de Doyle un
    requisito para operar la farmacia, que es lo contrario de la regla 4 —"sin
    dato" nunca es un cero, y tampoco es un bloqueo—. Lo que la pantalla sí hace
    es escribir "total sin saber" en vez de una cifra.

    **Que el total esté VIEJO sí lo está, y no es lo mismo.** `None` es "no se
    puede saber" y es honesto; una cifra con dos decimales calculada antes de
    que alguien corrigiera una cantidad es una mentira con formato de dato, y
    además la que alguien va a comparar contra la factura. Es el hilo abierto 13
    de `HANDOVER.md`, que le dejó este caso a este ticket. `total_envejecido` lo
    decide quien llama comparando `armado_en` con el `ajustada_en` de los
    renglones de dentro; la garantía vive en el `WHERE` de
    `almacenamiento._ENVIAR_EL_PEDIDO`, que lleva la misma condición.
    """
    if pedido.fue_enviado:
        return YA_ESTA_ENVIADO
    # Antes del conteo: un cancelado conserva sus renglones dentro —son su
    # historia— y sin esta línea saldría "se puede enviar".
    if pedido.fue_cancelado:
        return YA_ESTA_CANCELADO
    if renglones_dentro <= 0:
        return SIN_RENGLONES_QUE_ENVIAR
    if total_envejecido:
        return TOTAL_ENVEJECIDO
    return None


# ------------------------------------------------ capturar en el portal (22)


@dataclass(frozen=True, slots=True)
class Captura:
    """Lo que hay que teclear en el portal de **un** proveedor, y cuánto va.

    `lineas` son `Linea` —las mismas de la partición— y no un tipo aparte: la
    regla de qué precio le toca a cada una vive en `_linea` y se escribe una
    sola vez. Lo que agrega la captura es **cuáles** entran y **cuántas faltan**.

    `descartados_dentro` son los renglones que cuelgan de este pedido y que
    alguien descartó después de partir. `_DESCARTAR` no toca `pedido_id`, así
    que siguen "dentro" hasta que se vuelva a partir; **no se listan para
    capturar** —teclearlos sería comprar lo que alguien decidió no comprar— y se
    cuentan para que la cuenta del pedido y la de la captura no difieran sin
    explicación.
    """

    proveedor: str
    lineas: tuple[Linea, ...] = ()
    descartados_dentro: int = 0

    @property
    def nombre(self) -> str:
        return nombre_del_proveedor(self.proveedor)

    @property
    def hay(self) -> bool:
        return bool(self.lineas)

    @property
    def cuantos(self) -> int:
        return len(self.lineas)

    @property
    def capturados(self) -> int:
        return sum(1 for linea in self.lineas if linea.esta_capturado)

    @property
    def faltan(self) -> int:
        """**La segunda casilla.** Contado aquí, donde hay pruebas."""
        return self.cuantos - self.capturados

    @property
    def todo_capturado(self) -> bool:
        """**Nada que capturar NO es todo capturado.**

        Si lo fuera, el pedido que se quedó vacío al volver a partir invitaría a
        enviar, y `motivo_para_no_enviar` lo niega con razón (ticket 21).
        """
        return self.hay and self.faltan == 0

    @property
    def sin_clave(self) -> int:
        """Cuántas no tienen EAN que copiar: esas se buscan por nombre."""
        return sum(1 for linea in self.lineas if not linea.tiene_clave)

    @property
    def sin_clave_por_tachar(self) -> int:
        """Las de arriba que **todavía** faltan.

        Es lo que la frase dice, y no el total: con todo tachado, "búscalo por
        nombre" manda a buscar algo que ya se capturó. Lo cazó el recorrido del
        navegador del 2026-09-21, no el suite.
        """
        return sum(
            1
            for linea in self.lineas
            if not linea.tiene_clave and not linea.esta_capturado
        )


def lo_que_hay_que_capturar(
    pedido: PedidoGuardado,
    renglones: Sequence[RenglonGuardado],
    precios: Mapping[int, Sequence[PrecioDeProveedor]],
) -> Captura:
    """Los renglones de **este** pedido, como se teclean en su portal.

    **Entran los que el pedido GUARDADO tiene dentro** —`renglon.pedido_id`—, y
    no los de la vista previa de la partición, y ésa es la trampa del ticket.
    La vista previa se recalcula con los precios de este instante: si a media
    mañana llega un LEVIC más barato, la vista previa ya pone el renglón en
    LEVIC mientras el pedido de NADRO todavía lo tiene dentro. Lo que se captura
    tiene que ser exactamente lo que al enviar pasa a `en tránsito`, y eso lo
    decide `pedido_id`, que es lo mismo que mira `_RENGLONES_A_TRANSITO`.

    **El orden es el de la lista, y tachar no lo cambia.** Mandar lo tachado al
    final movería bajo el dedo la lista que alguien va recorriendo con el
    portal abierto al lado, y el renglón por el que iba se iría de su sitio.

    El precio es el de **ese** proveedor y no el más barato: es el que el
    encargado va a ver en el carrito de ese portal, y enseñar otro haría que los
    dos números no cuadraran justo mientras captura. Sin precio de ese
    proveedor, la línea lo dice con su motivo —regla 4—, igual que en la
    partición.
    """
    dentro = [r for r in renglones if r.pedido_id == pedido.pedido_id]
    return Captura(
        proveedor=pedido.proveedor,
        lineas=tuple(
            _linea(r, pedido.proveedor, precios.get(r.renglon_id, ()))
            for r in dentro
            if not r.esta_descartado
        ),
        descartados_dentro=sum(1 for r in dentro if r.esta_descartado),
    )


def frase_del_avance(captura: Captura) -> str:
    """Cuánto va y **cuántos faltan**, dicho como lo diría una persona.

    Tres formas y no una plantilla con números, porque "0 de 18 tachados" se lee
    como un marcador que va perdiendo y "18 de 18" como un trámite: lo que se
    dice al empezar, a la mitad y al final no es lo mismo.
    """
    if not captura.hay:
        frase = "Este pedido no tiene renglones que capturar"
    elif captura.capturados == 0:
        frase = (
            "El único renglón de este pedido está sin tachar todavía"
            if captura.cuantos == 1
            else f"Ninguno de los {captura.cuantos} renglones está tachado todavía"
        )
    elif captura.todo_capturado:
        frase = (
            "El único renglón de este pedido está tachado"
            if captura.cuantos == 1
            else f"Los {captura.cuantos} renglones están tachados"
        )
    else:
        falta = "falta 1" if captura.faltan == 1 else f"faltan {captura.faltan}"
        frase = f"{captura.capturados} de {captura.cuantos} tachados · {falta}"

    if captura.sin_clave_por_tachar:
        frase += (
            " · 1 sin código de barras: búscalo por nombre"
            if captura.sin_clave_por_tachar == 1
            else f" · {captura.sin_clave_por_tachar} sin código de barras: "
            "búscalos por nombre"
        )
    if captura.descartados_dentro:
        frase += (
            " · 1 renglón de este pedido está descartado: no lo captures, y "
            "vuelve a partir para sacarlo"
            if captura.descartados_dentro == 1
            else f" · {captura.descartados_dentro} renglones de este pedido están "
            "descartados: no los captures, y vuelve a partir para sacarlos"
        )
    return frase


def invitacion_a_enviar(captura: Captura, se_puede_enviar: bool) -> str | None:
    """**La quinta casilla**: tachar todo LLEVA a enviar, sin obligar a ello.

    | La captura | Se puede enviar | Qué se dice |
    |---|---|---|
    | todo tachado | sí | `CAPTURA_COMPLETA` — el siguiente paso es enviar |
    | a medias o sin empezar | sí | `CAPTURA_NO_OBLIGA` — no es requisito |
    | cualquiera | no | nada: el motivo del ticket 21 ya lo dice |
    | sin renglones | — | nada |

    **Lo que esta función NO hace es decidir si el botón se apaga**, y es a
    propósito: eso es `motivo_para_no_enviar` y no recibe la captura. Si
    tacharlo todo fuera condición, un encargado que capturó todo en el portal
    sin ir tachando aquí tendría que tachar cuarenta renglones para poder decir
    que ya lo hizo — y el que no lo hiciera dejaría la mercancía pedida sin
    pasar a `en tránsito`, que es la falla que el ticket 21 vino a evitar.

    Con el botón apagado no se invita a nada: dos frases al lado, una que dice
    "envía" y otra que dice por qué no se puede, se contradicen.
    """
    if not captura.hay or not se_puede_enviar:
        return None
    return CAPTURA_COMPLETA if captura.todo_capturado else CAPTURA_NO_OBLIGA


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


def captura_como_json(captura: Captura, se_puede_enviar: bool) -> dict:
    """La captura de un pedido como la pantalla la lee (ticket 22).

    Los conteos y las dos frases viajan **hechos**: el JavaScript ni filtra ni
    suma. Es la misma razón por la que los conteos de descartados salen del
    servidor desde el ticket 10 —dos pestañas abiertas bastan para que un número
    que el navegador va sumando se separe de la verdad—, y aquí además es el
    número que decide si la pantalla invita a enviar.
    """
    return {
        "proveedor": captura.proveedor,
        "nombre": captura.nombre,
        "cuantos": captura.cuantos,
        "capturados": captura.capturados,
        "faltan": captura.faltan,
        "todo_capturado": captura.todo_capturado,
        "sin_clave": captura.sin_clave,
        "descartados_dentro": captura.descartados_dentro,
        "frase": frase_del_avance(captura),
        "invitacion": invitacion_a_enviar(captura, se_puede_enviar),
        "lineas": [
            {
                "renglon_id": linea.renglon_id,
                "clave": linea.clave,
                "tiene_clave": linea.tiene_clave,
                "descripcion": linea.descripcion,
                "cantidad": linea.cantidad,
                # Cadena o `null`, jamás un número de JSON ni un cero.
                "precio": _cadena(linea.precio),
                "tiene_precio": linea.tiene_precio,
                "motivo": linea.motivo,
                "esta_capturado": linea.esta_capturado,
                # La firma viaja para el `title` de la casilla: quién la tachó y
                # cuándo. Es una firma, nunca un permiso (regla 3).
                "capturado_por": linea.capturado_por,
                "capturado_en": (
                    linea.capturado_en.isoformat() if linea.capturado_en else None
                ),
            }
            for linea in captura.lineas
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
