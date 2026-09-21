"""Los estados vacíos y de falla (ticket 29): que la pantalla diga qué pasó.

El manejo de errores del servidor existe desde el primer commit —reglas 4 y 5
de `CLAUDE.md`—; lo que faltaba es que la **pantalla** lo dijera en vez de
enseñar el vacío, que se lee como una respuesta. El inventario completo, ruta
por ruta y `fetch` por `fetch`, está en el ticket
(`.scratch/pedido-sugerido/issues/29-estados-vacios-y-de-falla.md`).

Cinco cosas, una por casilla:

1. **Doyle caído no esconde la lista**: la lista se ve, y dice que los precios
   no están disponibles y por qué (`/api/doyle`).
2. **El almacén caído no parece "no se vendió nada"**: el hueco lo dice con
   todas sus letras, y un 500 del servidor ya no cae en la rama de "sin ventas".
3. **"No hubo ventas" es un hecho que el servidor AFIRMA** —leyó y no había—,
   distinto de "no pude leer". Y un lunes por la mañana, la lista del viernes
   dice si eso es lo normal o si falta algo que ya debía haber llegado.
4. **Ningún error lleva detalles al navegador**, y eso no se prueba ruta por
   ruta a mano: la prueba recorre `app.routes` entera y le inyecta la falla en
   cada llamada a cada borde. La ruta que alguien agregue mañana entra sola.
5. **Cada falla dice qué hacer**, o que no hay nada que hacer y a quién
   avisarle. El contacto es configuración, no un nombre escrito en el código.

Ninguna prueba toca Postgres, ni Doyle, ni la red, ni duerme.
"""

from __future__ import annotations

import ast
import copy
import datetime as dt
import logging
import re
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from conftest import pantalla_completa, pantalla_servida
from continental import config
from continental.almacen import LineaDeCompra, LineaDeVenta, Producto
from continental.consultas import RegistroDeConsultas
from continental.dobles import AlmacenamientoFalso, AlmacenFalso, DoyleFalso, respuesta_lista
from continental.fallas import (
    A_QUIEN_AVISAR_POR_OMISION,
    AL_GUARDAR,
    AL_LEER,
    CASOS,
    CONFIGURACION,
    DOYLE,
    PETICION,
    SERVIDOR,
    estado_de_las_ventas,
    falla_como_json,
    frase_de_doyle_caido,
    frase_de_la_lista_vacia,
    frase_del_hueco,
    que_hacer,
    ultimo_dia_que_ya_deberia_estar,
)
from continental.precios import LecturaDePrecio
from continental.transito import ZONA_DE_LA_FARMACIA
from continental.web import app as modulo_app
from continental.web.app import app
from continental.web.dependencias import (
    obtener_almacen,
    obtener_almacenamiento,
    obtener_consultas,
    obtener_doyle,
)

RAIZ = Path(__file__).resolve().parent.parent
NEGOCIO = "farmacia_01"
CORREO = "encargado@farmacia.mx"
FIRMA = {"Cf-Access-Authenticated-User-Email": CORREO}
RUTA = "/api/pedido-sugerido"

#: Lo que un `str(exc)` de SQLAlchemy llevaría: la cadena de conexión con su
#: contraseña. Si esta palabra aparece en una sola respuesta, la regla 5 se rompió.
SECRETO = "SECRETO"
CADENA_CON_SECRETO = f"connection to postgresql://usuario:{SECRETO}@host/db failed"

# Una semana de septiembre de 2026, con nombre. El 20 es domingo.
LUNES_14 = dt.date(2026, 9, 14)
MARTES_15 = dt.date(2026, 9, 15)
MIERCOLES_16 = dt.date(2026, 9, 16)
JUEVES_17 = dt.date(2026, 9, 17)
VIERNES_18 = dt.date(2026, 9, 18)
SABADO_19 = dt.date(2026, 9, 19)
DOMINGO_20 = dt.date(2026, 9, 20)
LUNES_21 = dt.date(2026, 9, 21)
MARTES_22 = dt.date(2026, 9, 22)


def _en_la_farmacia(fecha: dt.date, hora: int, minuto: int = 0) -> dt.datetime:
    return dt.datetime(fecha.year, fecha.month, fecha.day, hora, minuto, tzinfo=ZONA_DE_LA_FARMACIA)


def _venta(fecha: dt.date, producto_id: int, cantidad: float = 3) -> LineaDeVenta:
    return LineaDeVenta(
        fecha=fecha,
        producto_id=producto_id,
        cantidad=cantidad,
        importe=cantidad * 10.0,
        costo=cantidad * 6.0,
        utilidad=cantidad * 4.0,
    )


def _producto(producto_id: int) -> Producto:
    return Producto(
        producto_id=producto_id,
        clave=f"750100000{producto_id:04d}",
        descripcion=f"PRODUCTO {producto_id}",
        categoria="MEDICAMENTO",
        departamento="FARMACIA",
        anaquel="PATENTE 1",
        precio_lista_sin_iva=50.0,
        costo=30.0,
        existencia=2.0,
        esta_activo=True,
        es_granel=False,
    )


def _lectura(proveedor: str, precio: str = "12.50") -> LecturaDePrecio:
    return LecturaDePrecio(
        proveedor=proveedor,
        precio_como_llego=precio,
        precio=Decimal(precio),
        existencia_como_llego="40",
        existencia=Decimal("40"),
        motivo=None,
    )


def _fijar_la_hora(monkeypatch, instante: dt.datetime) -> None:
    monkeypatch.setattr(modulo_app, "_ahora", lambda: instante)


# ================================================== casilla 5: qué hacer
#
# Va primero porque las otras cuatro la usan: cada falla termina en una de
# estas frases.


