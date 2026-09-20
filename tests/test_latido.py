"""El latido a Uptime Kuma, y las dos escrituras del final del lote (ticket 19).

Las dos últimas casillas del ticket, y la segunda es la que manda sobre la
primera: **si falla el latido, la corrida NO se aborta**. *"Marcar como rota
una corrida buena es peor que perderse un latido."*

Por qué el latido existe, en una frase: **el silencio es el modo de falla que
de verdad muerde**. Un lote que truena deja el journal en rojo y la unidad en
`failed`; un lote que *no corre* —atlas apagado a las 22:00, el timer sin
habilitar, un `daemon-reload` a medias— no deja nada, y a la mañana la lista
sin precios se ve igual que una noche en la que Doyle no contestó. Kuma es lo
único de esta casa que se queja **cuando no pasa nada**.

Y el monitor es **propio**, distinto del de la cadena de farmacia-data y del de
Marlowe, porque el ticket lo pide con su razón dentro: *"si compartieran
monitor, una noche sin lote no avisaría nada"* — la cadena de las 20:30
seguiría latiendo todas las noches y el monitor se vería verde con el lote de
las 22:00 muerto desde hace una semana.

## NINGUNA PRUEBA DE ESTE ARCHIVO MANDA UN LATIDO

Ni a la Kuma de atlas ni a ninguna otra, y no es celo: esa Kuma la comparten
Marlowe y la cadena de farmacia-data, y un latido de prueba escribiría en el
historial de un monitor que alguien mira. El borde HTTP entra por argumento
(`pedir`), igual que `dormir` y `ahora` en el lote, y el suite le pasa uno de
mentira — uno que apunta la URL, o uno que revienta, según lo que se esté
demostrando.

Tampoco se lee el `.env`: la URL entra por argumento también. El suite corre
sin Postgres, sin red y sin `.env`.
"""

from __future__ import annotations

import datetime as dt
from urllib.parse import parse_qs, urlparse

import pytest

from continental.almacen import LineaDeVenta, Producto
from continental.almacenamiento import (
    SE_ACABO_EL_TIEMPO,
    SE_INTERRUMPIO,
    SIN_LISTA,
    TERMINO,
    CorridaDelLote,
)
from continental.dobles import (
    AlmacenamientoFalso,
    AlmacenFalso,
    DoyleFalso,
    respuesta_lista,
)
from continental.latido import (
    ABAJO,
    ARRIBA,
    ESTADOS,
    LARGO_DEL_MENSAJE,
    VARIABLE_DEL_LATIDO,
    ResultadoDelLatido,
    armar_la_url,
    mandar_el_latido,
    recortar,
    url_del_latido,
)
from continental.lote import (
    CONSULTADO,
    NO_SE_PUDO,
    RenglonDelLote,
    ResumenDeLaCorrida,
    correr_el_lote,
    estado_del_latido,
    mensaje_del_latido,
)

NEGOCIO = "farmacia_01"
HOY = dt.date(2024, 3, 5)

#: Una URL de mentira con la forma de una de Kuma. **No existe y nunca se
#: pide**: el `pedir` que la recibe es un doble.
URL_FALSA = "http://kuma.invalido/api/push/TOKENDEMENTIRA"


# ------------------------------------------------------------- utilidades


def _apuntador():
    """Un `pedir` que apunta la URL en vez de pedirla. Devuelve `(pedir, vistas)`."""
    vistas: list[str] = []

    def pedir(url: str) -> None:
        vistas.append(url)

    return pedir, vistas


def _revienta(excepcion: BaseException):
    """Un `pedir` que falla. Es el Kuma caído, el token borrado, el DNS mudo."""

    def pedir(url: str) -> None:
        raise excepcion

    return pedir


def _parametros(url: str) -> dict[str, str]:
    """Los parámetros de una URL, ya decodificados."""
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def _resumen(**cambios) -> ResumenDeLaCorrida:
    base = dict(
        fecha_del_pedido=HOY,
        pedido_sugerido_id=1,
        final=TERMINO,
        segundos=600.0,
        tope_seg=3600.0,
    )
    base.update(cambios)
    return ResumenDeLaCorrida(**base)


