"""Lo que del ticket 16 se puede comprobar **sin atlas, sin ssh y sin red**.

Este archivo no sale de la torre: ninguna prueba se conecta a 192.168.100.14,
ni instala una unidad, ni reinicia nada. Lo que se revisa aquí es el
**contenido de los archivos que se van a desplegar** y el **comportamiento de
`iniciar.py`**, que son las dos cosas que sí caben en una prueba y que son
justo donde estuvieron las fallas que este ticket viene a evitar:

1. **Una unidad con las llaves en la sección equivocada.** Marlowe tuvo
   `StartLimitIntervalSec` y `StartLimitBurst` en `[Service]` hasta el
   2026-09-06, donde systemd **los ignora en silencio** —lo dijo
   `systemd-analyze verify`, no una falla—. El freno contra el bucle de
   reinicios no existía y el journal no decía nada. Es una prueba de contenido
   de archivo porque el daño vive en el archivo.
2. **Un `desplegar.sh` que reinicia aunque algo haya fallado.** El 2026-09-08
   Marlowe desplegó un `app.py` que no compilaba con "pull, reinicia y ojalá".
   Aquí se comprueba que los pasos están en el orden correcto y que el script
   se detiene al primero que falla.
3. **`--servicio` buscándose otro puerto.** El túnel apunta a UN puerto fijo:
   arrancar en otro deja el servicio vivo, la unidad en `active (running)` y
   `farmacia.farfanlab.uk` devolviendo 502, sin una línea roja en ninguna
   parte.

Lo que **no** cabe aquí y queda en manos del dueño está en
`docs/despliegue-en-atlas.md`: el Public Hostname y la política de Access viven
en el dashboard de Cloudflare Zero Trust, no en un archivo de este repo.

Los finales de línea (LF y no CRLF) de `scripts/desplegar.sh` y de
`scripts/systemd/continental-web.service` **no se revisan aquí**: ya los revisa
`tests/test_compila.py`, que camina el repo buscando `.sh`, `.service`,
`.timer` y `.sql`. Hasta hoy esos dos casos se anunciaban como saltados porque
no existía ni un archivo de esa clase; con este ticket dejan de saltarse y
empiezan a revisar de verdad.
"""

from __future__ import annotations

import importlib.util
import re
import socket
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
UNIDAD = RAIZ / "scripts" / "systemd" / "continental-web.service"
DESPLEGAR = RAIZ / "scripts" / "desplegar.sh"

#: El gateway de la red Docker `borde` en atlas, **medido** el 2026-09-19 con
#: `docker network inspect borde`, y confirmado el mismo día con `ss -ltn`:
#: marlowe-web está escuchando ahí y en ningún otro lado. No es un valor
#: elegido, es uno observado, y **cambia si se recrea la red** — por eso la
#: unidad lleva escrito cómo volver a medirlo.
GATEWAY_DE_BORDE = "172.19.0.1"
PUERTO = "8585"


@pytest.fixture
def iniciar():
    """`iniciar.py` cargado como módulo, por ruta.

    No se puede `import iniciar` a secas: el archivo vive en la raíz del repo y
    lo que pytest pone en `sys.path` es `src/` (por `pyproject.toml`) y la
    carpeta de las pruebas. Cargarlo por ruta evita tocar la configuración
    global del suite para una sola prueba.

    Y es justo el archivo que hay que cargar: `iniciar.py` es lo que el
    servicio ejecuta y lo que ninguna otra prueba importa. `test_compila.py` ya
    lo compila; esto lo hace correr.
    """
    especificacion = importlib.util.spec_from_file_location("iniciar", RAIZ / "iniciar.py")
    modulo = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def puerto_ocupado():
    """Un puerto de loopback con alguien escuchando de verdad, y su número.

    Es un socket real y no un doble a propósito: lo que se está probando es una
    sonda sobre el sistema operativo, y un doble la haría contestar lo que la
    prueba quiera oír. No es red hacia afuera —`127.0.0.1`, sin conexiones—,
    así que el suite sigue corriendo sin Postgres, sin atlas y sin `.env`.

    El puerto lo elige el sistema (`bind` al 0) en vez de ser el 8585: si una
    prueba fijara el puerto de producción, correr el suite con Continental
    levantado en la torre la pondría roja sin que nada estuviera mal.
    """
    servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    servidor.bind(("127.0.0.1", 0))
    servidor.listen(1)
    yield servidor.getsockname()[1]
    servidor.close()


