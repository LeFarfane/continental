"""Lanzador de Continental.

    python iniciar.py                 -> 8585 (o el siguiente libre), abre el navegador
    python iniciar.py 9100            -> intenta el 9100 primero
    python iniciar.py --servicio      -> no abre navegador, no busca otro puerto

Calcado de `Marlowe/iniciar.py`, que a su vez viene de Doyle y de
`Max/punto-interno`. Cuatro notas que no hay que redescubrir:

1. **`--servicio`.** Bajo systemd no hay a dónde abrir un navegador, y
   "buscarse otro puerto" es peor que fallar: el túnel de Cloudflare apunta a
   UN puerto fijo, así que arrancar en otro deja el servicio vivo pero
   inalcanzable — la clase de falla silenciosa que este repo prohíbe.
2. **Puerto 8585.** El 8383 es de Doyle, el 8484 de Marlowe y el 8787 de Max;
   los cuatro pueden acabar en la misma máquina.
3. **`CONTINENTAL_HOST`.** En atlas, el contenedor del túnel vive en la red
   Docker `borde` y para él `localhost` es él mismo, no el host. Por eso hace
   falta escuchar en el gateway de esa red — medido el 2026-09-19 en
   **172.19.0.1**, ver `docs/decisiones/0005-*`. A diferencia de Marlowe,
   Continental no necesita Xvfb: aquí no se abre un navegador nunca.
4. **El orden importa: primero `.env`, después el entorno.** Hasta el
   2026-09-19 `HOST` se leía como una constante de módulo, o sea **antes** de
   que nadie llamara a `load_dotenv`; `load_dotenv` vive dentro de
   `continental.config.cargar()`, que no corre hasta que uvicorn importa la
   aplicación. Resultado: `CONTINENTAL_HOST=172.19.0.1` puesto en `.env` —que
   es justo lo que `.env.example` documenta— **no hacía nada** y Continental
   se quedaba en `127.0.0.1`, con el túnel devolviendo el mismo 502 que
   Marlowe midió el 2026-09-06 y sin un solo mensaje de error. Por eso ahora
   el host lo resuelve `host_de_escucha()`, que carga el `.env` primero. La
   unidad de systemd pone la variable con `Environment=` y eso **gana** sobre
   el `.env`, porque `load_dotenv` no pisa lo que ya está en el entorno: son
   los dos caminos, y el de systemd es el que manda.
"""

import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent
HOST_POR_OMISION = "127.0.0.1"
PUERTO_PREFERIDO = 8585
INTENTOS = 20


def host_de_escucha(raiz: Path = RAIZ) -> str:
    """En qué interfaz escucha Continental, leyendo el `.env` **antes** del entorno.

    Devuelve `127.0.0.1` si nadie dice otra cosa: en la torre eso es lo
    correcto y es el valor más cerrado de los dos. En atlas la unidad de
    systemd pone `CONTINENTAL_HOST` con el gateway de la red Docker `borde`
    (ver la nota 4 del encabezado y `docs/decisiones/0005-*`).

    `load_dotenv` **no pisa** lo que ya esté en el entorno, así que el orden de
    precedencia real es: variable de entorno (systemd, o la shell) → `.env` →
    `127.0.0.1`. No lee la red ni la base.
    """
    load_dotenv(raiz / ".env")
    return os.environ.get("CONTINENTAL_HOST", HOST_POR_OMISION)


def configurar_bitacora():
    """La bitácora de `continental` en INFO, y solo la de `continental`.

    Sin esto no se pierde un detalle cosmético: se pierde **la firma**. El
    correo de Cloudflare Access sirve para saber quién hizo qué (regla 3 de
    CLAUDE.md), y quién cerró un pedido sugerido se anota con `log.info`; con
    la raíz de `logging` sin configurar, el nivel por omisión es WARNING y esa
    línea no se escribe en ninguna parte. Una firma que no se guarda no es una
    firma. Lo mismo vale para los avisos de operación —cuántas listas
    vencieron al abrir el día—, que es lo que se lee después en `journalctl`.

    **Solo el logger de `continental`**, y no `basicConfig` sobre la raíz:
    poner la raíz en INFO enciende también a `httpx`, que escribe una línea por
    cada petición a Doyle y a Marlowe —la pantalla las hace cada vez que
    alguien la carga— y ahoga en ruido justo lo que esto viene a hacer legible.

    Va aquí y no en `app.py` porque configurar el logging global al importar un
    módulo se lo impone a quien lo importe, incluidas las pruebas.
    """
    bitacora = logging.getLogger("continental")
    bitacora.setLevel(logging.INFO)
    if not bitacora.handlers:
        salida = logging.StreamHandler()
        salida.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        bitacora.addHandler(salida)
        # No se propaga a la raíz: si algún día alguien la configura, estas
        # líneas saldrían dos veces.
        bitacora.propagate = False


