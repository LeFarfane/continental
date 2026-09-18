"""Lanzador de Continental.

    python iniciar.py                 -> 8585 (o el siguiente libre), abre el navegador
    python iniciar.py 9100            -> intenta el 9100 primero
    python iniciar.py --servicio      -> no abre navegador, no busca otro puerto

Calcado de `Marlowe/iniciar.py`, que a su vez viene de Doyle y de
`Max/punto-interno`. Dos notas que no hay que redescubrir:

1. **`--servicio`.** Bajo systemd no hay a dónde abrir un navegador, y
   "buscarse otro puerto" es peor que fallar: el túnel de Cloudflare apunta a
   UN puerto fijo, así que arrancar en otro deja el servicio vivo pero
   inalcanzable — la clase de falla silenciosa que este repo prohíbe.
2. **Puerto 8585.** El 8383 es de Doyle, el 8484 de Marlowe y el 8787 de Max;
   los cuatro pueden acabar en la misma máquina.
3. **`CONTINENTAL_HOST`.** En atlas, el contenedor del túnel vive en la red
   Docker `borde` y para él `localhost` es él mismo, no el host. Por eso puede
   hacer falta escuchar en el gateway de esa red (`docker network inspect
   borde`). A diferencia de Marlowe, Continental no necesita Xvfb: aquí no se
   abre un navegador nunca.
"""

import os
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

HOST = os.environ.get("CONTINENTAL_HOST", "127.0.0.1")
PUERTO_PREFERIDO = 8585
INTENTOS = 20


def puerto_libre(host: str, puerto: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, puerto))
            return True
        except OSError:
            return False


def elegir_puerto(inicial: int) -> int:
    for p in range(inicial, inicial + INTENTOS):
        if puerto_libre(HOST, p):
            return p
    raise SystemExit(f"No hay puertos libres entre {inicial} y {inicial + INTENTOS - 1}.")


def abrir_navegador(url: str):
    time.sleep(1.2)          # dar tiempo a que uvicorn termine de levantar
    webbrowser.open(url)


def main():
    argumentos = [a for a in sys.argv[1:] if a != "--servicio"]
    servicio = "--servicio" in sys.argv
    inicial = int(argumentos[0]) if argumentos else PUERTO_PREFERIDO

    if servicio:
        if not puerto_libre(HOST, inicial):
            raise SystemExit(
                f"El puerto {inicial} está ocupado. En modo --servicio NO se busca "
                f"otro: el túnel apunta a este puerto y arrancar en otro dejaría el "
                f"servicio vivo pero inalcanzable.")
        puerto = inicial
    else:
        puerto = elegir_puerto(inicial)
        if puerto != inicial:
            print(f"El puerto {inicial} estaba ocupado. Usando el {puerto}.")

    url = f"http://{HOST}:{puerto}"
    print(f"\n  Continental          {url}")
    print(f"  Documentación API    {url}/docs")
    print("  Ctrl+C para detener\n")

    if not servicio:
        threading.Thread(target=abrir_navegador, args=(url,), daemon=True).start()

    uvicorn.run("continental.web.app:app", host=HOST, port=puerto, log_level="warning")


if __name__ == "__main__":
    main()