# =========================================================================
# LA URL DEL LATIDO — pura, y con el mensaje entero dentro
# =========================================================================


def test_la_url_lleva_los_tres_parametros_que_kuma_lee():
    """`status`, `msg` y `ping`, y ninguno más.

    El `ping` va en **milisegundos** porque es lo que Kuma grafica como tiempo
    de respuesta, y aquí sirve para algo que de verdad interesa: cuánto duró la
    corrida. Una noche que empiece a tardar el doble se ve en esa gráfica antes
    de que nadie mire un journal.
    """
    url = armar_la_url(URL_FALSA, estado=ARRIBA, mensaje="todo bien", segundos=612.5)

    assert url.startswith(URL_FALSA + "?")
    assert _parametros(url) == {
        "status": "up",
        "msg": "todo bien",
        "ping": "612500",
    }


def test_el_mensaje_con_acentos_y_ampersand_viaja_codificado():
    """Se arma con `urlencode` y no pegando cadenas, y esto es por qué.

    El mensaje del lote lleva acentos —"se acabó el tiempo"— y puede llevar un
    `&` dentro. Pegado a mano, ese `&` partiría la URL en dos y Kuma guardaría
    medio mensaje con un parámetro inventado al lado.
    """
    url = armar_la_url(
        URL_FALSA, estado=ARRIBA, mensaje="se acabó el tiempo & no pasó nada"
    )

    assert "&" not in url.split("?", 1)[1].replace("&msg=", "").replace(
        "&ping=", ""
    ).replace("&status=", "")
    assert _parametros(url)["msg"] == "se acabó el tiempo & no pasó nada"


def test_los_parametros_de_la_base_se_DESCARTAN_y_no_se_arrastran():
    """**Kuma muestra su Push URL con un ejemplo pegado, y se copia con él.**

    La interfaz de Kuma enseña la URL así:

        http://.../api/push/TOKEN?status=up&msg=OK&ping=

    Eso NO es información: es un marcador de posición. Si se conserva y se le
    añaden los parámetros de verdad detrás, la petición sale con `status`,
    `msg` y `ping` **por duplicado**, y cuál gana lo decide Kuma, no nosotros.

    Pasó de verdad el 2026-09-20, en la primera corrida real del lote: la URL
    salió con `status=up&msg=OK&ping=&status=down&msg=...&ping=2458`. Esa vez
    Kuma leyó el último y el latido quedó bien, pero **una corrida que depende
    de cómo el servidor ordena duplicados no es una garantía**: el día que
    ganara el primero, el monitor diría "todo bien" sobre un lote roto, que es
    exactamente la mentira que este módulo existe para no contar.

    Hasta ese día aquí se conservaban a propósito, con `&` en vez de `?`. La
    intención era buena —no romper la URL— pero la conclusión estaba al revés:
    lo que hay que hacer con esos parámetros es **tirarlos**.
    """
    url = armar_la_url(
        URL_FALSA + "?status=up&msg=OK&ping=", estado=ABAJO, mensaje="se cortó"
    )

    assert url.count("?") == 1
    assert url.count("status=") == 1, (
        "El `status` va duplicado: el del ejemplo de Kuma sobrevivió."
    )
    assert url.startswith(URL_FALSA + "?")
    assert _parametros(url) == {
        "status": "down",
        "msg": "se cortó",
        "ping": "0",
    }


def test_un_fragmento_en_la_base_tampoco_viaja():
    """Un `#algo` al final rompería el último parámetro sin decir nada."""
    url = armar_la_url(URL_FALSA + "#seccion", estado=ARRIBA, mensaje="ok")

    assert "#" not in url
    assert _parametros(url)["status"] == "up"


@pytest.mark.parametrize("estado", ESTADOS)
def test_los_dos_estados_que_kuma_entiende_pasan(estado: str):
    assert _parametros(armar_la_url(URL_FALSA, estado=estado, mensaje="x"))[
        "status"
    ] == estado


