# 0005 — Continental escucha en el gateway de la red Docker `borde`, no en loopback

**Fecha:** 2026-09-19  ·  **Estado:** aceptada

## Contexto

El ticket 16 pone a Continental detrás de `farmacia.farfanlab.uk`, por el mismo
túnel de Cloudflare que ya sirve a Metabase (`stadistics.farfanlab.uk`) y a
Marlowe. Antes de escribir la unidad de systemd hay que decidir **en qué
interfaz escucha el proceso**, y esa decisión roza la regla 2 de `CLAUDE.md`
—"Continental es la única puerta al exterior; los módulos escuchan en loopback
y por eso no llevan autenticación propia"—, así que no se puede tomar de paso.

Seis hechos delimitan el problema. Los seis están **medidos en atlas el
2026-09-19**, en solo lectura por ssh, salvo donde se dice otra cosa:

1. **El túnel corre en un contenedor, no en el host.** `borde_tunel`
   (`cloudflare/cloudflared:latest`) está en la red Docker `borde` con la IP
   **172.19.0.2**. No hay ninguna unidad de systemd de cloudflared en atlas:
   `systemctl list-units` no devuelve ninguna.
2. **El gateway de `borde` es 172.19.0.1.**
   `docker network inspect borde --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}'`
   lo contesta así.
3. **Para el contenedor del túnel, `localhost` es él mismo.** Marlowe lo pagó
   el 2026-09-06: apuntó el Public Hostname a `localhost:8484` y
   `marlowe.farfanlab.uk` devolvía **502**. El proceso estaba vivo y escuchando
   en 127.0.0.1 del host; el contenedor nunca lo podía alcanzar.
4. **Marlowe hoy escucha exactamente ahí, y funciona.** `ss -ltn` en atlas
   devuelve una sola línea para el 8484: `LISTEN 172.19.0.1:8484`. No en
   `0.0.0.0`, no en loopback.
5. **Los demás servicios de atlas son contenedores y publican a loopback**
   (`farmacia_bi` en 127.0.0.1:3000, `borde_kuma` en 127.0.0.1:3002,
   `farmacia_warehouse` en 127.0.0.1:5432). Para ellos el problema no existe:
   están **dentro** de la red del túnel. Continental, como Marlowe, no está
   dockerizado.
6. **Continental no tiene autenticación propia.** La seguridad real es Access
   (regla 3): el encabezado `Cf-Access-Authenticated-User-Email` es una firma,
   y quien alcance el puerto sin pasar por el túnel se lo puede inventar.

## Opciones consideradas

1. **Escuchar en `127.0.0.1:8585`.** Es lo más cerrado, y es lo que la regla 2
   pide para los módulos.
2. **Escuchar en `0.0.0.0:8585`.** Lo alcanza todo: el túnel, el host y la LAN.
3. **Escuchar en el gateway de `borde` (`172.19.0.1:8585`).** Lo alcanzan el
   túnel y el host; la LAN no tiene ruta hacia ahí.
4. **Meter Continental en un contenedor en la red `borde`.** Desaparece el
   problema: el túnel le hablaría por nombre de servicio.

## Decisión

**La 3: escuchar en el gateway de `borde`, con el valor en una variable de
entorno (`CONTINENTAL_HOST`) y no en el código.** La unidad de systemd lo fija
con `Environment=CONTINENTAL_HOST=172.19.0.1`, y por omisión —en la torre, o en
cualquier máquina que no diga nada— sigue siendo `127.0.0.1`.

La 1 está descartada por el hecho 3: es precisamente la configuración que
devuelve 502. No es una opción más segura, es una opción que no funciona.

La 2 está descartada porque expone la puerta a toda la LAN sin comprar nada a
cambio: el túnel no necesita `0.0.0.0` para alcanzarlo, y un servicio sin
autenticación propia escuchando en todas las interfaces es exactamente lo que
la regla 2 dice que hay que evitar.