@pytest.mark.parametrize("caso", CASOS)
def test_cada_caso_dice_que_hacer_y_a_quien_avisar(caso):
    frase = que_hacer(caso, "a quien administra atlas")

    assert frase.strip()
    assert "a quien administra atlas" in frase, (
        "cada falla termina diciendo a quién avisarle: si la persona no puede "
        "hacer nada, eso es lo único que le queda"
    )


def test_los_casos_son_distintos_entre_si():
    """Seis frases para seis situaciones: una sola frase para todo diría
    "vuelve a intentarlo" sobre un archivo de configuración mal escrito."""
    frases = [que_hacer(caso, "X") for caso in CASOS]

    assert len(set(frases)) == len(CASOS)


def test_un_caso_que_no_existe_truena_en_vez_de_callar():
    """Regla 4: un caso mal escrito en una ruta no puede dejar la falla sin
    su frase. Truena aquí, donde una prueba lo ve."""
    with pytest.raises(ValueError):
        que_hacer("se-me-olvido", "X")


def test_al_guardar_no_afirma_si_se_guardo_o_no():
    """Una escritura que truena pudo haberse aplicado —el `commit` pasó y la
    conexión se cayó al contestar—. La frase manda a mirar, no afirma."""
    frase = que_hacer(AL_GUARDAR, "X").lower()

    assert "vuelve a cargar" in frase
    assert "cómo quedó" in frase
    assert "no se guardó" not in frase
    assert "se quedó como estaba" not in frase


def test_doyle_caido_dice_que_hay_que_levantarlo_sin_repetir_la_frase():
    """Que la lista se ve igual lo dice la frase del hueco; el qué hacer dice lo
    que no funciona y cómo se arregla. El recorrido del navegador cazó las dos
    diciendo lo mismo, una debajo de la otra."""
    frase = que_hacer(DOYLE, "X")

    assert "Levanta Doyle" in frase
    assert "consultar o completar precios" in frase.lower()
    assert "se ve igual" not in frase and "se trabaja igual" not in frase
    assert "se ve igual" in frase_de_doyle_caido("Doyle no responde (TimeoutError)")


def test_la_configuracion_mala_dice_que_desde_aqui_no_hay_nada_que_hacer():
    frase = que_hacer(CONFIGURACION, "X")

    assert "no hay nada que hacer" in frase
    assert "config/continental.yml" in frase


def test_el_servidor_dice_que_el_detalle_quedo_en_la_bitacora():
    assert "bitácora" in que_hacer(SERVIDOR, "X")


def test_la_falla_como_json_lleva_ok_detalle_y_que_hacer():
    assert falla_como_json("no se pudo X (RuntimeError)", AL_LEER, "Y") == {
        "ok": False,
        "detalle": "no se pudo X (RuntimeError)",
        "que_hacer": que_hacer(AL_LEER, "Y"),
    }


def test_a_quien_avisar_es_configuracion_y_no_un_nombre_en_el_codigo():
    """"No inventes nombres ni teléfonos": el contacto concreto vive en el YAML
    y, si falta, se dice qué se hace —avisarle a quien administra atlas—."""
    yml = (RAIZ / "config" / "continental.yml").read_text(encoding="utf-8")

    assert "a_quien_avisar:" in yml
    assert config.cargar().a_quien_avisar
    assert A_QUIEN_AVISAR_POR_OMISION == "a quien administra atlas"


def test_sin_la_llave_en_el_yaml_se_usa_la_frase_por_omision(monkeypatch, tmp_path):
    yml = tmp_path / "continental.yml"
    yml.write_text("modulos: {}\npedido: {}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG", yml)
    config.cargar.cache_clear()
    try:
        assert config.cargar().a_quien_avisar == A_QUIEN_AVISAR_POR_OMISION
    finally:
        config.cargar.cache_clear()


def test_la_pantalla_ya_no_nombra_a_nadie():
    """Hasta el ticket 29 el JavaScript decía "Avísale a Eddie": un nombre de
    persona escrito en el único archivo sin pruebas de Python."""
    assert "Eddie" not in pantalla_completa()


# ======================== casilla 3: "no hubo ventas" contra "no pude leer"


@pytest.mark.parametrize(
    ("ahora", "esperada"),
    [
        # La cadena corre a las 20:30 de lunes a viernes; a las 22:00 —la hora
        # del lote— ya se cuenta con ella.
        (_en_la_farmacia(LUNES_21, 10), VIERNES_18),
        (_en_la_farmacia(LUNES_21, 21, 59), VIERNES_18),
        (_en_la_farmacia(LUNES_21, 22), LUNES_21),
        (_en_la_farmacia(MARTES_22, 9), LUNES_21),
        (_en_la_farmacia(VIERNES_18, 23), VIERNES_18),
        # El sábado no sube respaldo: lo del sábado llega el lunes.
        (_en_la_farmacia(SABADO_19, 12), VIERNES_18),
        (_en_la_farmacia(DOMINGO_20, 23), VIERNES_18),
    ],
)
def test_el_ultimo_dia_que_ya_deberia_estar_sigue_el_horario_de_la_cadena(ahora, esperada):
    assert ultimo_dia_que_ya_deberia_estar(ahora) == esperada


def test_el_dia_se_cuenta_en_la_hora_de_la_farmacia_y_no_en_utc():
    """Las 03:00 UTC del martes son las 21:00 del lunes en la farmacia: la
    cadena del lunes todavía no cuenta. En UTC diría que sí."""
    ahora = dt.datetime(2026, 9, 22, 3, 0, tzinfo=dt.UTC)

    assert ultimo_dia_que_ya_deberia_estar(ahora) == VIERNES_18


