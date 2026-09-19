# Estado de Continental — 2026-09-19

Describe **el estado actual**, no una lista de parches por aplicar. Si algo aquí
no coincide con el código, el código manda.

**Directorio de trabajo:** `D:\AAA\5_proyectos\Farmacia\Continental`

## Qué es

La suite que junta `Doyle` (precios de proveedor), `Marlowe` (precios de
competencia) y los módulos propios detrás de una sola puerta,
`farmacia.farfanlab.uk`, para que el encargado no tenga que saber que son tres
programas distintos.

Nació el 2026-09-17 de una sesión de diseño completa: 51 preguntas, cinco ADRs
escritos antes de la primera línea de código. El glosario está en `CONTEXT.md`
y **manda sobre el nombre de cualquier cosa**.

## Qué hay hoy

**El pedido sugerido completo hasta el precio, y el precio ya emparejado.**
Corre, dice si está vivo, dice quién entró según Cloudflare Access, arma y
guarda la lista del día, deja descartar y corregir cantidades, y desde el
ticket 12 **le pide a Doyle el precio de un renglón en los cuatro proveedores y
lo congela con su instante de lectura**. Desde el ticket 13 **ese precio solo se
acepta si empareja**: NADRO, LEVIC y QuePharma por EAN de 13 dígitos directo;
VICMA únicamente si la búsqueda devuelve exactamente un resultado. Lo que no
empareja queda como hueco con su motivo —`no empareja` o `varios resultados`—,
nunca como cero. Y desde el ticket 14 **la fila compara**: los cuatro
proveedores con su precio y su existencia, el más barato **con existencia**
marcado, la diferencia por pieza de cada uno contra él, y el ahorro contra NADRO
en pesos y por renglón —multiplicado por `cantidad_a_pedir`, que es lo que de
verdad se va a pedir—. Y desde el ticket 15 **la lista dice lo que le falta**:
arriba, antes de la tabla, cuántos renglones quedaron sin comparar y por qué
—nadie los consultó, se consultaron y ninguno dio precio, o hay un solo precio—;
en cada renglón, contra cuántos de los consultados se comparó; en cada hueco, su
motivo dicho con palabras de persona; y **un renglón con una sola lectura ya no
se marca como "el más barato" sino como "el único que contestó"**. Lo que falta
de precios —el lote de la noche— es el ticket 18.

**Y desde el ticket 18 la lista se arma sola de noche y trae precios sin que
nadie los pida.** `continental-lote.timer` dispara lun-vie a las 22:00 —noventa
minutos después de la cadena de las 20:30 de farmacia-data, que es la que mete
las ventas con las que la lista se arma— y `python -m continental.lote` abre la
lista del día, le pide a Doyle el precio de cada renglón uno por uno, y **se
detiene al tope de 60 minutos**. Lo que no alcanzó queda contado como *faltante
por tope*, con el motivo `no alcanzó el tiempo` que ya existía, y **no como un
error**: una corrida que se detiene al tope sale con cero, porque detenerse es
lo que se le pidió. Un proveedor que falla deja un hueco con su motivo y los
otros tres siguen; un renglón que no se pudo consultar tampoco tumba la
corrida. **La bitácora es el journal** —`journalctl -u continental-lote`— con
cuántos consultó, cuántos quedaron sin precio y el desglose por motivo; el
*por qué* de cada hueco además ya vivía en `pedidos.precio_de_proveedor`, así
que no se estrenó ninguna tabla (ADR 0006). Y **el lote no puede dejar la lista
peor que antes**: lo único que escribe son filas de precio —la tabla que solo
crece del ADR 0004— más la lista del día si no existía, sin un solo `UPDATE` de
renglón, y hay una prueba que lo mata a la mitad para demostrarlo.

**Dos casillas del ticket 18 quedaron SIN MARCAR, y las dos por bloqueos
externos que siguen puestos** (más la del timer, que está escrito y probado
pero no instalado porque Continental todavía no está en atlas):

- **El orden de importancia por clase ABC.** `marts.dim_producto` no tiene
  `clase_abc` (ADR 0018 de farmacia-data, **aceptado y sin implementar**). El
  orden está construido entero como función pura y probado con dobles; el lote
  **no reordena nada** mientras no haya clase —consulta en el orden de urgencia
  con el que la lista se guardó— y **lo declara en cada corrida**. No se
  inventó un orden alterno: el propio ADR 0018 descartó "ordenar por la
  utilidad de la ventana" con su razón escrita. El día que la columna exista,
  el trabajo es **una línea**: `almacen.LA_CLASE_ABC_ESTA_EN_DIM_PRODUCTO =
  True`. Y nadie tiene que acordarse — `continental.verificar` lo imprime como
  PENDIENTE en cada despliegue, con esa constante dentro.
- **El navegador reutilizado por proveedor.** Vive en Doyle (su ADR 0008, sin
  hacer) y Continental no abre navegadores nunca (regla 1). Lo único que de
  este lado depende está hecho: el lote es **estrictamente secuencial**, que es
  lo que le permite a Doyle reutilizar lo que tenga abierto.

**Y desde el ticket 17 el despliegue pregunta por los datos, no solo por el
código.** `python -m continental.verificar` es el paso 6 de `desplegar.sh`:
comprueba que el rol todavía pueda leer las cinco tablas de `marts` **haciendo
un `SELECT 1`** sobre cada una —no leyendo el catálogo, porque lo que importa
es si puede leer *ahora* y cada `dbt build` se lleva los permisos por delante—,
y revisa los invariantes del pedido sobre las filas de verdad. **Acumula todas
las fallas y las imprime juntas**, cada una con el comando que la repara listo
para copiar, y sale con código distinto de cero. **Señala y no repara**: quién
cierra una lista duplicada es una persona, no un script.

