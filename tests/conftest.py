"""La costura de pruebas de Continental, en un solo lugar y en pocas líneas.

Son cuatro fixtures porque los bordes son tres: el almacén que se lee, Doyle y
—desde el ticket 08— el almacenamiento donde el pedido se guarda. Ese es el
punto del prefactor: el equivalente en Marlowe es un fixture de ~100 líneas que
monta un `DISPLAY` falso y una URL de Postgres muerta solo para que
`import app` no truene, y existe porque allá la conexión nace al importar el
módulo. Aquí nace detrás de un `Depends`, así que sustituirla cabe en cuatro
renglones.

Ninguna prueba toca Postgres ni la red.

**El suite tarda ~1.0-1.3 s en la torre y el grueso no es una prueba.** Medido
el 2026-09-18, con el ticket 03 dentro: la primera prueba que sirve un archivo
estático paga 0.37-0.49 s de `mimetypes.init()` leyendo el registro de Windows.
En atlas (Linux) ese costo no existe, así que allá el mismo suite va por ~0.7 s.

El número subió con el ticket 03, y está medido, no adivinado: en corridas
seguidas, 30 pruebas en 0.73-0.95 s contra 43 en 0.95-1.37 s. Las 13 nuevas
cuestan ~0.2 s en total —~20 ms cada una de las que pasan por `TestClient`,
exactamente lo que ya costaba cada prueba de `test_bordes.py`— y ninguna
aparece entre las cinco más lentas. La recolección no se movió: 0.13-0.17 s, y
ahí es donde `--durations` no mira (ver la nota de `CARPETAS_QUE_NO_SE_MIRAN`
en `test_compila.py`).

**Con el ticket 04 dentro el suite no subió: bajó.** Medido el 2026-09-19, en
tres corridas seguidas, 52 recolectadas —50 pasan, 2 saltadas— en
**0.39-0.49 s**, con la recolección en 0.04-0.05 s. Las 9 pruebas nuevas no
aparecen entre las ocho más lentas. La diferencia contra los 0.95-1.37 s de
arriba no está en ellas: la prueba más lenta sigue siendo la primera que sirve
un archivo estático, y aquí costó 0.17 s contra los 0.37-0.49 s del día
anterior. Ese `mimetypes.init()` leyendo el registro de Windows cuesta distinto
según lo que el sistema tenga en caché, y es justo por eso que aquí se anotan
rangos de varias corridas y no un número solo.

**Con el ticket 05 dentro sigue igual.** Medido el 2026-09-19, en tres
corridas seguidas, 66 recolectadas —64 pasan, 2 saltadas— en **0.44-0.52 s**.
Las 14 pruebas nuevas de `test_clasificacion.py` casi no cuestan: la mitad
llama a una función pura sin almacén ni archivo, y las que leen
`config/continental.yml` lo hacen sobre un `cargar()` cacheado.

**Con el ticket 06 dentro sigue igual.** Medido el 2026-09-19, en tres corridas
seguidas, 79 recolectadas —77 pasan, 2 saltadas— en **0.50-0.70 s**, con la
recolección en 0.05 s. Las 12 pruebas nuevas de `test_vistas.py` cuestan poco y
solo una aparece entre las ocho más lentas, con 0.01 s: la mitad mira `VISTAS`,
que es un dato sin archivo ni almacén, y el resto pasa por `TestClient` como
las de sus vecinas. La más lenta del suite sigue siendo la primera que sirve un
archivo estático (0.16 s), y sigue siendo `mimetypes.init()` leyendo el
registro de Windows, no una prueba.

**Con el ticket 08 dentro sigue por debajo del segundo.** Medido el
2026-09-19, en tres corridas seguidas, 130 recolectadas —129 pasan, 1 saltada—
en **0.55-0.58 s**, con la recolección en 0.05 s. Las 29 pruebas nuevas de
`test_guardado.py` cuestan ~0.01 s cada una de las que pasan por `TestClient` y
nada las que solo tocan el doble en memoria: cinco de ellas aparecen entre las
ocho más lentas, todas con 0.01 s. Era el riesgo de este ticket y no lo fue:
guardar no agregó una sola consulta a Postgres porque el doble vive en un
diccionario, y **leer lo guardado ahorra dos lecturas del almacén por carga**
—el catálogo entero y 28 días de ventas— que antes se pagaban siempre.

**Con el ticket 09 dentro sube ~0.2 s y se sabe por qué.** Medido el
2026-09-19, en seis corridas seguidas, 149 recolectadas —148 pasan, 1 saltada—
en **0.70-0.80 s**, con la recolección en 0.07 s. Las 19 pruebas nuevas de
`test_acumulacion.py` cuestan ~0.01-0.02 s cada una de las que pasan por
`TestClient` —el doble de lo que cuesta una de sus vecinas, porque casi todas
hacen **dos** cargas de la página y un cierre en medio: ese ida y vuelta es lo
que se está probando— y nada las que llaman a `ventana_de_reposicion` directo.
Siete de ellas aparecen entre las ocho más lentas. La más lenta del suite sigue
sin ser una prueba: es la primera que sirve un archivo estático (0.15 s), que
ahora es la de la pantalla de este archivo, y sigue siendo `mimetypes.init()`
leyendo el registro de Windows.

Lo que este ticket **no** costó: ni una consulta más al almacén. La ventana de
reposición puede ser más larga que la del ritmo, pero la ruta sigue leyendo las
ventas una sola vez —el rango unión— y recortando en memoria. Lo que sí agrega
es una consulta corta al almacenamiento por carga, la del corte, que contra el
doble es recorrer una lista de diccionarios.

**Con el ticket 10 dentro el suite no se movió.** Medido el 2026-09-19, en
tres corridas seguidas, 188 recolectadas —187 pasan, 1 saltada— en
**0.87-1.07 s**, con la recolección en 0.08 s. Las 38 pruebas nuevas de
`test_descarte.py` cuestan ~0.01 s cada una de las que pasan por `TestClient`
y nada las que solo tocan el doble en memoria o leen un `.sql`; tres de ellas
aparecen entre las ocho más lentas, todas con 0.01 s. Descartar no agrega una
sola lectura del almacén: la lista ya está guardada y el conteo de descartados
sale de ella.

La recolección subió 0.01 s y se sabe de dónde: `sql/migraciones/` es una
carpeta nueva por la que `test_compila.py` camina buscando `.sql`, y el
archivo que hay dentro estrena un caso más de
`test_el_archivo_de_atlas_no_trae_retorno_de_carro`.

**Con el ticket 11 dentro el suite cuesta ~0.2 s más, y la torre ese día iba
lenta.** Medido el 2026-09-19, en tres corridas seguidas, 232 recolectadas
—231 pasan, 1 saltada— en **1.73-1.85 s**, con la recolección en 0.11 s. El
número se sale de los 0.87-1.07 s de arriba y **no son las 43 pruebas nuevas
de `test_ajuste.py`**: medido en la misma sesión y con el archivo nuevo fuera
(`pytest --ignore=tests/test_ajuste.py`), el suite tal como lo dejó el ticket
10 costó **1.39-1.88 s** contra los 0.87-1.07 s que había medido el día
anterior, con las mismas pruebas. La diferencia atribuible a este ticket
es la resta —~0.2 s para 43 pruebas, ~0.01-0.02 s cada una de las que pasan por
`TestClient`— y dos de ellas aparecen entre las ocho más lentas, las dos con
0.02 s, que son las que hacen **dos** peticiones y una carga en medio. Es el
mismo ruido de ±0.4 s de siempre, medido en vez de supuesto: la lección es la
de abajo —una sola corrida no dice nada, y antes de culpar a las pruebas nuevas
hay que correr el suite sin ellas—.

Ajustar una cantidad no agrega una sola lectura del almacén: la lista ya está
guardada y lo que cambia es una columna de una fila que ya se leyó.

**Con el ticket 12 dentro, el suite pasa de 232 a 336 recolectadas y la torre
sigue lenta.** Medido el 2026-09-19, en tres corridas seguidas, 336
recolectadas —335 pasan, 1 saltada— en **5.32-5.53 s**, con la recolección en
0.33 s. El número asusta al lado de los 1.73-1.85 s del ticket 11 y **no son
las 100 pruebas nuevas de `test_precio.py`**: medido en la misma sesión y con el
archivo nuevo fuera (`pytest --ignore=tests/test_precio.py`), el árbol del
ticket 11 —las mismas pruebas, más cuatro de la tabla nueva— costó
**3.65-4.16 s** contra los 1.73-1.85 s de esa mañana. La diferencia atribuible
a este ticket es la resta: **~1.3 s para 100 pruebas**, ~0.01 s cada una de las
que pasan por `TestClient`, exactamente lo que ya costaba cada vecina. La más
lenta del suite sigue sin ser una prueba de este ticket: es
`test_la_pantalla_dice_el_rango_de_ventas...`, con 0.42 s, igual que antes.

Es la misma lección de siempre, con otro número: **antes de culpar a las
pruebas nuevas, corre el suite sin ellas.**

Y hay una regla que este ticket agrega, porque estrenó lo primero que podría
tardar de verdad: **ninguna prueba espera a Doyle ni duerme un segundo.** La
espera entra por argumento (`dormir` y `ahora` de `consultar_a_doyle`) y las
pruebas del tope pasan un reloj que avanza cuando alguien duerme, así que un
sondeo de ciento veinte segundos simulados cuesta microsegundos reales. Y la
fixture `consultas` sustituye el hilo por un lanzador que ejecuta la tarea ahí
mismo: si una prueba de precios llega a tardar, está mal planteada.

**Con el ticket 13 dentro el suite no se movió, y eso es lo esperado.** Medido
el 2026-09-19, en tres corridas seguidas, 400 recolectadas —399 pasan, 1
saltada— en **5.27-5.70 s**. Las 64 pruebas nuevas de
`test_emparejamiento.py` cuestan **0.24-0.27 s corriendo solas**, y la
diferencia contra el árbol del ticket 12 medido en la misma sesión
(`pytest --ignore=tests/test_emparejamiento.py`: 4.75-5.27 s) cabe dentro del
ruido de ±0.4 s de la torre.

Que cuesten tan poco no es suerte: **63 de los 64 casos llaman a una función
pura** —`precios.emparejar` recibe dos objetos congelados y devuelve otro— sin
almacén, sin archivo y sin `TestClient`. **Uno solo** pasa por la aplicación
entera, y es el que demuestra que `no empareja` llega hasta la fila guardada. **Ninguna aparece entre las doce más lentas**
(`pytest --durations=12`): la más lenta del suite sigue siendo
`test_la_pantalla_dice_el_rango_de_ventas...`, con 0.33 s.

**Con el ticket 14 dentro el suite no subió, y de paso la torre volvió a
demostrar que su número no significa nada por sí solo.** Medido el 2026-09-19,
en tres corridas seguidas, 454 recolectadas —453 pasan, 1 saltada— en
**1.84-2.05 s**. El número **baja** de los 5.27-5.70 s del ticket 13 con 53
pruebas MÁS, y no es una optimización de nadie: es la misma torre en otro
momento del día. La resta que sí significa algo se midió en la misma sesión:
con el archivo nuevo fuera (`pytest --ignore=tests/test_comparacion.py`) el
árbol del ticket 13 costó **1.62-1.84 s**, así que las 53 pruebas nuevas
cuestan ~0.2 s. Corriendo solas, **0.22 s**.

Que cuesten tan poco es por lo mismo que en el 13: **41 de las 50 funciones de
prueba no levantan la aplicación** —`comparacion.comparar` recibe lecturas
congeladas y un entero y devuelve otro objeto congelado, sin almacén, sin red y
sin `TestClient`; las tres parametrizadas dan los 53 casos—. Las **nueve** que
quedan pasan por la aplicación entera y son las que demuestran que la
comparación llega hasta la pantalla con la cantidad correcta.

**La lección, otra vez y con el signo al revés: un número solo no dice nada.**
Si se hubiera mirado nada más el total, este ticket parecería haber hecho el
suite tres veces más rápido.

**Con el ticket 15 dentro el suite sigue igual, y la resta está medida.**
Medido el 2026-09-19, en tres corridas seguidas, 500 recolectadas —499 pasan, 1
saltada— en **1.96-2.02 s**, con la recolección en 0.13 s. Con el archivo nuevo
fuera (`pytest --ignore=tests/test_huecos.py`) y en la misma sesión, el árbol
del ticket 14 costó **1.80-1.86 s**: las 46 pruebas nuevas de `test_huecos.py`
cuestan ~0.15 s, y corriendo solas, **0.19-0.22 s**.

Por lo mismo de siempre: **33 de las 46 no levantan la aplicación**
—`contar_la_lista` recibe comparaciones y devuelve un conteo; `elegir_ganador`
recibe lecturas y devuelve un ganador; nueve leen `index.html` y comparan
cadenas—. Las **siete** que pasan por `TestClient` son las que demuestran que
el conteo llega hasta el JSON de la lista y que descartar lo recalcula; tres de
ellas aparecen entre las ocho más lentas, con 0.02-0.03 s. La más lenta del
suite sigue sin ser una prueba de este ticket:
`test_la_pantalla_dice_el_rango_de_ventas...`, con 0.13 s.

Lo que este ticket **sí** costó y conviene anotar: descartar, devolver y
ajustar cambiaron su lectura de *los precios de un renglón* por *los precios de
la lista*. Es **la misma consulta**, no una más —un `DISTINCT ON` con otro
`WHERE`—, y a cambio el conteo de arriba no envejece con cada clic.

**Con el ticket 16 dentro ya no queda ninguna saltada.** Medido el
2026-09-19, en tres corridas seguidas, 525 recolectadas —**525 pasan, 0
saltadas**— en **2.03-2.50 s**, con la recolección en 0.15 s. Con el archivo
nuevo fuera (`pytest --ignore=tests/test_despliegue.py`) y en la misma sesión,
el árbol costó 2.43 s: las 23 pruebas nuevas de `test_despliegue.py` no se
distinguen del ruido de ±0.4 s de la torre, y corriendo solas cuestan
**0.27-0.28 s**.

El salto de 500 a 525 recolectadas son dos cosas: las 23 nuevas, y **tres
casos que `test_compila.py` ya tenía escritos y que hasta hoy no revisaban
nada**. `scripts/desplegar.sh` y `scripts/systemd/continental-web.service`
nacieron con este ticket, así que los dos casos de CRLF y el del shebang
dejaron de ser un `skip` con su motivo y empezaron a mirar archivos de verdad.
Esa era toda la idea de haberlos dejado puestos desde el ticket 02.

Lo único que llama la atención en `--durations` es un **setup** de 0.07 s, y
está explicado: la fixture `puerto_ocupado` abre un socket de verdad en
loopback, porque lo que se prueba es una sonda sobre el sistema operativo y un
doble la haría contestar lo que la prueba quiera oír. No sale de la máquina, no
hay conexión, y el suite sigue corriendo sin Postgres, sin atlas y sin `.env`.

La saltada bajó de 2 a 1 con el ticket 07: `sql/crear_tablas.sql` estrenó los
casos de `.sql` de `test_compila.py` y solo queda saltado el del shebang, que
espera a que exista un `.sh`.

**Con el ticket 18 dentro el suite sube ~0.1 s, y es casi todo recolección.**
Medido el 2026-09-19, en tres corridas seguidas, 628 recolectadas —**628 pasan,
0 saltadas**— en **2.51-2.72 s**, con la recolección en 0.18 s. Con el archivo
nuevo fuera (`pytest --ignore=tests/test_lote.py`) y en la misma sesión, el
árbol del ticket 17 costó **2.39-2.47 s**; las 54 pruebas de `test_lote.py`
corriendo solas cuestan **0.09-0.10 s**, y ninguna aparece entre las ocho más
lentas. La más lenta del suite sigue sin ser de este ticket:
`test_la_pantalla_dice_el_rango_de_ventas...`, con 0.13 s.

El salto de 565 a 628 son cuatro cosas: las 54 nuevas, 5 de `test_verificar.py`
(el invariante 4, el de la clase ABC), 3 casos que `test_compila.py` gana solo
—hay un módulo de Python más y **dos unidades de systemd más** por las que
caminar— y 1 del `ast` de las funciones puras, que ahora son siete.

**Y este ticket estrena una regla que hay que respetar, no admirar: ninguna
prueba del lote espera, y varias simulan una hora entera.** El tope de 60
minutos se prueba con el mismo mecanismo que el tope por consulta del ticket
12: `ahora` y `dormir` entran por argumento y `_reloj()` devuelve un par en el
que el tiempo **solo avanza cuando alguien duerme**. Así
`test_se_detiene_al_tope_de_sesenta_minutos` mide 3600 s simulados en
microsegundos reales, y lo que avanza es **exactamente lo que el código pidió
esperar** — no un `monkeypatch` de `time.sleep`, que mediría otra cosa. Si una
prueba de `test_lote.py` empieza a tardar segundos, está mal planteada.

Que cuesten tan poco es por lo de siempre: **la mayoría no levanta nada**.
`ordenar_por_importancia` recibe renglones congelados y un diccionario;
`Cronometro` recibe un reloj; `contar_los_motivos` recibe una tupla; catorce
leen dos archivos `.service`/`.timer` y comparan cadenas. Las que sí orquestan
pasan por los **tres dobles** y no por `TestClient`: el lote es otro proceso y
no toca FastAPI.

**Con el ticket 19 dentro el suite sube ~0.5 s y casi nada es de él.** Medido
el 2026-09-19, en corridas seguidas, 749 recolectadas —**749 pasan, 0
saltadas**— en **3.55-4.46 s**, con la recolección en 0.19 s. Con los dos
archivos nuevos fuera y en la misma sesión
(`pytest --ignore=tests/test_motivos.py --ignore=tests/test_latido.py`), el
árbol del ticket 18 costó **3.66-4.06 s** contra los 2.51-2.72 s de esa mañana:
otra vez la torre en otro momento del día. **Las 117 pruebas nuevas corriendo
solas cuestan 0.45-0.50 s**, y ninguna aparece entre las ocho más lentas — la
más lenta del suite sigue siendo `test_la_pantalla_dice_el_rango_de_ventas...`,
con 0.12 s.

El salto de 632 a 749 son las 117 nuevas —83 en `test_motivos.py`, 34 en
`test_latido.py`— más dos casos
que `test_sql_del_pedido.py` gana solo: sus pruebas parametrizadas recorren
`TABLAS`, que pasó de cuatro a **cinco** con `pedidos.corrida_del_lote`.

Que cuesten tan poco es por lo de siempre: **la mayoría no levanta nada**.
`por_que_no_hay_lectura` recibe dos argumentos y devuelve un objeto congelado;
`armar_la_url` recibe cadenas y devuelve una cadena; una docena lee `sql/` o
`index.html` y compara texto. Las que sí pasan por `TestClient` son las que
demuestran que el motivo llega hasta el JSON y que el botón consulta lo que
dice consultar.

**Y este ticket agrega dos reglas más, las dos aprendidas a la mala:**

1. **Ninguna prueba manda un latido de verdad, ni a la Kuma real ni a ninguna
   otra.** El borde HTTP entra por argumento (`pedir`), igual que `dormir` y
   `ahora`. Esa Kuma la comparten Marlowe y la cadena de farmacia-data: un
   latido de prueba escribiría en el historial de un monitor que alguien mira.
2. **Lo que no se le prepara al `DoyleFalso` NO se consulta.** Un término sin
   resultado preparado sale `pendiente` —que es justo lo que hace un portal
   mientras carga— y la consulta espera el tope entero: **120 segundos reales**
   por renglón. Pasó al escribir `test_motivos.py` y el archivo tardó 120 s en
   vez de 0.4 s. Si una prueba de precios empieza a tardar, lo primero que hay
   que mirar es qué clave se está consultando sin tener respuesta preparada.

**La medición en la torre tiene ruido de ±0.4 s**, así que una sola corrida no
dice nada: corre tres. Y si el número se sale de lo anterior, mide antes de
culpar a las pruebas nuevas: `pytest --durations=8` para el tiempo de las
pruebas y `pytest --collect-only` para el de la recolección, que son dos
problemas distintos.

## UNA CORRIDA QUE SE CUELGA SIN AVANZAR — era un proceso huérfano, no el suite

Pasaó en la torre el 2026-09-19 y quedó resuelto el mismo día. Se veía así: el
suite se paraba en mitad de los puntos, sin consumir CPU, y no volvía. Llegó a
colgarse en **6 de 6 corridas seguidas**.

**La causa no estaba en el suite: era un `uvicorn` huérfano.** Un servidor
sembrado que se levantó para mirar la pantalla se quedó colgado —su primera
versión abría un `TestClient` dentro del `on_event("startup")` de la propia
aplicación, o sea un cliente de prueba dentro del ciclo de vida del servidor que
lo atiende— y **nunca murió**: dos procesos de Python vivos tres horas, el hijo
con 62 s de CPU consumidos y 1.6 GB residentes.

**La medición, con el proceso como única variable** (2026-09-19):

| | antes de matarlo | después de matarlo |
|---|---|---|
| árbol con el ticket 19 | 4 de 5 colgadas | **8 de 8 verdes**, 2.78-3.41 s |
| árbol del ticket 18 (sin tocar) | 6 de 6 colgadas | **4 de 4 verdes**, 2.62-3.39 s |

El árbol nunca fue la variable: el mismo código que colgaba 6 de 6 pasó 4 de 4
una hora después, sin cambiarle una línea.

**LA LECCIÓN, QUE ES LO QUE VALE LA PENA GUARDAR: comprobar que un puerto esté
libre NO es comprobar que el proceso murió.** `netstat -ano | findstr :8585`
salió vacío —tres veces, a tres personas distintas— y los dos procesos seguían
ahí: el socket se había soltado y el proceso no. Después de levantar un servidor
a mano, la comprobación que sirve es por **proceso**:

    powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name LIKE 'python%'\" | Where-Object { $_.CommandLine -like '*Continental*' }"

**El mecanismo, que sigue siendo cierto y conviene conocer.** `TestClient`
levanta un bucle de eventos nuevo por petición, y en Windows ese bucle se
despierta a sí mismo con un par de sockets de loopback (`_fallback_socketpair`,
porque Windows no tiene `socketpair`). El volcado del proceso colgado, con
`pytest -o faulthandler_timeout=8`, terminaba en el `accept()` de ese par. En
atlas (Linux) ese camino **no existe**: `epoll` no usa el par de respaldo.

**Lo que NO se supo ese día, y por eso no se tocó nada.** Si el suite por sí
solo puede colgarse por ese camino, sin un huérfano compitiendo, no quedó
demostrado ni descartado: después de la limpieza fueron **12 corridas seguidas
sin un solo cuelgue**, y eso era lo único que se podía afirmar. Si volvía a
pasar **con la máquina limpia**, el arreglo iba por reusar un `TestClient` de
sesión separando el cliente (de sesión) de los dobles (por prueba). Lo que
**no** es el arreglo: `WindowsSelectorEventLoopPolicy`, que en Windows usa el
mismo par de sockets de respaldo y mueve el problema sin quitarlo.

### El 2026-09-20 se hizo ese arreglo — y el cuelgue no se reprodujo para medirlo

Se pidió por el mismo síntoma, reportado ahora como **entre 1 de cada 12 y 1 de
cada 3 corridas**. Lo primero fue lo de la lección de arriba: comprobar la
máquina **por proceso**. No había ningún huérfano de Continental. Lo que sí
había eran dos `python` de otro proyecto, uno quemando un núcleo entero, y es
por eso que los tiempos de esta sección son de 6-14 s y no de los 2-3 s de los
tickets anteriores: **son otro día y otra carga, no otro suite.**

**Y entonces el cuelgue no apareció: 0 de 112 corridas.** 64 sobre el árbol de
`b30fbf6`, 24 sobre el árbol vivo y 24 sobre una copia congelada de `7820a13`,
con tope de 60 s por corrida y matando el árbol de procesos de la que se pasara.
Con 0 de 112, la regla de tres deja la frecuencia de cuelgue de ese día **por
debajo de 2.7% con 95% de confianza** — por debajo del piso de 1 de cada 12
(8.3%) que se había reportado. No dice que el cuelgue no exista; dice que ese
día, en esta máquina, no estaba ocurriendo.

**Por qué se midió sobre una copia congelada, que es una lección aparte.** A
media medición alguien editó el repo: `config/continental.yml` y dos archivos de
`tests/` cambiaron entre la corrida 37 y la 38, y en una tanda posterior la
huella del árbol **cambió nueve veces en 24 corridas**. Un antes y un después
sobre un árbol que se mueve no compara nada. Por eso el harness guarda un hash
del árbol en cada corrida y la comparación de abajo se hizo sobre
`git archive HEAD` en una carpeta temporal, con el arreglo como **única**
variable.

**Lo que sí quedó medido** (24 corridas de cada lado, misma copia, misma hora):

| | antes | después |
|---|---|---|
| bucles de eventos por corrida | **412** | **1** |
| corridas colgadas | 0 de 112 | 0 de 24 |
| tiempo de las que pasan | 7.04-14.46 s, mediana **9.57 s** | 5.98-8.16 s, mediana **6.48 s** |

Y sobre el repo de verdad, ya con el arreglo dentro: **24 de 24 verdes, 0
colgadas**, 5.61-17.46 s con mediana 6.17 s —la de 17.46 s es la primera de la
tanda, con todo frío—, 841 pruebas, árbol estable durante toda la tanda.

Los 412 no son una cuenta de peticiones: se contaron parchando
`anyio.from_thread.start_blocking_portal`, que es literalmente un bucle de
eventos nuevo cada vez. El suite hace 228 llamadas escritas a `cliente.*`; las
otras salen de las parametrizadas y de las pruebas que piden dos veces.

**Se dejó puesto, y la razón se dice entera porque la regla del repo es esa.**
El arreglo **no** se puede acreditar con una baja de cuelgues: no había cuelgues
que bajar. Lo que sí hace, y está medido, es quitar 411 de los 412 bucles —el
mecanismo exacto donde terminaba el volcado de pila— y **~3 s de mediana, un
32%**, con el rango apretándose de 7.4 s de ancho a 2.2 s. Un cambio que borra
el mecanismo sospechoso y de paso deja el suite un tercio más rápido no se
revierte por no haber podido reproducir el síntoma; lo que no se hace es
cantarlo como arreglado.

**Si vuelve a colgarse con esto puesto, el cliente de sesión no era la causa** —
un solo bucle por corrida ya no alcanza para explicarlo— y lo siguiente que hay
que mirar es, en este orden: los procesos vivos (por proceso, no por puerto),
qué más estaba cargando la torre, y el volcado real con
`pytest -q -o faulthandler_timeout=8`. Sin volcado no se diagnostica nada.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from continental.consultas import RegistroDeConsultas
from continental.dobles import AlmacenamientoFalso, AlmacenFalso, DoyleFalso
from continental.web.app import app
from continental.web.dependencias import (
    obtener_almacen,
    obtener_almacenamiento,
    obtener_consultas,
    obtener_doyle,
)


# --------------------------------------------------------------- la pantalla
#
# DESDE EL TICKET 28 LA PANTALLA SON TRES ARCHIVOS: `index.html`, la hoja de
# estilos `continental.css` y el JavaScript `continental.js`. Hasta el 27 era
# uno solo, y más de cuarenta pruebas leían ese archivo —o lo pedían a `/`—
# para afirmar dos clases de cosas: que algo ESTÁ (una ruta, una frase que
# llega hecha de Python, una regla de CSS) y que algo NO está (una frase que el
# JavaScript no puede componer, un cálculo que no puede hacer).
#
# Las dos se debilitarían en silencio si siguieran leyendo solo `index.html`:
# lo que "está" se iría a otro archivo y la prueba se pondría roja —eso es
# ruidoso y no preocupa—, pero lo que "no está" se volvería verdad por vacío,
# porque el texto que revisa ya no trae ni el CSS ni el JavaScript. Por eso
# ninguna prueba lee `index.html` a secas: todas piden **la pantalla entera**,
# armada como la ve el navegador —la hoja y el script puestos en el mismo sitio
# donde estaban cuando iban dentro—, y así cada guardia sigue revisando
# exactamente el mismo texto que revisaba antes de separar.

ESTATICOS = Path(__file__).resolve().parents[1] / "src" / "continental" / "web" / "static"

#: Cómo se enlazan los dos archivos. Se buscan con una expresión y no con la
#: etiqueta escrita a mano para que `pantalla_servida` pida la MISMA ruta que
#: pide el navegador, sea cual sea.
_HOJA = re.compile(r'<link rel="stylesheet" href="([^"]+)">')
_SCRIPT = re.compile(r'<script src="([^"]+)"></script>')


def _armar(html: str, leer) -> str:
    """El HTML con su hoja y su script puestos donde el navegador los pone.

    Exige que haya **exactamente una** hoja y **exactamente un** script: si
    alguien agrega un tercer archivo, esta función se pone roja en vez de
    dejarlo fuera de todas las guardias sin avisar.
    """
    hojas = _HOJA.findall(html)
    scripts = _SCRIPT.findall(html)
    assert len(hojas) == 1, f"la pantalla enlaza {len(hojas)} hojas de estilo y no una"
    assert len(scripts) == 1, f"la pantalla enlaza {len(scripts)} scripts y no uno"
    html = _HOJA.sub(lambda m: "<style>\n" + leer(m.group(1)) + "</style>", html)
    return _SCRIPT.sub(lambda m: "<script>\n" + leer(m.group(1)) + "</script>", html)


def _del_disco(ruta_publica: str) -> str:
    """Un archivo estático leído del disco a partir de su ruta pública.

    En binario y decodificando a mano, igual que los `_texto` de cada prueba:
    si alguien lo guarda en latin1, esto se pone rojo aquí.
    """
    assert ruta_publica.startswith("/static/"), ruta_publica
    return (ESTATICOS / ruta_publica.removeprefix("/static/")).read_bytes().decode("utf-8")


def pantalla_completa() -> str:
    """La pantalla entera —HTML, CSS y JavaScript— leída del disco."""
    return _armar(_del_disco("/static/index.html"), _del_disco)


def pantalla_servida(cliente: TestClient) -> str:
    """La pantalla entera **como la sirve la aplicación**: `/` y lo que enlaza.

    Para las pruebas que ya pedían `/` a propósito —"se comprueba sobre el HTML
    servido, que es lo que el navegador recibe"—: los dos archivos se piden
    también por HTTP, y un 404 en cualquiera de ellos pone roja la prueba.
    """
    def pedir(ruta: str) -> str:
        respuesta = cliente.get(ruta)
        assert respuesta.status_code == 200, f"{ruta} contestó {respuesta.status_code}"
        return respuesta.text

    return _armar(pedir("/"), pedir)


@pytest.fixture(autouse=True)
def _sin_env_del_disco(monkeypatch: pytest.MonkeyPatch) -> None:
    """El suite da el mismo resultado haya o no haya `.env` en la máquina.

    Corre en **todas** las pruebas, sin que nadie la pida. No es celo: es la
    única forma de que "pasa en la torre" signifique "pasa en atlas".

    ## La falla que existe para impedir, que ya ocurrió

    `config.cargar` llama a `load_dotenv(RAIZ / ".env")` antes de leer el
    entorno. Una prueba que simula *"falta esta variable"* con
    `monkeypatch.delenv(...)` funciona en una máquina **sin** `.env` y **deja
    de simular nada** en una que sí lo tenga: dotenv la repone del disco y la
    prueba afirma sobre un sistema bien configurado creyendo que lo probó roto.

    Pasó el 2026-09-20, el día que atlas estrenó su `.env`:
    `test_el_borde_real_del_almacen_mal_configurado_es_un_hueco_y_no_tumba_nada`
    seguía verde aquí y se puso roja allá —y de paso conectaba a Postgres de
    verdad, justo lo que su docstring promete no hacer—. Lo caro no fue la
    prueba: el suite es el **paso 3 de `scripts/desplegar.sh`**, así que una
    prueba roja en atlas es la capacidad de desplegar, perdida.

    ## Por qué neutralizar y no borrar el archivo

    Borrar o mover el `.env` de la máquina para correr pruebas es tocar la
    configuración de producción desde el suite, y un `pytest` interrumpido lo
    dejaría movido. Esto no toca el disco: sustituye la **función** en los dos
    módulos que la llaman, y `monkeypatch` la devuelve al terminar cada prueba.

    Ninguna prueba depende de que el `.env` se lea —en la torre no existe y el
    suite está verde desde siempre—, así que esto no le quita cobertura a nada.
    """
    from continental import config

    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: False)

    # `iniciar.py` tiene su propia llamada, y es la que decide dónde escucha el
    # servicio. Importarlo aquí es barato: el suite ya lo importa en
    # `test_despliegue.py`, y no abre nada al importarse.
    import iniciar

    monkeypatch.setattr(iniciar, "load_dotenv", lambda *a, **k: False)


@pytest.fixture
def almacen() -> AlmacenFalso:
    """El doble del almacén. Se le cargan filas y las devuelve tal cual."""
    return AlmacenFalso()


@pytest.fixture
def doyle() -> DoyleFalso:
    """El doble de Doyle. Guarda las búsquedas pedidas en memoria."""
    return DoyleFalso()


@pytest.fixture
def almacenamiento() -> AlmacenamientoFalso:
    """El doble del almacenamiento: las tablas del pedido, en memoria.

    Nace vacío en cada prueba, que es lo que una base recién creada sería. Y
    rechaza lo mismo que los CHECK y los UNIQUE del DDL — el porqué está en su
    docstring, en `dobles.py`: un doble permisivo deja el suite en verde y
    rompe en atlas.
    """
    return AlmacenamientoFalso()


@pytest.fixture
def consultas() -> RegistroDeConsultas:
    """El registro de consultas de precio, **sin hilos** (ticket 12).

    `lanzar` ejecuta la tarea ahí mismo en vez de arrancar un hilo, y eso es lo
    que hace que una prueba de precios sea determinista: cuando la petición
    vuelve, la consulta ya terminó y el precio ya está en el doble del
    almacenamiento. Con hilos de verdad habría que esperar —y esperar en una
    prueba es dormir, que es justo lo que este suite no hace— o sincronizar con
    un `Event`, que probaría la sincronización y no el código.

    Lo que **no** se finge aquí es la espera a Doyle: eso lo resuelven el
    `dormir` y el `ahora` de `consultas.consultar_a_doyle`, que entran por
    argumento. Contra el `DoyleFalso` la primera vuelta ya viene terminada, así
    que ni siquiera se duerme una vez.

    El registro es nuevo en cada prueba, que es lo que sería un proceso recién
    arrancado. El de verdad vive en el módulo y se comparte: uno compartido
    entre pruebas dejaría una consulta "en curso" de una prueba bloqueando la
    siguiente.
    """
    return RegistroDeConsultas(lanzar=lambda tarea: tarea())


@pytest.fixture(scope="session")
def cliente_de_sesion():
    """Un solo `TestClient` —y un solo bucle de eventos— para todo el suite.

    **El `with` es todo el punto, no el ámbito.** `TestClient` sin `with`
    levanta un bucle de eventos **por petición**
    (`starlette/testclient.py:423-428`: `_portal_factory` llama a
    `anyio.from_thread.start_blocking_portal` cada vez que no hay un portal
    abierto). Con `with`, `__enter__` abre el portal una vez y todas las
    peticiones lo reusan. Medido en la torre el 2026-09-20 contando las
    llamadas a `start_blocking_portal`: **412 bucles por corrida antes, 1
    después.**

    Cada bucle nuevo importa porque en Windows se despierta a sí mismo con un
    par de sockets de loopback —`proactor_events._make_self_pipe` →
    `socket._fallback_socketpair` → `socket.accept()`, porque Windows no tiene
    `socketpair`— y ese `accept()` es donde terminaba el volcado de pila de una
    corrida colgada. Es el camino descrito arriba. En atlas (Linux) no existe:
    `epoll` no usa el par de respaldo.

    **No guarda estado de nadie, y por eso puede ser de sesión.** Lo que cambia
    por prueba no vive en el cliente sino en `app.dependency_overrides`, que la
    fixture `cliente` pone y quita en cada una. `app` ya se compartía: es un
    objeto de módulo. Y ninguna prueba del suite usa cookies, encabezados
    pegados al cliente ni websockets, que es lo único que un cliente reusado
    arrastraría de una prueba a la siguiente.

    **El `with` corre el ciclo de vida de la aplicación.** Hoy `app` no
    registra `startup`, `shutdown` ni `lifespan` —los bordes nacen detrás de un
    `Depends`, no al arrancar—, así que abrirlo no conecta a nada ni levanta un
    hilo. El día que se registre uno, esta fixture lo va a ejecutar una vez por
    corrida: si ese ciclo toca Postgres o la red, esto deja de ser gratis y hay
    que mirarlo aquí.
    """
    with TestClient(app) as cliente_de_pruebas:
        yield cliente_de_pruebas


@pytest.fixture
def cliente(
    cliente_de_sesion: TestClient,
    almacen: AlmacenFalso,
    doyle: DoyleFalso,
    almacenamiento: AlmacenamientoFalso,
    consultas: RegistroDeConsultas,
):
    """La aplicación real con los cuatro bordes sustituidos.

    **El cliente es de sesión y los dobles son por prueba**, y por eso son dos
    fixtures y no una. Son dos vidas distintas: el cliente no tiene por qué
    nacer de nuevo —lo único que hacía al nacer era un bucle de eventos más,
    que es el mecanismo del cuelgue de arriba—, y los dobles sí, porque nacen
    vacíos como lo haría una base recién creada.

    Se limpia al terminar: `app` es un objeto de módulo y un override que
    sobrevive a su prueba contamina a las demás en un orden que depende de
    cómo pytest recolectó los archivos — el tipo de falla que se descubre un
    mes después y cuesta media tarde. Eso no cambió: lo que se comparte es el
    cliente, no los dobles.
    """
    app.dependency_overrides[obtener_almacen] = lambda: almacen
    app.dependency_overrides[obtener_doyle] = lambda: doyle
    app.dependency_overrides[obtener_almacenamiento] = lambda: almacenamiento
    app.dependency_overrides[obtener_consultas] = lambda: consultas
    yield cliente_de_sesion
    app.dependency_overrides.clear()
