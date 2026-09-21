# Pendientes para poner Continental en pie — 2026-09-19

**ESTE ARCHIVO SE BORRA.** No es documentación: es una lista de acarreo con
fecha de caducidad. Cuando las 17 casillas estén marcadas, `pendientes.md`
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

## Dónde vamos — 14 de 17 casillas

| | Pendiente | Estado |
|---|---|---|
| 1 | El remoto y el clon en atlas | ✅ 2026-09-19 |
| 2 | Los `grants` de farmacia-data | ✅ 2026-09-19 |
| 7 | El DDL, el rol y el verificador | ✅ 2026-09-20 |
| 8 | Las unidades de systemd | ✅ 2026-09-21 — el lote armado para las 22:00 |
| 9 | El túnel y Access | ✅ 2026-09-20 — falta mirar B.3 |
| 5 | `clase_abc` en `dim_producto` | ✅ 2026-09-20 — el ADR 0018, implementado |
| **12** | **Uptime Kuma 1.23 → 2.x** | ⏭️ **el siguiente — el CPU sí lo aguanta (medido)** |
| **11** | **El recorrido en navegador del ticket 20** | 🟡 a medias hasta que Doyle dé precios |
| 3 | Las cuatro sesiones de Doyle | ⏭️ **el siguiente con gente — hoy, en horario** |
| 4 | La decisión del descarte | ✅ 2026-09-20 — decidida e implementada |
| 6 | Doyle a atlas | ✅ 2026-09-21 — corre, con visor sobre Xvfb detrás de Access |
| 10 | El monitor de Uptime Kuma | ✅ 2026-09-20 — y se arregló el del vecino |

**El 12 no estaba en la lista original y se agregó el 2026-09-20.** Es el único
que no pone a Continental en pie: vive en `borde`. Está aquí porque **invalida
al 10** —las dos ventanas de mantenimiento están calibradas contra un
comportamiento de la 1.23— y sin casilla propia esta lista se podría borrar
entera dejando esos dos números mintiendo.

**Del 11 se sabe más que ayer, y es media mala noticia.** El desplegable de "Se
le pide a" se llena de una lista fija, así que se puede mirar hoy. Lo que no se
puede es lo que el recorrido existe para cazar: con los 124 renglones en *no se
pudo*, todos salen en "— elige —" y el bloque de partición no tiene qué
comparar. La mitad que importa espera al 6.

**Se levantó el freno de mano.** El 2 había puesto a farmacia-data en una
posición en la que un `git pull` en atlas tumbaba su cadena nocturna; el 7 creó
el rol que faltaba y con eso el `pull` se hizo el 2026-09-20 sin novedad. Los
números no se renumeran aunque cambie el orden —Notion y los commits los
referencian—; lo que cambia es por dónde se sigue.

**El `.env` de atlas no es ninguno de estos doce** —vive como paso A.4 de
`docs/despliegue-en-atlas.md`— y quedó hecho el 2026-09-20. Mordió al ponerlo:
la contraseña del rol y la del archivo no coincidían, y el síntoma es un
*password authentication failed* enterrado en cien líneas de SQLAlchemy, con un
*Connection refused* de `::1` arriba que lo disfraza de problema de red. El
remedio, con su orden de descarte, quedó escrito en A.4.

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

  Lo que queda de eso: **Marlowe sigue con su remoto en HTTPS** y va a chocar
  igual el día que le toque empujar. Ya tiene la llave que lo arregla; es un
  `git remote set-url` a `git@github.com:...` y nada más. **Doyle ya se movió**
  el 2026-09-21 (`git@github.com:LeFarfane/Doyle.git`).

  Y una corrección que salió al clonar Doyle en atlas: **allá el remoto no se
  escribe `git@github.com:`**, sino con un alias por repo —`git@github-doyle:`—
  definido en `~/.ssh/config` con su propia deploy key e `IdentitiesOnly yes`.
  Sin eso, `ssh` ofrece la llave de otro repo, GitHub la acepta, y el clon
  falla con *"repository not found"*, que no menciona llaves por ningún lado.
  Continental y Marlowe ya estaban así en atlas; lo que faltaba era escribirlo.

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

