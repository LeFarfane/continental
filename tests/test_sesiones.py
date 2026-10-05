"""La pestaña de Sesiones (2026-09-28): el «Inicio» de Doyle, sin creerle a `guardada`.

El `guardada` de Doyle es un marcador en disco que sobrevive a que el portal
caduque la sesión: el 2026-09-19 los cuatro decían `guardada` con las cuatro
caducadas. Así que la tarjeta cruza lo que dice Doyle con lo que el portal
contestó de verdad: la última vez que pasó del login y la última vez que mandó
al login, venga de una consulta del pedido o de una prueba (ADR 0024, ticket
02 de `sesiones-al-abrir`). Gana lo más reciente.

Ninguna prueba toca Doyle, ni Postgres, ni la red, ni duerme.
"""

from __future__ import annotations

import datetime as dt

import pytest

from conftest import pantalla_completa
from continental import config
from continental.almacenamiento import (
    RESULTADOS_DE_LA_PRUEBA,
    EvidenciaDeLaSesion,
    PruebaDeLaSesion,
    _EVIDENCIA_DE_LAS_SESIONES,
    _GUARDAR_PRUEBA_DE_SESION,
    _ULTIMAS_PRUEBAS_DE_SESION,
)
from continental.dobles import (
    respuesta_con_error,
    respuesta_con_sesion_caducada,
    respuesta_en_reconocimiento,
    respuesta_lista,
)
from continental.doyle import SesionDeProveedor
from continental.fallas import AL_GUARDAR, AL_LEER, CONFIGURACION, DOYLE, PORTAL, que_hacer
from continental.precios import (
    MOTIVOS,
    MOTIVOS_QUE_PASARON_DEL_LOGIN,
    NO_EMPAREJA,
    PORTAL_SIN_CONTESTAR,
    PRECIO_ILEGIBLE,
    SESION_CADUCADA,
    SIN_RESULTADOS,
    SIN_SELECTORES,
    SIN_TIEMPO,
    VARIOS_RESULTADOS,
    VENTANA_DE_SESION_ABIERTA,
)
from continental.sesiones import (
    CADUCADA,
    ESPERANDO,
    SIN_EVIDENCIA,
    SIN_PROBAR,
    SIN_SESION,
    SIRVIO,
    estado_de_la_sesion,
    resultado_de_la_prueba,
    resultados_de_la_prueba,
    sesiones_como_json,
)

UTC = dt.UTC
NEGOCIO = "farmacia_01"


def _sesion(proveedor="levic", estado="guardada", guardada_en="2026-09-28T10:00:00"):
    return SesionDeProveedor(proveedor=proveedor, nombre=proveedor.upper(), estado=estado,
                             guardada_en=guardada_en)


def _utc(hora: int, minuto: int = 0) -> dt.datetime:
    """El 2026-09-28 a esa hora UTC. La farmacia va seis horas atrás."""
    return dt.datetime(2026, 9, 28, hora, minuto, tzinfo=UTC)


# =========================================================================
# LAS TARJETAS
# =========================================================================


def test_una_ventana_esperando_dice_que_hacer_y_ofrece_ya_entre_y_cancelar():
    [tarjeta] = sesiones_como_json([_sesion(estado="abriendo")], {})

    assert tarjeta["etiqueta"] == ESPERANDO
    assert tarjeta["se_puede_confirmar"] is True and tarjeta["se_puede_abrir"] is False
    assert "Cancelar" in tarjeta["frase"]


def test_sin_sesion_hay_que_abrirla():
    [tarjeta] = sesiones_como_json([_sesion(estado="sin_sesion", guardada_en=None)], {})

    assert (tarjeta["etiqueta"], tarjeta["hay_que_abrirla"]) == (SIN_SESION, True)
    assert tarjeta["rotulo_de_abrir"] == "Abrir sesión"


def test_guardada_pero_el_portal_mando_al_login_despues_es_caducada():
    """Lo que pasó el 2026-09-19: Doyle decía `guardada` y el portal ya no la
    aceptaba. Guardada a las 10:00 de la farmacia (16:00 UTC), el login a las
    10:30 de la farmacia."""
    evidencia = EvidenciaDeLaSesion("levic", paso_el_login_en=_utc(16, 10), caduco_en=_utc(16, 30))

    etiqueta, frase = estado_de_la_sesion(_sesion(), evidencia)

    assert etiqueta == CADUCADA
    assert "a las 10:30" in frase and "login" in frase and "«guardada»" in frase
    assert "Una consulta la encontró caducada" in frase


def test_volver_a_guardarla_despues_del_login_no_la_deja_caducada():
    """Se abrió otra vez a las 10:00 después de que caducara a las 09:30 de la
    farmacia (15:30 UTC): no se sabe todavía si sirve. Compara el instante sin
    zona de Doyle contra uno con zona de la base: las seis horas importan."""
    evidencia = EvidenciaDeLaSesion("levic", paso_el_login_en=None, caduco_en=_utc(15, 30))

    assert estado_de_la_sesion(_sesion(), evidencia)[0] == SIN_PROBAR


