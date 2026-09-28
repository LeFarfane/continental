"""Cuánto aguanta sin uso la sesión de un portal (2026-09-28, LEVIC).

Uso, en atlas, con la sesión recién abierta por el visor:

    nohup setsid python3 scripts/medir_la_sesion.py --proveedor levic \
        > ~/medicion-levic.log 2>&1 &

Busca un producto a través de Continental (la misma pestaña de Buscar: nada
de navegadores aquí, regla 1), espera un hueco sin uso, y vuelve a buscar. Los
huecos crecen —15, 20, 25, 30, 40 minutos— y **cada búsqueda que sirve
reinicia la cuenta**, así que el primer hueco que la mata dice que el límite
está entre ése y el anterior. Se detiene en la primera que muere.

Mientras corre, **nadie más debe usar ese portal**: una búsqueda de por medio
reinicia la cuenta y la medición mide otra cosa. Cada búsqueda queda además en
`pedidos.lectura_de_portal`, con origen `buscar`.

Solo biblioteca estándar: corre con el `python3` del sistema.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.request

CONTINENTAL = "http://172.19.0.1:8585"


def _pedir(metodo: str, ruta: str, cuerpo: dict | None = None) -> dict:
    datos = None if cuerpo is None else json.dumps(cuerpo).encode("utf-8")
    peticion = urllib.request.Request(
        CONTINENTAL + ruta, data=datos, method=metodo,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(peticion, timeout=30) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def _ahora() -> str:
    return dt.datetime.now().strftime("%H:%M:%S")


def buscar(proveedor: str, termino: str, tope_seg: int = 240) -> tuple[bool | None, str]:
    """`(sirvio, que_paso)`. `sirvio` es `None` si no se supo (no terminó, o
    el portal falló por otra cosa que la sesión)."""
    acuse = _pedir("POST", "/api/buscar", {"termino": termino})
    if not acuse.get("ok"):
        return None, f"Continental no aceptó la búsqueda: {acuse.get('detalle')}"
    hasta = time.monotonic() + tope_seg
    while time.monotonic() < hasta:
        time.sleep(3)
        datos = _pedir("GET", f"/api/buscar/{acuse['job_id']}")
        if not datos.get("ok"):
            return None, f"Continental: {datos.get('detalle')}"
        [p] = [x for x in datos["proveedores"] if x["proveedor"] == proveedor] or [None]
        if p is None or not p["terminado"]:
            continue
        if p["sesion_caducada"]:
            return False, p["que_paso"] or "la sesión caducó"
        if p["motivo"] in (None, "sin resultados"):
            return True, f"{p['etiqueta']} ({len(p['filas'])} resultado(s))"
        return None, f"{p['etiqueta']}: {p['que_paso']}"
    return None, f"no terminó en {tope_seg} s"


def main() -> int:
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argumentos.add_argument("--proveedor", default="levic")
    argumentos.add_argument("--termino", default="7502256040203")  # la sonda del lote
    argumentos.add_argument("--huecos", default="15,20,25,30,40", help="minutos, en orden")
    a = argumentos.parse_args()
    huecos = [int(x) for x in a.huecos.split(",")]

    print(f"{_ahora()}  medición de {a.proveedor}, huecos {huecos} min, buscando {a.termino}", flush=True)
    sirvio, que = buscar(a.proveedor, a.termino)
    print(f"{_ahora()}  primera búsqueda: {que}", flush=True)
    if sirvio is not True:
        print("La sesión no sirve desde el principio (o no se supo): no hay qué medir.", flush=True)
        return 1

    anterior = 0
    for hueco in huecos:
        print(f"{_ahora()}  esperando {hueco} min sin usarla…", flush=True)
        time.sleep(hueco * 60)
        sirvio, que = buscar(a.proveedor, a.termino)
        print(f"{_ahora()}  tras {hueco} min sin uso: {que}", flush=True)
        if sirvio is False:
            print(f"RESULTADO: el límite está entre {anterior} y {hueco} minutos sin uso.", flush=True)
            return 0
        if sirvio is None:
            print("RESULTADO: no se pudo saber en este hueco (ver arriba); se detiene.", flush=True)
            return 1
        anterior = hueco
    print(f"RESULTADO: aguantó todos los huecos; el límite es mayor que {anterior} minutos.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