def test_un_estado_inventado_se_rechaza_en_vez_de_mandarse():
    """Kuma **no rechaza** un estado inventado: lo ignora.

    Y eso es peor que un error, porque el monitor se queda esperando un latido
    que ya se mandó y a la hora se pone rojo por una falla que no existe. Así
    que se caza aquí, que es donde se puede decir por qué.
    """
    with pytest.raises(ValueError) as fallo:
        armar_la_url(URL_FALSA, estado="verde", mensaje="x")

    assert "verde" in str(fallo.value)
    assert "lo ignora" in str(fallo.value)


def test_el_ping_nunca_es_negativo():
    """Una duración negativa no existe, y en la gráfica de Kuma se vería raro."""
    assert _parametros(armar_la_url(URL_FALSA, estado=ARRIBA, mensaje="x",
                                    segundos=-5.0))["ping"] == "0"


def test_el_mensaje_se_recorta_en_vez_de_reventar():
    """El resumen entero son ocho renglones y en una celda de Kuma no caben.

    Se corta con puntos suspensivos y **no se levanta**: un mensaje largo no es
    una falla de la corrida, y tirarla por eso sería exactamente lo contrario
    de lo que este módulo existe para hacer.
    """
    largo = recortar("x" * 500)

    assert len(largo) == LARGO_DEL_MENSAJE
    assert largo.endswith("…")


def test_el_mensaje_se_aplana_a_una_linea():
    """Viaja en una URL y se pinta en una celda: los saltos sobran."""
    assert recortar("una\nlínea\ty  otra") == "una línea y otra"


# =========================================================================
# MANDAR EL LATIDO — la casilla: NO LEVANTA NUNCA
# =========================================================================


def test_el_latido_bueno_pide_la_url_una_vez_y_lo_dice():
    pedir, vistas = _apuntador()

    resultado = mandar_el_latido(
        estado=ARRIBA, mensaje="terminó", segundos=60.0, url=URL_FALSA, pedir=pedir
    )

    assert resultado == ResultadoDelLatido(se_mando=True, estado=ARRIBA)
    assert len(vistas) == 1
    assert _parametros(vistas[0]) == {"status": "up", "msg": "terminó", "ping": "60000"}


@pytest.mark.parametrize(
    "excepcion",
    [
        RuntimeError("kuma caído"),
        OSError("no resuelve el DNS"),
        # Y las dos que un `except Exception` dejaría pasar. El `except` de
        # `mandar_el_latido` es de `BaseException` a propósito: lo que está
        # subiendo es el final de una corrida que YA terminó bien, y dejar que
        # un Ctrl-C se lleve por delante sesenta minutos de precios bien
        # traídos por el último paso es lo que esta casilla prohíbe.
        KeyboardInterrupt(),
        SystemExit(1),
    ],
)
def test_el_latido_que_falla_no_levanta_nunca(excepcion: BaseException):
    """**La casilla del ticket, en la función donde se cumple.**

    No hay un solo `raise` hacia afuera, así que quien la llama no necesita
    envolverla en otro `try` — y si mañana alguien la llama desde otro sitio,
    hereda la garantía sin acordarse.
    """
    resultado = mandar_el_latido(
        estado=ARRIBA, mensaje="terminó", url=URL_FALSA, pedir=_revienta(excepcion)
    )

    assert resultado.se_mando is False
    assert resultado.se_omitio is False
    assert resultado.motivo == type(excepcion).__name__


def test_el_motivo_es_el_TIPO_y_nunca_el_texto():
    """Regla 5, y aquí con un filo propio: **el texto trae el token**.

    Un error de `httpx` lleva la URL completa dentro, y la URL completa ES el
    secreto del monitor. Escribirla en el journal de atlas sería publicar el
    token en el sitio donde más gente mira.
    """
    resultado = mandar_el_latido(
        estado=ARRIBA,
        mensaje="x",
        url=URL_FALSA,
        pedir=_revienta(RuntimeError(f"fallo al pedir {URL_FALSA}")),
    )

    assert resultado.motivo == "RuntimeError"
    assert "TOKENDEMENTIRA" not in resultado.motivo
    assert URL_FALSA not in resultado.motivo