def test_un_precio_despues_de_guardarla_dice_que_sirvio_sin_afirmar_que_sigue():
    evidencia = EvidenciaDeLaSesion("nadro", paso_el_login_en=_utc(16, 45), caduco_en=_utc(15, 0))

    etiqueta, frase = estado_de_la_sesion(_sesion("nadro"), evidencia)

    assert etiqueta == SIRVIO
    # Dice el origen y la hora, y no afirma que siga sirviendo.
    assert "Una consulta pasó del login" in frase
    assert "a las 10:45" in frase and "Pudo caducar" in frase


def test_guardada_sin_ninguna_consulta_despues_es_sin_probar():
    assert estado_de_la_sesion(_sesion(), None)[0] == SIN_PROBAR
    assert estado_de_la_sesion(_sesion(), EvidenciaDeLaSesion("levic", paso_el_login_en=_utc(12)))[0] == SIN_PROBAR


def test_sin_poder_leer_la_evidencia_se_dice_y_no_se_afirma_nada():
    [tarjeta] = sesiones_como_json([_sesion()], None)

    assert tarjeta["etiqueta"] == "guardada"
    assert SIN_EVIDENCIA in tarjeta["frase"]
    assert tarjeta["hay_que_abrirla"] is False


def test_mientras_un_portal_espera_los_otros_dicen_por_que_no_se_abren():
    """ADR 0018: un portal a la vez. El botón no se pinta para rebotar."""
    tarjetas = sesiones_como_json(
        [_sesion("nadro", "abriendo"), _sesion("levic", "sin_sesion", None)], {}
    )
    nadro, levic = tarjetas

    assert nadro["se_puede_confirmar"] is True
    assert levic["se_puede_abrir"] is False
    assert "NADRO" in levic["por_que_no_se_abre"]


def test_las_tarjetas_van_en_el_orden_del_glosario():
    sesiones = [_sesion(p, "sin_sesion", None) for p in ("vicma", "quepharma", "levic", "nadro")]

    assert [t["nombre"] for t in sesiones_como_json(sesiones, {})] == ["NADRO", "LEVIC", "VICMA", "QuePharma"]


# =========================================================================
# LA EVIDENCIA
# =========================================================================


def test_la_evidencia_sale_de_precios_leidos_y_del_motivo_como_parametro():
    """"Pasó del login" es un precio **o** un motivo en que el portal sí
    contestó algo suyo; los motivos van como parámetro, con su acento en
    `precios.py` y no copiado en el SQL."""
    sql = str(_EVIDENCIA_DE_LAS_SESIONES)

    assert "precio is not null or motivo = any(:pasaron)" in sql
    assert "motivo = :caducada" in sql
    assert "sesi" not in sql.lower().replace("sesiones", "")


def test_pasar_del_login_son_exactamente_los_motivos_en_que_el_portal_contesto_algo_suyo():
    """Con un precio también, y ése no lleva motivo. Los que no dicen nada de la
    sesión —no contestó, ventana abierta, no se sabe leer, no alcanzó el
    tiempo— y el login mismo quedan fuera."""
    assert set(MOTIVOS_QUE_PASARON_DEL_LOGIN) == {
        SIN_RESULTADOS, VARIOS_RESULTADOS, NO_EMPAREJA, PRECIO_ILEGIBLE,
    }
    sin_decir_nada = {
        PORTAL_SIN_CONTESTAR, VENTANA_DE_SESION_ABIERTA, SIN_SELECTORES, SIN_TIEMPO,
    }
    assert set(MOTIVOS) == set(MOTIVOS_QUE_PASARON_DEL_LOGIN) | sin_decir_nada | {SESION_CADUCADA}


def test_el_doble_calcula_la_evidencia_igual_que_el_sql(almacenamiento):
    almacenamiento.precios = [
        {"negocio": NEGOCIO, "proveedor": "levic", "consultado_en": _utc(15), "precio": 10, "motivo": None},
        {"negocio": NEGOCIO, "proveedor": "levic", "consultado_en": _utc(17), "precio": None,
         "motivo": SESION_CADUCADA},
        # `no empareja` ya cuenta: el portal contestó algo suyo (ADR 0024).
        {"negocio": NEGOCIO, "proveedor": "levic", "consultado_en": _utc(18), "precio": None,
         "motivo": NO_EMPAREJA},
        # El portal que no contestó no dice nada de la sesión.
        {"negocio": NEGOCIO, "proveedor": "levic", "consultado_en": _utc(19), "precio": None,
         "motivo": PORTAL_SIN_CONTESTAR},
        {"negocio": "otra", "proveedor": "nadro", "consultado_en": _utc(18), "precio": 5, "motivo": None},
    ]

    evidencia = almacenamiento.evidencia_de_las_sesiones(NEGOCIO)

    assert evidencia == {"levic": EvidenciaDeLaSesion("levic", paso_el_login_en=_utc(18), caduco_en=_utc(17))}