### 4. La decisión del descarte — ✅ **decidido e implementado el 2026-09-20**

- [x] Decidir si descartar un renglón debe exigir la lista abierta

**Sí la exige.** Las cuatro acciones que una persona hace sobre un renglón dicen
ahora lo mismo:

| Acción | ¿Exige lista abierta? | Ticket |
|---|---|---|
| Descartar / devolver a abierto | **Sí, desde hoy** | 10 |
| Ajustar la cantidad | Sí | 11 |
| Elegir proveedor / partir | Sí | 20 |

El ticket 10 nunca pidió esa condición, así que no era un incumplimiento: era
una incoherencia, y el comentario de `_ELEGIR_PROVEEDOR` la tenía anotada
pidiendo que el arreglo se hiciera *"a propósito y no de paso"*. De cara al
encargado, **una lista cerrada que todavía se deja modificar es una lista que
no está cerrada** — y un descarte posterior separa el renglón de lo que de
verdad se le pidió al proveedor, así que el ticket 26 recibiría mercancía
contra un renglón que dice que nadie la pidió.

Qué se tocó:

- `_DESCARTAR` y `_DEVOLVER_A_ABIERTO` en `almacenamiento.py`, con la misma
  forma que `_AJUSTAR_LA_CANTIDAD`: la lista entra por `from
  pedidos.pedido_sugerido` y su `estado` viaja en el `WHERE`. En la sentencia y
  no en un `if` de Python, porque leer el estado y actualizar después tiene una
  carrera en medio —una pestaña cierra mientras otra descarta—.
- **Las dos direcciones.** Deshacer también es modificar: ponerlo solo en el
  descarte habría dejado renglones `descartado` dentro de una lista cerrada sin
  manera de volver.
- Los dos botones de la pantalla se apagan con la lista cerrada, con su motivo
  en el `title`. Apagados y no escondidos: la columna de acciones tiene ancho
  fijo y quitarlos movería todas las filas al cerrar.
- `CONTEXT.md` lo dice ahora en el glosario, que es donde manda.

Cuatro pruebas nuevas —dos de comportamiento, una sobre el SQL y una sobre el
HTML—, verificadas en rojo antes del cambio. **833 pasan.**

### 5. `clase_abc` en `dim_producto` (ADR 0018 de farmacia-data) — ✅ **hecho el 2026-09-20**

- [x] Las columnas `clase_abc` y `clase_xyz`, calculadas por dbt en la cadena
      nocturna

El ADR 0018 llevaba semanas aceptado y sin implementar. A3 —la clasificación
ABC-XYZ— dejó de ser un CTE copiado en cuatro archivos de tres repos y pasó a
ser columna de `dim_producto`, calculada por dbt. Commit `c989ecb` de
farmacia-data, rama `fase1-tableros`; **`dbt build` en atlas: 61 de 61**.

Y de este lado, la línea que esperaba:
`LA_CLASE_ABC_ESTA_EN_DIM_PRODUCTO = True`. El orden por importancia del lote
nocturno ya estaba escrito y probado; lo único que faltaba era el dato.