**Tres cosas del 14 que conviene no redescubrir.** La existencia tiene **tres**
categorías y no dos: la confirmó, dijo cero, o **no dijo** —los portales la
dicen con palabras a menudo—. El tercero no compite con quien sí la confirmó, y
si nadie la confirmó gana igual pero con otra certeza, escrita con otras
palabras y en ámbar en vez de verde. El **ahorro cuando NADRO no dio precio no
es cero**: es `None` con el motivo de NADRO al lado, porque un `$0.00` se lee
"da lo mismo a quién comprarle". Y un proveedor puede ser **más barato que el
ganador** y no haber ganado —el más barato de los que lo tienen—, así que su
diferencia sale negativa: la pantalla escribe "60.33 más barato por pieza, pero
no lo tiene", y el signo lo decide Python. Ese último caso lo cazó el recorrido
del navegador, no el suite: la pantalla había escrito `+-60.33`.

**Tres cosas del 15 que conviene no redescubrir.** *"El más barato"* es un
**superlativo**: afirma algo sobre los otros tres precios, y con una sola
cotización eso no se miró. Por eso la certeza del ganador pasó de dos valores a
cuatro —se cruzan "¿confirmó existencia?" y "¿hubo con qué comparar?"— y **la
frase viaja hecha desde Python**: hasta el 14 el JavaScript elegía entre dos
literales suyos, que es exactamente por qué el caso salía mal sin que ninguna
prueba se pusiera roja. "Sin comparar" son **tres** cosas y no una —nadie lo
consultó, se consultó y ninguno dio precio, hay un solo precio— porque el
encargado las arregla de tres maneras; el conteo desglosa las tres y **solo mira
los renglones de trabajo**, al revés que `sin_clasificar`. Y el recorrido del
navegador volvió a cazar lo que el suite no: con NADRO como único proveedor con
precio, el ahorro daba un cero legítimo y la pantalla escribía *"NADRO ya es el
más barato"* tres renglones debajo de la marca que decía *"el único que
contestó"*.

**Y desde el ticket 19 la pantalla dice POR QUÉ falta cada precio, y el
encargado arregla solo lo que falló.** Hasta el 18, un renglón sin lecturas se
veía como *"nadie lo consultó"* — verdad, y **menos de lo que se sabe**. Ahora
son **seis motivos distintos** y cada uno lleva a un sitio distinto: *al lote se
le acabó el tiempo* (el botón de completar, o mañana), *el lote no corrió sobre
esta lista* (el timer, atlas apagado), *la corrida del lote se cortó* (el
journal de esa noche), *el lote lo intentó y no pudo* (levantar Doyle), *el lote
no lo miró* (estaba descartado esa noche) y *no tiene código de barras* (SICAR).
Los otros dos motivos que el ticket nombra —*el portal no contestó* y *la sesión
caducó*— son de un **proveedor** de un renglón y ya vivían en
`pedidos.precio_de_proveedor` desde el ticket 12: son preguntas de dos granos
distintos y por eso salen de dos tablas distintas (ADR 0007).

**Eso costó la quinta tabla, `pedidos.corrida_del_lote`**: una fila por noche
con el resumen de la corrida —el mismo objeto que el lote ya imprimía y tiraba—,
que el lote escribe en su `finally` y la pantalla lee con la lista. El ADR 0007
tiene el porqué completo y las dos opciones descartadas; en corto: escribir
cuatro filas de hueco por renglón no alcanzado obligaría a **inventarse a qué
proveedores se iba a preguntar** y dispararía la condición de revisión del ADR
0004 (~11,000 filas de puro hueco en una noche que corte al 20%). Lo que se
renuncia está dicho: se guarda **cuántos** quedaron sin alcanzar, no **cuáles**,
así que la noche que el tope cortó *y además* hubo renglones `no se pudo`, la
pantalla escribe *"probablemente"* con el otro número al lado en vez de elegir
uno a cara o cruz.

**Un botón vuelve a consultar solo los precios que faltan**, y *faltar* es más
estrecho que *estar incompleto* a propósito: cada renglón que entre son cuatro
visitas a portales ajenos con las credenciales del dueño, ~9 s por proveedor.
Entran los que **no tienen ni una lectura** y los que se consultaron, **no
dieron ni un precio**, y tienen al menos un hueco de los tres que se arreglan
reintentando. **No entran** los que ya tienen un precio —esas cuatro visitas
ganarían como mucho una cotización más—, los que no tienen EAN, ni los huecos
definitivos, que mañana contestarían lo mismo. Consulta **uno tras otro en un
solo hilo**, con su propio tope (`pedido.completar.tope_minutos`, 20 min) que es
distinto del del lote.

**Y el lote late a Uptime Kuma al terminar, con monitor propio.** *"Si
compartieran monitor, una noche sin lote no avisaría nada."* Se detiene al tope
→ `up`, porque detenerse es lo que se le pide; la corrida se corta → `down`. **Y
si el latido falla, la corrida NO se aborta**: `mandar_el_latido` no levanta
nunca —su `except` es de `BaseException` y no tiene un solo `raise` hacia
afuera—, lo dice en el journal con el **tipo** de la falla y nunca el texto (el
texto de un error de `httpx` lleva la URL completa, y la URL completa **es** el
token). Lo mismo vale para la fila de `corrida_del_lote`: va en su propio `try`.