# =========================================================================
# LAS PRUEBAS GUARDADAS: el doble contra el SQL
# =========================================================================


def test_el_sql_de_las_pruebas_solo_agrega_y_la_hora_la_pone_la_base():
    insertar = " ".join(str(_GUARDAR_PRUEBA_DE_SESION).split())

    assert insertar.startswith("insert into pedidos.prueba_de_sesion (negocio, proveedor, resultado)")
    # Sin `probada_en` (el `DEFAULT now()` es el único reloj) y sin ninguna
    # sentencia que pise: ni `update`, ni `on conflict`.
    assert "probada_en" not in insertar and "on conflict" not in insertar
    assert "update" not in insertar and "delete" not in insertar


def test_el_sql_lee_la_ultima_prueba_de_cada_portal_con_desempate_por_id():
    sql = " ".join(str(_ULTIMAS_PRUEBAS_DE_SESION).split())

    assert "distinct on (proveedor)" in sql
    assert "order by proveedor, probada_en desc, prueba_de_sesion_id desc" in sql
    assert "where negocio = :negocio" in sql


def test_el_doble_guarda_y_lee_las_pruebas_igual_que_el_sql(almacenamiento):
    """La última por portal y por negocio; las demás siguen ahí (la tabla solo
    crece), y un portal que nunca se probó no aparece."""
    almacenamiento.pruebas_de_sesion = [
        {"negocio": NEGOCIO, "proveedor": "levic", "resultado": SIRVIO, "probada_en": _utc(15)},
        {"negocio": NEGOCIO, "proveedor": "levic", "resultado": CADUCADA, "probada_en": _utc(17)},
        {"negocio": NEGOCIO, "proveedor": "nadro", "resultado": SIRVIO, "probada_en": _utc(12)},
        {"negocio": "otra", "proveedor": "vicma", "resultado": SIRVIO, "probada_en": _utc(18)},
    ]

    ultimas = almacenamiento.ultimas_pruebas_de_las_sesiones(NEGOCIO)

    assert ultimas == {
        "levic": PruebaDeLaSesion("levic", CADUCADA, _utc(17)),
        "nadro": PruebaDeLaSesion("nadro", SIRVIO, _utc(12)),
    }

    guardadas = almacenamiento.guardar_pruebas_de_las_sesiones(
        NEGOCIO, [PruebaDeLaSesion("levic", SIRVIO), PruebaDeLaSesion("vicma", CADUCADA)]
    )

    assert guardadas == 2 and len(almacenamiento.pruebas_de_sesion) == 6
    nuevas = almacenamiento.ultimas_pruebas_de_las_sesiones(NEGOCIO)
    assert nuevas["levic"].resultado == SIRVIO and nuevas["vicma"].resultado == CADUCADA
    # La hora la puso el doble, como el `DEFAULT now()`: toda fila lleva la suya.
    assert all(f["probada_en"] is not None for f in almacenamiento.pruebas_de_sesion)


def test_el_doble_rechaza_lo_que_el_check_rechazaria(almacenamiento):
    """`sirvió` y `caducada` y nada más; y todo o nada: la mala no deja
    escritas las buenas."""
    assert RESULTADOS_DE_LA_PRUEBA == (SIRVIO, CADUCADA)

    with pytest.raises(ValueError, match="ck_prueba_resultado"):
        almacenamiento.guardar_pruebas_de_las_sesiones(
            NEGOCIO, [PruebaDeLaSesion("nadro", SIRVIO), PruebaDeLaSesion("levic", "dudosa")]
        )
    with pytest.raises(ValueError, match="ck_prueba_negocio"):
        almacenamiento.guardar_pruebas_de_las_sesiones("", [PruebaDeLaSesion("nadro", SIRVIO)])

    assert almacenamiento.pruebas_de_sesion == []


# =========================================================================
# LA ETIQUETA: PRUEBA CONTRA CONSULTA
# =========================================================================
#
# La sesión se guardó a las 10:00 de la farmacia (16:00 UTC). Cada caso dice
# lo último que dijo una consulta y lo último que dijo una prueba.

_GUARDADA = _utc(16)


def _con(consulta=None, prueba=None, guardada_en="2026-09-28T10:00:00"):
    """`(etiqueta, frase)` con una consulta `(paso, caduco)` y una prueba
    `(resultado, instante)`, cada una opcional."""
    evidencia = None if consulta is None else EvidenciaDeLaSesion(
        "levic", paso_el_login_en=consulta[0], caduco_en=consulta[1]
    )
    ultima = None if prueba is None else PruebaDeLaSesion("levic", prueba[0], prueba[1])
    return estado_de_la_sesion(_sesion(guardada_en=guardada_en), evidencia, prueba=ultima)


