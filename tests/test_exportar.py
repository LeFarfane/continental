"""Exportar un pedido a CSV: el respaldo que ya se sabe que sirve (ticket 23).

El pedido en un archivo que se abre en Excel, se manda por correo o se guarda.
Las Órdenes de Doyle ya lo hacían y el ADR 0002 las retira al entrar este
módulo: *"su exportación a CSV y el costo congelado se reproducen aquí"*.

**El daño que este archivo vigila no es hipotético.** Marlowe lo sufrió el
2026-09-03 (`Marlowe/tests/test_excel.py`): alguien abrió un CSV en Excel y los
códigos de barras pasaron a `7.50222E+12` y los SKU perdieron sus ceros a la
izquierda, sin un solo error. Y aquí se volvió a medir, con el Excel 16 de la
torre (es-MX) el 2026-09-21, antes de escribir una línea:

| Lo que va en la celda | Lo que Excel enseña |
|---|---|
| `7501234567890` | `7.5012E+12` |
| `0012345678905` | `1.2346E+10` — y el valor ya es `12345678905` |
| `="7501234567890"` | `7501234567890`, como texto |
| `="0012345678905"` | `0012345678905`, con sus ceros |
| tabulador o apóstrofo al frente | el tabulador o el apóstrofo, **literales** |
| `-GUION`, `+MAS` | `#¿NOMBRE?`: lo leyó como fórmula |
| `=1+1` | `2`: **la evaluó** |
| `ÁCIDO FÓLICO` sin BOM | `ÃCIDO FÃ“LICO` |

Marlowe se defiende **al leer** —su CSV es de entrada, lo vuelve a leer y
rechaza lo que Excel estropeó—. Éste es de **salida**: Continental no lo vuelve
a leer nunca, así que no hay lectura donde cazar el daño. La defensa tiene que
ir al escribir, y por eso se escribe distinto (ver `continental/exportar.py`).

Los tres seams del repo:

1. **Lo puro** —`exportar.filas_del_csv`, `csv_del_pedido`,
   `nombre_del_archivo` y `disposicion_de_descarga`—, sin base, sin red y sin
   reloj.
2. **Lo que se ve** —la ruta con sus bordes sustituidos por los dobles, y la
   pantalla leída como texto—.
3. **Lo que NO se guarda** —la cuarta casilla—: la ruta no escribe un solo
   archivo, y `.gitignore` tapa el que alguien baje a mano dentro del repo.

Ninguna prueba toca Postgres, ninguna duerme, y la única que escribe un archivo
lo hace en `tmp_path`.
"""

from __future__ import annotations

import ast
import csv
import datetime as dt
import io
import re
from decimal import Decimal
from pathlib import Path

import pytest

from conftest import pantalla_completa
from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import (
    BORRADOR,
    ENVIADO,
    PedidoGuardado,
    PrecioDeProveedor,
    RENGLON_ABIERTO,
    RENGLON_CANCELADO,
    RENGLON_DESCARTADO,
    RENGLON_EN_TRANSITO,
    RENGLON_RECIBIDO,
    RENGLON_RECIBIDO_PARCIAL,
    RenglonGuardado,
)
from continental.exportar import (
    COLUMNAS,
    LOS_PRECIOS_SON_SIN_IVA,
    SIN_CLAVE,
    SIN_PRECIO,
    TIPO_DEL_ARCHIVO,
    TOTAL_SIN_SABER,
    csv_del_pedido,
    disposicion_de_descarga,
    filas_del_csv,
    nombre_del_archivo,
    texto_para_excel,
)
from continental.particion import (
    SIN_CONSULTARLE,
    SIN_PRECIO_DE_ESE_PROVEEDOR,
    lo_que_hay_que_capturar,
)
from continental.precios import LecturaDePrecio, SESION_CADUCADA
from continental.sugerido import Renglon

RAIZ = Path(__file__).resolve().parent.parent
EXPORTAR = RAIZ / "src" / "continental" / "exportar.py"
# La pantalla entera —HTML, CSS y JavaScript— sale de `conftest.pantalla_completa`
# desde el ticket 28, que la separó en tres archivos: leer solo `index.html`
# dejaría las guardias de "esto NO está" revisando un texto sin el JavaScript.
GITIGNORE = RAIZ / ".gitignore"

RUTA = "/api/pedido-sugerido"
NEGOCIO = "farmacia_01"
HOY = dt.date(2024, 3, 5)
CORREO = "encargado@farmacia.mx"
#: A las 22:30 de Guadalajara ya es el día siguiente en UTC. Es la trampa del
#: contenedor, y por eso el nombre del archivo NO sale de aquí.
ARMADO = dt.datetime(2024, 3, 6, 4, 30, tzinfo=dt.UTC)
BOM = b"\xef\xbb\xbf"  # el BOM de UTF-8, escrito como escape para que se vea


# ------------------------------------------------------------- utilidades


def _renglon(
    renglon_id: int,
    clave: str = "7501000000001",
    descripcion: str | None = None,
    cantidad: int = 3,
    estado: str = RENGLON_ABIERTO,
    pedido_id: int | None = 7,
) -> RenglonGuardado:
    return RenglonGuardado(
        renglon_id=renglon_id,
        estado=estado,
        propuesto=Renglon(
            producto_id=renglon_id,
            clave=clave,
            descripcion=descripcion or f"PRODUCTO {renglon_id}",
            piezas_vendidas=float(cantidad),
            cantidad_propuesta=cantidad,
            esta_en_el_catalogo=bool(clave),
            existencia=None if not clave else 0.0,
            dias_de_cobertura=None,
            clasificacion="medicamento",
        ),
        descartado_por=CORREO if estado == RENGLON_DESCARTADO else None,
        descartado_en=ARMADO if estado == RENGLON_DESCARTADO else None,
        pedido_id=pedido_id,
    )


