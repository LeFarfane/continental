# 16: Continental desplegable en atlas

**Qué construir:** que el encargado pueda entrar desde `farmacia.farfanlab.uk` y usar la lista de verdad, y que desplegar una versión nueva no pueda dejar el servicio roto.

**Bloqueado por:** 14.

**Status:** ready-for-human

> **2026-09-19 — el ticket queda a medias A PROPÓSITO, y aquí está la raya.**
> Lo construible está construido y probado; lo que falta necesita dos cosas que
> una sesión de agente no puede hacer, y ninguna de las dos es código:
>
> 1. **Escribir en atlas.** Continental no está ahí —`~/proyectos/` tiene
>    `borde`, `Farmacia`, `Marlowe` y `Sarabia`, medido ese día en solo
>    lectura— y el repo todavía no tiene remoto de git, así que el `git pull`
>    de `desplegar.sh` no se puede ejercitar. Atlas tiene Marlowe corriendo en
>    producción; no se toca.
> 2. **Entrar al dashboard de Cloudflare.** El túnel de atlas es
>    *remotely-managed*: `borde_tunel` corre como `tunnel --no-autoupdate run`,
>    **sin `config.yml` local**, y su enrutamiento vive en Zero Trust. El
>    Public Hostname y la política de Access los da de alta una persona.
>
> Las casillas que dependen de eso quedan **sin marcar**, con los pasos exactos
> —campo por campo y en orden— en **`docs/despliegue-en-atlas.md`**.

- [ ] `continental-web.service` en systemd, arrancando con `--servicio` (sin abrir navegador y **sin buscarse otro puerto**: el túnel apunta a uno fijo).
      - **Hecho y probado:** el archivo es `scripts/systemd/continental-web.service`,
        con 7 pruebas en `tests/test_despliegue.py`. Entre ellas, la lección
        cara de Marlowe: `StartLimitIntervalSec`/`StartLimitBurst` en `[Unit]`
        y **no** en `[Service]`, donde systemd los ignora en silencio. Sin
        `xvfb-run`: Continental no abre navegadores (regla 1, ADR 0001).
        Declara `Requires=docker.service` —el almacén corre en Docker **y** la
        interfaz donde escucha no existe hasta que Docker levanta la red— y
        **no** se ata a Doyle ni a Marlowe, porque un módulo caído es un hueco
        en la pantalla, no la puerta abajo (regla 4).
      - **La parte del `--servicio` está verificada de verdad**, no supuesta:
        con el 8585 ocupado por otro proceso, `iniciar.py --servicio` sale con
        código 1 y su motivo, y no se muda al 8586. **Al verificarlo apareció
        un incumplimiento real y se arregló** — ver la nota al final.
      - **Falta:** instalar la unidad en atlas (`sudo cp`, `daemon-reload`,
        `systemd-analyze verify`, `enable --now`). Pasos A.6 y A.7 de
        `docs/despliegue-en-atlas.md`. Antes hacen falta A.1 a A.5: remoto de
        git, clonar plano en `~/proyectos/Continental`, venv, `.env` y el rol
        de Postgres del ticket 07.
- [ ] Ruta del túnel de Cloudflare para `farmacia.farfanlab.uk`, con Access delante.
      - **No se puede ejecutar desde aquí:** vive en el dashboard de Zero
        Trust, no en un archivo de atlas.
      - **Documentada paso a paso** en `docs/despliegue-en-atlas.md`, parte B,
        con los valores exactos: Public Hostname `farmacia` / `farfanlab.uk`,
        tipo **HTTP** (no HTTPS), URL **`172.19.0.1:8585`** (no `localhost`,
        que es el 502 que Marlowe midió el 2026-09-06); y después una
        aplicación *Self-hosted* de Access con política `Allow` → Include →
        Emails.
      - **El orden importa y está escrito:** entre que existe el Public
        Hostname y que existe la política de Access, el sitio está abierto a
        internet. Continental no tiene autenticación propia.
- [x] Si hace falta escuchar en el gateway de la red Docker `borde` en vez de loopback, queda documentado con el valor medido y la advertencia de que cambia si se recrea la red.
      - **Sí hace falta, y está decidido y razonado** en
        `docs/decisiones/0005-continental-escucha-en-el-gateway-de-borde.md`,
        con las cuatro opciones y por qué se descartaron tres.
      - **Valor medido el 2026-09-19 en atlas:** `172.19.0.1` (por
        `docker network inspect borde`), confirmado con `ss -ltn` — marlowe-web
        está escuchando ahí y en ningún otro lado, y `borde_tunel` está en esa
        misma red con la IP 172.19.0.2.
      - **La advertencia va en los tres lugares donde alguien la va a leer:** la
        unidad, el ADR y `.env.example`, con el comando para volver a medirlo y
        el recordatorio de cambiarlo **también** en el dashboard. Una prueba
        exige que la unidad diga "cambia si se recrea la red".
      - **Configurable, no incrustado:** `CONTINENTAL_HOST`, con precedencia
        entorno (systemd) → `.env` → `127.0.0.1`.
