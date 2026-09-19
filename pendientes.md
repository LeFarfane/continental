# Pendientes para poner Continental en pie — 2026-09-19

**ESTE ARCHIVO SE BORRA.** No es documentación: es una lista de acarreo con
fecha de caducidad. Cuando las 16 casillas estén marcadas, `pendientes.md`
deja de tener trabajo que describir y **hay que borrarlo del repo**.

No lo vas a tener que recordar: `tests/test_pendientes.py` se pone **rojo** en
cuanto no quede una sola casilla sin marcar, y su mensaje dice exactamente qué
hacer (`git rm pendientes.md`). Es la única prueba del suite que falla porque
las cosas salieron bien, y está escrita así a propósito — el modo de falla que
se quiere evitar es que este archivo siga aquí en diciembre diciendo mentiras.

> **Ojo con el orden:** esa prueba roja detiene `scripts/desplegar.sh` en su
> paso 3. Si marcas la última casilla en atlas, borra el archivo **antes** de
> volver a desplegar, o el despliegue se va a negar por una razón que no es un
> problema.

**La fuente de verdad es Notion**, base `Pendientes`, proyecto `Continental`.
Aquí está lo mismo para tenerlo a la mano dentro del repo, con los comandos
pegables. Si los dos no coinciden, manda Notion.

**Por qué existe esto y no está en `HANDOVER.md`:** el HANDOVER describe **el
estado actual** y no una lista de parches por aplicar —lo dice su primera
línea—. Esto es justo una lista de parches por aplicar.

---

## Lo que se puede empezar hoy

### 1. El remoto de GitHub y el clon en atlas · *bloquea casi todo lo demás*

- [ ] Crear el remoto y la llave de despliegue de solo lectura para atlas
- [ ] Clonar y preparar el entorno

Hoy el repo **no tiene remoto** y `~/proyectos/Continental` en atlas está vacío.

La rama por omisión es `main`, ya adelantada a `pedido-sugerido` el 2026-09-19
(avance directo: 24 commits, cero divergencia). Atlas clona la rama por omisión
y `desplegar.sh` hace `git pull` sobre la que esté: dejarlo parado en una rama
de trabajo es la trampa de que alguien fusione a `main` y atlas siga
desplegando lo viejo sin decir nada.

**En atlas los repos son hermanos y planos** (`~/proyectos/Marlowe`, y
`~/proyectos/Farmacia`, que **es** farmacia-data), al revés que en la torre,
donde están anidados. Verificado el 2026-09-19.

**El repo va privado.** Lleva el gateway de la red Docker, la IP de atlas, el
nombre del rol de Postgres y el enrutamiento del túnel. Nada de eso es un
secreto por sí solo, pero junto es el mapa de cómo entrar.

**La llave de despliegue se genera EN atlas y su mitad privada nunca sale de
ahí.** Se copia el patrón de Marlowe, verificado el 2026-09-19: una deploy key
de GitHub sirve a **un solo repo**, así que hace falta un alias de ssh por repo
—es lo que elige la llave correcta—. Por eso el remoto de Marlowe en atlas dice
`git@github-marlowe:...` y no `git@github.com:...`.

```bash
# 1. en atlas, la llave y su alias (respaldando el config: de él depende Marlowe)
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_continental_deploy -N ""     -C "continental-deploy@atlas"
cp -n ~/.ssh/config ~/.ssh/config.respaldo
cat >> ~/.ssh/config <<'EOF'

Host github-continental
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_continental_deploy
    IdentitiesOnly yes
EOF
cat ~/.ssh/id_ed25519_continental_deploy.pub   # esto se pega en GitHub

# 2. en GitHub: repo privado LeFarfane/Continental, y en
#    Settings -> Deploy keys -> Add, pegar esa línea SIN marcar
#    "Allow write access". Atlas despliega, no publica.

# 3. de vuelta en atlas
cd ~/proyectos && git clone git@github-continental:LeFarfane/Continental.git Continental
cd Continental
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest -q
```