```bash
python iniciar.py     # http://127.0.0.1:8585
python -m continental.verificar   # los datos de producción, no el código (ticket 17)
python -m continental.lote        # el lote nocturno, a mano (ticket 18)
python -m continental.lote --tope-minutos 5   # ...con tope corto, para mirarlo
pytest                # 749 pruebas, 0 saltadas, 3.55-4.46 s (2026-09-19, ticket 19)
                      # 628 en el 18. Las 121 nuevas son 83 de `test_motivos.py`,
                      # 34 de `test_latido.py`, 2 que `test_sql_del_pedido.py`
                      # gana solo —sus parametrizadas recorren TABLAS, que pasó
                      # de cuatro a cinco— y 3 del resto. Con los dos archivos
                      # nuevos fuera el árbol del 18 costó 3.66-4.06 s ese
                      # mismo rato; solas cuestan 0.45-0.50 s.
                      # NINGUNA MANDA UN LATIDO DE VERDAD, ni a la Kuma real ni
                      # a otra: `pedir` entra por argumento.
                      #
                      # 628 pruebas, 0 saltadas, 2.51-2.72 s (ticket 18)
                      # 565 en el ticket 17. Las 63 nuevas son 54 de
                      # `test_lote.py`, 5 de `test_verificar.py` (el invariante
                      # 4, el de la clase ABC), 3 de `test_compila.py` que gana
                      # solo por haber dos unidades y un módulo más que
                      # revisar, y 1 más del ast de las funciones puras.
                      # Medido en tres corridas: con `test_lote.py` fuera el
                      # árbol del 17 costó 2.39-2.47 s, y las 54 nuevas
                      # corriendo solas, 0.09-0.10 s. NINGUNA DUERME: varias
                      # simulan sesenta minutos con el reloj inyectado.
                      # 499 y 1 saltada en el ticket 15; 525 en el 16; las 40
                      # del 17 son 37 de `test_verificar.py`, 2 de
                      # `test_despliegue.py` y 1 que `test_compila.py` gana sola
                      # por haber un módulo más que compilar. Ninguna de las 37
                      # necesita Postgres: prueban la mitad PURA del verificador.
                      #
                      # Del ticket 15, y sigue valiendo: el tiempo sube con la
                      # torre y no con las pruebas. Ese día, con test_precio.py
                      # fuera, el árbol del ticket 11 costaba 3.7-4.2 s contra
                      # los 1.7-1.9 s que había medido por la mañana. Ver la
                      # nota de `tests/conftest.py`.
```

| Archivo | Qué es |
|---|---|
| `CONTEXT.md` | el glosario del negocio: pedido sugerido, renglón, pedido, sus estados |
| `CLAUDE.md` | las reglas no negociables y las trampas heredadas |
| `docs/decisiones/0001` | la suite como cáscara con módulos por HTTP |
| `docs/decisiones/0002` | el módulo de Pedido: reposición 1 a 1, EAN, recepción sugerida |
| `docs/decisiones/0003` | dónde viven las tablas del pedido y por qué el rol no puede crearlas |
| `docs/decisiones/0004` | el precio congelado: tabla que solo crece, `numeric`, y quién espera a Doyle |
| `docs/decisiones/0005` | dónde escucha Continental: el gateway de la red `borde`, no loopback |
| `docs/decisiones/0006` | el lote nocturno: la hora, el tope, qué pasa con lo que no alcanzó, y por qué la bitácora es el journal y no una tabla nueva |
| `docs/decisiones/0007` | la corrida del lote en **una fila por noche**, y por qué la pantalla deduce de ahí "el lote no llegó a este renglón" en vez de escribir cuatro huecos por renglón. Reabre la opción β del 0006 por su condición de disparo |
| `sql/` | el DDL de las **cinco** tablas, el rol acotado y `verificar_rol.sql`, que mira la **forma** de la base. **Se corren a mano, en ese orden, con credenciales de dueño** — no confundirlo con `continental.verificar`, que mira los **datos** en cada despliegue (la cabecera de ese módulo tiene la tabla que los separa) |
| `sql/migraciones/` | lo que le falta a una base donde las tablas YA existen: `crear_tablas.sql` usa `CREATE TABLE IF NOT EXISTS` y calla si la tabla ya está con otra forma. También a mano y con credenciales de dueño |
| `config/continental.yml` | puertos de los módulos y los parámetros del pedido |
| `src/continental/web/app.py` | `/api/salud`, `/api/modulos`, el pedido sugerido y su cierre, la portada |
| `src/continental/almacenamiento.py` | donde el pedido sugerido se guarda: el `Protocol`, el SQL real y las reglas de la tabla en un solo lugar |
| `src/continental/precios.py` | funciones puras: lo que Doyle contestó + la clave buscada -> precio `Decimal` o motivo de rechazo. Ahí vive `emparejar`, la regla por proveedor. No toca la red ni el reloj |
| `src/continental/consultas.py` | quién espera a Doyle y dónde queda el resultado si nadie está mirando |
| `src/continental/lote.py` | el lote nocturno. Tres mitades: lo **puro** —el orden por clase ABC, el cronómetro del tope, el resumen de la corrida—, la **orquestación** (`correr_el_lote`, con los tres bordes por argumento) y el **arranque** (`main`, lo único que construye bordes de verdad). El reloj entra por argumento: una prueba de sesenta minutos cuesta microsegundos |
| `src/continental/verificar.py` | los invariantes sobre los **datos** de producción, no sobre el código. Mitad pura (recibe listas, devuelve un `Informe`, se prueba) y mitad de recolección (lee de Postgres, no se prueba). Acumula todas las fallas, cada una con su comando de reparación, y sale distinto de cero. Es el paso 6 de `desplegar.sh` |
| `src/continental/comparacion.py` | funciones puras: las cuatro lecturas congeladas + las piezas -> quién gana, con qué certeza, cuánto se ahorra contra NADRO y, para la lista entera, cuántos renglones quedaron sin comparar (`contar_la_lista`). No toca la red, la base ni el reloj |
| `src/continental/faltantes.py` | funciones puras: la corrida del lote + las comparaciones -> **por qué** le falta el precio a cada renglón, y **cuáles** va a consultar el botón de completar. Ahí vive la decisión cara del ticket 19: qué cuenta como "faltante", que son ~36 s de navegador por renglón de más si se estira |
| `src/continental/latido.py` | el latido a Uptime Kuma, con monitor propio. `mandar_el_latido` **no levanta nunca** y el borde HTTP entra por argumento, así que ninguna prueba manda uno de verdad. El token vive en `KUMA_PUSH_URL_CONTINENTAL` del `.env`, jamás en el YAML |

