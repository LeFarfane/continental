"""La comparación de los cuatro: quién gana y cuánto se ahorra (ticket 14).

**Las dos decisiones del ticket son funciones puras** y por eso casi todas las
pruebas de aquí no levantan la aplicación: `comparacion.elegir_ganador` recibe
lecturas congeladas y devuelve quién gana; `comparacion.calcular_ahorro` recibe
esas lecturas, el ganador y las piezas, y devuelve pesos o un motivo por el que
no se puede. Ninguna de las dos abre una conexión, llama a Doyle ni mira el
reloj. Es el mismo patrón que dejó el ticket 13 con `precios.emparejar`.

Las que sí pasan por `TestClient` son las que demuestran que eso llega **hasta
la pantalla**: que el JSON de la lista lo trae, que la cantidad que multiplica
es la que se va a pedir de verdad, y que el HTML sabe pintarlo.

## Las tres trampas que este archivo vigila

1. **El más barato sin existencia no gana.** Y hay una tercera categoría que no
   es ni "lo tiene" ni "no lo tiene": el proveedor que dio precio y **no dijo**
   su existencia. Se trata aparte —nunca se le da la marca de "con
   existencia"— y hay una tabla de casos que lo fija.
2. **El ahorro contra NADRO cuando NADRO no tiene precio no es cero.** Un cero
   ahí diría "no se ahorra nada cambiando de proveedor", que es exactamente lo
   contrario de lo que pasa: no se sabe. Sale `None` con su motivo.
3. **El IVA.** Lo único que se resta aquí son dos precios de **compra**, los
   dos de proveedor y los dos sin IVA. El precio de mostrador —que lleva IVA—
   no entra ni por la puerta de atrás: `calcular_ahorro` no lo recibe, y hay
   una prueba que lo demuestra con un renglón cuyo precio de lista es otro.
"""

from __future__ import annotations

import ast
import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from continental.almacenamiento import PrecioDeProveedor
from continental.comparacion import (
    AHORRO_SIN_CANTIDAD,
    AHORRO_SIN_GANADOR,
    CON_EXISTENCIA,
    EXISTENCIA_SIN_DECIR,
    GANADOR_CON_EXISTENCIA,
    GANADOR_SIN_CONFIRMAR,
    NADIE_CONSULTO,
    NADIE_DIO_PRECIO,
    NINGUNO_LO_TIENE,
    ORDEN_DE_LA_FILA,
    REFERENCIA,
    REFERENCIA_SIN_CONSULTAR,
    REFERENCIA_SIN_PRECIO,
    SIN_CONSULTAR,
    SIN_EXISTENCIA,
    SIN_PRECIO,
    calcular_ahorro,
    comparacion_como_json,
    comparar,
    elegir_ganador,
    estado_del_proveedor,
)
from continental.almacen import LineaDeVenta, Producto
from continental.dobles import respuesta_con_sesion_caducada, respuesta_lista
from continental.doyle import FilaDeProveedor, RespuestaDeProveedor
from continental.precios import NOMBRES_DE_PROVEEDOR, SESION_CADUCADA

RAIZ = Path(__file__).resolve().parent.parent
RUTA = "/api/pedido-sugerido"
HOY = dt.date(2024, 3, 5)
CLAVE = "7501000000001"
INSTANTE = dt.datetime(2024, 3, 5, 10, 0, tzinfo=dt.timezone.utc)
MAS_TARDE = dt.datetime(2024, 3, 5, 18, 30, tzinfo=dt.timezone.utc)


# ------------------------------------------------------------- utilidades


def _lectura(
    proveedor: str,
    precio: str | None = None,
    existencia: str | None = None,
    motivo: str | None = None,
    consultado_en: dt.datetime = INSTANTE,
    existencia_como_llego: str = "",
) -> PrecioDeProveedor:
    """Una lectura congelada, como la que devuelve `precios_del_renglon`.

    `precio` y `existencia` entran como **texto** y se convierten aquí a
    `Decimal`, que es como viajan de verdad: escribirlos como `float` en una
    prueba sería estrenar en el suite justo el tipo que el DDL prohíbe.
    """
    return PrecioDeProveedor(
        renglon_id=1,
        proveedor=proveedor,
        consultado_en=consultado_en,
        precio_como_llego="" if precio is None else precio,
        precio=None if precio is None else Decimal(precio),
        existencia_como_llego=(
            existencia_como_llego
            or ("" if existencia is None else existencia)
        ),
        existencia=None if existencia is None else Decimal(existencia),
        motivo=motivo,
    )


def _venta(fecha: dt.date, producto_id: int, cantidad: float) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=fecha,
        producto_id=producto_id,
        cantidad=cantidad,
        importe=cantidad * 10.0,
        costo=cantidad * 6.0,
        utilidad=cantidad * 4.0,
    )