def _pedido(
    estado: str = BORRADOR,
    proveedor: str = "nadro",
    total: str | None = None,
) -> PedidoGuardado:
    return PedidoGuardado(
        pedido_id=7,
        negocio=NEGOCIO,
        pedido_sugerido_id=1,
        proveedor=proveedor,
        proveedor_id=1,
        estado=estado,
        armado_en=ARMADO,
        total_sin_iva=None if total is None else Decimal(total),
        enviado_por=CORREO if estado == ENVIADO else None,
        enviado_en=ARMADO if estado == ENVIADO else None,
    )


def _precio(renglon_id: int, proveedor: str, precio: str | None) -> PrecioDeProveedor:
    return PrecioDeProveedor(
        renglon_id=renglon_id,
        proveedor=proveedor,
        consultado_en=ARMADO,
        precio_como_llego="" if precio is None else precio,
        precio=None if precio is None else Decimal(precio),
        motivo=None if precio is not None else SESION_CADUCADA,
    )


def _filas(pedido, renglones, precios) -> list[list[str]]:
    captura = lo_que_hay_que_capturar(pedido, renglones, precios)
    return filas_del_csv(pedido, captura, HOY, renglones)


def _tabla(filas: list[list[str]]) -> list[dict[str, str]]:
    """Las filas de datos debajo del encabezado de columnas, como diccionarios.

    Se detiene en la primera fila en blanco: lo que sigue es el total.
    """
    inicio = filas.index(list(COLUMNAS)) + 1
    datos = []
    for fila in filas[inicio:]:
        if not any(fila):
            break
        datos.append(dict(zip(COLUMNAS, fila)))
    return datos


def _fila_del_total(filas: list[list[str]]) -> dict[str, str]:
    fila = next(f for f in filas if len(f) > 1 and f[1] == "Total sin IVA")
    return dict(zip(COLUMNAS, fila))


def _leer(contenido: bytes) -> list[list[str]]:
    """Lo que un lector de CSV sacaría del archivo, sin tocar un disco."""
    return list(csv.reader(io.StringIO(contenido.decode("utf-8-sig"), newline="")))


# ==========================================================================
# CASILLA 1 — un CSV por pedido con clave, descripción, cantidad, precio
# unitario congelado, importe y proveedor
# ==========================================================================


def test_las_seis_columnas_del_ticket_estan_y_en_ese_orden():
    """El encabezado nombra las seis del ticket, y las dos de dinero dicen
    **sin IVA** en la propia columna — no en una nota que se pierde al copiar."""
    assert COLUMNAS[:6] == (
        "clave",
        "descripción",
        "cantidad",
        "precio unitario sin IVA",
        "importe sin IVA",
        "proveedor",
    )


def test_una_fila_por_renglon_del_pedido():
    filas = _filas(
        _pedido(),
        [_renglon(1, cantidad=4), _renglon(2, clave="7501000000002", cantidad=2)],
        {1: [_precio(1, "nadro", "12.50")], 2: [_precio(2, "nadro", "3.10")]},
    )
    tabla = _tabla(filas)

    assert [f["descripción"] for f in tabla] == ["PRODUCTO 1", "PRODUCTO 2"]
    assert tabla[0]["cantidad"] == "4"
    assert tabla[0]["precio unitario sin IVA"] == "12.50"
    assert tabla[0]["importe sin IVA"] == "50.00"
    assert tabla[0]["proveedor"] == "NADRO"


def test_el_precio_es_el_de_ESE_proveedor_y_no_el_mas_barato():
    """**ADR 0004 y la quinta casilla del 20.** El pedido de NADRO lleva el
    precio de NADRO aunque LEVIC lo dé más barato: es el que va a salir en el
    carrito de NADRO y el que se compara contra su factura."""
    filas = _filas(
        _pedido(proveedor="nadro"),
        [_renglon(1)],
        {1: [_precio(1, "levic", "9.00"), _precio(1, "nadro", "12.50")]},
    )
    assert _tabla(filas)[0]["precio unitario sin IVA"] == "12.50"


def test_el_importe_se_multiplica_en_decimal_y_no_en_coma_flotante():
    """`3 × 10.10` en coma flotante es `30.299999999999997`. En el archivo que
    se compara contra una factura, eso es un centavo que nadie sabe explicar."""
    filas = _filas(_pedido(), [_renglon(1, cantidad=3)], {1: [_precio(1, "nadro", "10.10")]})
    assert _tabla(filas)[0]["importe sin IVA"] == "30.30"


def test_el_dinero_siempre_va_con_dos_decimales_y_sin_separador_de_miles():
    """Un `1,234.50` con coma de miles partiría la celda en dos en cuanto un
    lector no respete las comillas; y `Decimal("1E+3")` se escribiría `1E+3`."""
    filas = _filas(
        _pedido(),
        [_renglon(1, cantidad=1), _renglon(2, clave="7501000000002", cantidad=2)],
        {1: [_precio(1, "nadro", "1234.5")], 2: [_precio(2, "nadro", "1E+3")]},
    )
    tabla = _tabla(filas)
    assert tabla[0]["precio unitario sin IVA"] == "1234.50"
    assert tabla[1]["precio unitario sin IVA"] == "1000.00"
    assert tabla[1]["importe sin IVA"] == "2000.00"


def test_sin_precio_de_ese_proveedor_no_es_cero_ni_una_celda_vacia():
    """**Regla 4.** Una celda vacía en Excel se ve igual que un cero cuando
    alguien suma la columna. Se escribe `sin precio`, con el porqué al lado."""
    filas = _filas(_pedido(), [_renglon(1)], {1: [_precio(1, "nadro", None)]})
    fila = _tabla(filas)[0]

    assert fila["precio unitario sin IVA"] == SIN_PRECIO
    assert fila["importe sin IVA"] == SIN_PRECIO
    assert SIN_PRECIO_DE_ESE_PROVEEDOR in fila["por qué no hay precio"]
    assert "sesión" in fila["por qué no hay precio"]
    assert "0.00" not in ",".join(fila.values())