> **A3 no se pudo copiar tal cual, y las tres diferencias valen la pena.**
>
> 1. **La ventana se ancla en la última venta, no en `current_date`.** En una
>    consulta que alguien lee a mano eso mueve el borde un día y no pasa nada.
>    En una columna que decide el orden del pedido nocturno, la ventana se
>    recorrería sola cada vez que la cadena se salta una noche —el Postgres del
>    contenedor corre en UTC—, **sin fallar y sin avisar**. Es la regla que ya
>    le costó a farmacia-data 11.7 puntos de crecimiento inventados.
> 2. **El corte del 80% lleva desempate por `producto_id`.** La suma corrida va
>    con `rows between unbounded preceding and current row`: dos productos con
>    la misma utilidad quedaban en un orden que Postgres no promete, así que
>    cuál caía en A y cuál en B **podía cambiar entre corridas sin que nada
>    cambiara en el negocio**. A3 no lo necesitaba porque nadie comparaba dos
>    corridas suyas; una columna que se recalcula cada noche sí.
> 3. **Sin ventas en la ventana es NULL, no `'C'`.** `'C'` afirmaría que se
>    midió y salió bajo. Continental ya esperaba exactamente eso: A, B, C y al
>    final lo que no se sabe.
>
> Va además una prueba singular —`clase_abc_cubre_lo_que_se_vendio.sql`—, y no
> es de adorno: el `LEFT JOIN` que permite el NULL es el mismo que se tragaría
> un emparejamiento roto, y **una columna llena de nulos se lee igual que
> "estos productos no se han vendido"**. Eso mandaría al final de la noche
> justo a los que más pesan.

**Lo que esto NO cierra**, y lo dice el propio ADR 0018 en sus consecuencias:
las cuatro copias siguen ahí. A3, A3b y A3c en `sql/tableros/analisis_puntual.sql`
y el CTE `clase` de `Marlowe/sql/canasta.sql` siguen recalculando los umbrales
en vez de leer la columna. Son cinco definiciones en vez de una hasta que se
reemplacen por un join. Eso es trabajo de farmacia-data y de Marlowe, no de
esta lista.

### 6. Doyle a atlas (ADR 0008 de Doyle) · *lo más incierto de todo*

- [x] La mudanza, con visor remoto sobre Xvfb — ✅ **2026-09-21**

Doyle corre en atlas: `~/proyectos/Doyle`, `doyle.service` en
`127.0.0.1:8383`, pantalla `xvfb98.service` en la `:98`, y el visor
(`x11vnc` + noVNC) en `doyle.farfanlab.uk` detrás de Access. Las cuatro
sesiones salen como `sin_sesion`, que es lo correcto hasta la casilla 3.

**Los tres interrogantes que iban aquí, dos resueltos y uno reubicado:**

> *¿arranca el Chrome de Google en ese CPU de 2010?* — **la pregunta se
> disolvió.** Doyle dejó de pedirlo: usa `/usr/bin/chromium` de apt, que es el
> mismo que Marlowe ya corre ahí. Y no hay que correr `playwright install`.
>
> *¿VICMA abre ventana ahí?* — **sí, medido.** Y los otros tres también:
> `scripts/probar-pantalla.py` de Doyle abre los cuatro portales sobre la
> `:98`, con el campo de contraseña presente y sin emergentes. Lo que **no**
> prueba es que el acceso pase; eso se decide al enviar el formulario.
>
> *el captcha de LEVIC* — **sigue sin medir, y se muda a la casilla 3**, que es
> donde alguien teclea. Aquí no tenía forma de contestarse.

**Tres trampas que costaron la noche y no conviene redescubrir:**

> **La `:99` ya era de Marlowe.** Su `xvfb-run -a` la toma porque
> `/usr/bin/xvfb-run` trae `SERVERNUM=99` y `-a` busca libre **desde el 99 y
> hacia arriba**. Doyle quedó en la `:98`, seguro por construcción. El choque
> no habría hecho ruido: si Doyle gana, Marlowe se va al `:100` sin quejarse y
> el visor mira una pantalla vacía, sin una línea en ningún journal.
>
> **atlas clona con un alias de SSH por repo**, no con `git@github.com:`. Tiene
> una deploy key por repositorio, cada una con su `Host` en `~/.ssh/config` y
> `IdentitiesOnly yes`. Sin eso, `ssh` ofrece la llave de Marlowe y GitHub
> contesta *"repository not found"*, que no menciona llaves.
>
> **El Public Hostname del túnel no creó el registro DNS.** El `cloudflared`
> recibió el ingress —`version=6` en su log— pero `doyle.farfanlab.uk` daba
> `NXDOMAIN` hasta en el servidor autoritativo. Se arregló con un CNAME a mano
> a `<tunnel-id>.cfargotunnel.com`, **proxied**. Si vuelve a pasar con otro
> servicio, el diagnóstico es: pregunta al autoritativo, no al resolvedor de
> tu red.

