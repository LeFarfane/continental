"""De lo que Doyle contesta a lo que se guarda congelado: funciones puras.

Este módulo no abre una conexión, no llama a Doyle, no mira el reloj y no lee
un archivo. Recibe una `RespuestaDeProveedor` —el dato que el borde de
`doyle.py` ya tradujo— y devuelve una `LecturaDePrecio`: el precio tal como
llegó, el número al que se pudo convertir, la existencia que el proveedor
reportó, y **el motivo cuando no hay precio**.

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
VARIOS_RESULTADOS = "varios resultados"

#: Llegaron filas y **ninguna es este producto**. Lo va a escribir el
#: emparejamiento por EAN del ticket 13 —QuePharma usa código interno—; hoy
#: nadie lo produce todavía y por eso vive aquí desde ahora: agregarlo después
#: costaría una migración del `CHECK` y una visita a atlas (ADR 0003).
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
    (que corta en 20). Se guarda **aunque hoy solo se use para el motivo**
    porque es el dato con el que el ticket 13 decide VICMA: "se acepta
    únicamente si la búsqueda del EAN devuelve exactamente un resultado". Si no
    se guardara hoy, esa regla tendría que releer el portal mañana —o mentir—.

    `clave_del_proveedor` y `descripcion_del_proveedor` son lo que el portal
    mostró de la fila elegida. Son la evidencia de que se comparó el mismo
    producto, y es la lección que Marlowe pagó: una caja de 60 más barata por
    pieza se veía como más cara, sin fallar y sin avisar. Con la descripción a
    la vista, una persona lo caza de un vistazo.
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


def _una_sola_fila(respuesta: RespuestaDeProveedor) -> FilaDeProveedor | None:
    """La fila del portal cuando hay **exactamente una**, y si no `None`.

    Ésta es la regla provisional del ticket 12 y conviene que se lea como tal:
    el emparejamiento de verdad —NADRO y LEVIC por EAN de 13 dígitos directo,
    VICMA solo con un resultado, QuePharma por código interno— es el **ticket
    13**, y meterlo aquí sería hacer dos tickets en uno y dejar sin prueba
    propia la mitad que más duele equivocar.

    Mientras tanto se elige lo **más estricto que existe**, y esa dirección no
    es casual: equivocarse hacia "sin dato con su motivo" cuesta un hueco
    visible que alguien puede completar con un clic; equivocarse hacia "este
    precio es el de tu producto" cuesta una compra mala que nadie ve. El ticket
    13 solo puede aflojar esto para NADRO y LEVIC, nunca apretarlo.

    Se mira `total` —cuántas encontró el portal— y no `len(filas)`, porque
    Doyle corta la lista en 20: un portal con 43 resultados manda 20 filas, y
    contar las filas diría "20" donde la verdad es "43". Con `total` el motivo
    sale bien; con `len` diría un número falso en la pantalla.
    """
    if respuesta.total != 1 or len(respuesta.filas) != 1:
        return None
    return respuesta.filas[0]


def leer_el_precio(respuesta: RespuestaDeProveedor) -> LecturaDePrecio:
    """Lo que un proveedor contestó → la lectura que se va a congelar.

    Función pura: el mismo `RespuestaDeProveedor` da siempre la misma
    `LecturaDePrecio`. No mira el reloj —el instante de la lectura lo pone la
    base con `now()`, que es el único que no depende de qué máquina corrió
    esto— ni toca la red.

    **Toda salida sin precio lleva motivo.** No hay un camino por el que se
    devuelva `precio=None, motivo=None`: eso sería el `NULL` mudo.
    """
    proveedor = respuesta.proveedor
    detalle = _recortar(respuesta.mensaje)

    if respuesta.estado in ESTADOS_PENDIENTES:
        # Solo se lee una respuesta después de esperar, así que "sigue
        # buscando" en este punto quiere decir que se acabó el tiempo. Es el
        # motivo que la historia 31 pide distinguir de un portal caído.
        return LecturaDePrecio(
            proveedor=proveedor, motivo=SIN_TIEMPO, detalle=detalle
        )

    if respuesta.estado == "error":
        return LecturaDePrecio(
            proveedor=proveedor,
            motivo=(
                SESION_CADUCADA
                if _HUELE_A_SESION.search(respuesta.mensaje or "")
                else PORTAL_SIN_CONTESTAR
            ),
            detalle=detalle,
        )

    if respuesta.estado == "reconocimiento":
        return LecturaDePrecio(
            proveedor=proveedor, motivo=SIN_SELECTORES, detalle=detalle
        )

    if respuesta.estado != "listo":
        # Un estado que Doyle estrene y este código no conozca. Se trata como
        # "el portal no contestó" y se guarda el estado en el detalle, en vez
        # de tronar: un estado nuevo no puede dejar sin pedido a la farmacia, y
        # tampoco puede pasar callado.
        return LecturaDePrecio(
            proveedor=proveedor,
            motivo=PORTAL_SIN_CONTESTAR,
            detalle=f"Doyle contestó un estado que no se conoce: {respuesta.estado!r}",
        )

    if respuesta.total == 0 and not respuesta.filas:
        return LecturaDePrecio(
            proveedor=proveedor, motivo=SIN_RESULTADOS, detalle=detalle, resultados=0
        )

    fila = _una_sola_fila(respuesta)
    if fila is None:
        return LecturaDePrecio(
            proveedor=proveedor,
            motivo=VARIOS_RESULTADOS,
            detalle=detalle,
            resultados=respuesta.total,
        )

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


def congelar(estado: EstadoDeBusqueda) -> tuple[LecturaDePrecio, ...]:
    """La búsqueda entera → una lectura por proveedor, ordenadas por clave.

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
        leer_el_precio(respuesta)
        for _, respuesta in sorted(estado.proveedores.items())
    )