def test_no_haberle_consultado_se_distingue_de_que_no_diera_precio():
    """Uno se arregla apretando el botón y el otro mirando el motivo."""
    filas = _filas(_pedido(), [_renglon(1)], {})
    assert _tabla(filas)[0]["por qué no hay precio"] == SIN_CONSULTARLE


def test_con_precio_la_columna_del_porque_va_vacia():
    filas = _filas(_pedido(), [_renglon(1)], {1: [_precio(1, "nadro", "12.50")]})
    assert _tabla(filas)[0]["por qué no hay precio"] == ""


def test_el_total_es_la_suma_cuando_todas_tienen_precio():
    filas = _filas(
        _pedido(total="44.70"),
        [_renglon(1, cantidad=3), _renglon(2, clave="7501000000002", cantidad=1)],
        {1: [_precio(1, "nadro", "10.10")], 2: [_precio(2, "nadro", "14.40")]},
    )
    total = _fila_del_total(filas)
    assert total["importe sin IVA"] == "44.70"
    assert total["cantidad"] == "4", "la cantidad del total son las piezas"


def test_con_una_linea_sin_precio_el_total_NO_es_la_suma_de_las_demas():
    """**Lo mismo que `total_sin_iva` en NULL del ticket 20.** Un total parcial
    se compara contra la factura, no cuadra, y nadie sabe si falta mercancía o
    falta un precio. El parcial va dicho con palabras, con su conteo."""
    filas = _filas(
        _pedido(),
        [_renglon(1, cantidad=3), _renglon(2, clave="7501000000002", cantidad=1)],
        {1: [_precio(1, "nadro", "10.10")], 2: [_precio(2, "nadro", None)]},
    )
    total = _fila_del_total(filas)

    assert total["importe sin IVA"] == TOTAL_SIN_SABER
    assert "30.30" != total["importe sin IVA"]
    assert "1 renglón va sin precio" in total["por qué no hay precio"]
    assert "30.30" in total["por qué no hay precio"], "el parcial se dice, no se esconde"


def test_el_total_guardado_al_armar_se_dice_solo_si_no_coincide():
    """`pedido.total_sin_iva` se escribe al partir, y un precio nuevo después no
    lo recalcula (hilo 13 de `HANDOVER.md`, la mitad que sigue abierta). Si el
    archivo enseñara solo la suma de ahora, el total del botón y el del archivo
    diferirían sin explicación. Si coinciden, repetirlo es ruido."""
    renglones = [_renglon(1, cantidad=2)]
    precios = {1: [_precio(1, "nadro", "10.00")]}

    igual = _filas(_pedido(total="20.00"), renglones, precios)
    distinto = _filas(_pedido(total="18.00"), renglones, precios)

    assert not any("al armar" in c for f in igual for c in f)
    fila = next(f for f in distinto if any("al armar" in c for c in f))
    assert "18.00" in fila
    assert "no coincide" in ",".join(fila)


def test_un_descartado_dentro_del_pedido_no_va_y_se_dice():
    """El mismo trato que la captura del 22: teclearlo sería comprar lo que
    alguien decidió no comprar, y callarlo haría que el archivo y la pantalla
    contaran distinto."""
    filas = _filas(
        _pedido(),
        [_renglon(1), _renglon(2, clave="7501000000002", estado=RENGLON_DESCARTADO)],
        {1: [_precio(1, "nadro", "10.00")]},
    )
    assert [f["descripción"] for f in _tabla(filas)] == ["PRODUCTO 1"]
    assert any("descartado" in c for f in filas for c in f)


def test_solo_entran_los_renglones_del_pedido_guardado():
    """La trampa del 22 vale igual aquí: lo que se exporta es lo que tiene
    `pedido_id`, no lo que la vista previa pondría hoy en NADRO."""
    filas = _filas(
        _pedido(),
        [_renglon(1, pedido_id=7), _renglon(2, clave="7501000000002", pedido_id=8)],
        {},
    )
    assert [f["descripción"] for f in _tabla(filas)] == ["PRODUCTO 1"]


def test_el_encabezado_dice_que_todo_es_sin_iva():
    """**Trampa heredada de `CLAUDE.md`**: el costo nuestro es sin IVA y el de
    mostrador con IVA. Quien abra el archivo sin saberlo le suma el 16% de más
    o de menos al comparar con la factura."""
    filas = _filas(_pedido(), [_renglon(1)], {})
    assert any(LOS_PRECIOS_SON_SIN_IVA in c for f in filas for c in f)
    assert "sin IVA" in LOS_PRECIOS_SON_SIN_IVA
    assert "NADRO" in ",".join(c for f in filas[:6] for c in f)


def test_un_borrador_dice_que_no_se_le_ha_pedido_a_nadie():
    """Un borrador guardado en una carpeta se parece mucho a un pedido hecho.
    El glosario: *borrador — todavía no se le pidió a nadie*."""
    texto = ",".join(c for f in _filas(_pedido(BORRADOR), [_renglon(1)], {}) for c in f)
    assert "borrador" in texto
    assert "no se le ha pedido a nadie" in texto


def test_un_enviado_dice_quien_lo_capturo_y_cuando_en_utc():
    """**ADR 0009**: la firma, en voz activa, y el desmentido. La hora va en
    UTC y lo dice: el servidor no tiene la zona de la farmacia, y una hora sin
    zona es seis horas de diferencia que nadie ve."""
    texto = ",".join(c for f in _filas(_pedido(ENVIADO), [_renglon(1)], {}) for c in f)
    assert CORREO in texto
    assert "2024-03-06 04:30 UTC" in texto
    assert "Continental no se lo mandó a nadie" in texto


