# Desplegar Continental en atlas

Cómo `farmacia.farfanlab.uk` llega a existir, paso a paso y en orden.

**Estado al 2026-09-20: hechos A.1, A.2, A.3 y A.5. Falta A.4 y de A.6 en
adelante.** Lo que falta necesita dos cosas que una sesión de agente no puede
hacer sola: **escribir en atlas** y **entrar al dashboard de Cloudflare**. Las
casillas sin marcar lo están por eso, no por olvido.

> **A.5 se hizo antes que A.4 y el orden de los números no manda aquí.** El rol
> subió de prioridad cuando farmacia-data agregó `continental` al `grants` de
> sus modelos de `marts`: mientras el rol no existiera, un `dbt build` en atlas
> tumbaba la cadena nocturna entera. A.4 solo hace falta para que Continental
> *arranque*; A.5 hacía falta para que lo de al lado no se cayera.

El repo **ya existe en GitHub y ya está clonado en atlas**:
`LeFarfane/continental`, privado, y `~/proyectos/Continental` parado en `main`.
El suite corre ahí: **827 pasan en 9.86 s**, contra 3.3 s en la torre. Mismo
número de pruebas, tres veces más lento, que es lo que se espera de ese CPU.

---

## Lo que ya está listo en el repo

| Pieza | Dónde | Qué lo prueba |
|---|---|---|
| La unidad de systemd | `scripts/systemd/continental-web.service` | `tests/test_despliegue.py` (7 casos) |
| El script de despliegue | `scripts/desplegar.sh` | `tests/test_despliegue.py` (8 casos) |
| `--servicio` sin navegador y sin mudarse de puerto | `iniciar.py` | `tests/test_despliegue.py` (4 casos) |
| La interfaz de escucha, configurable | `iniciar.py`, `.env.example` | `tests/test_despliegue.py` (3 casos) |
| LF y no CRLF en `.sh` y `.service` | los archivos mismos | `tests/test_compila.py` |
| El porqué de la interfaz | `docs/decisiones/0005-*` | — |
| El lote nocturno y su timer | `scripts/systemd/continental-lote.{service,timer}` | `tests/test_lote.py` (14 casos) |
| El lote mismo | `src/continental/lote.py` | `tests/test_lote.py` (40 casos) |
| El porqué de la hora y del tope | `docs/decisiones/0006-*` | — |
| El latido a Uptime Kuma | `src/continental/latido.py` | `tests/test_latido.py` (34 casos) |
| La quinta tabla, `pedidos.corrida_del_lote` | `sql/crear_tablas.sql`, `sql/migraciones/0004-*` | `tests/test_motivos.py` |
| El porqué de la quinta tabla | `docs/decisiones/0007-*` | — |

---

## Parte A — en atlas, por ssh (la puede hacer una persona con la llave)

Nada de esto lo hizo el agente del ticket 16: **escribir en atlas estaba
prohibido** porque ahí corre Marlowe en producción.

### A.1 — Un remoto de git, primero

- [x] Hecho el 2026-09-19: `LeFarfane/continental` en GitHub, **privado**, con
      `main` por omisión.

**Se hizo como Marlowe, no como farmacia-data.** Este documento decía antes que
sería un repo bare en atlas más un GitHub, con `origin` empujando a los dos a
la vez. Se descartó al ver que Marlowe ya resuelve lo mismo con una pieza
menos: un bare en atlas es una segunda fuente de verdad que hay que mantener en
sincronía a mano, y el de farmacia-data existe por su historia, no porque sea
mejor.

Privado porque lleva el gateway de la red Docker, la IP de atlas, el nombre del
rol de Postgres y el enrutamiento del túnel. Ninguno es secreto por separado;
juntos son el mapa de cómo entrar.

**Dos llaves, con permisos distintos a propósito:**

| Quién | Llave | Alcance | Permiso |
|---|---|---|---|
| atlas | deploy key `id_ed25519_continental_deploy` | solo este repo | **lectura** |
| la torre | deploy key con la pública de `eddie@torre` | solo este repo | escritura |

