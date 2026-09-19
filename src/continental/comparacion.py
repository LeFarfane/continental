"""La comparación de los cuatro: quién gana y cuánto se ahorra. Funciones puras.

Este módulo es la razón de ser del módulo de Pedido escrita en aritmética. No
abre una conexión, no llama a Doyle, no mira el reloj y no lee un archivo:
recibe las lecturas **ya congeladas** de un renglón —lo que
`almacenamiento.precios_del_renglon` devuelve, una por proveedor, la más
reciente de cada uno— más las piezas que se van a pedir, y contesta tres cosas:

1. **quién gana**, que no es "el más barato" sino *el más barato de los que lo
   tienen*;
2. **cuánto se ahorra** contra NADRO, en pesos y por renglón;
3. **cómo se ve cada uno de los cuatro**, para que la pantalla no tenga que
   deducir nada.

Y desde el ticket 15, una cuarta que no es de un renglón sino de la lista:

4. **cuántos renglones quedaron sin comparar, y por qué cada uno**
   (`contar_la_lista`). Es lo que impide que alguien lea la lista como si
   estuviera completa.

## "El más barato" es un superlativo, y con un solo precio no se puede decir

La casilla del ticket 15 que más cambia este módulo: *un renglón comparado
contra un solo proveedor no se presenta como "el más barato": se presenta como
"el único que contestó"*. Decir "el más barato" afirma algo sobre los otros
tres —que se miraron y que costaban más— y con una sola lectura eso no se miró.

Quién gana no cambia: sigue siendo el mismo proveedor, con el mismo precio y la
misma existencia. Cambia **lo que se afirma de él**, y eso vive en la `certeza`
del `Ganador`, que viaja como frase hecha hasta la pantalla. Hasta el ticket 14
esa frase se elegía en el JavaScript entre dos literales suyos, y por eso un
renglón con una sola lectura salía rotulado *"el más barato con existencia"*
sin que ninguna prueba de Python se pusiera roja.

## "Sin comparar" son tres cosas, no una

Nadie lo consultó · se consultó y ninguno dio precio · hay un solo precio. Las
tres son "sin comparar" —de ninguna salió una cifra puesta al lado de otra— y
se cuentan por separado porque **el encargado las arregla distinto**: la
primera con un botón, la segunda mirando el motivo de cada hueco, y la tercera
no se arregla: es una advertencia sobre lo que ese precio puede decir de sí
mismo.

Vive aparte de la ruta y de la pantalla por la misma razón que `precios.py`: es
la regla con la que se decide a quién comprarle, y una regla que vive dentro de
un `if` de FastAPI o dentro del JavaScript solo se puede probar levantando un
servidor o abriendo un navegador. Aquí se prueba con una tabla de casos.

## La tercera categoría de la existencia, que es donde se cuelan los errores

El ticket dice *el más barato **con existencia** viene marcado*. Suena a dos
categorías y son tres:

| Lo que dijo el portal | Qué se sabe | ¿Puede ganar? |
|---|---|---|
| `40`, `+100`, `0.5` | lo tiene | sí, con la marca entera |
| `0` | **no** lo tiene | no, nunca |
| nada, `"Bajo pedido"`, `"SI"` | no se sabe | solo si nadie confirmó |

La tercera es la peligrosa. Tratarla como "no lo tiene" escondería al proveedor
más barato de la fila —y los portales dicen la existencia con palabras a
menudo: `precios.existencia_a_numero` devuelve `None` justo para eso—.
Tratarla como "lo tiene" pondría la marca de *con existencia* sobre algo que
ningún portal afirmó, y esa marca es la que decide la compra.

**La decisión: no compite con quien sí la confirmó, pero no desaparece.** Si
alguien confirmó existencia, gana el más barato de ésos aunque haya uno más
barato que no dijo nada —y el que no dijo nada sigue en la fila, con su precio
a la vista y su estado escrito—. Si **nadie** confirmó, gana igual el más
barato de los que no dijeron, pero con otra certeza
(`GANADOR_SIN_CONFIRMAR`), que la pantalla escribe con otras palabras. Dejar
el renglón sin ganador en ese caso sería esconder el único dato que hay; darle
la marca de "con existencia" sería inventarse una confirmación.

## El ahorro contra NADRO, y qué pasa cuando NADRO no tiene precio

La referencia es NADRO porque es contra quien se mide de verdad: hoy *el pedido
a NADRO se arma de memoria y de anaquel* (ADR 0002). El ahorro es lo que se deja
de gastar en **este renglón** por comprarle al ganador en vez de a NADRO, así
que es `piezas × (precio de NADRO − precio del ganador)`.

Las piezas son `RenglonGuardado.cantidad_a_pedir` —la corrección de la persona
si la hubo, y si no la propuesta del sistema—. Esa regla **no se repite aquí**:
entra por argumento ya resuelta, porque una regla escrita dos veces se cambia
una sola.

**Cuando NADRO no dio precio no hay ahorro, y no es cero.** Es la trampa más
cara de este módulo y va a pasar seguido —la sesión caducada, el portal caído,
el producto que no está en ese catálogo—. Un `0.00` ahí se lee *"da lo mismo a
quién comprarle"*, que es lo contrario de lo que ocurre: no se sabe cuánto
cobra NADRO hoy, así que no hay contra qué medir. Sale `None` **con el motivo
de NADRO al lado**, que es lo que le dice al encargado si puede arreglarlo. Y el
renglón no se esconde: el ganador sigue marcado y su precio sigue a la vista —lo
que falta es la comparación, no la fila (regla 4 de `CLAUDE.md`)—.

Hay **un cero legítimo** y se distingue del anterior: cuando NADRO es el
ganador. Ahí la resta sí se pudo hacer y su resultado es cero, porque cambiar de
proveedor no ahorraría nada. Viaja con `la_referencia_gana`, para que la
pantalla escriba "NADRO ya es el más barato" en vez de un `$0.00` que se lee
como un hueco.

Y hay un **negativo**, que tampoco es un ahorro: NADRO barato y agotado, el
ganador caro y con existencia. Se paga de más por comprarle a quien sí lo tiene.
Se dice así, con `es_sobrecosto`, y no como "ahorro de −$180.99".

## La trampa del IVA

`CLAUDE.md`: *el costo nuestro es sin IVA y el de mostrador con IVA; nunca
restes las dos cifras directo — Marlowe ya se equivocó así y la flecha apuntaba
al revés*. Aquí eso se cumple por construcción y no por cuidado: **lo único que
se resta son dos precios de proveedor**, los dos precio de compra y los dos sin
IVA. El `precio_lista_sin_iva` del catálogo y el costo de SICAR no entran a
estas funciones — ni siquiera están en sus firmas, así que no hay por dónde
colarlos. El día que alguien quiera comparar contra el mostrador, eso es otra
cuenta, con otro nombre y con el IVA puesto a mano de un lado.

## `Decimal` de punta a punta

El dinero no pasa por coma flotante ni para multiplicarse por las piezas: en
`float`, `0.1 * 3` es `0.30000000000000004` y el total de un pedido deja de
cuadrar contra la factura por centavos que nadie puede explicar. Entra `Decimal`
de `precios.precio_a_numero`, se opera en `Decimal`, y al navegador sale como
**cadena**, porque el JSON de JavaScript solo tiene `double`.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from continental.almacenamiento import PrecioDeProveedor
from continental.precios import (
    NOMBRES_DE_PROVEEDOR,
    explicacion_del_motivo,
    nombre_del_proveedor,
)

# --------------------------------------------------------------- la referencia

#: Contra quién se mide el ahorro. Es NADRO porque es contra quien se mide de
#: verdad: hoy el pedido a NADRO se arma de memoria y de anaquel (ADR 0002), así
#: que "cuánto se ahorra" quiere decir "cuánto se deja de gastar respecto de lo
#: que se habría comprado igual".
REFERENCIA = "nadro"

#: El orden en que se pintan los cuatro, y es **fijo**. Ordenarlos por precio
#: dejaría a cada renglón con las columnas cambiadas de sitio, y comparar dos
#: renglones de la lista —que es lo que el encargado hace todo el tiempo—
#: exigiría leer los nombres cada vez. La referencia va primero porque es contra
#: quien se compara todo lo demás.
ORDEN_DE_LA_FILA: tuple[str, ...] = (REFERENCIA,) + tuple(
    clave for clave in NOMBRES_DE_PROVEEDOR if clave != REFERENCIA
)


# ------------------------------------------------- los estados de un proveedor
#
# Cinco y no dos, porque cinco son las cosas distintas que le pueden pasar a un
# proveedor en un renglón y cada una se atiende de otra manera. Son constantes y
# no cadenas sueltas por la misma razón que los motivos de `precios.py`: viajan
# hasta el JavaScript de la pantalla y una prueba los compara.

#: Dio precio y **confirmó** que lo tiene: un número mayor que cero.
CON_EXISTENCIA = "con existencia"

#: Dio precio y dijo que tiene **cero**. Es un dato de verdad —no lo tiene— y
#: no se parece en nada a un hueco. Este proveedor no puede ganar.
SIN_EXISTENCIA = "sin existencia"

#: Dio precio y **no dijo** cuánto tiene, o lo dijo con palabras ("Bajo
#: pedido", "SI"). No es "no lo tiene" y no es "lo tiene": es la tercera
#: categoría, y el porqué de cómo se trata está arriba.
EXISTENCIA_SIN_DECIR = "no dijo existencia"

#: Contestó y no hubo precio. El motivo vive en la lectura (`precios.MOTIVOS`) y
#: es lo que distingue un hueco que el encargado puede atender de uno que no.
SIN_PRECIO = "sin precio"

#: No hay ninguna lectura de este proveedor para este renglón. **No es lo mismo
#: que "sin dato"**: aquí nadie preguntó todavía. Contarlos es el ticket 15.
SIN_CONSULTAR = "sin consultar"


# ------------------------------------------------------- la certeza del ganador

#: El más barato de los que **confirmaron** existencia. Es la marca entera.
GANADOR_CON_EXISTENCIA = "el más barato con existencia"

#: El más barato de los que dieron precio cuando **ninguno** dijo su existencia.
#: Se marca igual —esconderlo sería tirar el único dato que hay— pero con otras
#: palabras: nadie afirmó tenerlo.
GANADOR_SIN_CONFIRMAR = "el más barato, pero nadie confirmó existencia"

#: **Hubo un solo precio en todo el renglón.** Es la casilla del ticket 15 que
#: el 14 dejó incumplida a propósito: *un renglón comparado contra un solo
#: proveedor no se presenta como "el más barato": se presenta como "el único que
#: contestó"*.
#:
#: No es una pega de redacción. "El más barato" es un **superlativo**, y un
#: superlativo afirma algo sobre los otros tres: que se miraron y que costaban
#: más. Con una sola lectura eso no se miró, así que la frase dice algo que
#: nadie comprobó — y el encargado la lee como si hubiera visto cuatro precios
#: cuando vio uno. El precio sigue a la vista y el proveedor sigue marcado: lo
#: que cambia es lo que se afirma de él.
GANADOR_UNICO = "el único que contestó"

#: Lo mismo, y encima ese único no dijo cuántas piezas tiene. Son **dos**
#: cosas que faltan y por eso es una certeza propia y no la anterior: colapsar
#: las dos en "el único que contestó" callaría justo la advertencia ámbar en el
#: caso peor informado de todos (regla 4 de `CLAUDE.md`, el hueco con su
#: motivo).
GANADOR_UNICO_SIN_CONFIRMAR = "el único que contestó, y no dijo si lo tiene"

#: Las dos certezas de un solo precio. Existe para que `es_unico` no compare
#: cadenas sueltas y para que una prueba pueda recorrerlas.
CERTEZAS_DE_UN_SOLO_PRECIO: tuple[str, ...] = (
    GANADOR_UNICO,
    GANADOR_UNICO_SIN_CONFIRMAR,
)

#: Las dos certezas en las que un portal **confirmó** la existencia del ganador.
#: Es otro eje que el de arriba y se cruzan: el ganador puede ser el único y
#: haber confirmado, o ser uno de cuatro y no haberlo dicho.
CERTEZAS_CON_EXISTENCIA: tuple[str, ...] = (
    GANADOR_CON_EXISTENCIA,
    GANADOR_UNICO,
)

#: Cuántos precios hacen falta para que haya **comparación**. Dos, porque
#: comparar es poner uno al lado de otro: con un solo precio no hay contra qué
#: medirlo. Es el número que parte la lista en "comparados" y "sin comparar", y
#: vive aquí —con nombre— porque un `>= 2` suelto en cuatro sitios se cambia en
#: tres.
MINIMO_PARA_COMPARAR = 2


# ------------------------------------------- por qué a veces no hay ganador

#: Ni una lectura: este renglón no se ha consultado.
NADIE_CONSULTO = "todavía no se le ha consultado el precio"

#: Contestaron y ninguno dio precio. Cada hueco trae su motivo en su casilla.
NADIE_DIO_PRECIO = "ninguno de los proveedores dio precio"

#: Hubo precios, y **todos** los que lo dieron reportan cero existencia. El
#: renglón se ve entero, con sus precios, y sin ganador: comprarle a quien no lo
#: tiene no es comprar.
NINGUNO_LO_TIENE = "los que dieron precio no lo tienen"


# ------------------------------------- por qué un renglón se quedó sin comparar
#
# Las tres maneras de no tener comparación, y son tres porque **el encargado
# las arregla distinto**. Un solo número —"12 sin comparar"— diría cuánto falta
# y nada de qué hacer; tres dicen a qué se parece ese hueco.
#
# Y las tres son "sin comparar" de verdad, no una gradación amable: de ninguna
# de ellas salió una cifra puesta al lado de otra, que es lo único que este
# módulo llama comparar.

#: Nadie le preguntó el precio a este renglón. Es el más numeroso hoy —hasta el
#: lote de la noche (ticket 18) el precio se pide renglón por renglón— y el más
#: fácil de atender: es un botón.
SIN_CONSULTAR_EL_RENGLON = "no se le ha consultado el precio"

#: Se le preguntó y **ninguno** de los proveedores dio precio. No es lo mismo
#: que el anterior ni de lejos: aquí ya se molestó a los portales y cada hueco
#: trae su motivo, que es lo que dice si se puede hacer algo (la sesión caducada
#: se abre, el portal caído se reintenta, "no está en ese catálogo" no).
NINGUN_PRECIO = "se consultó y ninguno dio precio"

#: Hay **un** precio y nada contra qué medirlo. Es el caso que el ticket nombra
#: con todas sus letras: ese precio no es "el más barato", es el único que
#: contestó. No hay nada que arreglar —el dato está— y aun así cuenta como sin
#: comparar, porque una decisión de compra tomada sobre él se tomó sobre una
#: sola cotización.
UN_SOLO_PRECIO = "un solo proveedor dio precio"

#: Los tres, en el orden en que se dicen en la pantalla: de "falta todo" a
#: "falta el contraste".
MOTIVOS_DE_SIN_COMPARAR: tuple[str, ...] = (
    SIN_CONSULTAR_EL_RENGLON,
    NINGUN_PRECIO,
    UN_SOLO_PRECIO,
)


# --------------------------------------- por qué a veces no hay ahorro

#: No hay ganador, así que no hay contra qué restar.
AHORRO_SIN_GANADOR = "no hay proveedor al que comprarle"

#: A la referencia no se le consultó. Distinto de que no haya contestado:
#: "no contestó" se reintenta, "no se preguntó" se pregunta.
REFERENCIA_SIN_CONSULTAR = "no se le consultó el precio a NADRO"

#: La referencia contestó y no dio precio. **Aquí el ahorro es `None`, jamás un
#: cero.** El motivo de NADRO viaja en `detalle` para que se pueda atender.
REFERENCIA_SIN_PRECIO = "NADRO no dio precio"

#: No se supo cuántas piezas se van a pedir —el renglón no se pudo releer—. El
#: ahorro por pieza sí se dice: no depende de la cantidad y sigue siendo verdad.
AHORRO_SIN_CANTIDAD = "no se sabe cuántas piezas se van a pedir"


#: Los dos decimales de `numeric(12,2)`. Se cuantiza el total por la misma razón
#: que `precios.py` cuantiza el precio: que el resultado tenga exactamente la
#: escala con la que se va a pintar y a sumar.
_CENTAVOS = Decimal("0.01")


# ------------------------------------------------------------------ los datos


@dataclass(frozen=True, slots=True)
class Ganador:
    """Quién gana este renglón, o por qué no gana nadie.

    `proveedores` es una **tupla** y no un nombre suelto porque un empate es dos
    opciones, no una con desempate inventado. Elegir uno por orden alfabético
    diría "éste es el más barato" sobre una decisión que el sistema no tomó; el
    ADR 0002 ya dice que la suite propone y la persona elige, que hay razones que
    el sistema no ve —mínimo de pedido, días de entrega, crédito—.

    `certeza` dice **de qué tipo** es la marca, y son cuatro porque se cruzan
    dos preguntas que no son la misma: *¿confirmó alguien la existencia?* y
    *¿hubo con qué comparar?*

    | | confirmó existencia | no la dijo |
    |---|---|---|
    | dos o más precios | `GANADOR_CON_EXISTENCIA` | `GANADOR_SIN_CONFIRMAR` |
    | un solo precio | `GANADOR_UNICO` | `GANADOR_UNICO_SIN_CONFIRMAR` |

    **La segunda fila es el ticket 15.** Un renglón con una sola lectura no
    tiene "el más barato" porque no hay contra qué serlo, y la certeza lo dice
    con las palabras del ticket: *el único que contestó*. La frase es un dato
    puro y viaja hecha —la pantalla la escribe tal cual— para que la regla que
    decide qué se afirma de un proveedor no viva en el único archivo que
    ninguna prueba de Python mira.

    `motivo` solo viene cuando no hay ganador, y viene **siempre** que no lo hay:
    una fila sin marca y sin explicación se lee como un error de la pantalla.
    """

    proveedores: tuple[str, ...] = ()
    precio: Decimal | None = None
    certeza: str | None = None
    motivo: str | None = None

    @property
    def hay(self) -> bool:
        """Si alguien ganó."""
        return bool(self.proveedores)

    @property
    def con_existencia(self) -> bool:
        """Si un portal **confirmó** que el ganador lo tiene.

        Es una de las dos preguntas de la tabla de arriba y solo ésa: un
        ganador único que confirmó existencia la cumple, aunque no sea "el más
        barato" de nada. Mezclar los dos ejes aquí obligaría a la pantalla a
        deducir el otro comparando cadenas.
        """
        return self.certeza in CERTEZAS_CON_EXISTENCIA

    @property
    def es_unico(self) -> bool:
        """Si fue **el único** que dio precio en todo el renglón.

        La otra pregunta. Es lo que decide que la marca diga *el único que
        contestó* en vez de *el más barato*, y lo que hace que la fila no se vea
        verde entera: un solo precio no es una comparación, y una lista donde
        todo sale en verde se lee como completa.
        """
        return self.certeza in CERTEZAS_DE_UN_SOLO_PRECIO


@dataclass(frozen=True, slots=True)
class Ahorro:
    """Cuánto se deja de gastar en este renglón, o por qué no se puede saber.

    `total is None` **siempre viene con `motivo`**, igual que un precio faltante
    viene con el suyo. Es la misma regla y por la misma razón: un `None` mudo se
    ve idéntico a un cero en la pantalla, y aquí el cero miente.

    `la_referencia_gana` existe para distinguir el único cero legítimo —NADRO es
    el más barato— del `None`. Sin esa bandera, la pantalla tendría que comparar
    nombres para saber qué escribir.
    """

    cantidad: int | None = None
    precio_de_referencia: Decimal | None = None
    por_pieza: Decimal | None = None
    total: Decimal | None = None
    motivo: str | None = None
    detalle: str | None = None
    la_referencia_gana: bool = False

    @property
    def hay(self) -> bool:
        """Si la resta se pudo hacer, sea cual sea su signo."""
        return self.total is not None

    @property
    def es_ahorro(self) -> bool:
        """Si de verdad se ahorra algo. Un cero **no** es un ahorro."""
        return self.total is not None and self.total > 0

    @property
    def es_sobrecosto(self) -> bool:
        """Si comprarle al ganador cuesta MÁS que la referencia.

        Pasa cuando NADRO es más barato y está agotado. No es un ahorro
        negativo: es lo que cuesta de más comprarle a quien sí lo tiene, y se
        dice con esas palabras o la flecha apunta al revés.
        """
        return self.total is not None and self.total < 0


@dataclass(frozen=True, slots=True)
class Casilla:
    """Un proveedor dentro de la fila: cómo se ve y qué se sabe de él.

    Es lo que la pantalla pinta, ya resuelto en Python. `estado` es una de las
    cinco constantes de arriba y `diferencia` es cuánto más caro es que el
    ganador, **por pieza**, o `None` cuando no hay resta que hacer —sin precio,
    sin ganador, o siendo el ganador mismo—. Restar contra algo que no se sabe no
    da un número (regla 4 de `CLAUDE.md`).
    """

    proveedor: str
    estado: str
    es_ganador: bool = False
    precio: Decimal | None = None
    diferencia: Decimal | None = None
    existencia_como_llego: str = ""
    motivo: str | None = None

    @property
    def nombre(self) -> str:
        """Cómo se escribe, según el glosario."""
        return nombre_del_proveedor(self.proveedor)

    @property
    def mas_barato_que_el_ganador(self) -> bool:
        """Si cuesta MENOS que el que ganó. Pasa, y es información, no un error.

        El ganador es el más barato **de los que lo tienen**, así que un
        proveedor con cero piezas puede ser más barato y no haber ganado. Su
        diferencia sale negativa, y la pantalla tiene que escribir "$60.33 más
        barato, pero no lo tiene" y no "+$-60.33".

        Se decide aquí y no en el JavaScript por la misma razón que todo lo
        demás: comparar el signo de una cadena del otro lado es aritmética, y la
        aritmética de este módulo se prueba. Se descubrió en el recorrido del
        navegador del 2026-09-19, donde la pantalla escribió `+-60.33`.
        """
        return self.diferencia is not None and self.diferencia < 0


@dataclass(frozen=True, slots=True)
class Comparacion:
    """La fila entera de un renglón: los cuatro, el ganador, el ahorro y la fecha.

    `leido_en` es el instante **más reciente** de las lecturas que se están
    comparando, e `instantes_distintos` dice si no todas son de ahí. Las dos
    cosas juntas son la sexta casilla del ticket: la comparación usa el precio
    congelado y su fecha se ve. Enseñar una sola fecha cuando hay de varias diría
    que una lectura de hace tres semanas es de hoy — y eso pasa en cuanto alguien
    vuelve a consultar y solo dos proveedores contestan.
    """

    ganador: Ganador
    ahorro: Ahorro
    por_proveedor: tuple[Casilla, ...] = ()
    leido_en: dt.datetime | None = None
    instantes_distintos: bool = False
    consultados: int = 0
    con_precio: int = 0

    @property
    def hay_lecturas(self) -> bool:
        """Si a este renglón se le consultó el precio alguna vez."""
        return self.consultados > 0

    @property
    def se_comparo(self) -> bool:
        """Si de este renglón salió una **comparación**: dos precios o más.

        Es el corte del ticket 15, y no se mide con `consultados`: preguntarle
        a cuatro portales y que los cuatro devuelvan hueco es haber consultado,
        no haber comparado. Lo que hace comparado a un renglón es que haya dos
        cifras que poner una al lado de otra.
        """
        return self.con_precio >= MINIMO_PARA_COMPARAR

    @property
    def por_que_no_se_comparo(self) -> str | None:
        """Cuál de las tres situaciones de "sin comparar" es ésta, o `None`.

        Tres y no una, porque **cada una se arregla distinto** y ésa es la
        única razón por la que un conteo se desglosa:

        - `SIN_CONSULTAR_EL_RENGLON` — nadie preguntó. Se arregla apretando el
          botón, o dejándoselo al lote de la noche (ticket 18).
        - `NINGUN_PRECIO` — se preguntó y ninguno de los cuatro dio precio. Se
          arregla —o no— según el motivo de cada hueco: la sesión caducada son
          dos clics, el portal caído es reintentar, y "no está en ese catálogo"
          no lo arregla nadie.
        - `UN_SOLO_PRECIO` — hay precio, pero no hay comparación. **No es un
          hueco que arreglar**: es una advertencia sobre lo que ese precio puede
          afirmar de sí mismo.
        """
        if self.se_comparo:
            return None
        if self.consultados == 0:
            return SIN_CONSULTAR_EL_RENGLON
        return NINGUN_PRECIO if self.con_precio == 0 else UN_SOLO_PRECIO


@dataclass(frozen=True, slots=True)
class ConteoDeLaLista:
    """Cuántos renglones de la lista se compararon de verdad, y cuántos no.

    Es la primera casilla del ticket 15 —*se ve cuántos renglones quedaron sin
    comparar*— y el número que impide que alguien lea la lista como si
    estuviera completa. El otro número que pide esa casilla —*contra cuántos
    proveedores se comparó cada uno*— es de renglón y ya viaja en
    `Comparacion.consultados` y `Comparacion.con_precio`: son dos preguntas
    distintas y por eso son dos números en dos sitios distintos de la pantalla.

    **El desglose no es adorno.** `sin_comparar` es uno solo para el vistazo de
    arriba, pero se atiende de tres maneras que no se parecen —ver
    `MOTIVOS_DE_SIN_COMPARAR`—, y un total sin desglose manda al encargado a
    mirar renglón por renglón para saber cuál de las tres le tocó. Los tres
    suman exactamente `sin_comparar` y hay una prueba que lo fija: un conteo que
    no cuadra consigo mismo es peor que no tenerlo.

    **Se cuenta sobre los renglones de trabajo**, no sobre la lista entera. El
    porqué está en `contar_la_lista`.
    """

    renglones: int = 0
    comparados: int = 0
    sin_consultar: int = 0
    sin_un_solo_precio: int = 0
    con_un_solo_precio: int = 0

    @property
    def sin_comparar(self) -> int:
        """Los que no tienen dos precios que poner uno al lado de otro.

        Se deriva de los tres y no se guarda aparte: dos números que tienen que
        coincidir y se calculan por separado dejan de coincidir el día que
        alguien agregue un cuarto caso y se olvide de sumarlo.
        """
        return self.sin_consultar + self.sin_un_solo_precio + self.con_un_solo_precio

    @property
    def hay_sin_comparar(self) -> bool:
        """Si queda algo sin comparar. Es lo que decide si se avisa o se
        confirma, y las dos frases se escriben: **callar cuando está todo
        comparado dejaría el silencio con dos significados** —"ya está" y "esta
        pantalla no lo cuenta"— y el encargado no puede distinguirlos."""
        return self.sin_comparar > 0


