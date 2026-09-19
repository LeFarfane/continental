# Desplegar Continental en atlas

Cómo `farmacia.farfanlab.uk` llega a existir, paso a paso y en orden.

**Estado al 2026-09-19: nada de esto está hecho todavía.** Lo que los tickets
16 y 18 dejaron construido y probado es lo que vive en este repo —las tres
unidades de systemd (el servicio web, el lote y su timer), el script de
despliegue, la interfaz de escucha y sus pruebas—. Lo que falta
necesita dos cosas que una sesión de agente no puede hacer: **escribir en
atlas** y **entrar al dashboard de Cloudflare**. Las casillas de abajo están
sin marcar por eso, no por olvido.

Medido en atlas el 2026-09-19, en solo lectura: `~/proyectos/` contiene
`borde`, `Farmacia` (que es farmacia-data), `Marlowe` y `Sarabia`.
**Continental no está ahí**, y este repo todavía no tiene remoto de git.

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

---

## Parte A — en atlas, por ssh (la puede hacer una persona con la llave)

Nada de esto lo hizo el agente del ticket 16: **escribir en atlas estaba
prohibido** porque ahí corre Marlowe en producción.

### A.1 — Un remoto de git, primero

- [ ] Continental no tiene remoto. Sin él no hay `git pull` y `desplegar.sh`
      se detiene en el paso 1 con ese mensaje exacto (comprobado el
      2026-09-19). Es la misma forma que usa farmacia-data: un repo bare en
      atlas del que se despliega, más un GitHub privado como única copia fuera
      de casa, con `origin` empujando a los dos a la vez.

### A.2 — Clonar, plano

- [ ] El repo va en `~/proyectos/Continental`, **hermano** de `~/proyectos/Marlowe`
      y de `~/proyectos/Farmacia`. En la torre cuelga de `Farmacia/`, en atlas
      **no**. La unidad de systemd tiene esa ruta escrita en tres lugares
      (`WorkingDirectory`, `PYTHONPATH`, `ExecStart`).

```bash
cd ~/proyectos && git clone <url-del-remoto> Continental && cd Continental
```

### A.3 — El venv, con `--system-site-packages`

- [ ] El CPU de atlas es un Athlon II X4 de 2010 **sin SSSE3**: los wheels de
      PyPI con código vectorizado mueren ahí con `Illegal instruction`. Por eso
      todos los venvs de atlas se crean así. Continental no trae numpy ni
      pandas ni rapidfuzz —y no los va a traer—, pero la regla de la casa vale
      igual y cuesta cero.

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest -q      # el suite entero, antes de nada más
```

> **Sin verificar:** si `psycopg2-binary` muriera con `Illegal instruction` en
> ese CPU, la salida es `sudo apt install python3-psycopg2` y quitarlo de
> `pyproject.toml`. No se ha podido comprobar desde la torre. `pydantic_core`
> —que FastAPI arrastra— **sí** pasa: medido en atlas el 2026-09-06 con Marlowe.

### A.4 — El `.env`

- [ ] Copiar `.env.example` a `.env` y poner `WAREHOUSE_URL` con la contraseña
      del rol `continental`. **`CONTINENTAL_HOST` no hace falta aquí**: lo fija
      la unidad de systemd, y lo del entorno gana sobre lo del `.env`.

### A.5 — El rol y las tablas en Postgres

- [ ] Los tres pasos del ticket 07, con credenciales de dueño. Están escritos
      completos en `HANDOVER.md` (sección "Lo que todavía no existe"), con sus
      migraciones y el aviso de volver a correr `crear_rol.sql` después de la
      0003. El tercero da el veredicto: 20 comprobaciones y salida distinta de
      cero si algo quedó mal.

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
