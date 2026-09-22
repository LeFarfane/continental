"""Un pedido a CSV: el archivo que se abre en Excel, se manda o se guarda (23).

Funciones puras. No abre una conexión, no llama a Doyle, no mira el reloj y **no
escribe un archivo**: devuelve bytes, y la ruta los sirve. Así el CSV se
regenera cada vez que se pide y no hay copia en disco que respaldar, ni que
subir a git por descuido, ni que envejecer mientras el pedido cambia (cuarta
casilla del ticket).

## Qué precio va

**El de ESE proveedor, congelado** —la última lectura suya en
`pedidos.precio_de_proveedor` (ADR 0004)—, y no el más barato de los cuatro. Es
el que sale en el carrito de su portal y el que se compara contra su factura.
La regla no se reescribe aquí: las líneas salen de
`particion.lo_que_hay_que_capturar`, lo mismo que la pantalla de captura del
ticket 22, así que el archivo y la pantalla no pueden contar distinto. Y el
total sale de `particion.PedidoPorArmar`, que es donde vive la regla del ticket
20: **`None` en cuanto una línea va sin precio**, jamás la suma de las demás.

Un renglón sin precio escribe `sin precio` en su celda y el porqué al lado —no
un `0.00` ni una celda vacía, que en Excel se ven iguales cuando alguien suma la
columna—. Y todo es **sin IVA**, dicho en el nombre de las dos columnas de
dinero: es la trampa heredada de `CLAUDE.md` (el costo nuestro es sin IVA y el
de mostrador con IVA).

## Por qué se escribe así, medido y no supuesto

El daño lo sufrió Marlowe el 2026-09-03 (`Marlowe/tests/test_excel.py`) y aquí
se volvió a medir, con el Excel 16 de la torre en es-MX, el 2026-09-21:

- **La clave como fórmula de texto, `="7501234567890"`.** Cruda, Excel la
  enseña `7.5012E+12`, y una con ceros a la izquierda (`0012345678905`) pasa a
  valer `12345678905`: otro producto. Se probaron las otras dos recetas
  conocidas y las dos dejan basura en la celda: un tabulador al frente queda
  como tabulador, y un apóstrofo al frente queda como apóstrofo —en un CSV,
  Excel no lo trata como marca de texto—. La fórmula es la única que dejó la
  clave intacta, con sus ceros, como texto.
- **UTF-8 con BOM.** Sin él, `ÁCIDO FÓLICO` se ve `ÃCIDO FÃ“LICO`. Es lo mismo
  que Marlowe hace en `alta.escribir_csv`.
- **Coma como separador y punto decimal, sin `sep=,`.** Es la configuración
  regional de México —medido en la torre: lista `,`, decimal `.`—, y con ella
  Excel parte las columnas y lee `86.05` como número sin preguntar. España usa
  `;` y coma decimal; esta farmacia no está en España. La línea `sep=,` sobra
  en es-MX y además hace que Excel ignore el BOM (medido: los acentos vuelven
  a salir rotos).
- **Una descripción que empieza con `=`, `+`, `-` o `@` va también como
  fórmula de texto.** Medido: `-GUION` sale `#¿NOMBRE?` y `=1+1` sale `2` —Excel
  **la evaluó**—. Las descripciones vienen del catálogo de SICAR, que captura
  una persona. Solo se protege la que lo necesita: envolverlas todas dejaría
  `="..."` a la vista de cualquier lector que no sea Excel, y Excel limita la
  cadena de una fórmula a 255 caracteres.

Lo que de Marlowe **no** se copió es la mitad de su defensa que vive al leer
(`enlaces.validar` rechaza una clave en notación científica). Allá el CSV es de
entrada y se vuelve a leer; éste es de salida y Continental no lo lee nunca, así
que no hay lectura donde cazar el daño: la defensa tiene que ir al escribir.

## Las horas

El archivo **no lleva la hora en que se generó**: usaría el reloj del servidor,
que corre en UTC, y haría distintos dos archivos idénticos. Lo único con hora es
la firma del envío, y va escrita en UTC **diciéndolo**: el servidor no tiene la
zona de la farmacia (la torre ni siquiera tiene `tzdata`), y una hora sin zona
son seis horas de diferencia que nadie ve. La fecha del nombre es la de la lista
—`fecha_del_pedido`, anclada en `max(fecha)` del almacén—, nunca la del reloj.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
import unicodedata
from collections.abc import Callable, Iterable
from decimal import Decimal
from urllib.parse import quote

from continental.almacenamiento import (
    BORRADOR,
    CANCELADO,
    ENVIADO,
    PEDIDO_RECIBIDO,
    PEDIDO_RECIBIDO_PARCIAL,
    PedidoGuardado,
    RenglonGuardado,
)
from continental.particion import Captura, Linea, PedidoPorArmar
from continental.recepcion import PedidoALaVista

#: Las columnas, en el orden del ticket y con el IVA dicho en el propio nombre:
#: una nota arriba se pierde en cuanto alguien copia la tabla a otra hoja. La
#: séptima es la que hace que un hueco sea información (regla 4).
COLUMNAS: tuple[str, ...] = (
    "clave",
    "descripción",
    "cantidad",
    "precio unitario sin IVA",
    "importe sin IVA",
    "proveedor",
    "por qué no hay precio",
)

#: Lo que va en las celdas de dinero de una línea sin precio de ese proveedor.
#: Texto y no vacío: una celda vacía se suma como cero sin que nadie lo note.
SIN_PRECIO = "sin precio"

#: Lo que va en la celda del total cuando alguna línea va sin precio.
TOTAL_SIN_SABER = "sin saber"

#: Un producto que no está en el catálogo no tiene EAN: se busca por nombre en
#: el portal, igual que en la pantalla de captura.
SIN_CLAVE = "sin código de barras"

#: La trampa heredada, dicha arriba del archivo con todas sus letras.
LOS_PRECIOS_SON_SIN_IVA = (
    "Todo el dinero de este archivo es sin IVA: es el costo de compra, no el "
    "precio de mostrador, que sí lo lleva"
)

#: Lo que se sirve. El BOM va dentro de los bytes, no en el tipo.
TIPO_DEL_ARCHIVO = "text/csv; charset=utf-8"

#: Lo que Excel toma por el inicio de una fórmula. El tabulador y el retorno de
#: carro son de la lista de OWASP para inyección en CSV: otras hojas de cálculo
#: los quitan antes de mirar el primer carácter.
_INICIO_DE_FORMULA = ("=", "+", "-", "@", "\t", "\r")

#: Lo más largo que Excel acepta como cadena dentro de una fórmula.
_LARGO_MAXIMO_EN_FORMULA = 255

_CENTAVOS = Decimal("0.01")


# ---------------------------------------------------------- celdas para Excel


def texto_para_excel(valor: str) -> str:
    """`valor` como fórmula que devuelve ese texto: `="..."`.

    Es lo único que, medido, deja una clave de 13 dígitos intacta en Excel: ni
    notación científica ni ceros perdidos. Las comillas de adentro se doblan,
    que es como se escapan dentro de una cadena de fórmula; las de afuera las
    pone el módulo `csv`.
    """
    return '="' + valor.replace('"', '""') + '"'


def _celda(texto: str) -> str:
    """Texto libre que Excel no debe leer como fórmula.

    Solo se toca el que empieza como fórmula. Uno demasiado largo para ir
    dentro de una (255 caracteres) se protege con un espacio al frente, que
    cambia la celda en un carácter visible en vez de dejar que Excel la
    evalúe.
    """
    if not texto.startswith(_INICIO_DE_FORMULA):
        return texto
    if len(texto) <= _LARGO_MAXIMO_EN_FORMULA:
        return texto_para_excel(texto)
    return " " + texto


def _clave(clave: str) -> str:
    """La clave siempre como texto para Excel, o que no la hay — nunca vacía."""
    return texto_para_excel(clave) if clave else SIN_CLAVE


def _dinero(valor: Decimal) -> str:
    """Dos decimales, punto decimal y sin separador de miles.

    `format(..., "f")` y no `str()`: un `Decimal("1E+3")` se escribiría `1E+3`.
    """
    return format(valor.quantize(_CENTAVOS), "f")


def _en_utc(instante: dt.datetime) -> str:
    """Un instante en UTC, **diciéndolo**. Ver "Las horas" arriba.

    Uno sin zona se toma como UTC, que es como lo escribe todo este repo
    (`timestamptz` en Postgres, `dt.UTC` en los dobles).
    """
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=dt.UTC)
    return instante.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")


# ------------------------------------------------------------------ el archivo


def _borrador(pedido: PedidoGuardado, renglones: list[RenglonGuardado]) -> str:
    # El que más fácil se confunde: guardado en una carpeta se parece mucho a
    # un pedido hecho, y el glosario dice que todavía no se le pidió a nadie.
    return (
        f"borrador: todavía no se le ha pedido a nadie. Sirve para capturarlo "
        f"en el portal de {pedido.nombre} o para revisarlo; no es la "
        f"constancia de un pedido hecho"
    )


def _firma_del_envio(pedido: PedidoGuardado) -> str:
    """La firma en voz activa y el desmentido del ADR 0009, igual que la
    pantalla. Sigue siendo verdad cuando el pedido ya llegó (ADR 0015)."""
    cuando = "" if pedido.enviado_en is None else f" el {_en_utc(pedido.enviado_en)}"
    return (
        f"{pedido.enviado_por} dijo haberlo capturado en el portal "
        f"de {pedido.nombre}{cuando}. Continental no se lo mandó a nadie: "
        f"solo guarda quién lo dice y cuándo"
    )


def _enviado(pedido: PedidoGuardado, renglones: list[RenglonGuardado]) -> str:
    return f"enviado: {_firma_del_envio(pedido)}"


def _recibido(pedido: PedidoGuardado, renglones: list[RenglonGuardado]) -> str:
    # `recibido` y `recibido parcial` (ticket 27): la frase es la misma que la
    # pantalla enseña junto al pedido, y la firma del envío va detrás porque
    # sigue siendo verdad —alguien lo capturó en el portal—.
    vista = PedidoALaVista.de(pedido, renglones)
    return f"{vista.frase_de_la_recepcion} Antes, {_firma_del_envio(pedido)}"


def _cancelado(pedido: PedidoGuardado, renglones: list[RenglonGuardado]) -> str:
    # Cancelado (ticket 25): es el archivo que más se presta a confusión —dice
    # lo que se iba a pedir, y no se pidió—, así que lo dice con las dos firmas.
    cuando = "" if pedido.cancelado_en is None else f" el {_en_utc(pedido.cancelado_en)}"
    return (
        f"cancelado: {pedido.cancelado_por} dijo{cuando} que no está en el "
        f"portal de {pedido.nombre}. NO es la constancia de un pedido hecho; "
        f"lo suyo vuelve a proponerse en la siguiente lista"
    )


#: Qué se dice de cada uno de los cinco estados del glosario. **Se busca por el
#: estado CALCULADO** (`recepcion.PedidoALaVista`, ADR 0015), nunca por
#: `pedido.estado_declarado`: la columna de un pedido que ya llegó sigue
#: diciendo `enviado`, y el archivo lo decía también mientras la pantalla decía
#: `recibido`. Cuál es cuál se decide en un solo lugar; aquí solo se redacta.
_QUE_ES: dict[str, Callable[[PedidoGuardado, list[RenglonGuardado]], str]] = {
    BORRADOR: _borrador,
    ENVIADO: _enviado,
    PEDIDO_RECIBIDO: _recibido,
    PEDIDO_RECIBIDO_PARCIAL: _recibido,
    CANCELADO: _cancelado,
}


def _estado(pedido: PedidoGuardado, renglones: list[RenglonGuardado]) -> str:
    """Qué es este pedido, dicho para quien abra el archivo sin la pantalla."""
    estado = PedidoALaVista.de(pedido, renglones).estado
    redactar = _QUE_ES.get(estado)
    return estado if redactar is None else redactar(pedido, renglones)


def _porque_no_hay_precio(linea: Linea) -> str:
    if linea.tiene_precio:
        return ""
    if linea.detalle:
        return f"{linea.motivo}: {linea.detalle}"
    return linea.motivo or SIN_PRECIO


def _fila(linea: Linea, nombre: str) -> list[str]:
    return [
        _clave(linea.clave),
        _celda(linea.descripcion),
        str(linea.cantidad),
        SIN_PRECIO if linea.precio is None else _dinero(linea.precio),
        SIN_PRECIO if linea.importe is None else _dinero(linea.importe),
        _celda(nombre),
        _celda(_porque_no_hay_precio(linea)),
    ]


def filas_del_csv(
    pedido: PedidoGuardado,
    captura: Captura,
    fecha_del_pedido: dt.date,
    renglones: Iterable[RenglonGuardado],
) -> list[list[str]]:
    """El archivo como filas de texto: lo que después se escribe con `csv`.

    Arriba, cuatro renglones de contexto —a quién, de qué lista, en qué estado
    y que todo es sin IVA—; después la tabla con una fila por renglón del
    pedido **guardado**; y abajo el total, o por qué no se puede saber.

    `captura` es `particion.lo_que_hay_que_capturar(pedido, ...)`: las mismas
    líneas que la pantalla de captura, con el precio de ese proveedor.
    `renglones` son los de la lista: de ellos sale el estado **calculado** del
    pedido (ADR 0015), el mismo que la pantalla enseña.
    """
    nombre = pedido.nombre
    filas: list[list[str]] = [
        ["Pedido a", _celda(nombre)],
        ["Lista del día", fecha_del_pedido.isoformat()],
        ["Estado", _celda(_estado(pedido, list(renglones)))],
        [
            "Precios",
            f"{LOS_PRECIOS_SON_SIN_IVA}. El precio es el de {nombre}, congelado "
            f"la última vez que se le consultó, y no el más barato de los cuatro",
        ],
    ]
    if captura.descartados_dentro:
        filas.append(
            [
                "Descartados",
                f"{captura.descartados_dentro} renglón(es) de este pedido "
                f"descartado(s) después de armarlo: no van en este archivo, y "
                f"volver a partir los saca del pedido",
            ]
        )
    filas.append([])
    filas.append(list(COLUMNAS))
    filas.extend(_fila(linea, nombre) for linea in captura.lineas)

    # La regla del total vive en `PedidoPorArmar` (ticket 20) y aquí se usa, no
    # se reescribe: una regla escrita dos veces se cambia una sola.
    cuenta = PedidoPorArmar(proveedor=pedido.proveedor, lineas=captura.lineas)
    total = cuenta.total_sin_iva
    if total is None:
        faltan = cuenta.sin_precio
        porque = (
            f"{faltan} renglón va sin precio" if faltan == 1
            else f"{faltan} renglones van sin precio"
        ) + (
            f" de {nombre}, así que el total no se puede sumar. Lo que sí se "
            f"sabe suma {_dinero(cuenta.parcial_sin_iva)}"
        )
    else:
        porque = ""
    filas.append([])
    filas.append(
        [
            "",
            "Total sin IVA",
            str(cuenta.piezas),
            "",
            TOTAL_SIN_SABER if total is None else _dinero(total),
            _celda(nombre),
            porque,
        ]
    )

    # EL TOTAL GUARDADO, SOLO SI NO COINCIDE. `pedido.total_sin_iva` es el del
    # botón de enviar y se escribió al partir; un precio que llegue después no
    # lo recalcula (hilo 13 de `HANDOVER.md`, la mitad que sigue abierta). Si
    # el archivo solo enseñara la suma de ahora, los dos números diferirían sin
    # explicación — y el guardado es el que alguien vio antes de enviar.
    if pedido.total_sin_iva != total:
        guardado = (
            TOTAL_SIN_SABER if pedido.total_sin_iva is None
            else _dinero(pedido.total_sin_iva)
        )
        filas.append(
            [
                "",
                "Total guardado al armar el pedido",
                "",
                "",
                guardado,
                _celda(nombre),
                "no coincide con la suma de arriba: después de armarlo llegó "
                "un precio nuevo, cambió una cantidad o se descartó un renglón. "
                "Las líneas de arriba usan el último precio congelado",
            ]
        )
    return filas


def csv_del_pedido(
    pedido: PedidoGuardado,
    captura: Captura,
    fecha_del_pedido: dt.date,
    renglones: Iterable[RenglonGuardado],
) -> bytes:
    """Los bytes que se sirven: UTF-8 **con BOM**, coma, y `\\r\\n`.

    En memoria y nunca en disco. `\\r\\n` porque es lo que dice la RFC 4180 y lo
    que el Bloc de notas de Windows espera; el módulo `csv` lo pone igual por
    omisión, y aquí se escribe para que nadie lo cambie creyéndolo un descuido.
    """
    salida = io.StringIO()
    csv.writer(salida, lineterminator="\r\n").writerows(
        filas_del_csv(pedido, captura, fecha_del_pedido, renglones)
    )
    return salida.getvalue().encode("utf-8-sig")


# --------------------------------------------------------- el nombre del archivo


def _para_nombre(texto: str) -> str:
    """ASCII en minúsculas, con guiones: lo único que sobrevive a todos los
    sistemas de archivos y a un encabezado HTTP. `Ñandú` → `nandu`."""
    sin_acentos = (
        unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "-", sin_acentos.lower()).strip("-")


def nombre_del_archivo(
    pedido: PedidoGuardado,
    fecha_del_pedido: dt.date,
    renglones: Iterable[RenglonGuardado],
) -> str:
    """`pedido-2026-09-21-nadro-borrador.csv`.

    **La fecha es la de la lista**, no la de hoy ni la de `armado_en`: un pedido
    armado a las 22:30 de la farmacia ya es del día siguiente en UTC. **El
    proveedor es su clave de Doyle** y no su nombre de pantalla: es la identidad
    del pedido (ADR 0008) y ya es ASCII. **Y el estado va en el nombre**, que el
    ticket no pide: un borrador guardado en una carpeta no debe poder
    confundirse, por su nombre, con lo que se capturó en el portal.

    **El estado es el calculado** (ADR 0015), no la columna: un pedido que ya
    llegó se baja como `…-recibido.csv` o `…-recibido-parcial.csv`, igual que
    la pantalla lo dice. En la tabla seguiría `enviado`.
    """
    proveedor = _para_nombre(pedido.proveedor) or "proveedor"
    estado = _para_nombre(PedidoALaVista.de(pedido, renglones).estado) or "pedido"
    return f"pedido-{fecha_del_pedido.isoformat()}-{proveedor}-{estado}.csv"


def disposicion_de_descarga(nombre: str) -> str:
    """El `Content-Disposition` que hace que el navegador lo baje con su nombre.

    `filename` en ASCII y `filename*` en UTF-8 (RFC 6266). Starlette codifica
    los encabezados en latin-1: un carácter fuera de ahí no da un nombre feo, da
    un **500**. `nombre_del_archivo` ya devuelve ASCII; esto no confía en ello.
    """
    ascii_ = _para_nombre(nombre.removesuffix(".csv")) or "pedido"
    if nombre.endswith(".csv"):
        ascii_ += ".csv"
    return f"attachment; filename=\"{ascii_}\"; filename*=UTF-8''{quote(nombre)}"