def test_el_lunes_por_la_manana_la_lista_del_viernes_es_lo_normal_y_se_dice():
    """El caso del ticket: el domingo la farmacia cierra y lo del sábado todavía
    no llega. La pantalla enseña la lista del viernes y dice que es lo más
    reciente que puede haber — no que algo falló."""
    estado = estado_de_las_ventas(VIERNES_18, _en_la_farmacia(LUNES_21, 10), "X")

    assert estado["hay"] is True
    assert estado["al_dia"] is True
    assert estado["hasta"] == "2026-09-18"
    assert "el viernes 18 de septiembre" in estado["frase"]
    assert "lo más reciente que puede haber" in estado["frase"]
    assert "el lunes 21 de septiembre" in estado["frase"], "dice cuándo llega lo que sigue"
    assert "20:30" in estado["frase"]
    assert "domingos la farmacia cierra" in estado["frase"]
    assert estado["que_hacer"] is None, "no es una falla: no hay nada que hacer"


def test_entre_semana_no_se_menciona_el_domingo():
    estado = estado_de_las_ventas(MARTES_15, _en_la_farmacia(MIERCOLES_16, 10), "X")

    assert estado["al_dia"] is True
    assert "domingo" not in estado["frase"]
    assert "esta noche" in estado["frase"], "lo de hoy llega con la cadena de hoy"


def test_si_la_cadena_ya_debio_traer_un_dia_y_no_esta_se_dice_sin_inventar_por_que():
    """El lunes a las 23:00 lo del lunes ya debía estar. Continental no sabe
    si la farmacia no abrió o si el respaldo no llegó, y dice las dos cosas."""
    estado = estado_de_las_ventas(VIERNES_18, _en_la_farmacia(LUNES_21, 23), "quien sea")

    assert estado["hay"] is True
    assert estado["al_dia"] is False
    frase = estado["frase"]
    assert "el viernes 18 de septiembre" in frase
    assert "el lunes 21 de septiembre" in frase
    assert "no sabe por qué" in frase
    assert "si la farmacia no abrió" in frase, "puede ser un feriado: no se afirma una falla"
    assert estado["que_hacer"] and "quien sea" in estado["que_hacer"]
    assert "se puede trabajar" in estado["que_hacer"], "la lista de abajo sigue sirviendo"


def test_un_feriado_entre_semana_no_se_afirma_como_cerrado():
    """El 16 de septiembre se ve en el almacén idéntico a un domingo: cero
    filas (medido el 2026-09-20, `config/continental.yml`). Cero filas NO
    quiere decir "cerraron", y la frase no lo dice."""
    estado = estado_de_las_ventas(MARTES_15, _en_la_farmacia(JUEVES_17, 10), "X")

    assert estado["al_dia"] is False
    assert "cerró" not in estado["frase"]
    assert "cerraron" not in estado["frase"]


def test_sin_una_sola_venta_en_el_almacen_es_un_hecho_y_no_una_falla():
    estado = estado_de_las_ventas(None, _en_la_farmacia(LUNES_21, 10), "quien sea")

    assert estado["hay"] is False
    assert estado["hasta"] is None
    assert "no tiene ni una venta" in estado["frase"]
    assert "No es una falla" in estado["frase"]
    assert "quien sea" in estado["que_hacer"]


def test_el_estado_de_las_ventas_no_mira_el_reloj_por_su_cuenta():
    """El reloj entra por argumento: `fallas.py` no lo lee."""
    fuente = (RAIZ / "src" / "continental" / "fallas.py").read_text(encoding="utf-8")

    for prohibida in ("date.today(", "datetime.now(", "utcnow(", "time.time("):
        assert prohibida not in fuente


def test_la_lista_vacia_no_dice_que_no_se_vendio_nada():
    """Una lista sin renglones sale de ventas que SÍ se leyeron: el último día
    de la ventana siempre tiene ventas (`max(fecha)`). Lo que la deja vacía es
    que todo lo vendido ya venía en camino."""
    frase = frase_de_la_lista_vacia(VIERNES_18, LUNES_21)

    assert "no se vendió nada" not in frase
    assert "se leyeron" in frase.lower()
    assert "ya venía en camino" in frase or "ya viene en camino" in frase
    assert "del viernes 18 al lunes 21 de septiembre" in frase


def test_la_lista_vacia_de_un_solo_dia_lo_dice_con_una_fecha():
    assert "del lunes 21 de septiembre" in frase_de_la_lista_vacia(LUNES_21, LUNES_21)


def test_la_carga_trae_el_estado_de_las_ventas_hecho_en_python(
    cliente, almacen, monkeypatch
):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(VIERNES_18, 1)]
    _fijar_la_hora(monkeypatch, _en_la_farmacia(LUNES_21, 10))

    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["ok"] is True
    assert cuerpo["ventas"] == estado_de_las_ventas(
        VIERNES_18, _en_la_farmacia(LUNES_21, 10), config.cargar().a_quien_avisar
    )


def test_sin_ventas_la_carga_lo_afirma_con_ok_verdadero(cliente, monkeypatch):
    _fijar_la_hora(monkeypatch, _en_la_farmacia(LUNES_21, 10))

    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["ok"] is True
    assert cuerpo["ventas"]["hay"] is False
    assert "no tiene ni una venta" in cuerpo["ventas"]["frase"]


def test_una_lista_vacia_trae_su_frase_hecha_en_python(
    cliente, almacen, almacenamiento, monkeypatch
):
    """Se arma una lista sin renglones como la armaría la vida real: todo lo
    vendido viene en camino. Se siembra directo en el doble —una lista
    guardada vacía— para no depender de toda la maquinaria del tránsito."""
    from continental.almacenamiento import Ventana

    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES_21, 1)]
    almacenamiento.abrir_el_dia(
        NEGOCIO, LUNES_21, Ventana(desde=VIERNES_18, hasta=LUNES_21), lambda: ()
    )
    _fijar_la_hora(monkeypatch, _en_la_farmacia(LUNES_21, 23))

    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["ok"] is True
    assert cuerpo["renglones"] == []
    assert cuerpo["lista_vacia"] == frase_de_la_lista_vacia(VIERNES_18, LUNES_21)