**Sin `--system-site-packages`, y ya no hace falta plan B.** La duda era si
`psycopg2-binary` corre en el Athlon II X4 de 2010 sin SSSE3. **Corre**: medido
el 2026-09-19, el venv de Marlowe en atlas lo trae de PyPI (2.9.12), es un venv
con `include-system-site-packages = false`, y su intérprete lo importa sin
quejarse. El `apt install python3-psycopg2` que antes figuraba aquí como salida
de emergencia no existe: ese paquete no está instalado en atlas y no hace falta.

Atlas alcanza GitHub por ssh (medido el mismo día: el saludo llega y rebota con
`Permission denied (publickey)`, que es la respuesta de una máquina que sí
conecta y todavía no tiene llave).

### 2. Los `grants` de farmacia-data · *sin esto, los permisos se borran solos*

- [ ] `'continental'` en el `config(grants=...)` de `dim_fecha`, `dim_producto`,
      `fct_ventas` y `fct_compras`
- [ ] El bloque `grants` **entero** en `dim_proveedor.sql`, que hoy no tiene
      ninguno

Recrear una tabla en Postgres borra sus permisos, y cada `dbt build` recrea los
modelos de `marts`: **un GRANT dado a mano dura hasta las 20:30 de ese día.**
Marlowe lo midió el 2026-09-06 y reventó con *permission denied*.

`dim_proveedor` importa desde el ticket 20: ahí vive el `pro_id` de SICAR con
el que se identifica el proveedor de un pedido. Medido el 2026-09-19 contra el
almacén: 22 filas, **NADRO=1, VICMA=8, LEVIC=10, y QuePharma no está** — la
farmacia nunca le ha comprado.

El detalle está al final de `sql/crear_rol.sql`.

### 3. Las cuatro sesiones de Doyle · *desbloquea la evidencia que falta*

- [ ] Abrir las cuatro sesiones de proveedor

Medido el 2026-09-19 con `GET /api/sesiones`: las cuatro dicen `guardada`, pero
son marcadores de agosto. Una búsqueda real volvió con los cuatro proveedores
en `error`.

Qué desbloquea, y no es poco:

- Que una fila **con precio** se lea de un portal de verdad. Hoy solo está
  demostrado el camino del hueco.
- **De qué forma llega la existencia en cada portal.** De eso depende la
  decisión más delicada del ticket 14: el proveedor que da precio y **no dice**
  existencia. Si resulta ser el caso ordinario en dos de los cuatro, la marca
  ámbar sería lo que el encargado vea casi siempre y hay que volver a mirarla.
- Si QuePharma encuentra por EAN, que decide si queda fuera de la comparación
  para siempre.

Exige navegador visible en la máquina donde corre Doyle (su ADR 0001).

### 4. La decisión del descarte · *no es trabajo, es una decisión*

- [ ] Decidir si descartar un renglón debe exigir la lista abierta

Hoy conviven dos criterios sobre la misma lista:

| Acción | ¿Exige lista abierta? | Ticket |
|---|---|---|
| Descartar / devolver a abierto | **No** | 10 |
| Ajustar la cantidad | Sí | 11 |
| Elegir proveedor / partir | Sí | 20 |

El ticket 10 nunca pidió esa condición, así que no es un incumplimiento. Pero
de cara al encargado, **una lista cerrada que todavía se deja modificar es una
lista que no está cerrada**. Si decides que sí: `AND s.estado = 'abierto'` al
`WHERE` de `_DESCARTAR` y `_DEVOLVER_A_ABIERTO` en `almacenamiento.py`, con sus
pruebas.

### 5. `clase_abc` en `dim_producto` (ADR 0018 de farmacia-data)

- [ ] Las columnas `clase_abc` y `clase_xyz`, calculadas por dbt en la cadena
      nocturna