def _producto(producto_id: int, clave: str, precio_lista: float = 250.0) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=clave,
        descripcion=f"PRODUCTO {producto_id}",
        categoria="MEDICAMENTO",
        departamento="FARMACIA",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=precio_lista,
        costo=30.0,
        existencia=10.0,
        esta_activo=True,
        es_granel=False,
    )


def _poblar(almacen, clave: str = CLAVE, piezas: float = 3) -> None:
    almacen.catalogo_en_memoria = [_producto(1, clave)]
    almacen.ventas_en_memoria = [_venta(HOY, 1, piezas)]


def _los_cuatro(doyle, clave: str = CLAVE) -> None:
    """El caso que el ticket dibuja: uno barato con existencia, uno caro, dos huecos.

    NADRO da $146.38 y tiene 40; LEVIC da $86.05 y tiene 12 —el más barato con
    existencia—; VICMA no contestó nada porque su sesión caducó; QuePharma
    devuelve dos resultados, así que no empareja.
    """
    doyle.resultados_por_termino[clave] = {
        "nadro": respuesta_lista("nadro", [(clave, "146.38", "40")]),
        "levic": respuesta_lista("levic", [(clave, "86.05", "12")]),
        "vicma": respuesta_con_sesion_caducada("vicma"),
        "quepharma": RespuestaDeProveedor(
            proveedor="quepharma",
            estado="listo",
            filas=(
                FilaDeProveedor("A-1", "CAJA 30", "100.00", "", "5"),
                FilaDeProveedor("A-2", "CAJA 60", "180.00", "", "5"),
            ),
            total=2,
        ),
    }


def _primer_renglon(cliente) -> dict:
    return cliente.get(RUTA).json()["renglones"][0]


def _consultar(cliente, renglon_id: int):
    return cliente.post(f"/api/renglon/{renglon_id}/precio")


def _pantalla() -> str:
    return (RAIZ / "src" / "continental" / "web" / "static" / "index.html").read_text(
        encoding="utf-8"
    )


# ====================================================================
# CASILLA 1 — cada renglón muestra el precio de los CUATRO proveedores
# ====================================================================


def test_la_fila_trae_una_casilla_por_cada_uno_de_los_cuatro():
    """Aunque solo dos hayan contestado. Un proveedor que falta no desaparece.

    Es la primera casilla literal: *cada renglón muestra el precio de compra de
    los cuatro proveedores*. Si la fila solo trajera a los que contestaron, un
    renglón con dos huecos se vería idéntico a uno comparado contra dos
    proveedores nada más, y son dos cosas distintas (ticket 15).
    """
    comparacion = comparar(
        [_lectura("nadro", "146.38", "40"), _lectura("levic", "86.05", "12")],
        cantidad=3,
    )

    assert [c.proveedor for c in comparacion.por_proveedor] == list(ORDEN_DE_LA_FILA)
    assert len(comparacion.por_proveedor) == 4


def test_el_orden_de_la_fila_es_fijo_y_empieza_por_la_referencia():
    """Siempre los mismos cuatro en el mismo lugar, con NADRO primero.

    Ordenarlos por precio dejaría a cada renglón con las columnas cambiadas de
    sitio, y entonces comparar dos renglones de la lista —que es lo que el
    encargado hace todo el tiempo— exigiría leer los nombres cada vez. NADRO va
    primero porque es contra quien se mide el ahorro.
    """
    assert ORDEN_DE_LA_FILA[0] == REFERENCIA
    assert set(ORDEN_DE_LA_FILA) == set(NOMBRES_DE_PROVEEDOR)


def test_un_proveedor_del_que_no_hay_lectura_se_dice_sin_consultar():
    """Y no "sin dato": son dos cosas distintas y se arreglan distinto.

    "Sin dato" es un portal que contestó y no dio precio. "Sin consultar" es un
    portal al que no se le preguntó. Confundirlos borra la diferencia entre un
    hueco que ya se intentó y uno que nadie ha intentado.
    """
    comparacion = comparar([_lectura("nadro", "146.38", "40")], cantidad=1)
    casillas = {c.proveedor: c for c in comparacion.por_proveedor}

    assert casillas["levic"].estado == SIN_CONSULTAR
    assert casillas["levic"].es_ganador is False


def test_un_renglon_que_nadie_consulto_no_inventa_cuatro_casillas():
    """Sin una sola lectura no hay fila que pintar, y eso no es un error."""
    comparacion = comparar([], cantidad=3)

    assert comparacion.por_proveedor == ()
    assert comparacion.hay_lecturas is False
    assert comparacion.ganador.motivo == NADIE_CONSULTO


def test_un_quinto_proveedor_no_se_esconde_por_no_estar_en_la_lista():
    """Regla 4 de CLAUDE.md: nada se cae de la pantalla por no reconocerse.

    El día que Doyle estrene un proveedor, su precio se ve igual aunque el mapa
    de nombres de `precios.py` todavía no lo conozca. Va al final, después de
    los cuatro del glosario.
    """
    comparacion = comparar(
        [_lectura("nadro", "146.38", "40"), _lectura("fanasa", "80.00", "5")],
        cantidad=1,
    )

    assert [c.proveedor for c in comparacion.por_proveedor][-1] == "fanasa"
    assert comparacion.ganador.proveedores == ("fanasa",)