Con esto se destraba la casilla 8 —`continental-lote.{service,timer}`— que
estaba esperando justo a esto. Los tickets 18 y 19 dejan de estar bloqueados
por falta de máquina: ahora hay una pantalla donde sí hay quien mire.

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

**El lazo con el pendiente 2, cerrado el 2026-09-20.** Los tres pasos, en orden:
`git pull` de farmacia-data en atlas —fast-forward de `742d062` a `8ddd91f`—,
`dbt build` completo, y `verificar_rol.sql` otra vez. **Salió BIEN las dos
veces, antes y después de la construcción.**

Eso es lo que había que demostrar y no se podía dar por hecho: la comprobación
**7** compara las tablas de `marts` que el rol puede leer contra las cinco
esperadas, y las cinco siguen ahí **después** de que dbt las recreara. Recrear
una tabla en Postgres borra sus permisos, así que un `GRANT` dado a mano habría
desaparecido justo aquí. El del `config` no. Es la falla que mordió el
2026-09-06 y otra vez el 09-07, ahora medida en esta base.

> **El `dbt build` de esa corrida: `PASS=160 WARN=4 ERROR=0` de 164.** Dos de
> los avisos son los conocidos —`fecha_caducidad` nulo en `stg_lote` y en
> `fct_caducidad`, degradados a aviso el 2026-08-19, con 2 filas cada uno—. Los
> otros dos son de `fct_precio_competencia`, que es de Marlowe y que este
> cambio **no toca**: no salieron de aquí. Quedan anotados en el repo de
> farmacia-data, no en éste.
>
> Y de paso: `CLAUDE.md` de farmacia-data dice **16 modelos y 124 pruebas**, y
> en esa corrida fueron **19 y 164**. Si vas a citar esas cifras, mídelas —yo
> las cité de ahí y salieron mal.

### 8. Las unidades de systemd — ✅ **hecho el 2026-09-21**

- [x] `continental-web.service` y `continental-lote.{service,timer}` instalados

**`continental-web.service` está instalado y corriendo desde el 2026-09-20
00:56.** `systemd-analyze verify` calló, `NRestarts=0`, escucha en
`172.19.0.1:8585` —el gateway, no loopback— y `/api/salud` contesta
`{"ok":true,...,"negocio":"farmacia_01"}`. El journal de la unidad está vacío y
**eso es correcto**: `iniciar.py` arranca uvicorn con `log_level="warning"`, así
que no hay banner ni log de accesos, pero los avisos y los errores sí viajan.
La confirmación de que está viva son `systemctl status`, `ss` y `/api/salud`,
no el journal.

**El lote entró el 2026-09-21 a la 01:30**, cuando se cumplieron las dos
condiciones que lo tenían detenido. `systemd-analyze verify` calló sobre las
dos unidades, y el timer quedó armado:

```
NEXT                        LEFT  UNIT                   ACTIVATES
Mon 2026-09-21 22:00:00 CST  20h  continental-lote.timer continental-lote.service
```

**Las dos condiciones, y las dos se cumplieron por caminos distintos:**

> **Doyle está en atlas** (pendiente 6, cerrado esa misma noche):
> `/api/sesiones` contesta `200` desde la propia máquina.
>
> **Y el defecto del latido ya estaba arreglado**, lo que este archivo no
> decía. Decía que `estado_del_latido` solo manda `ABAJO` cuando la corrida se
> interrumpió, así que una noche entera sin que Doyle conteste saldría
> `ARRIBA`. **Dejó de ser cierto el 2026-09-20**: ahora hay una segunda regla,
> `if resumen.intentados and not resumen.consultados: return ABAJO` — se
> intentó preguntar y no se pudo ni una vez. Es la regla más estrecha que caza
> ese caso, y está razonada en el docstring de la función junto con la que se
> descartó por ancha (`con_precio == 0 → down`, que pintaría rojo la noche en
> que Doyle contesta y los cuatro portales fallan, que es *sin dato* y se
> arregla abriendo sesiones).