# ---------------------------------------------------------------------------
# `--servicio`: ni navegador, ni mudarse de puerto
# ---------------------------------------------------------------------------


def test_la_sonda_de_puerto_ve_ocupado_lo_que_esta_ocupado(iniciar, puerto_ocupado):
    """El cimiento de todo lo demás, y **estuvo roto hasta el 2026-09-19**.

    `puerto_libre` ponía `SO_REUSEADDR` en las dos plataformas, y en Windows
    esa opción permite amarrarse a un puerto donde ya hay alguien escuchando.
    Medido ese día en la torre: con un `listen()` vivo en el 8585, la sonda
    contestaba **libre**. El freno de `--servicio` pasaba de largo y uvicorn
    moría después con un `[Errno 10048]` que no explica nada. En atlas (Linux)
    el freno sí funcionaba, que es lo peor de todo: la garantía existía
    únicamente donde nadie la podía probar.

    Si alguien vuelve a poner `SO_REUSEADDR` a secas, esta prueba se pone roja
    en la torre.
    """
    assert iniciar.puerto_libre("127.0.0.1", puerto_ocupado) is False


def test_como_servicio_el_puerto_ocupado_no_arranca_en_otro(iniciar, puerto_ocupado):
    """La casilla del ticket: con el puerto ocupado NO se va a otro, se muere.

    El túnel de Cloudflare apunta a `172.19.0.1:8585` fijo. Arrancar en el 8586
    dejaría el proceso vivo, la unidad en `active (running)`, el journal limpio
    y `farmacia.farfanlab.uk` devolviendo 502. Fallar ruidoso (regla 4 de
    CLAUDE.md) aquí significa **no arrancar**.
    """
    with pytest.raises(SystemExit) as fallo:
        iniciar.decidir_puerto("127.0.0.1", puerto_ocupado, servicio=True)

    motivo = str(fallo.value)
    assert str(puerto_ocupado) in motivo
    assert "túnel" in motivo, (
        "El mensaje de salida no explica POR QUÉ no se busca otro puerto. "
        "Quien lo lea en journalctl tiene que entender que el problema es el "
        "puerto fijo del túnel, no un capricho."
    )


def test_a_mano_el_puerto_ocupado_si_se_mueve(iniciar, puerto_ocupado):
    """El otro lado del cinturón: sin `--servicio` la comodidad sigue ahí.

    Sin esta prueba, "no busca otro puerto" se podría cumplir rompiendo también
    el modo de escritorio, y nadie se enteraría hasta la próxima vez que
    alguien lanzara Continental a mano en la torre.
    """
    elegido = iniciar.decidir_puerto("127.0.0.1", puerto_ocupado, servicio=False)

    assert elegido != puerto_ocupado
    assert puerto_ocupado < elegido <= puerto_ocupado + iniciar.INTENTOS


def test_como_servicio_no_se_abre_ningun_navegador(iniciar, monkeypatch, tmp_path):
    """Regla 1 de CLAUDE.md y ADR 0001: aquí no se toca un navegador.

    Bajo systemd además no habría dónde abrirlo. Por eso la unidad **no** lleva
    `xvfb-run`, a diferencia de la de Marlowe: no es un olvido al copiarla.

    Se sustituyen `uvicorn.run` y `webbrowser.open` para que `main()` haga todo
    su trabajo sin levantar un servidor ni abrir nada.
    """
    abiertos = []
    servidos = {}
    monkeypatch.setattr(iniciar.webbrowser, "open", lambda url: abiertos.append(url))
    monkeypatch.setattr(iniciar.uvicorn, "run", lambda app, **kw: servidos.update(kw))
    monkeypatch.setattr(iniciar.sys, "argv", ["iniciar.py", "--servicio"])
    monkeypatch.setenv("CONTINENTAL_HOST", "127.0.0.1")
    monkeypatch.setattr(iniciar, "RAIZ", tmp_path)

    iniciar.main()

    assert abiertos == [], f"Se intentó abrir un navegador: {abiertos}"
    assert servidos["port"] == iniciar.PUERTO_PREFERIDO
    assert servidos["host"] == "127.0.0.1"