Aceptado y sin implementar: verificado el 2026-09-19, `clase_abc` no aparece en
un solo modelo de `dbt/models`.

**Continental ya tiene su mitad lista esperando.** `ordenar_por_importancia` es
función pura, escrita y probada (A, B, C, y al final lo que no se sabe). El día
que la columna exista: `LA_CLASE_ABC_ESTA_EN_DIM_PRODUCTO = True` en
`src/continental/almacen.py`, y `pytest`. Hoy la consulta **ni nombra la
columna**, porque un `select clase_abc` rebotaría con *column does not exist* y
se llevaría por delante la lista del día entera.

Nadie tiene que acordarse: `continental.verificar` lo imprime como PENDIENTE en
cada despliegue.

### 6. Doyle a atlas (ADR 0008 de Doyle) · *lo más incierto de todo*

- [ ] La mudanza, con visor remoto sobre Xvfb

Verificado el 2026-09-19: en `~/proyectos/` de atlas están `borde`, `Farmacia`,
`Marlowe` y `Sarabia`. **Doyle no está ahí.**

Cierra dos casillas que hoy no se pueden cerrar: el lote reutilizando el
navegador por proveedor (ticket 18) y el botón que abre una sesión caducada
(ticket 19) — hoy esa ventana se abriría en la torre, donde no hay nadie
mirando.

Va con interrogantes que nadie ha medido: si el Chrome de Google arranca en ese
CPU de 2010, si VICMA abre ventana ahí, el captcha de LEVIC.

---

## Lo que depende de que el repo esté en atlas

### 7. El DDL, el rol y el verificador · *nada de esto ha tocado una base real*

- [ ] `sql/crear_tablas.sql`
- [ ] `sql/crear_rol.sql`
- [ ] `sql/verificar_rol.sql` — **el que da el veredicto**

Cinco tablas escritas y cero creadas. Se corre **a mano, con credenciales de
dueño**, desde `~/proyectos/Continental`. El rol `continental` no puede hacer
DDL a propósito (ADR 0003).

```bash
docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
    -v ON_ERROR_STOP=1 < sql/crear_tablas.sql
docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
    -v ON_ERROR_STOP=1 -v password="'LA_DEL_.ENV'" < sql/crear_rol.sql
docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
    -v ON_ERROR_STOP=1 < sql/verificar_rol.sql ; echo "salida: $?"
```

El tercero hace 26 comprobaciones y sale con código distinto de cero si algo
quedó mal.

Si la base se creó **antes** del 2026-09-19, correr además las migraciones
`0001` a `0005` de `sql/migraciones/`. Son idempotentes. Hacen falta porque
`CREATE TABLE IF NOT EXISTS` **calla si la tabla ya existe con otra forma**.

### 8. Las unidades de systemd

- [ ] `continental-web.service` y `continental-lote.{service,timer}` instalados

```bash
sudo cp scripts/systemd/continental-web.service /etc/systemd/system/
sudo cp scripts/systemd/continental-lote.service /etc/systemd/system/
sudo cp scripts/systemd/continental-lote.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemd-analyze verify continental-web.service continental-lote.service
sudo systemctl enable --now continental-web.service continental-lote.timer
ss -ltn | grep 8585    # debe decir 172.19.0.1:8585
```

**`systemd-analyze verify` ANTES del `enable --now`, no después.** Marlowe tuvo
`StartLimitIntervalSec` en la sección equivocada y systemd lo ignoraba **en
silencio**: el freno contra el bucle de reinicios no existía y nadie se habría
enterado. Es la única herramienta que caza eso, y no se puede correr desde la
torre.

### 9. El túnel y Access · *no se hace por ssh*

- [ ] Public Hostname en el dashboard
- [ ] Política de Access, inmediatamente después

El túnel de atlas es *remotely-managed*: su enrutamiento vive en el dashboard
de Cloudflare Zero Trust, no en un archivo local.