**No se corrió a mano, a propósito.** El lote solo tiene `--tope-minutos`, no
hay ensayo en seco, y una corrida manual **crea un segundo pedido sugerido
abierto** que no es el de la noche y **manda un latido a Kuma** por una corrida
que no es la nocturna. Con Doyle todavía sin sesiones, además no probaría lo
único que falta por probar. La primera corrida de verdad es la de las 22:00.

**Qué mirar después de esa primera corrida:**

```bash
journalctl -u continental-lote -n 200 --no-pager
```

```bash
systemctl show continental-lote.service -p Result -p ExecMainStatus
```

La bitácora sí llega viva al journal durante la corrida —`logging` escribe a
stderr, que Python deja line-buffered aunque no haya terminal—, así que no hace
falta `PYTHONUNBUFFERED` aquí. En `doyle.service` sí hizo falta, y por lo
contrario: ahí lo que se perdía eran `print()` a stdout.

**`systemd-analyze verify` ANTES del `enable --now`, no después.** Marlowe tuvo
`StartLimitIntervalSec` en la sección equivocada y systemd lo ignoraba **en
silencio**: el freno contra el bucle de reinicios no existía y nadie se habría
enterado. Es la única herramienta que caza eso, y no se puede correr desde la
torre. En la web ya se corrió y calló.

### 9. El túnel y Access · *no se hace por ssh*

- [x] Política de Access **primero**
- [x] Public Hostname después

**Comprobado desde fuera el 2026-09-20, sin autenticar.** Ocho rutas —`/`,
`/api/salud`, `/api/pedidos`, `/api/lista`, `/static/app.css`, `/favicon.ico`,
`/docs` y `/openapi.json`— contestan **302 al login de Access**, y el HTTP
plano del puerto 80 da 301 a HTTPS y de ahí al mismo login. El token de la
redirección dice `auth_status: NONE` y su `aud` es el de la aplicación de
`farmacia.farfanlab.uk`, así que la política está amarrada al hostname
correcto y no hay excepción por ruta.

`/docs` y `/openapi.json` se probaron a propósito: FastAPI los publica solos y
son los que se olvidan cuando alguien agrega una ruta de excepción.

**Falta B.3**, que no se puede hacer por `curl`: entrar desde fuera con el
login y mirar que la pantalla diga el correo y no `sin-identificar`.

El túnel de atlas es *remotely-managed*: su enrutamiento vive en el dashboard
de Cloudflare Zero Trust, no en un archivo local.

**B.1, primero:** Access → Applications → Add → Self-hosted, dominio
`farmacia.farfanlab.uk`, política `Allow` con Include → Emails. **No Bypass.**

**B.2, después:** Zero Trust → Networks → Tunnels → el túnel de atlas → Public
Hostname → Add: subdominio `farmacia`, dominio `farfanlab.uk`, path vacío, tipo
**HTTP** (no HTTPS), URL **`172.19.0.1:8585`**.

**No `localhost`**: para el contenedor `borde_tunel`, `localhost` es su propio
contenedor. Es el 502 exacto que Marlowe midió el 2026-09-06. Ese gateway
**cambia si se recrea la red Docker `borde`**; remedido el 2026-09-20, sigue en
`172.19.0.1`.

> ### Este orden estaba al revés hasta el 2026-09-20
>
> Este archivo decía *Public Hostname primero, Access acto seguido*, y avisaba
> de que en medio el sitio queda abierto a internet pidiendo que la ventana
> "durara un minuto". **No tiene que durar nada.** La aplicación de Access se
> puede crear antes de que el hostname enrute: solo exige que el dominio esté
> activo en la cuenta, y `farfanlab.uk` lo está. Es además lo que recomienda
> Cloudflare, con esta razón textual: *"If you do not have an Access
> application in place, the published application will be available to anyone
> on the Internet."*
>
> Importa más aquí que en Metabase: Continental **escribe** a Postgres, y
> `172.19.0.1` es *no estar enrutado*, no *estar bloqueado*. La garantía real
> es Access.