Atlas despliega, no publica: si esa máquina se ve comprometida, lo que se filtra
es lectura de un repo. La mitad privada de su llave se generó **en atlas** y no
sale de ahí.

**Una deploy key de GitHub sirve a un solo repo**, así que hace falta un alias
de ssh por repo —es lo que elige la llave correcta—. Por eso el remoto en atlas
dice `git@github-continental:` y no `git@github.com:`. El bloque vive en
`~/.ssh/config` de atlas, junto al `github-marlowe` que ya estaba:

```
Host github-continental
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_continental_deploy
    IdentitiesOnly yes
```

**Comprobar la llave antes de clonar.** GitHub contesta con el nombre del repo
al que está amarrada, así que es lo único que caza de una vez la llave pegada
en el repo equivocado, en vez de que eso aparezca como un `git clone` que falla
sin decir por qué:

```bash
ssh -T git@github-continental
# Hi LeFarfane/continental! You've successfully authenticated...
```

> **Trampa medida el 2026-09-19, para cuando toque el próximo repo:** desde la
> torre, empujar por HTTPS falla dos veces seguidas. Primero el almacén de
> credenciales de Windows (`fatal: Unable to persist credentials with the
> 'wincredman' credential store`), y aunque eso se arregle, **GitHub no acepta
> contraseñas desde 2021**. El camino que sí funciona es ssh.

### A.2 — Clonar, plano

- [x] Hecho el 2026-09-19. El repo va en `~/proyectos/Continental`, **hermano** de `~/proyectos/Marlowe`
      y de `~/proyectos/Farmacia`. En la torre cuelga de `Farmacia/`, en atlas
      **no**. La unidad de systemd tiene esa ruta escrita en tres lugares
      (`WorkingDirectory`, `PYTHONPATH`, `ExecStart`).

```bash
cd ~/proyectos && git clone git@github-continental:LeFarfane/continental.git Continental
cd Continental
```

### A.3 — El venv, normal

- [x] Hecho el 2026-09-19. **Sin `--system-site-packages`**, al revés de lo que
      decía antes este documento.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest -q      # el suite entero, antes de nada más
```

Aquí decía que `--system-site-packages` era "la regla de la casa" de atlas,
porque su CPU es un Athlon II X4 de 2010 **sin SSSE3** y los wheels de PyPI con
código vectorizado mueren ahí con `Illegal instruction`. **Medido el
2026-09-19: no es la regla de la casa.** El venv de Marlowe en atlas tiene
`include-system-site-packages = false` y trae `psycopg2-binary` de PyPI.

La causa sí es cierta —numpy, pandas y rapidfuzz mueren ahí—, pero Continental
no trae ninguno y no los va a traer. Medido el mismo día dentro de este venv,
en atlas:

| Paquete | Versión | Importa |
|---|---|---|
| `psycopg2-binary` | 2.9.13 | sí |
| `pydantic_core` | 2.46.5 | sí |

El plan B que figuraba aquí —`sudo apt install python3-psycopg2` y quitarlo de
`pyproject.toml`— **se retira**: ese paquete no está instalado en atlas, así
que el `--system-site-packages` no habría encontrado nada que heredar. La red
de seguridad no estaba conectada.

### A.4 — El `.env` — ✅ **hecho el 2026-09-20**

- [x] `.env` con `WAREHOUSE_URL` y `CODIGO_NEGOCIO`. **`CONTINENTAL_HOST` se
      queda comentado**: lo fija la unidad de systemd, y lo del entorno gana
      sobre lo del `.env`.

`python -m continental.verificar` entra con las credenciales del servicio y lee
las cinco tablas de `marts` y las cinco de `pedidos`. Los dos `··` que reporta
son pendientes conocidos que se encienden solos: `clase_abc` cuando exista la
columna (ADR 0018 de farmacia-data) y `enviado_por` cuando llegue el ticket 21.

> ### ⚠️ La trampa de la contraseña mordió, y así se ve por dentro
>
> Entre A.5 y A.4 el rol quedó con **una contraseña distinta** de la del
> `.env`. El síntoma es `FATAL: password authentication failed for user
> "continental"` dentro de un rastro de SQLAlchemy de cien líneas, y **parece
> un problema de red**: psycopg2 intenta primero `::1`, que contesta
> *Connection refused*, y esa es la primera línea que uno lee.
>
> Antes de tocar nada conviene descartar lo mecánico, que es rápido y explica
> la mayoría de los casos: que la contraseña lleve caracteres que una URL tiene
> que escapar (`@ : / # %`), que al `.env` se le haya colado un `\r`, un
> espacio final, comillas o un BOM, o que el rol se haya quedado sin
> contraseña —`select rolpassword is null from pg_authid`—. Si todo eso está
> limpio, lo que queda es que las dos mitades no coinciden.
>
> **No se arregla volviendo a correr `crear_rol.sql`**: es idempotente y, si
> encuentra el rol ya creado, no le toca la contraseña a propósito. Se arregla
> con un `ALTER ROLE` aparte, y lo correcto es **leer la contraseña del `.env`
> en vez de teclearla**, para que las dos mitades coincidan por construcción y
> no por cuidado. Desde `~/proyectos/Continental`:
>
> ```bash
> CLAVE=$(./.venv/bin/python -c 'from urllib.parse import urlsplit; l=next(x for x in open(".env") if x.startswith("WAREHOUSE_URL=")); print(urlsplit(l.split("=",1)[1].strip()).password)')
> printf "ALTER ROLE continental PASSWORD '%s';\n" "$CLAVE" | docker exec -i farmacia_warehouse psql -U farmacia -d farmacia -v ON_ERROR_STOP=1
> unset CLAVE && ./.venv/bin/python -m continental.verificar
> ```
>
> Va por entrada estándar a propósito: así la contraseña no entra al historial
> del shell ni se asoma en `ps`.