# ---------------------------------------------------------------------------
# En qué interfaz escucha, y que se pueda configurar sin editar código
# ---------------------------------------------------------------------------


def test_por_omision_escucha_en_loopback(iniciar, monkeypatch, tmp_path):
    """Sin nadie que diga otra cosa, `127.0.0.1`: el valor más cerrado.

    Abrirse a una interfaz más ancha tiene que ser un acto deliberado —la
    unidad de systemd lo hace con `Environment=`— y nunca lo que pasa por
    omisión en la máquina de alguien.
    """
    monkeypatch.delenv("CONTINENTAL_HOST", raising=False)

    assert iniciar.host_de_escucha(tmp_path) == "127.0.0.1"


def test_el_env_del_repo_manda_sobre_la_omision(iniciar, monkeypatch, tmp_path):
    """**La trampa que este ticket encontró y arregló.**

    `.env.example` documenta `CONTINENTAL_HOST=172.19.0.1` desde hace días,
    pero hasta el 2026-09-19 ponerlo ahí **no hacía nada**: `iniciar.py` leía
    el entorno como constante de módulo, o sea antes de que nadie llamara a
    `load_dotenv` —que vive dentro de `continental.config.cargar()` y no corre
    hasta que uvicorn importa la aplicación—. Continental se quedaba en
    `127.0.0.1` y el túnel devolvía el mismo 502 que Marlowe midió el
    2026-09-06, sin un solo mensaje de error: exactamente la falla silenciosa
    que este repo prohíbe.
    """
    monkeypatch.delenv("CONTINENTAL_HOST", raising=False)
    (tmp_path / ".env").write_text(
        f"CONTINENTAL_HOST={GATEWAY_DE_BORDE}\n", encoding="utf-8"
    )

    assert iniciar.host_de_escucha(tmp_path) == GATEWAY_DE_BORDE


def test_el_entorno_gana_sobre_el_env(iniciar, monkeypatch, tmp_path):
    """systemd manda: `load_dotenv` no pisa lo que ya está en el entorno.

    Importa que el orden sea ese y no el contrario. La unidad de systemd es la
    que sabe en qué máquina está corriendo, y un `.env` viejo copiado de otra
    parte no debe poder cambiar la interfaz a la que apunta el túnel.
    """
    (tmp_path / ".env").write_text("CONTINENTAL_HOST=10.0.0.9\n", encoding="utf-8")
    monkeypatch.setenv("CONTINENTAL_HOST", GATEWAY_DE_BORDE)

    assert iniciar.host_de_escucha(tmp_path) == GATEWAY_DE_BORDE


# ---------------------------------------------------------------------------
# La unidad de systemd
# ---------------------------------------------------------------------------


def _unidad() -> str:
    return UNIDAD.read_bytes().decode("utf-8")


def _seccion(texto: str, nombre: str) -> str:
    """El cuerpo de una sección de un `.ini`, sin las que vienen después.

    La cabecera se busca **anclada a principio de línea** y no con un
    `index()` a secas, y eso no es refinamiento: los comentarios de la unidad
    nombran `[Service]` y `[Unit]` justamente para explicar dónde va cada
    llave y por qué. Un `index()` encontraría primero el comentario y esta
    prueba estaría midiendo un pedazo de prosa.
    """
    encabezado = re.search(rf"^\[{nombre}\]", texto, re.MULTILINE)
    assert encabezado, f"La unidad no tiene sección [{nombre}]."
    siguiente = re.search(r"^\[", texto[encabezado.end() :], re.MULTILINE)
    fin = encabezado.end() + siguiente.start() if siguiente else len(texto)
    return texto[encabezado.start() : fin]