**B.3** Entrar desde fuera y confirmar que la pantalla dice el correo y no
`sin-identificar`. Un `curl` desde atlas **no sirve** para esto: entra por el
gateway, no por el túnel, así que siempre dirá `sin-identificar`.

### 10. El monitor de Uptime Kuma — ✅ **hecho el 2026-09-20**

- [x] Push monitor **propio**, su URL en el `.env`, y decidir el fin de semana

`Continental - lote nocturno`, monitor Push propio: intervalo **93600 s** (26 h),
reintentos **2** con retry de **3600 s**, resend **0**. Su token vive solo en
`KUMA_PUSH_URL_CONTINENTAL` del `.env` de atlas — comprobado que no se coló a
`config/continental.yml`, que es lo que vigila
`tests/test_latido.py::test_el_nombre_de_la_variable_es_propio_y_esta_en_el_ejemplo`.

**El fin de semana se decidió: ventana de mantenimiento**, cron `0 0 * * 6`,
**4190 minutos**, zona `America/Mexico_City` elegida a mano. Cierra el **lunes a
las 21:50**, diez minutos antes del disparo del timer — y ese detalle es todo el
truco, porque en Kuma 1.23 un latido que llega *dentro* de una ventana se guarda
como `MAINTENANCE` y **no levanta** un monitor Push. El razonamiento completo,
con lo descartado, está en la parte D de `docs/despliegue-en-atlas.md`.

> **De paso se arregló el monitor del vecino, que llevaba 99.95% del tiempo en
> rojo.** `Cadena nocturna` tenía intervalo de **60 segundos** contra una cadena
> que late una vez por noche: 10,073 latidos rojos contra 5 verdes en siete
> días. Ahora va con los mismos 93600 s y su propia ventana de **4105 minutos**,
> que cierra el lunes a las **20:25** porque late a las 20:33 — medido sobre 12
> latidos reales, no calculado.
>
> Y quedó dicho que **no hay monitor de Marlowe**: son seis y ninguno es suyo.

**Lo que este verde todavía no prueba.** Con Doyle fuera de atlas, una corrida
de verdad termina con todos los renglones en *no se pudo*. Desde el arreglo del
2026-09-20 eso late en **rojo** y no en verde, así que la primera corrida real
va a pintar el monitor de rojo **con razón**. Es la prueba de que las dos cosas
funcionan, no una falla.

Kuma corre en atlas como `borde_kuma` en `127.0.0.1:3002` (medido 2026-09-19).
**Monitor propio, distinto del de la cadena de ventas y del de Marlowe**: si
compartieran monitor, una noche sin lote no avisaría nada.

La URL del push va en `KUMA_PUSH_URL_CONTINENTAL` del `.env`. **Es un secreto**
y nunca va al YAML versionado — hay una prueba que lo vigila.

El timer es `Mon-Fri`: sin una ventana de mantenimiento el monitor se pone rojo
todos los sábados, y eso enseña a ignorar el rojo.

### 12. Uptime Kuma 1.23 → 2.x · *el único que no es de Continental*

- [ ] Respaldar, actualizar y volver a medir la ventana

**Está aquí porque invalida el pendiente 10, no porque ponga a Continental en
pie.** Kuma corre en `borde`, que es otro repo; si esta casilla no existiera, la
lista se podría borrar entera con los dos números del 10 apuntando a un
comportamiento que ya no es cierto.