@pytest.mark.parametrize(
    ("consulta", "prueba", "etiqueta", "origen"),
    [
        # Solo una prueba.
        (None, (SIRVIO, _utc(17)), SIRVIO, "Probada"),
        (None, (CADUCADA, _utc(17)), CADUCADA, "Probada"),
        # Solo una consulta.
        ((_utc(17), None), None, SIRVIO, "Una consulta"),
        ((None, _utc(17)), None, CADUCADA, "Una consulta"),
        # Gana la más reciente, sea cual sea la fuente.
        ((_utc(17), None), (CADUCADA, _utc(18)), CADUCADA, "Probada"),
        ((None, _utc(17)), (SIRVIO, _utc(18)), SIRVIO, "Probada"),
        ((_utc(18), None), (CADUCADA, _utc(17)), SIRVIO, "Una consulta"),
        ((None, _utc(18)), (SIRVIO, _utc(17)), CADUCADA, "Una consulta"),
        # Una consulta que pasó del login y otra que no: gana la última.
        ((_utc(17), _utc(18)), (SIRVIO, _utc(16, 30)), CADUCADA, "Una consulta"),
        ((_utc(18), _utc(17)), (CADUCADA, _utc(16, 30)), SIRVIO, "Una consulta"),
        # Lo anterior a guardarla es de la sesión de antes: no cuenta.
        (None, (CADUCADA, _utc(15)), SIN_PROBAR, None),
        ((None, _utc(15)), (SIRVIO, _utc(14)), SIN_PROBAR, None),
        # Nada de nada.
        (None, None, SIN_PROBAR, None),
    ],
)
def test_gana_lo_mas_reciente_entre_la_prueba_y_la_consulta(consulta, prueba, etiqueta, origen):
    obtenida, frase = _con(consulta, prueba)

    assert obtenida == etiqueta
    if origen:
        assert frase.startswith(origen), frase


def test_una_prueba_nombra_su_origen_y_su_hora_en_la_frase():
    _, sirvio = _con(prueba=(SIRVIO, _utc(15 + 3)))
    _, caduco = _con(prueba=(CADUCADA, _utc(17, 30)))

    assert sirvio.startswith("Probada el lunes 28 de septiembre a las 12:00: pasó del login.")
    assert "Pudo caducar" in sirvio
    assert caduco.startswith("Probada el lunes 28 de septiembre a las 11:30")
    assert "login" in caduco and "«guardada»" in caduco and "ábrela otra vez" in caduco


def test_una_consulta_que_encontro_el_login_nombra_su_origen_y_su_hora():
    _, frase = _con(consulta=(None, _utc(17)))

    assert frase.startswith("Una consulta la encontró caducada el lunes 28 de septiembre a las 11:00")


def test_con_la_misma_hora_gana_que_sirvio():
    """Así lo decidía la regla de antes: un login solo gana si es posterior."""
    assert _con(consulta=(_utc(17), _utc(17)))[0] == SIRVIO
    assert _con(consulta=(_utc(17), None), prueba=(CADUCADA, _utc(17)))[0] == SIRVIO


def test_ya_entre_deja_la_tarjeta_en_guardada_sin_probar():
    """Después de «Ya entré» Doyle guarda otra vez: una prueba `caducada` de
    antes de eso ya no dice nada de la sesión nueva."""
    caducada_antes = PruebaDeLaSesion("levic", CADUCADA, _utc(15))
    sesion_nueva = _sesion(guardada_en="2026-09-28T10:05:00")  # 16:05 UTC

    assert estado_de_la_sesion(sesion_nueva, None, prueba=caducada_antes)[0] == SIN_PROBAR


def test_sin_poder_leer_la_evidencia_la_prueba_tampoco_se_afirma():
    """Una etiqueta decidida con la mitad de lo que se sabe sería afirmar de más."""
    [tarjeta] = sesiones_como_json(
        [_sesion()], None, {"levic": PruebaDeLaSesion("levic", SIRVIO, _utc(17))}
    )

    assert tarjeta["etiqueta"] == "guardada" and SIN_EVIDENCIA in tarjeta["frase"]


def test_la_tarjeta_trae_la_prueba_en_su_etiqueta():
    [tarjeta] = sesiones_como_json(
        [_sesion()], {}, {"levic": PruebaDeLaSesion("levic", CADUCADA, _utc(17))}
    )

    assert tarjeta["etiqueta"] == CADUCADA and tarjeta["hay_que_abrirla"] is True
    assert tarjeta["frase"].startswith("Probada ")