**B.1** Zero Trust → Networks → Tunnels → el túnel de atlas → Public Hostname →
Add: subdominio `farmacia`, dominio `farfanlab.uk`, path vacío, tipo **HTTP**
(no HTTPS), URL **`172.19.0.1:8585`**.

**No `localhost`**: para el contenedor `borde_tunel`, `localhost` es su propio
contenedor. Es el 502 exacto que Marlowe midió el 2026-09-06. Ese gateway
**cambia si se recrea la red Docker `borde`**.

**B.2, acto seguido:** Access → Applications → Add → Self-hosted, dominio
`farmacia.farfanlab.uk`, política `Allow` con Include → Emails. **No Bypass.**

> ⚠️ **Entre B.1 y B.2 el sitio está abierto a internet.** Que la ventana dure
> un minuto. `172.19.0.1` es *no estar enrutado*, no *estar bloqueado*: la
> garantía real es Access.

**B.3** Entrar desde fuera y confirmar que la pantalla dice el correo y no
`sin-identificar`.

### 10. El monitor de Uptime Kuma

- [ ] Push monitor **propio**, su URL en el `.env`, y decidir el fin de semana

Kuma corre en atlas como `borde_kuma` en `127.0.0.1:3002` (medido 2026-09-19).
**Monitor propio, distinto del de la cadena de ventas y del de Marlowe**: si
compartieran monitor, una noche sin lote no avisaría nada.

La URL del push va en `KUMA_PUSH_URL_CONTINENTAL` del `.env`. **Es un secreto**
y nunca va al YAML versionado — hay una prueba que lo vigila.

El timer es `Mon-Fri`: sin una ventana de mantenimiento el monitor se pone rojo
todos los sábados, y eso enseña a ignorar el rojo.

### 11. El recorrido en navegador del ticket 20

- [ ] Mirar la pantalla de elegir proveedor y partir, en atlas y a 375 px

Es la parte con **menos evidencia** de los veinte tickets: sus cinco casillas se
cerraron con pruebas sobre el HTML y un volcado del JSON, pero nadie la vio en
un navegador. No es paranoia — el navegador cazó lo que el suite no en tres
tickets seguidos: `+-60.33` (14), *"NADRO ya es el más barato"* debajo de *"el
único que contestó"* (15), y *"Completar los 1 que faltan"* (19).

Qué mirar: el desplegable de "Se le pide a", el bloque de partición con sus
totales, un pedido cuyo total es `NULL` porque una línea va sin precio, y
QuePharma sin `proveedor_id` de SICAR.

> Al levantar un servidor a mano, **verificar por proceso y no por puerto**. El
> 2026-09-19 un `uvicorn` huérfano soltó el socket y no murió: `netstat` salió
> vacío tres veces y el proceso siguió vivo tres horas con 1.6 GB, colgando el
> suite.
>
> ```bash
> powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name LIKE 'python%'\" | Where-Object { \$_.CommandLine -like '*Continental*' }"
> ```

---

## Cuando esté todo

Las 16 casillas marcadas —los once pendientes— quieren decir que Continental **corre en atlas, con
sus tablas creadas, detrás de Access y con el lote programado**. Entonces:

```bash
git rm pendientes.md tests/test_pendientes.py
git commit -m "Continental en pie: se van la lista de acarreo y su recordatorio"
```

Lo que **no** cierran estas casillas es la definición de terminado que
tiene `HANDOVER.md`, y conviene no confundirlas: *un día de operación real en
que la lista se armó sola de noche, trajo precios de los cuatro proveedores,
una persona la revisó, capturó el pedido leyendo de la pantalla, y al día
siguiente los renglones se marcaron como probablemente recibidos —**con al
menos un renglón donde NADRO no era el más barato y se le pidió a otro***.

Eso necesita además los tickets 21, 22, 24 y 26.