def puerto_libre(host: str, puerto: int) -> bool:
    """¿Se puede escuchar en ese puerto? Se responde intentándolo, no mirando una lista.

    **La opción del socket no es adorno, y estuvo mal hasta el 2026-09-19.**
    La sonda usaba `SO_REUSEADDR` en las dos plataformas, y en Windows esa
    opción significa lo contrario de lo que significa en Linux: permite
    amarrarse a un puerto donde YA hay alguien escuchando. Medido ese día en la
    torre, con un `listen()` vivo en el 8585, la sonda contestaba **libre**.
    O sea que en la torre el freno de `--servicio` no frenaba nada: la
    comprobación pasaba, uvicorn intentaba amarrarse igual y moría con un
    `[Errno 10048]` que no explica por qué importa. En atlas (Linux) sí
    frenaba, porque allá `SO_REUSEADDR` no deja pisar un socket a la escucha
    — pero una garantía que solo funciona donde nadie la puede probar es una
    garantía que nadie está probando.

    Por eso cada sistema lleva la opción que de verdad responde la pregunta:

    - **Windows**: `SO_EXCLUSIVEADDRUSE`, que es el par documentado de
      `SO_REUSEADDR` y hace que el `bind` falle si alguien ya está ahí. Las
      dos juntas no se pueden poner.
    - **Linux (atlas)**: `SO_REUSEADDR`, que es lo que uvicorn va a usar unos
      milisegundos después. La sonda tiene que preguntar lo mismo que el
      servidor va a hacer; sin ella, un puerto con conexiones en `TIME_WAIT`
      de la corrida anterior se leería como ocupado y un reinicio normal del
      servicio se negaría a arrancar sin motivo.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, puerto))
            return True
        except OSError:
            return False


def elegir_puerto(host: str, inicial: int) -> int:
    for p in range(inicial, inicial + INTENTOS):
        if puerto_libre(host, p):
            return p
    raise SystemExit(f"No hay puertos libres entre {inicial} y {inicial + INTENTOS - 1}.")


def decidir_puerto(host: str, inicial: int, servicio: bool) -> int:
    """La regla del puerto, aparte de `main()` para que se pueda probar.

    Dos comportamientos distintos a propósito:

    - **A mano** (sin `--servicio`): si el puerto está ocupado se busca el
      siguiente libre. Es una comodidad de escritorio; quien lo lanzó está
      mirando la terminal y ve en qué puerto quedó.
    - **Como servicio** (`--servicio`): se muere. El túnel de Cloudflare apunta
      a UN puerto fijo —lo dice `docs/despliegue-en-atlas.md`, paso 2— y
      arrancar en otro dejaría el proceso vivo, la unidad en `active (running)`
      y `farmacia.farfanlab.uk` devolviendo 502 sin una sola línea roja en
      `journalctl`. Fallar ruidoso es la regla 4 de CLAUDE.md, y aquí eso
      significa **no arrancar**.

    Vivía dentro de `main()` hasta el 2026-09-19 y no se podía probar sin
    levantar uvicorn, así que la garantía era un comentario. Ahora es
    `tests/test_despliegue.py`.
    """
    if servicio:
        if not puerto_libre(host, inicial):
            raise SystemExit(
                f"El puerto {inicial} está ocupado. En modo --servicio NO se busca "
                f"otro: el túnel apunta a este puerto y arrancar en otro dejaría el "
                f"servicio vivo pero inalcanzable.")
        return inicial

    puerto = elegir_puerto(host, inicial)
    if puerto != inicial:
        print(f"El puerto {inicial} estaba ocupado. Usando el {puerto}.")
    return puerto


def abrir_navegador(url: str):
    time.sleep(1.2)          # dar tiempo a que uvicorn termine de levantar
    webbrowser.open(url)


def main():
    configurar_bitacora()
    argumentos = [a for a in sys.argv[1:] if a != "--servicio"]
    servicio = "--servicio" in sys.argv
    inicial = int(argumentos[0]) if argumentos else PUERTO_PREFERIDO

    host = host_de_escucha()
    puerto = decidir_puerto(host, inicial, servicio)

    url = f"http://{host}:{puerto}"
    print(f"\n  Continental          {url}")
    print(f"  Documentación API    {url}/docs")
    print("  Ctrl+C para detener\n")

    if not servicio:
        threading.Thread(target=abrir_navegador, args=(url,), daemon=True).start()

    uvicorn.run("continental.web.app:app", host=host, port=puerto, log_level="warning")


if __name__ == "__main__":
    main()
