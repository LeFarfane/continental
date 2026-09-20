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

---

## Dónde vamos — 7 de 16 casillas

| | Pendiente | Estado |
|---|---|---|
| 1 | El remoto y el clon en atlas | ✅ 2026-09-19 |
| 2 | Los `grants` de farmacia-data | ✅ 2026-09-19 |
| 7 | El DDL, el rol y el verificador | ✅ 2026-09-20 |
| **8** | **Las unidades de systemd** | ⏭️ **el siguiente** — antes, el `.env` (A.4) |
| 3 | Las cuatro sesiones de Doyle | pendiente |
| 4 | La decisión del descarte | pendiente *(es una decisión, no trabajo)* |
| 5 | `clase_abc` en `dim_producto` | pendiente |
| 6 | Doyle a atlas | pendiente *(lo más incierto)* |
| 9 | El túnel y Access | pendiente |
| 10 | El monitor de Uptime Kuma | pendiente |
| 11 | El recorrido en navegador del ticket 20 | pendiente |

**Se levantó el freno de mano.** El 2 había puesto a farmacia-data en una
posición en la que un `git pull` en atlas tumbaba su cadena nocturna; el 7 creó
el rol que faltaba y con eso el `pull` se hizo el 2026-09-20 sin novedad. Los
números no se renumeran aunque cambie el orden —Notion y los commits los
referencian—; lo que cambia es por dónde se sigue.

**El `.env` de atlas no es ninguno de estos once**, y sin él el 8 no arranca:
vive como paso A.4 de `docs/despliegue-en-atlas.md`. Es copiar `.env.example` y
poner la contraseña del rol en `WAREHOUSE_URL` —**la misma** que se le dio a
`crear_rol.sql`, o lo que se ve es un *password authentication failed* con cara
de problema de red.

**Por qué existe esto y no está en `HANDOVER.md`:** el HANDOVER describe **el
estado actual** y no una lista de parches por aplicar —lo dice su primera
línea—. Esto es justo una lista de parches por aplicar.

---

## Los que no esperaban a nadie

### 1. El remoto de GitHub y el clon en atlas — ✅ **hecho el 2026-09-19**

- [x] Crear el remoto y la llave de despliegue de solo lectura para atlas
- [x] Clonar y preparar el entorno

`LeFarfane/continental` en GitHub, **privado**, con `main` por omisión, y
`~/proyectos/Continental` clonado en atlas. **827 pasan ahí en 9.86 s**, contra
3.3 s en la torre: mismo número de pruebas, tres veces más lento.

El procedimiento completo —las dos llaves, el alias de ssh, los comandos— quedó
en `docs/despliegue-en-atlas.md`, pasos A.1 a A.3, que es donde vive lo
permanente. Aquí solo el saldo:

- **`psycopg2-binary` corre en ese CPU.** Era la única duda técnica del
  pendiente. 2.9.13 importa sin `Illegal instruction`, y el venv va **sin**
  `--system-site-packages`. El plan B que este archivo proponía
  —`apt install python3-psycopg2`— no existía: ese paquete no está instalado en
  atlas, así que no había nada que heredar.
- **Dos llaves, con alcances distintos a propósito.** Atlas tiene una *deploy
  key* de **solo lectura**, amarrada a este repo: despliega, no publica. La
  torre tiene una **llave de cuenta**, que alcanza todos los repos porque es
  donde se escribe el código. Si atlas se ve comprometido, lo que se filtra es
  lectura de un repo.
- **Empujar por HTTPS desde la torre no funciona, y ya no hace falta.** Fallaba
  dos veces seguidas: el almacén de credenciales de Windows no persiste
  (`wincredman`), y aunque eso se arregle, GitHub no acepta contraseñas desde
  2021. Se resolvió pasando la llave de la torre a llave de cuenta, así que el
  problema está cerrado **para todos los repos**, no solo para este.

  Lo que queda de eso: **Marlowe y Doyle siguen con sus remotos en HTTPS** y van
  a chocar igual el día que les toque empujar. Ya tienen la llave que los
  arregla; es un `git remote set-url` a `git@github.com:...` y nada más.