# ==========================================================================
# CASILLA 3 — sobrevive a Excel
# ==========================================================================


def test_la_clave_va_como_formula_de_texto():
    """**El caso de Marlowe.** Medido en el Excel de la torre: sin esto se ve
    `7.5012E+12`, y guardarlo lo deja así para siempre."""
    filas = _filas(_pedido(), [_renglon(1, clave="7501234567890")], {})
    assert _tabla(filas)[0]["clave"] == '="7501234567890"'


def test_la_clave_con_ceros_a_la_izquierda_los_conserva():
    """Medido: `0012345678905` cruda se vuelve `12345678905` — otro producto."""
    filas = _filas(_pedido(), [_renglon(1, clave="0012345678905")], {})
    assert _tabla(filas)[0]["clave"] == '="0012345678905"'


def test_ninguna_celda_lleva_un_numero_largo_desnudo():
    """La regla escrita como barrido y no como caso: ninguna celda del archivo
    —encabezado, datos o total— es una tira de 12 o más dígitos sin proteger."""
    filas = _filas(
        _pedido(ENVIADO, total="30.00"),
        [_renglon(1, clave="7501234567890"), _renglon(2, clave="0000000000017")],
        {1: [_precio(1, "nadro", "10.00")]},
    )
    for fila in filas:
        for celda in fila:
            assert not re.fullmatch(r"\s*\d{12,}\s*", celda), celda


def test_un_renglon_sin_clave_lo_dice_y_no_deja_la_celda_vacia():
    filas = _filas(_pedido(), [_renglon(1, clave="")], {})
    assert _tabla(filas)[0]["clave"] == SIN_CLAVE


@pytest.mark.parametrize(
    "descripcion",
    ["-GUION AL INICIO", "=1+1", "+MAS", "@ARROBA", "\tTAB", "\rRETORNO"],
)
def test_una_descripcion_que_empieza_como_formula_no_se_evalua(descripcion):
    """Medido: `-GUION` sale `#¿NOMBRE?` y `=1+1` sale `2`. Una descripción
    viene del catálogo de SICAR, y el catálogo lo captura una persona."""
    filas = _filas(_pedido(), [_renglon(1, descripcion=descripcion)], {})
    celda = _tabla(filas)[0]["descripción"]
    assert celda.startswith('="') and celda.endswith('"')
    assert descripcion in celda


def test_la_proteccion_dobla_las_comillas_de_adentro():
    """Una comilla sin doblar cerraría la cadena de la fórmula a la mitad."""
    assert texto_para_excel('-JERINGA "X"') == '="-JERINGA ""X"""'


def test_una_descripcion_normal_no_se_toca():
    """Envolver todo en fórmula lo protegería igual, pero Excel limita la cadena
    de una fórmula a 255 caracteres y un lector que no sea Excel vería `="..."`
    en cada renglón. Solo se protege lo que hace falta proteger."""
    filas = _filas(_pedido(), [_renglon(1, descripcion="ÁCIDO FÓLICO 5 MG")], {})
    assert _tabla(filas)[0]["descripción"] == "ÁCIDO FÓLICO 5 MG"


def test_el_archivo_empieza_con_bom_para_que_excel_lea_los_acentos():
    """Medido: sin BOM, `ÁCIDO FÓLICO` se ve `ÃCIDO FÃ“LICO`. Es lo mismo que
    Marlowe escribió en `alta.escribir_csv` el 2026-09-03."""
    renglones = [_renglon(1, descripcion="ÁCIDO FÓLICO ñ")]
    captura = lo_que_hay_que_capturar(_pedido(), renglones, {})
    contenido = csv_del_pedido(_pedido(), captura, HOY, renglones)

    assert contenido.startswith(BOM)
    assert "ÁCIDO FÓLICO ñ" in contenido.decode("utf-8-sig")


def test_separador_coma_decimal_punto_y_fin_de_linea_de_windows():
    """**Medido en la torre (es-MX)**: separador de lista `,` y decimal `.`. Es
    la configuración de México —no la de España, que usa `;` y coma decimal—, y
    con ella Excel parte las columnas y lee `86.05` como número sin preguntar.
    Por eso NO va la línea `sep=,`: en es-MX sobra, y Excel ignora el BOM
    cuando la encuentra."""
    renglones = [_renglon(1)]
    captura = lo_que_hay_que_capturar(
        _pedido(), renglones, {1: [_precio(1, "nadro", "86.05")]}
    )
    contenido = csv_del_pedido(_pedido(), captura, HOY, renglones)
    texto = contenido.decode("utf-8-sig")

    assert not texto.startswith("sep=")
    assert "\r\n" in texto and "\n" not in texto.replace("\r\n", "")
    assert ',86.05,' in texto


def test_una_descripcion_con_coma_y_comillas_vuelve_intacta():
    renglones = [_renglon(1, descripcion='JERINGA 3ML, 21G "X"')]
    captura = lo_que_hay_que_capturar(_pedido(), renglones, {})
    filas = _leer(csv_del_pedido(_pedido(), captura, HOY, renglones))
    assert _tabla(filas)[0]["descripción"] == 'JERINGA 3ML, 21G "X"'


def test_lo_que_se_escribe_es_lo_que_se_lee(tmp_path):
    """El viaje entero por un archivo de verdad, **en `tmp_path`** y nunca en el
    repo: escrito como lo baja el navegador y leído como `utf-8-sig`."""
    pedido = _pedido()
    renglones = [_renglon(1, clave="0012345678905", descripcion="ÁCIDO, FÓLICO")]
    captura = lo_que_hay_que_capturar(
        pedido, renglones, {1: [_precio(1, "nadro", "10.10")]}
    )
    archivo = tmp_path / nombre_del_archivo(pedido, HOY, renglones)
    archivo.write_bytes(csv_del_pedido(pedido, captura, HOY, renglones))

    with open(archivo, encoding="utf-8-sig", newline="") as f:
        leidas = list(csv.reader(f))

    assert leidas == filas_del_csv(pedido, captura, HOY, renglones)