### A.5 — El rol y las tablas en Postgres — ✅ **hecho el 2026-09-20**

- [x] `sql/crear_tablas.sql`, `sql/crear_rol.sql` y `sql/verificar_rol.sql`, en
      ese orden, con credenciales de dueño

Veredicto de la primera corrida de verdad: **25 de 26 comprobaciones pasan, con
1 aviso conocido**, y `verificar_rol.sql` sale con 0. El esquema `pedidos`
existe con sus cinco tablas, las posee `farmacia` —no `continental`—, el rol
escribe las suyas, lee las cinco de `marts` y no puede crear ni borrar nada.

**Las migraciones `0001` a `0005` NO se corrieron, y no hacía falta.** Están
para una base que se creó antes que ellas; ésta se creó después, y
`crear_tablas.sql` ya trae lo que las cinco agregan —verificado antes de correr
nada: las cinco tablas, `pedido.proveedor_id` admitiendo nulos con `proveedor`
NOT NULL al lado, `ux_pedido_proveedor` sobre `(pedido_sugerido_id, proveedor)`
y `fk_renglon_pedido` con sus tres columnas—. Un solo `psql` y ya. Lo de abajo
sigue valiendo para cualquier instalación vieja.

> **Las dos migraciones que CREAN una tabla exigen volver a correr
> `crear_rol.sql`, y es el olvido más caro de este esquema.** Un GRANT no se
> puede dar sobre una tabla que todavía no existía. La `0003` estrena
> `pedidos.precio_de_proveedor` y la `0004` estrena `pedidos.corrida_del_lote`
> (ticket 19). El síntoma de la segunda es el peor de los dos porque **nadie lo
> ve**: el lote de las 22:00 rebota con "permission denied for table
> corrida_del_lote", la corrida **no** se aborta —los precios de esa noche se
> guardan igual—, y lo único que pasa es que a la mañana la pantalla dice *"el
> lote no corrió sobre esta lista"* sobre una noche en la que sí corrió. Es la
> ausencia de esa fila lo que significa eso. Las comprobaciones 4 y 6 del
> verificador lo cazan.

