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
import os
import re
import shutil
import socket
import subprocess
from pathlib import Path

import pytest
from conftest import pantalla_servida

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


def test_el_paso_uno_avisa_si_otra_rama_remota_va_adelante():
    """`Already up to date` puede ser cierto y engañar al mismo tiempo.

    **Pasó el 2026-09-20.** Atlas estaba en `main` y todo el trabajo iba en
    `pedido-sugerido`. `git pull` bajó los objetos, movió
    `origin/pedido-sugerido`… y contestó *Already up to date*, que era cierto
    para `main`. Los seis pasos salieron **verdes sobre código de antier**, el
    servicio se reinició, el paso 5 contestó y el 6 pidió un cambio que ya
    estaba hecho y empujado. Nada estaba roto y nada era verdad.

    Lo único que lo delataba era el commit que el paso 1 imprime, que es
    exactamente la línea que se lee de reojo.

    Se avisa y **no se falla**, y esa parte también es la decisión: desplegar
    `main` mientras una rama de trabajo va adelante es lo normal a media
    semana. Lo que no puede pasar es que no se diga.
    """
    texto = _desplegar()

    assert "rev-parse --abbrev-ref HEAD" in texto, (
        "El paso 1 no dice en qué RAMA está. Con el commit solo, desplegar la "
        "rama equivocada se ve idéntico a desplegar la correcta."
    )
    assert "refs/remotes/origin" in texto and "rev-list --count" in texto, (
        "Falta el aviso de ramas remotas por delante de lo que se despliega. "
        "Sin él, `git pull` puede contestar 'Already up to date' con razón y "
        "el despliegue entero salir verde sobre código viejo."
    )
    assert "exit" not in texto[texto.index("refs/remotes/origin"):][:600], (
        "El aviso de ramas adelantadas no puede detener el despliegue: "
        "desplegar `main` mientras una rama de trabajo va adelante es "
        "legítimo. Avisa y sigue."
    )


def test_el_script_esta_marcado_ejecutable_en_git():
    """El modo `100755`, que es de lo que git se acuerda y el disco de Windows no.

    **Nunca lo estuvo, y eso explica todo lo demás.** `CLAUDE.md` y
    `docs/despliegue-en-atlas.md` llevan desde el principio diciendo que se
    despliega con `~/proyectos/Continental/scripts/desplegar.sh`, y en atlas
    ese comando contesta `Permission denied` porque el archivo se subió con
    modo `100644`. En la torre no se nota: Windows no tiene bit de ejecución y
    `core.filemode` está en `false`, así que no hay nada que git pueda notar
    solo.

    Lo caro no fue el `Permission denied` —eso se ve— sino la salida que
    provoca: quien lo recibe prueba `. desplegar.sh`, que **sí** arranca. Y ahí
    empieza la cadena del 2026-09-20 que tiró la sesión de ssh y culpó al
    remoto. El freno contra ser importado, que está una prueba más abajo, fue
    la cura del síntoma; esto es la causa.

    Se comprueba contra el índice de git y no con `os.access`, porque en la
    torre ese permiso no existe: lo único que viaja a atlas es el modo que git
    guardó. Si vuelve a caer a `100644`, se arregla sin tocar el contenido:

        git update-index --chmod=+x scripts/desplegar.sh
    """
    salida = subprocess.run(
        ["git", "ls-files", "-s", "--", "scripts/desplegar.sh"],
        cwd=RAIZ, capture_output=True, text=True,
    )
    if salida.returncode != 0 or not salida.stdout.strip():
        pytest.skip("sin git o sin índice: no hay modo que comprobar")

    modo = salida.stdout.split()[0]
    assert modo == "100755", (
        f"scripts/desplegar.sh está en git como {modo} y tiene que ser 100755. "
        "Sin el bit de ejecución, el comando que documentan CLAUDE.md y "
        "docs/despliegue-en-atlas.md contesta 'Permission denied' en atlas, y "
        "quien lo reciba va a probar `. desplegar.sh`, que es peor. Se arregla "
        "sin tocar el contenido:\n\n"
        "    git update-index --chmod=+x scripts/desplegar.sh"
    )


