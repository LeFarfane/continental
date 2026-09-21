"""Los huecos, visibles y contados (ticket 15).

La frase que define el ticket es una sola: **que nadie lea la lista como si
estuviera completa**. No se está agregando un contador decorativo; se está
impidiendo que alguien decida una compra creyendo que vio cuatro precios cuando
vio uno.

De ahí salen las tres cosas que este archivo vigila, y las tres son del mismo
tipo: *no afirmar lo que no se comprobó*.

1. **Un renglón con una sola lectura no es "el más barato".** El superlativo
   afirma algo sobre otros tres precios —que se miraron y que costaban más— y
   con una sola cotización eso no se miró. La certeza dice "el único que
   contestó", y la dice `comparacion.py`, no el JavaScript: hasta el ticket 14
   esa frase se elegía en la pantalla, que es el único archivo que ninguna
   prueba de Python mira, y por eso el caso salía mal sin que nada se pusiera
   rojo.
2. **"Sin comparar" son tres cosas y se cuentan aparte.** Nadie lo consultó, se
   consultó y ninguno dio precio, y hay un solo precio. Los tres son "sin
   comparar" —de ninguno salió una cifra puesta al lado de otra— y el encargado
   los arregla de tres maneras distintas, que es la única razón por la que un
   conteo se desglosa.
3. **Cada hueco dice su motivo con palabras de persona.** El motivo corto es lo
   que se guarda y lo que se cuenta; el largo es lo que se lee. Son dos cadenas
   y no una porque tienen dos trabajos: uno no puede cambiar sin una migración
   y el otro se reescribe cuantas veces haga falta.

Casi todo se prueba **sin levantar la aplicación**: `contar_la_lista` y
`elegir_ganador` reciben datos congelados y devuelven otros. Las que pasan por
`TestClient` son las que demuestran que eso llega hasta el JSON de la lista, y
las que leen `index.html` son las que demuestran que la pantalla lo escribe en
vez de inventárselo.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from conftest import pantalla_completa
from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import PrecioDeProveedor
from continental.comparacion import (
    CERTEZAS_CON_EXISTENCIA,
    CERTEZAS_DE_UN_SOLO_PRECIO,
    GANADOR_CON_EXISTENCIA,
    GANADOR_SIN_CONFIRMAR,
    GANADOR_UNICO,
    GANADOR_UNICO_SIN_CONFIRMAR,
    MINIMO_PARA_COMPARAR,
    MOTIVOS_DE_SIN_COMPARAR,
    NINGUN_PRECIO,
    SIN_CONSULTAR_EL_RENGLON,
    UN_SOLO_PRECIO,
    comparacion_como_json,
    comparar,
    contar_la_lista,
    conteo_como_json,
    elegir_ganador,
)
from continental.dobles import (
    respuesta_con_error,
    respuesta_con_sesion_caducada,
    respuesta_lista,
)
from continental.doyle import FilaDeProveedor, RespuestaDeProveedor
from continental.precios import (
    EXPLICACION_DEL_MOTIVO,
    MOTIVOS,
    NO_EMPAREJA,
    PORTAL_SIN_CONTESTAR,
    SESION_CADUCADA,
    SIN_RESULTADOS,
    VARIOS_RESULTADOS,
    explicacion_del_motivo,
)

RAIZ = Path(__file__).resolve().parent.parent
RUTA = "/api/pedido-sugerido"
HOY = dt.date(2024, 3, 5)
INSTANTE = dt.datetime(2024, 3, 5, 10, 0, tzinfo=dt.timezone.utc)

#: Una clave por renglón, para poder prepararle a cada uno su propia respuesta
#: de Doyle: `DoyleFalso` indexa por el término que se busca, que es el EAN.
SIN_CONSULTAR_CLAVE = "7501000000001"
SIN_PRECIOS_CLAVE = "7501000000002"
UN_PRECIO_CLAVE = "7501000000003"
COMPLETO_CLAVE = "7501000000004"


# ------------------------------------------------------------- utilidades


def _lectura(
    proveedor: str,
    precio: str | None = None,
    existencia: str | None = None,
    motivo: str | None = None,
) -> PrecioDeProveedor:
    """Una lectura congelada, como la que devuelve `precios_del_renglon`."""
    return PrecioDeProveedor(
        renglon_id=1,
        proveedor=proveedor,
        consultado_en=INSTANTE,
        precio_como_llego="" if precio is None else precio,
        precio=None if precio is None else Decimal(precio),
        existencia_como_llego="" if existencia is None else existencia,
        existencia=None if existencia is None else Decimal(existencia),
        motivo=motivo,
    )


def _venta(producto_id: int, cantidad: float) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=HOY,
        producto_id=producto_id,
        cantidad=cantidad,
        importe=cantidad * 10.0,
        costo=cantidad * 6.0,
        utilidad=cantidad * 4.0,
    )


def _producto(producto_id: int, clave: str) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=clave,
        descripcion=f"PRODUCTO {producto_id}",
        categoria="MEDICAMENTO",
        departamento="FARMACIA",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=250.0,
        costo=30.0,
        existencia=10.0,
        esta_activo=True,
        es_granel=False,
    )


#: Las cuatro claves con su producto, en el orden en que se siembran.
_CLAVES = (
    SIN_CONSULTAR_CLAVE,
    SIN_PRECIOS_CLAVE,
    UN_PRECIO_CLAVE,
    COMPLETO_CLAVE,
)


def _poblar_los_cuatro_casos(almacen, doyle) -> None:
    """Los cuatro casos feos del ticket, sembrados a propósito en una lista.

    Uno que nadie consultó, uno consultado con los cuatro proveedores en hueco,
    uno con un solo proveedor que contestó, y uno completo. Son exactamente los
    cuatro renglones que el conteo de arriba tiene que saber distinguir, y los
    cuatro que la pantalla tiene que escribir distinto.
    """
    almacen.catalogo_en_memoria = [
        _producto(i + 1, clave) for i, clave in enumerate(_CLAVES)
    ]
    almacen.ventas_en_memoria = [_venta(i + 1, 3) for i in range(len(_CLAVES))]

    # Los cuatro en hueco, y cada uno por un motivo distinto: es de paso la
    # demostración de la segunda casilla.
    doyle.resultados_por_termino[SIN_PRECIOS_CLAVE] = {
        # Buscó y no encontró nada: no está en ese catálogo.
        "nadro": respuesta_lista("nadro", []),
        # El EAN dio varios resultados y ninguno se puede elegir sin adivinar.
        "levic": RespuestaDeProveedor(
            proveedor="levic",
            estado="listo",
            filas=(
                FilaDeProveedor(SIN_PRECIOS_CLAVE, "CAJA 30", "100.00", "", "5"),
                FilaDeProveedor(SIN_PRECIOS_CLAVE, "CAJA 60", "180.00", "", "5"),
            ),
            total=2,
        ),
        # El portal no contestó.
        "vicma": respuesta_con_error("vicma", "se cayó la conexión"),
        # La sesión caducó.
        "quepharma": respuesta_con_sesion_caducada("quepharma"),
    }

    # Un solo proveedor con precio: los otros tres, huecos.
    doyle.resultados_por_termino[UN_PRECIO_CLAVE] = {
        "nadro": respuesta_lista("nadro", [(UN_PRECIO_CLAVE, "86.05", "40")]),
        "levic": respuesta_con_sesion_caducada("levic"),
        "vicma": respuesta_con_sesion_caducada("vicma"),
        "quepharma": respuesta_con_sesion_caducada("quepharma"),
    }

    # Los cuatro con precio: el único renglón comparado de la lista.
    doyle.resultados_por_termino[COMPLETO_CLAVE] = {
        "nadro": respuesta_lista("nadro", [(COMPLETO_CLAVE, "146.38", "40")]),
        "levic": respuesta_lista("levic", [(COMPLETO_CLAVE, "86.05", "12")]),
        "vicma": respuesta_lista("vicma", [(COMPLETO_CLAVE, "99.00", "3")]),
        "quepharma": respuesta_lista("quepharma", [(COMPLETO_CLAVE, "120.00", "0")]),
    }


def _por_clave(cliente) -> dict[str, dict]:
    return {r["clave"]: r for r in cliente.get(RUTA).json()["renglones"]}


def _consultar_los_tres(cliente) -> None:
    """Se consultan tres de los cuatro. El primero se queda sin consultar."""
    renglones = _por_clave(cliente)
    for clave in (SIN_PRECIOS_CLAVE, UN_PRECIO_CLAVE, COMPLETO_CLAVE):
        cliente.post(f"/api/renglon/{renglones[clave]['renglon_id']}/precio")


def _pantalla() -> str:
    return pantalla_completa()


# ====================================================================
# CASILLA 3 — un renglón contra UN solo proveedor no es "el más barato"
#
# La casilla que es el corazón del ticket, y la que el 14 dejó incumplida a
# propósito: un renglón con una sola lectura salía marcado "el más barato con
# existencia".
# ====================================================================


def test_un_solo_precio_no_se_presenta_como_el_mas_barato():
    """La casilla, literal. Un proveedor, con precio y con existencia.

    Nada de lo que se sabe cambia —ese proveedor lo tiene y cuesta eso— y lo
    que cambia es lo que se **afirma**: "el más barato" dice algo de otros tres
    precios que nadie vio.
    """
    ganador = elegir_ganador([_lectura("nadro", "86.05", "40")])

    assert ganador.proveedores == ("nadro",)
    assert ganador.precio == Decimal("86.05")
    assert ganador.certeza == GANADOR_UNICO
    assert ganador.es_unico is True
    assert "más barato" not in ganador.certeza


def test_el_unico_que_contesto_y_no_dijo_existencia_lo_dice_tambien():
    """Dos cosas faltan y se dicen las dos: es el caso peor informado de todos.

    Colapsarlo en "el único que contestó" callaría justo la advertencia de que
    nadie confirmó tener el producto, y la callaría en el renglón donde más
    falta hace.
    """
    ganador = elegir_ganador([_lectura("levic", "86.05", existencia=None)])

    assert ganador.certeza == GANADOR_UNICO_SIN_CONFIRMAR
    assert ganador.es_unico is True
    assert ganador.con_existencia is False


def test_tres_huecos_y_un_precio_siguen_siendo_un_solo_precio():
    """Lo que cuenta son los PRECIOS, no a cuántos se les preguntó.

    Es el caso real de hoy: las cuatro sesiones de Doyle caducadas y una sola
    que alguien alcanzó a abrir. Se consultó a cuatro y se comparó contra uno.
    """
    ganador = elegir_ganador(
        [
            _lectura("nadro", "86.05", "40"),
            _lectura("levic", motivo=SESION_CADUCADA),
            _lectura("vicma", motivo=PORTAL_SIN_CONTESTAR),
            _lectura("quepharma", motivo=SIN_RESULTADOS),
        ]
    )

    assert ganador.certeza == GANADOR_UNICO
    assert ganador.es_unico is True


def test_con_dos_precios_vuelve_a_ser_el_mas_barato():
    """El corte es dos, y con dos ya hay una comparación de verdad."""
    ganador = elegir_ganador(
        [_lectura("nadro", "146.38", "40"), _lectura("levic", "86.05", "12")]
    )

    assert ganador.certeza == GANADOR_CON_EXISTENCIA
    assert ganador.es_unico is False
    assert MINIMO_PARA_COMPARAR == 2


def test_dos_precios_con_uno_agotado_siguen_siendo_una_comparacion():
    """La trampa fina: "único" se mide sobre los PRECIOS, no sobre los elegibles.

    NADRO da $146.38 y tiene 40; LEVIC da $86.05 y tiene cero. Solo uno podía
    ganar, pero se vieron **dos** cifras y la de LEVIC está a la vista en la
    fila. Decir "el único que contestó" sobre un renglón con dos precios
    escritos se leería como un error de la pantalla.
    """
    ganador = elegir_ganador(
        [_lectura("nadro", "146.38", "40"), _lectura("levic", "86.05", "0")]
    )

    assert ganador.proveedores == ("nadro",)
    assert ganador.certeza == GANADOR_CON_EXISTENCIA
    assert ganador.es_unico is False


def test_dos_precios_y_nadie_confirmo_no_es_el_caso_del_unico():
    """Las dos preguntas son ejes distintos y no se confunden entre sí."""
    ganador = elegir_ganador(
        [
            _lectura("nadro", "146.38", existencia=None),
            _lectura("levic", "86.05", existencia=None),
        ]
    )

    assert ganador.certeza == GANADOR_SIN_CONFIRMAR
    assert ganador.es_unico is False
    assert ganador.con_existencia is False


@pytest.mark.parametrize("certeza", CERTEZAS_DE_UN_SOLO_PRECIO)
def test_ninguna_certeza_de_un_solo_precio_dice_el_mas_barato(certeza: str):
    """Ninguna de las dos puede traer el superlativo, hoy ni cuando se reescriban.

    Es la casilla convertida en una regla sobre las propias cadenas: da igual
    cómo se redacten después, no pueden afirmar que sea el más barato de nada.
    Y las dos dicen "el único", que es la frase del ticket.
    """
    assert "más barato" not in certeza
    assert "único" in certeza


def test_las_certezas_con_existencia_son_las_que_un_portal_confirmo():
    """`con_existencia` es un eje y `es_unico` es el otro; se cruzan los cuatro."""
    assert set(CERTEZAS_CON_EXISTENCIA) == {GANADOR_CON_EXISTENCIA, GANADOR_UNICO}
    assert elegir_ganador([_lectura("nadro", "86.05", "40")]).con_existencia is True


def test_el_json_del_renglon_lleva_la_frase_hecha_y_los_dos_ejes():
    """La pantalla no tiene que deducir nada: recibe la frase y las banderas."""
    json = comparacion_como_json(comparar([_lectura("nadro", "86.05", "40")], 3))

    assert json["ganador"]["certeza"] == GANADOR_UNICO
    assert json["ganador"]["es_unico"] is True
    assert json["ganador"]["con_existencia"] is True
    assert json["se_comparo"] is False
    assert json["por_que_no_se_comparo"] == UN_SOLO_PRECIO


def test_la_lista_marca_el_renglon_de_un_solo_proveedor_como_el_unico(
    cliente, almacen, doyle
):
    """De punta a punta: tres sesiones caducadas y NADRO con precio."""
    _poblar_los_cuatro_casos(almacen, doyle)
    _consultar_los_tres(cliente)

    renglon = _por_clave(cliente)[UN_PRECIO_CLAVE]
    ganador = renglon["comparacion"]["ganador"]

    assert ganador["proveedores"] == ["nadro"]
    assert ganador["certeza"] == GANADOR_UNICO
    assert ganador["es_unico"] is True
    assert renglon["comparacion"]["se_comparo"] is False


def test_la_pantalla_escribe_la_certeza_del_servidor_y_no_una_cadena_suya():
    """La regresión del ticket 14, fijada donde se rompió.

    La marca del ganador se escribía eligiendo entre dos literales del
    JavaScript según una bandera, y por eso el renglón de un solo proveedor
    salía rotulado "el más barato con existencia". Ahora la frase llega hecha.
    Lo que se comprueba es lo mismo por los dos lados: que la pantalla use
    `ganador.certeza`, y que **no quede en el archivo** ninguno de los dos
    literales viejos.
    """
    portada = _pantalla()

    assert "comparacion.ganador.certeza" in portada
    assert "'✔ el más barato con existencia'" not in portada
    assert "'✔ el más barato, nadie confirmó existencia'" not in portada


# ====================================================================
# CASILLA 1 — cuántos renglones quedaron sin comparar, y contra cuántos
#             proveedores se comparó cada uno
# ====================================================================


def _cuatro_comparaciones() -> list:
    """Los cuatro casos del ticket, en comparaciones puras y sin almacén."""
    return [
        # Nadie lo consultó.
        comparar([], 3),
        # Se consultó y ninguno dio precio, cada uno por su motivo.
        comparar(
            [
                _lectura("nadro", motivo=SIN_RESULTADOS),
                _lectura("levic", motivo=VARIOS_RESULTADOS),
                _lectura("vicma", motivo=PORTAL_SIN_CONTESTAR),
                _lectura("quepharma", motivo=SESION_CADUCADA),
            ],
            3,
        ),
        # Un solo precio.
        comparar([_lectura("nadro", "86.05", "40")], 3),
        # Comparado de verdad.
        comparar(
            [_lectura("nadro", "146.38", "40"), _lectura("levic", "86.05", "12")],
            3,
        ),
    ]


def test_el_conteo_parte_la_lista_en_comparados_y_sin_comparar():
    """El número de arriba, con los cuatro casos feos sembrados."""
    conteo = contar_la_lista(_cuatro_comparaciones())

    assert conteo.renglones == 4
    assert conteo.comparados == 1
    assert conteo.sin_comparar == 3


def test_el_desglose_distingue_las_tres_maneras_de_no_haber_comparado():
    """Tres números y no uno, porque el encargado los arregla distinto.

    El que nadie consultó se arregla con un botón. El que se consultó y no dio
    un solo precio se arregla —o no— mirando el motivo de cada hueco. El de un
    solo precio no se arregla: es una advertencia, no un hueco.
    """
    conteo = contar_la_lista(_cuatro_comparaciones())

    assert conteo.sin_consultar == 1
    assert conteo.sin_un_solo_precio == 1
    assert conteo.con_un_solo_precio == 1


def test_el_desglose_suma_exactamente_el_total():
    """Un conteo que no cuadra consigo mismo es peor que no tenerlo.

    Se comprueba sobre los cuatro casos y también sobre la lista vacía: un
    total que se calculara aparte se separaría del desglose el día que alguien
    agregue un cuarto caso y se olvide de sumarlo.
    """
    for comparaciones in ([], _cuatro_comparaciones()):
        conteo = contar_la_lista(comparaciones)
        assert conteo.sin_comparar == (
            conteo.sin_consultar
            + conteo.sin_un_solo_precio
            + conteo.con_un_solo_precio
        )
        assert conteo.renglones == conteo.comparados + conteo.sin_comparar


def test_el_que_nadie_consulto_y_el_que_se_consulto_sin_precios_van_aparte():
    """Son dos cosas y se arreglan en dos lugares: el botón y el portal.

    Contarlos juntos diría "doce sin comparar" sin decir que de once nadie sabe
    nada y de uno ya se sabe que no se pudo.
    """
    nadie = contar_la_lista([comparar([], 3)])
    fallaron = contar_la_lista(
        [comparar([_lectura("nadro", motivo=SESION_CADUCADA)], 3)]
    )

    assert (nadie.sin_consultar, nadie.sin_un_solo_precio) == (1, 0)
    assert (fallaron.sin_consultar, fallaron.sin_un_solo_precio) == (0, 1)


def test_un_renglon_con_un_solo_precio_cuenta_como_sin_comparar():
    """Tiene dato y aun así no está comparado: no hay contra qué medirlo.

    Es la decisión del ticket puesta en el conteo. Contarlo como comparado
    metería en el número de "ya está" justo los renglones donde una decisión de
    compra se tomaría sobre una sola cotización.
    """
    conteo = contar_la_lista([comparar([_lectura("nadro", "86.05", "40")], 3)])

    assert conteo.comparados == 0
    assert conteo.con_un_solo_precio == 1
    assert conteo.hay_sin_comparar is True


def test_una_lista_sin_renglones_no_inventa_huecos():
    """Cero renglones es cero huecos, y la pantalla no escribe nada."""
    conteo = contar_la_lista([])

    assert conteo.renglones == 0
    assert conteo.sin_comparar == 0
    assert conteo.hay_sin_comparar is False


def test_una_lista_entera_comparada_lo_dice_en_vez_de_callar():
    """Callar dejaría el silencio con dos significados y no se distinguen.

    "Ya está todo comparado" y "esta pantalla no lo cuenta" se ven iguales si no
    se escribe nada, y el segundo es exactamente lo que este ticket existe para
    evitar.
    """
    conteo = contar_la_lista(_cuatro_comparaciones()[-1:])

    assert conteo.hay_sin_comparar is False
    assert conteo.comparados == 1


@pytest.mark.parametrize(
    "comparacion, esperado",
    [
        (comparar([], 3), SIN_CONSULTAR_EL_RENGLON),
        (comparar([_lectura("nadro", motivo=SIN_RESULTADOS)], 3), NINGUN_PRECIO),
        (comparar([_lectura("nadro", "86.05", "40")], 3), UN_SOLO_PRECIO),
        (
            comparar(
                [_lectura("nadro", "146.38", "40"), _lectura("levic", "86.05", "12")],
                3,
            ),
            None,
        ),
    ],
)
def test_cada_renglon_sabe_por_que_no_se_comparo(comparacion, esperado):
    """La clasificación vive en el renglón y el conteo solo la suma."""
    assert comparacion.por_que_no_se_comparo == esperado
    assert comparacion.se_comparo is (esperado is None)


def test_los_tres_motivos_de_sin_comparar_son_distintos_entre_si():
    """Si dos se atendieran igual, sobraría uno."""
    assert len(set(MOTIVOS_DE_SIN_COMPARAR)) == 3


def test_cada_renglon_dice_contra_cuantos_proveedores_se_comparo():
    """El otro número de la casilla, que es de renglón y no de lista.

    Dos cifras y no una: a cuántos se les preguntó y cuántos contestaron con un
    precio. "Se preguntó a cuatro y contestaron dos" no es "se preguntó a dos",
    y la diferencia es la que dice si vale la pena volver a intentar.
    """
    json = comparacion_como_json(
        comparar(
            [
                _lectura("nadro", "146.38", "40"),
                _lectura("levic", "86.05", "12"),
                _lectura("vicma", motivo=SESION_CADUCADA),
            ],
            3,
        )
    )

    assert json["consultados"] == 3
    assert json["con_precio"] == 2
    assert json["se_comparo"] is True


def test_la_lista_trae_el_conteo_con_los_cuatro_casos_sembrados(
    cliente, almacen, doyle
):
    """De punta a punta, y es el mismo caso que se sembró en el navegador."""
    _poblar_los_cuatro_casos(almacen, doyle)
    _consultar_los_tres(cliente)

    conteo = cliente.get(RUTA).json()["conteo_de_precios"]

    assert conteo["renglones"] == 4
    assert conteo["comparados"] == 1
    assert conteo["sin_comparar"] == 3
    assert conteo["sin_consultar"] == 1
    assert conteo["sin_un_solo_precio"] == 1
    assert conteo["con_un_solo_precio"] == 1
    assert conteo["hay_sin_comparar"] is True


def test_el_conteo_no_cuenta_los_renglones_descartados(cliente, almacen, doyle):
    """Un descartado ya se atendió: nadie va a comprarlo y nada falta de él.

    Se aparta de `sin_clasificar`, que sí se cuenta sobre la lista entera: esa
    pregunta es sobre el catálogo de SICAR y no cambia porque alguien descarte
    un renglón hoy. Ésta es sobre la compra que se está por decidir, y un número
    que subiera mientras la lista se resuelve se dejaría de mirar.
    """
    _poblar_los_cuatro_casos(almacen, doyle)
    _consultar_los_tres(cliente)

    renglon = _por_clave(cliente)[SIN_CONSULTAR_CLAVE]
    respuesta = cliente.post(f"/api/renglon/{renglon['renglon_id']}/descartar").json()

    assert respuesta["conteo_de_precios"]["renglones"] == 3
    assert respuesta["conteo_de_precios"]["sin_consultar"] == 0
    assert respuesta["conteo_de_precios"]["sin_comparar"] == 2
    # Y la carga siguiente dice lo mismo: el conteo sale del servidor las dos
    # veces y no de una cuenta que el navegador vaya llevando.
    assert cliente.get(RUTA).json()["conteo_de_precios"]["renglones"] == 3


def test_devolver_un_renglon_lo_vuelve_a_meter_en_el_conteo(cliente, almacen, doyle):
    """Y al revés: devolverlo a la lista de trabajo vuelve a contarlo."""
    _poblar_los_cuatro_casos(almacen, doyle)
    renglon_id = _por_clave(cliente)[SIN_CONSULTAR_CLAVE]["renglon_id"]

    cliente.post(f"/api/renglon/{renglon_id}/descartar")
    respuesta = cliente.post(f"/api/renglon/{renglon_id}/devolver").json()

    assert respuesta["conteo_de_precios"]["renglones"] == 4
    assert respuesta["conteo_de_precios"]["sin_consultar"] == 4


def test_una_lista_recien_armada_dice_que_no_se_ha_comparado_nada(
    cliente, almacen, doyle
):
    """El estado ordinario de hoy: el precio se pide renglón por renglón.

    Sin este número, cuatro renglones sin un solo precio se ven exactamente
    igual que cuatro comparados contra los cuatro proveedores.
    """
    _poblar_los_cuatro_casos(almacen, doyle)

    conteo = cliente.get(RUTA).json()["conteo_de_precios"]

    assert conteo == {
        "renglones": 4,
        "comparados": 0,
        "sin_comparar": 4,
        "hay_sin_comparar": True,
        "sin_consultar": 4,
        "sin_un_solo_precio": 0,
        "con_un_solo_precio": 0,
    }


def test_el_conteo_como_json_trae_el_total_y_el_desglose():
    """Los dos hacen dos cosas: el total se lee de un vistazo y el desglose
    dice qué hacer con él."""
    json = conteo_como_json(contar_la_lista(_cuatro_comparaciones()))

    assert json["sin_comparar"] == 3
    assert json["hay_sin_comparar"] is True
    assert set(json) == {
        "renglones",
        "comparados",
        "sin_comparar",
        "hay_sin_comparar",
        "sin_consultar",
        "sin_un_solo_precio",
        "con_un_solo_precio",
    }


# ====================================================================
# CASILLA 2 — cada precio faltante dice su motivo
# ====================================================================


#: Los cuatro motivos que el ticket nombra, con las palabras del ticket.
LOS_CUATRO_DEL_TICKET = (
    (SIN_RESULTADOS, "el producto no está en ese catálogo"),
    (VARIOS_RESULTADOS, "el EAN dio varios resultados"),
    (PORTAL_SIN_CONTESTAR, "el portal no contestó"),
    (SESION_CADUCADA, "la sesión de ese proveedor caducó"),
)


def test_los_cuatro_motivos_del_ticket_existen_y_son_cuatro_distintos():
    """Ninguno de los cuatro se está fusionando con otro.

    Es la comprobación que el ticket pide de frente: los ocho motivos del
    vocabulario cerrado tienen que cubrir estos cuatro **por separado**, porque
    cada uno lleva a una acción distinta —no hay nada que hacer, no se puede
    elegir sin adivinar, se reintenta, se abre la sesión—.
    """
    claves = [motivo for motivo, _ in LOS_CUATRO_DEL_TICKET]

    assert len(set(claves)) == 4
    for motivo in claves:
        assert motivo in MOTIVOS


@pytest.mark.parametrize("motivo, frase", LOS_CUATRO_DEL_TICKET)
def test_cada_motivo_del_ticket_se_dice_con_las_palabras_del_ticket(motivo, frase):
    """Lo que se lee en la pantalla es la frase del ticket, no la cadena corta.

    "sin resultados" es lo que se guarda y lo que se cuenta; "el producto no
    está en ese catálogo" es lo que dice si hay algo que hacer. Ninguna regla de
    texto convierte la primera en la segunda, y ese salto es justo el que hace
    que un hueco se pueda atender.
    """
    assert frase in explicacion_del_motivo(motivo)


def test_no_empareja_no_se_fusiona_con_sin_resultados():
    """`no empareja` y `sin resultados` se parecen y NO son el mismo.

    Los dos terminan en "no está en ese catálogo", y por eso hay que decir en
    qué se distinguen: en el primero llegaron filas y ninguna es este producto
    —el final ordinario de QuePharma, que busca por código interno (ADR 0002)—
    y en el segundo el portal no encontró nada. Fundirlos escondería que ese
    portal casi nunca empareja, que es una de las preguntas abiertas del
    `HANDOVER`.
    """
    assert NO_EMPAREJA != SIN_RESULTADOS
    assert explicacion_del_motivo(NO_EMPAREJA) != explicacion_del_motivo(SIN_RESULTADOS)
    assert "llegaron resultados" in explicacion_del_motivo(NO_EMPAREJA)


def test_los_ocho_motivos_tienen_explicacion_y_ninguna_se_repite():
    """Ocho motivos, ocho explicaciones distintas. Si dos coincidieran, sobraría
    uno de los dos motivos."""
    assert set(EXPLICACION_DEL_MOTIVO) == set(MOTIVOS)
    assert len(set(EXPLICACION_DEL_MOTIVO.values())) == len(MOTIVOS)


def test_un_motivo_que_no_esta_en_el_mapa_se_dice_tal_cual():
    """Regla 4: nada se cae de la pantalla por no reconocerse.

    El día que un motivo nuevo llegue sin su explicación, el hueco sigue
    diciendo algo —la cadena corta— en vez de quedarse mudo.
    """
    assert explicacion_del_motivo("motivo que nadie escribió") == (
        "motivo que nadie escribió"
    )
    assert explicacion_del_motivo(None) is None


def test_cada_hueco_del_renglon_viaja_con_su_motivo_y_su_explicacion(
    cliente, almacen, doyle
):
    """El renglón donde los cuatro fallaron, cada uno por su razón."""
    _poblar_los_cuatro_casos(almacen, doyle)
    _consultar_los_tres(cliente)

    casillas = {
        c["proveedor"]: c
        for c in _por_clave(cliente)[SIN_PRECIOS_CLAVE]["comparacion"]["por_proveedor"]
    }

    assert casillas["nadro"]["motivo"] == SIN_RESULTADOS
    assert casillas["levic"]["motivo"] == VARIOS_RESULTADOS
    assert casillas["vicma"]["motivo"] == PORTAL_SIN_CONTESTAR
    assert casillas["quepharma"]["motivo"] == SESION_CADUCADA
    # Los cuatro motivos son distintos entre sí **en la respuesta**, no solo en
    # el módulo: es lo que hace que el encargado sepa cuál de los cuatro puede
    # arreglar él.
    assert len({c["motivo"] for c in casillas.values()}) == 4
    for casilla in casillas.values():
        assert casilla["motivo_explicado"] == explicacion_del_motivo(casilla["motivo"])


def test_la_pantalla_escribe_el_motivo_explicado():
    """Y se cae a la cadena corta si el servidor no manda la larga."""
    assert "c.motivo_explicado || c.motivo" in _pantalla()


# ====================================================================
# CASILLA 4 — el conteo es legible sin abrir cada renglón
# ====================================================================


def test_el_conteo_va_arriba_de_la_tabla_y_no_dentro_de_un_renglon():
    """La casilla es de pantalla: se tiene que ver de un vistazo, arriba.

    Un conteo escondido dentro de cada renglón no es un conteo: es exactamente
    lo que hay que abrir uno por uno para saber cuánto falta.
    """
    portada = _pantalla()

    assert 'id="pedido-sin-comparar"' in portada
    assert portada.index('id="pedido-sin-comparar"') < portada.index('id="pedido-tabla"')


def test_la_pantalla_pinta_el_conteo_con_los_numeros_del_servidor():
    """Ningún número se cuenta en el navegador.

    La regla de qué es "sin comparar" no es obvia —consultado sin precios y no
    consultado son dos cosas— y escribirla aquí la pondría en el único archivo
    que ninguna prueba de Python mira, que es el error que este ticket vino a
    arreglar en la marca del ganador.
    """
    portada = _pantalla()

    assert "pintarConteoDePrecios" in portada
    assert "datos.conteo_de_precios" in portada
    for campo in (
        "sin_comparar",
        "sin_consultar",
        "sin_un_solo_precio",
        "con_un_solo_precio",
        "hay_sin_comparar",
    ):
        assert "conteo." + campo in portada


def test_la_pantalla_dice_contra_cuantos_proveedores_se_comparo_cada_renglon():
    """El segundo número de la casilla 1, en la celda de cada renglón."""
    portada = _pantalla()

    assert "comparacion.con_precio" in portada
    assert "comparacion.consultados" in portada
    assert "comparacion.se_comparo" in portada


def test_la_pantalla_avisa_cuando_el_conteo_envejecio():
    """Consultar un precio cambia el conteo y esa respuesta no lo trae.

    La lista se pide **una sola vez** —es un acuerdo más viejo que este ticket y
    hay tres pruebas que lo fijan—, así que el conteo no se refresca solo. Lo
    que no puede pasar es que un número viejo se presente como de ahora: eso es
    la falla silenciosa de la regla 4. Se marca y se dice.
    """
    portada = _pantalla()

    assert "conteoEnvejecido" in portada
    assert "Recarga la página para ponerlo al día" in portada
    # Y sigue pidiéndose una sola vez: si esto sube a dos, el acuerdo se rompió.
    assert portada.count("fetch('/api/pedido-sugerido')") == 1


def test_la_pantalla_no_dice_que_la_referencia_es_la_mas_barata_si_fue_la_unica():
    """El quinto caso del veredicto, y lo cazó el navegador y no el suite.

    Con NADRO como único proveedor con precio, el ahorro contra NADRO se puede
    calcular y da **cero** —comprarle a él en vez de a él no ahorra nada—, así
    que la frase "NADRO ya es el más barato" se disparaba: la misma afirmación
    que este ticket prohíbe, tres renglones debajo de la marca que ya decía "el
    único que contestó". La rama del cero legítimo queda guardada por la misma
    bandera que la marca.
    """
    portada = _pantalla()

    assert "a.hay && a.la_referencia_gana && comparacion.ganador.es_unico" in portada
    assert "fue el único que dio precio" in portada


def test_el_conteo_escribe_el_singular_cuando_queda_un_solo_renglon():
    """"los 1 renglones" se lee como una pantalla rota, y una pantalla rota se
    deja de creer justo donde este ticket necesita que se le crea.

    Pasa de verdad: basta descartar todo menos uno. Se vio en el recorrido del
    navegador del 2026-09-19, igual que el `+-60.33` del ticket 14.
    """
    portada = _pantalla()

    assert "el único renglón de la lista se comparó" in portada
    assert "solo 1 tiene dos precios o más." in portada