> **El aviso que queda es el 17 y se deja a propósito.** `continental` puede
> crear tablas TEMPORALES, porque el `TEMPORARY` le llega por `PUBLIC` sobre la
> base. Quitarlo sería `REVOKE TEMPORARY ... FROM PUBLIC`, que le pega a dbt y a
> Metabase por igual: es decisión de farmacia-data, no de Continental. Una tabla
> temporal vive en la sesión, no puede leer nada que el rol no lea ya, y
> desaparece al desconectarse.

> **El verificador tenía un `[MAL]` que no lo era, y se arregló ese día
> (`f445e21`).** La comprobación 23 armaba su *obtenido* con un `string_agg`
> ordenado `DESC` y lo comparaba contra un *esperado* escrito en orden
> ascendente: las dos cadenas decían lo mismo y no coincidían nunca. El script
> salió con código 3 sobre un esquema impecable. Si un verificador de éstos
> vuelve a dar `[MAL]`, **lee las dos celdas antes de tocar la base**: puede
> estar mintiendo. Ahora hay una prueba que impide que otro `string_agg` del
> archivo ordene descendente.

### A.6 — Instalar la unidad

- [ ] Y verificarla **antes** de encenderla: `systemd-analyze verify` es lo que
      delató en Marlowe que `StartLimitIntervalSec` estaba en la sección
      equivocada y systemd lo ignoraba en silencio.

```bash
sudo cp scripts/systemd/continental-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemd-analyze verify continental-web.service     # no debe decir nada
sudo systemctl enable --now continental-web.service
systemctl status continental-web.service
```

### A.7 — Comprobar que escucha donde se cree

- [ ] Tiene que decir `172.19.0.1:8585`, no `127.0.0.1` y no `0.0.0.0`:

```bash
ss -ltn | grep 8585
curl -s http://172.19.0.1:8585/api/salud
```

> Si `ss` no muestra nada y el journal dice "Cannot assign requested address",
> el gateway de `borde` cambió. Volver a medirlo y poner el valor nuevo en la
> unidad **y** en el paso B.1:
> ```bash
> docker network inspect borde --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}'
> ```

### A.8 — Instalar el lote nocturno (ticket 18)

Es lo que hace que **en la mañana la lista ya traiga precios sin que nadie los
pida**. Va después de A.6 porque comparte el venv y el `.env`, y **puede ir
antes de la parte B**: el lote no escucha en ningún puerto y no pasa por el
túnel. Lo que necesita es Postgres y Doyle, no Cloudflare.

- [ ] Instalar las dos unidades y **habilitar el TIMER, no el servicio**. Un
      `enable` sobre el servicio no hace nada útil —no tiene `[Install]`, a
      propósito— y dejaría el lote sin disparar sin un solo error que ver.

```bash
sudo cp scripts/systemd/continental-lote.service /etc/systemd/system/
sudo cp scripts/systemd/continental-lote.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemd-analyze verify continental-lote.service   # no debe decir nada
sudo systemctl enable --now continental-lote.timer
systemctl list-timers continental-lote.timer           # ¿cuándo dispara?
```

- [ ] **Probarlo a mano antes de dejarlo solo**, con un tope corto para no
      pasarse una hora mirando:

```bash
cd ~/proyectos/Continental
PYTHONPATH=src .venv/bin/python -m continental.lote --tope-minutos 5
```

- [ ] Y a la mañana siguiente, la bitácora de la corrida — **es aquí donde
      vive**, no en una tabla (ver `docs/decisiones/0006-*`):

```bash
journalctl -u continental-lote -n 200 --no-pager
```

> **La hora es 22:00 lun-vie, y no es independiente.** Son noventa minutos
> después de `farmacia-diario.timer` (la cadena de farmacia-data, lun-vie
> 20:30), porque la lista del día se arma con las ventas que esa cadena acaba
> de meter. **Si la cadena se mueve, esto se mueve en el mismo movimiento** —
> hilo abierto 5 de `HANDOVER.md`: si el respaldo de SICAR pasa a las ~20:15,
> la cadena va a las 21:00 y esto a las 22:30. Moverla a ella y no a esto
> dejaría el lote armando la lista con las ventas de ayer, sin fallar y sin
> avisar.