def test_el_script_no_se_deja_importar_ni_se_ubica_por_dolar_cero():
    """Un `. desplegar.sh` no puede tumbarte la sesión ni mentir sobre por qué.

    **Pasó el 2026-09-20**, estando dentro de `scripts/`, que es justo donde da
    más natural escribirlo. La cadena completa, porque cada eslabón es
    invisible por su cuenta:

    1. `. desplegar.sh` **importa** el script en el shell de la sesión en vez
       de ejecutarlo, así que `$0` no vale la ruta del script: vale `-bash`.
    2. `dirname "$0"` recibe entonces una opción en vez de una ruta y contesta
       *invalid option -- 'b'*. La sustitución queda **vacía**.
    3. `cd "/.."` aterriza en `/` **sin fallar**, que es lo que mata el
       `set -e`: no hay error que detener.
    4. `git` en `/` contesta *not a git repository*... y el script culpaba al
       remoto, que existe desde el 2026-09-19.
    5. Como está importado, el `exit 1` sale del shell de la sesión: **se cayó
       la conexión de ssh**.

    Se vigilan las tres defensas y no solo la última, porque cualquiera de las
    tres sola habría convertido eso en un mensaje de una línea:

    - `BASH_SOURCE` en vez de `$0` para ubicarse.
    - Un freno explícito contra ser importado, que además no puede usar `exit`.
    - Un diagnóstico que distinga *no estás en un repo* de *no hay remoto*.

    Es la misma clase de falla que el `[MAL]` falso del verificador: un
    mensaje seguro de sí mismo señalando el lugar equivocado enseña a
    desconfiar de la herramienta.
    """
    texto = _desplegar()

    assert "BASH_SOURCE" in texto, (
        "El script se ubica con `$0`, que vale `-bash` cuando alguien lo "
        "importa con `. desplegar.sh`: `dirname` contesta 'invalid option' y "
        "el `cd` aterriza en `/` sin fallar. Usa `${BASH_SOURCE[0]}`."
    )

    assert 'return 1 2>/dev/null || exit 1' in texto, (
        "Falta el freno contra ser importado, o no sale como debe. Un `exit` "
        "dentro de un script importado mata el shell que lo importó — en ssh, "
        "cierra la conexión. `return` primero, `exit` solo si no se pudo."
    )

    # Las posiciones del CÓDIGO, no de la prosa: el comentario que explica
    # todo esto nombra `set -euo pipefail` antes de que aparezca la primera
    # línea ejecutable, y buscar la primera coincidencia del texto medía el
    # comentario en vez del script.
    freno = re.search(r"^if \[\[ \"\$\{BASH_SOURCE\[0\]\}\"", texto, re.MULTILINE)
    modo = re.search(r"^set -euo pipefail$", texto, re.MULTILINE)
    assert freno and modo, (
        "No se encontró el freno contra ser importado o el `set -euo pipefail` "
        "como líneas de código. Si cambiaron de forma, actualiza esta prueba: "
        "lo que tiene que seguir siendo cierto es el ORDEN entre los dos."
    )
    assert freno.start() < modo.start(), (
        "El freno contra ser importado quedó DEBAJO de `set -euo pipefail`, y "
        "así no sirve aunque se vea bien. Importado, el `set -e` se le pega al "
        "shell de la sesión; con él puesto, hasta un `return 1` limpio es un "
        "comando que devolvió distinto de cero y `set -e` mata ese shell "
        "igual. La conexión de ssh se cae lo mismo, solo que con el mensaje "
        "correcto impreso antes. Medido el 2026-09-20 con el freno ya escrito."
    )

    assert "rev-parse" in texto, (
        "El script no distingue *no estás en un repositorio* de *no hay "
        "remoto configurado*, así que contesta lo segundo cuando pasa lo "
        "primero. Pregunta antes con `git rev-parse`."
    )

    assert "todavía no tiene remoto" not in texto, (
        "Quedó el mensaje que decía que Continental no tiene remoto de git. "
        "Lo tiene desde el 2026-09-19 (pendiente 1), y ese texto mandó a "
        "configurar un remoto que ya existía mientras el problema real era "
        "otro."
    )