# ==========================================================================
# CASILLA 2 — la fecha y el proveedor en el nombre del archivo
# ==========================================================================


def test_el_nombre_lleva_la_fecha_de_la_lista_el_proveedor_y_el_estado():
    # En camino: el estado calculado de un enviado sigue siendo `enviado`.
    en_camino = [_renglon(1, estado=RENGLON_EN_TRANSITO)]
    assert (
        nombre_del_archivo(_pedido(BORRADOR), HOY, [_renglon(1)])
        == "pedido-2024-03-05-nadro-borrador.csv"
    )
    assert (
        nombre_del_archivo(_pedido(ENVIADO), HOY, en_camino)
        == "pedido-2024-03-05-nadro-enviado.csv"
    )


def test_la_fecha_es_la_de_la_lista_y_no_la_del_reloj():
    """**Trampa heredada**: todo se ancla en el dato, nunca en el reloj. El
    pedido se armó a las 04:30 UTC del día 6 —las 22:30 del 5 en la farmacia—,
    y el archivo es de la lista del 5."""
    assert ARMADO.date() == dt.date(2024, 3, 6)
    assert "2024-03-05" in nombre_del_archivo(_pedido(), HOY, [_renglon(1)])
    assert "2024-03-06" not in nombre_del_archivo(_pedido(), HOY, [_renglon(1)])


@pytest.mark.parametrize(
    "proveedor", ["Farmacéutica Ñandú", 'nadro"; x=1', "../../etc", "levic\r\nX-Otra: 1", "   "]
)
def test_un_proveedor_raro_no_rompe_el_nombre(proveedor):
    """La clave del proveedor viene de la tabla, y el glosario la da como
    cerrada — pero `partir` acepta cualquier otra detrás de los cuatro. El
    nombre sale en ASCII, sin comillas, sin barras y sin saltos de línea."""
    nombre = nombre_del_archivo(_pedido(proveedor=proveedor), HOY, [_renglon(1)])
    assert re.fullmatch(r"pedido-2024-03-05-[a-z0-9-]+-borrador\.csv", nombre), nombre
    assert "--" not in nombre


def test_la_disposicion_es_de_descarga_y_cabe_en_un_encabezado_http():
    """Starlette codifica los encabezados en latin-1: un carácter fuera de ahí
    no da un nombre feo, da un **500**. Va el `filename` en ASCII y el
    `filename*` de la RFC 6266 para lo demás."""
    valor = disposicion_de_descarga("pedido-2024-03-05-farmacéutica ñ.csv")
    valor.encode("latin-1")
    assert valor.startswith("attachment; ")
    assert "filename*=UTF-8''" in valor
    assert "\r" not in valor and "\n" not in valor


def test_la_disposicion_de_un_nombre_ascii():
    valor = disposicion_de_descarga("pedido-2024-03-05-nadro-borrador.csv")
    assert 'filename="pedido-2024-03-05-nadro-borrador.csv"' in valor


def test_el_tipo_es_csv_en_utf8():
    assert TIPO_DEL_ARCHIVO == "text/csv; charset=utf-8"


# ==========================================================================
# LO PURO ES PURO
# ==========================================================================


def test_exportar_no_toca_la_red_la_base_ni_el_disco():
    """**Casilla 4 por construcción.** El módulo no importa nada con qué
    escribir un archivo ni con qué abrir una conexión: devuelve bytes, y quien
    llama decide qué hacer con ellos."""
    arbol = ast.parse(EXPORTAR.read_text(encoding="utf-8"))
    importados = {
        (n.module or "").split(".")[0] if isinstance(n, ast.ImportFrom) else a.name.split(".")[0]
        for n in ast.walk(arbol)
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in (n.names if isinstance(n, ast.Import) else [n])
    }
    assert not importados & {"sqlalchemy", "httpx", "fastapi", "starlette", "os", "pathlib", "shutil"}
    llamadas = {
        n.func.id for n in ast.walk(arbol) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "open" not in llamadas


def test_sin_librerias_vectorizadas():
    """Atlas es un Athlon II X4 de 2010 sin SSSE3: pandas muere ahí."""
    texto = EXPORTAR.read_text(encoding="utf-8")
    assert "import pandas" not in texto and "import numpy" not in texto
    assert "import csv" in texto


# ==========================================================================
# LO QUE SE VE — la ruta
# ==========================================================================


def _venta(fecha: dt.date, producto_id: int, cantidad: float) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=fecha,
        producto_id=producto_id,
        cantidad=cantidad,
        importe=cantidad * 10.0,
        costo=cantidad * 6.0,
        utilidad=cantidad * 4.0,
    )


def _producto(producto_id: int, clave: str, descripcion: str) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=clave,
        descripcion=descripcion,
        categoria="MEDICAMENTO",
        departamento="FARMACIA",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=50.0,
        costo=30.0,
        existencia=0.0,
        esta_activo=True,
        es_granel=False,
    )


def _lectura(proveedor: str, precio: str | None) -> LecturaDePrecio:
    return LecturaDePrecio(
        proveedor=proveedor,
        precio_como_llego="" if precio is None else precio,
        precio=None if precio is None else Decimal(precio),
        existencia_como_llego="40",
        existencia=Decimal("40"),
        motivo=None if precio is not None else SESION_CADUCADA,
    )


#: Dos productos de mentira, con lo que el ticket pide cuidar: una clave con
#: ceros a la izquierda y una descripción con acentos y coma.
CATALOGO = [
    ("0012345678905", "ÁCIDO FÓLICO, 5 MG"),
    ("7501234567890", "OMEPRAZOL 20 MG"),
]