# ------------------------------------------------------------- las funciones


def estado_del_proveedor(lectura: PrecioDeProveedor | None) -> str:
    """En cuál de las cinco situaciones está este proveedor para este renglón.

    `None` es "no hay lectura" y sale `SIN_CONSULTAR`, que **no** es lo mismo que
    "sin dato": uno es un portal al que no se le preguntó y el otro uno que
    contestó sin precio. Se arreglan distinto, así que se dicen distinto.

    Sin precio le gana a cualquier cosa que diga la existencia, y no es un
    empate de categorías: si no se sabe a cuánto, cuántas piezas haya no decide
    nada.
    """
    if lectura is None:
        return SIN_CONSULTAR
    if lectura.precio is None:
        return SIN_PRECIO
    if lectura.existencia is None:
        return EXISTENCIA_SIN_DECIR
    return CON_EXISTENCIA if lectura.existencia > 0 else SIN_EXISTENCIA


def elegir_ganador(lecturas: Sequence[PrecioDeProveedor]) -> Ganador:
    """El más barato **de los que lo tienen**, o por qué no hay ninguno.

    La tabla de casos, en orden de cómo se resuelve:

    | Lecturas | Resultado |
    |---|---|
    | ninguna | sin ganador, `NADIE_CONSULTO` |
    | ninguna con precio | sin ganador, `NADIE_DIO_PRECIO` |
    | alguna con existencia confirmada | el más barato **de ésas**, marca entera |
    | ninguna confirmada, alguna sin decir | el más barato de ésas, `GANADOR_SIN_CONFIRMAR` |
    | todas las que dieron precio en cero | sin ganador, `NINGUNO_LO_TIENE` |

    La tercera fila es la que importa: **un precio más bajo sin existencia
    confirmada no le gana a uno más alto que sí la confirmó.** Es literal la
    segunda casilla del ticket 14 —*el más barato con existencia*— y la cuarta
    —*el más barato no sirve si no lo tiene*—. El proveedor descartado no
    desaparece: sigue en la fila con su precio, y la persona puede llamarle si
    quiere.

    **Y encima de todo eso va el ticket 15**: si el precio fue **uno solo**, el
    que gana no se presenta como "el más barato" sino como *el único que
    contestó*. Quién gana no cambia —sigue siendo el mismo proveedor, con el
    mismo precio y la misma existencia—; cambia lo que se **afirma** de él. La
    elección y la frase salen de la misma función a propósito: separarlas
    dejaría la frase en la ruta o en el JavaScript, que es donde nadie la
    prueba.
    """
    if not lecturas:
        return Ganador(motivo=NADIE_CONSULTO)

    con_precio = [l for l in lecturas if l.precio is not None]
    if not con_precio:
        return Ganador(motivo=NADIE_DIO_PRECIO)

    confirmados = [l for l in con_precio if estado_del_proveedor(l) == CON_EXISTENCIA]
    sin_decir = [l for l in con_precio if estado_del_proveedor(l) == EXISTENCIA_SIN_DECIR]

    elegibles = confirmados or sin_decir
    if not elegibles:
        return Ganador(motivo=NINGUNO_LO_TIENE)

    barato = min(l.precio for l in elegibles)

    # Las dos preguntas, por separado, y después la certeza que les corresponde.
    # `unico` se mide sobre **todas** las lecturas con precio y no sobre las
    # elegibles: un renglón donde NADRO dio precio con cero piezas y LEVIC dio
    # precio con cuarenta SÍ se comparó —se vieron dos precios—, aunque solo uno
    # pudiera ganar. Medirlo sobre las elegibles diría "el único que contestó"
    # sobre un renglón con dos cifras a la vista, y eso se lee como un error de
    # la pantalla.
    if len(con_precio) < MINIMO_PARA_COMPARAR:
        certeza = GANADOR_UNICO if confirmados else GANADOR_UNICO_SIN_CONFIRMAR
    else:
        certeza = GANADOR_CON_EXISTENCIA if confirmados else GANADOR_SIN_CONFIRMAR

    return Ganador(
        proveedores=tuple(sorted(l.proveedor for l in elegibles if l.precio == barato)),
        precio=barato,
        certeza=certeza,
    )