def test_una_lista_con_renglones_no_trae_frase_de_lista_vacia(cliente, almacen):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES_21, 1)]

    assert cliente.get(RUTA).json()["lista_vacia"] is None


# ============================ casilla 2: el almacén caído no es "no se vendió"


def test_el_almacen_caido_dice_que_la_lista_no_esta_vacia_y_que_hacer(cliente, almacen):
    almacen.falla = RuntimeError(CADENA_CON_SECRETO)

    respuesta = cliente.get(RUTA)
    cuerpo = respuesta.json()

    assert cuerpo["ok"] is False
    assert "RuntimeError" in cuerpo["detalle"]
    assert cuerpo["frase"] == frase_del_hueco(cuerpo["detalle"])
    assert "no quiere decir que no se vendió nada" in cuerpo["frase"]
    assert cuerpo["que_hacer"] == que_hacer(AL_LEER, config.cargar().a_quien_avisar)
    assert SECRETO not in respuesta.text


def test_la_base_de_pedidos_caida_tambien_es_un_hueco_con_que_hacer(
    cliente, almacen, almacenamiento
):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES_21, 1)]
    almacenamiento.falla = RuntimeError(CADENA_CON_SECRETO)

    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["ok"] is False
    assert cuerpo["que_hacer"]
    assert "no quiere decir que no se vendió nada" in cuerpo["frase"]


class _FallaEn(AlmacenamientoFalso):
    """El almacenamiento que contesta todo salvo una lectura."""

    def __init__(self, metodo: str):
        super().__init__()
        self._metodo = metodo

    def __getattribute__(self, nombre):
        if nombre != "_metodo" and nombre == object.__getattribute__(self, "_metodo"):
            raise RuntimeError(CADENA_CON_SECRETO)
        return super().__getattribute__(nombre)


def _lista_con_la_lectura_caida(cliente, almacen, metodo: str) -> dict:
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES_21, 1)]
    doble = _FallaEn(metodo)
    app.dependency_overrides[obtener_almacenamiento] = lambda: doble
    respuesta = cliente.get(RUTA)
    assert SECRETO not in respuesta.text
    return respuesta.json()


def test_los_precios_que_no_se_leen_no_se_pintan_como_sin_consultar(cliente, almacen):
    """Hasta el ticket 29 una lectura de precios caída se volvía `{}` en
    silencio y la tabla entera decía "nadie lo consultó". Ahora la lista se ve
    igual —sirve para pedir— y un aviso dice que esos huecos no son de verdad."""
    cuerpo = _lista_con_la_lectura_caida(cliente, almacen, "precios_de_la_lista")

    assert cuerpo["ok"] is True
    assert cuerpo["renglones"], "la lista se ve igual"
    [aviso] = cuerpo["avisos"]
    assert "RuntimeError" in aviso["detalle"]
    assert "precios" in aviso["frase"]
    assert "no quiere decir que falten" in aviso["frase"]
    assert aviso["que_hacer"]


def test_sin_los_precios_no_se_calcula_nada_de_lo_que_sale_de_ellos(cliente, almacen):
    """Lo cazó el recorrido del navegador, no el suite: con los precios sin
    leer, el conteo decía "5 de 5 sin comparar", cada renglón "nadie le ha
    pedido el precio", y el botón ofrecía "Completar los 5 que faltan" — cuatro
    visitas a portales ajenos por renglón, por precios que sí existen. Lo que
    sale de los precios viaja `null`, como ya hacían las respuestas de un
    renglón, y el aviso de arriba dice por qué."""
    cuerpo = _lista_con_la_lectura_caida(cliente, almacen, "precios_de_la_lista")

    assert cuerpo["conteo_de_precios"] is None
    assert cuerpo["faltantes"] is None
    assert cuerpo["sesiones_caducadas"] == []
    for renglon in cuerpo["renglones"]:
        assert "porque_no_hay_lectura" not in renglon
        assert renglon["huecos_reintentables"] == []


def test_los_pedidos_que_no_se_leen_no_se_pintan_como_sin_partir(cliente, almacen):
    cuerpo = _lista_con_la_lectura_caida(cliente, almacen, "pedidos_de_la_lista")

    assert cuerpo["ok"] is True
    [aviso] = cuerpo["avisos"]
    assert "pedidos" in aviso["frase"]
    assert "No partas" in aviso["frase"] or "no partas" in aviso["frase"]
    assert aviso["que_hacer"]


def test_sin_fallas_no_hay_avisos(cliente, almacen):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES_21, 1)]

    assert cliente.get(RUTA).json()["avisos"] == []


def test_lo_que_viene_en_camino_y_la_recepcion_caidos_dicen_que_hacer(cliente, almacen):
    cuerpo = _lista_con_la_lectura_caida(cliente, almacen, "lo_ya_pedido")

    # `lo_ya_pedido` también lo usa la memoria al ARMAR: la lista entera es un
    # hueco, y por eso esto se mira con la lista ya guardada.
    assert cuerpo["ok"] is False
    assert cuerpo["que_hacer"]

    cuerpo = _lista_con_la_lectura_caida(cliente, almacen, "lo_que_esta_en_transito")
    assert cuerpo["ok"] is True
    assert cuerpo["recepcion"]["ok"] is False
    assert cuerpo["recepcion"]["que_hacer"]


def test_el_bloque_en_camino_caido_con_la_lista_ya_guardada_dice_que_hacer(
    cliente, almacen, almacenamiento
):
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES_21, 1)]
    assert cliente.get(RUTA).json()["ok"] is True  # la lista queda guardada

    original = almacenamiento.lo_ya_pedido

    def caido(*a, **k):
        raise RuntimeError(CADENA_CON_SECRETO)

    almacenamiento.lo_ya_pedido = caido
    try:
        respuesta = cliente.get(RUTA)
    finally:
        almacenamiento.lo_ya_pedido = original

    cuerpo = respuesta.json()
    assert SECRETO not in respuesta.text
    assert cuerpo["ok"] is True
    assert cuerpo["en_camino"]["ok"] is False
    assert cuerpo["en_camino"]["que_hacer"]