def test_sin_url_no_se_intenta_nada_y_se_dice_con_todas_sus_letras():
    """Un lote que **cree** estar latiendo y no late es la falla silenciosa.

    `se_omitio` lo distingue de un latido que falló: no es lo mismo "Kuma no
    contestó" que "nadie configuró el monitor". El primero se arregla mirando
    el contenedor; el segundo, creándolo.
    """
    pedir, vistas = _apuntador()

    resultado = mandar_el_latido(estado=ARRIBA, mensaje="x", url="", pedir=pedir)

    assert resultado.se_mando is False
    assert resultado.se_omitio is True
    assert VARIABLE_DEL_LATIDO in resultado.motivo
    assert vistas == []


def test_un_estado_inventado_no_se_manda_y_tampoco_levanta():
    """El error de programación se caza, se dice entero, y no tumba la corrida.

    Entero porque el texto de este error no lleva nada de nadie: lo redacta
    este repo y nombra un estado que este repo escribió.
    """
    pedir, vistas = _apuntador()

    resultado = mandar_el_latido(
        estado="verde", mensaje="x", url=URL_FALSA, pedir=pedir
    )

    assert resultado.se_mando is False
    assert resultado.se_omitio is False
    assert vistas == []


def test_la_url_sale_del_entorno_y_no_de_una_constante(monkeypatch):
    """Y se lee **dentro de una función**, que es la falla del ADR 0005.

    Una constante de módulo se evaluaría antes de que nadie cargara el `.env`,
    y el latido quedaría apagado sin un solo mensaje de error — con Kuma
    avisando de una falla que no existe todas las noches.
    """
    monkeypatch.setenv(VARIABLE_DEL_LATIDO, "  " + URL_FALSA + "  ")
    assert url_del_latido() == URL_FALSA

    monkeypatch.setenv(VARIABLE_DEL_LATIDO, "   ")
    assert url_del_latido() is None

    monkeypatch.delenv(VARIABLE_DEL_LATIDO, raising=False)
    assert url_del_latido() is None


def test_el_nombre_de_la_variable_es_propio_y_esta_en_el_ejemplo():
    """El monitor propio empieza por una variable propia.

    Medido en atlas el 2026-09-19: farmacia-data usa `KUMA_PUSH_URL` y Marlowe
    `KUMA_PUSH_URL_MARLOWE`. Tres nombres distintos son tres URLs con tres
    tokens, que es lo que hace que sean tres monitores — y que una noche sin
    lote no se tape con el latido de la cadena de las 20:30.
    """
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    ejemplo = (raiz / ".env.example").read_text(encoding="utf-8")

    assert VARIABLE_DEL_LATIDO == "KUMA_PUSH_URL_CONTINENTAL"
    assert VARIABLE_DEL_LATIDO in ejemplo
    # Y NO está en el YAML versionado: el token es un secreto.
    assert VARIABLE_DEL_LATIDO not in (
        raiz / "config" / "continental.yml"
    ).read_text(encoding="utf-8")


# =========================================================================
# QUÉ SE LE DICE A KUMA — la tabla de casos, pura
# =========================================================================


@pytest.mark.parametrize(
    "final, esperado",
    [
        # Recorrió la lista entera.
        (TERMINO, ARRIBA),
        # **Se detuvo al tope, y eso NO es un error**: es lo que se le pide. Un
        # monitor rojo todas las noches por el tope es un monitor que nadie
        # vuelve a mirar, y entonces el silencio —lo único que de verdad
        # muerde— deja de distinguirse de nada.
        (SE_ACABO_EL_TIEMPO, ARRIBA),
        # El lote corrió y el almacén no tenía ventas. La farmacia cierra los
        # domingos: un lote que no encuentra ventas no falló.
        (SIN_LISTA, ARRIBA),
        # Esto sí es una falla, y `down` pinta el monitor en rojo AHORA, sin
        # esperar a que venza el intervalo de gracia.
        (SE_INTERRUMPIO, ABAJO),
    ],
)
def test_el_estado_del_latido_sale_del_final_de_la_corrida(final, esperado):
    assert estado_del_latido(_resumen(final=final)) == esperado