def calcular_ahorro(
    lecturas: Sequence[PrecioDeProveedor],
    ganador: Ganador,
    cantidad: int | None,
) -> Ahorro:
    """Piezas × (precio de NADRO − precio del ganador), o el motivo de que no.

    `cantidad` es lo que de verdad se va a pedir y llega **ya resuelto**
    (`RenglonGuardado.cantidad_a_pedir`): la regla de si manda la propuesta del
    sistema o la corrección de la persona vive ahí y no se repite aquí.

    Las dos cifras que se restan son precios de **compra** de proveedor, las dos
    sin IVA. Nada de esta función ve el precio de mostrador, que lleva IVA — ni
    siquiera está en la firma. Restarlos sería la flecha al revés de `CLAUDE.md`.

    Los cuatro finales sin número, y por qué cada uno es distinto:

    - `AHORRO_SIN_GANADOR` — nadie a quien comprarle, no hay contra qué restar.
    - `REFERENCIA_SIN_CONSULTAR` — a NADRO no se le preguntó.
    - `REFERENCIA_SIN_PRECIO` — NADRO contestó sin precio. **Nunca un cero**:
      un cero diría "da lo mismo a quién comprarle" y lo cierto es que no se
      sabe. El motivo de NADRO va en `detalle`.
    - `AHORRO_SIN_CANTIDAD` — no se supo cuántas piezas. El ahorro por pieza sí
      se dice: no depende de la cantidad.
    """
    if not ganador.hay or ganador.precio is None:
        return Ahorro(cantidad=cantidad, motivo=AHORRO_SIN_GANADOR)

    referencia = next((l for l in lecturas if l.proveedor == REFERENCIA), None)
    if referencia is None:
        return Ahorro(cantidad=cantidad, motivo=REFERENCIA_SIN_CONSULTAR)

    if referencia.precio is None:
        return Ahorro(
            cantidad=cantidad,
            motivo=REFERENCIA_SIN_PRECIO,
            detalle=referencia.motivo,
        )

    por_pieza = (referencia.precio - ganador.precio).quantize(_CENTAVOS)
    gana_la_referencia = REFERENCIA in ganador.proveedores

    if cantidad is None:
        return Ahorro(
            precio_de_referencia=referencia.precio,
            por_pieza=por_pieza,
            motivo=AHORRO_SIN_CANTIDAD,
            la_referencia_gana=gana_la_referencia,
        )

    return Ahorro(
        cantidad=cantidad,
        precio_de_referencia=referencia.precio,
        por_pieza=por_pieza,
        total=(por_pieza * cantidad).quantize(_CENTAVOS),
        la_referencia_gana=gana_la_referencia,
    )