> **Dos casillas del ticket 18 quedan abiertas aquí y no se cierran
> instalando nada:** el orden por clase ABC necesita la columna
> `clase_abc` en `marts.dim_producto` (ADR 0018 de farmacia-data, aceptado y
> sin implementar), y el navegador reutilizado por proveedor vive en Doyle (su
> ADR 0008, también sin hacer). El paso 6 del despliegue imprime la primera
> como PENDIENTE en cada corrida, con la única línea que hay que cambiar el
> día que la columna exista.

---

## Parte B — en el dashboard de Cloudflare (esto NO se puede hacer por ssh)

**Por qué no:** el túnel de atlas es *remotely-managed*. El contenedor
`borde_tunel` corre como `tunnel --no-autoupdate run`, **sin `config.yml`
local**: su enrutamiento vive en el panel de Cloudflare Zero Trust y se
descarga al arrancar. No hay ningún archivo en atlas que editar, así que esto
lo hace una persona con la cuenta, en el navegador. Es lo mismo que le pasó a
Marlowe y está escrito en su unidad desde el 2026-09-06.

**El orden importa: primero B.1 y luego B.2, sin publicar nada en medio.**
Entre el momento en que existe el Public Hostname y el momento en que existe la
política de Access, `farmacia.farfanlab.uk` está **abierto a internet**.
Continental no tiene autenticación propia (regla 2 de `CLAUDE.md`) y el correo
del encabezado es una firma, no un permiso (regla 3): quien llegue sin pasar
por Access se lo inventa. Que la ventana entre los dos pasos dure un minuto y
no una tarde.

### B.1 — La ruta del túnel

- [ ] **Zero Trust → Networks → Tunnels →** el túnel de atlas (el mismo que ya
      sirve `stadistics.farfanlab.uk`) **→ Public Hostname → Add a public
      hostname**, con estos valores:

| Campo | Valor |
|---|---|
| Subdomain | `farmacia` |
| Domain | `farfanlab.uk` |
| Path | *(vacío)* |
| Type | `HTTP` |
| URL | `172.19.0.1:8585` |

- [ ] **`HTTP`, no `HTTPS`.** Continental habla HTTP plano; el TLS lo termina
      Cloudflare. Poner `HTTPS` da un 502 que parece un problema del servicio.
- [ ] **`172.19.0.1:8585`, no `localhost:8585`.** Para el contenedor del túnel
      `localhost` es él mismo. Ese error exacto le costó a Marlowe un 502 el
      2026-09-06, y el porqué está en `docs/decisiones/0005-*`.

### B.2 — Access delante, inmediatamente después

- [ ] **Zero Trust → Access → Applications → Add an application →
      Self-hosted**:

| Campo | Valor |
|---|---|
| Application name | `Continental` |
| Session duration | lo mismo que Metabase |
| Subdomain / Domain | `farmacia` / `farfanlab.uk` |

- [ ] Y una política: **Action `Allow`**, regla **Include → Emails** con los
      correos del dueño y del encargado. Esos correos son los que van a
      aparecer en la pantalla como "Entrando como": es la firma de quién está
      trabajando.
- [ ] **No usar "Bypass"** ni dejar la aplicación sin política. Esto escribe a
      producción (pedidos y renglones en Postgres), no es un tablero de solo
      lectura: necesita Access igual que Metabase, no menos.

### B.3 — Comprobarlo de punta a punta

- [ ] Entrar a `https://farmacia.farfanlab.uk` desde fuera de la casa, pasar
      el login de Access, y **mirar la sección "Estado" de la pantalla**: tiene
      que decir `Entrando como` con el correo con el que se entró, no
      `sin-identificar`. Si dice `sin-identificar`, el encabezado
      `Cf-Access-Authenticated-User-Email` no está llegando: casi siempre es
      que la aplicación de Access quedó sobre otro dominio que el del Public
      Hostname.

---

## Parte C — a partir de aquí, desplegar es un comando

Con A y B hechos, cada versión nueva se despliega así, desde la torre:

```bash
git push
ssh -t eddie@192.168.100.14 '~/proyectos/Continental/scripts/desplegar.sh'
```

