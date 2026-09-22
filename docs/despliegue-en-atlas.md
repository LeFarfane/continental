# Desplegar Continental en atlas

Cómo `farmacia.farfanlab.uk` llega a existir, paso a paso y en orden.

**Estado al 2026-09-20: hecha toda la parte A menos A.8.** Continental corre en
atlas, escucha en `172.19.0.1:8585` y lee el almacén con su rol acotado. Lo que
queda es **la parte B, que se hace en el dashboard de Cloudflare y no por ssh**,
y **A.8, el lote nocturno, que espera a que Doyle esté en atlas** (ADR 0008 de
Doyle, pendiente 6 de `pendientes.md`).

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
| El script de despliegue | `scripts/desplegar.sh` | `tests/test_despliegue.py` (20 casos; 4 corren el paso 1 de verdad en un repo temporal con un bash real) |
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
| La verificación diaria y su timer | `scripts/systemd/continental-verificar.{service,timer}` | `tests/test_verificar_timer.py` (17 casos) |
| `--latido` de `continental.verificar` y el segundo monitor de Kuma | `src/continental/verificar.py`, `src/continental/latido.py` | `tests/test_verificar.py`, `tests/test_latido.py` |
| El porqué de la verificación diaria | ADR 0017, enmienda 2026-09-21 | — |

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
las cinco tablas de `marts` y las cinco de `pedidos`. Los `··` que reporta son
pendientes conocidos que se encienden solos: `enviado_por` cuando llegue el
ticket 21. (El de `clase_abc` se apagó: la columna existe desde el 2026-09-20,
farmacia-data `c989ecb`, y Continental la lee.)

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

### A.6 — Instalar la unidad — ✅ **hecho el 2026-09-20**

- [x] Verificada **antes** de encenderla. `systemd-analyze verify` **no dijo
      nada**, que es lo que se busca: es lo que delató en Marlowe que
      `StartLimitIntervalSec` estaba en la sección equivocada y systemd lo
      ignoraba en silencio.

```bash
sudo cp scripts/systemd/continental-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemd-analyze verify continental-web.service     # no debe decir nada
sudo systemctl enable --now continental-web.service
systemctl status continental-web.service
```

Corriendo desde las 00:56 del 2026-09-20, con `NRestarts=0`.

> **El journal de esta unidad está vacío y no es un síntoma.** `iniciar.py`
> arranca uvicorn con `log_level="warning"`, así que no hay banner de arranque
> ni log de accesos — los avisos y los errores sí viajan. Si buscas confirmar
> que está viva, `systemctl status`, `ss` y `/api/salud` son las respuestas;
> `journalctl -u continental-web` en silencio significa *nada que reportar*, no
> *no arrancó*. (Marlowe se lee igual: su última línea es de septiembre 8.)

### A.7 — Comprobar que escucha donde se cree — ✅ **hecho el 2026-09-20**

- [x] Dice `172.19.0.1:8585` —el gateway de `borde`, no loopback y no
      `0.0.0.0`— y `/api/salud` contesta
      `{"ok":true,"version":"0.1.0","negocio":"farmacia_01",...}`.

```bash
ss -ltn | grep 8585
curl -s http://172.19.0.1:8585/api/salud
```

> **En esa respuesta `"quien"` dice `sin-identificar`, y está bien.** Ese `curl`
> entra por el gateway, no por el túnel, así que no trae
> `Cf-Access-Authenticated-User-Email`. Que diga un correo es lo que hay que
> comprobar en **B.3**, desde fuera; verlo aquí sería el problema, no la
> confirmación.

> Si `ss` no muestra nada y el journal dice "Cannot assign requested address",
> el gateway de `borde` cambió. Volver a medirlo y poner el valor nuevo en la
> unidad **y** en el Public Hostname del paso B.2:
> ```bash
> docker network inspect borde --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}'
> ```

### A.8 — Instalar el lote nocturno (ticket 18)

Es lo que hace que **en la mañana la lista ya traiga precios sin que nadie los
pida**. Va después de A.6 porque comparte el venv y el `.env`, y **puede ir
antes de la parte B**: el lote no escucha en ningún puerto y no pasa por el
túnel. Lo que necesita es Postgres y Doyle, no Cloudflare.