def test_la_lista_completa_trae_la_comparacion_de_cada_renglon(
    cliente, almacen, doyle
):
    """De punta a punta: se consulta y el JSON de la lista ya la trae."""
    _poblar(almacen)
    _los_cuatro(doyle)
    _consultar(cliente, _primer_renglon(cliente)["renglon_id"])

    renglon = _primer_renglon(cliente)

    assert renglon["comparacion"]["ganador"]["proveedores"] == ["levic"]
    assert len(renglon["comparacion"]["por_proveedor"]) == 4


# ====================================================================
# CASILLA 2 — el más barato CON EXISTENCIA viene marcado
# ====================================================================


def test_gana_el_mas_barato_cuando_todos_tienen_existencia():
    ganador = elegir_ganador(
        [_lectura("nadro", "146.38", "40"), _lectura("levic", "86.05", "12")]
    )

    assert ganador.proveedores == ("levic",)
    assert ganador.precio == Decimal("86.05")
    assert ganador.certeza == GANADOR_CON_EXISTENCIA


def test_el_mas_barato_sin_existencia_no_gana():
    """La trampa central del ticket: *el más barato no sirve si no lo tiene*.

    LEVIC da $86.05 y reporta **cero** piezas. NADRO da $146.38 y tiene 40. El
    ganador es NADRO, aunque cueste 70% más: comprarle a quien no lo tiene no
    es comprar.
    """
    ganador = elegir_ganador(
        [_lectura("nadro", "146.38", "40"), _lectura("levic", "86.05", "0")]
    )

    assert ganador.proveedores == ("nadro",)
    assert ganador.certeza == GANADOR_CON_EXISTENCIA


def test_un_proveedor_que_dio_precio_y_no_dijo_existencia_no_se_lleva_la_marca():
    """La tercera categoría, y es donde se cuelan los errores.

    "No dijo su existencia" **no** es "no la tiene" —descartarlo escondería al
    proveedor más barato de la fila— y tampoco es "la tiene" —marcarlo como *el
    más barato con existencia* afirmaría algo que ningún portal dijo—. Así que
    no compite con quien sí la confirmó: la marca se la lleva el confirmado, y
    el otro se queda con su precio a la vista y su estado dicho con todas sus
    letras.
    """
    ganador = elegir_ganador(
        [
            _lectura("nadro", "146.38", "40"),
            _lectura("levic", "86.05", existencia=None, existencia_como_llego="Bajo pedido"),
        ]
    )

    assert ganador.proveedores == ("nadro",)
    assert ganador.certeza == GANADOR_CON_EXISTENCIA


def test_si_nadie_confirmo_existencia_gana_el_mas_barato_pero_se_dice_que_no_se_sabe():
    """Y la marca **cambia de palabra**: no se puede decir "con existencia".

    Dejar el renglón sin ganador sería esconder el único dato que hay; llamarlo
    "el más barato con existencia" sería inventarse una confirmación. La salida
    honesta es marcarlo con otra certeza, que la pantalla escribe distinto.
    """
    ganador = elegir_ganador(
        [
            _lectura("nadro", "146.38", existencia=None, existencia_como_llego="Disponible"),
            _lectura("levic", "86.05", existencia=None, existencia_como_llego="SI"),
        ]
    )

    assert ganador.proveedores == ("levic",)
    assert ganador.certeza == GANADOR_SIN_CONFIRMAR
    assert ganador.con_existencia is False


def test_nadie_gana_si_los_unicos_precios_son_de_quien_no_lo_tiene():
    """Dos proveedores con precio y cero piezas: no hay a quién comprarle."""
    ganador = elegir_ganador(
        [_lectura("nadro", "146.38", "0"), _lectura("levic", "86.05", "0")]
    )

    assert ganador.proveedores == ()
    assert ganador.motivo == NINGUNO_LO_TIENE


def test_nadie_gana_si_ninguno_dio_precio():
    ganador = elegir_ganador(
        [
            _lectura("nadro", motivo=SESION_CADUCADA),
            _lectura("levic", motivo=SESION_CADUCADA),
        ]
    )

    assert ganador.proveedores == ()
    assert ganador.motivo == NADIE_DIO_PRECIO


def test_un_empate_marca_a_los_dos_y_no_elige_uno_al_azar():
    """Dos al mismo precio son dos opciones, no una con desempate inventado.

    Elegir uno por orden alfabético diría "éste es el más barato" sobre una
    decisión que el sistema no tomó. Se marcan los dos y la persona elige, que
    es exactamente lo que el ADR 0002 dice que pasa con el mínimo de pedido, los
    días de entrega y el crédito.
    """
    ganador = elegir_ganador(
        [_lectura("nadro", "86.05", "40"), _lectura("levic", "86.05", "12")]
    )

    assert ganador.proveedores == ("levic", "nadro")
    assert ganador.precio == Decimal("86.05")