La 4 es la respuesta correcta a largo plazo y está **descartada por ahora**,
no por siempre: dockerizar Continental obliga a resolver el venv con
`--system-site-packages` que atlas necesita (Athlon II X4 de 2010 sin SSSE3,
numpy y pandas vienen de `apt`), a montar el repo para que `desplegar.sh` siga
teniendo sentido, y a repetir todo eso para Doyle. Es un ticket propio, no un
paso de este. Mientras tanto, la opción 3 es la misma que Marlowe lleva
funcionando desde el 2026-09-06, y tener las dos iguales vale más que tener una
mejor y otra distinta.

**Honestidad sobre lo que 172.19.0.1 sí y no garantiza.** No es un cortafuegos:
es una dirección del host en el puente `br-*` de esa red. Ningún equipo de la
LAN tiene ruta a 172.19.0.0/16, así que en la práctica no lo alcanza; pero eso
es *no estar enrutado*, no *estar bloqueado*, y alguien con acceso a atlas que
añada una ruta lo vería. La garantía real sigue siendo Access, delante del
túnel, y por eso la política de Access no es opcional ni "se pone después".

## Consecuencias

- La unidad de systemd declara `Requires=docker.service`. No solo por el
  almacén: **la interfaz donde este proceso escucha no existe hasta que Docker
  levanta la red `borde`.** Sin el puente, uvicorn muere con "Cannot assign
  requested address". El `Restart=on-failure` con `RestartSec=10` cubre la
  carrera de arranque; el `StartLimitBurst` la distingue de un problema real.
- **El valor caduca si se recrea la red.** Un `docker compose down` seguido de
  `up` en `~/proyectos/borde` puede asignar otra subred. Si eso pasa,
  Continental arranca y muere, y hay que volver a medir:

  ```bash
  docker network inspect borde --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}'
  ```

  y poner el valor nuevo en **dos** lugares: la unidad de systemd y el Public
  Hostname del dashboard de Cloudflare. Cambiar solo uno deja un 502 que parece
  otra cosa. La advertencia está escrita en la propia unidad, que es donde la
  va a leer quien la esté editando.
- `scripts/desplegar.sh` comprueba la salud por **esa misma** dirección y
  puerto. Preguntarle a `127.0.0.1` diría que todo está bien mientras
  `farmacia.farfanlab.uk` devuelve 502, que es la falla que el ticket viene a
  evitar.
- **Se arregló una falla silenciosa al escribir esto.** `.env.example`
  documenta `CONTINENTAL_HOST` desde hace días, pero `iniciar.py` leía el
  entorno como constante de módulo —antes de que nadie llamara a
  `load_dotenv`, que vive dentro de `continental.config.cargar()` y no corre
  hasta que uvicorn importa la aplicación—. Poner el gateway en `.env` **no
  hacía nada** y Continental se habría quedado en loopback, con el 502 del
  hecho 3 y sin un solo mensaje de error. Ahora lo resuelve
  `iniciar.py:host_de_escucha()`, que carga el `.env` primero, y el orden de
  precedencia es entorno (systemd) → `.env` → `127.0.0.1`. Lo vigilan tres
  pruebas de `tests/test_despliegue.py`.
- La regla 2 **no se rompe**: los que siguen en loopback son Doyle (8383) y
  Marlowe (8484) *(corregido abajo, 2026-09-21: Marlowe no sigue en
  loopback)*, que son los que no tienen autenticación. Continental es la
  puerta, y una puerta tiene que ser alcanzable por el túnel para ser puerta.
  Si algún día Doyle o Marlowe necesitan salir de loopback, esa suposición sí
  deja de valer y hace falta un token entre servicios **antes** de moverlos.

## Enmienda del 2026-09-21 — Marlowe no está en loopback, y no lo ha estado desde antes de este ADR