**El salto no es un `docker pull`.** La migración del SQLite es automática, en
el sitio y **de un solo sentido**: no hay downgrade de una base ya migrada, y la
2.x además **eliminó el respaldo/restauración en JSON** que tenía la 1.23. El
directorio `data`, respaldado con el contenedor parado, es el único camino de
vuelta. La guía oficial es explícita con que la migración **no se interrumpe**;
si se corta a la mitad, se restaura y se empieza de nuevo.

> ### ✅ El CPU sí lo aguanta — medido el 2026-09-20
>
> Era la duda que podía cerrar esta casilla antes de empezar. Kuma 2.x exige
> **Node ≥ 20.4**, y atlas es un Athlon II X4 de 2010: SSE2 y SSE4a, **sin
> SSSE3, SSE4.1 ni SSE4.2**. Es la misma trampa que el `CLAUDE.md` de
> farmacia-data tiene escrita para numpy y pandas, y hay reportes de Node 20
> muriendo con `Illegal instruction` por debajo de la línea base moderna
> (`nodejs/node#52371`).
>
> ```bash
> docker run --rm --entrypoint node louislam/uptime-kuma:2 --version
> ```
>
> Contestó **`v22.22.3`**. No `Illegal instruction`: Node 22, dos versiones
> mayores por encima del mínimo, corriendo en un CPU de 2010.
>
> **Por qué la predicción falló, que es lo que hay que recordar:** esos
> reportes son de compilaciones de distribución —Fedora y compañía— que se
> arman contra una línea base de micro-arquitectura más alta. La imagen de
> Docker trae el binario oficial de Node, que sigue apuntando bajo. **No es lo
> mismo "Node 20 no corre en este CPU" que "el Node de mi distro no corre en
> este CPU"**, y aquí la diferencia decidía el pendiente entero.
>
> **Y la aplicación entera también arranca.** `node --version` imprime y se
> sale: no ejercita el JIT ni las dependencias nativas que Kuma carga al
> arrancar, que es donde muere numpy. Así que se midió la segunda, en un
> volumen desechable y sin tocar los datos:
>
> ```bash
> docker run --rm -p 127.0.0.1:3099:3001 louislam/uptime-kuma:2
> ```
>
> **Uptime Kuma 2.5.5 sobre Node 22.22.3**: cargó módulos, levantó express y
> socket.io, y se quedó esperando en la pantalla de configuración inicial. Eso
> es el arranque completo, no un `--version`.
>
> **El gate está cerrado: el CPU no es el problema.** Lo que queda es el
> respaldo, la migración del SQLite y volver a medir la ventana.

**Qué hay que volver a medir después, y es el motivo de que esto esté aquí:**
los **4190** minutos de la ventana del fin de semana y los **4105** del vecino
están calibrados contra un comportamiento de la 1.23 —que un latido que llega
*dentro* de una ventana se guarda como `MAINTENANCE` y **no levanta** un monitor
Push—. Si la 2.x no lo conserva, los dos números quedan mal **sin que nada lo
diga**, que es exactamente el modo de falla contra el que se escribió el 10.

Lo demás que cambia y nos roza: los reintentos por omisión pasan de 1 a 0 **solo
para monitores nuevos** (los seis que existen conservan lo suyo, incluidos los 2
del de Continental), y las imágenes Alpine desaparecen. Conviene apuntar los
seis monitores antes —nombre, tipo, intervalo— para poder cotejar, y **los
tokens de push sobre todo**: si la migración los tocara, los `.env` de
farmacia-data y de Marlowe apuntarían a monitores que ya no escuchan, en
silencio.

> **El fin de semana es la mejor ventana que va a haber.** Las dos ventanas de
> mantenimiento están abiertas hasta el lunes 21:50 y la cadena nocturna es
> `Mon-Fri`, así que **nadie empuja un latido hasta el lunes**: si Kuma se cae
> hoy no se pierde una medición ni suena una alerta. El lunes ya no es cierto.
>
> Y el token de Continental que falta regenerar va **después** de actualizar,
> no antes.

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

Las 17 casillas marcadas —los doce pendientes— quieren decir que Continental **corre en atlas, con
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