def test_los_pasos_van_en_el_orden_del_ticket():
    """pull entonces compila entonces pruebas entonces reinicia, vive, verifica.

    El orden es la casilla entera: reiniciar antes de compilar y probar es
    exactamente lo que Marlowe hizo el 2026-09-08. Se comprueban las posiciones
    dentro del archivo y no que los seis pasos existan sueltos, porque un
    script con los seis pasos en desorden pasaría una prueba de existencia.

    **Y se cuentan sobre el "N/7".** El ticket 17 agregó un paso al final y el
    ADR 0017 uno antes del reinicio (la forma de la base); un rótulo que sigue
    diciendo "6" mientras hay siete pasos miente en la única parte del
    despliegue que alguien lee de reojo.
    """
    texto = _desplegar()

    for viejo in ("/5", "/6"):
        assert viejo not in texto, (
            f"Quedó un rótulo 'N{viejo}' después de que el ADR 0017 agregara el "
            "paso de la forma. Los rótulos de los pasos se ajustan TODOS o ninguno."
        )
    posiciones = [texto.index(f"{n}/7") for n in range(1, 8)]
    assert posiciones == sorted(posiciones), "Los siete pasos no están en orden."

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


def test_el_verificador_de_datos_va_al_final_y_despues_de_la_salud():
    """La casilla 3 del ticket 17: `desplegar.sh` lo encadena **al final**.

    Al final y no antes, porque son dos preguntas distintas: los pasos 1 a 5
    dicen si el código quedó bien desplegado, y el 6 dice si los datos que hay
    en la base están sanos. Un dato roto no tiene por qué impedir que un código
    bueno llegue a atlas — pero sí tiene que verse, y por eso el paso existe en
    vez de quedar en un comando que alguien correría "cuando se acuerde".
    """
    texto = _desplegar()

    assert "-m continental.verificar" in texto, (
        "El script no encadena continental.verificar. Un verificador que hay "
        "que acordarse de correr no se corre."
    )
    # La corrida de los DATOS es la que va sin `--forma`: la de la forma va
    # antes del reinicio, a propósito (ADR 0017), y no es ésta.
    de_los_datos = texto.index('-m continental.verificar; then')
    assert texto.index("curl") < de_los_datos, (
        "El verificador de datos corre ANTES de comprobar que el servicio "
        "quedó vivo. El orden del ticket 17 es al final de todo."
    )
    assert '"$PYTHON" -m continental.verificar' in texto, (
        "Se invoca con un `python` del PATH en vez del venv de atlas: sin "
        "SQLAlchemy ni dotenv, el paso 6 fallaría por el intérprete y no por "
        "los datos."
    )


def test_una_falla_de_datos_sale_con_codigo_distinto_de_cero_y_lo_explica():
    """Salir en rojo es la mitad; decir **qué** está rojo es la otra.

    Sin el mensaje, un paso 6 rojo se lee como "el despliegue falló" y lo
    primero que hace alguien con prisa es intentar deshacer un despliegue que
    está bien. El servicio ya contestó en el paso 5: lo que falla son los datos.
    """
    texto = _desplegar()
    desde = texto.index("7/7")

    assert "exit 1" in texto[desde:], "Una falla de datos no aborta el script."
    assert "DATOS" in texto[desde:], (
        "El script no distingue 'el código quedó mal desplegado' de 'los datos "
        "están rotos'. Son dos cosas y se arreglan de maneras distintas."
    )


def test_la_forma_de_la_base_se_revisa_antes_del_reinicio_y_lo_detiene():
    """ADR 0017, alternativa D: la FORMA —¿este código puede correr contra esta
    base?— sí tiene que impedir el reinicio, al revés que los datos.

    Va después de las pruebas y antes de `systemctl restart`, sale con
    `exit 1` si no cuadra, y dice la trampa: el `git pull` ya dejó el código
    nuevo en disco, así que el mensaje manda a migrar antes de las 22:00 (el
    lote, además, se niega solo: `forma.antes_del_lote`).
    """
    texto = _desplegar()

    forma = texto.index('"$PYTHON" -m continental.verificar --forma')
    assert texto.index("-m pytest") < forma < texto.index("systemctl restart"), (
        "La forma se revisa después de las pruebas y ANTES del reinicio: si "
        "corre después, el código nuevo ya está sirviendo contra la base vieja."
    )
    assert texto.index("4/7") < forma < texto.index("5/7")
    bloque = texto[forma : texto.index("5/7")]
    assert "exit 1" in bloque, "Una forma que no cuadra no detiene el despliegue."
    assert "NO se reinicia" in bloque
    assert "22:00" in bloque, "No dice que el lote de la noche ya ve el código nuevo."