@pytest.mark.parametrize(
    ("existencia", "esperado"),
    [
        ("40", CON_EXISTENCIA),
        ("0.500", CON_EXISTENCIA),
        ("0", SIN_EXISTENCIA),
        (None, EXISTENCIA_SIN_DECIR),
    ],
)
def test_la_tabla_de_casos_de_la_existencia(existencia, esperado):
    """Las tres categorías, una por una, sobre un proveedor que SÍ dio precio."""
    assert estado_del_proveedor(_lectura("nadro", "86.05", existencia)) == esperado


def test_sin_precio_le_gana_a_cualquier_cosa_que_diga_la_existencia():
    """Un proveedor sin precio no entra a la comparación, tenga o no piezas.

    No es un empate de categorías: si no se sabe a cuánto, la existencia no
    decide nada. La pantalla lo pinta como hueco con su motivo.
    """
    sin_precio = _lectura("nadro", motivo=SESION_CADUCADA)
    assert estado_del_proveedor(sin_precio) == SIN_PRECIO
    assert estado_del_proveedor(None) == SIN_CONSULTAR


def test_el_ganador_viene_marcado_en_su_casilla_y_solo_en_la_suya():
    comparacion = comparar(
        [
            _lectura("nadro", "146.38", "40"),
            _lectura("levic", "86.05", "12"),
            _lectura("vicma", motivo=SESION_CADUCADA),
        ],
        cantidad=3,
    )
    marcados = [c.proveedor for c in comparacion.por_proveedor if c.es_ganador]

    assert marcados == ["levic"]


def test_cada_casilla_dice_cuanto_mas_cara_es_que_la_ganadora():
    """La diferencia por pieza, al lado de cada precio que no ganó.

    Es lo que vuelve legible una fila de cuatro cifras sin hacer la resta de
    cabeza. Un hueco **no** lleva diferencia: restar contra algo que no se sabe
    no da un número (regla 4 de `CLAUDE.md`).
    """
    comparacion = comparar(
        [
            _lectura("nadro", "146.38", "40"),
            _lectura("levic", "86.05", "12"),
            _lectura("vicma", motivo=SESION_CADUCADA),
        ],
        cantidad=3,
    )
    casillas = {c.proveedor: c for c in comparacion.por_proveedor}

    assert casillas["nadro"].diferencia == Decimal("60.33")
    assert casillas["levic"].diferencia is None
    assert casillas["vicma"].diferencia is None


def test_un_proveedor_mas_barato_que_el_ganador_se_dice_con_otras_palabras():
    """El caso que el recorrido del navegador encontró: la pantalla puso `+-60.33`.

    El ganador es el más barato **de los que lo tienen**, así que un proveedor
    con cero piezas puede ser más barato y no haber ganado: su diferencia sale
    negativa. Poner un `+` delante no da una cifra y no dice nada. El signo lo
    decide Python —con su bandera y su magnitud sin signo— y la pantalla solo
    elige la frase: *"60.33 más barato por pieza, pero no lo tiene"*.
    """
    comparacion = comparar(
        [_lectura("nadro", "86.05", "0"), _lectura("levic", "146.38", "12")],
        cantidad=3,
    )
    casillas = {c.proveedor: c for c in comparacion.por_proveedor}

    assert casillas["nadro"].diferencia == Decimal("-60.33")
    assert casillas["nadro"].mas_barato_que_el_ganador is True
    assert casillas["levic"].mas_barato_que_el_ganador is False

    como_json = {c["proveedor"]: c for c in comparacion_como_json(comparacion)["por_proveedor"]}
    assert como_json["nadro"]["diferencia_magnitud"] == "60.33"
    assert como_json["nadro"]["mas_barato_que_el_ganador"] is True


# ====================================================================
# CASILLA 3 — el ahorro contra NADRO, en pesos y por renglón
# ====================================================================


def test_el_ahorro_son_las_piezas_por_la_diferencia():
    """Por renglón y no por pieza: lo que se deja de gastar en esta compra."""
    lecturas = [_lectura("nadro", "146.38", "40"), _lectura("levic", "86.05", "12")]
    ahorro = calcular_ahorro(lecturas, elegir_ganador(lecturas), cantidad=3)

    assert ahorro.por_pieza == Decimal("60.33")
    assert ahorro.cantidad == 3
    assert ahorro.total == Decimal("180.99")
    assert ahorro.es_ahorro is True