def _pedido_partido(cliente, almacen, almacenamiento, precios=("10.10", "20.00")):
    # 3 piezas de cada uno: 3 × 10.10 + 3 × 20.00 = 90.30.
    """La lista del día con los dos productos, precios de NADRO, partida.

    Devuelve `(lista_id, pedido_json)`.
    """
    almacen.catalogo_en_memoria = [
        _producto(n, clave, desc) for n, (clave, desc) in enumerate(CATALOGO, start=1)
    ]
    almacen.ventas_en_memoria = [_venta(HOY, n, 3) for n in range(1, len(CATALOGO) + 1)]
    lista = cliente.get(RUTA).json()
    for renglon, precio in zip(lista["renglones"], precios):
        almacenamiento.guardar_precios(
            NEGOCIO, renglon["renglon_id"], [_lectura("nadro", precio)]
        )
    partida = cliente.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()
    return lista["pedido_sugerido_id"], partida["pedidos"][0]


def _url(lista_id: int, pedido_id: int) -> str:
    return f"{RUTA}/{lista_id}/pedido/{pedido_id}/csv"


def test_la_ruta_sirve_el_csv_como_descarga(cliente, almacen, almacenamiento):
    lista_id, pedido = _pedido_partido(cliente, almacen, almacenamiento)

    respuesta = cliente.get(_url(lista_id, pedido["pedido_id"]))

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == TIPO_DEL_ARCHIVO
    assert respuesta.headers["content-disposition"].startswith("attachment; ")
    assert "nadro-borrador.csv" in respuesta.headers["content-disposition"]
    assert respuesta.content.startswith(BOM)

    tabla = _tabla(_leer(respuesta.content))
    assert {f["clave"] for f in tabla} == {'="0012345678905"', '="7501234567890"'}
    assert "ÁCIDO FÓLICO, 5 MG" in {f["descripción"] for f in tabla}
    assert {f["proveedor"] for f in tabla} == {"NADRO"}


def test_la_fecha_del_nombre_es_la_de_la_lista(cliente, almacen, almacenamiento):
    lista_id, pedido = _pedido_partido(cliente, almacen, almacenamiento)
    respuesta = cliente.get(_url(lista_id, pedido["pedido_id"]))
    lista = almacenamiento.leer_por_id(NEGOCIO, lista_id)
    fecha = lista.fecha_del_pedido.isoformat()
    assert f"pedido-{fecha}-nadro-borrador.csv" in respuesta.headers["content-disposition"]


def test_un_pedido_enviado_tambien_se_exporta_y_lo_dice(cliente, almacen, almacenamiento):
    """**El respaldo de lo que se pidió** es justo el caso que más importa. Y el
    archivo cambia de nombre: un borrador guardado en una carpeta no debe
    poder confundirse con lo que se capturó."""
    lista_id, pedido = _pedido_partido(cliente, almacen, almacenamiento)
    cliente.post(
        f"/api/pedido/{pedido['pedido_id']}/enviar",
        headers={"Cf-Access-Authenticated-User-Email": CORREO},
    )

    respuesta = cliente.get(_url(lista_id, pedido["pedido_id"]))

    assert respuesta.status_code == 200
    assert "nadro-enviado.csv" in respuesta.headers["content-disposition"]
    texto = respuesta.content.decode("utf-8-sig")
    assert CORREO in texto
    assert len(_tabla(_leer(respuesta.content))) == 2, "sus renglones en tránsito van igual"


def test_sin_precio_la_ruta_escribe_sin_saber_y_nunca_cero(cliente, almacen, almacenamiento):
    """El caso ordinario, no el raro: el pedido se armó con precio y después se
    volvió a consultar con la sesión caducada. La tabla solo crece (ADR 0004) y
    la lectura más reciente de NADRO ya no trae precio.

    Y es también el caso del total guardado que ya no coincide: el botón de
    enviar decía `$90.30` y ahora no se puede sumar. El archivo dice las dos
    cosas en vez de elegir una."""
    lista_id, pedido = _pedido_partido(cliente, almacen, almacenamiento)
    segundo = almacenamiento.leer_por_id(NEGOCIO, lista_id).renglones[1]
    almacenamiento.guardar_precios(NEGOCIO, segundo.renglon_id, [_lectura("nadro", None)])

    filas = _leer(cliente.get(_url(lista_id, pedido["pedido_id"])).content)

    assert _fila_del_total(filas)["importe sin IVA"] == TOTAL_SIN_SABER
    assert SIN_PRECIO in {f["importe sin IVA"] for f in _tabla(filas)}
    guardado = next(f for f in filas if len(f) > 1 and f[1].startswith("Total guardado"))
    assert guardado[4] == pedido["total_sin_iva"] == "90.30"
    assert not any(c == "0.00" for f in filas for c in f)


def test_regenerarlo_da_el_mismo_archivo(cliente, almacen, almacenamiento):
    """**Casilla 4.** Se regenera cuando se pida, y sin reloj dentro: pedirlo dos
    veces sin que nada cambie da los mismos bytes. Un "generado el ..." haría
    distintos dos archivos idénticos, y usaría el reloj del servidor, que corre
    en UTC."""
    lista_id, pedido = _pedido_partido(cliente, almacen, almacenamiento)
    url = _url(lista_id, pedido["pedido_id"])
    assert cliente.get(url).content == cliente.get(url).content


def test_regenerarlo_trae_lo_de_ahora(cliente, almacen, almacenamiento):
    """Y como no se guarda, no envejece: enviar el pedido cambia lo que dice."""
    lista_id, pedido = _pedido_partido(cliente, almacen, almacenamiento)
    url = _url(lista_id, pedido["pedido_id"])
    antes = cliente.get(url).content
    cliente.post(f"/api/pedido/{pedido['pedido_id']}/enviar")
    assert cliente.get(url).content != antes