## Lo que falta, en orden

1. **Doyle se muda a atlas** (ADR 0008 de Doyle): visor remoto sobre Xvfb para
   abrir sesión, lote que reutiliza un navegador por proveedor, y Doyle sin
   interfaz propia. **Va primero a propósito**: es lo que puede fallar por
   razones que no controlamos —VICMA sin ventana, el captcha de LEVIC, si el
   Chrome de Google arranca en ese CPU de 2010—, y descubrirlo mientras además
   se construye la suite mezclaría dos fallas distintas.
2. **`clase_abc` y `clase_xyz` como columnas de `dim_producto`** en
   farmacia-data (ADR 0018). El lote nocturno necesita un orden de importancia
   desde el primer día. **Desde el ticket 18 todo lo de este lado está listo y
   esperando**: el orden es una función pura probada, `Producto.clase_abc`
   existe, y el único trabajo del día que llegue la columna es poner
   `almacen.LA_CLASE_ABC_ESTA_EN_DIM_PRODUCTO = True` —la consulta de hoy ni
   siquiera la nombra, a propósito, porque un `select clase_abc` se llevaría
   por delante la lista del día entera—. El paso 6 del despliegue lo imprime
   como PENDIENTE hasta entonces.
3. **El módulo de Pedido.**
4. **Absorber la interfaz de Marlowe**, que pasa a ser API como Doyle. Después
   del Pedido: es reescribir una interfaz que ya funciona y no agrega ninguna
   capacidad nueva.

**Terminado, para el módulo de Pedido**, quiere decir esto y no "ya corre": un
día de operación real en que la lista se armó sola de noche con las ventas del
día anterior, trajo precios de los cuatro proveedores, una persona la revisó,
descartó lo que no iba, capturó el pedido en NADRO leyendo de la pantalla, y al
día siguiente los renglones se marcaron como probablemente recibidos cuando la
compra apareció en el almacén. **Con al menos un renglón donde NADRO no era el
más barato y se le pidió a otro.**

## Lo que todavía no existe y va a hacer falta

- ~~`scripts/desplegar.sh` y `continental-web.service`~~ **ya existen** desde
  el ticket 16 (2026-09-19), con 25 pruebas en `tests/test_despliegue.py`, y
  desde el ticket 17 el script tiene **seis** pasos: el nuevo corre
  `python -m continental.verificar` al final. Lo
  que falta no son los archivos: es **instalarlos en atlas**, y eso empieza por
  algo que todavía no hay (ver abajo). Los pasos completos, en orden y con las
  casillas sin marcar, están en `docs/despliegue-en-atlas.md`.
- ~~`continental-lote.service` y `continental-lote.timer`~~ **ya existen**
  desde el ticket 18 (2026-09-19), con 14 pruebas en `tests/test_lote.py`.
  Tampoco están instalados, por lo mismo, y su paso es el **A.8** de
  `docs/despliegue-en-atlas.md`. Dos cosas que conviene no redescubrir a la
  mala: se habilita **el timer y no el servicio** —la unidad no tiene
  `[Install]` a propósito, así que un `enable` sobre ella no hace nada y deja
  el lote sin disparar en silencio—, y el `TimeoutStartSec=75min` **no es
  adorno**: `Type=oneshot` usa ese valor para matar el proceso y el de omisión
  de systemd son 90 segundos, o sea que sin esa línea el tope de 60 minutos no
  existiría y la unidad quedaría en `failed` todas las noches.
- **El rol `continental` y sus tablas, CREADOS EN LA BASE.** El SQL ya está
  escrito (ticket 07): `sql/crear_tablas.sql`, `sql/crear_rol.sql` y
  `sql/verificar_rol.sql`, con su cabecera explicando el porqué de cada
  decisión. **Nadie lo ha corrido todavía**: el almacén vive en Docker en
  atlas y desde la torre no hay Postgres alcanzable (verificado el
  2026-09-19). Los tres pasos, en orden, con credenciales de dueño y desde
  `~/proyectos/Continental` en atlas —**plano, no anidado**: en atlas los
  repos son hermanos (`~/proyectos/Marlowe`, y `~/proyectos/Farmacia`, que es
  farmacia-data), al revés que en la torre—:

  ```bash
  docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
      -v ON_ERROR_STOP=1 < sql/crear_tablas.sql
  docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
      -v ON_ERROR_STOP=1 -v password="'LA_DEL_.ENV'" < sql/crear_rol.sql
  docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
      -v ON_ERROR_STOP=1 < sql/verificar_rol.sql ; echo "salida: $?"
  ```

  **Y desde el ticket 19 hay una migración más**, que también crea una tabla y
  por lo tanto también exige volver a correr `crear_rol.sql` después:

  ```bash
  docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
      -v ON_ERROR_STOP=1 < sql/migraciones/0004-la-corrida-del-lote-en-una-fila.sql
  # y otra vez crear_rol.sql y verificar_rol.sql, en ese orden
  ```

  El tercero es el que **da el veredicto**: 22 comprobaciones con lo que se
  esperaba y lo que se encontró, y salida distinta de cero si algo quedó mal.
  Es lo que cierra la última casilla del ticket 07, y solo lo puede correr una
  persona con credenciales de dueño en atlas. Las 18, 19 y 20 son del ticket 12
  y miran la forma de la tabla del precio: que no le hayan puesto un `UNIQUE`
  que obligue a pisar el historial, que los ocho motivos sobrevivieran con sus
  acentos, y que sigan puestas las dos restricciones que impiden que un hueco
  se vea como el más barato. La **21 y la 22** son del ticket 19 y miran la
  corrida del lote: que los cuatro finales sobrevivieran con sus acentos, y que
  no pueda guardarse un conteo imposible ni media lista.

  **Ojo con la comprobación 16: estaba mal y se arregló en el ticket 19.**
  Esperaba `3` llaves `GENERATED AS IDENTITY` cuando ya eran cuatro desde el
  ticket 12, así que **habría salido `[MAL]` sobre una base correcta la primera
  vez que alguien la corriera** — y nadie la ha corrido nunca. Ahora compara
  contra el número de tablas del esquema, que es lo que de verdad se quiere
  afirmar, y la sexta tabla entra sola. Un verificador que da un falso `[MAL]`
  es tan malo como uno que da un falso `[BIEN]`: los dos enseñan a no creerle.