def test_el_mensaje_del_latido_dice_lo_que_cabe_en_una_celda():
    mensaje = mensaje_del_latido(_resumen(final=TERMINO, segundos=1200.0))

    assert mensaje == "terminó: 0/0 consultados, 0 con precio, 20 min"


def test_el_mensaje_del_latido_nunca_lleva_el_texto_de_una_excepcion():
    """Regla 5, y con el mismo filo: esto acaba en la base de un Kuma ajeno.

    El `detalle` que el lote redacta lleva el **tipo** de la falla y nada más
    —lo escribe `correr_el_lote`—, así que lo que este mensaje puede llevar
    está acotado desde el otro lado. Aquí se comprueba que lo que llega es eso
    y no otra cosa.
    """
    mensaje = mensaje_del_latido(
        _resumen(
            final=SE_INTERRUMPIO,
            detalle="la corrida se cortó (OperationalError) después de 7 renglón(es)",
        )
    )

    assert "OperationalError" in mensaje
    assert "postgresql://" not in mensaje


# =========================================================================
# EL CABLEADO DEL LOTE — las dos escrituras del `finally`
# =========================================================================


def _mundo(cuantos: int = 2):
    """Un almacén con `cuantos` productos vendidos hoy y un Doyle que contesta."""
    claves = [f"750100000{n:04d}" for n in range(1, cuantos + 1)]
    almacen = AlmacenFalso(
        ventas_en_memoria=[
            LineaDeVenta(
                fecha=HOY,
                producto_id=n,
                cantidad=1.0,
                importe=100.0,
                costo=80.0,
                utilidad=20.0,
            )
            for n in range(1, cuantos + 1)
        ],
        catalogo_en_memoria=[
            Producto(
                producto_id=n,
                clave=claves[n - 1],
                descripcion=f"PRODUCTO {n}",
                categoria="GRUP4",
                departamento="MED",
                anaquel="PATENTE 1",
                precio_lista_sin_iva=100.0,
                costo=80.0,
                existencia=5.0,
                esta_activo=True,
                es_granel=False,
            )
            for n in range(1, cuantos + 1)
        ],
    )
    doyle = DoyleFalso()
    for clave in claves:
        doyle.resultados_por_termino[clave] = {
            p: respuesta_lista(p, [(clave, "86.05", "40")])
            for p in ("nadro", "levic", "vicma", "quepharma")
        }
    return almacen, doyle


def _correr(almacen, almacenamiento, doyle, **extra):
    """`correr_el_lote` con el reloj inyectado y un latido que no sale a la red."""
    transcurrido = [0.0]
    extra.setdefault("latir", lambda **_: ResultadoDelLatido(se_mando=True))
    return correr_el_lote(
        almacen=almacen,
        almacenamiento=almacenamiento,
        doyle=doyle,
        negocio=NEGOCIO,
        tope_seg=extra.pop("tope_seg", 3600.0),
        tope_por_consulta_seg=120.0,
        cada_seg=1.0,
        ahora=lambda: transcurrido[0],
        dormir=lambda s: transcurrido.__setitem__(0, transcurrido[0] + s),
        **extra,
    )


def test_el_lote_guarda_su_corrida_al_terminar():
    """La fila del ADR 0007, escrita: es de donde la pantalla lo lee a la mañana.

    Lo que se guarda es **el mismo objeto que se imprime** —sale de la misma
    caja del `finally`—, así que no hay dos versiones de la misma noche.
    """
    almacen, doyle = _mundo(2)
    almacenamiento = AlmacenamientoFalso()

    resumen = _correr(almacen, almacenamiento, doyle)

    guardada = almacenamiento.ultima_corrida(NEGOCIO, resumen.pedido_sugerido_id)
    assert guardada is not None
    assert guardada.final == TERMINO
    assert guardada.en_la_lista == 2
    assert guardada.consultados == 2
    assert guardada.con_precio == 2
    assert guardada.fecha_del_pedido == HOY
    assert guardada.tope_minutos == pytest.approx(60.0)
    # `orden_cumplido` en falso, y no por descuido: `marts.dim_producto` no
    # tiene `clase_abc` (ADR 0018 de farmacia-data). El lote lo dice en vez de
    # disimularlo, y ahora además queda guardado.
    assert guardada.orden_cumplido is False


