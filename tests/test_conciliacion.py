"""La conciliación diaria (2026-09-27): lo propuesto contra lo que de verdad se
compró.

**Por qué existe.** Medido el 2026-09-27 contra la base real: 883 renglones
creados, 0 pedidos, 0 enviados, 0 en tránsito, 0 recibidos. La encargada pide
directo en el portal de NADRO sin pasar por Continental, así que el módulo
entero de "en tránsito" y "probablemente recibido" nunca se ha disparado. El
dueño decidió seguir suponiendo que alguien va a marcar «Enviar», con
tolerancia a que se le olvide uno o dos días, deduciendo lo que pasó de las
compras que sí se dan de alta en SICAR.

**Lo que se prueba aquí.** Función pura y nada más (`conciliacion.py`): sin
Postgres, sin red, sin reloj. Las tres cosas que el ticket pide distinguir sin
confundirlas:

- "no se compró" (`MOTIVO_NO_COMPRADO`) — la ventana de tolerancia ya se
  cumplió y sigue sin aparecer una compra.
- "de éste nunca hay compras" (`MOTIVO_NUNCA_EN_COMPRAS`) — 606 de 3,429
  artículos (17.7%, medido sobre el respaldo del 2026-07-27) nunca aparecen en
  `fct_compras` y esto no se va a disparar jamás.
- "los datos no han llegado" (`MOTIVO_DATOS_NO_HAN_LLEGADO`) — el respaldo de
  SICAR llega hasta 2.5 días tarde (CLAUDE.md): un día reciente sin compras no
  es un día sin compras.

Y las dos trampas medidas que el ticket nombra con todas sus letras:
**nunca por folio**, y **`compra.fecha` no está verificada** como día de
llegada ni de captura — nada aquí depende de que sea una y no la otra, solo de
que sea posterior o igual al día de la lista.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from continental.almacen import DiaCalendario, LineaDeCompra
from continental.almacenamiento import RENGLON_ABIERTO, RENGLON_EN_TRANSITO, RenglonGuardado
from continental.almacenamiento import PrecioDeProveedor, tolerancia_dias_habiles_configurada
from continental.conciliacion import (
    MOTIVO_DATOS_NO_HAN_LLEGADO,
    MOTIVO_NO_COMPRADO,
    MOTIVO_NUNCA_EN_COMPRAS,
    calendario_desde_lista,
    comparar_precio_pagado,
    conciliar,
    fecha_limite,
    frase_de_la_coincidencia,
    frase_de_la_compra_suelta,
    frase_del_sin_comprar,
)
from continental.sugerido import Renglon

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "config" / "continental.yml"

LUNES = dt.date(2026, 9, 14)
MARTES = dt.date(2026, 9, 15)
MIERCOLES = dt.date(2026, 9, 16)  # Independencia: festivo oficial, entre semana
JUEVES = dt.date(2026, 9, 17)
VIERNES = dt.date(2026, 9, 18)
SABADO = dt.date(2026, 9, 19)
DOMINGO = dt.date(2026, 9, 20)

NADRO = 1
LEVIC = 10
VICMA = 8
OTRO_NO_DOYLE = 99  # un proveedor que SICAR conoce y Doyle no compara

PUENTE = {"nadro": NADRO, "levic": LEVIC, "vicma": VICMA}


def _calendario(dias: dict[dt.date, tuple[bool, bool]]) -> dict[dt.date, DiaCalendario]:
    """`{fecha: (es_cerrado, es_festivo_oficial)}` -> el mapa que pide `fecha_limite`."""
    return {
        fecha: DiaCalendario(fecha=fecha, es_cerrado=cerrado, es_festivo_oficial=festivo, nombre_evento=None)
        for fecha, (cerrado, festivo) in dias.items()
    }


#: El calendario de la semana del 14 al 20 de septiembre de 2026: domingo
#: cerrado y miércoles festivo oficial (Independencia), igual que la trampa
#: medida en `almacen.DiaCalendario`.
CALENDARIO_DE_LA_SEMANA = _calendario(
    {
        LUNES: (False, False),
        MARTES: (False, False),
        MIERCOLES: (False, True),
        JUEVES: (False, False),
        VIERNES: (False, False),
        SABADO: (False, False),
        DOMINGO: (True, False),
    }
)


def _renglon(producto_id: int, cantidad: int = 5) -> Renglon:
    return Renglon(
        producto_id=producto_id,
        clave=f"750100000{producto_id:04d}",
        descripcion=f"PRODUCTO {producto_id}",
        piezas_vendidas=float(cantidad),
        cantidad_propuesta=cantidad,
        esta_en_el_catalogo=True,
        existencia=0.0,
        dias_de_cobertura=None,
        clasificacion="medicamento",
    )


def _guardado(
    renglon_id: int,
    producto_id: int,
    *,
    cantidad: int = 5,
    estado: str = RENGLON_ABIERTO,
    descartado_por: str | None = None,
    descartado_en: dt.datetime | None = None,
) -> RenglonGuardado:
    return RenglonGuardado(
        renglon_id=renglon_id,
        estado=estado,
        propuesto=_renglon(producto_id, cantidad),
        descartado_por=descartado_por,
        descartado_en=descartado_en,
    )


def _compra(
    compra_id: int,
    producto_id: int,
    proveedor_id: int,
    fecha: dt.date,
    cantidad: float = 5.0,
    precio: float = 100.0,
) -> LineaDeCompra:
    return LineaDeCompra(
        compra_id=compra_id,
        producto_id=producto_id,
        proveedor_id=proveedor_id,
        fecha=fecha,
        cantidad=cantidad,
        precio_unitario_pagado=precio,
        importe_pagado=precio * cantidad,
        folio=f"F{compra_id}",
    )


# --------------------------------------------------------- fecha_limite


class TestFechaLimite:
    def test_salta_domingo(self):
        # Del viernes + 1 día hábil: el sábado cuenta (nadie dijo que la
        # farmacia no reciba en sábado), pero de viernes a domingo hay que
        # saltarse el domingo si la tolerancia pide dos.
        lunes_siguiente = dt.date(2026, 9, 21)
        assert fecha_limite(VIERNES, 1, CALENDARIO_DE_LA_SEMANA) == SABADO
        assert fecha_limite(VIERNES, 2, CALENDARIO_DE_LA_SEMANA) == lunes_siguiente  # sáb, [dom no], lun

    def test_salta_festivo_oficial_entre_semana(self):
        # El martes + 2 días hábiles: miércoles es festivo (Independencia) y
        # NO cuenta, aunque `es_cerrado` no lo vea (la trampa medida).
        assert fecha_limite(MARTES, 2, CALENDARIO_DE_LA_SEMANA) == VIERNES  # [mié no], jue, vie

    def test_un_dia_fuera_del_mapa_se_trata_como_habil(self):
        # Sin dato de un día, no se afirma "domingo" ni "festivo" (regla 4).
        lejos = dt.date(2027, 1, 1)
        assert fecha_limite(lejos, 1, {}) == lejos + dt.timedelta(days=1)

    def test_tolerancia_menor_a_uno_truena(self):
        with pytest.raises(ValueError):
            fecha_limite(LUNES, 0, CALENDARIO_DE_LA_SEMANA)

    def test_calendario_desde_lista_arma_el_mapa(self):
        dias = [
            DiaCalendario(fecha=LUNES, es_cerrado=False, es_festivo_oficial=False, nombre_evento=None),
            DiaCalendario(fecha=DOMINGO, es_cerrado=True, es_festivo_oficial=False, nombre_evento=None),
        ]
        mapa = calendario_desde_lista(dias)
        assert mapa[LUNES].es_dia_sin_lista is False
        assert mapa[DOMINGO].es_dia_sin_lista is True


# --------------------------------------------------------- conciliar: bloque 1


class TestBloque1Coincidencias:
    def test_compra_completa_es_accionable(self):
        renglon = _guardado(1, 100, cantidad=5)
        compra = _compra(9001, 100, NADRO, MARTES, cantidad=5.0)
        resultado = conciliar(
            LUNES,
            [renglon],
            [compra],
            puente=PUENTE,
            tolerancia_dias_habiles=3,
            calendario=CALENDARIO_DE_LA_SEMANA,
            ancla=VIERNES,
        )
        assert len(resultado.coincidencias) == 1
        c = resultado.coincidencias[0]
        assert c.accionable
        assert c.proveedor == "nadro"
        assert c.piezas == 5.0
        assert c.piezas_pedidas == 5
        assert c.compras_ids == (9001,)
        # NADRO y no `nadro`: la clave de Doyle viene en minúsculas y esta
        # frase la lee una persona. Hasta el 2026-09-27 esta prueba fijaba la
        # clave cruda, así que el defecto pasaba en verde.
        assert "NADRO" in frase_de_la_coincidencia(c)

    def test_dos_compras_del_mismo_proveedor_se_suman(self):
        renglon = _guardado(1, 100, cantidad=10)
        compras = [
            _compra(9001, 100, NADRO, MARTES, cantidad=6.0),
            _compra(9002, 100, NADRO, JUEVES, cantidad=4.0),
        ]
        resultado = conciliar(
            LUNES,
            [renglon],
            compras,
            puente=PUENTE,
            tolerancia_dias_habiles=3,
            calendario=CALENDARIO_DE_LA_SEMANA,
            ancla=VIERNES,
        )
        (c,) = resultado.coincidencias
        assert c.piezas == 10.0
        assert set(c.compras_ids) == {9001, 9002}

    def test_compra_de_menos_sigue_siendo_coincidencia_pero_con_menos_piezas(self):
        # El ticket 27 ya resolvió "llegó menos de lo pedido" para la
        # recepción normal; aquí solo se cuenta la evidencia — decidir
        # recibido vs. recibido parcial es del lado que escribe.
        renglon = _guardado(1, 100, cantidad=10)
        compra = _compra(9001, 100, NADRO, MARTES, cantidad=4.0)
        resultado = conciliar(
            LUNES,
            [renglon],
            [compra],
            puente=PUENTE,
            tolerancia_dias_habiles=3,
            calendario=CALENDARIO_DE_LA_SEMANA,
            ancla=VIERNES,
        )
        (c,) = resultado.coincidencias
        assert c.piezas == 4.0
        assert c.piezas_pedidas == 10

    def test_compra_de_proveedor_sin_clave_de_doyle_no_es_accionable(self):
        renglon = _guardado(1, 100, cantidad=5)
        compra = _compra(9001, 100, OTRO_NO_DOYLE, MARTES, cantidad=5.0)
        resultado = conciliar(
            LUNES,
            [renglon],
            [compra],
            puente=PUENTE,
            tolerancia_dias_habiles=3,
            calendario=CALENDARIO_DE_LA_SEMANA,
            ancla=VIERNES,
        )
        (c,) = resultado.coincidencias
        assert not c.accionable
        assert c.proveedor is None
        assert "no es uno de los cuatro" in c.motivo_no_accionable

    def test_compra_anterior_al_dia_de_la_lista_no_empareja(self):
        renglon = _guardado(1, 100, cantidad=5)
        # Antes de que la lista existiera: no puede ser su evidencia.
        compra = _compra(9001, 100, NADRO, dt.date(2026, 9, 10), cantidad=5.0)
        resultado = conciliar(
            LUNES,
            [renglon],
            [compra],
            puente=PUENTE,
            tolerancia_dias_habiles=3,
            calendario=CALENDARIO_DE_LA_SEMANA,
            ancla=VIERNES,
        )
        assert resultado.coincidencias == ()
        assert resultado.sin_comprar[0].motivo == MOTIVO_NO_COMPRADO


# --------------------------------------------------------- conciliar: bloque 2


class TestBloque2SinComprar:
    def test_nunca_en_compras_no_depende_de_la_ventana(self):
        renglon = _guardado(1, 100, cantidad=5)
        resultado = conciliar(
            LUNES,
            [renglon],
            [],
            puente=PUENTE,
            tolerancia_dias_habiles=3,
            calendario=CALENDARIO_DE_LA_SEMANA,
            ancla=LUNES,  # la ventana ni siquiera se cumplió, y no importa
            productos_con_compras=frozenset(),  # 100 no está: nunca ha aparecido
        )
        (s,) = resultado.sin_comprar
        assert s.motivo == MOTIVO_NUNCA_EN_COMPRAS
        assert "nunca ha aparecido" in frase_del_sin_comprar(s)

    def test_datos_no_han_llegado_antes_de_cumplirse_la_ventana(self):
        renglon = _guardado(1, 100, cantidad=5)
        limite = fecha_limite(LUNES, 3, CALENDARIO_DE_LA_SEMANA)
        resultado = conciliar(
            LUNES,
            [renglon],
            [],
            puente=PUENTE,
            tolerancia_dias_habiles=3,
            calendario=CALENDARIO_DE_LA_SEMANA,
            ancla=limite - dt.timedelta(days=1),
            productos_con_compras=frozenset({100}),
        )
        (s,) = resultado.sin_comprar
        assert s.motivo == MOTIVO_DATOS_NO_HAN_LLEGADO
        assert "2.5 días" in frase_del_sin_comprar(s)

    def test_no_comprado_despues_de_cumplirse_la_ventana(self):
        renglon = _guardado(1, 100, cantidad=5)
        limite = fecha_limite(LUNES, 3, CALENDARIO_DE_LA_SEMANA)
        resultado = conciliar(
            LUNES,
            [renglon],
            [],
            puente=PUENTE,
            tolerancia_dias_habiles=3,
            calendario=CALENDARIO_DE_LA_SEMANA,
            ancla=limite,
            productos_con_compras=frozenset({100}),
        )
        (s,) = resultado.sin_comprar
        assert s.motivo == MOTIVO_NO_COMPRADO
        assert "no se compró" in frase_del_sin_comprar(s).lower()

    def test_productos_con_compras_none_nunca_afirma_nunca_en_compras(self):
        renglon = _guardado(1, 100, cantidad=5)
        limite = fecha_limite(LUNES, 3, CALENDARIO_DE_LA_SEMANA)
        resultado = conciliar(
            LUNES,
            [renglon],
            [],
            puente=PUENTE,
            tolerancia_dias_habiles=3,
            calendario=CALENDARIO_DE_LA_SEMANA,
            ancla=limite,
            productos_con_compras=None,  # "no se pudo saber"
        )
        (s,) = resultado.sin_comprar
        assert s.motivo == MOTIVO_NO_COMPRADO


# --------------------------------------------------------- conciliar: bloque 3


class TestBloque3CompradoSinProponer:
    def test_nadie_lo_propuso(self):
        compra = _compra(9001, 777, NADRO, MARTES, cantidad=3.0)
        resultado = conciliar(
            LUNES,
            [],
            [compra],
            puente=PUENTE,
            tolerancia_dias_habiles=3,
            calendario=CALENDARIO_DE_LA_SEMANA,
            ancla=VIERNES,
        )
        (suelta,) = resultado.compradas_sin_proponer
        assert suelta.proveedor == "nadro"
        assert not suelta.fue_descartado
        assert not suelta.ambiguo
        assert "nadie la propuso" in frase_de_la_compra_suelta(suelta)

    def test_se_propuso_y_se_descarto_pero_se_compro(self):
        ayer = dt.datetime(2026, 9, 14, 9, 0, tzinfo=dt.UTC)
        renglon = _guardado(
            1, 100, cantidad=5, estado="descartado", descartado_por="ana@x.mx", descartado_en=ayer
        )
        compra = _compra(9001, 100, NADRO, MARTES, cantidad=5.0)
        resultado = conciliar(
            LUNES,
            [renglon],
            [compra],
            puente=PUENTE,
            tolerancia_dias_habiles=3,
            calendario=CALENDARIO_DE_LA_SEMANA,
            ancla=VIERNES,
        )
        assert resultado.coincidencias == ()
        assert resultado.sin_comprar == ()
        (suelta,) = resultado.compradas_sin_proponer
        assert suelta.fue_descartado
        assert "se descartó" in frase_de_la_compra_suelta(suelta)

    def test_ambiguo_dos_proveedores_del_mismo_producto(self):
        renglon = _guardado(1, 100, cantidad=5)
        compras = [
            _compra(9001, 100, NADRO, MARTES, cantidad=5.0),
            _compra(9002, 100, LEVIC, MIERCOLES, cantidad=5.0),
        ]
        resultado = conciliar(
            LUNES,
            [renglon],
            compras,
            puente=PUENTE,
            tolerancia_dias_habiles=3,
            calendario=CALENDARIO_DE_LA_SEMANA,
            ancla=VIERNES,
        )
        assert resultado.coincidencias == ()
        assert resultado.sin_comprar == ()
        assert len(resultado.compradas_sin_proponer) == 2
        assert all(s.ambiguo for s in resultado.compradas_sin_proponer)
        assert "más de un proveedor" in frase_de_la_compra_suelta(resultado.compradas_sin_proponer[0])

    def test_ya_usadas_no_se_vuelven_a_proponer(self):
        renglon = _guardado(1, 100, cantidad=5)
        compra = _compra(9001, 100, NADRO, MARTES, cantidad=5.0)
        resultado = conciliar(
            LUNES,
            [renglon],
            [compra],
            puente=PUENTE,
            tolerancia_dias_habiles=3,
            calendario=CALENDARIO_DE_LA_SEMANA,
            ancla=VIERNES,
            ya_usadas={9001},
            productos_con_compras=frozenset({100}),
        )
        assert resultado.coincidencias == ()
        assert resultado.compradas_sin_proponer == ()
        (s,) = resultado.sin_comprar
        # Sin la compra -ya usada en otro lado-, es como si no hubiera llegado
        # nada todavía: la ventana decide, igual que cualquier otro hueco.
        assert s.motivo in (MOTIVO_NO_COMPRADO, MOTIVO_DATOS_NO_HAN_LLEGADO)

    def test_renglon_en_transito_no_se_concilia_ni_su_compra_cae_al_bloque_3(self):
        # Ya lo atiende `recepcion.py`: conciliar encima sería la misma
        # pregunta con dos reglas.
        renglon = _guardado(1, 100, cantidad=5, estado=RENGLON_EN_TRANSITO)
        compra = _compra(9001, 100, NADRO, MARTES, cantidad=5.0)
        resultado = conciliar(
            LUNES,
            [renglon],
            [compra],
            puente=PUENTE,
            tolerancia_dias_habiles=3,
            calendario=CALENDARIO_DE_LA_SEMANA,
            ancla=VIERNES,
        )
        assert resultado.coincidencias == ()
        assert resultado.sin_comprar == ()
        assert resultado.compradas_sin_proponer == ()


# --------------------------------------------------- comparar_precio_pagado


def _lectura(proveedor: str, precio: float | None, existencia: float | None = 10.0) -> PrecioDeProveedor:
    return PrecioDeProveedor(
        renglon_id=1,
        proveedor=proveedor,
        consultado_en=dt.datetime(2026, 9, 14, 8, 0, tzinfo=dt.UTC),
        precio=None if precio is None else Decimal(str(precio)),
        existencia=None if existencia is None else Decimal(str(existencia)),
    )


class TestCompararPrecioPagado:
    def test_encuentra_uno_mas_barato(self):
        # El caso del ADR 0002: $86.05 en NADRO contra $146.38 en LEVIC, aquí
        # al revés -se pagó de más- para probar que se dice solo.
        lecturas = [_lectura("nadro", 126.25), _lectura("levic", 122.50)]
        c = comparar_precio_pagado(126.25, "nadro", lecturas)
        assert c.hubo_mas_barato
        assert c.diferencia_por_pieza == Decimal("3.75")

    def test_no_hay_hallazgo_si_ya_se_le_compro_al_mas_barato(self):
        lecturas = [_lectura("nadro", 126.25), _lectura("levic", 122.50)]
        c = comparar_precio_pagado(122.50, "levic", lecturas)
        assert not c.hubo_mas_barato

    def test_sin_lecturas_no_hay_hallazgo(self):
        c = comparar_precio_pagado(126.25, "nadro", [])
        assert not c.hubo_mas_barato
        assert c.diferencia_por_pieza is None


# ------------------------------------------- tolerancia_dias_habiles_configurada
#
# El mismo par de pruebas que `test_cancelar.py` le hace a su vecino
# `dias_en_transito_para_atrasado_configurados`: el número sale del YAML
# versionado, con su comentario, y trueña si falta o está mal escrito — nunca
# se inventa uno en silencio (regla 4).


def _yaml_con(monkeypatch, pedido: dict) -> None:
    import continental.config as config

    monkeypatch.setattr(
        config,
        "cargar",
        lambda: config.Ajustes(negocio="farmacia_01", warehouse_url=None, modulos={}, pedido=pedido),
    )


class TestToleranciaDiasHabilesConfigurada:
    def test_sale_del_yaml_con_su_comentario(self):
        texto = CONFIG.read_text(encoding="utf-8")
        assert "tolerancia_dias_habiles: 3" in texto
        assert tolerancia_dias_habiles_configurada() == 3

    def test_es_la_que_diga_el_yaml_y_no_una_escrita_en_el_codigo(self, monkeypatch):
        _yaml_con(monkeypatch, {"tolerancia_dias_habiles": 5})
        assert tolerancia_dias_habiles_configurada() == 5

    @pytest.mark.parametrize("valor", [None, "tres", 0, -1, 3.5, True, "3"])
    def test_una_tolerancia_que_falta_o_esta_mal_escrita_truena(self, monkeypatch, valor):
        _yaml_con(monkeypatch, {} if valor is None else {"tolerancia_dias_habiles": valor})
        with pytest.raises(ValueError, match="tolerancia_dias_habiles"):
            tolerancia_dias_habiles_configurada()