def test_los_invariantes_de_los_datos_siguen_sin_bloquear_el_reinicio():
    """Lo que el ADR 0017 NO movió: los datos siguen al final, después de la
    salud. Un dato roto no tiene por qué impedir que un código bueno llegue."""
    texto = _desplegar()

    de_los_datos = texto.index('"$PYTHON" -m continental.verificar; then')
    assert texto.index("systemctl restart") < de_los_datos
    assert texto.count("-m continental.verificar") == 2


def test_el_script_limpia_el_estado_failed_antes_de_reiniciar():
    """Si el servicio quedó en `failed` por el límite de reinicios, un
    `restart` a secas no lo levanta.

    Es el estado en el que precisamente queda un despliegue roto, o sea el que
    este script va a encontrar cuando más falta haga.
    """
    assert "reset-failed" in _desplegar()


# ---------------------------------------------------------------------------
# Si el pull cambió `desplegar.sh`, se corre la versión NUEVA
# ---------------------------------------------------------------------------
#
# Medido el 2026-09-21: `37abad2` pasó el script de seis pasos a siete y el
# dueño lo corrió en atlas. La salida decía "1/6 … 4/6 reinicio": el pull trajo
# la versión de siete y bash siguió corriendo la de seis, que ya tenía abierta.
# El filtro de la forma (ADR 0017) no corrió en el despliegue que lo traía.


def test_el_relanzamiento_va_despues_del_pull_y_antes_del_paso_dos():
    """El pull, la comparación y el `exec` en una función; la llamada, en una
    sola línea entre el rótulo del paso 1 y el del paso 2.

    Se mide sobre líneas de CÓDIGO (regex anclada), no sobre la primera
    aparición del texto: los comentarios que lo explican nombran todo esto antes.
    """
    texto = _desplegar()

    llamada = re.search(r'^actualizar_y_relanzarse "\$@"$', texto, re.MULTILINE)
    assert llamada, (
        "Falta la llamada `actualizar_y_relanzarse \"$@\"` como línea propia. "
        "Sin ella, un pull que cambia este script corre la versión VIEJA."
    )
    assert texto.index('paso "1/7') < llamada.start() < texto.index('paso "2/7'), (
        "El relanzamiento tiene que ir en el paso 1, justo después del pull y "
        "antes de compilar: más tarde, ya corrió código de la versión vieja."
    )

    funcion = re.search(
        r"^actualizar_y_relanzarse\(\) \{\n(.*?)^\}$", texto, re.MULTILINE | re.DOTALL
    )
    assert funcion, "Falta la función `actualizar_y_relanzarse`."
    cuerpo = funcion.group(1)
    assert funcion.start() < llamada.start(), "La función se usa antes de definirse."

    antes = cuerpo.index("hash-object")
    pull = cuerpo.index("pull -q")
    despues = cuerpo.index("hash-object", pull)
    relanza = cuerpo.index("exec ")
    assert antes < pull < despues < relanza, (
        "El orden dentro de la función es: hash, pull, hash, y solo entonces "
        "`exec` si cambió."
    )

    # Un solo pull en TODO el script, y es el de la función. Un pull fuera de
    # ella deja la comparación leyéndose del archivo que el pull acaba de
    # tocar: exactamente la lectura por partes que la función evita.
    assert len(re.findall(r"^\s*git [^\n]*\bpull\b", texto, re.MULTILINE)) == 1, (
        "Hay un `git pull` fuera de `actualizar_y_relanzarse`. El pull tiene "
        "que vivir DENTRO de la función, junto con la comparación y el exec."
    )