def test_el_lote_que_se_corta_por_tiempo_tambien_guarda_su_corrida():
    """**La noche que el ticket 19 existe para poder contar.**

    Sin esta fila, a la mañana los renglones que el tope no alcanzó se ven como
    "nadie los consultó" — que es verdad y es menos de lo que se sabe.
    """
    almacen, doyle = _mundo(3)
    almacenamiento = AlmacenamientoFalso()

    # Tope en cero: se acaba antes del primer renglón.
    resumen = _correr(almacen, almacenamiento, doyle, tope_seg=0.0)

    guardada = almacenamiento.ultima_corrida(NEGOCIO, resumen.pedido_sugerido_id)
    assert guardada.final == SE_ACABO_EL_TIEMPO
    assert guardada.se_corto_por_tiempo is True
    assert guardada.consultados == 0
    assert guardada.sin_alcanzar == 3


class _AlmacenamientoQueMuere(AlmacenamientoFalso):
    """El almacenamiento que se muere a la mitad de la corrida.

    `KeyboardInterrupt` y no un `Exception` cualquiera, por lo mismo que en
    `test_lote.py`: lo que se quiere probar es **el lote matado a la mitad**
    —un `systemctl stop`, un Ctrl-C, la máquina que se apaga— y no una falla
    que el código ya atrapa y convierte en hueco.
    """

    def __init__(self, morir_en: int):
        super().__init__()
        self.morir_en = morir_en
        self.guardadas = 0

    def guardar_precios(self, negocio, renglon_id, lecturas):
        self.guardadas += 1
        if self.guardadas > self.morir_en:
            raise KeyboardInterrupt("alguien mató el lote")
        return super().guardar_precios(negocio, renglon_id, lecturas)


def test_el_lote_que_se_interrumpe_deja_su_fila_y_late_en_rojo():
    """El `finally` corre aunque algo tumbe la corrida, y la excepción SIGUE.

    Tres cosas a la vez, y las tres importan:

    - la fila queda escrita **con lo que alcanzó a hacer**, no con ceros: una
      bitácora que dice "0 renglones" sobre una noche en la que se consultaron
      dos parece un dato y no lo es;
    - el latido va en `down`, que declara la corrida caída sin esperar a que
      venza el intervalo de gracia de 26 h (pasa antes por `PENDING`, porque el
      monitor lleva `Retries = 2`);
    - la excepción sube igual, porque una corrida cortada tiene que salir
      distinto de cero para que systemd la marque.
    """
    almacen, doyle = _mundo(3)
    almacenamiento = _AlmacenamientoQueMuere(morir_en=1)
    latidos: list[dict] = []

    with pytest.raises(KeyboardInterrupt):
        _correr(
            almacen,
            almacenamiento,
            doyle,
            latir=lambda **kw: (
                latidos.append(kw) or ResultadoDelLatido(se_mando=True)
            ),
        )

    assert len(almacenamiento.corridas) == 1
    fila = almacenamiento.corridas[0]
    assert fila["final"] == SE_INTERRUMPIO
    assert fila["consultados"] == 1
    assert fila["pedido_sugerido_id"] is not None
    assert "KeyboardInterrupt" in fila["detalle"]

    assert latidos[0]["estado"] == ABAJO
    assert "KeyboardInterrupt" in latidos[0]["mensaje"]


def test_el_latido_va_con_el_resumen_de_ESA_corrida():
    """Lo que Kuma recibe sale del mismo resumen, no de una segunda cuenta."""
    almacen, doyle = _mundo(2)
    almacenamiento = AlmacenamientoFalso()
    latidos: list[dict] = []

    def latir(**kw):
        latidos.append(kw)
        return ResultadoDelLatido(se_mando=True, estado=kw["estado"])

    resumen = _correr(almacen, almacenamiento, doyle, latir=latir)

    assert len(latidos) == 1
    assert latidos[0]["estado"] == ARRIBA
    assert latidos[0]["mensaje"] == mensaje_del_latido(resumen)
    assert latidos[0]["segundos"] == resumen.segundos