def _orden_de_la_fila(lecturas: Sequence[PrecioDeProveedor]) -> tuple[str, ...]:
    """Los cuatro del glosario, y detrás cualquier otro que haya contestado.

    Un proveedor que Doyle estrene y que el mapa de nombres todavía no conozca
    se ve igual, al final: nada se cae de la pantalla por no reconocerse (regla
    4 de `CLAUDE.md`).
    """
    extras = sorted({l.proveedor for l in lecturas} - set(ORDEN_DE_LA_FILA))
    return ORDEN_DE_LA_FILA + tuple(extras)


def comparar(
    lecturas: Sequence[PrecioDeProveedor], cantidad: int | None = None
) -> Comparacion:
    """La fila entera: los cuatro, quién gana, cuánto se ahorra y de cuándo es.

    **Los cuatro siempre**, aunque solo dos hayan contestado: es la primera
    casilla del ticket. Un proveedor sin lectura sale con `SIN_CONSULTAR` en vez
    de no salir — si la fila solo trajera a los que contestaron, un renglón con
    dos huecos se vería idéntico a uno comparado contra dos proveedores, y son
    dos cosas distintas.

    Un renglón que nadie consultó devuelve la fila **vacía** y no cuatro
    casillas de "sin consultar": ahí lo que hay que enseñar es el botón, no una
    tabla de nadas.
    """
    ganador = elegir_ganador(lecturas)
    ahorro = calcular_ahorro(lecturas, ganador, cantidad)

    por_clave = {l.proveedor: l for l in lecturas}
    casillas: list[Casilla] = []
    if lecturas:
        for proveedor in _orden_de_la_fila(lecturas):
            lectura = por_clave.get(proveedor)
            es_ganador = proveedor in ganador.proveedores
            diferencia = None
            if (
                lectura is not None
                and lectura.precio is not None
                and ganador.precio is not None
                and not es_ganador
            ):
                diferencia = (lectura.precio - ganador.precio).quantize(_CENTAVOS)
            casillas.append(
                Casilla(
                    proveedor=proveedor,
                    estado=estado_del_proveedor(lectura),
                    es_ganador=es_ganador,
                    precio=None if lectura is None else lectura.precio,
                    diferencia=diferencia,
                    existencia_como_llego=(
                        "" if lectura is None else lectura.existencia_como_llego
                    ),
                    motivo=None if lectura is None else lectura.motivo,
                )
            )

    instantes = {l.consultado_en for l in lecturas}
    return Comparacion(
        ganador=ganador,
        ahorro=ahorro,
        por_proveedor=tuple(casillas),
        leido_en=max(instantes) if instantes else None,
        instantes_distintos=len(instantes) > 1,
        consultados=len(lecturas),
        con_precio=sum(1 for l in lecturas if l.precio is not None),
    )


