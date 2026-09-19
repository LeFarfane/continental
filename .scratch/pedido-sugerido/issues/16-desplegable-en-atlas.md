# 16: Continental desplegable en atlas

**Qué construir:** que el encargado pueda entrar desde `farmacia.farfanlab.uk` y usar la lista de verdad, y que desplegar una versión nueva no pueda dejar el servicio roto.

**Bloqueado por:** 14.

**Status:** ready-for-agent

- [ ] `continental-web.service` en systemd, arrancando con `--servicio` (sin abrir navegador y **sin buscarse otro puerto**: el túnel apunta a uno fijo).
- [ ] Ruta del túnel de Cloudflare para `farmacia.farfanlab.uk`, con Access delante.
- [ ] Si hace falta escuchar en el gateway de la red Docker `borde` en vez de loopback, queda documentado con el valor medido y la advertencia de que cambia si se recrea la red.
- [ ] `scripts/desplegar.sh`: `pull`, compila todos los módulos, corre el suite con el venv real, y **solo entonces** reinicia. Se detiene en el primer paso que falla.
- [ ] El correo que Access verifica llega y se ve en la pantalla: es la firma de quién está trabajando.
- [ ] Los archivos `.sh` y las unidades van con LF, no CRLF.
- [ ] Marlowe desplegó un `app.py` que no compilaba con "pull, reinicia y ojalá", y el servicio quedó en bucle mientras el dueño trabajaba contra un servidor que no existía. Esto es para que no se repita.