def _sin_comentarios(texto: str) -> str:
    """El archivo sin sus comentarios, para preguntar qué **hace** y no qué dice.

    La unidad habla de `xvfb-run` en prosa —para dejar escrito por qué aquí no
    va, a diferencia de la de Marlowe— y una búsqueda sobre el texto entero
    confundiría la explicación con la orden.
    """
    return "\n".join(
        linea for linea in texto.splitlines() if not linea.strip().startswith("#")
    )


def _llaves(seccion: str) -> dict[str, list[str]]:
    """Las llaves de una sección, **ignorando los comentarios**.

    Sin esto, la prueba de que `StartLimitIntervalSec` no está en `[Service]`
    se pondría roja por el comentario que explica justamente por qué no está.
    """
    pares: dict[str, list[str]] = {}
    for linea in seccion.splitlines():
        limpia = linea.strip()
        if not limpia or limpia.startswith("#") or limpia.startswith("["):
            continue
        if "=" in limpia:
            llave, _, valor = limpia.partition("=")
            pares.setdefault(llave.strip(), []).append(valor.strip())
    return pares


def test_la_unidad_existe_y_es_utf8():
    assert UNIDAD.exists(), (
        "Falta scripts/systemd/continental-web.service. Es la mitad del "
        "ticket 16 que sí vive en el repo."
    )
    _unidad()


def test_el_limite_de_reinicios_va_en_unit_y_no_en_service():
    """**La lección cara de Marlowe, convertida en prueba.**

    `StartLimitIntervalSec` y `StartLimitBurst` en `[Service]` no son un error
    de systemd: los **ignora en silencio** y sigue arrancando la unidad. Allá
    estuvieron mal hasta el 2026-09-06 y lo delató `systemd-analyze verify`, no
    una falla en producción: "Unknown key ... in section [Service], ignoring".
    O sea que el freno contra un bucle de reinicios no existía y nadie se
    habría enterado hasta ver el servicio reintentar sin parar.

    Se comprueban los dos sentidos: que estén en `[Unit]` y que **no** estén en
    `[Service]`.
    """
    texto = _unidad()
    unit = _llaves(_seccion(texto, "Unit"))
    service = _llaves(_seccion(texto, "Service"))

    for llave in ("StartLimitIntervalSec", "StartLimitBurst"):
        assert llave in unit, (
            f"{llave} no está en [Unit]. Sin ella no hay freno contra un bucle "
            "de reinicios."
        )
        assert llave not in service, (
            f"{llave} está en [Service], que es donde systemd la IGNORA EN "
            "SILENCIO. Es el error exacto que Marlowe tuvo hasta el "
            "2026-09-06. Muévela a [Unit]."
        )

    assert unit["StartLimitIntervalSec"] == ["300"]
    assert unit["StartLimitBurst"] == ["5"]
    assert service["Restart"] == ["on-failure"]


def test_la_unidad_arranca_con_servicio():
    """Sin `--servicio` no hay ni una cosa ni la otra: buscaría otro puerto y
    trataría de abrir un navegador que bajo systemd no tiene dónde abrirse."""
    ejecuta = _llaves(_seccion(_unidad(), "Service"))["ExecStart"][0]

    assert ejecuta.endswith("iniciar.py --servicio"), (
        f"ExecStart no termina en iniciar.py --servicio: {ejecuta}"
    )
    assert "/home/eddie/proyectos/Continental/.venv/bin/python" in ejecuta, (
        "ExecStart no usa el python del venv de atlas. systemd no hereda un "
        "PATH con el venv activado: la ruta va absoluta o arranca con el "
        "Python del sistema y sin las dependencias."
    )