- **Las migraciones de los tickets 10, 11 y 12, si las tablas ya se crearon
  antes del 2026-09-19.** Las dos primeras le agregaron a `pedidos.renglon`
  cinco columnas: `descartado_por` y `descartado_en` (la firma del descarte,
  ticket 10) y `cantidad_final`, `ajustada_por` y `ajustada_en` (la cantidad
  que una persona decidió pedir y quién la decidió, ticket 11). La tercera
  crea la **cuarta tabla**, `pedidos.precio_de_proveedor` (el precio congelado,
  ticket 12). Están escritas en los **dos** lados: en `sql/crear_tablas.sql`,
  para una base desde cero, y en `sql/migraciones/`, para una base donde las
  tablas ya existen. Hacen falta los dos porque `CREATE TABLE IF NOT EXISTS`
  **calla si la tabla ya existe con otra forma**: volver a correr el DDL sobre
  una tabla vieja no agrega la columna y no avisa, y el primer descarte
  rebotaría en atlas con "column descartado_por does not exist".

  Si `crear_tablas.sql` **todavía no se ha corrido** (que es el caso al
  2026-09-19), no hay nada que migrar: correrlo ahora ya crea las **cinco**
  tablas con todas sus columnas. Si ya se corrió antes de esa fecha, además de
  los tres pasos de arriba, y **en este orden**:

  ```bash
  docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
      -v ON_ERROR_STOP=1 \
      < sql/migraciones/0001-renglon-quien-descarto-y-cuando.sql
  docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
      -v ON_ERROR_STOP=1 \
      < sql/migraciones/0002-renglon-cantidad-final-y-quien-la-ajusto.sql
  docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
      -v ON_ERROR_STOP=1 \
      < sql/migraciones/0003-precio-congelado-por-renglon-y-proveedor.sql
  docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
      -v ON_ERROR_STOP=1 \
      < sql/migraciones/0004-la-corrida-del-lote-en-una-fila.sql
  ```

  Las cuatro son idempotentes: correrlas dos veces no rompe nada.

  **OJO CON LA 0003 Y CON LA 0004: después de cada una HAY que volver a correr
  `sql/crear_rol.sql`**, y ahí se apartan de las dos primeras. Las 0001 y 0002
  agregaban columnas, y el `GRANT SELECT, INSERT, UPDATE` es sobre la tabla
  entera: las cubría solas (no se usan permisos por columna, a propósito). Cada
  una de las otras dos crea una TABLA, y **un permiso no se puede dar sobre una
  tabla que todavía no existe**: el GRANT que se corrió en su día no la
  alcanza.

  Sin ese paso, con la 0003 el primer clic en "Consultar precio" rebota en
  atlas con "permission denied for table precio_de_proveedor" — y lo hace
  dentro del hilo que consulta, así que la pantalla solo dice "no se pudo
  guardar el precio" mientras el detalle vive en la bitácora.

  **Con la 0004 es peor, porque nadie lo ve**: el lote de las 22:00 rebota con
  "permission denied for table corrida_del_lote", la corrida **no** se aborta
  —esa escritura va en su propio `try`, ADR 0007— así que los precios de la
  noche se guardan igual, y lo único que pasa es que a la mañana la pantalla
  dice *"el lote no corrió sobre esta lista"* sobre una noche en la que sí
  corrió. Es la AUSENCIA de esa fila lo que significa eso.

  `crear_rol.sql` es idempotente y no le toca la contraseña a un rol que ya
  existe. Las comprobaciones 4 y 6 de `verificar_rol.sql` cazan el olvido.

  Ninguna la corre el código de arranque: el rol no tiene DDL y eso es el ADR
  0003.

- **Del lado de farmacia-data, y sin esto lo anterior se borra solo:** agregar
  `'continental'` al `grants` de `dim_fecha.sql`, `dim_producto.sql`,
  `fct_ventas.sql` y `fct_compras.sql`, y **agregarle un `grants` entero a
  `dim_proveedor.sql`, que hoy no tiene ninguno**. Recrear una tabla en
  Postgres borra sus permisos y cada `dbt build` recrea los modelos de
  `marts`: un GRANT dado a mano dura hasta las 20:30 de ese día. Marlowe lo
  midió el 2026-09-06. El detalle está al final de `sql/crear_rol.sql`.
- **El remoto de git**, y es lo que bloquea todo el despliegue. Continental no
  tiene ninguno (verificado el 2026-09-19), así que `desplegar.sh` se detiene
  en su paso 1 y lo dice con ese motivo exacto. Hace falta el remoto de GitHub
  y la llave de despliegue de solo lectura para atlas.
- **Continental no está en atlas.** Medido el 2026-09-19 en solo lectura:
  `~/proyectos/` tiene `borde`, `Farmacia` (que es farmacia-data), `Marlowe` y
  `Sarabia`, y nada más. Clonarlo va **plano**, en `~/proyectos/Continental`.