**Falso lo dicho arriba en Consecuencias:** Marlowe **no** sigue en loopback.
Medido en atlas el 2026-09-21 (mismo día, misma herramienta que el hecho 4 de
este ADR): `ss -ltn` da una sola línea para el 8484, `LISTEN 172.19.0.1:8484`
—el gateway de `borde`, no `127.0.0.1`— y `curl http://172.19.0.1:8484/api/salud`
contesta `200`. Doyle sí sigue en loopback: su propia unidad de systemd fija
`Environment=DOYLE_HOST=127.0.0.1` y no hay nada en sus ADRs que lo mueva. La
frase de arriba juntó a los dos servicios y solo describe bien a uno.

**No es un cambio reciente ni una sorpresa nueva.** `marlowe-web.service` fija
`Environment=MARLOWE_HOST=172.19.0.1` desde el sprint 02 de Marlowe (su ADR
0011, 2026-09-06) —trece días antes de que este ADR se escribiera—, por la
misma razón que llevó a Continental a la opción 3: Marlowe todavía tiene su
propia pantalla de curación, `https://marlowe.farfanlab.uk`, detrás de su
propio túnel y de Cloudflare Access, y para el contenedor del túnel
`localhost` es él mismo (hecho 3 de este ADR, que es literalmente el golpe que
Marlowe se llevó el 2026-09-06). El propio
`Doyle/scripts/systemd/doyle.service` ya lo tenía escrito, antes de este ADR:
*"Marlowe y Continental escuchan en 172.19.0.1"*. Y el commit `de94e57` de
este repo (2026-09-21) es la prueba práctica del error: `config/continental.yml`
apuntaba a Marlowe en `http://127.0.0.1:8484`, Continental lo veía como
`ConnectError`, y el arreglo fue apuntar a `http://172.19.0.1:8484` —no
cambiarle nada a Marlowe, que ya estaba ahí.

**Qué quiere decir esto para la regla 2.** La regla se sostiene en que un
módulo sin autenticación propia es seguro porque nada externo lo alcanza. Eso
ya no describe a Marlowe: su interfaz web no tiene autenticación propia
(revisado `src/marlowe/web/app.py` y `static/index.html` de ese repo: no hay
`Depends`, cabecera ni middleware de auth, solo lo que Cloudflare Access añade
delante del túnel) y escucha en el gateway de `borde`, así que **cualquier
cosa que esté en esa red Docker la alcanza sin pasar por Access**. Medido en
este mismo ADR (hechos 1 y 5), hoy eso son `borde_tunel` (cloudflared,
172.19.0.2) y los contenedores que publican a loopback desde dentro de
`borde` (`farmacia_bi`/Metabase, `borde_kuma`, `farmacia_warehouse`). Desde
internet, a Marlowe solo se llega por su túnel más Access, igual que a
Continental. La garantía real sigue siendo la misma que ya razona la
Decisión de este ADR para 172.19.0.1: Access, y que la LAN no tiene ruta a
`172.19.0.0/16` —que es *no estar enrutado*, no *estar bloqueado*—.

**Lo que este ADR no decide — queda abierto para el dueño.** Que Marlowe
quede expuesto a `borde` sin token propio fue una decisión de Marlowe (su
propio ADR 0011), tomada antes de que existiera este ADR y sin que este
documento la describiera bien hasta hoy. Tres caminos, ninguno se toma aquí:

a. **Dejarlo como está**, aceptando que cualquier contenedor de `borde`
   alcanza la interfaz de curación de Marlowe sin pasar por Access.
b. **Separar las dos cosas de Marlowe**: mover su interfaz de datos —la que
   Continental consulta— a loopback, y dejar solo su pantalla de curación en
   `borde`, si se puede separar sin duplicar el proceso.
c. **Un token entre servicios**, que es justo lo que la frase original de
   este ADR ya preveía para el día en que Doyle o Marlowe salieran de
   loopback —ese día ya llegó para Marlowe, sin que nadie lo hubiera
   decidido a propósito.

Doyle, que sí sigue en loopback y no tiene pantalla propia, no tiene esta
exposición.