def test_la_unidad_no_lleva_xvfb_ni_nada_de_navegador():
    """Regla 1 de CLAUDE.md y ADR 0001, del lado del despliegue.

    La unidad de Marlowe sí lleva `xvfb-run -a` porque allá se mide con
    Playwright. Copiarlo aquí sería arrastrar una dependencia de pantalla a un
    servicio que por decisión no abre un navegador nunca — y el día que eso
    haga falta, la separación del ADR 0001 se rompió y hay que reabrirla a
    propósito, no de a poquito.
    """
    ordenes = _sin_comentarios(_unidad()).lower()

    for prohibido in ("xvfb", "playwright", "display="):
        assert prohibido not in ordenes, (
            f"La unidad ejecuta o declara {prohibido}. Continental no toca un "
            "navegador (regla 1 de CLAUDE.md, ADR 0001)."
        )


def test_la_unidad_depende_de_docker_y_no_de_los_modulos():
    """Qué se declara y qué **no**, que es la mitad interesante.

    - `docker.service` es requisito duro por dos razones que van juntas: el
      almacén corre en Docker y la interfaz donde este proceso escucha —el
      gateway de la red `borde`— no existe hasta que Docker levanta esa red.
    - Doyle y Marlowe **no** son dependencias: un módulo que no contesta se
      muestra como un hueco con su motivo (regla 4), no tira la puerta entera.
      Encadenarlos convertiría "Marlowe está caído" en "la farmacia no puede
      ver su pedido". Y un `Requires=` sobre una unidad que no existe —la de
      Doyle, al 2026-09-19— haría fallar el arranque.
    """
    unit = _llaves(_seccion(_unidad(), "Unit"))

    assert unit["Requires"] == ["docker.service"]
    assert any("docker.service" in valor for valor in unit["After"])

    ataduras = " ".join(
        unit.get("Requires", []) + unit.get("Wants", []) + unit.get("After", [])
    ).lower()
    for modulo in ("marlowe", "doyle"):
        assert modulo not in ataduras, (
            f"La unidad se ata a {modulo}. Un módulo caído tiene que verse "
            "como un hueco en la pantalla, no como la puerta entera abajo "
            "(regla 4 de CLAUDE.md)."
        )


def test_la_unidad_escucha_en_el_gateway_medido_y_lo_advierte():
    """El valor medido, y la advertencia de que caduca.

    La casilla del ticket pide las dos cosas juntas, y la segunda es la que
    vale: `172.19.0.1` es lo que `docker network inspect borde` contestó el
    2026-09-19, no una constante del universo. Si alguien recrea la red, el
    gateway puede cambiar y esta unidad arranca y muere con "Cannot assign
    requested address". Quien lo lea tiene que encontrar ahí mismo cómo volver
    a medirlo.
    """
    texto = _unidad()
    service = _llaves(_seccion(texto, "Service"))

    assert f"CONTINENTAL_HOST={GATEWAY_DE_BORDE}" in service["Environment"], (
        f"La unidad no fija CONTINENTAL_HOST={GATEWAY_DE_BORDE}. Sin eso "
        "Continental escucha en loopback y el contenedor del túnel no lo "
        "alcanza: 502, igual que Marlowe el 2026-09-06."
    )
    assert "docker network inspect borde" in texto, (
        "La unidad no dice cómo volver a medir el gateway. El valor cambia si "
        "se recrea la red y quien lo lea a las 8 de la mañana no tiene por qué "
        "acordarse del comando."
    )
    # La advertencia se busca sobre el texto con los saltos de línea y las
    # almohadillas de comentario colapsados: está redactada en prosa y parte
    # de una línea a la otra, así que buscarla literal se rompería el día que
    # alguien reacomode el párrafo sin cambiarle una palabra.
    corrido = re.sub(r"[\s#]+", " ", texto).upper()
    assert "CAMBIA SI SE RECREA LA RED" in corrido, (
        "Falta la advertencia de que el valor cambia si se recrea la red. Es "
        "la mitad que de verdad importa de esta casilla: el número medido sin "
        "su fecha de caducidad se lee como una constante."
    )