- **La ruta del túnel de Cloudflare para `farmacia.farfanlab.uk`, con Access
  delante.** Esto **no se puede hacer por ssh** y no es una limitación del
  agente: el túnel de atlas es *remotely-managed* —`borde_tunel` corre como
  `tunnel --no-autoupdate run`, sin `config.yml` local— así que el Public
  Hostname y la política de Access viven en el dashboard de Cloudflare Zero
  Trust. Lo hace una persona con la cuenta. Los valores exactos, campo por
  campo y en orden, están en `docs/despliegue-en-atlas.md`, parte B. **El
  orden importa**: entre que existe el Public Hostname y que existe la política
  de Access, el sitio está abierto a internet.

## Hilos abiertos

1. **LAS CUATRO SESIONES DE DOYLE ESTÁN CADUCADAS, y hay que abrirlas a mano.**
   Medido el 2026-09-19 contra el Doyle real, con UNA sola búsqueda de UN solo
   producto (el EAN `7501349028234`):

   - `GET /api/sesiones` contestó **`guardada` para los cuatro**, con
     marcadores del 2026-08-17 (NADRO) y del 2026-08-18 (LEVIC, QuePharma,
     VICMA). **Ese `guardada` no quiere decir que la sesión sirva**: el
     marcador solo dice que alguien confirmó una alguna vez, y el propio
     `portal.exigir_sesion` de Doyle lo advierte. Un mes después, no servía
     ninguna.
   - La búsqueda tardó **47 s** y terminó con los cuatro en `error`. NADRO,
     QuePharma y VICMA con "la sesión caducó (o el portal rechazó esta
     sesión)", cada uno con la URL de login a la que lo mandaron. LEVIC con
     "falla inesperada: Page.wait_for_timeout: Target page, context or browser
     has been closed", que es otra cosa y se clasifica aparte.
   - Continental lo leyó bien: tres huecos con motivo `la sesión caducó` y uno
     con `el portal no contestó`. Ningún cero, ninguna lista vacía. Como
     demostración del ticket 12 sirve; **lo que NO quedó demostrado contra el
     portal real es una fila con precio**, porque no hubo ninguna.

   Abrirlas es un acto manual con navegador visible y las credenciales del
   dueño (ADR 0001 de Doyle): `python -m doyle.sesion --proveedor <clave>`, o
   el botón "Iniciar sesión" de la pestaña Inicio de su web. **Hasta que se
   abran, el módulo de Pedido no puede traer un solo precio**, y los tickets 13
   y 14 no se pueden cerrar contra datos reales. Es lo primero que hay que
   hacer antes de seguir.

   **Qué queda sin demostrar del ticket 14, dicho con precisión (2026-09-19).**
   Las reglas —quién gana, el ahorro, las tres categorías de existencia— están
   escritas y probadas, y el recorrido del navegador cubrió los siete casos
   (incluido el que la pantalla tenía mal). Pero **todo eso corrió contra los
   dobles**: sin una sesión abierta no hay un solo precio de un portal de verdad,
   así que lo que NO está demostrado contra el mundo es de qué forma llega la
   existencia en cada portal. La tercera categoría —"dio precio y no dijo su
   existencia"— es la que más depende de eso: hoy se decidió que no compita con
   quien sí la confirmó, y **cuán seguido se cae en ella no se sabe**. Si
   resultara ser el caso ordinario en dos de los cuatro portales, la marca
   ámbar de "nadie confirmó existencia" sería lo que el encargado vea casi
   siempre, y entonces la decisión hay que volver a mirarla —no cambiarla a
   ciegas—. Se mide con `select proveedor, existencia_como_llego, count(*)`
   sobre `pedidos.precio_de_proveedor` en cuanto haya lecturas reales.

2. **El conteo de huecos envejece al consultar un precio, y lo dice.** La
   respuesta de `/api/renglon/{id}/precio` es de **un** renglón: no trae el
   conteo de la lista, y recalcularlo ahí necesitaría leer la lista entera por
   su id —`AlmacenamientoDelPedido` solo sabe leerla por fecha—. Volver a pedir
   la lista está descartado por un acuerdo anterior (*la lista se pide una sola
   vez*, fijado por tres pruebas en `test_vistas`, `test_sugerido` y
   `test_clasificacion`): dos lecturas en momentos distintos pueden no coincidir
   y nadie sabría cuál tiene razón. Así que la pantalla **marca el conteo como
   viejo y lo escribe** ("este conteo es de antes de eso; recarga la página").
   Envejece hacia el lado seguro —dice más huecos de los que quedan— pero es un
   remiendo. Descartar, devolver y ajustar **sí** lo traen recalculado y sin una
   consulta más: esas tres rutas cambiaron su lectura de *los precios de un
   renglón* por *los precios de la lista*, que es la misma consulta con otro
   `WHERE`. **Condición de disparo:** cuando el lote nocturno (ticket 18)
   consulte la lista entera de golpe, o cuando entre un `leer_por_id` al
   almacenamiento por otra razón, esto se cierra en una línea.

   **La condición se cumplió a medias con el ticket 18 y el hilo sigue
   abierto.** El lote sí consulta la lista entera de golpe, pero lo hace desde
   **otro proceso** y sin pasar por la ruta: no le agrega ni le quita nada al
   conteo que la pantalla muestra. Lo que sí cambió es cuánto duele — a la
   mañana la lista ya llega con sus precios, así que el encargado aprieta el
   botón muchas menos veces, que es justo cuando el conteo envejece.

   **Y la OTRA condición sí se cumplió entera con el ticket 19: ya existe
   `leer_por_id`** en `AlmacenamientoDelPedido` —lo estrenó el botón de
   completar, que recibe el id de la lista y necesita sus renglones—. Así que
   esto **se cierra en una línea** y el que venga después no tiene que
   construir nada: `/api/renglon/{id}/precio` puede releer la lista por su id,
   recalcular `conteo_de_precios` y `faltantes`, y devolverlos junto al renglón,
   exactamente como ya hacen descartar, devolver y ajustar. Cuesta **dos**
   consultas más por sondeo (la lista y sus precios), así que conviene hacerlo
   en la respuesta del POST y no en cada vuelta del GET.