def contar_la_lista(comparaciones: Iterable[Comparacion]) -> ConteoDeLaLista:
    """Las comparaciones de una lista → cuántas lo son de verdad y cuántas no.

    ## Dónde vive este conteo, y por qué aquí

    Había tres sitios posibles y el repositorio ya usa dos de ellos:

    1. **Una propiedad de `PedidoSugeridoGuardado`**, como `sin_catalogo`,
       `sin_clasificar` y `descartados`. Esas tres se calculan sobre los
       renglones que el propio dato ya trae dentro; ésta no puede, porque
       depende de `precios_de_la_lista`, que es **otra lectura**. Ponerla ahí
       obligaría a una de dos cosas malas: meter los precios dentro del objeto
       que representa "la lista tal como se guardó" —que no los tiene, y que se
       arma en `armar_guardado` con cabecera y filas— o dejar que una propiedad
       abra una conexión. Lo segundo es peor: una propiedad que consulta es una
       consulta que nadie ve al leer el código que la usa.
    2. **Armarlo en la ruta.** Es donde los dos datos se encuentran, pero
       entonces la regla de qué cuenta como "sin comparar" viviría dentro de un
       `if` de FastAPI y solo se podría probar levantando la aplicación. Es
       exactamente lo que `comparacion.py` existe para no hacer.
    3. **Una función pura aquí**, junto a `comparar`. La ruta trae las dos
       lecturas —ya las hace las dos— y las junta; la regla se prueba con una
       tabla de casos y sin `TestClient`.

    Se eligió la 3, y la consecuencia de elegirla está a la vista: la ruta tiene
    que pasarle las comparaciones, que es una línea, y a cambio el corte de "dos
    precios o más" se puede cambiar en un solo sitio probado.

    ## Qué entra al conteo

    **Los renglones de trabajo, no todos.** Un renglón descartado ya se
    atendió: alguien lo miró y decidió no pedirlo, así que no falta comparar
    nada de él. Contarlo mandaría al encargado a conseguir precios de mercancía
    que nadie va a comprar, y —peor— el número seguiría subiendo justo mientras
    la lista se va resolviendo.

    Se aparta a propósito de `sin_clasificar`, que **sí** se cuenta sobre la
    lista entera: esa pregunta es sobre el catálogo de SICAR ("¿vale la pena
    ponerles anaquel?") y no cambia porque alguien descarte un renglón hoy.
    Ésta es sobre la compra que se está por decidir.

    Quién es "de trabajo" lo decide `PedidoSugeridoGuardado.de_trabajo`, que ya
    es la regla probada: aquí solo se cuenta lo que llega.
    """
    conteo = {
        SIN_CONSULTAR_EL_RENGLON: 0,
        NINGUN_PRECIO: 0,
        UN_SOLO_PRECIO: 0,
    }
    renglones = 0
    comparados = 0
    for comparacion in comparaciones:
        renglones += 1
        porque = comparacion.por_que_no_se_comparo
        if porque is None:
            comparados += 1
        else:
            conteo[porque] += 1

    return ConteoDeLaLista(
        renglones=renglones,
        comparados=comparados,
        sin_consultar=conteo[SIN_CONSULTAR_EL_RENGLON],
        sin_un_solo_precio=conteo[NINGUN_PRECIO],
        con_un_solo_precio=conteo[UN_SOLO_PRECIO],
    )