def test_la_unidad_dice_como_instalarse_y_que_queda_en_el_dashboard():
    """Una unidad que no dice cómo se instala se instala mal una vez.

    Y sobre todo: tiene que decir que **después** faltan dos pasos que no se
    pueden hacer por ssh. El túnel de atlas es *remotely-managed* —corre como
    `tunnel --no-autoupdate run`, sin `config.yml` local— así que el Public
    Hostname y la política de Access viven en el dashboard de Cloudflare Zero
    Trust. Sin eso, alguien instala la unidad, ve `active (running)` y cree que
    terminó.
    """
    texto = _unidad()

    for esperado in (
        "systemctl daemon-reload",
        "systemd-analyze verify",
        "enable --now",
        "Public Hostname",
        "Access",
        "farmacia.farfanlab.uk",
        "docs/despliegue-en-atlas.md",
    ):
        assert esperado in texto, f"La cabecera de la unidad no menciona {esperado}."


def test_la_unidad_apunta_al_repo_plano_de_atlas():
    """`~/proyectos/Continental`, hermano de Marlowe, **no anidado** bajo
    Farmacia como en la torre.

    Una ruta mal copiada aquí es una unidad que no arranca y un
    `WorkingDirectory` que no existe.
    """
    texto = _unidad()
    service = _llaves(_seccion(texto, "Service"))

    assert service["WorkingDirectory"] == ["/home/eddie/proyectos/Continental"]
    assert any(
        valor == "PYTHONPATH=/home/eddie/proyectos/Continental/src"
        for valor in service["Environment"]
    )
    assert "/proyectos/Farmacia/Continental" not in texto, (
        "Se coló la ruta anidada de la torre. En atlas los repos son hermanos."
    )


# ---------------------------------------------------------------------------
# El script de despliegue
# ---------------------------------------------------------------------------


def _desplegar() -> str:
    return DESPLEGAR.read_bytes().decode("utf-8")


def test_el_script_existe_y_se_detiene_al_primer_fallo():
    """`set -euo pipefail`, y `pipefail` es el que de verdad importa.

    Sin `-o pipefail`, un `algo_que_falla | tail -1` devuelve cero: el script
    seguiría hasta reiniciar un servicio que funcionaba, con un código que no
    pasa las pruebas. Es la forma exacta en que "pull, reinicia y ojalá" se
    disfraza de script serio.
    """
    assert DESPLEGAR.exists(), "Falta scripts/desplegar.sh."
    assert "set -euo pipefail" in _desplegar()


def test_los_pasos_van_en_el_orden_del_ticket():
    """pull entonces compila entonces pruebas entonces reinicia, y verifica.

    El orden es la casilla entera: reiniciar antes de compilar y probar es
    exactamente lo que Marlowe hizo el 2026-09-08. Se comprueban las posiciones
    dentro del archivo y no que los cinco pasos existan sueltos, porque un
    script con los cinco pasos en desorden pasaría una prueba de existencia.
    """
    texto = _desplegar()

    posiciones = [texto.index(f"{n}/5") for n in range(1, 6)]
    assert posiciones == sorted(posiciones), "Los cinco pasos no están en orden."

    reinicio = texto.index("systemctl restart")
    for antes in ("ast.parse", "-m pytest"):
        assert texto.index(antes) < reinicio, (
            f"{antes} ocurre DESPUÉS del reinicio. El orden del ticket 16 es "
            "compilar y probar primero, reiniciar solo entonces."
        )


def test_el_suite_corre_con_el_venv_real_de_atlas():
    """`.venv/bin/python -m pytest`, no `pytest` a secas.

    Un `pytest` del PATH puede ser el del sistema, con otras versiones o sin
    las dependencias, y entonces el paso que decide si se reinicia está
    midiendo un entorno distinto del que va a correr.
    """
    texto = _desplegar()

    assert "PYTHON=.venv/bin/python" in texto
    assert '"$PYTHON" -m pytest' in texto


def test_el_paso_de_compilar_incluye_iniciar_py():
    """El archivo que el servicio ejecuta y que ninguna prueba importa.

    Es el hueco exacto que tumbó a Marlowe: su suite de 148 pruebas pasaba
    porque ninguna importaba el módulo de la web. Compilar solo `src/` aquí
    dejaría fuera justo el archivo del `ExecStart`.
    """
    texto = _desplegar()

    assert 'pathlib.Path("iniciar.py")' in texto
    assert 'pathlib.Path("src").rglob("*.py")' in texto