def test_el_sondeo_del_precio_no_borra_lo_que_ya_estaba_si_no_pudo_leer(
    cliente, almacenamiento
):
    """Hasta el ticket 29 `GET …/precio` con la lectura caída contestaba
    `precios: []`, y la pantalla lo pintaba encima de lo que ya tenía."""
    almacenamiento.falla = RuntimeError(CADENA_CON_SECRETO)

    respuesta = cliente.get("/api/renglon/1/precio")
    cuerpo = respuesta.json()

    assert SECRETO not in respuesta.text
    assert cuerpo["precios"] is None, "None es 'no se pudo leer', no 'no hay'"
    assert cuerpo["comparacion"] is None
    assert cuerpo["precios_sin_leer"]["que_hacer"]
    assert "RuntimeError" in cuerpo["precios_sin_leer"]["detalle"]


# ======================================= casilla 1: Doyle caído, la lista igual


def test_doyle_caido_se_dice_con_su_motivo_y_con_que_hacer(cliente, doyle):
    doyle.falla = TimeoutError(CADENA_CON_SECRETO)

    respuesta = cliente.get("/api/doyle")
    cuerpo = respuesta.json()

    assert respuesta.status_code == 200
    assert cuerpo["ok"] is True, "la pregunta se atendió: la respuesta es que Doyle no contesta"
    assert cuerpo["contesta"] is False
    assert cuerpo["detalle"] == "Doyle no responde (TimeoutError)"
    assert cuerpo["frase"] == frase_de_doyle_caido(cuerpo["detalle"])
    assert cuerpo["frase"].startswith("Doyle no responde (TimeoutError): ")
    assert "no están disponibles" in cuerpo["frase"]
    assert "La lista se ve igual" in cuerpo["frase"]
    assert cuerpo["que_hacer"] == que_hacer(DOYLE, config.cargar().a_quien_avisar)
    assert SECRETO not in respuesta.text


def test_doyle_vivo_no_trae_frase(cliente):
    cuerpo = cliente.get("/api/doyle").json()

    assert cuerpo == {"ok": True, "contesta": True, "frase": None, "que_hacer": None}


def test_con_doyle_caido_la_lista_se_arma_y_se_ve_igual(cliente, almacen, doyle):
    """La lista no depende de Doyle: los precios que ya estaban guardados se
    leen de `pedidos`, no de él. Doyle caído se pregunta APARTE."""
    doyle.falla = TimeoutError("no contestó")
    almacen.catalogo_en_memoria = [_producto(1)]
    almacen.ventas_en_memoria = [_venta(LUNES_21, 1)]

    cuerpo = cliente.get(RUTA).json()

    assert cuerpo["ok"] is True
    assert len(cuerpo["renglones"]) == 1
    assert doyle.pedidos == [] and doyle.consultas == []


def test_la_pantalla_pregunta_por_doyle_aparte_y_pinta_lo_que_llega():
    pantalla = pantalla_completa()

    assert pantalla.count("fetch('/api/doyle')") == 1
    assert 'id="pedido-doyle"' in pantalla
    # La frase y el qué hacer llegan hechos: aquí no se compone "no disponible".
    assert "no están disponibles" not in _solo_el_script(pantalla)


# ============================== casilla 4: ningún detalle viaja al navegador
#
# No se prueba ruta por ruta a mano. Se recorre `app.routes` y, para cada ruta,
# se le inyecta la falla en CADA llamada que haga a cada borde —la primera, la
# segunda, ...— hasta que la ruta termina sin llegar a la N. Una ruta nueva
# entra sola; una lectura nueva dentro de una ruta vieja, también.

#: Cuerpos válidos por modelo. Si una ruta estrena un modelo que no está aquí,
#: la prueba se pone roja en vez de mandarle `{}` y quedarse en el 422.
CUERPOS = {
    "CantidadNueva": {"cantidad": 3},
    "ProveedorElegido": {"proveedor": "nadro"},
    "MarcaDeCaptura": {"capturado": True},
    "ComprasVistas": {"compras": [1]},
    "PiezasRecibidas": {"piezas": 2},
}

#: Con qué se prueba cada parámetro de ruta. Se prueban todos y la ruta se
#: recorre con el que la lleva MÁS HONDO —el que más llamadas hace a los
#: bordes—: un renglón descartado no llega a la escritura, uno abierto sí.
VALORES = {
    "renglon_id": (1, 2, 3, 4),
    "pedido_id": (1, 2),
    "pedido_sugerido_id": (1,),
    "proveedor": ("nadro",),
}

RUTAS = [r for r in app.routes if isinstance(r, APIRoute)]
BORDES = ("almacen", "almacenamiento", "doyle")
TOPE_DE_LLAMADAS = 60


class _Cuenta:
    """Envuelve un doble: cuenta las llamadas de la ruta y truena en la N."""

    def __init__(self, doble, falla_en: int | None = None):
        self._doble = doble
        self._falla_en = falla_en
        self.llamadas = 0
        self.disparo = False

    def __getattr__(self, nombre):
        valor = getattr(self._doble, nombre)
        if nombre.startswith("_") or not callable(valor):
            return valor

        def envuelta(*args, **kwargs):
            self.llamadas += 1
            if self.llamadas == self._falla_en:
                self.disparo = True
                raise RuntimeError(CADENA_CON_SECRETO)
            return valor(*args, **kwargs)

        return envuelta