def test_la_que_espera_en_el_visor_no_se_prueba_y_las_demas_si():
    nadro, levic = sesiones_como_json([_sesion("nadro", "abriendo"), _sesion("levic")], {})

    assert nadro["se_puede_probar"] is False and levic["se_puede_probar"] is True


# -------------------------------------------------- el veredicto de la prueba


@pytest.mark.parametrize(
    ("motivo", "tiene_precio", "esperado"),
    [
        (None, True, SIRVIO),  # con precio
        (SIN_RESULTADOS, False, SIRVIO),
        (NO_EMPAREJA, False, SIRVIO),
        (VARIOS_RESULTADOS, False, SIRVIO),
        (PRECIO_ILEGIBLE, False, SIRVIO),
        (SESION_CADUCADA, False, CADUCADA),
        # Lo que no dice nada de la sesión no se guarda: no saber no es `caducada`.
        (PORTAL_SIN_CONTESTAR, False, None),
        (VENTANA_DE_SESION_ABIERTA, False, None),
        (SIN_SELECTORES, False, None),
        (SIN_TIEMPO, False, None),
    ],
)
def test_el_veredicto_de_una_lectura(motivo, tiene_precio, esperado):
    assert resultado_de_la_prueba(motivo, tiene_precio) == esperado


def test_todo_motivo_tiene_veredicto_decidido():
    """Si mañana nace un motivo nuevo, esta prueba obliga a decidir si pasó del
    login o no, en vez de que caiga en `None` sin que nadie lo vea."""
    con_veredicto = {m for m in MOTIVOS if resultado_de_la_prueba(m, False) is not None}
    assert con_veredicto == set(MOTIVOS_QUE_PASARON_DEL_LOGIN) | {SESION_CADUCADA}


def test_un_portal_pedido_que_doyle_no_menciono_sale_como_no_probado():
    """Callarlo se leería como "se probó y no hubo nada que decir"."""
    from continental.precios import LecturaDePrecio

    resultados = resultados_de_la_prueba(
        [LecturaDePrecio("nadro", motivo=NO_EMPAREJA)], pedidos=("levic", "nadro")
    )

    assert [(r.proveedor, r.resultado) for r in resultados] == [("nadro", SIRVIO), ("levic", None)]


# =========================================================================
# LAS RUTAS
# =========================================================================


def test_las_sesiones_cruzan_lo_de_doyle_con_las_consultas_guardadas(cliente, doyle, almacenamiento):
    doyle.sesiones_en_memoria = [
        {"proveedor": "levic", "estado": "guardada", "guardada_en": "2026-09-28T10:00:00"},
        {"proveedor": "nadro", "estado": "sin_sesion"},
    ]
    almacenamiento.precios = [
        {"negocio": NEGOCIO, "proveedor": "levic", "consultado_en": _utc(16, 30), "precio": None,
         "motivo": SESION_CADUCADA},
    ]

    datos = cliente.get("/api/sesiones").json()

    assert datos["ok"] is True and datos["evidencia_sin_leer"] is None
    nadro, levic = datos["sesiones"]
    assert (nadro["etiqueta"], levic["etiqueta"]) == (SIN_SESION, CADUCADA)


def test_sin_la_tabla_de_precios_las_tarjetas_se_ven_y_avisan(cliente, doyle, almacenamiento):
    doyle.sesiones_en_memoria = [{"proveedor": "levic", "estado": "guardada", "guardada_en": "2026-09-28T10:00:00"}]
    almacenamiento.falla = RuntimeError("SECRETO")

    respuesta = cliente.get("/api/sesiones")

    datos = respuesta.json()
    assert datos["ok"] is True
    assert datos["evidencia_sin_leer"]["que_hacer"] == que_hacer(AL_LEER, config.cargar().a_quien_avisar)
    assert SIN_EVIDENCIA in datos["sesiones"][0]["frase"]
    assert "SECRETO" not in respuesta.text


# -------------------------------------------------------------- probar un portal

TERMINO = "paracetamol 500"
EN_EL_PASADO = "2020-01-01T00:00:00"


def _doyle_con(doyle, **por_proveedor):
    """Doyle contesta, a la primera, lo que se diga de cada portal."""
    doyle.resultados_por_termino[TERMINO] = {
        proveedor.replace("_", ""): respuesta for proveedor, respuesta in por_proveedor.items()
    }
    doyle.sesiones_en_memoria = [
        {"proveedor": p, "estado": "guardada", "guardada_en": EN_EL_PASADO}
        for p in doyle.resultados_por_termino[TERMINO]
    ]


def _etiqueta(cliente, proveedor):
    [tarjeta] = [t for t in cliente.get("/api/sesiones").json()["sesiones"] if t["proveedor"] == proveedor]
    return tarjeta["etiqueta"]