- [x] `scripts/desplegar.sh`: `pull`, compila todos los módulos, corre el suite con el venv real, y **solo entonces** reinicia. Se detiene en el primer paso que falla.
      - Cinco pasos en ese orden, `set -euo pipefail`, y el paso de compilar
        incluye **`iniciar.py`**, que es el archivo que el servicio ejecuta y
        el que ninguna prueba importa — el hueco exacto que tumbó a Marlowe.
      - **Ejercitado de verdad** el 2026-09-19, en una caja de arena con `git`,
        `sudo` y `systemctl` falsos: con un módulo que no compila se detiene en
        2/5; con el suite en rojo se detiene en 3/5; en los dos casos **el
        reinicio nunca se ejecuta**. Con todo en verde sí reinicia y encadena
        la comprobación por HTTP.
      - Encadena `curl` a `/api/salud` por **la misma interfaz y puerto** a los
        que apunta el túnel, y limpia un `failed` por límite de reinicios antes
        de reiniciar.
      - Contra el repo real se detiene en 1/5 con "este repo no tiene ningún
        remoto configurado", que es la verdad de hoy.
- [ ] El correo que Access verifica llega y se ve en la pantalla: es la firma de quién está trabajando.
      - **Todo lo que depende de Continental está demostrado.**
        `tests/test_salud.py` ya probaba que `/api/salud` devuelve el correo de
        `Cf-Access-Authenticated-User-Email` y `sin-identificar` cuando no hay
        ninguno; el ticket 16 agrega la otra mitad, que era la que faltaba:
        que **se ve en la pantalla**. La sección "Estado" pinta
        `Entrando como <correo>` en una lista que no está escondida detrás de
        un `hidden`, y una prueba nueva lo exige sobre el HTML servido.
      - También se blinda la regla 3: una prueba falla si `quien(request)`
        aparece dentro de una condición. Es una **firma**, nunca una prueba de
        autorización.
      - **Sin marcar porque el eslabón de en medio no se pudo ejercitar:** que
        el encabezado llegue *de verdad* exige que exista la aplicación de
        Access, que es la casilla de arriba. Queda como paso **B.3** de
        `docs/despliegue-en-atlas.md`: entrar desde fuera y comprobar que dice
        el correo y no `sin-identificar`.
- [x] Los archivos `.sh` y las unidades van con LF, no CRLF.
      - `.gitattributes` ya fijaba `eol=lf` para `.sh`, `.service` y `.timer`;
        lo que faltaba era que existiera algún archivo de esas clases.
      - `tests/test_compila.py` ya caminaba el repo buscándolos y anunciaba el
        caso como **saltado** mientras no hubiera ninguno. Con este ticket
        dejan de saltarse: hoy revisa `scripts/desplegar.sh` y
        `scripts/systemd/continental-web.service` de verdad, más el shebang del
        primero. Su docstring y el motivo del salto se actualizaron para que no
        sigan diciendo que no existen.
      - **Comprobado que tiene dientes:** inyectando CRLF en `desplegar.sh` la
        prueba se pone roja; restaurado, vuelve a verde.
- [x] Marlowe desplegó un `app.py` que no compilaba con "pull, reinicia y ojalá", y el servicio quedó en bucle mientras el dueño trabajaba contra un servidor que no existía. Esto es para que no se repita.
      - Las tres defensas están puestas y probadas: el **orden** de
        `desplegar.sh` (compilar y probar antes de reiniciar, verificado en la
        caja de arena), el **freno de reinicios** en la sección correcta de la
        unidad (verificado moviéndolo a `[Service]` y viendo la prueba roja), y
        la **comprobación por HTTP** de que quedó vivo.

---

## Lo que apareció al verificar `--servicio` (y no era lo que se esperaba)

`CLAUDE.md` decía que `--servicio` ya existía y no se buscaba otro puerto. El
ticket pedía comprobarlo de verdad en vez de suponerlo, y comprobarlo valió la
pena: **la garantía existía en atlas y no existía en la torre.**

`puerto_libre()` sondeaba con `SO_REUSEADDR` en las dos plataformas. En Linux
esa opción **no** deja amarrarse a un puerto donde ya hay alguien escuchando,
así que el freno funcionaba. En Windows significa casi lo contrario: **sí** lo
deja. Medido el 2026-09-19 en la torre, con un `listen()` vivo en el 8585, la
sonda contestaba **libre**; el freno pasaba de largo y uvicorn moría después
con un `[Errno 10048]` que no explica por qué importa.

O sea: la única máquina donde alguien podía probar esa garantía era justo
aquella donde no funcionaba. Arreglado usando en cada sistema la opción que de
verdad responde la pregunta —`SO_EXCLUSIVEADDRUSE` en Windows, `SO_REUSEADDR`
en Linux, que es lo que uvicorn va a usar milisegundos después—, con la prueba
que lo vigila.

**Lo importante:** la regla del ticket —"no se busca otro puerto"— nunca
estuvo rota. Aun con la sonda mintiendo, el modo servicio moría en vez de
mudarse, porque `--servicio` no llama a `elegir_puerto` nunca. Lo que estaba
roto era el mensaje: se perdía la explicación y quedaba un traceback.

De paso apareció una segunda falla silenciosa, ésta sí con consecuencias
directas para este ticket: **`CONTINENTAL_HOST` puesto en `.env` no hacía
nada.** `iniciar.py` leía el entorno al importarse, antes de que nadie llamara
a `load_dotenv`. Continental se habría quedado en `127.0.0.1` y el túnel habría
devuelto el mismo 502 de Marlowe, sin un solo mensaje de error. Arreglado en
`host_de_escucha()` y cubierto por tres pruebas.