> ### ⏸️ Detenido a propósito el 2026-09-20: falta Doyle
>
> `Doyle no está en atlas` (el 8383 no escucha; es el ADR 0008 de Doyle y el
> pendiente 6). Una corrida sin él **no truena**: marca cada renglón como *no se
> pudo* y lo dice, que es el comportamiento correcto de la regla 4. El problema
> es el latido: `lote.estado_del_latido` manda `ABAJO` **solo** cuando la
> corrida `se interrumpió`, así que una noche entera en la que Doyle nunca
> contestó sale como `ARRIBA`.
>
> Hoy eso no se ve porque `KUMA_PUSH_URL_CONTINENTAL` todavía no existe y el
> lote solo escribe un aviso. El día que exista —parte D—, lo primero que ese
> monitor diría es *"todo bien"* sobre un lote que no pudo preguntarle a nadie.
> Un monitor que empieza mintiendo es peor que no tenerlo: enseña a ignorar el
> verde.
>
> **Orden, entonces:** primero Doyle en atlas; si por lo que sea el lote entra
> antes, que entre **después** del monitor y no antes, para que la primera noche
> rara quede en el historial en vez de pasar en verde.

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

> **Una casilla del ticket 18 queda abierta aquí y no se cierra instalando
> nada:** el navegador reutilizado por proveedor, que vive en Doyle (su ADR
> 0008, sin hacer). La del orden por clase ABC se marcó el 2026-09-21 (la
> columna existe desde farmacia-data `c989ecb`; qué es "cumplido" está en la
> enmienda del ADR 0006).

### A.9 — Instalar la verificación diaria (ADR 0017, enmienda 2026-09-21)

Es lo que hace que un invariante roto **no se quede sin que nadie lo mire
mientras nadie despliega**. `scripts/desplegar.sh` ya corre
`continental.verificar` en su paso 7/7, pero solo cuando alguien despliega; si
pasan varios días sin un `git push`, la base puede llevar días con un
invariante roto sin que nadie se entere hasta la próxima vez que alguien toque
el repo. `continental-verificar.timer` corre esa misma verificación completa
—forma + datos— **todos los días**, con `--latido`, y avisa por su propio
monitor de Kuma.

No depende de A.8 ni del lote: solo necesita Postgres (Docker) y Kuma por
loopback. Se puede instalar **antes** de A.8, o aunque A.8 nunca se instale.

```bash
sudo cp scripts/systemd/continental-verificar.service /etc/systemd/system/
sudo cp scripts/systemd/continental-verificar.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemd-analyze verify continental-verificar.service   # no debe decir nada
sudo systemctl enable --now continental-verificar.timer
systemctl list-timers continental-verificar.timer           # ¿cuándo dispara?
```

- [ ] **Probarla a mano antes de dejarla sola:**

```bash
cd ~/proyectos/Continental
PYTHONPATH=src .venv/bin/python -m continental.verificar --latido
journalctl -u continental-verificar -n 100 --no-pager
```

- [ ] **Crear el segundo monitor de Kuma** (`KUMA_PUSH_URL_VERIFICAR`) antes de
      dejarla corriendo sola, siguiendo el mismo procedimiento que el del lote
      —parte D, más abajo— pero con su propio nombre: si se reutiliza el token
      del lote (`KUMA_PUSH_URL_CONTINENTAL`), una noche en la que los DATOS
      están rotos se ve idéntica a una noche en la que el LOTE no trajo
      precios, y son dos problemas que se arreglan de maneras distintas. Sin
      esta variable, `--latido` **no falla**: escribe un `WARNING` en el
      journal que nombra la variable que falta y sigue —nunca en silencio
      (regla 4 de `CLAUDE.md`).

**La hora es 23:30, todos los días, y no es independiente** (razonado entero
en `scripts/systemd/continental-verificar.timer`): 90 minutos después de la
cadena de las 20:30 —el mismo colchón que ya midió el ADR 0006 para el lote,
porque `dbt build` recrea los permisos de `marts` y una lectura a medio
recrear daría un `down` falso— y después del peor caso del lote (22:00 + hasta
75 min = 23:15), para no competir por el almacén al mismo tiempo. **Si la
cadena se mueve, esto se revisa igual que el lote** (hilo abierto 5 de
`HANDOVER.md`).