El `-t` es para que `sudo` pueda pedir la contraseña: el script corre como
`eddie` y solo el reinicio necesita root.

`desplegar.sh` hace seis pasos y **se detiene en el primero que falla**:

1. `git pull`
2. compila **todos** los módulos, incluido `iniciar.py` —el archivo que el
   servicio ejecuta y que ninguna prueba importa—
3. corre el suite completo con el venv de atlas
4. reinicia, **solo si 2 y 3 pasaron**, limpiando antes un `failed` por límite
   de reinicios
5. comprueba por HTTP que quedó vivo, por la misma interfaz y el mismo puerto a
   los que apunta el túnel
6. corre `python -m continental.verificar`: los invariantes sobre los **datos**
   de producción (ticket 17)

El orden es el punto entero. El 2026-09-08 Marlowe desplegó un `app.py` que no
compilaba con "pull, reinicia y ojalá": el servicio entró en bucle de reinicio
y el dueño estuvo corrigiendo enlaces contra un servidor que no existía.

**El paso 6 pregunta otra cosa que los cinco anteriores, y por eso va al
final.** Del 1 al 5 dicen si el código quedó bien desplegado; el 6 dice si lo
que hay en la base está sano: que no haya dos listas abiertas del mismo día,
que ningún renglón en tránsito se haya quedado sin su pedido, y que el rol
todavía pueda leer las cinco tablas de `marts` —lo que `dbt build` se lleva por
delante cada noche a las 20:30—. **Un paso 6 rojo no es un despliegue fallido**:
el servicio ya contestó en el paso 5. Lo que está roto son los datos, y el
propio script lo dice con esas palabras para que nadie intente deshacer un
despliegue que no hace falta deshacer. Cada falla sale con el comando que la
repara; el verificador **señala y no repara**, a propósito.

**El despliegue no toca el lote nocturno, y no hace falta.**
`continental-lote.service` es `Type=oneshot`: cada noche arranca un proceso
nuevo desde el repo, así que un `git pull` a las tres de la tarde ya cambia lo
que corre a las 22:00 sin reiniciar nada. Lo único que hay que volver a copiar
a `/etc/systemd/system/` es la unidad o el timer **si cambian esos archivos**,
y entonces sí: `daemon-reload`.

No confundirlo con `sql/verificar_rol.sql`, que también "verifica": ése mira la
**forma** de la base (que el rol no tenga `CREATE`, que los CHECK sigan
puestos), se corre **a mano y una vez** con credenciales de dueño, y pregunta
leyendo el catálogo. El paso 6 mira los **datos**, corre en cada despliegue con
el rol acotado, y comprueba los permisos **haciendo un `SELECT 1`** sobre cada
tabla. La cabecera de `src/continental/verificar.py` lo tiene en una tabla.

---

## Parte D — el monitor de Uptime Kuma (esto lo hace el dueño, en la interfaz de Kuma)

**Qué caza este monitor, y por qué ninguna otra cosa lo caza:** un lote que
truena deja el journal en rojo y `continental-lote.service` en `failed`. Un
lote que **no corre** —atlas apagado a las 22:00, el timer sin habilitar, un
`daemon-reload` a medias— no deja nada en ningún sitio, y a la mañana la lista
sin precios se ve igual que una noche en la que Doyle no contestó. **El
silencio es el modo de falla que de verdad muerde**, y Kuma es lo único de esta
casa que se queja cuando no pasa nada.

**MONITOR PROPIO, y eso es la casilla entera.** El ticket lo pide con su razón
dentro: *"si compartieran monitor, una noche sin lote no avisaría nada"*. Kuma
ya vigila la cadena de farmacia-data y a Marlowe; si este latido entrara por el
mismo *push monitor*, la cadena de las 20:30 seguiría latiendo todas las noches
y el monitor se vería verde con el lote de las 22:00 muerto desde hace una
semana. Un monitor compartido mide "algo de esta casa sigue vivo", que no es
una pregunta que nadie se haga.

Medido en atlas el 2026-09-19, en solo lectura:

- Kuma corre como el contenedor **`borde_kuma`**, publicado en
  **`127.0.0.1:3002`** (`3002->3001/tcp`), `Up 12 days (healthy)`.
- Los otros dos ya tienen el suyo, con su propia variable: `KUMA_PUSH_URL` en
  farmacia-data y `KUMA_PUSH_URL_MARLOWE` en Marlowe. Tres nombres distintos
  son tres URLs con tres tokens, que es lo que los vuelve tres monitores.

**Nada de esto lo hizo el agente del ticket 19, a propósito:** crear un monitor
es escribir en la Kuma que Marlowe y la cadena de farmacia-data comparten, y un
latido de prueba escribiría en el historial de un monitor que alguien mira.

### D.1 — Crear el push monitor

- [ ] Entrar a Kuma (`http://127.0.0.1:3002` desde atlas, o por el túnel si lo
      tiene) y **Add New Monitor** con estos valores:

| Campo | Valor | Por qué |
|---|---|---|
| Monitor Type | **Push** | Es el lote quien avisa; Kuma no puede consultarlo, porque el lote no escucha en ningún puerto |
| Friendly Name | `Continental — lote nocturno` | Que se distinga del de la cadena y del de Marlowe de un vistazo |
| Heartbeat Interval | **93600** s (26 h) | El lote corre **lunes a viernes a las 22:00**. Con 24 h justas, el lunes por la noche sería siempre un falso rojo, porque el último latido sería el del viernes. Ver D.3 |
| Retries | 0 | Un push no se reintenta: o llegó o no llegó |
| Resend Notification if Down | 1 | Que avise una vez y no cada intervalo |

- [ ] Copiar la **Push URL** que Kuma genera (`http://.../api/push/<token>`).

### D.2 — El token es un secreto y va en el `.env`

- [ ] Ponerlo en `~/proyectos/Continental/.env` como
      `KUMA_PUSH_URL_CONTINENTAL=...`, y **en ningún otro sitio**.

```bash
# en atlas, desde ~/proyectos/Continental
echo 'KUMA_PUSH_URL_CONTINENTAL=http://127.0.0.1:3002/api/push/EL_TOKEN' >> .env
```

**Quien tenga esa URL puede decirle a Kuma que todo está bien**, que es
justamente la afirmación que el monitor existe para hacer honesta. Por eso va
en `.env` —que está en `.gitignore`— y **nunca** en `config/continental.yml`,
que sí se versiona. Es la misma frontera que ya separa `WAREHOUSE_URL` del
YAML, y hay una prueba que comprueba que el nombre de la variable no aparezca
en el YAML.

- [ ] Probarlo a mano, **una vez**, con un tope corto — y mirar Kuma después:

```bash
cd ~/proyectos/Continental
PYTHONPATH=src .venv/bin/python -m continental.lote --tope-minutos 5
journalctl -u continental-lote -n 50 --no-pager | grep -i latido
```

Si la variable falta, el lote **no falla**: escribe un `WARNING` que la nombra
y sigue. Si Kuma no contesta, tampoco: escribe otro `WARNING` con el **tipo**
de la falla —nunca el texto, porque el texto de un error de `httpx` lleva la
URL completa y la URL completa **es** el token— y la corrida vale lo que valía.
*"Marcar como rota una corrida buena es peor que perderse un latido."*

### D.3 — Qué se va a ver, para no confundir un rojo bueno con uno malo

- [ ] Dejarlo una semana y mirar el historial. Lo que tiene que pasar:

| Situación | Qué manda el lote | Cómo se ve en Kuma |
|---|---|---|
| recorrió la lista entera | `up` | verde |
| **se detuvo al tope de 60 min** | `up` | **verde, y es lo correcto**: detenerse es lo que se le pide (ticket 18). Un rojo todas las noches por el tope es un monitor que nadie vuelve a mirar |
| no hubo ventas que consultar | `up` | verde. La farmacia cierra los domingos |
| la corrida se cortó | `down` | rojo **ahora**, sin esperar al intervalo |
| **el lote no corrió** | nada | rojo cuando vence el intervalo. **Esto es lo que el monitor existe para cazar** |