def test_el_latido_que_falla_NO_aborta_la_corrida():
    """**La casilla, de punta a punta y no solo dentro de `mandar_el_latido`.**

    El `pedir` que se inyecta revienta —Kuma caído, token borrado—, el latido
    se manda de verdad a través de `mandar_el_latido`, y la corrida vuelve
    entera con sus precios guardados. *"Marcar como rota una corrida buena es
    peor que perderse un latido."*
    """
    almacen, doyle = _mundo(2)
    almacenamiento = AlmacenamientoFalso()

    resumen = _correr(
        almacen,
        almacenamiento,
        doyle,
        latir=lambda **kw: mandar_el_latido(
            **kw, url=URL_FALSA, pedir=_revienta(OSError("kuma no contesta"))
        ),
    )

    assert resumen.final == TERMINO
    assert resumen.con_precio == 2
    # Y lo que se guardó sigue guardado: la corrida no se deshizo por el latido.
    assert len(almacenamiento.precios) == 8
    assert almacenamiento.ultima_corrida(NEGOCIO, resumen.pedido_sugerido_id) is not None


def test_un_latido_que_LEVANTA_tampoco_aborta_la_corrida():
    """El cinturón sobre el tirante, y no es por gusto.

    `mandar_el_latido` promete no levantar, pero quien se llama es `latir`, que
    entra por argumento. Una excepción levantada dentro de un `finally`
    mientras otra va subiendo **la sustituye**: un doble mal escrito no solo
    rompería una corrida buena, además se llevaría el motivo por el que la
    corrida se había muerto.
    """
    almacen, doyle = _mundo(2)
    almacenamiento = AlmacenamientoFalso()

    def latir(**_):
        raise RuntimeError("un latido mal escrito")

    resumen = _correr(almacen, almacenamiento, doyle, latir=latir)

    assert resumen.final == TERMINO
    assert resumen.con_precio == 2


def test_la_fila_que_no_se_puede_escribir_tampoco_aborta_la_corrida():
    """La otra escritura del `finally`, con la misma garantía (ADR 0007).

    Es el caso de atlas cuando alguien corre la migración 0004 y se olvida de
    `crear_rol.sql`: el `INSERT` rebota con "permission denied" a las 22:00 y
    sin nadie mirando. Los precios de esa noche se guardan igual; lo que se
    pierde es la frase de la pantalla.
    """
    almacen, doyle = _mundo(2)

    class SinPermiso(AlmacenamientoFalso):
        def guardar_la_corrida(self, negocio, corrida):
            raise PermissionError("permission denied for table corrida_del_lote")

    almacenamiento = SinPermiso()
    resumen = _correr(almacen, almacenamiento, doyle)

    assert resumen.final == TERMINO
    assert resumen.con_precio == 2
    assert almacenamiento.corridas == []


def test_el_lote_sin_ventas_tambien_late_y_deja_su_fila():
    """Una noche sin ventas **no es una falla**, y tiene que latir en verde.

    Si no latiera, un domingo se vería en Kuma igual que un lote que no corrió
    — y entonces el aviso de "no hubo latido" dejaría de significar algo, que
    es exactamente cómo un monitor se vuelve ruido de fondo.
    """
    almacenamiento = AlmacenamientoFalso()
    latidos: list[dict] = []

    resumen = _correr(
        AlmacenFalso(),
        almacenamiento,
        DoyleFalso(),
        latir=lambda **kw: (
            latidos.append(kw) or ResultadoDelLatido(se_mando=True)
        ),
    )

    assert resumen.final == SIN_LISTA
    assert latidos[0]["estado"] == ARRIBA
    # La fila se escribe con la lista en NULL, y por eso la llave foránea de
    # `corrida_del_lote` admite nulos: es justo la corrida que contesta "el
    # lote corrió y no encontró ventas".
    assert len(almacenamiento.corridas) == 1
    assert almacenamiento.corridas[0]["pedido_sugerido_id"] is None
    assert almacenamiento.corridas[0]["fecha_del_pedido"] is None