def test_probar_un_portal_con_precio_sale_sirvio_y_se_guarda(cliente, doyle, almacenamiento):
    _doyle_con(doyle, nadro=respuesta_lista("nadro", [("PARACETAMOL 500 MG", "12.50", "40")]))

    datos = cliente.post("/api/sesiones/probar", json={"proveedores": ["nadro"]}).json()

    assert datos["ok"] is True and datos["algunos_sin_probar"] is False
    [resultado] = datos["resultados"]
    assert (resultado["proveedor"], resultado["resultado"]) == ("nadro", SIRVIO)
    assert "pasó del login" in datos["detalle"]
    # Lo que se buscó es el término configurado, solo en el portal pedido.
    assert doyle.pedidos == [TERMINO] and doyle.filtros == [("nadro",)]
    # Una fila nueva: negocio, proveedor, hora y resultado. Sin firma ni precio.
    [fila] = almacenamiento.pruebas_de_sesion
    assert set(fila) == {"negocio", "proveedor", "resultado", "probada_en"}
    assert (fila["negocio"], fila["proveedor"], fila["resultado"]) == (NEGOCIO, "nadro", SIRVIO)


def test_sin_resultados_sale_sirvio(cliente, doyle, almacenamiento):
    """El portal contestó que no tiene el producto: la sesión pasó del login."""
    _doyle_con(doyle, nadro=respuesta_lista("nadro", []))

    datos = cliente.post("/api/sesiones/probar", json={"proveedores": ["nadro"]}).json()

    assert datos["resultados"][0]["resultado"] == SIRVIO
    assert [f["resultado"] for f in almacenamiento.pruebas_de_sesion] == [SIRVIO]


def test_la_sesion_caduco_sale_caducada(cliente, doyle, almacenamiento):
    _doyle_con(doyle, levic=respuesta_con_sesion_caducada("levic"))

    datos = cliente.post("/api/sesiones/probar", json={"proveedores": ["levic"]}).json()

    assert datos["ok"] is True
    assert datos["resultados"][0]["resultado"] == CADUCADA
    assert "caducó" in datos["detalle"] and "Ábrela otra vez" in datos["detalle"]
    assert [f["resultado"] for f in almacenamiento.pruebas_de_sesion] == [CADUCADA]


def test_despues_de_probar_la_tarjeta_trae_la_etiqueta_nueva(cliente, doyle):
    _doyle_con(doyle, levic=respuesta_con_sesion_caducada("levic"))
    assert _etiqueta(cliente, "levic") == SIN_PROBAR

    cliente.post("/api/sesiones/probar", json={"proveedores": ["levic"]})

    [tarjeta] = cliente.get("/api/sesiones").json()["sesiones"]
    assert tarjeta["etiqueta"] == CADUCADA
    assert tarjeta["frase"].startswith("Probada ") and tarjeta["hay_que_abrirla"] is True


def test_sin_cuerpo_se_prueban_los_cuatro_en_una_sola_busqueda(cliente, doyle, almacenamiento):
    """La lista vacía —o ninguna— quiere decir los cuatro (la usa «Probar todas»)."""
    _doyle_con(
        doyle,
        nadro=respuesta_lista("nadro", [("A", "10.00", "1")]),
        levic=respuesta_con_sesion_caducada("levic"),
        vicma=respuesta_lista("vicma", []),
        quepharma=respuesta_lista("quepharma", [("B", "9.00", "1")]),
    )

    datos = cliente.post("/api/sesiones/probar").json()

    assert doyle.pedidos == [TERMINO] and doyle.filtros == [()]
    assert [(r["proveedor"], r["resultado"]) for r in datos["resultados"]] == [
        ("nadro", SIRVIO), ("levic", CADUCADA), ("vicma", SIRVIO), ("quepharma", SIRVIO),
    ]
    assert len(almacenamiento.pruebas_de_sesion) == 4


def test_un_portal_que_no_contesto_no_guarda_nada_y_los_demas_si(cliente, doyle, almacenamiento):
    _doyle_con(
        doyle,
        nadro=respuesta_lista("nadro", [("A", "10.00", "1")]),
        vicma=respuesta_con_error("vicma", "Timeout 30000ms exceeded"),
    )

    datos = cliente.post("/api/sesiones/probar").json()

    assert datos["ok"] is True and datos["algunos_sin_probar"] is True
    assert [(r["proveedor"], r["resultado"]) for r in datos["resultados"]] == [
        ("nadro", SIRVIO), ("vicma", None),
    ]
    assert "VICMA: no se pudo probar" in datos["detalle"]
    assert [f["proveedor"] for f in almacenamiento.pruebas_de_sesion] == ["nadro"]