> **El fin de semana es el caso que va a confundir.** El timer es
> `OnCalendar=Mon-Fri 22:00` sin `Persistent=true` (ADR 0006), así que del
> viernes 22:00 al lunes 22:00 pasan 72 h sin latido. Con el intervalo de 26 h
> de D.1, Kuma se pone rojo el sábado por la madrugada y se queda así hasta el
> lunes por la noche, **todas las semanas**. Hay dos salidas y las dos son
> decisiones del dueño, así que se dejan escritas en vez de elegidas aquí:
>
> - **Silenciar el monitor los fines de semana** (Kuma tiene ventanas de
>   mantenimiento: *Maintenance → sábado y domingo*). Es lo que conserva el
>   aviso útil de lunes a viernes.
> - **Subir el intervalo a 73 h** y perder la capacidad de distinguir "no
>   corrió el martes" hasta el viernes. **No se recomienda**: convierte el
>   monitor en ruido de fondo, que es exactamente lo que la casilla del ticket
>   quería evitar.
>
> Sin ninguna de las dos, el rojo del fin de semana enseña a ignorar el rojo, y
> entonces el lunes que el lote de verdad no corra nadie lo va a mirar.

---

## Diagnóstico rápido

| Síntoma | Causa más probable |
|---|---|
| 502 en `farmacia.farfanlab.uk`, servicio `active (running)` | El Public Hostname apunta a `localhost` en vez de `172.19.0.1`, o el gateway cambió |
| La unidad no arranca: "Cannot assign requested address" | Se recreó la red `borde` y el gateway ya no es `172.19.0.1` (A.7) |
| `active (running)` pero nada contesta en el 8585 | Arrancó en otro puerto. **No debería poder**: `--servicio` se niega. Si pasa, mirar `ExecStart` |
| La pantalla dice `sin-identificar` entrando por el túnel | Falta la aplicación de Access, o está sobre otro dominio (B.3) |
| El despliegue se detiene en "1/6 git pull" | No hay remoto configurado (A.1) |
| El despliegue se detiene en "6/6 invariantes" | Los datos, no el código: el servicio ya está arriba. Lee cada falla con su comando en la salida del paso 6 |
| El lote nunca dispara, y `systemctl status continental-lote` dice `inactive (dead)` | Se habilitó el servicio en vez del timer (A.8) |
| El lote muere a los 90 s con `Failed with result 'timeout'` | Falta o se borró `TimeoutStartSec` de la unidad: `Type=oneshot` usa el valor por omisión de systemd |
| A la mañana la lista no tiene precios y el journal del lote está vacío | El timer no está habilitado, o atlas estuvo apagado a las 22:00 (no es `Persistent`, a propósito) |
| El lote dice "se acabó el tiempo" todas las noches | No es una falla: mira el resumen del journal. Antes de subir `pedido.tope_lote_minutos`, ver la condición de disparo del ADR 0006 |
| "permission denied for table ..." a las 8 de la mañana | `dbt build` recreó los modelos de `marts` y se llevó los GRANT. Ver el final de `sql/crear_rol.sql` |
| La pantalla dice "el lote no corrió sobre esta lista" y el journal dice que sí corrió | Falta el GRANT sobre `pedidos.corrida_del_lote`: se corrió la migración `0004` y no `crear_rol.sql` después (A.5). Buscar "permission denied for table corrida_del_lote" en el journal de esa noche |
| El journal del lote dice "NO se mandó latido a Uptime Kuma: falta KUMA_PUSH_URL_CONTINENTAL" | El monitor no está creado o el token no está en el `.env` (D.1 y D.2). **No es una falla de la corrida** |
| El monitor de Kuma se pone rojo todos los sábados | Es el fin de semana: el timer es `Mon-Fri`. Ver el aviso de D.3 — se silencia con una ventana de mantenimiento, no subiendo el intervalo |
| El monitor de Kuma se ve verde y la lista no tiene precios | El lote corrió y se detuvo al tope: eso late en verde **a propósito** (D.3). El número está en el journal y arriba de la tabla de la pantalla |