def test_la_ruta_no_escribe_un_solo_archivo_en_el_repo(cliente, almacen, almacenamiento):
    """**Casilla 4, de punta a punta.** Se arma en memoria y se sirve: ni en
    `data/export/` —que `.gitignore` anticipó desde el primer día— ni en
    ninguna otra parte del árbol."""
    antes = {p for p in RAIZ.rglob("*.csv") if ".venv" not in p.parts}
    lista_id, pedido = _pedido_partido(cliente, almacen, almacenamiento)

    cliente.get(_url(lista_id, pedido["pedido_id"]))

    despues = {p for p in RAIZ.rglob("*.csv") if ".venv" not in p.parts}
    assert despues == antes
    assert not (RAIZ / "data" / "export").exists()


def test_un_pedido_que_no_es_de_esa_lista_es_404(cliente, almacen, almacenamiento):
    lista_id, pedido = _pedido_partido(cliente, almacen, almacenamiento)

    respuesta = cliente.get(_url(lista_id, pedido["pedido_id"] + 99))
    otra_lista = cliente.get(_url(lista_id + 99, pedido["pedido_id"]))

    assert respuesta.status_code == 404
    assert respuesta.json()["ok"] is False
    assert otra_lista.status_code == 404


def test_un_pedido_sin_renglones_no_se_exporta_y_se_dice(cliente, almacen, almacenamiento):
    """El pedido que se quedó vacío al volver a partir existe —no hay
    `DELETE`— pero un archivo con solo el encabezado se leería como "no se
    pidió nada", que no es lo que pasó: sus renglones están en otro pedido."""
    lista_id, pedido = _pedido_partido(cliente, almacen, almacenamiento)
    for renglon in almacenamiento.leer_por_id(NEGOCIO, lista_id).renglones:
        cliente.post(f"/api/renglon/{renglon.renglon_id}/descartar")

    respuesta = cliente.get(_url(lista_id, pedido["pedido_id"]))

    assert respuesta.status_code == 409
    assert "renglones" in respuesta.json()["detalle"]


def test_con_la_base_caida_el_error_no_viaja_al_navegador(
    cliente, almacen, almacenamiento
):
    """**Regla 5.** Y no se sirve un archivo a medias: con los precios sin leer,
    cada línea diría "no se le ha consultado", que sería mentira."""
    lista_id, pedido = _pedido_partido(cliente, almacen, almacenamiento)
    almacenamiento.falla = RuntimeError(
        "postgresql://continental:SECRETO@warehouse:5432/farmacia"
    )

    respuesta = cliente.get(_url(lista_id, pedido["pedido_id"]))

    assert respuesta.status_code == 503
    assert "SECRETO" not in respuesta.text
    assert "RuntimeError" in respuesta.json()["detalle"]
    assert "content-disposition" not in respuesta.headers


def test_cada_pedido_trae_su_enlace_hecho_desde_python(cliente, almacen, almacenamiento):
    """La pantalla no arma la URL: la recibe. Y `null` cuando no hay qué
    exportar, que la pantalla usa para no pintar un enlace que daría 409."""
    lista_id, pedido = _pedido_partido(cliente, almacen, almacenamiento)
    assert pedido["csv"] == _url(lista_id, pedido["pedido_id"])

    for renglon in almacenamiento.leer_por_id(NEGOCIO, lista_id).renglones:
        cliente.post(f"/api/renglon/{renglon.renglon_id}/descartar")
    lista = cliente.get(RUTA).json()
    assert lista["pedidos"][0]["csv"] is None


# ==========================================================================
# LA PANTALLA Y EL REPO
# ==========================================================================


def test_la_pantalla_pinta_el_enlace_con_la_url_del_servidor():
    """Un enlace y no un `fetch`: la descarga la hace el navegador con el
    `Content-Disposition`. En otra pestaña, para que un error se lea ahí y no
    tire la pantalla de trabajo — y sin `download`, que haría guardar el JSON
    del error con nombre de CSV."""
    texto = pantalla_completa()
    bloque = texto[texto.index("const enlaceCsv"):]
    bloque = bloque[: bloque.index("\n};") + 3]
    assert "pedido.csv" in bloque, "la URL es la que manda el servidor"
    assert "'/api/" not in bloque, "la pantalla no arma la URL"
    assert "_blank" in bloque and "noopener" in bloque
    assert ".download" not in bloque and "'download'" not in bloque
    # Se pinta en los dos recorridos de `pintarParticion`: el de la partición y
    # el de los pedidos que ya no están en ella —los enviados—. Pintarlo solo
    # en el primero repetiría el error del 21: el pedido enviado, que es el que
    # más interesa respaldar, se quedaría sin enlace.
    assert texto.count("enlaceCsv(") >= 2


def test_gitignore_tapa_el_csv_que_alguien_baje_dentro_del_repo():
    """**Casilla 4, el cinturón.** El servidor no escribe nada, pero una persona
    puede guardar el archivo bajado en la carpeta del repo. Tiene datos de
    compra de la farmacia y no va en git."""
    patrones = [
        l.strip() for l in GITIGNORE.read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.startswith("#")
    ]
    assert "pedido-*.csv" in patrones


# ==========================================================================
# EL ESTADO QUE DICE EL ARCHIVO ES EL CALCULADO (ticket 27, ADR 0015)
#
# La revisión lo cazó: `recibido` y `recibido parcial` del pedido no se
# guardan, se calculan de sus renglones (`recepcion.estado_del_pedido`), y en
# la tabla el pedido que llegó sigue `enviado`. El CSV leía la columna, así que
# un pedido que ya llegó completo se bajaba como `…-enviado.csv` y decía
# "enviado" adentro, mientras la pantalla decía "recibido".
# ==========================================================================


