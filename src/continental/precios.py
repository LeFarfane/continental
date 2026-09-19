"""De lo que Doyle contesta a lo que se guarda congelado: funciones puras.

Este módulo no abre una conexión, no llama a Doyle, no mira el reloj y no lee
un archivo. Recibe una `RespuestaDeProveedor` —el dato que el borde de
`doyle.py` ya tradujo— **y la clave que se buscó**, y devuelve una
`LecturaDePrecio`: el precio tal como llegó, el número al que se pudo
convertir, la existencia que el proveedor reportó, y **el motivo cuando no hay
precio**.

## El emparejamiento, que es la mitad que decide

`emparejar` responde la pregunta de la que cuelga todo lo demás: **¿lo que
contestó este proveedor es el producto que se buscó?** Cuatro portales, dos
reglas —el EAN de 13 dígitos para NADRO, LEVIC y QuePharma; el único resultado
para VICMA— y un motivo de rechazo cuando no se puede afirmar que sí. El porqué
de cada una está junto a `REGLA_DEL_PROVEEDOR`.

Sin eso, la comparación puede poner una caja de 30 contra una de 60 y decir que
la segunda es más barata. **Marlowe ya se equivocó exactamente así**, y lo peor
no fue el número: no falló y no avisó.

## Por qué el motivo es una columna y no un comentario

Un precio faltante no es un `NULL` mudo. "NADRO no dio precio" puede querer
decir cinco cosas muy distintas y **cada una se arregla de otra manera**: si la
sesión caducó, el encargado la abre en dos clics; si el portal no contestó, se
vuelve a intentar; si el producto no está en ese catálogo, no hay nada que
hacer y el hueco es la respuesta correcta. Sin el motivo, las cinco se ven
idénticas en la pantalla y ninguna se puede atender (historia 23 del spec, y
la segunda casilla del ticket 15).

Por eso `MOTIVOS` es un vocabulario cerrado con su `CHECK` en el DDL y no texto
libre: el ticket 15 tiene que **contar** los huecos por motivo, y un conteo
sobre texto libre cuenta faltas de ortografía.

## Dónde se convierte el precio, y por qué aquí

El precio llega de Doyle como **texto**. `doyle.py` no lo convierte a propósito
—su docstring lo dice— porque convertirlo en el borde obligaría a inventar un
`0.0` para el hueco, y un cero se lee como "el más barato" y dispara una compra
equivocada (regla 4 de `CLAUDE.md`).

**Qué texto llega, medido contra el Doyle real el 2026-09-19** (y no supuesto,
que es lo que costaría caro): Doyle **ya normaliza**. Su `_solo_numero` recibe
`"$ 208.97"` del portal y entrega `"208.97"` —sin signo y sin separador de
millar— y su `_solo_entero` convierte `"Disponibles: 420"` en `"420"`. Cuando
no encuentra ningún número **devuelve el texto original, y si estaba vacío, un
guion largo `"—"`**, a propósito: "No disponible" o "Bajo pedido" es
información que un hueco tiraría a la basura.

Así que lo normal es que aquí llegue una cifra limpia. La conversión de abajo
acepta igual el `$`, las comas y el espacio duro, y eso **no es código muerto**:
es lo que impide que el día que Doyle agregue un proveedor cuyo selector
devuelva el texto crudo, un precio perfectamente legible se convierta en un
hueco. Y el `"—"` no se puede leer como número, que es exactamente lo que se
quiere: sale `precio ilegible` con su texto al lado.

Una precisión sobre el nombre: `precio_como_llego` es **como llegó de Doyle**,
no como lo pintó el portal. Lo segundo no lo tenemos y no se va a fingir que
sí.

Se convierte **aquí**, en Python, antes de escribir la fila, y no en el SQL con
un `::numeric`. La diferencia importa y es concreta: `'1,234.50'::numeric`
**truena**, y un error de conversión aborta la transacción entera — se
perderían también los tres proveedores que sí contestaron bien. Aquí un texto
que no se puede convertir es una lectura más, con `precio` nulo y el motivo
`precio ilegible`, que es información. Y de paso: una función pura se prueba
sin Postgres, que es la única manera de probar algo en este repo.

**Las dos cosas se guardan**: `precio` es el número con el que se compara y
`precio_como_llego` es el texto original, que es lo único que permite auditar
una conversión dudosa meses después. Si sobreviviera solo el número, "¿de dónde
salió este 1234.50?" no tendría respuesta.

**`Decimal` y nunca `float`.** Es la misma lección medida que llevó a
`numeric(12,2)` en el DDL: en coma flotante `0.1 + 0.2` no es `0.3`, y un total
de pedido deja de cuadrar contra la factura del proveedor por centavos que
nadie puede explicar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from continental.doyle import (
    ESTADOS_PENDIENTES,
    EstadoDeBusqueda,
    FilaDeProveedor,
    RespuestaDeProveedor,
)

# ----------------------------------------------------------- el vocabulario
#
# Los ocho motivos por los que un renglón puede quedarse sin precio en un
# proveedor. Son constantes y no cadenas sueltas por la misma razón que los
# estados del glosario: viajan hasta el JavaScript de la pantalla, el DDL los
# repite en un `CHECK`, y `test_sql_del_pedido.py` compara las dos listas.
#
# Cada uno existe porque **lleva a una acción distinta**. Si dos motivos se
# atienden igual, sobra uno.

#: El portal buscó y no encontró nada: ese producto no está en ese catálogo.
#: No hay nada que hacer, y el hueco es la respuesta correcta.
SIN_RESULTADOS = "sin resultados"

#: La clave devolvió más de un resultado y ninguno se puede elegir sin
#: adivinar. Es el caso de VICMA, que muestra código interno y no el EAN (ADR
#: 0002): "VICMA entra si el EAN devuelve exactamente un resultado".
#:
#: Desde el ticket 13 también lo escriben las otras tres reglas en dos casos: el
#: mismo EAN repetido en varias filas con datos distintos, y una lista que Doyle
#: cortó en 20 sin el EAN dentro —ahí no se puede afirmar `no empareja`, porque
#: eso diría algo de las filas que nunca llegaron—.
VARIOS_RESULTADOS = "varios resultados"

#: Llegaron filas y **ninguna es este producto**. Lo escribe el emparejamiento
#: por EAN (`emparejar`, ticket 13), y es el final ordinario de QuePharma, que
#: usa código interno: **va a quedar fuera seguido y eso es lo esperado**, no
#: una falla (ADR 0002). Un hueco visible con su motivo es información; una
#: comparación mal emparejada es una compra equivocada.
NO_EMPAREJA = "no empareja"

#: Doyle intentó y el portal falló. Se vuelve a intentar.
PORTAL_SIN_CONTESTAR = "el portal no contestó"

#: La sesión de ese proveedor caducó. **Lo arregla el encargado en dos clics**,
#: y por eso no puede verse igual que "el portal no contestó" (historia 33).
SESION_CADUCADA = "la sesión caducó"

#: Doyle todavía no sabe leer esa página (su `modo: reconocimiento`). No es un
#: fallo del portal: lo primero se arregla escribiendo selectores y lo segundo
#: volviendo a intentar.
SIN_SELECTORES = "no se sabe leer la página"

#: Se acabó el tiempo con ese proveedor todavía buscando. Distinto de "el
#: portal falló" con todas sus letras, que es lo que pide la historia 31: uno
#: se resuelve volviendo a consultar ese renglón, el otro no.
SIN_TIEMPO = "no alcanzó el tiempo"

#: Llegó la fila pero su precio no se pudo convertir a número —venía vacío, o
#: con un formato que no se puede leer sin adivinar—. **Nunca un cero**: el
#: texto original se guarda al lado para poder mirarlo.
PRECIO_ILEGIBLE = "precio ilegible"

#: Los ocho, en el orden en que se leen de mejor a peor noticia. El DDL los
#: repite en `ck_precio_motivo_conocido`.
MOTIVOS: tuple[str, ...] = (
    SIN_RESULTADOS,
    VARIOS_RESULTADOS,
    NO_EMPAREJA,
    PORTAL_SIN_CONTESTAR,
    SESION_CADUCADA,
    SIN_SELECTORES,
    SIN_TIEMPO,
    PRECIO_ILEGIBLE,
)

# Cómo se le dice cada motivo al encargado.
#
# El ticket 15 pide que **cada precio faltante diga su motivo**, y lo pide con
# estas palabras: *el producto no está en ese catálogo, el EAN dio varios
# resultados, el portal no contestó, la sesión caducó*. Dos de los ocho ya se
# llaman así con todas sus letras; los otros seis se llaman en corto porque lo
# que se **guarda** tiene que ser corto, estable y contable —el `CHECK` del DDL
# los repite y el conteo se hace sobre ellos—.
#
# Así que hay dos cadenas por motivo y no una, y cada una tiene su trabajo:
#
# - `MOTIVOS` es lo que se escribe en la tabla y lo que se cuenta. No cambia
#   sin una migración.
# - `EXPLICACION_DEL_MOTIVO` es lo que se lee en la pantalla. Se puede reescribir
#   cuantas veces haga falta para que se entienda, sin tocar una sola fila.
#
# Un `.title()` o un diccionario a medias no sirven: "sin resultados" no se
# convierte en "el producto no está en ese catálogo" con reglas de texto, y ese
# salto es justo el que hace que un hueco se pueda atender.
EXPLICACION_DEL_MOTIVO: dict[str, str] = {
    SIN_RESULTADOS: "el producto no está en ese catálogo",
    VARIOS_RESULTADOS: (
        "el EAN dio varios resultados y ninguno se puede elegir sin adivinar"
    ),
    # Se parece al primero y **no es el mismo**: allá el portal no encontró
    # nada; aquí encontró filas y ninguna es este producto. La diferencia
    # importa porque la segunda es el final ordinario de QuePharma, que busca
    # por código interno (ADR 0002), y confundirlas escondería que ese portal
    # casi nunca empareja.
    NO_EMPAREJA: (
        "llegaron resultados y ninguno es este producto: no está en ese "
        "catálogo con este EAN"
    ),
    PORTAL_SIN_CONTESTAR: "el portal no contestó; se vuelve a intentar",
    SESION_CADUCADA: (
        "la sesión de ese proveedor caducó: ábrela y vuelve a consultar"
    ),
    SIN_SELECTORES: "Doyle todavía no sabe leer esa página",
    SIN_TIEMPO: "se acabó el tiempo con ese proveedor todavía buscando",
    PRECIO_ILEGIBLE: (
        "el precio llegó con un formato que no se puede leer sin adivinar"
    ),
}


def explicacion_del_motivo(motivo: str | None) -> str | None:
    """El motivo dicho para una persona, o el motivo mismo si no se conoce.

    Nunca `None` cuando hay motivo, y nunca cadena vacía: un hueco que pierde su
    explicación por no estar en el diccionario se queda con la corta, que dice
    menos pero dice algo. Es la regla 4 de `CLAUDE.md` aplicada al propio mapa
    de presentación —lo mismo que hace `nombre_del_proveedor` con un proveedor
    que no reconoce—.
    """
    if motivo is None:
        return None
    return EXPLICACION_DEL_MOTIVO.get(motivo, motivo)


#: Cómo se escribe el nombre de cada proveedor, para la pantalla. La clave es
#: la de Doyle (`config/proveedores.yml` de ese repo) y el valor es el del
#: glosario de `CONTEXT.md`.
#:
#: Existe porque `.upper()` daría "QUEPHARMA" y el glosario dice "QuePharma", y
#: el glosario manda sobre el nombre de cualquier cosa. Es un mapa de
#: PRESENTACIÓN y nada más: lo que se guarda es la clave, que es lo que no
#: cambia. Una clave que no esté aquí se muestra tal cual llegó —nunca se
#: esconde un proveedor por no reconocer su nombre (regla 4)—.
NOMBRES_DE_PROVEEDOR: dict[str, str] = {
    "nadro": "NADRO",
    "levic": "LEVIC",
    "vicma": "VICMA",
    "quepharma": "QuePharma",
}


def nombre_del_proveedor(clave: str) -> str:
    """Cómo se escribe ese proveedor. La clave misma si no se conoce."""
    return NOMBRES_DE_PROVEEDOR.get(clave, clave)


# ------------------------------------------------------------ la conversión

#: Lo que se le quita al texto antes de intentar leerlo como número: el signo
#: de pesos, las siglas de moneda y **el espacio duro** (`\xa0`), que es con lo
#: que muchos portales separan el símbolo de la cifra y que no es un espacio
#: normal — `"$\xa086.05".strip()` no lo quita y la conversión fallaría por una
#: razón invisible en la pantalla.
_BASURA_DEL_PRECIO = re.compile(r"[\s $]|MXN|MN", re.IGNORECASE)

#: Un precio legible: dígitos con separador de miles opcional por comas y hasta
#: dos decimales por punto. `1,234.50`, `86.05`, `1234`, `.50` no.
#:
#: **Estricto a propósito.** Un `"1.234,50"` —formato europeo— no empareja y se
#: queda como `precio ilegible` con su texto al lado, en vez de leerse como
#: `1.234` y convertir un producto de mil doscientos pesos en el más barato de
#: los cuatro. Adivinar cuál separador es cuál sobre un solo número es
#: imposible (`1.234` puede ser mil doscientos treinta y cuatro o uno con
#: fracción), y adivinar mal aquí compra al proveedor equivocado.
_PRECIO_LEGIBLE = re.compile(r"^\d{1,3}(,\d{3})+(\.\d{1,2})?$|^\d+(\.\d{1,2})?$")

#: Lo mismo para la existencia, con **tres** decimales en vez de dos: es la
#: escala de `numeric(12,3)` y la de `pedidos.renglon.existencia`, porque hay
#: artículos a granel (5, medidos sobre el respaldo del 2026-07-27).
_EXISTENCIA_LEGIBLE = re.compile(r"^\d{1,3}(,\d{3})+(\.\d{1,3})?$|^\d+(\.\d{1,3})?$")

#: Dos decimales, los de `numeric(12,2)` del DDL. Se redondea aquí para que el
#: doble en memoria devuelva exactamente lo mismo que Postgres al releer: un
#: doble que conservara tres decimales dejaría una prueba en verde en la torre
#: para fallar en atlas.
_CENTAVOS = Decimal("0.01")

#: Tres decimales, los de `numeric(12,3)` de la existencia. Los mismos de
#: `pedidos.renglon.existencia` y de `sugerido._DECIMALES_DE_GRANEL`: hay 5
#: artículos a granel en el catálogo (medido sobre el respaldo del 2026-07-27)
#: y un proveedor puede reportar fracciones por la misma razón.
_MILESIMAS = Decimal("0.001")


def precio_a_numero(texto: str) -> Decimal | None:
    """El texto que dio el portal → `Decimal`, o `None` si no se puede leer.

    `None` es **"no se sabe"** y nunca cero. Devolver `Decimal("0")` para un
    hueco es exactamente la falla que la regla 4 de `CLAUDE.md` prohíbe: el cero
    gana toda comparación de "el más barato" y dispara la compra equivocada sin
    un solo error que ver.

    **Un cero que el portal SÍ escribió tampoco es un precio.** `"0.00"` no es
    "regalado": es un portal que no supo decir cuánto cuesta, o una fila de
    promoción sin precio. Sale `None` y el `CHECK (precio > 0)` del DDL lo
    vuelve a rechazar del otro lado — dos puertas para el mismo cero, que es el
    único número que aquí puede hacer daño.
    """
    if not texto:
        return None

    limpio = _BASURA_DEL_PRECIO.sub("", texto)
    if not _PRECIO_LEGIBLE.match(limpio):
        return None

    try:
        valor = Decimal(limpio.replace(",", "")).quantize(_CENTAVOS)
    except InvalidOperation:
        return None

    return valor if valor > 0 else None


def existencia_a_numero(texto: str) -> Decimal | None:
    """Lo que el proveedor reportó de existencia → `Decimal`, o `None`.

    Se intenta y se acepta que falle, y eso es distinto del precio: los portales
    escriben la existencia de muchas maneras —`"40"`, `"+100"`, `"Disponible"`,
    `"SI"`— y **ninguna de ellas es motivo para tirar el precio**. Por eso el
    texto original se guarda siempre (`existencia_como_llego`) y el número es un
    extra: el ticket 14 quiere marcar "el más barato **con existencia**" y para
    eso el texto alcanza cuando el número no.

    `None` aquí no produce motivo ni hueco: significa "el proveedor lo dijo con
    palabras". Un cero **sí** se conserva: "cero piezas" es un dato de verdad
    —el proveedor no lo tiene— y no se parece en nada a un precio en cero.
    """
    if not texto:
        return None

    # El `+` de "+100" se quita antes de mirar la forma: es la manera en que un
    # portal dice "cien o más", y lo que se puede afirmar de ahí es el cien.
    # Que sea una cota inferior y no la cifra exacta es información que se
    # conserva en `existencia_como_llego`, que se guarda siempre.
    limpio = _BASURA_DEL_PRECIO.sub("", texto).lstrip("+")
    if not _EXISTENCIA_LEGIBLE.match(limpio):
        return None

    try:
        return Decimal(limpio.replace(",", "")).quantize(_MILESIMAS)
    except InvalidOperation:
        return None


# --------------------------------------------------------------- la lectura


@dataclass(frozen=True, slots=True)
class LecturaDePrecio:
    """Lo que un proveedor dijo de un renglón en un instante. Una fila futura.

    Congelada y sin propiedades que vuelvan a preguntar: lo que se guarda es
    esto y nada se resuelve al leer. Es el mismo criterio de
    `sugerido.Renglon` —"los números viajan congelados"— aplicado al precio, y
    es literal la tercera casilla del ticket 12: *un pedido dice a qué precio se
    decidió, no a cómo está hoy*.

    **`precio is None` y `motivo` van siempre juntos**, en los dos sentidos: o
    hay precio y no hay motivo, o hay motivo y no hay precio. Lo comprueba
    `revisar_el_precio` de `almacenamiento.py` y lo garantiza
    `ck_precio_sin_dato` en la tabla. Un `None` sin motivo sería el "NULL mudo"
    que este ticket existe para evitar.

    `resultados` es cuántas filas encontró el portal, no cuántas trajo Doyle
    (que corta en 20). **Es el número con el que se decide VICMA** desde el
    ticket 13 —"se acepta únicamente si la búsqueda del EAN devuelve
    exactamente un resultado"—, y por eso se guarda: sin él, esa regla tendría
    que releer el portal mañana, o mentir.

    `clave_del_proveedor` y `descripcion_del_proveedor` son lo que el portal
    mostró de **la fila elegida**, y solo de ella: una lectura sin precio las
    deja vacías a propósito, porque llenarlas con una fila que se descartó las
    convertiría en la evidencia falsa de un emparejamiento que no ocurrió. Son
    la lección que Marlowe pagó —una caja de 60 más barata por pieza se veía
    como más cara, sin fallar y sin avisar— y con la descripción a la vista una
    persona lo caza de un vistazo. Es lo único que protege el caso de VICMA, que
    se acepta sin poder compararlo con nada.
    """

    proveedor: str
    precio_como_llego: str = ""
    precio: Decimal | None = None
    existencia_como_llego: str = ""
    existencia: Decimal | None = None
    motivo: str | None = None
    detalle: str = ""
    clave_del_proveedor: str = ""
    descripcion_del_proveedor: str = ""
    resultados: int = 0

    @property
    def sin_dato(self) -> bool:
        """Si este proveedor no dejó precio. **Nunca se deduce de un cero.**"""
        return self.precio is None


#: Cuánto del mensaje de Doyle se guarda. Doyle contesta con instrucciones de
#: varias líneas —"ábrela con `python -m doyle.sesion --proveedor nadro`"— que
#: son útiles en su propia pantalla y ruido en un renglón de tabla.
#:
#: **Esto NO contradice la regla 5 de `CLAUDE.md`**, y conviene decir por qué:
#: la regla prohíbe que viaje al navegador el detalle de una excepción NUESTRA
#: —un `str(exc)` de SQLAlchemy lleva la cadena de conexión con contraseña—.
#: Esto es un mensaje que Doyle redactó a propósito para que una persona lo lea,
#: y la historia 23 pide justamente eso. Lo que no viaja nunca es el tipo ni el
#: texto de una excepción de Continental: eso se convierte en motivo antes de
#: llegar aquí.
_LARGO_DEL_DETALLE = 200


def _recortar(mensaje: str) -> str:
    """La primera línea del mensaje de Doyle, acotada. `""` si no dijo nada."""
    primera = (mensaje or "").strip().splitlines()
    if not primera:
        return ""
    texto = primera[0].strip()
    return texto if len(texto) <= _LARGO_DEL_DETALLE else texto[:_LARGO_DEL_DETALLE] + "…"


#: Cómo se reconoce una sesión caducada dentro del mensaje de Doyle. Con y sin
#: acento porque el texto viaja por HTTP entre dos procesos y no hay ninguna
#: garantía de que llegue acentuado; y `\bsesion` para no cazar otra palabra.
_HUELE_A_SESION = re.compile(r"sesi[oó]n", re.IGNORECASE)


# ------------------------------------------- el emparejamiento (ticket 13)
#
# El corazón del ticket 13: **decidir si lo que contestó un proveedor es el
# producto que se buscó**. Todo lo demás de este módulo cuelga de aquí.
#
# Sin esto, la comparación puede poner una caja de 30 contra una de 60 y decir
# que la segunda es más barata. Marlowe ya se equivocó exactamente así, y lo
# peor del caso es lo que NO pasó: no falló, no avisó, y la flecha apuntaba al
# revés.

#: Un EAN tiene trece dígitos. El glosario de `CONTEXT.md` no deja margen:
#: "**Clave** — el código de barras del producto (EAN de 13 dígitos). Es lo
#: único que significa lo mismo en nuestro catálogo y en el de un proveedor".
LARGO_DEL_EAN = 13

#: Emparejar por el EAN de 13 dígitos, y solo por él. Es la regla estricta y la
#: de omisión: lo que no se conoce se trata así.
POR_EAN = "por EAN"

#: Aceptar el único resultado de la búsqueda, sin poder compararlo con nada.
#: Es una **excepción razonada** y hoy la tiene un solo proveedor.
POR_UN_SOLO_RESULTADO = "por un solo resultado"

#: Con qué regla se acepta el precio de cada proveedor. Las cuatro vienen del
#: ADR 0002 y del ticket 13, y están las cuatro escritas aunque tres sean
#: iguales: una tabla que solo lista la excepción obliga a deducir el resto.
#:
#: **Por qué QuePharma está con NADRO y LEVIC, y no con VICMA** — es la
#: decisión que más cuesta ver de este ticket. Los tres portales que no son
#: NADRO/LEVIC muestran código interno, así que la tentación es darle a
#: QuePharma la misma excepción que a VICMA. La diferencia está medida en el
#: ADR 0002: de VICMA se sabe que **sí indexa el EAN**, así que un único
#: resultado de una búsqueda por EAN es ese producto; de QuePharma **ni
#: siquiera está confirmado que encuentre por EAN**, así que su único resultado
#: puede ser el de una búsqueda que ignoró el término. Aceptarlo sería comprar
#: por lo que devolvió una búsqueda que quizá no buscó nada.
#:
#: La consecuencia está aceptada y escrita en el ADR 0002: **QuePharma va a
#: quedar fuera seguido**, y eso es lo esperado, no una falla. "El más barato"
#: a veces querrá decir "el más barato de los que contestaron", y por eso el
#: hueco se muestra con su motivo.
REGLA_DEL_PROVEEDOR: dict[str, str] = {
    "nadro": POR_EAN,        # el portal muestra el EAN de 13 dígitos
    "levic": POR_EAN,        # igual que NADRO
    "quepharma": POR_EAN,    # usa código interno: casi nunca va a emparejar
    "vicma": POR_UN_SOLO_RESULTADO,  # código interno, pero indexa el EAN
}

#: Con qué regla se trata un proveedor que esta tabla no conoce. **La
#: estricta**, y la dirección no es casual: equivocarse hacia "sin dato con su
#: motivo" cuesta un hueco visible que alguien completa con un clic;
#: equivocarse hacia "este precio es el de tu producto" cuesta una compra mala
#: que nadie ve. Un quinto proveedor no nace con una excepción regalada.
REGLA_POR_OMISION = POR_EAN


def regla_del_proveedor(proveedor: str) -> str:
    """Con qué regla se acepta un precio de ese proveedor."""
    return REGLA_DEL_PROVEEDOR.get(proveedor, REGLA_POR_OMISION)


_NO_ES_DIGITO = re.compile(r"\D")


def _solo_digitos(texto: str) -> str:
    """El código sin adornos. `"750 1349-028234"` → `"7501349028234"`.

    Los portales pintan el código de barras con espacios, guiones o un espacio
    duro. Comparar el texto crudo convertiría una presentación distinta de **la
    misma cifra** en un hueco, y un hueco de mentira manda a alguien a teclear
    el precio a mano, que es peor que no tenerlo.

    Lo que **no** se hace es normalizar de más: no se rellenan ceros a la
    izquierda para convertir un UPC de 12 en un EAN de 13. Eso sí es adivinar, y
    adivinar aquí compra la presentación equivocada; si alguna vez hace falta,
    es una decisión con su ADR y no una línea de más en esta función.
    """
    return _NO_ES_DIGITO.sub("", texto or "")


@dataclass(frozen=True, slots=True)
class Emparejamiento:
    """La respuesta de `emparejar`: **la fila aceptada, o el motivo del rechazo**.

    Nunca las dos y nunca ninguna. Es la misma invariante que `LecturaDePrecio`
    un escalón más abajo, y es lo que hace que un precio faltante sea
    información en vez de un `NULL` mudo.

    Se devuelve la **fila entera** y no solo su precio a propósito: `clave` y
    `descripcion` son la evidencia de que se comparó el mismo producto, y son
    justo lo que le faltaba a Marlowe cuando tomó la caja de 60 por la de 30.

    `detalle` explica el rechazo con números —cuántas encontró el portal,
    cuántas llegaron— para que el hueco de la pantalla diga algo más que su
    motivo. No lleva nunca el texto de una excepción nuestra (regla 5 de
    `CLAUDE.md`): es una frase redactada aquí, sobre datos que ya viajaban.
    """

    fila: FilaDeProveedor | None = None
    motivo: str | None = None
    detalle: str = ""

    @property
    def aceptado(self) -> bool:
        """Si esta respuesta es el producto que se buscó."""
        return self.fila is not None


def emparejar(respuesta: RespuestaDeProveedor, clave: str) -> Emparejamiento:
    """Lo que devolvió un proveedor + la clave buscada → fila aceptada o motivo.

    **La función pura del ticket 13.** No abre una conexión, no llama a Doyle,
    no mira el reloj y no lee un archivo: los mismos dos argumentos dan siempre
    la misma respuesta, y por eso su tabla de casos se puede escribir entera sin
    Postgres y sin red (`tests/test_emparejamiento.py`).

    `clave` es **lo que Continental buscó**, no el `termino` que Doyle repite en
    su respuesta. Son dos cosas distintas: si Doyle devolviera un término
    recortado, vacío o de otro trabajo, emparejar contra él movería la portería
    sin que nadie lo viera.

    El orden importa y es el único posible: primero cómo le fue al proveedor
    —sin filas no hay nada que emparejar, y decir `no empareja` de un portal que
    ni contestó sería mentir sobre qué hay que arreglar— y solo al final la
    regla del proveedor.
    """
    if respuesta.estado in ESTADOS_PENDIENTES:
        # Solo se lee una respuesta después de esperar, así que "sigue
        # buscando" en este punto quiere decir que se acabó el tiempo. Es el
        # motivo que la historia 31 pide distinguir de un portal caído.
        return Emparejamiento(motivo=SIN_TIEMPO)

    if respuesta.estado == "error":
        return Emparejamiento(
            motivo=(
                SESION_CADUCADA
                if _HUELE_A_SESION.search(respuesta.mensaje or "")
                else PORTAL_SIN_CONTESTAR
            )
        )

    if respuesta.estado == "reconocimiento":
        return Emparejamiento(motivo=SIN_SELECTORES)

    if respuesta.estado != "listo":
        # Un estado que Doyle estrene y este código no conozca. Se trata como
        # "el portal no contestó" y se guarda el estado en el detalle, en vez
        # de tronar: un estado nuevo no puede dejar sin pedido a la farmacia, y
        # tampoco puede pasar callado.
        return Emparejamiento(
            motivo=PORTAL_SIN_CONTESTAR,
            detalle=f"Doyle contestó un estado que no se conoce: {respuesta.estado!r}",
        )

    if not respuesta.filas:
        if respuesta.total <= 0:
            # El portal buscó y no encontró nada: ese producto no está en ese
            # catálogo. No hay nada que hacer y el hueco es la respuesta
            # correcta.
            return Emparejamiento(motivo=SIN_RESULTADOS)
        # Dijo cuántas encontró y no mandó ninguna. **No es `sin resultados`**
        # —encontró— ni `no empareja` —no llegó nada que comparar—: es una
        # lectura que se quedó a medias, y eso se reintenta.
        return Emparejamiento(
            motivo=PORTAL_SIN_CONTESTAR,
            detalle=(
                f"el portal dijo que encontró {respuesta.total} y no llegó "
                "ninguna fila que leer."
            ),
        )

    if regla_del_proveedor(respuesta.proveedor) == POR_UN_SOLO_RESULTADO:
        return _por_un_solo_resultado(respuesta)
    return _por_el_ean(respuesta, clave)


def _por_un_solo_resultado(respuesta: RespuestaDeProveedor) -> Emparejamiento:
    """La regla de VICMA: se acepta **únicamente con exactamente un resultado**.

    VICMA muestra código interno y no el EAN, así que no hay nada con qué
    comparar la fila; lo que sostiene la aceptación es que su búsqueda **sí
    indexa el EAN** (ADR 0002), de modo que un único resultado para un EAN es
    ese producto. Con dos o más no se puede elegir sin adivinar, y adivinar aquí
    es la caja de 60 contra la de 30.

    **El número que manda es `total` y no `len(filas)`**, y conviene decir
    exactamente por qué, porque las dos cifras coinciden casi siempre:

    - `total` es cuántas encontró el portal; `filas` es cuántas trajo Doyle, que
      **corta en 20**. Un portal con 43 resultados manda 20 filas: contar filas
      diría "20" donde la verdad es "43", y ese 20 es el número que se guarda en
      `resultados` y se pinta en la pantalla. La regla saldría igual de estricta
      por casualidad y el dato de al lado estaría mal.
    - En la dirección que importa —aceptar— `len(filas) == 1` sería **más
      flojo**: un portal que encontró 43 y mandó una sola fila se leería como
      "exactamente un resultado". `total` no se deja engañar por eso.

    Que la fila esté además es un requisito aparte y no una segunda regla:
    `total == 1` con cero filas ya se atendió antes, porque sin fila no hay
    precio que congelar y aceptar sería inventarlo.
    """
    if respuesta.total != 1:
        return Emparejamiento(
            motivo=VARIOS_RESULTADOS,
            detalle=(
                f"la búsqueda del EAN devolvió {respuesta.total} resultados y "
                "este portal muestra código interno, no el EAN: con más de uno "
                "no se puede elegir sin adivinar."
            ),
        )

    if len(respuesta.filas) != 1:
        return Emparejamiento(
            motivo=PORTAL_SIN_CONTESTAR,
            detalle=(
                f"el portal encontró 1 resultado y llegaron "
                f"{len(respuesta.filas)} filas: no se puede saber cuál es."
            ),
        )

    return Emparejamiento(fila=respuesta.filas[0])


def _por_el_ean(respuesta: RespuestaDeProveedor, clave: str) -> Emparejamiento:
    """La regla estricta: la fila cuyo código **es** el EAN de 13 dígitos buscado.

    Es la de NADRO y LEVIC, que muestran el EAN, y también la de QuePharma —que
    usa código interno y por eso va a caer casi siempre en `no empareja`, que es
    lo que el ADR 0002 ya da por probable—.

    Con varias filas **sí** se puede aceptar, al revés que en VICMA, y esa es la
    diferencia entre las dos reglas: un EAN de 13 dígitos identifica una
    presentación concreta, así que encontrarlo entre tres filas no es adivinar,
    es leer. Lo que no se puede es elegir cuando el mismo EAN aparece dos veces
    —dos almacenes, dos presentaciones de venta— porque ahí quedarse con la
    primera sería elegir por el orden en que el portal pintó la tabla.
    """
    buscado = _solo_digitos(clave)
    if len(buscado) != LARGO_DEL_EAN:
        # Sin EAN no hay emparejamiento posible. La ruta ya se niega a consultar
        # un renglón sin clave, así que esto es el cinturón: si llegara aquí,
        # sale hueco con motivo y nunca un precio de un producto cualquiera.
        return Emparejamiento(
            motivo=NO_EMPAREJA,
            detalle=(
                f"se buscó {clave!r}, que no es un EAN de 13 dígitos: no hay con "
                "qué emparejar lo que contestó el portal."
            ),
        )

    iguales = [f for f in respuesta.filas if _solo_digitos(f.clave) == buscado]

    if len(iguales) == 1:
        return Emparejamiento(fila=iguales[0])

    if len(iguales) > 1:
        return Emparejamiento(
            motivo=VARIOS_RESULTADOS,
            detalle=(
                f"{len(iguales)} filas del portal traen el EAN {buscado} con "
                "datos distintos: quedarse con una sería elegir por el orden en "
                "que el portal las pintó."
            ),
        )

    if len(respuesta.filas) < respuesta.total:
        # La lista venía cortada (Doyle trae 20 como mucho) y el EAN no está
        # entre las que llegaron. **No se puede decir `no empareja`**: eso
        # afirmaría algo sobre las filas que nunca se vieron. Lo que de verdad
        # pasó es que había demasiadas para decidir con lo que se trajo.
        return Emparejamiento(
            motivo=VARIOS_RESULTADOS,
            detalle=(
                f"el portal encontró {respuesta.total} y llegaron "
                f"{len(respuesta.filas)}: el EAN {buscado} no está entre las que "
                "llegaron, y de las demás no se sabe."
            ),
        )

    return Emparejamiento(
        motivo=NO_EMPAREJA,
        detalle=(
            f"llegaron {len(respuesta.filas)} fila(s) del portal y ninguna trae "
            f"el EAN {buscado}: lo que contestó es otro producto."
        ),
    )


# --------------------------------------------- de la fila al precio congelado


def leer_el_precio(respuesta: RespuestaDeProveedor, clave: str) -> LecturaDePrecio:
    """Lo que un proveedor contestó + la clave buscada → la lectura a congelar.

    Función pura: los mismos argumentos dan siempre la misma `LecturaDePrecio`.
    No mira el reloj —el instante de la lectura lo pone la base con `now()`, que
    es el único que no depende de qué máquina corrió esto— ni toca la red.

    Es `emparejar` más la conversión del texto a `Decimal`: quién decide si esta
    fila es el producto buscado está arriba, y aquí solo se traduce lo aceptado.
    Separarlo no es ceremonia — es lo que permite probar la regla de cada
    proveedor sin arrastrar el formato de los precios, y al revés.

    **Toda salida sin precio lleva motivo.** No hay un camino por el que se
    devuelva `precio=None, motivo=None`: eso sería el `NULL` mudo.
    """
    proveedor = respuesta.proveedor
    detalle = _recortar(respuesta.mensaje)
    elegido = emparejar(respuesta, clave)

    if elegido.fila is None:
        return LecturaDePrecio(
            proveedor=proveedor,
            motivo=elegido.motivo,
            # El detalle del emparejamiento manda sobre el de Doyle: cuando hay
            # uno, es más específico —dice cuántas encontró el portal y por qué
            # ninguna sirve— que el mensaje genérico del otro lado.
            detalle=elegido.detalle or detalle,
            resultados=max(respuesta.total, 0),
        )

    fila = elegido.fila
    precio = precio_a_numero(fila.precio)
    # La advertencia que Doyle anotó al leer la fila —varios precios sin
    # tachar, por ejemplo— viaja aunque el precio se haya podido leer: un dato
    # con reserva es información, un dato limpio que no lo era es una decisión
    # mal tomada (docstring de `FilaDeProveedor`).
    con_reserva = _recortar(fila.advertencia) or detalle

    return LecturaDePrecio(
        proveedor=proveedor,
        precio_como_llego=fila.precio,
        precio=precio,
        existencia_como_llego=fila.existencia,
        existencia=existencia_a_numero(fila.existencia),
        motivo=None if precio is not None else PRECIO_ILEGIBLE,
        detalle=con_reserva,
        clave_del_proveedor=fila.clave,
        descripcion_del_proveedor=fila.descripcion,
        resultados=respuesta.total,
    )


def congelar(
    estado: EstadoDeBusqueda, clave: str
) -> tuple[LecturaDePrecio, ...]:
    """La búsqueda entera + la clave buscada → una lectura por proveedor.

    `clave` es **la que Continental buscó**, y no el `estado.termino` que Doyle
    repite: contra qué se empareja no lo puede decidir el otro proceso. Un
    `termino` recortado, vacío o de otro trabajo movería la portería sin que
    nadie lo viera, y lo que se decide con esto es a qué proveedor comprarle.

    **Una por proveedor, siempre, aunque no haya contestado ninguno.** Ésa es
    la decisión: un proveedor que falló deja una fila con su motivo, no deja de
    existir. Guardar solo los que dieron precio haría indistinguible "a NADRO no
    se le preguntó" de "NADRO no contestó", y el ticket 15 tiene que contar
    exactamente eso: *contra cuántos proveedores se comparó cada renglón*.

    Ordenadas por clave para que el orden de las filas no dependa de en qué
    orden terminaron los hilos de Doyle. Dos consultas del mismo renglón se
    pueden leer en paralelo sin que el orden confunda a nadie.
    """
    return tuple(
        leer_el_precio(respuesta, clave)
        for _, respuesta in sorted(estado.proveedores.items())
    )