def test_cuando_nadro_no_tiene_precio_no_hay_ahorro_y_se_dice_por_que():
    """**La trampa que más duele.** Un cero aquí sería mentira, no prudencia.

    "Ahorro: $0.00" se lee *"da lo mismo a quién comprarle"*. Lo que pasa de
    verdad es que no se sabe cuánto cobra NADRO hoy, así que no hay contra qué
    medir. Sale `None` —nunca un cero— con el motivo de NADRO al lado, que es
    lo que le dice al encargado si puede arreglarlo (la sesión caducada se
    arregla en dos clics).

    Y el renglón **no se esconde**: el ganador sigue marcado y su precio
    sigue a la vista. Lo que falta es la comparación, no la fila.
    """
    lecturas = [
        _lectura("nadro", motivo=SESION_CADUCADA),
        _lectura("levic", "86.05", "12"),
    ]
    ahorro = calcular_ahorro(lecturas, elegir_ganador(lecturas), cantidad=3)

    assert ahorro.total is None
    assert ahorro.por_pieza is None
    assert ahorro.motivo == REFERENCIA_SIN_PRECIO
    assert ahorro.detalle == SESION_CADUCADA
    assert ahorro.es_ahorro is False


def test_cuando_a_nadro_no_se_le_consulto_el_motivo_es_otro():
    """"No contestó" y "no se le preguntó" no se arreglan igual."""
    lecturas = [_lectura("levic", "86.05", "12")]
    ahorro = calcular_ahorro(lecturas, elegir_ganador(lecturas), cantidad=3)

    assert ahorro.total is None
    assert ahorro.motivo == REFERENCIA_SIN_CONSULTAR


def test_si_nadro_gana_el_ahorro_es_cero_de_verdad_y_se_dice_distinto():
    """Éste sí es un cero legítimo, y no se parece en nada al de arriba.

    NADRO es el más barato: cambiar de proveedor no ahorra nada. El cero es el
    resultado de una resta que sí se pudo hacer, y por eso viene con
    `la_referencia_gana` — para que la pantalla escriba "NADRO ya es el más
    barato" en vez de un "$0.00" que se lee como un hueco.
    """
    lecturas = [_lectura("nadro", "86.05", "40"), _lectura("levic", "146.38", "12")]
    ahorro = calcular_ahorro(lecturas, elegir_ganador(lecturas), cantidad=3)

    assert ahorro.total == Decimal("0.00")
    assert ahorro.la_referencia_gana is True
    assert ahorro.es_ahorro is False


def test_comprarle_a_quien_si_lo_tiene_puede_costar_mas_y_eso_no_es_un_ahorro():
    """NADRO barato y agotado, LEVIC caro y con existencia: se paga de más.

    La resta da negativo y **no se le llama ahorro**: se dice que cuesta más.
    Esconderlo o pintarlo como ahorro de cero sería justo la flecha al revés que
    Marlowe ya se equivocó una vez.
    """
    lecturas = [_lectura("nadro", "86.05", "0"), _lectura("levic", "146.38", "12")]
    ahorro = calcular_ahorro(lecturas, elegir_ganador(lecturas), cantidad=3)

    assert ahorro.total == Decimal("-180.99")
    assert ahorro.es_sobrecosto is True
    assert ahorro.es_ahorro is False


def test_un_sobrecosto_viaja_tambien_sin_signo_para_que_la_pantalla_no_reste():
    """"Cuesta $180.99 más" se escribe sin quitarle el menos a una cadena.

    Toda la aritmética vive en Python —incluido un valor absoluto—: el
    JavaScript pinta y no calcula. El signo sigue en `total` y en las banderas,
    que es lo que decide qué frase se escribe.
    """
    como_json = comparacion_como_json(
        comparar(
            [_lectura("nadro", "86.05", "0"), _lectura("levic", "146.38", "12")],
            cantidad=3,
        )
    )

    assert como_json["ahorro"]["total"] == "-180.99"
    assert como_json["ahorro"]["magnitud"] == "180.99"
    assert como_json["ahorro"]["es_sobrecosto"] is True


def test_sin_ganador_no_hay_ahorro_que_calcular():
    lecturas = [_lectura("nadro", "146.38", "0"), _lectura("levic", "86.05", "0")]
    ahorro = calcular_ahorro(lecturas, elegir_ganador(lecturas), cantidad=3)

    assert ahorro.total is None
    assert ahorro.motivo == AHORRO_SIN_GANADOR


def test_sin_cantidad_conocida_se_dice_el_ahorro_por_pieza_y_no_el_total():
    """Pasa si el renglón no se pudo releer. Media respuesta, dicha entera.

    El ahorro por pieza no depende de la cantidad y sigue siendo verdad;
    inventar un total con una cantidad supuesta sí sería mentira.
    """
    lecturas = [_lectura("nadro", "146.38", "40"), _lectura("levic", "86.05", "12")]
    ahorro = calcular_ahorro(lecturas, elegir_ganador(lecturas), cantidad=None)

    assert ahorro.por_pieza == Decimal("60.33")
    assert ahorro.total is None
    assert ahorro.motivo == AHORRO_SIN_CANTIDAD