def test_el_relanzamiento_usa_exec_conserva_los_argumentos_y_no_hace_bucle():
    texto = _desplegar()
    cuerpo = re.search(
        r"^actualizar_y_relanzarse\(\) \{\n(.*?)^\}$", texto, re.MULTILINE | re.DOTALL
    ).group(1)

    assert 'exec bash "$YO" "$@"' in cuerpo, (
        "El relanzamiento tiene que ser `exec bash \"$YO\" \"$@\"`: `exec` para "
        "que no siga corriendo la versión vieja al volver, `bash` para no "
        "depender del bit de ejecución (commit 00f79e0), y `\"$@\"` para no "
        "perder los argumentos."
    )
    guarda = cuerpo.index("CONTINENTAL_DESPLEGAR_RELANZADO")
    pull_idx = cuerpo.index("pull -q")
    assert guarda < pull_idx, (
        "La guarda contra el bucle va ANTES del pull: la versión relanzada no "
        "vuelve a jalar, así que no tiene nada que comparar ni por qué relanzarse."
    )
    assert "return 0" in cuerpo[guarda:pull_idx]

    unset_idx = cuerpo.index("unset CONTINENTAL_DESPLEGAR_RELANZADO")
    assert guarda < unset_idx < pull_idx, (
        "La variable se lee y se borra del entorno ANTES del pull (y antes de "
        "cualquier otra cosa): si se queda exportada, un proceso hijo del resto "
        "del despliegue (pytest, el filtro de la forma, systemctl...) la hereda."
    )

    # La guarda ya no es un booleano ("puesta o no"): solo aplica si el valor
    # es el hash de ESTE archivo. Un valor que sobra de otra sesión (exportado
    # a mano, o de una corrida vieja) no debe apagar el pull en silencio.
    assert re.search(r'\brelanzado"\s*==\s*"\$yo_hash"', cuerpo), (
        "La guarda tiene que comparar el valor guardado contra el hash del "
        "archivo que está corriendo AHORA, no solo mirar si está puesta."
    )
    exportar = cuerpo.index('export CONTINENTAL_DESPLEGAR_RELANZADO="$despues"')
    assert exportar < cuerpo.index("exec "), (
        "Sin exportar el HASH nuevo antes del exec, la versión relanzada no "
        "tiene con qué comparar y no sabría que este pull ya la trajo."
    )
    assert 'rm -f "$SALIDA_PRUEBAS"' in cuerpo, (
        "`exec` no corre el trap de EXIT: el temporal quedaría tirado."
    )


def test_la_ruta_propia_se_resuelve_antes_del_cd():
    """Con `desplegar.sh` o `./desplegar.sh` relativos, después del `cd` a la
    raíz la ruta ya no apunta al archivo. `$YO` se calcula antes, absoluta."""
    texto = _desplegar()
    yo = re.search(r"^YO=.*BASH_SOURCE", texto, re.MULTILINE)
    cd = re.search(r'^cd "\$RAIZ"$', texto, re.MULTILINE)
    assert yo and cd and yo.start() < cd.start()


def _bash_de_verdad() -> str | None:
    """Git Bash en la torre; el `bash` del PATH en Linux.

    En Windows NO se usa el del PATH: suele ser `System32\\bash.exe`, el de WSL,
    que vive en otro sistema de archivos y no ve las rutas de `tmp_path`.
    """
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432")):
            if base and (Path(base) / "Git" / "bin" / "bash.exe").exists():
                return str(Path(base) / "Git" / "bin" / "bash.exe")
        return None
    return shutil.which("bash")


BASH = _bash_de_verdad()
_sin_bash = pytest.mark.skipif(
    BASH is None or shutil.which("git") is None,
    reason="hace falta un bash real (Git Bash en Windows) y git para correr el script",
)


def _git(*args: str, cwd: Path) -> str:
    r = subprocess.run(
        ["git", "-c", "user.name=prueba", "-c", "user.email=prueba@local",
         "-c", "core.autocrlf=false", "-c", "init.defaultBranch=main", *args],
        cwd=cwd, capture_output=True,
    )
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    return r.stdout.decode("utf-8", "replace")


def _con_marca(marca: str) -> bytes:
    """El `desplegar.sh` REAL, cortado antes del paso 2 con una marca.

    Se prueba el paso 1 de verdad —la función, la guarda, el `exec`— y se
    corta ahí porque del paso 2 en adelante hacen falta el venv, Postgres y
    systemd de atlas. La marca dice qué versión corrió y con qué argumentos.
    """
    real = DESPLEGAR.read_bytes()
    corte = b'paso "2/7'
    assert real.count(corte) == 1
    return real.replace(
        corte,
        f'echo "    {marca} args=$# [$*]"; exit 0\n'.encode() + corte,
    )