def _enviado_con(*estados: str) -> tuple[PedidoGuardado, list[RenglonGuardado]]:
    """Un pedido enviado con un renglón por cada estado dado."""
    return _pedido(ENVIADO), [
        _renglon(n, clave=f"750100000000{n}", estado=estado)
        for n, estado in enumerate(estados, start=1)
    ]


def _texto_de(pedido, renglones) -> str:
    return ",".join(c for f in _filas(pedido, renglones, {}) for c in f)


def test_un_pedido_que_llego_completo_se_llama_recibido():
    pedido, renglones = _enviado_con(RENGLON_RECIBIDO, RENGLON_RECIBIDO)
    assert (
        nombre_del_archivo(pedido, HOY, renglones)
        == "pedido-2024-03-05-nadro-recibido.csv"
    )


def test_un_pedido_que_llego_de_menos_se_llama_recibido_parcial_con_guion():
    """Con guion y sin espacio: el estado es `recibido parcial`, y un espacio
    en el nombre de un archivo es una comilla que alguien olvida."""
    pedido, renglones = _enviado_con(RENGLON_RECIBIDO, RENGLON_RECIBIDO_PARCIAL)
    assert (
        nombre_del_archivo(pedido, HOY, renglones)
        == "pedido-2024-03-05-nadro-recibido-parcial.csv"
    )


def test_un_pedido_que_llego_completo_lo_dice_adentro_y_no_dice_enviado():
    pedido, renglones = _enviado_con(RENGLON_RECIBIDO, RENGLON_RECIBIDO)
    estado = dict((f[0], f[1]) for f in _filas(pedido, renglones, {}) if len(f) > 1)["Estado"]
    assert estado.startswith("Recibido:"), estado
    assert "llegaron completos" in estado
    assert not estado.startswith("enviado")
    # La firma del envío sigue siendo verdad (ADR 0015) y se conserva.
    assert CORREO in estado
    assert "Continental no se lo mandó a nadie" in estado


def test_un_pedido_que_llego_de_menos_lo_dice_adentro():
    pedido, renglones = _enviado_con(RENGLON_RECIBIDO, RENGLON_RECIBIDO_PARCIAL)
    estado = dict((f[0], f[1]) for f in _filas(pedido, renglones, {}) if len(f) > 1)["Estado"]
    assert estado.startswith("Recibido parcial:"), estado
    assert "1 llegó de menos" in estado
    assert "vuelve a proponerse" in estado


def test_un_pedido_con_algo_en_camino_sigue_siendo_enviado():
    """Lo calculado no inventa: mientras algo venga en camino, es `enviado`."""
    pedido, renglones = _enviado_con(RENGLON_RECIBIDO, RENGLON_EN_TRANSITO)
    assert nombre_del_archivo(pedido, HOY, renglones).endswith("-nadro-enviado.csv")
    assert "Recibido" not in _texto_de(pedido, renglones)


def test_el_archivo_y_la_pantalla_dicen_el_mismo_estado():
    """Una sola fuente: el nombre sale de `estado_del_pedido`, lo mismo que
    `estado_a_la_vista` de la pantalla."""
    from continental.recepcion import estado_del_pedido

    for estados in (
        (RENGLON_RECIBIDO,),
        (RENGLON_RECIBIDO_PARCIAL,),
        (RENGLON_RECIBIDO, RENGLON_CANCELADO),
        (RENGLON_EN_TRANSITO,),
    ):
        pedido, renglones = _enviado_con(*estados)
        calculado = estado_del_pedido(pedido, renglones).replace(" ", "-")
        assert nombre_del_archivo(pedido, HOY, renglones).endswith(f"-nadro-{calculado}.csv")


def _recibir_todo(cliente, almacenamiento, lista_id: int, pedido_id: int, piezas) -> None:
    cliente.post(
        f"/api/pedido/{pedido_id}/enviar",
        headers={"Cf-Access-Authenticated-User-Email": CORREO},
    )
    renglones = [
        r for r in almacenamiento.leer_por_id(NEGOCIO, lista_id).renglones
        if r.pedido_id == pedido_id
    ]
    for renglon, cuantas in zip(renglones, piezas):
        respuesta = cliente.post(
            f"/api/renglon/{renglon.renglon_id}/recepcion/a-mano",
            json={"piezas": cuantas},
            headers={"Cf-Access-Authenticated-User-Email": CORREO},
        )
        assert respuesta.status_code == 200, respuesta.json()


def test_la_ruta_baja_como_recibido_el_pedido_que_llego_completo(
    cliente, almacen, almacenamiento
):
    lista_id, pedido = _pedido_partido(cliente, almacen, almacenamiento)
    _recibir_todo(cliente, almacenamiento, lista_id, pedido["pedido_id"], (3, 3))

    respuesta = cliente.get(_url(lista_id, pedido["pedido_id"]))

    assert respuesta.status_code == 200
    assert "nadro-recibido.csv" in respuesta.headers["content-disposition"]
    assert "enviado.csv" not in respuesta.headers["content-disposition"]
    filas = _leer(respuesta.content)
    estado = next(f[1] for f in filas if f and f[0] == "Estado")
    assert estado.startswith("Recibido:"), estado


def test_la_ruta_baja_como_recibido_parcial_el_pedido_que_llego_de_menos(
    cliente, almacen, almacenamiento
):
    lista_id, pedido = _pedido_partido(cliente, almacen, almacenamiento)
    _recibir_todo(cliente, almacenamiento, lista_id, pedido["pedido_id"], (3, 1))

    respuesta = cliente.get(_url(lista_id, pedido["pedido_id"]))

    assert respuesta.status_code == 200
    assert "nadro-recibido-parcial.csv" in respuesta.headers["content-disposition"]
    filas = _leer(respuesta.content)
    estado = next(f[1] for f in filas if f and f[0] == "Estado")
    assert estado.startswith("Recibido parcial:"), estado