def test_un_portal_que_no_contesto_deja_su_etiqueta_como_estaba(cliente, doyle, almacenamiento):
    """No saber no es lo mismo que `caducada`: la tarjeta no cambia, y la
    respuesta es una falla con su qué hacer, para la nota fija."""
    _doyle_con(doyle, vicma=respuesta_con_error("vicma", "Timeout 30000ms exceeded"))
    antes = _etiqueta(cliente, "vicma")

    datos = cliente.post("/api/sesiones/probar", json={"proveedores": ["vicma"]}).json()

    assert datos["ok"] is False
    assert datos["que_hacer"] == que_hacer(PORTAL, config.cargar().a_quien_avisar)
    assert "VICMA: no se pudo probar" in datos["detalle"]
    assert almacenamiento.pruebas_de_sesion == []
    assert _etiqueta(cliente, "vicma") == antes == SIN_PROBAR


def test_un_portal_que_no_se_sabe_leer_no_guarda_nada(cliente, doyle, almacenamiento):
    _doyle_con(doyle, vicma=respuesta_en_reconocimiento("vicma"))

    datos = cliente.post("/api/sesiones/probar", json={"proveedores": ["vicma"]}).json()

    assert datos["ok"] is False and almacenamiento.pruebas_de_sesion == []


def test_con_doyle_caido_no_se_escribe_nada_y_la_etiqueta_se_queda(cliente, doyle, almacenamiento):
    _doyle_con(doyle, levic=respuesta_con_sesion_caducada("levic"))
    cliente.post("/api/sesiones/probar", json={"proveedores": ["levic"]})
    assert _etiqueta(cliente, "levic") == CADUCADA
    [una] = almacenamiento.pruebas_de_sesion
    doyle.falla = RuntimeError("SECRETO postgresql://usuario:clave@host/db")

    respuesta = cliente.post("/api/sesiones/probar", json={"proveedores": ["levic"]})
    datos = respuesta.json()

    assert datos["ok"] is False
    assert datos["que_hacer"] == que_hacer(DOYLE, config.cargar().a_quien_avisar)
    assert "RuntimeError" in datos["detalle"]
    assert "SECRETO" not in respuesta.text and "usuario:clave" not in respuesta.text  # regla 5
    assert almacenamiento.pruebas_de_sesion == [una]
    doyle.falla = None
    assert _etiqueta(cliente, "levic") == CADUCADA


def test_si_no_se_pudo_guardar_se_dice_y_no_hay_etiqueta_nueva(cliente, doyle, almacenamiento):
    _doyle_con(doyle, levic=respuesta_con_sesion_caducada("levic"))
    almacenamiento.falla = RuntimeError("SECRETO")

    respuesta = cliente.post("/api/sesiones/probar", json={"proveedores": ["levic"]})
    datos = respuesta.json()

    assert datos["ok"] is False
    assert datos["que_hacer"] == que_hacer(AL_GUARDAR, config.cargar().a_quien_avisar)
    assert "SECRETO" not in respuesta.text
    almacenamiento.falla = None
    assert almacenamiento.pruebas_de_sesion == [] and _etiqueta(cliente, "levic") == SIN_PROBAR


def test_sin_termino_de_prueba_no_se_busca_otra_cosa(cliente, doyle, monkeypatch):
    """Se niega, ruidosamente, y no le pide nada a Doyle (ADR 0024, decisión 4)."""
    monkeypatch.setattr("continental.web.app.termino_de_prueba_configurado", lambda: None)

    datos = cliente.post("/api/sesiones/probar", json={"proveedores": ["nadro"]}).json()

    assert datos["ok"] is False and "termino_de_prueba" in datos["detalle"]
    assert datos["que_hacer"] == que_hacer(CONFIGURACION, config.cargar().a_quien_avisar)
    assert doyle.pedidos == []


def test_un_proveedor_que_no_existe_se_rechaza_sin_buscar(cliente, doyle):
    respuesta = cliente.post("/api/sesiones/probar", json={"proveedores": ["inventado"]})

    assert respuesta.status_code == 400 and respuesta.json()["ok"] is False
    assert doyle.pedidos == []


def test_una_prueba_posterior_le_gana_a_una_consulta(cliente, doyle, almacenamiento):
    """La consulta encontró el login ayer; hoy una prueba pasó del login."""
    _doyle_con(doyle, levic=respuesta_lista("levic", []))
    almacenamiento.precios = [
        {"negocio": NEGOCIO, "proveedor": "levic", "consultado_en": dt.datetime(2020, 6, 1, tzinfo=UTC),
         "precio": None, "motivo": SESION_CADUCADA},
    ]
    assert _etiqueta(cliente, "levic") == CADUCADA

    cliente.post("/api/sesiones/probar", json={"proveedores": ["levic"]})

    assert _etiqueta(cliente, "levic") == SIRVIO


