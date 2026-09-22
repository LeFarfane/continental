"""`continental-verificar.timer` / `.service` (ADR 0017): lo que se puede
revisar **sin atlas, sin ssh y sin red**.

Mismo trato que `tests/test_despliegue.py` y la sección de systemd de
`tests/test_lote.py`: se lee el **contenido de los archivos que se van a
desplegar**, nunca se instala nada y nunca se toca 192.168.100.14. Los finales
de línea (LF y no CRLF) no se revisan aquí: ya los revisa `test_compila.py`,
que camina el repo entero buscando `.sh`, `.service`, `.timer` y `.sql`.

Por qué esta unidad existe, en una frase: **`scripts/desplegar.sh` solo corre
`continental.verificar` cuando alguien despliega**, y si nadie despliega en
varios días un invariante roto se queda sin que nadie lo mire. Este timer
corre la misma verificación completa —forma + datos— **todos los días**, con
`--latido`, y avisa por su propio monitor de Kuma en vez de esperar al
próximo despliegue.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVICIO = RAIZ / "scripts" / "systemd" / "continental-verificar.service"
TIMER = RAIZ / "scripts" / "systemd" / "continental-verificar.timer"

# El peor caso de fin del lote: dispara a las 22:00 y `TimeoutStartSec=75min`
# (continental-lote.service) lo puede llevar hasta las 23:15. La verificación
# tiene que caer DESPUÉS de eso para no competir por el almacén al mismo
# tiempo, y también después del colchón de 90 min sobre la cadena de las
# 20:30 (mismo colchón que ya midió y razonó ADR 0006 para el lote).
FIN_DEL_PEOR_CASO_DEL_LOTE_MIN = 23 * 60 + 15
COLCHON_SOBRE_LA_CADENA_MIN = 20 * 60 + 30 + 90


def _texto(ruta: Path) -> str:
    return ruta.read_bytes().decode("utf-8")


def _seccion(texto: str, nombre: str) -> str:
    """El cuerpo de una sección de un `.ini`, sin las que vienen después.

    Anclada a principio de línea y no con un `index()`: los comentarios de
    esta unidad explican en prosa por qué cada llave va donde va —incluida la
    lección de Marlowe sobre StartLimit*— y un `index()` encontraría primero
    esa prosa.
    """
    encabezado = re.search(rf"^\[{nombre}\]", texto, re.MULTILINE)
    assert encabezado, f"No hay sección [{nombre}]."
    siguiente = re.search(r"^\[", texto[encabezado.end() :], re.MULTILINE)
    fin = encabezado.end() + siguiente.start() if siguiente else len(texto)
    return texto[encabezado.start() : fin]


def _llaves(seccion: str) -> dict[str, list[str]]:
    """Las llaves de una sección, ignorando los comentarios."""
    pares: dict[str, list[str]] = {}
    for linea in seccion.splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("#") or limpia.startswith("["):
            continue
        if "=" in limpia:
            llave, _, valor = limpia.partition("=")
            pares.setdefault(llave.strip(), []).append(valor.strip())
    return pares


def test_la_unidad_y_el_timer_existen_y_son_utf8():
    assert SERVICIO.exists(), "Falta scripts/systemd/continental-verificar.service."
    assert TIMER.exists(), "Falta scripts/systemd/continental-verificar.timer."
    _texto(SERVICIO)
    _texto(TIMER)


# ---------------------------------------------------------------------------
# El timer: la hora, todos los días, y qué NO se usa
# ---------------------------------------------------------------------------


def test_el_timer_dispara_todos_los_dias_y_no_solo_lun_vie():
    """A diferencia del lote, un invariante puede romperse cualquier día de la
    semana, y ninguna migración ni ningún dato depende de que la cadena de
    farmacia-data haya corrido ese día para que valga la pena mirar."""
    llaves = _llaves(_seccion(_texto(TIMER), "Timer"))
    assert len(llaves["OnCalendar"]) == 1, (
        "Con dos OnCalendar el timer dispara dos veces por día."
    )
    calendario = llaves["OnCalendar"][0]

    assert not calendario.lower().startswith(("mon", "tue", "wed", "thu", "fri", "sat", "sun")), (
        f"OnCalendar={calendario} está acotado a ciertos días. La "
        "verificación tiene que correr TODOS los días: un dato puede "
        "romperse cualquiera de ellos, no solo los que corre la cadena."
    )


def test_el_timer_dispara_despues_del_colchon_de_la_cadena_y_del_peor_caso_del_lote():
    """Las dos cuentas que justifican la hora, comprobadas por separado para
    que la prueba siga valiendo si algún día solo una de las dos manda."""
    llaves = _llaves(_seccion(_texto(TIMER), "Timer"))
    calendario = llaves["OnCalendar"][0]

    m = re.search(r"(\d{1,2}):(\d{2})(?::\d{2})?\s*$", calendario)
    assert m, f"No se pudo leer la hora de OnCalendar={calendario!r}."
    minutos_del_dia = int(m.group(1)) * 60 + int(m.group(2))

    assert minutos_del_dia > COLCHON_SOBRE_LA_CADENA_MIN, (
        f"La verificación dispara a las {m.group(0)} y el colchón sobre la "
        "cadena de las 20:30 (90 min, el mismo que mide ADR 0006 para el "
        "lote) pide caer después de las 22:00: podría leer `marts` mientras "
        "`dbt build` todavía está recreando permisos."
    )
    assert minutos_del_dia > FIN_DEL_PEOR_CASO_DEL_LOTE_MIN, (
        f"La verificación dispara a las {m.group(0)} y el lote puede seguir "
        "vivo hasta las 23:15 (22:00 + TimeoutStartSec=75min). Tienen que no "
        "coincidir."
    )


def test_el_timer_dispara_la_unidad_de_verificar():
    llaves = _llaves(_seccion(_texto(TIMER), "Timer"))
    assert llaves["Unit"] == ["continental-verificar.service"]


def test_el_timer_se_instala_en_timers_y_la_unidad_no_arranca_al_bootear():
    """El que se habilita es el timer; la unidad no lleva `[Install]`. Mismo
    trato que continental-lote.service y por la misma razón: un
    `WantedBy=multi-user.target` en el servicio lo arrancaría en cada boot."""
    assert _llaves(_seccion(_texto(TIMER), "Install"))["WantedBy"] == ["timers.target"]
    assert not re.search(r"^\[Install\]", _texto(SERVICIO), re.MULTILINE), (
        "continental-verificar.service no debe tener [Install]: quien se "
        "habilita es el timer."
    )


def test_el_timer_si_es_persistente_y_es_lo_contrario_del_lote():
    """A propósito, y al revés de `continental-lote.timer`. El lote no lleva
    `Persistent=true` porque dispararía cuatro navegadores contra portales
    ajenos en horario de mostrador (ADR 0006); esta corrida solo lee Postgres
    y manda un latido HTTP a un contenedor local -la misma clase de trabajo
    que el paso 7/7 de `desplegar.sh` ya hace a cualquier hora-, así que
    perderse un día entero de verificación por un atlas apagado a las 23:30
    es un costo real y evitable, no uno que haya que proteger."""
    llaves = _llaves(_seccion(_texto(TIMER), "Timer"))
    assert llaves.get("Persistent") == ["true"], (
        "continental-verificar.timer tiene que llevar Persistent=true: es la "
        "corrida que existe para que un día sin ella no pase inadvertido."
    )


def test_el_timer_avisa_de_que_hay_que_revisarlo_si_se_mueve_la_cadena():
    texto = _texto(TIMER)
    assert "20:15" in texto and "21:00" in texto
    assert "SI SE MUEVE LA CADENA" in texto


# ---------------------------------------------------------------------------
# La unidad: oneshot, con --latido, y SÍ reintenta (al revés del lote)
# ---------------------------------------------------------------------------


def test_la_unidad_es_de_una_corrida_y_no_un_servicio_persistente():
    llaves = _llaves(_seccion(_texto(SERVICIO), "Service"))
    assert llaves["Type"] == ["oneshot"]


def test_la_unidad_si_reintenta_y_es_lo_contrario_del_lote():
    """El lote no reintenta porque reintentar cuesta hacia afuera (cuatro
    portales de proveedor). Esta corrida solo lee Postgres y manda un latido:
    un tropiezo transitorio merece un reintento antes de esperar 24 h."""
    llaves = _llaves(_seccion(_texto(SERVICIO), "Service"))
    assert llaves["Restart"] == ["on-failure"]
    assert "RestartSec" in llaves


def test_el_limite_de_reinicios_va_en_unit_y_no_en_service():
    """La lección cara de Marlowe (ver continental-web.service), comprobada
    también aquí: en [Service], systemd IGNORA esas llaves EN SILENCIO."""
    texto = _texto(SERVICIO)
    unit = _llaves(_seccion(texto, "Unit"))
    service = _llaves(_seccion(texto, "Service"))

    for llave in ("StartLimitIntervalSec", "StartLimitBurst"):
        assert llave in unit, f"{llave} no está en [Unit]."
        assert llave not in service, (
            f"{llave} está en [Service], que es donde systemd la IGNORA EN "
            "SILENCIO (la lección de Marlowe, 2026-09-06)."
        )


def test_la_unidad_corre_verificar_con_latido_y_el_venv_de_atlas():
    llaves = _llaves(_seccion(_texto(SERVICIO), "Service"))
    ejecuta = llaves["ExecStart"][0]

    assert ejecuta.startswith("/home/eddie/proyectos/Continental/.venv/bin/python"), (
        "El venv de atlas se crea con --system-site-packages. El python del "
        "sistema no serviría."
    )
    assert ejecuta.endswith("-m continental.verificar --latido"), (
        f"ExecStart es {ejecuta!r}. Sin --latido esta corrida sería idéntica "
        "al paso 7/7 de desplegar.sh y no mandaría nada a Kuma."
    )
    assert llaves["WorkingDirectory"] == ["/home/eddie/proyectos/Continental"], (
        "En atlas el repo va PLANO, hermano de ~/proyectos/Marlowe."
    )
    assert llaves["Environment"] == [
        "PYTHONPATH=/home/eddie/proyectos/Continental/src"
    ]


def test_la_unidad_no_abre_un_navegador():
    """Regla 1 de CLAUDE.md: Continental no toca un navegador nunca. Esta
    corrida además ni siquiera habla con Doyle."""
    sin_prosa = "\n".join(
        linea
        for linea in _texto(SERVICIO).splitlines()
        if not linea.strip().startswith("#")
    )
    for prohibido in ("xvfb", "DISPLAY"):
        assert prohibido not in sin_prosa


def test_la_unidad_no_escucha_en_ningun_puerto():
    llaves = _llaves(_seccion(_texto(SERVICIO), "Service"))
    entorno = " ".join(llaves.get("Environment", []))
    assert "CONTINENTAL_HOST" not in entorno
    assert "8585" not in entorno


def test_la_unidad_depende_solo_de_docker():
    """Ni Doyle, ni Marlowe, ni el lote, ni la cadena de farmacia-data: esta
    corrida solo necesita Postgres (Docker) y Kuma por loopback."""
    llaves = _llaves(_seccion(_texto(SERVICIO), "Unit"))
    assert llaves["Requires"] == ["docker.service"]

    ataduras = " ".join(
        llaves.get("Requires", []) + llaves.get("Wants", []) + llaves.get("After", [])
    ).lower()
    for ajeno in ("marlowe", "doyle", "farmacia-diario", "continental-lote"):
        assert ajeno not in ataduras, (
            f"La unidad se ata a {ajeno}, y no debería depender de nada de eso."
        )


def test_el_timeout_es_generoso_pero_mucho_menor_que_el_del_lote():
    """Estas lecturas tardan segundos; el tope solo está para matar un
    proceso colgado, no para acotar un trabajo largo como el del lote."""
    llaves = _llaves(_seccion(_texto(SERVICIO), "Service"))
    crudo = llaves["TimeoutStartSec"][0]

    assert crudo.endswith("min"), f"TimeoutStartSec={crudo} no se lee en minutos."
    minutos = float(crudo.removesuffix("min"))
    assert 0 < minutos <= 15, (
        f"TimeoutStartSec son {minutos} min. Esta corrida no hace nada "
        "parecido al lote -no habla con proveedores externos-, así que un "
        "tope de varios minutos ya es generoso."
    )


def test_la_unidad_dice_como_instalarse():
    texto = _texto(SERVICIO)
    for esperado in (
        "systemctl daemon-reload",
        "systemd-analyze verify",
        "enable --now",
        "continental-verificar.timer",
    ):
        assert esperado in texto, f"La cabecera de la unidad no menciona {esperado}."


def test_la_unidad_apunta_al_repo_plano_de_atlas():
    texto = _texto(SERVICIO)
    assert "/proyectos/Farmacia/Continental" not in texto, (
        "Se coló la ruta anidada de la torre. En atlas los repos son hermanos."
    )