**`Persistent=true`, al revés que el lote, y a propósito.** El lote no lo
lleva porque dispararía cuatro navegadores contra portales ajenos en horario
de mostrador si atlas arrancara a media mañana; esta corrida solo lee Postgres
y manda un latido HTTP local, así que perderse un día entero de verificación
por un atlas apagado a las 23:30 es justo el hueco que este timer existe para
cerrar.

**`desplegar.sh` NO instala ni refresca esta unidad, y es a propósito: es el
mismo trato que ya recibe `continental-lote.{service,timer}`.** El script
despliega código, no unidades de systemd —ninguno de sus siete pasos copia un
archivo a `/etc/systemd/system/`—, así que si algún día cambia
`continental-verificar.service` o `.timer`, hay que volver a copiarlo a mano y
correr `daemon-reload`, igual que con la unidad del lote. Lo que sí llega solo
con cada `git pull` es el CÓDIGO que la unidad ejecuta
(`continental.verificar`): como es `Type=oneshot`, cada disparo del timer
arranca un proceso nuevo desde el repo tal como está en ese momento.

---

## Parte B — en el dashboard de Cloudflare (esto NO se puede hacer por ssh)

**Por qué no:** el túnel de atlas es *remotely-managed*. El contenedor
`borde_tunel` corre como `tunnel --no-autoupdate run`, **sin `config.yml`
local**: su enrutamiento vive en el panel de Cloudflare Zero Trust y se
descarga al arrancar. No hay ningún archivo en atlas que editar, así que esto
lo hace una persona con la cuenta, en el navegador. Es lo mismo que le pasó a
Marlowe y está escrito en su unidad desde el 2026-09-06.

**EL ORDEN IMPORTA, Y ES ACCESS PRIMERO.** Si la ruta del túnel existe antes
que la política, `farmacia.farfanlab.uk` queda **abierto a internet** en ese
intervalo. Continental no tiene autenticación propia (regla 2 de `CLAUDE.md`) y
el correo del encabezado es una firma, no un permiso (regla 3): quien llegue
sin pasar por Access se lo inventa. Y esto **escribe** a Postgres; no es un
tablero de solo lectura.

