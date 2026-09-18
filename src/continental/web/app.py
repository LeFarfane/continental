"""El backend de Continental.

Esqueleto: hoy solo sabe decir si está vivo, quién está entrando y si los
módulos contestan. El módulo de Pedido se construye encima de esto.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from continental import __version__
from continental.config import cargar

ESTATICOS = Path(__file__).parent / "static"

log = logging.getLogger("continental")

app = FastAPI(title="Continental", version=__version__, docs_url="/docs")


def quien(request: Request) -> str:
    """Quién está entrando, según el encabezado que Cloudflare Access ya validó.

    Es una FIRMA, no un permiso (regla 3 de CLAUDE.md). Si alguien alcanza este
    puerto sin pasar por el túnel, puede escribir el encabezado que quiera: la
    autorización la hace Access, no esto. Sirve para saber quién armó un pedido,
    no para decidir si puede armarlo.
    """
    return request.headers.get("Cf-Access-Authenticated-User-Email") or "sin-identificar"


@app.exception_handler(Exception)
async def error_generico(request: Request, exc: Exception):
    """El detalle va a la consola del servidor; al navegador, un mensaje corto.

    Esto corre detrás de un túnel: un `str(exc)` de SQLAlchemy lleva la cadena
    de conexión con contraseña. Doyle puede darse el lujo de devolver el texto
    del error porque solo escucha en 127.0.0.1; aquí no.
    """
    log.exception("Error atendiendo %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "Algo falló del lado del servidor. Revisa la bitácora."},
    )


@app.get("/api/salud")
async def salud(request: Request):
    """Vivo o no, y contra qué negocio está trabajando. No toca la base."""
    ajustes = cargar()
    return {
        "ok": True,
        "version": __version__,
        "negocio": ajustes.negocio,
        "quien": quien(request),
        "modulos": sorted(ajustes.modulos),
    }


@app.get("/api/modulos")
async def modulos():
    """Le pregunta a cada módulo si está vivo.

    Un módulo caído es un hueco con su motivo, nunca una pantalla colgada: por
    eso cada llamada lleva su timeout y el error se traduce a texto legible.
    """
    ajustes = cargar()
    resultado = []

    for modulo in ajustes.modulos.values():
        entrada = {"nombre": modulo.nombre, "url": modulo.url}
        try:
            async with httpx.AsyncClient(timeout=modulo.timeout_seg) as cliente:
                respuesta = await cliente.get(f"{modulo.url}/api/salud")
            entrada["ok"] = respuesta.status_code == 200
            if not entrada["ok"]:
                entrada["detalle"] = f"contestó {respuesta.status_code}"
        except httpx.TimeoutException:
            entrada["ok"] = False
            entrada["detalle"] = f"no contestó en {modulo.timeout_seg:g} s"
        except httpx.HTTPError as exc:
            entrada["ok"] = False
            entrada["detalle"] = f"no se pudo alcanzar ({type(exc).__name__})"
        resultado.append(entrada)

    return {"modulos": resultado}


@app.get("/")
async def inicio():
    return FileResponse(ESTATICOS / "index.html")


app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")