def _cadena(valor: Decimal | None) -> str | None:
    """Un `Decimal` al navegador: **cadena** o `None`, jamás un número de JSON.

    El JSON de JavaScript solo tiene `double`. Mandar `180.99` como número lo
    mete en coma flotante justo en el borde donde acababa de salir, que es la
    falla que el `numeric(12,2)` del DDL existe para evitar. Como cadena se
    pinta tal cual.
    """
    return None if valor is None else str(valor)


def comparacion_como_json(comparacion: Comparacion) -> dict:
    """La comparación como la pantalla la lee. Vive aquí y no en el JavaScript.

    Ninguna cifra se recalcula del otro lado: el navegador pinta lo que llega y
    pregunta por banderas (`es_ganador`, `es_ahorro`, `la_referencia_gana`), no
    por números que tendría que comparar él. Es el mismo criterio que
    `consultas.lecturas_como_json` y que las vistas del ticket 06 — la regla se
    prueba en Python, la pantalla la obedece.
    """
    return {
        "hay_lecturas": comparacion.hay_lecturas,
        # Los dos números por renglón de la primera casilla del ticket 15:
        # a cuántos se les preguntó y cuántos contestaron con una cifra. Van
        # los dos porque son dos hechos —"se preguntó a cuatro y contestaron
        # dos" no es "se preguntó a dos"— y porque se arreglan distinto.
        "consultados": comparacion.consultados,
        "con_precio": comparacion.con_precio,
        # Si de este renglón salió una comparación de verdad, y cuál de las
        # tres situaciones es si no. Resueltos aquí y no en el JavaScript con
        # un `>= 2`: es el corte que decide qué se le puede llamar "el más
        # barato", y vive en un solo sitio probado.
        "se_comparo": comparacion.se_comparo,
        "por_que_no_se_comparo": comparacion.por_que_no_se_comparo,
        "leido_en": (
            None if comparacion.leido_en is None else comparacion.leido_en.isoformat()
        ),
        "instantes_distintos": comparacion.instantes_distintos,
        "referencia": REFERENCIA,
        "nombre_de_la_referencia": nombre_del_proveedor(REFERENCIA),
        "ganador": {
            "proveedores": list(comparacion.ganador.proveedores),
            "nombres": [
                nombre_del_proveedor(p) for p in comparacion.ganador.proveedores
            ],
            "precio": _cadena(comparacion.ganador.precio),
            # La frase de la marca viaja **hecha**, y la pantalla la escribe
            # tal cual. Hasta el ticket 14 el JavaScript elegía entre dos
            # cadenas suyas mirando `con_existencia`, y por eso un renglón con
            # una sola lectura salía rotulado "el más barato con existencia":
            # la afirmación que el ticket 15 prohíbe vivía en el único archivo
            # que ninguna prueba de Python mira.
            "certeza": comparacion.ganador.certeza,
            "con_existencia": comparacion.ganador.con_existencia,
            # Los dos ejes van por separado —confirmó existencia, y fue el
            # único— porque la pantalla necesita los dos para decidir el color:
            # el verde entero es solo para el más barato de varios que además
            # confirmó tenerlo.
            "es_unico": comparacion.ganador.es_unico,
            "motivo": comparacion.ganador.motivo,
        },
        "ahorro": {
            "hay": comparacion.ahorro.hay,
            "es_ahorro": comparacion.ahorro.es_ahorro,
            "es_sobrecosto": comparacion.ahorro.es_sobrecosto,
            "la_referencia_gana": comparacion.ahorro.la_referencia_gana,
            "cantidad": comparacion.ahorro.cantidad,
            "precio_de_referencia": _cadena(comparacion.ahorro.precio_de_referencia),
            "por_pieza": _cadena(comparacion.ahorro.por_pieza),
            "total": _cadena(comparacion.ahorro.total),
            # El total **sin signo**, para que la pantalla escriba "cuesta
            # $180.99 más" sin tener que quitarle el menos a una cadena. Toda
            # aritmética —incluido un valor absoluto— vive de este lado: el
            # JavaScript pinta y no calcula. El signo sigue viajando en `total`
            # y en las dos banderas, que es lo que decide qué frase se escribe.
            "magnitud": (
                None
                if comparacion.ahorro.total is None
                else str(abs(comparacion.ahorro.total))
            ),
            "motivo": comparacion.ahorro.motivo,
            "detalle": comparacion.ahorro.detalle,
        },
        "por_proveedor": [
            {
                "proveedor": c.proveedor,
                "nombre": c.nombre,
                "estado": c.estado,
                "es_ganador": c.es_ganador,
                "precio": _cadena(c.precio),
                "diferencia": _cadena(c.diferencia),
                # Sin signo, por lo mismo que `ahorro.magnitud`: la pantalla
                # escribe la frase y no le quita el menos a una cadena.
                "diferencia_magnitud": (
                    None if c.diferencia is None else str(abs(c.diferencia))
                ),
                "mas_barato_que_el_ganador": c.mas_barato_que_el_ganador,
                "existencia_como_llego": c.existencia_como_llego,
                # El motivo corto —el que se guarda y el que se cuenta— y el
                # mismo motivo dicho para una persona. Los dos viajan: la
                # pantalla escribe el largo, que es lo que pide la segunda
                # casilla del ticket 15, y el corto sigue siendo lo que
                # identifica el hueco en la tabla y en la bitácora.
                "motivo": c.motivo,
                "motivo_explicado": explicacion_del_motivo(c.motivo),
            }
            for c in comparacion.por_proveedor
        ],
    }


def conteo_como_json(conteo: ConteoDeLaLista) -> dict:
    """El conteo de la lista como la pantalla lo lee, con las tres sumas aparte.

    Viaja el total y el desglose, no uno de los dos: el total es lo que se lee
    de un vistazo —la cuarta casilla del ticket, *el conteo es legible sin abrir
    cada renglón*— y el desglose es lo que dice qué hacer con él.

    `hay_sin_comparar` viaja resuelto para que el JavaScript no pregunte por un
    `> 0`: es la misma razón de siempre, y aquí además decide **cuál de las dos
    frases** se escribe. Las dos se escriben, la de aviso y la de confirmación:
    no decir nada cuando está todo comparado dejaría el silencio con dos
    significados.
    """
    return {
        "renglones": conteo.renglones,
        "comparados": conteo.comparados,
        "sin_comparar": conteo.sin_comparar,
        "hay_sin_comparar": conteo.hay_sin_comparar,
        "sin_consultar": conteo.sin_consultar,
        "sin_un_solo_precio": conteo.sin_un_solo_precio,
        "con_un_solo_precio": conteo.con_un_solo_precio,
    }