Lo que esto desbloquea son los pendientes 7 a 11: todos empiezan con "en
`~/proyectos/Continental`", que hasta hoy no existía.

### 2. Los `grants` de farmacia-data — ✅ **hecho el 2026-09-19**

- [x] `'continental'` en el `config(grants=...)` de `dim_fecha`, `dim_producto`,
      `fct_ventas` y `fct_compras`
- [x] El bloque `grants` **entero** en `dim_proveedor.sql`, que no tenía ninguno

Commit `8ddd91f` del repo `Farmacia`, rama `fase1-tableros`. Los cinco modelos
otorgan `continental` desde su config, que es lo único que sobrevive a un
`dbt build` —recrear una tabla en Postgres borra sus permisos, y un GRANT dado
a mano dura hasta las 20:30 de ese día; Marlowe lo midió el 2026-09-06—.

Va además una prueba nueva, `tests/test_permisos_de_marts.py`, con la tabla
**exacta** de quién lee cada modelo. Vigila las dos direcciones: que no falte
un rol y que no sobre. Quitar `'continental'` de un modelo no rompe nada en
farmacia-data —ni sus pruebas ni su `dbt build`—; rompe **este** repo, de
noche, sin dejar rastro que apunte al cambio.

> ### ✅ Esto invirtió el orden, y el orden ya se cumplió
>
> Del 2026-09-19 al 20, este cambio estuvo **empujado pero no traído**: mientras
> el rol `continental` no existiera, un `git pull` de farmacia-data en atlas
> dejaba a la cadena nocturna a un `dbt build` de contestar
> `role "continental" does not exist`, fallar el modelo y llevarse lo que
> cuelga de él —y a Marlowe con ello—, por un permiso para un módulo que ni
> siquiera estaba corriendo.
>
> No se armó. La cadena **no hace `git pull`**: corre `dbt build` sobre el árbol
> que haya en `~/proyectos/Farmacia`, así que empujar desde la torre nunca puso
> la trampa. Atlas se quedó en `742d062` hasta que el pendiente 7 creó el rol, y
> el `pull` se hizo el **2026-09-20**, ya sin riesgo: fast-forward a `8ddd91f`,
> doce commits, y de `dbt/` exactamente los cinco `grants` y nada más.
>
> **Lo que dejó escrito, por si vuelve a pasar:** el orden correcto es *primero
> el rol, después el `grants`*, y no se arregla creando el rol a mano para
> adelantarse. `crear_rol.sql` es idempotente y, si lo encuentra ya creado,
> **no le toca la contraseña** a propósito: un rol creado a mano deja a
> Continental sin poder entrar nunca, y el script imprime que todo salió bien.

`dim_proveedor` importa desde el ticket 20: ahí vive el `pro_id` de SICAR con
el que se identifica el proveedor de un pedido. Medido el 2026-09-19 contra el
almacén: 22 filas, **NADRO=1, VICMA=8, LEVIC=10, y QuePharma no está** — la
farmacia nunca le ha comprado. Marlowe **no** lee ese modelo, así que es el
único de los cinco que otorga solo a `continental`.

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

Verificado el 2026-09-19: en `~/proyectos/` de atlas están `borde`,
`Continental` (desde hoy), `Farmacia`, `Marlowe` y `Sarabia`. **Doyle no está
ahí.**

Cierra dos casillas que hoy no se pueden cerrar: el lote reutilizando el
navegador por proveedor (ticket 18) y el botón que abre una sesión caducada
(ticket 19) — hoy esa ventana se abriría en la torre, donde no hay nadie
mirando.

Va con interrogantes que nadie ha medido: si el Chrome de Google arranca en ese
CPU de 2010, si VICMA abre ventana ahí, el captcha de LEVIC.

---

## Los que esperaban al repo en atlas — **la espera terminó**

Esa condición se cumplió el 2026-09-19 con el pendiente 1:
`~/proyectos/Continental` existe, con su venv y las 827 pruebas en verde. Los
cinco de aquí abajo **ya se pueden empezar**; se quedan agrupados así porque
explica por qué estuvieron detenidos, no porque sigan estándolo.