3. **Un fallo de Doyle al PEDIR la búsqueda no deja rastro guardado.** Si
   `pedir_busqueda` truena —Doyle apagado, el puerto ocupado por otra cosa— no
   se escribe ninguna fila: no se sabe siquiera a qué proveedores se iba a
   preguntar, porque esa lista sale del acuse. El motivo vive solo en el
   registro en memoria del proceso, así que **una recarga de la página lo
   pierde** y el renglón vuelve a verse como "sin consultar". Es honesto —no se
   consultó nada— pero es menos información de la que había un segundo antes.
   Se arreglaría escribiendo cuatro filas con motivo contra una lista fija de
   proveedores, y eso es inventarse de dónde sale esa lista: se deja anotado en
   vez de resuelto a medias. **Condición de disparo:** si el lote nocturno
   (ticket 18) corre con Doyle caído y a la mañana no hay forma de saber que
   corrió, esto deja de ser un detalle.

   **El ticket 18 le quitó la mitad del filo.** El lote deja su resumen en el
   journal **pase lo que pase** —está en un `finally`, así que sale hasta
   cuando alguien mata el proceso— y ahí se lee cuántos renglones quedaron
   `no se pudo` y con qué tipo de falla. O sea que sí hay forma de saber que
   corrió y cómo le fue.

   **Y el ticket 19 cerró la otra mitad:** *"¿corrió el lote anoche?"* ya se
   contesta con SQL —`select ... from pedidos.corrida_del_lote`—, y la pantalla
   lo escribe arriba de la tabla en cada carga. **Lo que queda abierto de este
   hilo es solo lo de origen**: un fallo al PEDIR la búsqueda sigue sin dejar
   fila de precio, así que de un renglón concreto no se sabe **a qué
   proveedores** se le iba a preguntar. La corrida sí lo cuenta —`no_se_pudo`
   es exactamente ese número— y por eso `por_que_no_hay_lectura` devuelve
   `seguro=False` esa noche. **Condición de disparo, nueva:** si el `seguro=False`
   aparece dos noches seguidas, o si el encargado pregunta por un renglón
   concreto y la respuesta tiene que ser exacta, lo que hace falta es una tabla
   de detalle colgada de `corrida_del_lote_id`, y la función pura ya tiene el
   sitio donde dejar de adivinar (ADR 0007).

4. **El tercer invariante del ticket 17 está DECLARADO, no revisado.** "Ningún
   pedido enviado sin quién lo envió" necesita dos columnas que `pedidos.pedido`
   **todavía no tiene**: `estado` y `enviado_por`. Llegan con los tickets 20
   (los pedidos nacen en `borrador`) y 21 (`borrador` -> `enviado`, firmado con
   el correo que verificó Access). Inventarlas hoy habría sido escribir un
   `SELECT` que rebota en atlas con "column does not exist" y dejar el paso 6
   del despliegue rojo por algo que nadie prometió.

   Cómo quedó: la recolección lee `select * from pedidos.pedido` —que de paso
   es cómo se averigua la forma real de la tabla sin consultar el catálogo— y
   `revisar_pedidos_enviados` decide. Sin las columnas, el resultado es
   `PENDIENTE`: **se ve en la salida con su porqué y no tumba el despliegue**.
   Con ellas, el invariante empieza a revisar solo, sin que nadie vuelva a
   tocar el archivo. **Condición de disparo:** si los tickets 20 y 21 les ponen
   otro nombre a esas columnas, lo que hay que cambiar es
   `verificar.COLUMNAS_QUE_EXIGE_EL_ENVIO` y nada más — y si nadie lo cambia,
   el pendiente se queda imprimiéndose en cada despliegue, que es justo lo que
   se quiere.

5. **El horario del respaldo de SICAR está en `propuesta`** (ADR 0017 de
   farmacia-data): lo decide el dueño. Si se acepta mover el respaldo a las
   ~20:15, **hay que mover el timer de la cadena a las 21:00 en el mismo
   movimiento**, o el colchón baja de hora y media a 15 minutos.

   **Desde el ticket 18 son TRES cosas que se mueven juntas y no dos**: el
   respaldo, `farmacia-diario.timer` (20:30 → 21:00) y
   `continental-lote.timer` (22:00 → 22:30). El lote arma la lista con las
   ventas que la cadena acaba de meter, así que moverla a ella y no a él
   dejaría el lote trayendo precios para la lista de **ayer** — sin fallar y
   sin avisar. El aviso está escrito en mayúsculas dentro del propio
   `scripts/systemd/continental-lote.timer`, que es donde lo va a leer quien lo
   esté editando, y hay una prueba que comprueba que siga ahí.
6. **Falta probar `google-chrome --version` en atlas.** Si ese CPU de 2010 no
   lo aguanta, Doyle usa el Chromium de `apt` —que ya está medido— y la parte
   del ADR 0004 que dependía de Chrome queda cerrada.
7. **Qué hay en VITRINA 1-3.** Entró a la lista blanca de "medicamento" a
   petición del dueño, pero nadie escribió qué se guarda ahí.