def test_el_script_comprueba_por_http_que_quedo_vivo():
    """Reiniciar sin comprobar es la mitad del trabajo.

    Y la comprobación va por la **misma interfaz y el mismo puerto** a los que
    apunta el túnel: preguntarle a `127.0.0.1` diría que todo está bien
    mientras `farmacia.farfanlab.uk` devuelve 502, que es justo la falla que
    este ticket existe para evitar.
    """
    texto = _desplegar()

    assert "/api/salud" in texto
    assert "curl" in texto
    assert GATEWAY_DE_BORDE in texto, (
        "El script no usa el mismo gateway que la unidad. Si los dos valores "
        "se separan, la comprobación de salud miente."
    )
    assert PUERTO in texto


def test_el_script_limpia_el_estado_failed_antes_de_reiniciar():
    """Si el servicio quedó en `failed` por el límite de reinicios, un
    `restart` a secas no lo levanta.

    Es el estado en el que precisamente queda un despliegue roto, o sea el que
    este script va a encontrar cuando más falta haga.
    """
    assert "reset-failed" in _desplegar()


# ---------------------------------------------------------------------------
# La firma de quién está trabajando, **en la pantalla**
# ---------------------------------------------------------------------------


def test_la_pantalla_pinta_el_correo_de_access(cliente):
    """La casilla pide que el correo **se vea**, no solo que llegue.

    `tests/test_salud.py` ya demuestra que `/api/salud` devuelve el correo del
    encabezado `Cf-Access-Authenticated-User-Email`, y `sin-identificar` cuando
    no hay ninguno. Lo que falta es lo otro: que la pantalla lo pinte. Se
    comprueba sobre el HTML servido —que es lo que el navegador recibe— porque
    este repo no ejecuta JavaScript en las pruebas y no va a empezar a abrir un
    navegador para probarse a sí mismo (regla 1 de CLAUDE.md).

    Los tres eslabones, en el mismo orden en que se rompen: que la pantalla
    pida `/api/salud`, que use `salud.quien`, y que lo ponga en una lista que
    no esté escondida detrás de un `hidden`.
    """
    html = cliente.get("/").text

    assert "/api/salud" in html
    assert "salud.quien" in html, (
        "La pantalla no usa salud.quien. El correo llegaría al servidor y no "
        "se vería en ninguna parte: la firma de quién está trabajando se "
        "perdería justo donde tiene que leerse."
    )
    assert "Entrando como" in html, (
        "Falta el rótulo que acompaña al correo. Un correo suelto en una lista "
        "de estado no dice que es la firma de quien está trabajando."
    )
    assert '<ul id="estado">' in html, "La lista de estado cambió de forma."
    assert not re.search(r'<ul id="estado"[^>]*\shidden', html), (
        "La lista de estado está hidden: el correo no se vería."
    )


def test_la_firma_nunca_se_usa_como_permiso():
    """Regla 3 de CLAUDE.md, comprobada donde se podría romper.

    El correo llega ya verificado por Cloudflare Access y sirve para saber
    **quién hizo qué**. Nunca para decidir **qué puede hacer**: quien alcance
    el puerto sin pasar por el túnel se lo inventa escribiendo un encabezado.
    La seguridad real es Access y la política del dashboard, no este código.

    La prueba mira que `quien(request)` no aparezca en una condición: un
    `if quien(request) ==` o un `in LISTA_DE_PERMITIDOS` sería justo el código
    que la regla prohíbe.
    """
    app = (RAIZ / "src" / "continental" / "web" / "app.py").read_bytes().decode("utf-8")

    prohibidos = re.findall(r"(?:if|elif|assert|while)[^\n]*\bquien\(request\)", app)
    assert not prohibidos, (
        f"quien(request) se está usando como condición: {prohibidos}. El "
        "correo de Access es una FIRMA, no un permiso (regla 3 de CLAUDE.md)."
    )