> **Este orden estuvo al revés en este archivo hasta el 2026-09-20**, con la
> instrucción de que la ventana "durara un minuto y no una tarde". No hace
> falta que dure nada: la aplicación de Access se puede crear **antes** de que
> el hostname enrute. Solo exige que el dominio esté activo en la cuenta, y
> `farfanlab.uk` lo está desde que existe `stadistics.farfanlab.uk`. Es además
> lo que recomienda Cloudflare: *"We recommend creating an Access application
> before setting up the tunnel route. If you do not have an Access application
> in place, the published application will be available to anyone on the
> Internet."*
> ([documentación de Cloudflare](https://developers.cloudflare.com/cloudflare-one/applications/configure-apps/self-hosted-public-app/))
>
> Si el panel se quejara de que no hay registro DNS todavía, es una advertencia
> y no un impedimento. Si de verdad no dejara guardar, entonces sí: B.2 y B.1
> pegados, en ese orden y sin nada en medio.

### B.1 — Access, antes de que haya nada que proteger — ✅ **2026-09-20**

- [x] **Zero Trust → Access → Applications → Add an application →
      Self-hosted**:

| Campo | Valor |
|---|---|
| Application name | `Continental` |
| Session duration | lo mismo que Metabase |
| Subdomain / Domain | `farmacia` / `farfanlab.uk` |

- [x] Y una política: **Action `Allow`**, regla **Include → Emails** con los
      correos del dueño y del encargado. Esos correos son los que van a
      aparecer en la pantalla como "Entrando como": es la firma de quién está
      trabajando.
- [x] **No usar "Bypass"** ni dejar la aplicación sin política. Esto escribe a
      producción (pedidos y renglones en Postgres), no es un tablero de solo
      lectura: necesita Access igual que Metabase, no menos.

Hasta aquí no hay nada publicado: la política existe y no hay tráfico que
proteger todavía. Eso es justo lo que se busca.

### B.2 — La ruta del túnel, ya con la puerta puesta — ✅ **2026-09-20**

- [x] **Zero Trust → Networks → Tunnels →** el túnel de atlas (el mismo que ya
      sirve `stadistics.farfanlab.uk`) **→ Public Hostname → Add a public
      hostname**, con estos valores:

| Campo | Valor |
|---|---|
| Subdomain | `farmacia` |
| Domain | `farfanlab.uk` |
| Path | *(vacío)* |
| Type | `HTTP` |
| URL | `172.19.0.1:8585` |

- [x] **`HTTP`, no `HTTPS`.** Continental habla HTTP plano; el TLS lo termina
      Cloudflare. Poner `HTTPS` da un 502 que parece un problema del servicio.
- [x] **`172.19.0.1:8585`, no `localhost:8585`.** Para el contenedor del túnel
      `localhost` es él mismo. Ese error exacto le costó a Marlowe un 502 el
      2026-09-06, y el porqué está en `docs/decisiones/0005-*`. Medido otra vez
      el 2026-09-20: el gateway de `borde` sigue siendo `172.19.0.1`.

En cuanto este paso se guarda, el hostname empieza a resolver **y a exigir
Access desde la primera petición**.

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

`desplegar.sh` hace siete pasos y **se detiene en el primero que falla**:

1. `git pull` — y si el pull cambió el propio `desplegar.sh`, **se vuelve a
   lanzar** con la versión nueva antes de seguir (ver abajo)
2. compila **todos** los módulos, incluido `iniciar.py` —el archivo que el
   servicio ejecuta y que ninguna prueba importa—
3. corre el suite completo con el venv de atlas
4. corre `python -m continental.verificar --forma`: que la base tenga cada
   columna que este código nombra, leída como el rol. **Si falta una, no se
   reinicia nada** y la salida nombra la migración exacta con su comando
   (ADR 0017)
5. reinicia, **solo si 2, 3 y 4 pasaron**, limpiando antes un `failed` por
   límite de reinicios
6. comprueba por HTTP que quedó vivo, por la misma interfaz y el mismo puerto a
   los que apunta el túnel
7. corre `python -m continental.verificar`: los invariantes sobre los **datos**
   de producción (ticket 17)

**El paso 4 es la forma, no los datos, y por eso sí detiene el reinicio.** Las
migraciones sólo agregan columnas: el código anterior sigue sirviendo con la
base migrada, así que el orden es **migrar y después desplegar**. Si el paso 4
se detiene, el código nuevo ya quedó en disco por el `git pull`; el lote de las
22:00 lo va a ver, revisa la forma por su cuenta y **se niega a correr** (sale
distinto de cero y late `down` en Kuma con la migración que falta) hasta que la
base cuadre.

**Si el pull cambia `desplegar.sh`, el script se relanza.** Medido el
2026-09-21: `37abad2` pasó el script de seis pasos a siete (el 4, la forma) y
la corrida en atlas imprimió esto —los rótulos, tal cual—:

```
==> 1/6  git pull
    rama: main
37abad2 (HEAD -> main, origin/pedido-sugerido, origin/main, origin/HEAD) Mezcla verificar-forma-base...
==> 2/6  compilan todos los módulos
...
==> 4/6  reinicio de continental-web.service
```

El pull trajo la versión de siete pasos y **bash siguió corriendo la de
seis**, que ya tenía abierta: el filtro de la forma, que existe para impedir
justo ese reinicio, no corrió en el despliegue que lo traía. Pasaría cada vez
que cambie el script. Desde entonces el paso 1 compara el hash del archivo
antes y después del pull y, si cambió, dice
`==> desplegar.sh cambió con este pull: me vuelvo a lanzar con la versión nueva`
y hace `exec` de la nueva. La relanzada lleva
`CONTINENTAL_DESPLEGAR_RELANZADO=<hash del archivo nuevo>` y **no vuelve a
jalar** (dice `sin git pull: ...`), así que no puede relanzarse otra vez. Si
esa variable queda puesta con un valor que NO es el hash de la corrida
actual —alguien la exportó a mano, o sobró de una sesión vieja—, el script no
se queda callado saltándose el pull para siempre: avisa
`AVISO: ... no coincide con el hash de este archivo` y jala de todos modos. El
porqué de que el pull, la comparación y el `exec` vivan juntos en una función
está en el comentario del script: bash lee el archivo por partes.

> **El primer despliegue que trae este arreglo todavía cae en la trampa**: lo
> corre la versión anterior, que no sabe relanzarse. Ese, córrelo **dos
> veces**; el segundo ya es la versión de siete pasos completa.

El orden es el punto entero. El 2026-09-08 Marlowe desplegó un `app.py` que no
compilaba con "pull, reinicia y ojalá": el servicio entró en bucle de reinicio
y el dueño estuvo corrigiendo enlaces contra un servidor que no existía.

**El paso 7 pregunta otra cosa que los seis anteriores, y por eso va al
final.** Del 1 al 6 dicen si el código quedó bien desplegado; el 7 dice si lo
que hay en la base está sano: que no haya dos listas abiertas del mismo día,
que ningún renglón en tránsito se haya quedado sin su pedido, y que el rol
todavía pueda leer las cinco tablas de `marts` —lo que `dbt build` se lleva por
delante cada noche a las 20:30—. **Un paso 7 rojo no es un despliegue fallido**:
el servicio ya contestó en el paso 6. Lo que está roto son los datos, y el
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
leyendo el catálogo. El paso 7 mira los **datos**, corre en cada despliegue con
el rol acotado, y comprueba los permisos **haciendo un `SELECT 1`** sobre cada
tabla. La cabecera de `src/continental/verificar.py` lo tiene en una tabla.

---

## Parte D — el monitor de Uptime Kuma (esto lo hace el dueño, en la interfaz de Kuma)

**Dos monitores, uno por cada corrida desatendida.** D.1-D.3 son del lote
nocturno; D.4 es de la verificación diaria (ADR 0017, enmienda 2026-09-21).
Los dos son *push* y los dos son PROPIOS —tokens distintos, en variables
distintas de `.env`— por la misma razón: un monitor compartido confundiría
"los datos están rotos" con "no se trajeron precios".

**Qué caza el del lote, y por qué ninguna otra cosa lo caza:** un lote que
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

> ### ⚠️ No copies al vecino: está roto, y medido el 2026-09-20
>
> Aquí se llegó a escribir que los 26 h *"no es inventado: es lo que ya hay en
> casa"*. **No lo hay.** Leyendo la base de Kuma en solo lectura —sin tocar
> ningún token—, esto es lo que hay de verdad:
>
> | Monitor | Tipo | Intervalo | Reintentos | Resend |
> |---|---|---|---|---|
> | Metabase · Sarabia · Túnel ×2 | http | 60 s | 0 | 0 |
> | **Cadena nocturna** | **push** | **60 s** | 0 | 0 |
>
> Ese último es el de farmacia-data, y su cadena late **una vez por noche**
> contra un monitor que espera un latido **cada minuto**. El historial de los
> últimos siete días: **10,073 latidos en rojo contra 5 en verde**, con el
> mensaje *"No heartbeat in the time window"* repetido cada minuto. Lleva rojo
> el **99.95%** del tiempo desde que se creó.
>
> Y en todo Kuma hay **cero ventanas de mantenimiento** definidas.
>
> Un monitor que siempre dice "roto" no dice nada: es el mismo daño que este
> documento describe para el rojo de los sábados, pero permanente. **Copiar esa
> configuración habría hecho nacer al de Continental igual de inútil**, y con
> la apariencia de estar siguiendo lo que ya existe.
>
> **Tampoco hay monitor de Marlowe.** Son cinco en total y ninguno es suyo, así
> que `KUMA_PUSH_URL_MARLOWE` apunta a algo que no existe o no está puesta.
>
> Los valores de abajo siguen siendo los correctos —salen del timer y de cómo
> se comporta Kuma, no de imitar al vecino—. Lo que se cae es la justificación
> por imitación. **Y de paso queda un arreglo pendiente en farmacia-data**:
> su monitor necesita intervalo de 93600 s y su propia ventana, cerrando a las
> **20:25** porque late a las 20:35.

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
| Retries | **2** | Dos horas de gracia al cerrar la ventana del fin de semana. Ver D.3: sin esto, **todos los lunes** son rojo entre las 21:50 y el latido de las 22:0x |
| Heartbeat Retry Interval | **3600** s | 2 × 3600 = esas dos horas |
| Resend Notification if Down | **0** | **`0` es "no reenviar".** Aquí decía `1` con la glosa *"que avise una vez y no cada intervalo"*, y `1` hace justo lo contrario: el campo es *resend every X times*, así que `1` reenvía en **cada** ciclo — cada 26 h. Corregido el 2026-09-20 |

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

> **El fin de semana es el caso que va a confundir, y ya está elegido.** El
> timer es `OnCalendar=Mon-Fri 22:00` sin `Persistent=true` (ADR 0006), así que
> del viernes 22:00 al lunes 22:00 pasan 72 h sin latido. Con el intervalo de
> 26 h de D.1, Kuma se pone rojo el sábado por la madrugada y se queda así hasta
> el lunes por la noche: **70 horas de rojo bueno cada semana**, que es
> literalmente enseñar a ignorar el rojo.
>
> **Una ventana de mantenimiento**, en *Maintenance → Schedule Maintenance*:
>
> | Campo | Valor |
> |---|---|
> | Affected Monitors | **solo** `Continental — lote nocturno` |
> | Strategy | **Cron Expression** |
> | Cron | `0 0 * * 6` (sábado 00:00) |
> | Duration | **4190** minutos → cierra el **lunes a las 21:50** |
> | Timezone | **`America/Mexico_City`, elegida a mano** — ver abajo |
>
> Durante la ventana el monitor se pinta **azul** y no rojo, y no notifica. El
> historial sigue diciendo la verdad —"estos días no se esperaba latido"— en vez
> de mentir en los dos sentidos.
>
> ### La ventana cierra ANTES del disparo, y ahí está todo el truco
>
> Lo cómodo sería extenderla hasta el martes. **No funciona.** En Kuma 1.23 el
> manejador del push **pisa** un latido que llega dentro de una ventana: lo
> guarda como `MAINTENANCE` con el mensaje *"Monitor under maintenance"*, y el
> mensaje real de la corrida se pierde. Peor: el chequeo de un monitor Push
> exige que el latido previo esté en `UP`, y uno guardado como `MAINTENANCE`
> **no levanta el monitor** al cerrar la ventana. O sea que el lunes amanecería
> rojo con el lote habiendo corrido bien, y un `down` de verdad se vería verde.
>
> Por eso cierra a las **21:50**, diez minutos antes del disparo, y por eso
> `Retries = 2`: el hueco entre el cierre y el latido de las 22:0x tiene que
> pasar por `PENDING` —naranja, sin notificar— en vez de por rojo.
>
> **Lo que eso cuesta, dicho:** un `down` explícito ya no pinta rojo al
> instante, sino ~2 h después. A las 22:30 no hay nadie mirando el panel, así
> que el aviso sirve igual a las 00:30 — y el precio de equivocarse del otro
> lado es un falso rojo **cada semana**.
>
> ### ⚠️ La zona horaria está desalineada, y medido
>
> `atlas` corre en `America/Mexico_City`; el contenedor `borde_kuma` **no tiene
> `TZ` definida y corre en UTC** (medido el 2026-09-20: `date` dentro del
> contenedor da 6 h adelante). La ventana trae *"Same as Server Timezone"* por
> omisión, y ese "servidor" es **Kuma, no atlas**: dejarla así correría la
> ventana seis horas —empezaría el sábado a las 06:00 y cerraría el martes a las
> 03:50—, con un rojo el sábado de madrugada y el latido del lunes tragado por
> la ventana. **Elige `America/Mexico_City` a mano**, y confirma que la próxima
> ocurrencia que muestra la interfaz dice sábado 00:00.
>
> Es la misma clase de trampa que el Postgres del contenedor en UTC.
>
> ### Lo que se descartó
>
> - **Subir el intervalo a 73 h**: pierde la capacidad de distinguir "no corrió
>   el martes" hasta el viernes. Convierte el monitor en ruido de fondo.
> - **Recurring – Day of Week (sáb + dom)**: no cubre el lunes de 00:00 a 21:50,
>   o sea 22 h de falso rojo cada lunes. Cubrirlo exige **dos** entradas; el
>   cron lo dice en una.
> - **Poner el timer en `Mon-Sun`** para que late todas las noches: cambia la
>   operación para arreglar el monitor, y manda cuatro navegadores contra los
>   portales del dueño en fin de semana por una lista armada con datos que no se
>   movieron.
> - **Un latido de relleno** el sábado: es mentirle a Kuma. Un `up` que no
>   corresponde a ninguna corrida reintroduce el modo de falla que este monitor
>   existe para evitar.
>
> **Y farmacia-data tiene el mismo problema desde el 2026-09-01** —
> `farmacia-diario.timer` es `Mon..Fri 20:30` con monitor de 26 h— sin una sola
> mención en su repo. O lo viven con el rojo, o alguien lo configuró en la
> interfaz sin dejar rastro. Su ventana sería igual pero cerrando a las **20:25**,
> porque late a las 20:35.

### D.4 — El segundo monitor: la verificación diaria (ADR 0017, enmienda 2026-09-21)

**Mismo procedimiento que D.1-D.2, con su propio nombre y valores más
simples** —simples porque `continental-verificar.timer` dispara **todos los
días**, no lun-vie: nada de la ventana de mantenimiento de D.3 hace falta
aquí, porque no hay ningún fin de semana sin latido que tapar.

- [ ] **Add New Monitor** en Kuma:

| Campo | Valor | Por qué |
|---|---|---|
| Monitor Type | **Push** | Igual que el del lote: es la corrida quien avisa |
| Friendly Name | `Continental — verificación diaria` | Que se distinga del lote y de Marlowe de un vistazo |
| Heartbeat Interval | **90000** s (25 h) | Dispara a las 23:30 todos los días; 25 h y no 24 h justas deja un colchón para que `AccuracySec=1min` del timer, o un reintento de `Restart=on-failure` (hasta 30 s + el próximo intento), nunca produzcan un falso rojo |
| Retries | **1** | Un solo reintento de gracia: a diferencia del lote, aquí no hay fin de semana que tapar, así que no hace falta la ventana de dos horas |
| Heartbeat Retry Interval | **1800** s | 30 minutos de gracia antes del rojo |
| Resend Notification if Down | **0** | Igual que el del lote: `0` es "no reenviar" |

- [ ] Copiar la **Push URL** y ponerla en `~/proyectos/Continental/.env` como
      `KUMA_PUSH_URL_VERIFICAR=...` — **nunca** la misma URL que
      `KUMA_PUSH_URL_CONTINENTAL`, o los dos monitores se confundirían.

```bash
# en atlas, desde ~/proyectos/Continental
echo 'KUMA_PUSH_URL_VERIFICAR=http://127.0.0.1:3002/api/push/EL_OTRO_TOKEN' >> .env
```

- [ ] Probar a mano y mirar Kuma:

```bash
cd ~/proyectos/Continental
PYTHONPATH=src .venv/bin/python -m continental.verificar --latido
journalctl -u continental-verificar -n 50 --no-pager | grep -i latido
```

Si la variable falta, `--latido` **no falla la corrida**: escribe un
`WARNING` que la nombra y el código de salida sigue siendo el de la
verificación misma (0 si todo está en orden, 1 si algo falló). *"Marcar como
rota una corrida buena es peor que perderse un latido"* — la misma regla que
D.2, aplicada al segundo monitor.

**Qué se va a ver, sin la complicación del fin de semana de D.3:**

| Situación | Qué manda `--latido` | Cómo se ve en Kuma |
|---|---|---|
| ninguna comprobación falló (aunque haya pendientes) | `up` | verde |
| al menos una `FALLA` | `down`, con el resumen corto de cada una | rojo, con `Retries=1` de gracia antes de pintarse |
| la verificación no corrió (atlas apagado, timer sin habilitar) | nada | rojo cuando vence el intervalo — esto es lo que el monitor existe para cazar |

---

## Diagnóstico rápido

| Síntoma | Causa más probable |
|---|---|
| 502 en `farmacia.farfanlab.uk`, servicio `active (running)` | El Public Hostname apunta a `localhost` en vez de `172.19.0.1`, o el gateway cambió |
| La unidad no arranca: "Cannot assign requested address" | Se recreó la red `borde` y el gateway ya no es `172.19.0.1` (A.7) |
| `active (running)` pero nada contesta en el 8585 | Arrancó en otro puerto. **No debería poder**: `--servicio` se niega. Si pasa, mirar `ExecStart` |
| La pantalla dice `sin-identificar` entrando por el túnel | Falta la aplicación de Access, o está sobre otro dominio (B.3) |
| El despliegue se detiene en "1/7 git pull" | No hay remoto configurado (A.1) |
| Los rótulos dicen otro total de pasos que el script que acabas de empujar | Corrió la versión vieja del script: el pull la cambió debajo de bash. Desde el 2026-09-21 se relanza sola; si no viste "me vuelvo a lanzar", la que corrió aún no sabía hacerlo: vuelve a correrlo (Parte C) |
| El paso 1 dice "sin git pull" y no trajo nada | Tienes `CONTINENTAL_DESPLEGAR_RELANZADO` exportada en tu sesión con el hash exacto de este archivo (coincidencia real, no debería pasar sola). `unset` y vuelve a correr. Si el valor NO coincide, el script ya lo detecta solo: avisa y jala igual, no hace falta tocar nada |
| El despliegue se detiene en "4/7 la base tiene la forma..." | Falta una migración. El servicio sigue con el código anterior. Corre con credenciales de dueño las que nombra la salida, en su orden, y vuelve a desplegar (ADR 0017) |
| El despliegue se detiene en "7/7 invariantes" | Los datos, no el código: el servicio ya está arriba. Lee cada falla con su comando en la salida del paso 7 |
| El lote sale con 1 sin armar lista y Kuma dice "la base no cuadra" | Se desplegó (o se hizo `pull`) código que nombra columnas que la base no tiene. El journal del lote trae la migración y su comando |
| El lote nunca dispara, y `systemctl status continental-lote` dice `inactive (dead)` | Se habilitó el servicio en vez del timer (A.8) |
| El lote muere a los 90 s con `Failed with result 'timeout'` | Falta o se borró `TimeoutStartSec` de la unidad: `Type=oneshot` usa el valor por omisión de systemd |
| A la mañana la lista no tiene precios y el journal del lote está vacío | El timer no está habilitado, o atlas estuvo apagado a las 22:00 (no es `Persistent`, a propósito) |
| El lote dice "se acabó el tiempo" todas las noches | No es una falla: mira el resumen del journal. Antes de subir `pedido.tope_lote_minutos`, ver la condición de disparo del ADR 0006 |
| "permission denied for table ..." a las 8 de la mañana | `dbt build` recreó los modelos de `marts` y se llevó los GRANT. Ver el final de `sql/crear_rol.sql` |
| La pantalla dice "el lote no corrió sobre esta lista" y el journal dice que sí corrió | Falta el GRANT sobre `pedidos.corrida_del_lote`: se corrió la migración `0004` y no `crear_rol.sql` después (A.5). Buscar "permission denied for table corrida_del_lote" en el journal de esa noche |
| El journal del lote dice "NO se mandó latido a Uptime Kuma: falta KUMA_PUSH_URL_CONTINENTAL" | El monitor no está creado o el token no está en el `.env` (D.1 y D.2). **No es una falla de la corrida** |
| El monitor de Kuma se pone rojo todos los sábados | Es el fin de semana: el timer es `Mon-Fri`. Ver el aviso de D.3 — se silencia con una ventana de mantenimiento, no subiendo el intervalo |
| El monitor de Kuma se ve verde y la lista no tiene precios | El lote corrió y se detuvo al tope: eso late en verde **a propósito** (D.3). El número está en el journal y arriba de la tabla de la pantalla |
| `continental-verificar` nunca dispara, `systemctl status continental-verificar` dice `inactive (dead)` | Se habilitó el servicio en vez del timer (A.9) |
| El journal de `continental-verificar` dice "NO se mandó latido a Uptime Kuma: falta KUMA_PUSH_URL_VERIFICAR" | El segundo monitor no está creado o el token no está en el `.env` (A.9, D.4). **No es una falla de la verificación**: la corrida vale lo que valía |
| El monitor "Continental — verificación diaria" se pone rojo | De verdad hay algo que revisar: `journalctl -u continental-verificar -n 200` trae cada falla con su comando (igual que el paso 7/7 de `desplegar.sh`) |