def test_el_ahorro_se_calcula_en_decimal_y_nunca_en_coma_flotante():
    """Tres piezas a diez centavos de diferencia son treinta centavos exactos.

    En `float`, `0.1 * 3` es `0.30000000000000004`, y el total de un pedido deja
    de cuadrar contra la factura por centavos que nadie puede explicar.
    """
    lecturas = [_lectura("nadro", "10.20", "40"), _lectura("levic", "10.10", "12")]
    ahorro = calcular_ahorro(lecturas, elegir_ganador(lecturas), cantidad=3)

    assert isinstance(ahorro.total, Decimal)
    assert ahorro.total == Decimal("0.30")
    assert str(ahorro.total) == "0.30"


def test_el_ahorro_viaja_al_navegador_como_cadena():
    """Igual que el precio: el JSON de JavaScript solo tiene coma flotante."""
    comparacion = comparar(
        [_lectura("nadro", "146.38", "40"), _lectura("levic", "86.05", "12")],
        cantidad=3,
    )
    como_json = comparacion_como_json(comparacion)

    assert como_json["ahorro"]["total"] == "180.99"
    assert isinstance(como_json["ahorro"]["total"], str)
    assert isinstance(como_json["ganador"]["precio"], str)


def test_el_ahorro_usa_la_cantidad_que_de_verdad_se_va_a_pedir(
    cliente, almacen, doyle
):
    """La regla vive en `RenglonGuardado.cantidad_a_pedir` y no se repite aquí.

    Se venden 3 piezas, alguien corrige a 10, y el ahorro pasa de $180.99 a
    $603.30. Si la comparación multiplicara por `cantidad_propuesta`, el
    encargado vería un ahorro que no corresponde a la compra que está por hacer.
    """
    _poblar(almacen, piezas=3)
    _los_cuatro(doyle)
    renglon_id = _primer_renglon(cliente)["renglon_id"]
    _consultar(cliente, renglon_id)

    antes = _primer_renglon(cliente)
    assert antes["cantidad_a_pedir"] == 3
    assert antes["comparacion"]["ahorro"]["total"] == "180.99"

    cliente.post(f"/api/renglon/{renglon_id}/cantidad", json={"cantidad": 10})
    despues = _primer_renglon(cliente)

    assert despues["cantidad_a_pedir"] == 10
    assert despues["comparacion"]["ahorro"]["total"] == "603.30"


# ====================================================================
# LA TRAMPA DEL IVA — solo se restan cifras de la misma naturaleza
# ====================================================================


def test_el_ahorro_solo_resta_precios_de_compra_y_nunca_el_de_mostrador(
    cliente, almacen, doyle
):
    """El costo nuestro es sin IVA y el de mostrador con IVA (`CLAUDE.md`).

    Aquí lo único que se resta son **dos precios de proveedor**: los dos son
    precio de compra y los dos vienen sin IVA, así que la resta significa algo.
    El `precio_lista_sin_iva` del catálogo —que es otra naturaleza y además
    lleva IVA al mostrador— no toca este número: se pone en 999.99 y el ahorro
    sigue valiendo exactamente lo mismo.
    """
    almacen.catalogo_en_memoria = [_producto(1, CLAVE, precio_lista=999.99)]
    almacen.ventas_en_memoria = [_venta(HOY, 1, 3)]
    _los_cuatro(doyle)
    _consultar(cliente, _primer_renglon(cliente)["renglon_id"])

    assert _primer_renglon(cliente)["comparacion"]["ahorro"]["total"] == "180.99"


def test_la_comparacion_no_puede_ni_recibir_el_precio_de_mostrador():
    """La garantía no es una convención: no hay por dónde colarlo.

    `elegir_ganador` y `calcular_ahorro` reciben lecturas de proveedor y un
    entero de piezas, y nada más. No ven el renglón, así que no pueden mirar su
    `precio_lista_sin_iva` ni el costo de SICAR aunque alguien quisiera.
    """
    import inspect

    assert list(inspect.signature(elegir_ganador).parameters) == ["lecturas"]
    assert list(inspect.signature(calcular_ahorro).parameters) == [
        "lecturas",
        "ganador",
        "cantidad",
    ]