### 7. El DDL, el rol y el verificador — ✅ **hecho el 2026-09-20**

- [x] `sql/crear_tablas.sql`
- [x] `sql/crear_rol.sql`
- [x] `sql/verificar_rol.sql` — **el que da el veredicto**

**Veredicto: BIEN. 25 de 26 comprobaciones, 1 aviso conocido, salida 0.** El
esquema `pedidos` existe con sus cinco tablas, las posee `farmacia` y no
`continental`, el rol escribe las suyas, lee las cinco de `marts`, y no puede
crear objetos en ningún esquema ni borrar una sola fila. El DDL se corrió a
mano con credenciales de dueño, que es como tiene que ser: el rol no hace DDL a
propósito (ADR 0003).

El aviso es el **17** y se deja: `continental` puede crear tablas TEMPORALES
porque el `TEMPORARY` le llega por `PUBLIC` sobre la base. Quitarlo sería un
`REVOKE ... FROM PUBLIC` que le pega a dbt y a Metabase por igual — decisión de
farmacia-data, no de Continental.

**Las migraciones `0001` a `0005` no se corrieron, y no hacía falta.** Están
para una base creada antes que ellas; ésta se creó después y `crear_tablas.sql`
ya trae lo que las cinco agregan. Se verificó **antes** de correr nada, no
después: las cinco tablas, `pedido.proveedor_id` admitiendo nulos con
`proveedor` NOT NULL al lado, `ux_pedido_proveedor` sobre
`(pedido_sugerido_id, proveedor)` y `fk_renglon_pedido` con sus tres columnas.

> **El verificador dio un `[MAL]` que no lo era, y eso valía arreglarlo.** La
> comprobación 23 armaba su *obtenido* con un `string_agg` ordenado `DESC` y lo
> comparaba —igualdad de cadenas— contra un *esperado* escrito ascendente:
> `proveedor_id admite nulos, proveedor NOT NULL` contra `proveedor NOT NULL,
> proveedor_id admite nulos`. Lo mismo, en otro orden, sin coincidir jamás. El
> script salió con código 3 sobre un esquema impecable.
>
> Arreglado en `f445e21`, con una prueba para la clase entera: ningún
> `string_agg` de `verificar_rol.sql` puede ordenar descendente. **Si uno de
> estos vuelve a decir `[MAL]`, lee las dos celdas antes de tocar la base.** Un
> falso `[MAL]` es lo segundo peor que puede hacer un verificador: enseña a
> desconfiar de él, y el día que tenga razón nadie le va a creer.

> **La contraseña se pone una sola vez, y el script no avisa de lo contrario.**
> `crear_rol.sql` es idempotente, y si encuentra el rol ya creado **no le toca
> la contraseña** a propósito (línea 96): imprime *"NO se le toca la
> contraseña"* y sigue con los permisos. Eso está bien cuando se recorre para
> reaplicar grants, y es una trampa cuando el rol se creó a mano o con otra
> contraseña — Continental se queda sin poder entrar y la corrida termina en
> verde. Si hay que cambiarla, es un `ALTER ROLE continental PASSWORD ...`
> aparte, no otra pasada de este archivo.
>
> **Ahora esa contraseña tiene que volver a aparecer, idéntica**, en
> `WAREHOUSE_URL` del `.env` de atlas (paso A.4 de
> `docs/despliegue-en-atlas.md`). Si las dos no coinciden, lo que se ve es un
> *password authentication failed* que parece problema de red.

**El lazo con el pendiente 2, a medias.** El `git pull` de farmacia-data en
atlas ya se hizo —fast-forward de `742d062` a `8ddd91f`, sin novedad—. Falta
correr `cd dbt && ../.venv/bin/dbt build` una vez y **volver a correr
`verificar_rol.sql`**: su comprobación **7** compara las tablas de `marts` que
el rol puede leer contra las cinco esperadas, así que detecta tanto que falte
una —dbt se la llevó al recrearla— como que sobre otra. Hasta que eso corra, que
los `grants` del config sobrevivan a una construcción está razonado pero no
medido en esta base.

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