@pytest.fixture
def atlas_de_juguete(tmp_path):
    """Un "GitHub" local con la versión vieja y un clon que hace de atlas."""
    origen = tmp_path / "origen"
    (origen / "scripts").mkdir(parents=True)
    _git("init", "-q", cwd=origen)
    (origen / "scripts" / "desplegar.sh").write_bytes(_con_marca("VERSION-VIEJA"))
    _git("add", ".", cwd=origen)
    _git("commit", "-qm", "vieja", cwd=origen)

    atlas = tmp_path / "atlas"
    _git("clone", "-q", str(origen), str(atlas), cwd=tmp_path)
    _git("config", "core.autocrlf", "false", cwd=atlas)
    return origen, atlas


def _correr(script: str, cwd: Path, *args: str, extra_env: dict | None = None):
    env = {k: v for k, v in os.environ.items() if k != "CONTINENTAL_DESPLEGAR_RELANZADO"}
    env.update(extra_env or {})
    r = subprocess.run(
        [BASH, script, *args], cwd=cwd, capture_output=True, env=env, timeout=60,
    )
    return r.returncode, (r.stdout + r.stderr).decode("utf-8", "replace")


@_sin_bash
@pytest.mark.parametrize("como", ["absoluta", "relativa"])
def test_si_el_pull_cambia_el_script_corre_la_version_nueva_una_sola_vez(
    atlas_de_juguete, como
):
    """La trampa del 2026-09-21, reproducida: el pull trae otra versión de
    `desplegar.sh`. Tiene que decir que se relanza, correr la NUEVA una sola
    vez, con los mismos argumentos, y la vieja nunca pasar del paso 1."""
    origen, atlas = atlas_de_juguete
    (origen / "scripts" / "desplegar.sh").write_bytes(_con_marca("VERSION-NUEVA"))
    _git("commit", "-qam", "nueva", cwd=origen)

    if como == "absoluta":
        script, cwd = str(atlas / "scripts" / "desplegar.sh"), atlas.parent
    else:
        script, cwd = "desplegar.sh", atlas / "scripts"
    codigo, salida = _correr(script, cwd, "uno", "dos dos")

    assert codigo == 0, salida
    assert salida.count("me vuelvo a lanzar con la versi") == 1, salida
    assert salida.count("VERSION-NUEVA") == 1, salida
    assert "VERSION-VIEJA" not in salida, salida
    assert "args=2 [uno dos dos]" in salida, "Se perdieron los argumentos:\n" + salida
    assert salida.count("1/7") == 2, "El paso 1 tiene que verse dos veces:\n" + salida
    assert "sin git pull" in salida, "La relanzada no dijo que se salta el pull:\n" + salida
    assert _git("log", "--format=%s", "-1", cwd=atlas).strip() == "nueva"


@_sin_bash
def test_si_el_pull_no_toca_el_script_no_se_relanza(atlas_de_juguete):
    origen, atlas = atlas_de_juguete
    (origen / "otro.txt").write_bytes(b"cambia otra cosa\n")
    _git("add", ".", cwd=origen)
    _git("commit", "-qm", "otra cosa", cwd=origen)

    codigo, salida = _correr(str(atlas / "scripts" / "desplegar.sh"), atlas.parent)

    assert codigo == 0, salida
    assert "me vuelvo a lanzar" not in salida, salida
    assert salida.count("VERSION-VIEJA") == 1, salida
    assert (atlas / "otro.txt").exists(), "El pull no corrió."


@_sin_bash
def test_con_la_guarda_puesta_no_jala_ni_se_relanza(atlas_de_juguete):
    """La guarda contra el bucle: con el HASH correcto puesto (el de ESTE
    archivo, tal como lo dejaría el `exec` de un relanzamiento real) no hay
    pull, así que tampoco hay cambio que detectar. Una versión nueva esperando
    en el remoto se queda ahí."""
    origen, atlas = atlas_de_juguete
    hash_actual = _git(
        "hash-object", "--no-filters", "scripts/desplegar.sh", cwd=atlas
    ).strip()
    (origen / "scripts" / "desplegar.sh").write_bytes(_con_marca("VERSION-NUEVA"))
    _git("commit", "-qam", "nueva", cwd=origen)

    codigo, salida = _correr(
        str(atlas / "scripts" / "desplegar.sh"), atlas.parent,
        extra_env={"CONTINENTAL_DESPLEGAR_RELANZADO": hash_actual},
    )

    assert codigo == 0, salida
    assert "me vuelvo a lanzar" not in salida, salida
    assert "sin git pull" in salida, salida
    assert "VERSION-VIEJA" in salida and "VERSION-NUEVA" not in salida, salida
    assert _git("log", "--format=%s", "-1", cwd=atlas).strip() == "vieja"