class _SinRed:
    """`httpx.AsyncClient` que no sale a la red: `/api/modulos` no tiene
    costura y le pegaría al Doyle de verdad si estuviera corriendo."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, *args, **kwargs):
        raise httpx.ConnectError(CADENA_CON_SECRETO)


@pytest.fixture(scope="module")
def cliente_sin_relanzar():
    """Un cliente que deja al manejador global contestar el 500.

    `raise_server_exceptions=False`: con el de omisión, `TestClient` vuelve a
    lanzar la excepción en la prueba y el manejador nunca se ve. Con `with`,
    por la razón de `conftest.cliente_de_sesion`: un solo bucle de eventos.
    """
    with TestClient(app, raise_server_exceptions=False) as cliente:
        yield cliente


@pytest.fixture(scope="module")
def semilla(cliente_sin_relanzar):
    """Una lista con un poco de todo, armada por la aplicación misma.

    Cuatro renglones: dos con precio de NADRO que se parten y se envían (en
    tránsito, uno con una compra que encaja), uno con precio de LEVIC en un
    pedido en borrador, y uno descartado. Así cada ruta encuentra un renglón o
    un pedido en el estado que la lleva más adentro.
    """
    almacen, almacenamiento, doyle = AlmacenFalso(), AlmacenamientoFalso(), DoyleFalso()
    almacen.catalogo_en_memoria = [_producto(p) for p in (1, 2, 3, 4)]
    almacen.ventas_en_memoria = [_venta(LUNES_21, p) for p in (1, 2, 3, 4)]
    almacen.compras_en_memoria = [
        LineaDeCompra(
            compra_id=1, producto_id=1, proveedor_id=1, fecha=MARTES_22, cantidad=3,
            precio_unitario_pagado=12.5, importe_pagado=37.5, folio="F-1",
        )
    ]
    # Doyle contesta TERMINADO a la primera para cada clave: con una búsqueda
    # pendiente, la consulta de precio sondearía con el `time.sleep` de verdad
    # hasta su tope de 120 s — y este suite no duerme.
    doyle.resultados_por_termino = {
        f"750100000{p:04d}": {
            proveedor: respuesta_lista(proveedor, [(f"750100000{p:04d}", "12.50", "40")])
            for proveedor in ("nadro", "levic", "vicma", "quepharma")
        }
        for p in (1, 2, 3, 4)
    }
    registro = RegistroDeConsultas(lanzar=lambda tarea: tarea())
    app.dependency_overrides.update({
        obtener_almacen: lambda: almacen,
        obtener_almacenamiento: lambda: almacenamiento,
        obtener_doyle: lambda: doyle,
        obtener_consultas: lambda: registro,
    })
    try:
        c = cliente_sin_relanzar
        lista = c.get(RUTA).json()
        assert lista["ok"] is True, lista
        por_producto = {r["producto_id"]: r["renglon_id"] for r in lista["renglones"]}
        for p in (1, 2):
            almacenamiento.guardar_precios(NEGOCIO, por_producto[p], [_lectura("nadro")])
        almacenamiento.guardar_precios(NEGOCIO, por_producto[3], [_lectura("levic")])
        assert c.post(f"/api/renglon/{por_producto[4]}/descartar", headers=FIRMA).json()["ok"]
        partida = c.post(f"{RUTA}/{lista['pedido_sugerido_id']}/partir").json()
        assert partida["ok"] is True, partida
        [nadro] = [p for p in partida["pedidos"] if p["proveedor"] == "nadro"]
        assert c.post(f"/api/pedido/{nadro['pedido_id']}/enviar", headers=FIRMA).json()["ok"]
    finally:
        app.dependency_overrides.clear()
    return almacen, almacenamiento, doyle


def _cuerpo_de(ruta: APIRoute):
    parametros = ruta.dependant.body_params
    if not parametros:
        return None
    [parametro] = parametros
    nombre = parametro.field_info.annotation.__name__
    assert nombre in CUERPOS, (
        f"{ruta.path} recibe un {nombre} que esta prueba no sabe llenar: agrégalo "
        "a CUERPOS, o la ruta se quedaría en el 422 sin llegar a ningún borde"
    )
    return CUERPOS[nombre]


def _caminos(ruta: APIRoute) -> list[str]:
    nombres = re.findall(r"{(\w+)}", ruta.path)
    for nombre in nombres:
        assert nombre in VALORES, f"{ruta.path}: falta con qué probar {{{nombre}}}"
    caminos = [ruta.path]
    for nombre in nombres:
        caminos = [
            c.replace("{" + nombre + "}", str(v)) for c in caminos for v in VALORES[nombre]
        ]
    return caminos


def _llamar(cliente, ruta, camino, semilla, caido=None, falla_en=None):
    """Una petición contra una copia fresca de la semilla. Devuelve la
    respuesta y los tres contadores."""
    almacen, almacenamiento, doyle = copy.deepcopy(semilla)
    cuentas = {
        "almacen": _Cuenta(almacen, falla_en if caido == "almacen" else None),
        "almacenamiento": _Cuenta(almacenamiento, falla_en if caido == "almacenamiento" else None),
        "doyle": _Cuenta(doyle, falla_en if caido == "doyle" else None),
    }
    registro = RegistroDeConsultas(lanzar=lambda tarea: tarea())
    app.dependency_overrides.update({
        obtener_almacen: lambda: cuentas["almacen"],
        obtener_almacenamiento: lambda: cuentas["almacenamiento"],
        obtener_doyle: lambda: cuentas["doyle"],
        obtener_consultas: lambda: registro,
    })
    try:
        [metodo] = sorted(ruta.methods)
        respuesta = cliente.request(metodo, camino, json=_cuerpo_de(ruta), headers=FIRMA)
    finally:
        app.dependency_overrides.clear()
    return respuesta, cuentas


def test_el_recorrido_ve_todas_las_rutas_de_la_api():
    """Si las rutas dejaran de aparecer en `app.routes` —un `APIRouter` mal
    montado— el recorrido pasaría en verde sin mirar nada."""
    caminos = {r.path for r in RUTAS}

    assert len(RUTAS) >= 25
    assert RUTA in caminos and "/api/doyle" in caminos


@pytest.mark.parametrize("ruta", RUTAS, ids=lambda r: f"{sorted(r.methods)[0]} {r.path}")
def test_ninguna_falla_de_ningun_borde_lleva_detalles_al_navegador(
    ruta, semilla, cliente_sin_relanzar, monkeypatch, caplog
):
    """La casilla 4, para todas las rutas y todas las llamadas a los bordes.

    Para cada borde, la falla se inyecta en la llamada 1, luego en la 2, … hasta
    que la ruta termina sin llegar a la N. En cada respuesta:

    - el texto de la excepción no aparece (regla 5);
    - si la respuesta es un `ok: false`, dice **qué hacer** (casilla 5);
    - y el detalle **sí** quedó en la bitácora, con su traza: "el detalle a la
      bitácora" no es "el detalle a ninguna parte".
    """
    monkeypatch.setattr(modulo_app.httpx, "AsyncClient", _SinRed)
    cliente = cliente_sin_relanzar

    # El camino que lleva más hondo: el que más llamadas hace sin fallar.
    def hondura(camino):
        _, cuentas = _llamar(cliente, ruta, camino, semilla)
        return sum(c.llamadas for c in cuentas.values())

    camino = max(_caminos(ruta), key=hondura)
    _, sin_fallas = _llamar(cliente, ruta, camino, semilla)
    inyectadas = 0

    for caido in BORDES:
        for n in range(1, TOPE_DE_LLAMADAS + 1):
            caplog.clear()
            with caplog.at_level(logging.WARNING, logger="continental"):
                respuesta, cuentas = _llamar(cliente, ruta, camino, semilla, caido, n)
            texto = respuesta.text
            donde = f"{camino} con {caido} caído en la llamada {n}"
            assert SECRETO not in texto and "usuario:" not in texto, donde
            if not cuentas[caido].disparo:
                break
            inyectadas += 1
            try:
                cuerpo = respuesta.json()
            except ValueError:
                cuerpo = None
            if isinstance(cuerpo, dict) and cuerpo.get("ok") is False:
                assert cuerpo.get("que_hacer"), f"{donde}: falla sin qué hacer: {cuerpo}"
            en_la_bitacora = [
                r for r in caplog.records
                if r.exc_info or SECRETO in r.getMessage()
            ]
            assert en_la_bitacora, f"{donde}: la falla no quedó en la bitácora"
        else:
            pytest.fail(f"{camino} hizo más de {TOPE_DE_LLAMADAS} llamadas a {caido}")

    # El cinturón del cinturón: si la ruta llama a los bordes, el recorrido
    # tuvo que inyectar al menos una falla por cada llamada del camino sin
    # fallas. Sin esto, un `_Cuenta` que dejara de contar pasaría en verde.
    llamadas = sum(c.llamadas for c in sin_fallas.values())
    assert inyectadas >= llamadas, (camino, inyectadas, llamadas)


@pytest.mark.parametrize("ruta", RUTAS, ids=lambda r: f"{sorted(r.methods)[0]} {r.path}")
def test_una_excepcion_no_atrapada_sale_como_500_generico(
    ruta, cliente_sin_relanzar, monkeypatch, caplog
):
    """El manejador global: lo que ninguna ruta atrapa —aquí, las cuatro
    dependencias que truenan al construirse, antes de entrar a la ruta— sale
    como un 500 con `ok: false`, un mensaje genérico y qué hacer. El detalle,
    entero, a la bitácora."""
    monkeypatch.setattr(modulo_app.httpx, "AsyncClient", _SinRed)

    def truena():
        raise RuntimeError(CADENA_CON_SECRETO)

    for dependencia in (obtener_almacen, obtener_almacenamiento, obtener_doyle, obtener_consultas):
        app.dependency_overrides[dependencia] = truena
    try:
        with caplog.at_level(logging.ERROR, logger="continental"):
            [metodo] = sorted(ruta.methods)
            [camino] = _caminos(ruta)[:1]
            respuesta = cliente_sin_relanzar.request(
                metodo, camino, json=_cuerpo_de(ruta), headers=FIRMA
            )
    finally:
        app.dependency_overrides.clear()

    assert SECRETO not in respuesta.text
    if respuesta.status_code == 500:
        cuerpo = respuesta.json()
        assert cuerpo["ok"] is False
        assert cuerpo["detalle"]
        assert cuerpo["que_hacer"] == que_hacer(SERVIDOR, config.cargar().a_quien_avisar)
        assert any(SECRETO in (r.exc_text or "") or r.exc_info for r in caplog.records)


def test_el_500_generico_lleva_ok_falso_para_que_la_pantalla_no_lo_lea_como_vacio(
    cliente_sin_relanzar,
):
    """Hasta el ticket 29 el 500 era `{"error": …}` sin `ok`, y `cargarPedido`
    lo leía como "el almacén no tiene ni una venta registrada"."""
    def truena():
        raise RuntimeError(CADENA_CON_SECRETO)

    app.dependency_overrides[obtener_almacen] = truena
    try:
        respuesta = cliente_sin_relanzar.get(RUTA)
    finally:
        app.dependency_overrides.clear()

    cuerpo = respuesta.json()
    assert respuesta.status_code == 500
    assert cuerpo["ok"] is False
    assert "no quiere decir que no exista" in cuerpo["frase"]
    assert "no se pudo leer" in cuerpo["frase"]


def test_un_cuerpo_invalido_contesta_en_espanol_y_sin_repetir_lo_mandado(cliente):
    """El 422 de FastAPI venía en inglés y devolvía el cuerpo tal cual, sin
    `ok` ni `detalle`. Ahora es una falla como las demás, con qué hacer."""
    respuesta = cliente.post("/api/renglon/1/capturado", json={"nada": SECRETO})
    cuerpo = respuesta.json()

    assert respuesta.status_code == 422
    assert cuerpo["ok"] is False
    assert cuerpo["que_hacer"] == que_hacer(PETICION, config.cargar().a_quien_avisar)
    assert SECRETO not in respuesta.text


#: Los módulos cuyo texto llega al navegador. `lote.py`, `verificar.py` y
#: `latido.py` escriben en la consola del servidor y en el journal, que es
#: justo a donde el detalle tiene que ir.
QUE_LLEGAN_AL_NAVEGADOR = ("web/app.py", "web/dependencias.py", "consultas.py")


@pytest.mark.parametrize("nombre", QUE_LLEGAN_AL_NAVEGADOR)
def test_la_excepcion_solo_se_usa_para_su_tipo(nombre):
    """El cinturón del recorrido, sobre el código: dentro de un `except … as X`
    de estos archivos, `X` solo aparece como `type(X)` o en una llamada a la
    bitácora. Un `str(X)`, un `f"{X}"` o un `X.args` es la cadena de conexión
    camino del navegador, aunque hoy ninguna prueba recorra esa rama."""
    fuente = (RAIZ / "src" / "continental" / nombre).read_text(encoding="utf-8")
    arbol = ast.parse(fuente)
    padres = {h: p for p in ast.walk(arbol) for h in ast.iter_child_nodes(p)}

    for manejador in (n for n in ast.walk(arbol) if isinstance(n, ast.ExceptHandler)):
        if not manejador.name:
            continue
        for nodo in ast.walk(ast.Module(body=manejador.body, type_ignores=[])):
            if not (isinstance(nodo, ast.Name) and nodo.id == manejador.name):
                continue
            padre = padres[nodo]
            permitido = isinstance(padre, ast.Call) and (
                ast.unparse(padre.func) == "type"
                or ast.unparse(padre.func).startswith("log.")
            )
            assert permitido, (
                f"{nombre}:{nodo.lineno} usa la excepción como "
                f"{ast.unparse(padre)!r}: solo su tipo viaja al navegador"
            )


# ======================================== la pantalla: el JS solo pinta


def _solo_el_script(pantalla: str) -> str:
    return pantalla.split("<script>", 1)[1]


def test_la_pantalla_no_compone_las_frases_que_afirman():
    """Las frases que afirman algo sobre las ventas o sobre una falla llegan
    hechas de Python (lección de los tickets 15 y 21)."""
    script = _solo_el_script(pantalla_completa())

    for vieja in (
        "Ese día no se vendió nada que reponer",
        "El almacén no tiene ni una venta registrada",
        "La lista no está vacía: no se pudo leer",
        "Todavía no hay ventas de las cuales reponer",
    ):
        assert vieja not in script, vieja


def test_la_pantalla_pinta_las_frases_del_servidor():
    script = _solo_el_script(pantalla_completa())

    for llave in (
        "datos.ventas",
        "datos.lista_vacia",
        "datos.avisos",
        "que_hacer",
        "precios_sin_leer",
    ):
        assert llave in script, llave


def test_sin_respuesta_del_servidor_las_frases_del_js_viven_en_un_solo_lugar():
    """Cuando `fetch` falla NO hay respuesta del servidor: ahí el JavaScript lo
    dice con sus palabras. Esas palabras están UNA vez, en `SIN_RESPUESTA`."""
    script = _solo_el_script(pantalla_completa())

    assert script.count("const SIN_RESPUESTA = ") == 1
    bloque = script.split("const SIN_RESPUESTA = ", 1)[1].split("};", 1)[0]
    for llave in ("red", "no_es_de_continental", "al_leer", "al_guardar"):
        assert llave + ":" in bloque, llave
    # "Continental no contestó. X se quedó como estaba" afirmaba lo que no se
    # sabe: la petición pudo llegar y aplicarse antes de perderse la respuesta.
    assert "se quedó como estaba" not in script
    assert "sigue como estaba" not in script
    assert "no se sabe si se guardó" in bloque.lower() or "no se sabe si" in bloque


def test_ninguna_respuesta_se_lee_con_json_a_pelo():
    """Todas las respuestas pasan por `respuestaDe`, que no truena con HTML
    (el 502 del túnel) ni con una red caída. Un `.json()` suelto fuera de ella
    es un botón que se queda apagado para siempre."""
    script = _solo_el_script(pantalla_completa())

    assert script.count(".json()") == 1, "solo dentro de respuestaDe"
    definicion = script.split("const respuestaDe = ", 1)[1].split("\n};", 1)[0]
    assert ".json()" in definicion


def test_cada_fetch_pasa_por_respuesta_de():
    script = _solo_el_script(pantalla_completa())

    assert script.count("fetch(") == script.count("respuestaDe(fetch(")


def test_las_fallas_se_distinguen_sin_depender_solo_del_color():
    """Ticket 28: un estado de falla se distingue sin depender solo del color.
    La nota de falla lleva un rótulo escrito, además del color."""
    pantalla = pantalla_completa()

    assert "rotulo" in _solo_el_script(pantalla)
    assert ".nota .rotulo" in pantalla


def test_la_pantalla_servida_trae_el_hueco_de_doyle(cliente):
    assert 'id="pedido-doyle"' in pantalla_servida(cliente)


def test_la_salud_dice_a_quien_avisar_para_cuando_luego_no_haya_respuesta(cliente_de_sesion):
    """Cuando `fetch` falla la pantalla habla sola, y aun así tiene que decir a
    quién avisarle. Lo aprende de `/api/salud` en cuanto carga: el contacto
    sigue siendo el del YAML, no uno escrito en el JavaScript."""
    cuerpo = cliente_de_sesion.get("/api/salud").json()

    assert cuerpo["a_quien_avisar"] == config.cargar().a_quien_avisar
    assert "salud.a_quien_avisar" in _solo_el_script(pantalla_completa())