8. **QuePharma casi seguro va a quedar fuera de la comparación**: usa código
   interno y no está confirmado que encuentre por EAN. Hay dos pendientes
   viejos de Doyle que responden esto —probar el EAN en QuePharma, y confirmar
   VICMA por cantidad de resultados—, y ahora sí importan.

   **El ticket 13 ya fijó las reglas y no espera a esas dos respuestas**, a
   propósito: las dos se resuelven mirando portales, y las cuatro sesiones
   siguen caducadas (hilo 1). Lo que se decidió es lo más estricto que sostiene
   el ADR 0002 —QuePharma empareja por EAN como NADRO y LEVIC, así que su final
   ordinario es `no empareja`; VICMA se acepta solo con exactamente un
   resultado— y **las dos respuestas solo pueden aflojarlo, nunca apretarlo**.
   Lo que cambiaría con cada una:

   - Si se confirma que QuePharma **sí encuentra por EAN** pero muestra código
     interno en la columna de clave, su caso pasa a ser el de VICMA y la línea
     que cambia es una: su entrada en `precios.REGLA_DEL_PROVEEDOR`. Con su
     ADR, porque es aflojar una garantía.
   - Si se confirma que QuePharma **no encuentra por EAN**, no cambia nada: hoy
     ya queda fuera con `no empareja`, que es lo correcto.
   - Si VICMA resultara **no** indexar el EAN, su excepción deja de estar
     sostenida y hay que quitársela: pasaría a `POR_EAN` y quedaría fuera casi
     siempre, como QuePharma.

   **Cómo se mide cuando haya sesiones:** consultar un renglón con EAN conocido
   y mirar `resultados` y `clave_del_proveedor` de las cuatro filas que quedan
   en `pedidos.precio_de_proveedor`. Esa tabla guarda exactamente lo que hace
   falta para responder las dos preguntas sin volver a los portales.
9. **El almacén de contraseñas de atlas baja una garantía.** Hoy no hay ninguna
   contraseña de proveedor en disco; después de la mudanza habrá cuatro,
   ofuscadas pero recuperables. Está aceptado con mitigación (permisos `700`,
   fuera de respaldos) en el ADR 0008 de Doyle. Si alguien saca una copia del
   disco, se cambian las cuatro contraseñas.
10. ~~**La pantalla no distingue "el lote no llegó" de "el lote no corrió".**~~
   **CERRADO por el ticket 19** (2026-09-19). Se cumplió su condición de
   disparo por el lado del ticket y no por el del encargado, y la salida **no**
   fue escribir las cuatro filas de hueco por renglón: fue guardar **una fila
   por corrida** en `pedidos.corrida_del_lote` y que la pantalla deduzca de ahí
   el estado de cada renglón sin lectura (ADR 0007). Los dos argumentos que
   hundían la otra opción siguen valiendo íntegros —habría que inventarse a qué
   proveedores se iba a preguntar, y ~11,000 filas de puro hueco en una noche
   que corte al 20%—.

   Hoy son seis motivos y cada uno lleva a un sitio distinto: *al lote se le
   acabó el tiempo*, *el lote no corrió sobre esta lista*, *la corrida del lote
   se cortó*, *el lote lo intentó y no pudo*, *el lote no lo miró* y *no tiene
   código de barras*. La regla que decide cuál le toca a cada renglón es una
   función pura con su tabla de casos (`faltantes.por_que_no_hay_lectura`), no
   un `if` del JavaScript.

   **Lo que quedó sin resolver, y por eso el hilo 3 sigue medio abierto:** se
   guarda *cuántos* renglones quedaron sin alcanzar, no *cuáles*. La noche en
   que el tope cortó **y además** hubo renglones `no se pudo`, de un renglón
   concreto no se puede afirmar cuál de los dos le tocó, y la pantalla escribe
   *"probablemente"* con el otro número al lado. Su condición de disparo está
   escrita en el ADR 0007 y repetida en el hilo 3.

11. **El lote vuelve a consultar los renglones que ya tienen precio.** No se
   saltan, a propósito: decidir "qué tan viejo es viejo" es una regla que nadie
   ha tomado, y la tabla solo crece, así que volver a consultar no pierde nada
   —solo gasta tope—. Hoy da igual porque a las 22:00 la lista del día acaba de
   nacer y no tiene ni una lectura. Empieza a importar el día que alguien cargue
   la pantalla por la tarde y consulte a mano media lista. **Condición de
   disparo:** si el lote se queda sin tiempo de forma habitual, lo primero que
   hay que probar es saltarse lo que ya tenga lectura de esa misma noche —antes
   de subir `pedido.tope_lote_minutos`, y antes de culpar a Doyle—.

   Lo segundo que hay que probar, por la misma razón, es **saltarse los
   renglones de `abarrote`**: no se le compran a estos cuatro proveedores
   (`CONTEXT.md`) y hoy el lote los consulta igual, porque nada se filtra. Ojo
   con hacerlo al revés: saltarse *"lo que no es medicamento"* tiraría también
   los 688 artículos **sin anaquel conocido**, que caen en `sin clasificar` y
   sí se compran. Solo es seguro saltarse lo que dice `abarrote` con todas sus
   letras.

12. **El día del corte se cierra a medias y ese pedacito se pierde.** El
   respaldo de SICAR corta a las 18:51, así que el último día del almacén
   siempre está incompleto: lo que se venda después llega al día siguiente. El
   sugerido acumula desde el corte del último cerrado y **arranca al día
   siguiente** de ese corte (ver `almacenamiento.ventana_de_reposicion`), así
   que si alguien cierra una lista cuyo `ventas_consideradas_hasta` es ese día
   a medias, la cola de esa tarde queda fuera. No se arregla moviendo el
   límite —incluir el día entero duplicaría todo lo demás de ese día, en
   silencio—: se arregla con hora en `marts.fct_ventas` o cerrando solo
   ventanas de días completos, y las dos son otra decisión. **Condición de
   disparo:** si el encargado reporta faltantes de productos que sí se
   vendieron, medir primero cuánto vende la farmacia después de las 18:51.