@_sin_bash
def test_con_la_guarda_desactualizada_advierte_y_jala(atlas_de_juguete):
    """Si el valor de CONTINENTAL_DESPLEGAR_RELANZADO no coincide con el hash
    de ESTE archivo, no es el relanzamiento de esta corrida: es un sobrante
    (exportada a mano, o de una sesión vieja cuyo `exec` no llegó a
    terminar). Ignorarlo en silencio era exactamente el bug original -el
    despliegue dejaba de jalar para siempre y nadie se enteraba-, así que
    tiene que avisar fuerte Y jalar de todos modos."""
    origen, atlas = atlas_de_juguete
    (origen / "otro.txt").write_bytes(b"cambia otra cosa\n")
    _git("add", ".", cwd=origen)
    _git("commit", "-qm", "otra cosa", cwd=origen)

    codigo, salida = _correr(
        str(atlas / "scripts" / "desplegar.sh"), atlas.parent,
        extra_env={
            "CONTINENTAL_DESPLEGAR_RELANZADO": "0" * 40,  # hash que no existe
        },
    )

    assert codigo == 0, salida
    assert "sin git pull" not in salida, (
        "Con un valor que no coincide, la guarda no aplica: tiene que jalar."
    )
    assert "no coincide" in salida, (
        "Tiene que avisar EN VOZ ALTA que la guarda no aplica:\n" + salida
    )
    assert (atlas / "otro.txt").exists(), "El pull no corrió a pesar del aviso."
    assert "me vuelvo a lanzar" not in salida, (
        "El script no cambió en este pull, así que no hay por qué relanzarse:\n"
        + salida
    )


@_sin_bash
def test_la_guarda_no_se_hereda_a_procesos_hijos(tmp_path):
    """El `unset` tiene que pasar de verdad: si la variable se quedara
    exportada, todo lo que el resto del despliegue arranca como proceso hijo
    -pytest, el filtro de la forma, systemctl- la heredaría. Se comprueba con
    `env`, no leyendo la variable de bash: eso demuestra que salió del
    entorno del PROCESO, no solo que una variable de shell cambió de valor.

    No usa `atlas_de_juguete`/`_con_marca`: esos ya cortan el script en
    "paso 2/7" con un `exit 0` propio, y agregar un segundo corte ahí
    encadenado quedaría después de ese `exit 0` -código muerto-. Este test
    arma su propio repo de juguete con el corte que necesita, una sola vez."""
    origen = tmp_path / "origen"
    (origen / "scripts").mkdir(parents=True)
    _git("init", "-q", cwd=origen)

    real = DESPLEGAR.read_bytes()
    corte = b'paso "2/7'
    assert real.count(corte) == 1
    marcado = real.replace(
        corte,
        b"if env | grep -q '^CONTINENTAL_DESPLEGAR_RELANZADO='; then\n"
        b'    echo "    FUGA: la variable llega a un proceso hijo"\n'
        b"else\n"
        b'    echo "    LIMPIO: la variable no llega a procesos hijos"\n'
        b"fi\n"
        b"exit 0\n" + corte,
    )
    (origen / "scripts" / "desplegar.sh").write_bytes(marcado)
    _git("add", ".", cwd=origen)
    _git("commit", "-qm", "marcada", cwd=origen)

    atlas = tmp_path / "atlas"
    _git("clone", "-q", str(origen), str(atlas), cwd=tmp_path)
    _git("config", "core.autocrlf", "false", cwd=atlas)

    hash_actual = _git(
        "hash-object", "--no-filters", "scripts/desplegar.sh", cwd=atlas
    ).strip()

    codigo, salida = _correr(
        str(atlas / "scripts" / "desplegar.sh"), atlas.parent,
        extra_env={"CONTINENTAL_DESPLEGAR_RELANZADO": hash_actual},
    )

    assert codigo == 0, salida
    assert "sin git pull" in salida, "La guarda debía aplicar (hash correcto):\n" + salida
    assert "LIMPIO" in salida, salida
    assert "FUGA" not in salida, salida


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
    html = pantalla_servida(cliente)

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