def test_una_consulta_posterior_le_gana_a_la_prueba(cliente, doyle, almacenamiento):
    """Al revés: la prueba pasó del login y después una consulta del pedido
    encontró el login. Se ve el `caducada`, y dice que lo encontró una consulta."""
    _doyle_con(doyle, levic=respuesta_lista("levic", []))
    cliente.post("/api/sesiones/probar", json={"proveedores": ["levic"]})
    assert _etiqueta(cliente, "levic") == SIRVIO
    almacenamiento.precios = [
        {"negocio": NEGOCIO, "proveedor": "levic",
         "consultado_en": dt.datetime.now(UTC) + dt.timedelta(hours=1),
         "precio": None, "motivo": SESION_CADUCADA},
    ]

    [tarjeta] = cliente.get("/api/sesiones").json()["sesiones"]

    assert tarjeta["etiqueta"] == CADUCADA
    assert tarjeta["frase"].startswith("Una consulta la encontró caducada")


def test_ya_entre_no_lanza_ninguna_prueba(cliente, doyle):
    doyle.sesiones_en_memoria = [{"proveedor": "nadro"}]
    cliente.post("/api/sesion/nadro/abrir")

    cliente.post("/api/sesion/nadro/confirmar")

    assert doyle.pedidos == []


def test_las_pruebas_sin_leer_se_dicen_y_no_se_afirma_nada(cliente, doyle, almacenamiento):
    doyle.sesiones_en_memoria = [{"proveedor": "levic", "estado": "guardada", "guardada_en": EN_EL_PASADO}]
    almacenamiento.falla = RuntimeError("SECRETO")

    respuesta = cliente.get("/api/sesiones")

    datos = respuesta.json()
    assert datos["evidencia_sin_leer"]["que_hacer"]
    assert "SECRETO" not in respuesta.text
    assert SIN_EVIDENCIA in datos["sesiones"][0]["frase"]


def test_doyle_caido_es_un_hueco_con_que_hacer(cliente, doyle):
    doyle.falla = RuntimeError("SECRETO")

    respuesta = cliente.get("/api/sesiones")

    assert respuesta.json()["ok"] is False
    assert respuesta.json()["que_hacer"] == que_hacer(DOYLE, config.cargar().a_quien_avisar)
    assert "SECRETO" not in respuesta.text


def test_cancelar_cierra_la_ventana_y_suelta_el_candado(cliente, doyle):
    """La salida que el ADR 0018 dejó prevista: una ventana abandonada ya no
    bloquea a los otros tres portales."""
    doyle.sesiones_en_memoria = [{"proveedor": p} for p in ("nadro", "levic")]
    assert cliente.post("/api/sesion/nadro/abrir").json()["ok"] is True
    assert cliente.post("/api/sesion/levic/abrir").json()["ok"] is False  # el candado

    cancelada = cliente.post("/api/sesion/nadro/cancelar").json()

    assert cancelada["ok"] is True and doyle.sesiones_canceladas == ["nadro"]
    assert cliente.post("/api/sesion/levic/abrir").json()["ok"] is True


def test_cancelar_sin_ventana_dice_que_hacer(cliente, doyle):
    datos = cliente.post("/api/sesion/nadro/cancelar").json()

    assert datos["ok"] is False and datos["que_hacer"]


# =========================================================================
# LA PANTALLA
# =========================================================================


def _script() -> str:
    return pantalla_completa().split("<script>", 1)[1]


def test_las_sesiones_se_leen_al_abrir_su_pestana():
    """Una pregunta a Doyle que solo hace falta cuando alguien las va a mirar."""
    assert "if (elegida === 'sesiones') cargarSesiones();" in _script()


def test_las_tarjetas_pintan_lo_que_decide_el_servidor():
    script = _script()

    for llave in ("s.etiqueta", "s.frase", "s.se_puede_abrir", "s.por_que_no_se_abre",
                  "s.se_puede_confirmar", "s.rotulo_de_abrir"):
        assert llave in script, llave


@pytest.mark.parametrize("paso", ["abrirSesion", "confirmarSesion", "cancelarSesion"])
def test_cada_paso_vuelve_a_pintar_las_tarjetas(paso):
    # Desde el ticket 05 la tarjeta es de la función compartida: escribe en la
    # nota de su sitio y avisa a quien se le pasó (la pestaña y la ventana).
    assert f"{paso}(s, b, sitio.accion, alTerminar)" in _script()


def test_la_tarjeta_ofrece_probar_con_la_misma_firma_que_los_otros_pasos():
    """El botón está en `tarjetaDeSesion`, la única que pinta, así que sale en la
    pestaña y en la ventana; y al terminar repinta sin recargar la página."""
    script = _script()

    assert "probarSesion(s, b, sitio.accion, alTerminar)" in script
    assert "s.se_puede_probar" in script
    assert "'/api/sesiones/probar'" in script


def test_la_pantalla_dice_donde_se_teclea_la_contrasena():
    """Nunca en Continental: en el portal, dentro del visor (ADR 0001 de Doyle)."""
    assert "nunca en esta página" in pantalla_completa()