def test_el_modulo_de_comparacion_es_puro():
    """Ni red, ni reloj, ni base: las mismas garantías que `precios.py`.

    Se mira el árbol y no el texto: un `import` dentro de una función también
    cuenta, y un comentario que mencione `requests` no.
    """
    arbol = ast.parse(
        (RAIZ / "src" / "continental" / "comparacion.py").read_text(encoding="utf-8")
    )
    importados = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            importados.update(alias.name.split(".")[0] for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            importados.add(nodo.module.split(".")[0])

    prohibidos = {
        "time",
        "socket",
        "requests",
        "httpx",
        "urllib",
        "sqlalchemy",
        "psycopg2",
        "playwright",
    }
    assert not (importados & prohibidos)


# ====================================================================
# CASILLA 4 — la existencia que reporta cada proveedor, a la vista
# ====================================================================


def test_cada_casilla_lleva_la_existencia_tal_como_la_dijo_el_proveedor():
    """El texto original y no solo el número: "+100" dice más que "100"."""
    comparacion = comparar(
        [_lectura("nadro", "146.38", "100", existencia_como_llego="+100")],
        cantidad=1,
    )
    casillas = {c.proveedor: c for c in comparacion.por_proveedor}

    assert casillas["nadro"].existencia_como_llego == "+100"
    assert casillas["nadro"].estado == CON_EXISTENCIA


def test_una_existencia_dicha_con_palabras_no_se_convierte_en_un_numero():
    """"Bajo pedido" se conserva tal cual y el estado dice que no se sabe."""
    comparacion = comparar(
        [
            _lectura(
                "nadro", "146.38", existencia=None, existencia_como_llego="Bajo pedido"
            )
        ],
        cantidad=1,
    )
    casillas = {c.proveedor: c for c in comparacion.por_proveedor}

    assert casillas["nadro"].estado == EXISTENCIA_SIN_DECIR
    assert casillas["nadro"].existencia_como_llego == "Bajo pedido"


def test_el_cero_de_existencia_se_ve_como_agotado_y_no_como_sin_dato():
    comparacion = comparar([_lectura("nadro", "146.38", "0")], cantidad=1)
    casillas = {c.proveedor: c for c in comparacion.por_proveedor}

    assert casillas["nadro"].estado == SIN_EXISTENCIA


def test_la_existencia_llega_al_navegador_dentro_de_la_comparacion():
    como_json = comparacion_como_json(
        comparar([_lectura("nadro", "146.38", "40")], cantidad=1)
    )
    casilla = como_json["por_proveedor"][0]

    assert casilla["estado"] == CON_EXISTENCIA
    assert casilla["existencia_como_llego"] == "40"
    assert casilla["nombre"] == "NADRO"


# ====================================================================
# CASILLA 5 — sin dato se ve distinto de caro, de un vistazo
# ====================================================================


def test_un_hueco_no_tiene_precio_ni_diferencia_ni_puede_ganar():
    """Nunca cero, nunca vacío, nunca "el más caro" (regla 4 de CLAUDE.md)."""
    comparacion = comparar(
        [
            _lectura("nadro", "146.38", "40"),
            _lectura("vicma", motivo=SESION_CADUCADA),
        ],
        cantidad=3,
    )
    casillas = {c.proveedor: c for c in comparacion.por_proveedor}

    assert casillas["vicma"].estado == SIN_PRECIO
    assert casillas["vicma"].diferencia is None
    assert casillas["vicma"].es_ganador is False
    assert comparacion.ganador.proveedores == ("nadro",)


def test_un_hueco_no_cuenta_como_proveedor_comparado():
    comparacion = comparar(
        [
            _lectura("nadro", "146.38", "40"),
            _lectura("levic", "86.05", "12"),
            _lectura("vicma", motivo=SESION_CADUCADA),
        ],
        cantidad=3,
    )

    assert comparacion.con_precio == 2
    assert comparacion.consultados == 3


def test_la_pantalla_pinta_los_tres_estados_con_clases_distintas():
    """Ganador, caro y sin dato: tres aspectos, no tres tonos del mismo gris.

    Se comprueba sobre el HTML porque es el único archivo que ninguna prueba de
    comportamiento mira, y es justo donde vive esta casilla.
    """
    pantalla = _pantalla()

    for clase in (".precio.gana", ".precio .sindato", ".precio .caro"):
        assert clase in pantalla


def test_la_marca_del_ganador_no_depende_solo_del_color():
    """Un verde más oscuro no es una marca para quien no distingue verdes.

    La casilla ganadora lleva **una palabra** además del color, y eso es lo que
    la hace legible en una pantalla de mostrador con reflejo.
    """
    pantalla = _pantalla()

    assert "el más barato" in pantalla
    assert "aria-label" in pantalla


# ====================================================================
# CASILLA 6 — el precio congelado del renglón, con su fecha visible
# ====================================================================


def test_la_comparacion_dice_cuando_se_leyo_lo_que_compara():
    comparacion = comparar(
        [_lectura("nadro", "146.38", "40"), _lectura("levic", "86.05", "12")],
        cantidad=3,
    )

    assert comparacion.leido_en == INSTANTE
    assert comparacion.instantes_distintos is False


def test_con_lecturas_de_dos_momentos_se_dice_la_mas_reciente_y_que_no_coinciden():
    """Pasa en cuanto alguien vuelve a consultar y solo dos proveedores contestan.

    Enseñar una sola fecha como si las cuatro fueran de ahí sería decir que una
    lectura de hace tres semanas es de hoy. Se enseña la más reciente **y** se
    avisa que hay de varias.
    """
    comparacion = comparar(
        [
            _lectura("nadro", "146.38", "40", consultado_en=INSTANTE),
            _lectura("levic", "86.05", "12", consultado_en=MAS_TARDE),
        ],
        cantidad=3,
    )

    assert comparacion.leido_en == MAS_TARDE
    assert comparacion.instantes_distintos is True


def test_la_fecha_viaja_en_iso_con_zona():
    """Sin zona el navegador la leería como hora local y el contenedor va en UTC."""
    como_json = comparacion_como_json(
        comparar([_lectura("nadro", "146.38", "40")], cantidad=1)
    )

    assert como_json["leido_en"] == INSTANTE.isoformat()
    assert como_json["leido_en"].endswith("+00:00")


def test_la_comparacion_sale_de_lo_guardado_y_no_vuelve_a_preguntarle_a_doyle(
    cliente, almacen, doyle
):
    """Se consulta una vez; recargar la lista compara sin molestar a un portal.

    Es la sexta casilla entera: *la comparación usa el precio congelado del
    renglón*. Si volviera a preguntar, cada carga de la página costaría cuatro
    visitas a los portales con las credenciales del dueño.
    """
    _poblar(almacen)
    _los_cuatro(doyle)
    _consultar(cliente, _primer_renglon(cliente)["renglon_id"])
    busquedas = len(doyle.pedidos)

    for _ in range(3):
        renglon = _primer_renglon(cliente)

    assert len(doyle.pedidos) == busquedas
    assert renglon["comparacion"]["ganador"]["proveedores"] == ["levic"]


def test_la_pantalla_dice_cuando_se_leyo_el_precio_que_compara():
    assert "leído el " in _pantalla()


# ====================================================================
# LA RUTA — la comparación llega por los tres caminos que la pintan
# ====================================================================


def test_la_ruta_de_consultar_devuelve_la_comparacion_ya_hecha(
    cliente, almacen, doyle
):
    """Para que el navegador no tenga que calcular nada al volver el botón."""
    _poblar(almacen)
    _los_cuatro(doyle)
    respuesta = _consultar(cliente, _primer_renglon(cliente)["renglon_id"]).json()

    assert respuesta["comparacion"]["ganador"]["proveedores"] == ["levic"]
    assert respuesta["comparacion"]["ahorro"]["total"] == "180.99"


def test_la_ruta_de_sondeo_devuelve_la_comparacion(cliente, almacen, doyle):
    _poblar(almacen)
    _los_cuatro(doyle)
    renglon_id = _primer_renglon(cliente)["renglon_id"]
    _consultar(cliente, renglon_id)

    respuesta = cliente.get(f"/api/renglon/{renglon_id}/precio").json()

    assert respuesta["comparacion"]["ganador"]["proveedores"] == ["levic"]
    assert respuesta["comparacion"]["ahorro"]["total"] == "180.99"


def test_un_renglon_sin_consultar_trae_una_comparacion_vacia_y_no_un_nulo(
    cliente, almacen
):
    """`null` obligaría al JavaScript a comprobarlo antes de cada campo."""
    _poblar(almacen)
    renglon = _primer_renglon(cliente)

    assert renglon["comparacion"]["hay_lecturas"] is False
    assert renglon["comparacion"]["ganador"]["proveedores"] == []


def test_descartar_un_renglon_no_le_borra_la_comparacion(cliente, almacen, doyle):
    """El precio al que se decidió sigue ahí aunque el renglón salga de la lista."""
    _poblar(almacen)
    _los_cuatro(doyle)
    renglon_id = _primer_renglon(cliente)["renglon_id"]
    _consultar(cliente, renglon_id)

    respuesta = cliente.post(f"/api/renglon/{renglon_id}/descartar").json()

    assert respuesta["renglon"]["comparacion"]["ganador"]["proveedores"] == ["levic"]


def test_el_detalle_de_una_falla_al_releer_el_renglon_no_viaja_al_navegador(
    cliente, almacen, doyle, almacenamiento
):
    """Regla 5: un `str(exc)` lleva la cadena de conexión con contraseña.

    Si el renglón no se puede releer, el sondeo sigue contestando —con los
    precios congelados y sin el total del ahorro— y nada del error sale.
    """
    _poblar(almacen)
    _los_cuatro(doyle)
    renglon_id = _primer_renglon(cliente)["renglon_id"]
    _consultar(cliente, renglon_id)

    def _truena(negocio, identificador):
        raise RuntimeError("postgresql://continental:CONTRASEÑA@atlas/farmacia")

    almacenamiento.leer_renglon = _truena
    respuesta = cliente.get(f"/api/renglon/{renglon_id}/precio")

    assert respuesta.status_code == 200
    assert "CONTRASEÑA" not in respuesta.text
    assert respuesta.json()["comparacion"]["ahorro"]["motivo"] == AHORRO_SIN_CANTIDAD