def test_el_resumen_se_traduce_a_la_fila_sin_recontar_nada():
    """`como_corrida` es pura y copia; no vuelve a contar.

    Dos versiones de la misma noche es lo que el ADR 0006 no quería, y la
    manera de no tenerlas es que la traducción no tenga aritmética propia.
    """
    resumen = _resumen(final=SE_ACABO_EL_TIEMPO, segundos=3601.0, tope_seg=3600.0)
    corrida = resumen.como_corrida(NEGOCIO)

    assert isinstance(corrida, CorridaDelLote)
    assert corrida.negocio == NEGOCIO
    assert corrida.final == resumen.final
    assert corrida.segundos == resumen.segundos
    assert corrida.tope_minutos == 60.0
    assert corrida.en_la_lista == resumen.en_la_lista
    assert corrida.consultados == resumen.consultados
    # Todavía no hay fila, así que no hay id ni hora de la base. `None` quiere
    # decir "esto es lo que se va a guardar"; con fecha, "esto es lo que se
    # leyó".
    assert corrida.corrida_del_lote_id == 0
    assert corrida.termino_en is None


# ------------------- la noche en que no se le pudo preguntar a nadie
#
# Decidido el 2026-09-20. Hasta hoy `estado_del_latido` decidia con UNA sola
# variable -- `final` -- y por eso una noche entera con Doyle ausente salia
# `up`: los renglones acaban en `no se pudo`, la corrida recorre la lista y
# termina, asi que `final = termino`. El monitor recien nacido habria dicho
# "todo bien" sobre un lote que no pudo preguntarle a nadie -- y ese es
# exactamente el estado de hoy, porque Doyle todavia no esta en atlas.
#
# La regla es LA MAS ESTRECHA que caza el caso: se intento y no se pudo NI UNA
# vez. Si se consulto aunque sea un renglon, la corrida hizo su trabajo y el
# `msg` ya dice cuantos huecos hubo. Se descarto `con_precio == 0 -> abajo`,
# que es mas ancha y pintaria rojo la noche en que Doyle contesta y los cuatro
# portales fallan -- eso es "sin dato", ya se ve en la pantalla con su motivo,
# y se arregla abriendo sesiones, no reparando el lote.


def _renglon_del_lote(final: str) -> RenglonDelLote:
    return RenglonDelLote(
        renglon_id=1, clave="7501000000001", descripcion="lo que sea", final=final
    )


def test_una_noche_sin_poder_preguntarle_a_nadie_pinta_el_monitor_en_rojo():
    """Doyle caido toda la noche. La lista amanece sin un solo precio."""
    resumen = _resumen(
        final=TERMINO,
        renglones=tuple(_renglon_del_lote(NO_SE_PUDO) for _ in range(3)),
    )

    assert estado_del_latido(resumen) == ABAJO


def test_si_se_consulto_aunque_sea_uno_la_corrida_hizo_su_trabajo():
    """Un solo renglon consultado basta para que el verde sea honesto.

    Que dos de tres portales fallen es el caso ordinario que el vocabulario de
    los tickets 14 y 15 llama "sin dato": se ve en la pantalla con su motivo y
    no es una falla del lote.
    """
    resumen = _resumen(
        final=TERMINO,
        renglones=(_renglon_del_lote(NO_SE_PUDO), _renglon_del_lote(CONSULTADO)),
    )

    assert estado_del_latido(resumen) == ARRIBA


def test_una_lista_que_nadie_intento_no_es_una_falla():
    """Sin renglones que intentar no hay nada que reprocharle a la corrida.

    Es el caso de `sin lista` -- la farmacia cierra los domingos -- y tambien el
    de una lista entera sin EAN, que es un problema de captura en SICAR y no del
    lote. La regla mira lo intentado, no lo logrado.
    """
    assert estado_del_latido(_resumen(final=TERMINO, renglones=())) == ARRIBA
