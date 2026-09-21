# Estado de Continental — 2026-09-21

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

**Dos casillas del ticket 18 siguen SIN MARCAR** (más la del timer, que está
escrito y probado pero no instalado porque Continental todavía no está en
atlas):

- **El orden de importancia por clase ABC. Ya no es un bloqueo externo.**
  `marts.dim_producto.clase_abc` ('A'/'B'/'C'/NULL) existe: farmacia-data la
  materializó el 2026-09-20 (`c989ecb`, su ADR 0018), el rol `continental` la
  lee, y Continental la usa desde `f3d7120`
  (`almacen.LA_CLASE_ABC_ESTA_EN_DIM_PRODUCTO = True`). Un producto sin ventas
  en 365 días queda en NULL **a propósito** —el 55% del catálogo— y el lote lo
  manda al final. La casilla sigue abierta por una decisión de este repo, no
  por farmacia-data: `Orden.cumple_el_orden` es falso si **un solo** renglón
  no tiene clase, así que con ese NULL intencional la bitácora puede decir
  "SIN CUMPLIR" en noches en que el orden es exactamente el del ADR 0018. Está
  anotado en el ticket 18. No se inventó un orden alterno: el propio ADR 0018
  descartó "ordenar por la utilidad de la ventana" con su razón escrita.
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

**Y desde el ticket 20 la comparación se vuelve una decisión: la lista se parte
en pedidos, uno por proveedor.** Cada renglón dice a quién se le pide —por
omisión el más barato con existencia, que es el ganador del ticket 14— y **una
persona puede cambiarlo**, porque hay razones que el sistema no ve: mínimo de
pedido, días de entrega, crédito con cada proveedor (ADR 0002). Un botón
convierte la lista en un pedido por proveedor, con su total y sus renglones
dentro; los pedidos **nacen en `borrador`** y se pueden volver a armar mientras
sigan así.

**Y desde el ticket 21 un pedido se puede enviar — que aquí quiere decir otra
cosa de lo que parece.** `borrador` → `enviado`, firmado con el correo que
verificó Access, y **Continental no le manda nada a ningún proveedor**: no entra
a los portales y no va a entrar (regla 1 de `CLAUDE.md`, y el ADR 0002 lo dejó
fuera de alcance). Lo que se guarda es la **declaración** de una persona —*yo ya
lo capturé en el portal de NADRO*— con su correo y la hora. Por eso lleva firma
y no acuse: el hecho ocurrió en otra pantalla, con otras credenciales, y lo
único verdadero que se puede escribir es quién lo dice y cuándo lo dijo. El
porqué entero, con las tres alternativas descartadas, en el ADR 0009; la
pantalla lo desmiente con todas sus letras en el mismo bloque del botón, no en
una nota al pie.

**El total en pesos va DENTRO del botón** —`Enviar a LEVIC — $832.10`—, que es
el sitio donde de verdad se ve antes de apretar. Cuando no se puede saber dice
`total sin saber`, nunca `$0.00`. Y **un pedido sin total se envía igual**: la
quinta casilla del ticket 20 dice que un renglón sin precio se pide igual, y el
precio de verdad lo ve el encargado en el portal mientras lo captura. Lo que
**no** se envía es un pedido **vacío** —el que se quedó sin renglones al volver
a partir—: se parecen y son opuestos.

**Al enviar, sus renglones pasan a `en tránsito`**, en la misma transacción. Es
lo que impide pedir dos veces lo mismo, y es la primera vez que algún código
escribe ese estado: hasta el ticket 20 solo lo nombraban comentarios y pruebas.
De ahí sale un efecto que no estaba en el ticket y sí en el código: las cuatro
cuentas de "qué falta" —la partición, el conteo de huecos, la cola del botón de
completar y el aviso de sesiones caducadas— salen ahora de
`PedidoSugeridoGuardado.por_repartir` y no de `de_trabajo`. Contar un renglón ya
pedido mandaría a visitar cuatro portales ajenos por mercancía que viene en
camino.

**Cuatro cosas del 21 que cazó el recorrido del navegador y no el suite** — la
tercera vez que pasa (14, 15, 21), y las cuatro tienen prueba ahora. La peor:
**el pedido recién enviado desaparecía de la pantalla**. Sus renglones salen de
`por_repartir`, así que el pedido sale de `particion.pedidos` —donde está bien
que no esté— y `pintarParticion` recorría solo esa lista: se borraba de la vista
el pedido con su firma y su total, justo el que el encargado acababa de crear.
Ahora se pinta la **unión** de las dos listas. Las otras tres: *"3 renglones por
atender"* seguía diciendo 3 con dos ya pedidos y sus controles encendidos para
contestar 409; con todo enviado la pantalla decía *"Todavía no hay en qué partir
esta lista · Elige a quién se le pide cada renglón"* sobre una lista ya pedida
entera; y `armado ... 02:07 a.m..` con dos puntos, que era del ticket 20.

**Y el invariante 3 de `continental.verificar` se encendió solo**, sin que nadie
tocara `verificar.py`: estaba escrito desde el ticket 17 esperando `estado` y
`enviado_por`, el 20 puso la primera y el 21 la segunda, y
`COLUMNAS_QUE_EXIGE_EL_ENVIO` nunca cambió. Deja de imprimirse como PENDIENTE en
cada despliegue.

**Y desde el ticket 22 hay pantalla de captura: el portal en una ventana, esto
en la otra, y el encargado tachando renglón por renglón.** Cada pedido en
borrador lleva un bloque plegable —*Capturar en el portal de NADRO · 3 de 5
tachados · faltan 2*— con un renglón por línea: la casilla, **la clave como
botón que la copia de un clic** (portapapeles moderno, camino viejo si no está,
y si ninguno sirve lo dice en vez de callar), la descripción, las piezas y el
precio **de ese proveedor**. Lo tachado se tacha de verdad y no se mueve de
sitio. Con el último, la pantalla **invita** a enviar, resalta el botón y le
lleva el foco; mientras falte algo dice que tachar **no es requisito** — enviar
con cero renglones tachados sigue funcionando igual que en el 21, y hay una
prueba que lo fija.

**El avance vive en `pedidos.renglon`, no en el navegador, y ésa es la decisión
del ticket** (ADR 0010): dos columnas firmadas, `capturado_por` y
`capturado_en`, pareadas por `ck_renglon_captura`, migración 0007. Con
`localStorage`, dos pestañas del mismo pedido divergirían en silencio, cambiar
de máquina a la mitad perdería el avance, y la marca que lleva a la única
acción que compromete dinero no diría quién la puso. **Tachar no es un estado
del renglón** —sigue `abierto`— porque cuatro sentencias llevan
`estado = 'abierto'` en su `WHERE` y volver a partir se saltaría uno
`capturado` en silencio. Tachar **no exige la lista abierta**, igual que enviar.

**Dos cosas del 22 que conviene no redescubrir.** (1) **La lista de captura sale
del pedido GUARDADO (`renglon.pedido_id`), nunca de la vista previa de la
partición**: la vista previa se recalcula con los precios de este instante y
puede ya haber movido un renglón a LEVIC mientras el pedido de NADRO todavía lo
tiene dentro. Lo que se captura es lo que al enviar pasa a `en tránsito`. (2)
**Volver a partir borra la marca del renglón que CAMBIA de pedido y conserva la
del que se queda** —un `case ... is distinct from` sobre el valor viejo en
`_ASIGNAR_RENGLONES`—: en el portal nuevo nadie lo ha tecleado. Y el recorrido
del navegador volvió a cazar una —cuarta vez: 14, 15, 21, 22—: con todo
tachado, el resumen seguía mandando a "buscar por nombre" el renglón sin EAN que
ya se había capturado.

**Y desde el ticket 23 cada pedido se baja en CSV para Excel**, en borrador y
en enviado, con un enlace bajo su captura. **Se arma en memoria cada vez que se
pide y no se escribe en ninguna parte** (ADR 0011): no hay copia que respaldar
ni que envejezca, y `.gitignore` gana `pedido-*.csv` para el archivo que una
persona guarde dentro del repo. El nombre lleva la fecha **de la lista** —no la
del reloj—, la clave de Doyle y el estado (`pedido-2026-09-18-nadro-enviado.csv`),
y las líneas son las de la captura del 22: el pedido guardado, con el precio
**de ese proveedor**. Sin precio es `sin precio` y el total `sin saber`, nunca
`0.00`; si el total guardado al armar ya no coincide con la suma de ahora, el
archivo escribe los dos.

**Lo que conviene no redescubrir del 23, y está medido con el Excel real de la
torre (es-MX)**: la clave va como fórmula de texto, `="7501234567890"`, porque
cruda sale `7.5012E+12` y con ceros a la izquierda pasa a **valer** otro número;
**el apóstrofo y el tabulador al frente NO sirven en un CSV** —Excel los deja
literales en la celda—. Una descripción que empieza con `-` o `=` también va
protegida: `=1+1` Excel **la evalúa**. UTF-8 con BOM, coma, punto decimal y
**sin `sep=,`**, que hace que Excel ignore el BOM. Y la defensa de Marlowe
(rechazar al leer) no aplica: allá el CSV es de entrada, éste es de salida.

**Y desde el ticket 24 la lista tiene memoria de lo ya pedido: lo que viene en
camino no se vuelve a proponer.** Hasta el 23 nada leía `en tránsito` al armar,
y el doble pedido existía **sin una sola venta nueva**: una lista que se envía y
no se cierra deja el corte donde estaba, la del día siguiente vuelve a recoger
sus días por el piso del ticket 09, y lo ya pedido a NADRO se proponía otra vez
sumado en el mismo número. Ahora `armar_la_lista` **exige** una
`transito.MemoriaDeLoPedido` —sin valor por omisión: olvidarla sería pedir dos
veces en silencio—, la pantalla y el lote la leen con `lo_ya_pedido` **dentro**
de `armar`, y si esa lectura falla la lista no se arma: un hueco con su motivo,
no una lista que pide dos veces guardada todo el día.

**La decisión del ticket es dónde queda lo que se vende mientras tanto** (ADR
0012, con cinco alternativas descartadas). **Se queda en `marts.fct_ventas`**,
donde ya estaba, y lo que se recuerda es **el ancla**: la
`ventas_consideradas_hasta` de la lista del renglón en tránsito, que existe desde
el ticket 08. Mientras viene en camino, el producto no se propone. **En cuanto
el renglón pasa a `recibido` o `recibido parcial`** —los estados de los tickets
26 y 27—, la siguiente lista lo cuenta **desde el día siguiente al ancla**,
aunque las listas de en medio se hayan cerrado y el corte haya avanzado encima.
Ninguna tabla nueva, ninguna venta copiada, y nada que envejezca cuando el
sábado llega el lunes. **El enganche para 26 y 27 es
`almacenamiento.ESTADOS_QUE_CIERRAN_EL_TRANSITO`**: quien escriba cualquiera de
los dos estados no tiene que hacer nada más para que lo retenido vuelva. Cancelar
(ticket 25) queda fuera a propósito: lo que vuelve ahí es también lo que el
renglón repuso, porque nunca llegó — y así lo resolvió el 25, con su propia
tupla y su propia cláusula (ver abajo y el ADR 0013).

**El renglón que vuelve lo dice**: `renglon.ventas_desde` (migración 0008, una
columna, **sin tabla nueva**) y la frase *"Trae también lo vendido desde el
martes 15 de septiembre, mientras venía en camino: esas ventas no se
perdieron."* Sin eso, "pide 4" en una lista de un día con una venta no se podría
verificar. **Y la pantalla enseña lo que viene en camino** de listas
anteriores, en un bloque bajo la tabla: atenuado y no escondido, con *"Pedido el
martes a NADRO, sin recibir."*, quién lo marcó y a qué hora, de qué lista salió,
cuánto se lleva vendido desde entonces, y **siempre** la advertencia de la quinta
casilla —esto solo sabe de lo que se envió desde aquí; lo capturado por fuera se
propone otra vez—. Los renglones de la lista del día que ya se enviaron se
atenúan en la tabla con la misma frase.

**Tres cosas del 24 que conviene no redescubrir.** (1) **El día de la semana
se calcula en la hora de la farmacia**, UTC-6 fijo (sin horario de verano desde
2022; la torre no tiene `tzdata`): un envío del lunes a las 20:30 son las 02:30
del martes en el contenedor. (2) **`app.py` tiene prohibido mirar el reloj**
(`test_sugerido.test_el_calculo_no_menciona_el_reloj_en_ninguna_parte`), y
"hace cuánto se envió" sí lo necesita — es un instante contra otro, no una fecha
de venta; contra `max(fecha)` los lunes saldría "enviado en el futuro". El reloj
entró a `web/dependencias.reloj`, con los otros bordes. (3) **El recorrido del
navegador cazó una, la quinta vez (14, 15, 21, 22, 24)**: la firma del envío se
armaba en el JavaScript pegándole un punto a una hora que ya terminaba en
"a.m." —*"11:00 a.m.."*, el mismo tropiezo del 21— y vivía en un `title` que en
pantalla táctil no se ve. Ahora es `transito.frase_de_la_firma`, a la vista y con
prueba.

**Y desde el ticket 25 hay válvula de escape: lo que nunca llega ya no se queda
fuera de la lista para siempre.** Dos salidas, las dos firmadas con el correo de
Access y las dos con el mismo destino (ADR 0013):

- **Cancelar un pedido** que nunca se capturó en el portal —`enviado` →
  `cancelado`—, desde el pedido enviado de hoy o desde el bloque de lo que viene
  en camino. **No es "desenviar"**: el ADR 0009 sigue en pie y lleva una nota de
  enmienda que dice exactamente qué cambió. Un cancelado no vuelve a borrador,
  no se edita, no se vuelve a enviar y no se descancela. Un pedido con algo
  recibido no se cancela.
- **Devolver a la lista un renglón atrasado**, él solo: su pedido sigue
  `enviado`. **Atrasado** es lo que lleva **más de N días** en camino, N en
  `config/continental.yml` (`pedido.dias_en_transito_para_atrasado: 7`, sin
  medir, con su porqué y su condición de revisión). **No es un estado** —se
  calcula cada vez— y no se llama "vencido", que es de la lista. El `WHERE` de
  `_DEVOLVER_EL_ATRASADO` recibe el límite como parámetro, calculado por la
  misma función con que la pantalla decide ofrecer el botón.

**En los dos casos el renglón pasa a `cancelado` —no a `abierto`— y lo que
vuelve es su producto, en la siguiente lista**, contado desde el principio de lo
que el renglón cubría: nunca se pidió, así que también vuelve lo que repuso. Lo
lleva la misma memoria del 24 (`_LO_YA_PEDIDO` trae lo cancelado que nadie ha
atendido, `LoYaPedido.retiene_desde` dice desde cuándo), con un solo intervalo
por producto y el mismo "se olvida en cuanto una lista cerrada lo trae", así que
ni se pierde ni se propone dos veces. No vuelve a `abierto` en su lista porque
casi siempre está cerrada —y solo una lista abierta se modifica—, y porque detrás
del corte sus ventas se perderían. **Lo que se renuncia:** quien cancela un
pedido de hoy lo tiene de vuelta mañana, no hoy. La pantalla enseña lo que
vuelve, con su firma y desde qué día.

**Tres cosas del 25 que conviene no redescubrir.** (1) **`at time zone '-06'` en
Postgres es la convención POSIX: se lee como UTC+6.** Por eso el límite del
atraso se calcula en Python (medianoche de la farmacia) y viaja al `WHERE`; una
prueba recorre doce días de hora en hora para que pantalla y base digan lo
mismo. (2) **Un tercer estado del pedido rompe `!fue_enviado`**, que la pantalla
usaba como "borrador" para pintar la captura: ahora es `es_borrador`, y
`motivo_para_no_enviar` mira `fue_cancelado` antes del conteo —si no, un
cancelado "se podía enviar"—. (3) **Hasta el ticket 26, lo que llegó también se
veía atrasado**: nada lo pasaba a `recibido`, y devolverlo era pedirlo dos veces.
*Desde el 26 eso vale solo para lo que llega sin dejar compra en SICAR* (ver
abajo); la advertencia sigue junto al botón, con ese alcance. Y el recorrido del navegador cazó dos, **la
sexta vez** (14, 15, 21, 22, 24, 25): con todo cancelado la partición mandaba a
"elegir a quién se le pide" renglones que ya no se reparten, y lo que vuelve no
tenía encabezado.

**La 0009 va ANTES de desplegar**: `_LEER_RENGLONES`, `_LEER_PEDIDOS` y
`_LO_YA_PEDIDO` nombran las columnas nuevas. No crea tabla: `crear_rol.sql` no
se vuelve a correr.

**Y desde el ticket 26 lo que llegó se puede recibir — pero nunca solo.** Cuando
una compra de SICAR encaja con un renglón en tránsito —**mismo proveedor (su
`pro_id`), mismo producto, y del mismo día del envío o después, en días de la
farmacia; nunca por folio**—, la pantalla lo propone como **probablemente
recibido**, con su evidencia a la vista: a quién, qué día, cuántas piezas,
cuántos días después del envío y el folio (*"se enseña para buscarlo en la
factura; no se usó para emparejar"*). Una persona **confirma** —el renglón pasa
a `recibido`, firmado con el correo de Access y con los `compra_id` que juzgó—
o **rechaza** —sigue en tránsito, y esa compra ya no se le vuelve a proponer;
una distinta, sí—. Con confirmar basta para que **lo retenido del ticket 24
vuelva solo**: `recibido` está en `ESTADOS_QUE_CIERRAN_EL_TRANSITO` y nadie tuvo
que tocar `transito.py`. Es la primera vez que algún código escribe `recibido`.

**La decisión del ticket es que la propuesta NO se guarda** (ADR 0014, con las
alternativas descartadas). `recepcion.proponer` es pura y se recalcula en cada
carga: si la compra desaparece del almacén —se canceló en SICAR, o la cadena no
corrió—, la propuesta desaparece con ella en vez de quedar escrita afirmando
algo sin evidencia. Un estado guardado además habría sacado el renglón de
`en tránsito` y su producto **se habría vuelto a proponer** antes de que nadie
confirmara nada. Lo que sí se guarda son las dos decisiones de una persona, en
seis columnas de `pedidos.renglon` (migración **0010**, sin tabla nueva):
`recibido_por`, `recibido_en`, `recibido_con_compras`, `compras_rechazadas`,
`recepcion_rechazada_por` y `recepcion_rechazada_en`. **El rechazo guarda QUÉ
compra, no una fecha tope**: una compra del viernes capturada a las 19:30 llega
al almacén hasta el lunes, y una fecha tope se la habría tragado.

**Las otras cuatro decisiones, en una línea cada una.** (1) **Cantidades**: se
enseñan siempre; solo se confirma si la evidencia trae al menos lo pedido
—`recibido` es "llegó completo"— y la condición está en la función pura **y** en
el `WHERE` (`:piezas`, el patrón del límite del 25). Con menos, se dice que es
un recibido parcial, que es el ticket 27, y no se ofrece el clic. Dos facturas
del mismo producto se suman. (2) **Una compra que encaja con dos renglones** se
propone en los dos, cada uno lo dice, y el `WHERE` impide que confirme dos
(`&&` contra `recibido_con_compras`). (3) **Sin puente** (QuePharma): nunca
habrá propuesta, y se dice primero. (4) **La fecha**: día de la farmacia,
calculado en Python; el mismo día del envío cuenta.

**Lo que nunca va a tener propuesta se dice arriba de lo que solo espera**: un
pedido a QuePharma, y un producto que nunca ha aparecido en una compra de SICAR
(606 de 3,429, 17.7%) —una lectura nueva del almacén, `productos_con_compras`,
sobre la misma `fct_compras` que el rol ya lee—. Su única salida es el recibido
a mano —que desde el ticket 27 existe—, y **la pantalla decía que todavía no existía** en vez de pintar un botón
que no hay. **Una noche de retraso se dice normal, no un error**, siempre, en
el mismo bloque.

**Lo que cambió de rebote.** Un renglón atrasado **con propuesta** ya no ofrece
devolverlo (*"Probablemente ya llegó… confírmala o recházala antes de pensar en
devolverlo"*); si se rechaza, el botón vuelve. Un pedido con algo recibido ya no
ofrece cancelar, en la partición de hoy y en el bloque de listas anteriores —el
`NOT EXISTS` que el 25 dejó puesto se ejercita por fin—. La lista de hoy también
entra a la recepción: lo que se pidió a las 9 puede llegar a las 15.

**Tres cosas del 26 que conviene no redescubrir.** (1) **`ck_renglon_recepcion`
exige firma también para `recibido parcial`**, y `recibido_con_compras` admite
`NULL` en lo recibido: es la puerta del 27 (marcado a mano, sin compra). Cinco
pruebas viejas que ponían `recibido` a pelo en el doble tuvieron que firmar.
(2) **`_LO_YA_PEDIDO` mira solo listas anteriores y la recepción no puede**: hay
una sentencia hermana, `_EN_TRANSITO`, sin fecha de lista y con el `pro_id` del
pedido. (3) **El recorrido del navegador cazó cuatro, la séptima vez** (14, 15,
21, 22, 24, 25, 26), y las cuatro tienen prueba: *"Trae las 1 pieza que se
pidieron"*; *"siguen en camino"* debajo de un solo renglón; el motivo de no
confirmar repetido debajo de la frase de la cantidad; y un renglón recibido que
seguía contando *"por atender"*. **Y dejó ver uno que no es del 26**: con un
pedido enviado y otro renglón todavía sin proveedor, la partición dice *"Esta
lista ya se pidió entera · No queda nada por repartir"* —el texto de reserva del
JavaScript, del ticket 21—. Queda anotado abajo, sin tocar.

**La 0010 va ANTES de desplegar**: `_LEER_RENGLONES`, `_LEER_RENGLON_POR_ID`,
`_LO_YA_PEDIDO` y `_EN_TRANSITO` nombran las columnas nuevas. No crea tabla y no
pide ningún permiso nuevo sobre `marts`: **`crear_rol.sql` no se vuelve a
correr.**

**Y desde el ticket 27 lo que llega de menos tiene salida, y lo que faltó
vuelve solo.** Tres salidas nuevas, las tres de una persona y firmadas con el
correo de Access (ADR 0015):

- **Recibir a mano** —`POST /api/renglon/{id}/recepcion/a-mano {"piezas": N}`—:
  cuántas llegaron **en total**, sin propuesta del sistema. Cada renglón en
  camino tiene su campo en el bloque de la recepción, con propuesta o sin
  ella. Es la única salida de QuePharma y del 17.7% del catálogo que nunca
  aparece en compras, y la del pedido que llega en dos facturas. **La misma
  pregunta corrige la cifra** de lo ya recibido —la segunda factura (6 → 10) o
  un error de captura— mientras lo que faltó no lo haya atendido una lista
  posterior (cerrada con el producto, o el producto vuelto a pedir).
- **Recibir parcial con la evidencia** —`POST .../recepcion/parcial`—: la
  propuesta del 26 que trae de menos (3 de 5) ya no se queda sin salida:
  *"Llegaron solo 3 de 5: recibir parcial"*, con las garantías de confirmar y
  la cantidad al revés.
- **El estado sale de las piezas**: `recibido` si llegaron al menos las
  pedidas, `recibido parcial` si menos. `renglon.piezas_recibidas` lo guarda y
  `ck_renglon_completo_o_parcial` lo amarra en la tabla. Las piezas se validan
  en el servidor (`recepcion.piezas_escritas`): entero, de 1 en adelante; cero
  no es recibir, y **más de lo pedido se acepta** como `recibido` sin
  descontar nada de ninguna lista.

**La decisión del ticket es cómo vuelve "la diferencia", y vuelve como PIEZAS.**
Pedí 10, llegaron 6: las 4 son ventas de la ventana *original* que no se
repusieron, y no hay manera de saber de qué días; volver a leerlas por fecha
propondría también las 6 que llegaron. Así que `LoYaPedido.piezas_que_vuelven`
→ `MemoriaDeLoPedido.faltaron` (un tercer mapa, de piezas) →
`calcular_pedido_sugerido(faltaron=)` las **suma** a lo vendido, y el renglón
nuevo guarda cuántas trae en `renglon.piezas_que_faltaron` y lo dice: *"Trae
también 4 piezas que faltaron en un pedido anterior"*. Lo vendido mientras venía
sigue volviendo por el ancla del 24: son dos conjuntos de ventas que no se
tocan. Los números: lunes 10, martes 3, miércoles 2, jueves llegan 6 y se vende
1 → la del jueves propone 3 + 2 + 1 + 4 = **10**; la del viernes, **1**. Un
cancelado que traía lo que faltó lo devuelve también ("con todo lo que
cubría").

**El estado del PEDIDO se calcula, no se guarda.** `recepcion.estado_del_pedido`:
`recibido` si no le queda nada en camino y todos llegaron completos, `recibido
parcial` si alguno llegó de menos o se dejó de esperar. Viaja como
`estado_a_la_vista` con su frase; en la tabla sigue `enviado`, que es verdad. Un
cuarto estado guardado habría roto los cuatro `WHERE` que exigen `p.estado =
'enviado'` —el 25 ya midió que un tercero rompió `!fue_enviado`—. Cancelar un
pedido con algo recibido parcial sigue prohibido, sin cambiar una línea.

**Tres cosas del 27 que conviene no redescubrir.** (1) **`git stash` en esta
torre convierte a CRLF los archivos modificados** (`core.autocrlf=true`; el
`.gitattributes` solo fija LF para `.sh`, `.service`, `.timer` y `.sql`), y
después ningún reemplazo exacto encuentra su texto. No se use para medir. (2)
**Una llave de JSON con la palabra "parcial" tumba la prueba del 26** que impide
componer frases en `pintarRecepcion`: por eso son `se_puede_recibir_lo_que_trae`
y `etiqueta_de_lo_que_trae`. (3) **El recorrido del navegador cazó tres, la
octava vez** (14, 15, 21, 22, 24, 25, 26, 27): lo que llegó de menos decía
"vuelve en la siguiente lista" debajo de una lista que ya lo traía; la segunda
factura corregida después de armar la lista de hoy dejaba ese renglón pidiendo
lo que ya llegó sin decirlo (ahora lo avisa en ámbar, como "ya viene en camino"
del 24); y **el hilo abierto 18 se disparó** —con lo recibido, la reserva decía
"sus renglones están en tránsito" sobre lo que ya llegó—: la frase del caso
mixto sale ahora de Python y el título dice "se pidió en parte".

**La 0011 va ANTES de desplegar**: `_LEER_RENGLONES`, `_LEER_RENGLON_POR_ID`,
`_LO_YA_PEDIDO` y `_EN_TRANSITO` nombran `piezas_recibidas` y
`piezas_que_faltaron`, y `_INSERTAR_RENGLONES` escribe la segunda: sin ella, ni
la pantalla ni el lote arman la lista. Rellena lo confirmado por el 26 con lo
pedido antes de poner sus CHECK. No crea tabla ni toca `pedidos.pedido`:
**`crear_rol.sql` no se vuelve a correr.** `verificar_rol.sql` gana la 36 y la
37.

**Y desde el ticket 28 la pantalla se lee: una hoja de estilos propia, claro y
oscuro, 40 renglones sin cansarse y el teléfono sin desplazar hacia los lados.**
`index.html` son ahora **tres archivos** en `src/continental/web/static/`
—`index.html` (el marcado), `continental.css` y `continental.js`—, servidos tal
cual, sin compilar nada y sin nada de fuera. **Ningún color se escribe fuera de
las dos listas de `:root`** de la hoja, y el oscuro redefine las once. A 1366 px
la tabla de 47 renglones del recorrido pasó de 19,306 px de alto a 8,962 (de
409 a 189 px por renglón): cada proveedor es una línea, con su marca, su
diferencia o el motivo de su hueco en una cuarta columna y no colgando debajo.
La tabla se apila por debajo de **76rem** y no de 34: a 768 px la de antes
desplazaba la página 190 px. Lo que se distinguía solo por color lleva además
una forma —barra continua lo agotado, punteada lo que está en tránsito, doble
lo atrasado; recuadro el ahorro, punteado lo que cuesta de más; un signo en
cada marca (`?` sin clasificar, `!` hay que mirar, `✓` punteado probablemente
recibido)—. **El comportamiento no cambió**: el JavaScript es el del 27 salvo
clases CSS y un `append` (ver el ticket).

**Dos cosas del 28 que conviene no redescubrir.** (1) **Ninguna prueba lee
`index.html` a secas**: todas piden `conftest.pantalla_completa()` o
`pantalla_servida(cliente)`, que arman la pantalla como era antes —la hoja y el
script dentro, en su sitio—. Una guardia de "el JavaScript NO compone esta
frase" que leyera solo el HTML pasaría por vacío; `test_pasada_visual` lo
vigila, y el ayudante exige exactamente una hoja y un script. (2) **`/` y
`/static/*` salen con `Cache-Control: no-cache`** (`EstaticosQueSeRevalidan`
en `web/app.py`): sin eso un despliegue podía dejar al mostrador con el HTML
nuevo y el JavaScript de ayer. El navegador revalida y Starlette contesta 304.

**Y desde el ticket 29 la pantalla dice qué pasó cuando algo falla, y qué
hacer.** El servidor ya fallaba ruidoso desde el primer commit; lo que faltaba
era la pantalla, y el inventario del ticket (25 rutas y 17 `fetch`, en su
archivo) encontró que el servidor estaba bien en lo esencial y la pantalla no:
**un 500 se leía como "el almacén no tiene ni una venta registrada"**, dos
botones se quedaban apagados para siempre con el HTML de un 502 del túnel, y
los precios o los pedidos que no se leían se pintaban en silencio como "sin
consultar" y "sin partir". Ahora:

- **Doyle caído se dice arriba de la tabla**, no abajo en "Módulos": `GET
  /api/doyle`, aparte de la lista y al mismo tiempo, porque la lista no
  depende de Doyle y un Doyle colgado no la puede hacer esperar.
- **Cada falla dice qué hacer**, o que desde ahí no hay nada que hacer y a
  quién avisarle: `fallas.que_hacer`, seis casos. **El contacto es
  `a_quien_avisar` en `config/continental.yml`** ("a quien administra
  atlas"): el JavaScript decía "Avísale a Eddie".
- **"No hubo ventas" lo afirma el servidor**, distinto de "no pude leer":
  `ventas` en cada carga dice qué tan recientes son las ventas que sí leyó
  contra el horario de la cadena. Un lunes por la mañana la lista del viernes
  dice que es lo más reciente que puede haber y que los domingos la farmacia
  cierra; si falta un día que ya debía estar, dice que **no sabe por qué** —cero
  filas no es "cerraron"— y a quién avisarle si la farmacia sí abrió.
- **Ningún detalle viaja al navegador, y no se prueba ruta por ruta**: el
  recorrido de `tests/test_fallas.py` toma `app.routes` e inyecta la falla en
  cada llamada a cada borde (26 rutas, 71 fallas). La ruta de mañana entra
  sola.
- **En el JavaScript todo pasa por `respuestaDe`**, que no truena, y las
  únicas frases de falla que escribe viven en `SIN_RESPUESTA`. Ninguna acción
  afirma ya "se quedó como estaba" sin respuesta: la petición pudo llegar.

**Dos cosas del 29 que conviene no redescubrir.** (1) **Sin los precios
leídos no se calcula nada de lo que sale de ellos**: con `{}` el conteo decía
"5 de 5 sin comparar" y ofrecía completarlos —cuatro visitas a portales por
renglón, por precios que sí existen—. Lo cazó el recorrido del navegador (la
novena vez), no el suite. (2) **El reloj entra para una sola pregunta**: si lo
más reciente del almacén es lo más reciente que puede haber. La lista se sigue
anclando en `max(fecha)`.

**Con el 29, el módulo de Pedido está completo en código: sus 29 tickets.**
**No está terminado**: terminado es lo de "Lo que falta, en orden" —un día de
operación real con la lista armada sola de noche, los precios de los cuatro,
el pedido capturado leyendo de la pantalla y la recepción propuesta al día
siguiente—, y eso no ha pasado. Continental ni siquiera está desplegado en
atlas todavía (`docs/despliegue-en-atlas.md`).

**Y desde el ADR 0016 cerrar avisa lo que se pierde, y el cierre se puede
deshacer.** Lo pidió el dueño después de una revisión de código de los tickets
24 y 27: `_LO_YA_PEDIDO` da por atendido un producto en cuanto una lista
posterior **cerrada** lo trae, aunque ahí siguiera `abierto` o `descartado`; si
se cerró sin pedirlo, **lo que faltó de un parcial y lo vendido mientras un
pedido viajaba se perdían sin que nada avisara**. No es un error de la
sentencia —es lo que cerrar quiere decir desde el ticket 09—, así que se
resolvió en la pantalla y con un deshacer:

- **Antes de cerrar, un `<dialog>` propio** (nada de `window.confirm()`: con
  `showModal()` atrapa el foco, Esc lo cierra sin cerrar la lista, el foco va a
  "Volver" cuando algo se perdería). Dice cuántos renglones quedan sin pedir,
  cuántos están en un borrador sin enviar, y **en un recuadro ámbar con rótulo
  "Ojo:" y un `!` por renglón** los que traen algo de otro pedido, con sus
  piezas: *"PARACETAMOL 500 MG: 10 piezas sin pedir. Trae 4 piezas que
  faltaron en un pedido anterior y lo vendido desde el martes 15 de septiembre
  mientras venía en camino: si se cierra así, ninguna lista vuelve a
  traerlas."* El botón pasa a "Cerrar de todos modos": **avisa, no prohíbe**.
  Todo sale de `cierre.al_cerrar` (Python, probado) por `GET
  /api/pedido-sugerido/{id}/al-cerrar`, leído **al apretar** y no en la carga
  —descartar cambia un renglón sin reenviar la lista—. Si no se puede leer, se
  dice con su qué hacer y se puede cerrar igual.
- **Reabrir**: `cerrado → abierto`, firmado (`reabierto_por`, `reabierto_en`),
  por `POST /api/pedido-sugerido/{id}/reabrir`. **Solo la última lista del
  negocio, mientras ninguna se haya armado después** —la regla es una cadena,
  `_NINGUNA_LISTA_DESPUES`, que usan el `WHERE` de `_REABRIR` y la lectura
  `_SE_PUEDE_REABRIR` con la que se decide si se pinta el botón—. En cuanto el
  lote o la pantalla arman la siguiente, ésta empezó donde la cerrada terminó y
  reabrir contesta 409 con su porqué; el botón se esconde. `vencido` no se
  reabre. **Reabrir no deshace lo enviado ni lo recibido.** El glosario gana
  la transición y la palabra **cerrar** con lo que implica.

**La 0012 va ANTES de desplegar, y hay que correrla en atlas**:
`_LEER_LISTA`, `_LEER_LISTA_POR_ID`, `_INSERTAR_LISTA` y `_CERRAR` devuelven
las dos columnas nuevas. **No rompe el código que hoy corre allá**: las dos
admiten nulos y no tienen DEFAULT, ningún `INSERT` viejo las nombra, y el CHECK
pareado no mira el estado — se puede correr primero sin que el servicio lo
note. No crea tabla: **`crear_rol.sql` no se vuelve a correr**.
`verificar_rol.sql` gana la 38.

**Tres cosas del 0016 que conviene no redescubrir.** (1) **La regla es
"ninguna lista después", no "la de hoy"**: lo que hace segura la reapertura es
que nadie haya leído el corte, y quien lo lee es quien arma una lista. El borde
—la cadena ya trajo el viernes y nadie abrió el día— deja reabrir, y la
siguiente carga la vence como a cualquier lista que nadie cerró: el escenario
con números (3 + 2 + 1 + 1 + 4 = 11 = 10 del jueves + 1 del viernes) está en
`test_cierre.py`. (2) **Queda una carrera de milisegundos**, dicha en el ADR:
el `not exists` no ve una lista posterior que se está insertando sin
confirmar. Se midió qué deja —nada se propone dos veces; lo sin pedir se pierde
igual que sin reabrir— y no se pagó un candado compartido con `abrir_el_dia`.
(3) **El recorrido del navegador no cazó nada esta vez** (`recorrer.py` con
Playwright del venv de Doyle, en el scratchpad): el diálogo centrado a 1280, a
375 sin desplazar (`scrollWidth == innerWidth`), en oscuro; Esc deja la lista
abierta; Tab + Enter cierra; la pestaña vieja que reabre después de armarse la
siguiente recibe el 409 y el botón desaparece.

**Lo sugerido NO se guarda y lo decidido SÍ, y ésa es la decisión del ticket.**
Es la misma pregunta que el 11 resolvió con `cantidad_propuesta` /
`cantidad_final`, y **aquí la respuesta es distinta a propósito**: la sugerencia
se recalcula de `comparacion.elegir_ganador`, que es pura sobre una tabla de
precios que solo crece (ADR 0004), mientras que `cantidad_propuesta` **no se
puede recalcular** —sale de las ventas de una ventana que ya pasó—. Una
sugerencia guardada además envejece sin avisar: si a las 8 era NADRO y a las 9
llega un LEVIC más barato, la columna seguiría diciendo NADRO y nadie podría
distinguir esa cifra vieja de una decisión que alguien tomó. Así que
`renglon.proveedor_elegido IS NULL` quiere decir exactamente *nadie eligió*, con
su firma pareada (`elegido_por`, `elegido_en`) por `ck_renglon_eleccion`.

**El puente entre las claves de Doyle y `proveedor_id` de SICAR no existía en
ninguna parte, y el ADR 0008 lo resuelve.** La comparación entera habla en
`nadro`/`levic`/`vicma`/`quepharma`; `pedidos.pedido` hablaba en `pro_id`. Ahora
**la identidad del pedido es la clave de Doyle** (`pedido.proveedor`, `NOT
NULL`) y `proveedor_id` es una **correspondencia que puede faltar**: admite
nulos. Y no es un caso hipotético — **QuePharma no está en
`marts.dim_proveedor`** (22 filas, leídas en atlas el 2026-09-19: NADRO es el 1,
VICMA el 8, LEVIC el 10) porque la farmacia nunca le ha comprado. Se le puede
pedir igual, con `proveedor_id` en `NULL` y la pantalla diciéndolo. El mapa vive
en `config/continental.yml` (`pedido.proveedores_en_sicar`) y **guarda el id y
no el nombre**: el `pro_id` no cambia cuando SICAR renombra.

**Tres cosas del 20 que conviene no redescubrir.** (1) `ux_pedido_proveedor`
**tuvo que moverse** de `proveedor_id` a `proveedor`: con la columna admitiendo
nulos, un UNIQUE sobre ella deja de impedir nada —en Postgres dos nulos no son
iguales— y dos pedidos a QuePharma entrarían los dos. (2) **Un renglón dentro de
un pedido en borrador sigue `abierto`**, no pasa a `en tránsito`: el glosario
define ese estado como "ya se le pidió a un proveedor" y un borrador no se le ha
pedido a nadie; lo pone el ticket 21 al enviar. (3) **El total de un pedido es
`NULL` en cuanto una línea va sin precio**, jamás la suma de las demás: un total
parcial se compara contra la factura del proveedor, no cuadra, y nadie sabe si
falta mercancía o falta un precio. El parcial viaja aparte con su conteo.

```bash
python iniciar.py     # http://127.0.0.1:8585
python -m continental.verificar   # los datos de producción, no el código (ticket 17)
python -m continental.lote        # el lote nocturno, a mano (ticket 18)
python -m continental.lote --tope-minutos 5   # ...con tope corto, para mirarlo
python -m continental.verificar --forma   # solo la forma de la base (ADR 0017)
pytest                # 1691 pruebas, 0 saltadas, 14.8-19.7 s (2026-09-21, ADR 0017,
                      # medido con otra sesión corriendo en la torre)
                      # Las 44 nuevas: 41 de `test_forma.py` (el parseo de
                      # crear_tablas.sql y de las migraciones, revisar_forma,
                      # `--forma`, el lote que no corre, y la prueba G sobre
                      # las sentencias de almacenamiento.py), 2 de
                      # `test_despliegue.py` (la forma antes del reinicio;
                      # los datos siguen al final) y 1 que `test_compila.py`
                      # gana por `forma.py`. Viejas tocadas: los rótulos N/6
                      # a N/7; el invariante 3 sin `enviado_por` pasa de
                      # PENDIENTE a FALLA (test_verificar, test_pedidos); y
                      # `migraciones` en src/ se permite sólo en forma.py,
                      # que la lee como texto (test_ajuste, test_descarte).
                      #
                      # 1647 pruebas, 0 saltadas, 6.69-7.27 s (2026-09-21, ADR 0016)
                      # 1566 antes (el 29 más el commit del CSV de lo que
                      # llegó). Las 81 nuevas son 75 de `test_cierre.py` (lo
                      # puro: qué se perdería y sus frases, la reapertura;
                      # lo que se guarda: el doble, los CHECK, el SQL como
                      # texto, la 0012 y que no rompe lo de atlas; lo que se
                      # ve: tres escenarios de varios días con sus números,
                      # los 409, la regla 5 y la pantalla), 4 que el recorrido
                      # de `app.routes` de `test_fallas.py` gana solo por las
                      # dos rutas nuevas, y 2 que `test_compila.py` gana por
                      # `cierre.py` y la 0012. Se ajustaron los tres censos de
                      # `fetch('/api/` (16 a 18, por `/al-cerrar` y
                      # `/reabrir`), con su párrafo; ninguna otra prueba vieja
                      # se tocó. Las 75 solas, 0.39 s.
                      #
                      # 1558 pruebas, 0 saltadas, 6.48-8.04 s (2026-09-21, ticket 29)
                      # 1442 en el 28. Las 116 nuevas son 115 de
                      # `test_fallas.py` (el qué hacer, el estado de las
                      # ventas contra el horario de la cadena, los huecos de la
                      # carga, Doyle aparte, el recorrido de `app.routes` —26
                      # rutas, 71 fallas inyectadas— y del manejador global,
                      # el 422, la guardia sobre el código y la pantalla) y 1
                      # que `test_compila.py` gana sola por `fallas.py`.
                      # Se ajustaron los tres censos de `fetch('/api/` (15 a
                      # 16, por `/api/doyle`), con su párrafo. Medido: sin
                      # `test_fallas.py`, 5.37 s ese mismo rato; las 115 solas,
                      # 1.36 s. NINGUNA TOCA POSTGRES, NI DOYLE, NI DUERME.
                      #
                      # 1442 pruebas, 0 saltadas, 5.20-5.26 s (2026-09-21, ticket 28)
                      # 1395 en el 27. Las 47 nuevas son todas de
                      # `test_pasada_visual.py` (los tres archivos y nada de
                      # fuera, los colores solo en `:root`, el oscuro completo,
                      # el fondo explícito, las cifras a la derecha, 16
                      # distinciones que no dependen solo del color, el apilado
                      # bajo 76rem, `no-cache` y el 304, y que ninguna prueba lea
                      # `index.html` a secas). Veinte archivos de pruebas que
                      # leían la pantalla pasaron a `conftest.pantalla_completa`
                      # / `pantalla_servida` SIN tocar una sola afirmación.
                      # NINGUNA TOCA POSTGRES ni abre un navegador.
                      #
                      # 1395 pruebas, 0 saltadas, 4.87-5.10 s (2026-09-21, ticket 27)
                      # 1285 en el 26. Las 110 nuevas son 109 de `test_parcial.py`
                      # (lo puro: cuánto faltó, cómo vuelve —por piezas, aparte
                      # de lo vendido—, las piezas escritas, el estado del pedido
                      # calculado y las frases; lo que se guarda: recibir a mano,
                      # corregir, recibir parcial con compras, el candado de lo
                      # ya atendido, los tres CHECK en Python, el SQL como texto,
                      # la 0011 y `verificar_rol.sql`; lo que se ve: cinco
                      # escenarios de varios días con los números escritos, el
                      # estado del pedido en la partición, las reglas 3 y 5, el
                      # 422 en español y la pantalla) y 1 que `test_compila.py`
                      # gana sola por la migración 0011. Se ajustaron: las que
                      # ponían `recibido` a pelo en el doble ahora dicen cuántas
                      # llegaron (`test_ajuste`, `test_descarte`, `test_cancelar`,
                      # `test_transito`, y la del CHECK del marcado manual en
                      # `test_recepcion`), las dos del 26 que esperaban "todavía
                      # no se puede" ahora esperan la salida a mano, y los tres
                      # censos de `fetch('/api/` de 14 a 15. Medido: sin
                      # `test_parcial.py`, 4.55 s ese mismo rato; las 109 solas,
                      # 0.49 s. NINGUNA TOCA POSTGRES ni duerme.
                      #
                      # 1285 pruebas, 0 saltadas, 5.33-6.53 s (2026-09-21, ticket 26)
                      # 1191 en el 25. Las 94 nuevas son 92 de `test_recepcion.py`
                      # (lo puro: qué encaja y qué no, nunca el folio, el día de
                      # la farmacia, las cantidades, la compra compartida, los
                      # seis motivos y las frases; lo que se guarda: confirmar y
                      # rechazar en el doble, los CHECK en Python, el SQL como
                      # texto, la 0010 y `verificar_rol.sql`; lo que se ve: las
                      # dos rutas en una semana de punta a punta, el 409 de la
                      # propuesta que cambió, las reglas 3, 4 y 5, y la pantalla)
                      # y 2 que `test_compila.py` gana sola por el módulo nuevo y
                      # la migración 0010. Nueve pruebas viejas se ajustaron:
                      # cinco que ponían `recibido` sin firma y ahora firman, tres
                      # censos de `fetch('/api/` de 13 a 14, y la advertencia del
                      # 25. NINGUNA TOCA POSTGRES ni duerme.
                      #
                      # 1191 pruebas, 0 saltadas, 4.92-6.05 s (2026-09-21, ticket 25)
                      # 1095 en el 24. Las 96 nuevas son 95 de `test_cancelar.py`
                      # (lo puro: días en tránsito, el umbral, el límite del
                      # WHERE contra los días hora por hora, la memoria con lo
                      # cancelado y las frases; lo que se guarda: cancelar y
                      # devolver en el doble, los CHECK en Python, el SQL como
                      # texto y el YAML; lo que se ve: las dos rutas en
                      # escenarios de varios días, el lote y la pantalla) y 1 que
                      # `test_compila.py` gana sola por la migración 0009. Siete
                      # pruebas viejas se ajustaron porque los estados crecieron
                      # (`ESTADOS_DEL_PEDIDO`, `ESTADOS_DEL_RENGLON`, la 0006 ya
                      # no es la última palabra del CHECK) y porque la pantalla
                      # tiene dos `fetch` más. NINGUNA TOCA POSTGRES ni duerme.
                      #
                      # 1095 pruebas, 0 saltadas, 5.40-5.49 s (2026-09-21, ticket 24)
                      # 1011 en el 23. Las 84 nuevas son 82 de `test_transito.py`
                      # (lo puro: qué se queda fuera, desde cuándo vuelve, cuánto
                      # se vendió y las frases, con el `ahora` por argumento; lo
                      # que se guarda: `lo_ya_pedido` en el doble, la columna
                      # `ventas_desde` y el SQL como texto; lo que se ve: la ruta,
                      # el lote y la pantalla) y 2 que `test_compila.py` gana sola
                      # por el módulo nuevo y la migración 0008.
                      # Medido: sin `test_transito.py`, 4.30 s ese mismo rato; las
                      # 82 solas, 0.40 s. NINGUNA TOCA POSTGRES y ninguna duerme.
                      # Ojo: `test_despliegue.test_como_servicio_no_se_abre_...`
                      # se pone ROJA si hay algo escuchando en el 8585 — un
                      # servidor de recorrido olvidado, por ejemplo. No es una
                      # regresión: es la prueba de que `--servicio` no busca
                      # otro puerto, haciendo su trabajo.
                      #
                      # 1011 pruebas, 0 saltadas, 4.17-5.48 s (2026-09-21, ticket 23)
                      # 953 en el 22. Las 58 nuevas son 57 de `test_exportar.py`
                      # (lo puro: las filas, los bytes, el nombre y el
                      # Content-Disposition; lo que se ve: la ruta, el 404, el
                      # 409 y el 503; lo que NO se guarda: ni un archivo en el
                      # árbol, y el patrón de `.gitignore`) y 1 que
                      # `test_compila.py` gana sola por el módulo nuevo.
                      # Medido en dos corridas: sin `test_exportar.py`, 954 en
                      # 3.91-5.06 s ese mismo rato; las 57 solas, 0.58-0.62 s.
                      # NINGUNA TOCA POSTGRES, ninguna duerme, y la única que
                      # escribe un archivo lo hace en `tmp_path`.
                      #
                      # 953 pruebas, 0 saltadas, 4.05-5.26 s (2026-09-21, ticket 22)
                      # 886 en el 21. Las 67 nuevas son 66 de `test_captura.py`
                      # (lo puro: qué entra en la captura, cuántos faltan y las
                      # dos frases de la quinta casilla; lo que se guarda: la
                      # firma en el doble y el SQL como texto; lo que se ve: la
                      # ruta, la recarga y la pantalla) y 1 que `test_compila.py`
                      # gana sola por la migración 0007. Tres pruebas viejas
                      # cambiaron su censo de `fetch('/api/` de 10 a 11.
                      # Medido: con `test_captura.py` fuera, 4.22 s ese mismo
                      # rato; las 66 solas, 0.56 s. NINGUNA TOCA POSTGRES y
                      # ninguna duerme.
                      #
                      # 886 pruebas, 0 saltadas, 3.31-4.81 s (2026-09-21, ticket 21)
                      # 845 AL EMPEZAR EL 21, y no las 824 que este bloque
                      # anoto el dia del 20: entre medias entraron las de los
                      # pendientes 2, 6, 7 y 8, que son despliegue y lote y no
                      # tocaron el modulo. Las 41 nuevas son 40 de `test_envio.py`
                      # (lo puro: la frase del envio y cuando se niega el boton;
                      # lo que se guarda: los dos UPDATE en una transaccion; lo
                      # que se ve: la ruta, la pantalla y los .sql) y 1 que
                      # `test_compila.py` gana sola, porque sus parametrizadas
                      # recorren los .sql y hay una migracion mas.
                      # Medido en dos corridas: con `test_envio.py` fuera el
                      # arbol del 20 costo 4.13-5.31 s ese mismo rato, y las 40
                      # nuevas corriendo solas, 0.39-0.54 s. El +1.2 s contra el
                      # ticket 20 es la torre y no las pruebas, otra vez.
                      # NINGUNA TOCA POSTGRES y ninguna duerme.
                      #
                      # CUATRO DE LAS 40 SALIERON DEL NAVEGADOR Y NO DE ESCRIBIR
                      # PRUEBAS, y una de ellas era el peor error del ticket: el
                      # pedido recien enviado desaparecia de la pantalla. Es la
                      # tercera vez (14, 15, 21). Abrir la pantalla y apretar el
                      # boton sigue siendo obligatorio.
                      #
                      # 824 pruebas, 0 saltadas, 2.85-3.11 s (2026-09-19, ticket 20)
                      # 749 en el 19. Las 76 nuevas son 35 de
                      # `test_particion.py` (lo puro: elegir, partir,
                      # totalizar, y el puente con SICAR), 38 de
                      # `test_pedidos.py` (lo que se guarda, lo que se ve y lo
                      # que dicen los .sql) y 3 que `test_compila.py` gana sola
                      # —sus parametrizadas recorren los .py y los .sql, y hay
                      # dos modulos y una migracion mas—. NINGUNA TOCA POSTGRES
                      # y ninguna duerme.
                      #
                      # 749 pruebas, 0 saltadas, 3.55-4.46 s (2026-09-19, ticket 19)
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
| `docs/decisiones/0009` | **"enviar" no es enviar**: `enviado` es la firma de que una persona ya capturó el pedido en el portal, no un envío de Continental. Por qué firma y no acuse, por qué no se puede enviar un pedido vacío y sí uno sin total, por qué enviar NO exige la lista abierta, y por qué no hay "desenviar" |
| `docs/decisiones/0010` | **el avance de la captura vive en la tabla del renglón**, no en el navegador: dos columnas firmadas y no `localStorage`, ni una tabla nueva, ni un estado `capturado`. Por qué se puede destachar y enviar no se deshace, y por qué tachar todo lleva a enviar sin ser requisito |
| `docs/decisiones/0012` | **lo vendido mientras un renglón está en tránsito se queda en el almacén y vuelve al recibirse**: el ancla es la ventana de la lista del renglón, no una tabla de ventas retenidas; por qué no congelar el corte, ni restar lo que viene en camino, ni filtrar y olvidar. El enganche para los tickets 25, 26 y 27 |
| `docs/decisiones/0011` | **el CSV del pedido se arma en memoria cada vez** y se escribe para el Excel de México: la clave como fórmula de texto (medido contra el tabulador y el apóstrofo, que quedan literales), BOM, coma y sin `sep=`, y la ruta colgada de la lista para no escribir SQL nuevo |
| `docs/decisiones/0008` | **el puente que no existía**: el pedido se identifica por la clave de Doyle y el `proveedor_id` de SICAR es una correspondencia que puede faltar. Por qué el mapa va en el YAML y guarda el id y no el nombre, y por qué el UNIQUE tuvo que moverse |
| `sql/` | el DDL de las **cinco** tablas, el rol acotado y `verificar_rol.sql`, que mira la **forma** de la base. **Se corren a mano, en ese orden, con credenciales de dueño** — no confundirlo con `continental.verificar`, que mira los **datos** en cada despliegue (la cabecera de ese módulo tiene la tabla que los separa) |
| `docs/decisiones/0013` | **cancelar suelta el tránsito sin desenviarlo**, y lo que vuelve es el producto, no el renglón. Atrasado es una señal calculada y no se llama "vencido" |
| `docs/decisiones/0014` | **"probablemente recibido" se calcula cada vez y lo decidido se guarda**: por qué no es un estado, por qué el rechazo guarda qué compra y no una fecha tope, por qué solo se confirma lo que trae al menos lo pedido, qué pasa con una compra que encaja con dos renglones, con el proveedor sin puente, y por qué el día del envío es el de la farmacia y el mismo día cuenta |
| `docs/decisiones/0016` | **cerrar avisa lo que se pierde, y reabrir vale mientras nadie use el corte**: por qué el deshacer solo sirve mientras ninguna lista se haya armado después (y no una ventana de tiempo, ni rehacer la siguiente, ni pasar lo perdido a la de hoy), la regla en el `WHERE` y escrita una vez, qué NO deshace, los tres escenarios con números, y la carrera que queda, medida |
| `src/continental/cierre.py` | funciones puras del ADR 0016: qué se da por atendido al cerrar (`al_cerrar`, `lo_que_se_perderia`) y sus frases, el botón de reabrir (`reapertura`), la firma de la reapertura en la hora de la farmacia y por qué no se reabrió |
| `docs/decisiones/0015` | **lo que faltó vuelve como piezas, lo recibido se dice en total, y el estado del pedido se calcula**: por qué no por fechas (propondría también lo que sí llegó) y por qué eso no rompe la reposición 1 a 1, los escenarios de varios días con sus números, por qué el pedido `recibido` no se guarda, por qué se corrige la cifra solo mientras nadie atendió lo que faltó, y por qué más de lo pedido se acepta |
| `src/continental/recepcion.py` | funciones puras: lo que está en tránsito + las compras de SICAR -> propuestas de *probablemente recibido* con su evidencia, y los renglones sin propuesta con su motivo (seis). Empareja por proveedor, producto y día; **nunca por folio**. Ahí viven las frases de la recepción, el aviso de la noche de retraso y la regla de la cantidad (ticket 26, ADR 0014). Desde el 27, también **las piezas escritas a mano** (`piezas_escritas`), el estado que sale de ellas, **el estado del pedido calculado** (`estado_del_pedido`) y las frases de lo recibido a mano y parcial (ADR 0015) |
| `sql/migraciones/` | **doce** archivos numerados: lo que le falta a una base donde las tablas YA existen: `crear_tablas.sql` usa `CREATE TABLE IF NOT EXISTS` y calla si la tabla ya está con otra forma. También a mano y con credenciales de dueño |
| `config/continental.yml` | puertos de los módulos y los parámetros del pedido |
| `src/continental/web/app.py` | `/api/salud`, `/api/modulos`, el pedido sugerido y su cierre, la portada |
| `src/continental/web/static/index.html` | la pantalla, solo el marcado: enlaza la hoja y el script (ticket 28) |
| `src/continental/web/static/continental.css` | la hoja de estilos. **Los colores solo en las dos listas de `:root`** (claro y oscuro); la tabla se apila por debajo de 76rem. El porqué de cada regla va en su comentario |
| `src/continental/web/static/continental.js` | todo el JavaScript de la pantalla. Pinta lo que el servidor manda hecho: **no compone frases que afirman** (lección de los tickets 15 y 21) |
| `tests/conftest.py` | los dobles y, desde el 28, `pantalla_completa()` / `pantalla_servida()`: la pantalla entera tal como la ve el navegador, que es lo único que las pruebas de la pantalla leen |
| `src/continental/almacenamiento.py` | donde el pedido sugerido se guarda: el `Protocol`, el SQL real y las reglas de la tabla en un solo lugar |
| `src/continental/precios.py` | funciones puras: lo que Doyle contestó + la clave buscada -> precio `Decimal` o motivo de rechazo. Ahí vive `emparejar`, la regla por proveedor. No toca la red ni el reloj |
| `src/continental/consultas.py` | quién espera a Doyle y dónde queda el resultado si nadie está mirando |
| `src/continental/lote.py` | el lote nocturno. Tres mitades: lo **puro** —el orden por clase ABC, el cronómetro del tope, el resumen de la corrida—, la **orquestación** (`correr_el_lote`, con los tres bordes por argumento) y el **arranque** (`main`, lo único que construye bordes de verdad). El reloj entra por argumento: una prueba de sesenta minutos cuesta microsegundos |
| `src/continental/verificar.py` | los invariantes sobre los **datos** de producción, no sobre el código. Mitad pura (recibe listas, devuelve un `Informe`, se prueba) y mitad de recolección (lee de Postgres, no se prueba). Acumula todas las fallas, cada una con su comando de reparación, y sale distinto de cero. Es el paso 6 de `desplegar.sh` |
| `src/continental/comparacion.py` | funciones puras: las cuatro lecturas congeladas + las piezas -> quién gana, con qué certeza, cuánto se ahorra contra NADRO y, para la lista entera, cuántos renglones quedaron sin comparar (`contar_la_lista`). No toca la red, la base ni el reloj |
| `src/continental/proveedores.py` | funciones puras: el puente entre la clave de Doyle y el `proveedor_id` de SICAR (ADR 0008). Lee el mapa del YAML, se niega con un aviso a una entrada mal escrita —y deja a ese proveedor "sin puente", que es un estado que el módulo sabe decir— y **nunca devuelve un cero**: `None` es "SICAR no lo conoce" |
| `src/continental/particion.py` | funciones puras: los renglones + sus comparaciones + el puente -> a quién se le pide cada uno, en cuántos pedidos se parte la lista y cuánto suma cada uno. Ahí vive la decisión del ticket 20 —la sugerencia se recalcula, la decisión se guarda—, la regla de que un total con una línea sin precio es `None` y no una suma parcial, desde el 21 **las frases que dicen qué significa "enviar"** y cuándo no se puede (`frase_del_envio`, `motivo_para_no_enviar`), y desde el 22 **la captura**: qué renglones se teclean en el portal de cada pedido —los del pedido guardado, no los de la vista previa—, cuántos faltan, y la frase que lleva a enviar sin obligar (`lo_que_hay_que_capturar`, `frase_del_avance`, `invitacion_a_enviar`) |
| `src/continental/transito.py` | funciones puras: lo ya pedido + las ventas + un `ahora` -> qué producto se queda fuera de la lista (viene en camino), desde qué día vuelve el que ya llegó (`MemoriaDeLoPedido`), cuánto se ha vendido desde que se pidió, y las frases de la pantalla: "Pedido el martes a NADRO, sin recibir.", la firma, lo vendido y la advertencia de que solo sabe de lo que pasó por Continental (ticket 24, ADR 0012). Desde el 25, **el atraso** —cuántos días lleva, si pasó de N, y el límite que recibe el `WHERE` (`dias_en_transito`, `esta_atrasado`, `enviado_antes_de`)— y las frases de cancelar y de lo que vuelve en la siguiente lista (ADR 0013) |
| `src/continental/exportar.py` | funciones puras: el pedido guardado + su captura -> los bytes del CSV (`csv_del_pedido`), su nombre (`nombre_del_archivo`) y su `Content-Disposition`. No escribe un archivo: la ruta sirve los bytes. Ahí vive por qué la clave va como `="..."`, medido contra el Excel de la torre (ticket 23) |
| `src/continental/faltantes.py` | funciones puras: la corrida del lote + las comparaciones -> **por qué** le falta el precio a cada renglón, y **cuáles** va a consultar el botón de completar. Ahí vive la decisión cara del ticket 19: qué cuenta como "faltante", que son ~36 s de navegador por renglón de más si se estira |
| `src/continental/fallas.py` | funciones puras (ticket 29): **qué hacer** ante cada falla (`que_hacer`, seis casos, con el contacto de `a_quien_avisar` del YAML entrando por argumento), las frases de los huecos de la carga, y **qué tan recientes son las ventas** contra el horario de la cadena (`estado_de_las_ventas`): lo que distingue "el domingo no hay ventas" de "no llegaron". El reloj entra por argumento |
| `src/continental/latido.py` | el latido a Uptime Kuma, con monitor propio. `mandar_el_latido` **no levanta nunca** y el borde HTTP entra por argumento, así que ninguna prueba manda uno de verdad. El token vive en `KUMA_PUSH_URL_CONTINENTAL` del `.env`, jamás en el YAML |

## Lo que falta, en orden

1. **Doyle se muda a atlas** (ADR 0008 de Doyle): visor remoto sobre Xvfb para
   abrir sesión, lote que reutiliza un navegador por proveedor, y Doyle sin
   interfaz propia. **Va primero a propósito**: es lo que puede fallar por
   razones que no controlamos —VICMA sin ventana, el captcha de LEVIC, si el
   Chrome de Google arranca en ese CPU de 2010—, y descubrirlo mientras además
   se construye la suite mezclaría dos fallas distintas.
2. **`clase_abc` y `clase_xyz` como columnas de `dim_producto`** en
   farmacia-data (ADR 0018). **Hecho del lado de farmacia-data el 2026-09-20
   (`c989ecb`)**, y Continental lee `clase_abc` desde `f3d7120`
   (`almacen.LA_CLASE_ABC_ESTA_EN_DIM_PRODUCTO = True`). Lo que queda es de
   este repo: decidir si un renglón sin clase (NULL a propósito, sin ventas en
   365 días) debe tumbar `Orden.cumple_el_orden` — ver la nota en el ticket 18.
3. **El módulo de Pedido.** Completo en código desde el ticket 29 (los 29
   tickets); lo que falta es desplegarlo y el día de operación real de abajo.
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

  **Y desde el ticket 26 hay SEIS migraciones que NO crean tabla** —la 0005,
  la 0006, la 0007, la 0008, la 0009 y la 0010, de los tickets 20, 21, 22, 24,
  25 y 26— así que `crear_rol.sql` no hace falta volver a correrlo por ellas: el
  `GRANT SELECT, INSERT, UPDATE` es sobre la tabla entera y no se usan permisos
  por columna. Lo que sí conviene después de las seis es `verificar_rol.sql`,
  porque sus comprobaciones **23 a 35** son suyas. **Las seis van ANTES de
  desplegar el código de su ticket**:
  `_LEER_RENGLONES` nombra las columnas nuevas, y con la base vieja la lista del
  día no se puede leer — y `continental.verificar` no lo caza (ver el ticket 22,
  "sin hacer"):

  ```bash
  docker exec -i farmacia_warehouse psql -U farmacia -d farmacia       -v ON_ERROR_STOP=1 < sql/migraciones/0005-elegir-proveedor-y-partir.sql
  docker exec -i farmacia_warehouse psql -U farmacia -d farmacia       -v ON_ERROR_STOP=1 < sql/migraciones/0006-enviar-el-pedido.sql
  docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
      -v ON_ERROR_STOP=1 < sql/migraciones/0007-el-avance-de-la-captura.sql
  docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
      -v ON_ERROR_STOP=1 < sql/migraciones/0008-el-renglon-que-vuelve-dice-desde-cuando.sql
  docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
      -v ON_ERROR_STOP=1 < sql/migraciones/0009-cancelar-y-devolver-lo-atrasado.sql
  docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
      -v ON_ERROR_STOP=1 < sql/migraciones/0010-la-recepcion-sugerida.sql
  ```

  Sin la 0010, con el código del ticket 26 la lista tampoco se puede leer
  —"column recibido_por does not exist": la nombran `_LEER_RENGLONES`,
  `_LEER_RENGLON_POR_ID`, `_LO_YA_PEDIDO` y `_EN_TRANSITO`—. **Y la recepción
  ejercita por primera vez el GRANT de `marts.fct_compras`**: si un `dbt build`
  se lo llevó, el bloque de la recepción sale como hueco con su motivo (la lista
  sigue) y la comprobación 9 de `verificar_rol.sql` lo dice.

  Sin la 0009, con el código del ticket 25 la lista tampoco se puede leer
  —"column cancelado_por does not exist": la nombran `_LEER_RENGLONES`,
  `_LEER_PEDIDOS` y `_LO_YA_PEDIDO`—.

  Sin la 0008, con el código del ticket 24 la lista **no se puede leer ni
  armar** —"column ventas_desde does not exist": la nombran `_LEER_RENGLONES`,
  `_INSERTAR_RENGLONES` y `_LO_YA_PEDIDO`— y el lote de la noche se corta con su
  motivo en el journal.

  **Y desde el ticket 19 hay una migración más**, que también crea una tabla y
  por lo tanto también exige volver a correr `crear_rol.sql` después:

  ```bash
  docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
      -v ON_ERROR_STOP=1 < sql/migraciones/0004-la-corrida-del-lote-en-una-fila.sql
  # y otra vez crear_rol.sql y verificar_rol.sql, en ese orden
  ```

  El tercero es el que **da el veredicto**: 33 comprobaciones con lo que se
  esperaba y lo que se encontró, y salida distinta de cero si algo quedó mal.
  Es lo que cierra la última casilla del ticket 07, y solo lo puede correr una
  persona con credenciales de dueño en atlas. Las 18, 19 y 20 son del ticket 12
  y miran la forma de la tabla del precio: que no le hayan puesto un `UNIQUE`
  que obligue a pisar el historial, que los ocho motivos sobrevivieran con sus
  acentos, y que sigan puestas las dos restricciones que impiden que un hueco
  se vea como el más barato. La **21 y la 22** son del ticket 19 y miran la
  corrida del lote: que los cuatro finales sobrevivieran con sus acentos, y que
  no pueda guardarse un conteo imposible ni media lista. Las **23 a 26** son del
  ticket 20 y miran el puente con SICAR: que `proveedor_id` admita nulos, que
  `ux_pedido_proveedor` haya quedado sobre la clave de Doyle —sobre
  `proveedor_id` con nulos no impediría nada— y que `fk_renglon_pedido` lleve
  las tres columnas. Las **27 y 28** son del ticket 21: que `ck_pedido_estado`
  conozca los dos estados —con el CHECK viejo, el primer clic en "Enviar" rebota
  en atlas— y que la firma del envío esté pareada en los dos sentidos. La **29**
  es del ticket 22: que la marca de captura tenga sus dos columnas y
  `ck_renglon_captura`. La **30** es del ticket 24: que `renglon.ventas_desde`
  exista y sea `date` que admite nulos. Las **31 a 33** son del ticket 25: que
  `ck_pedido_estado` y `ck_renglon_estado` conozcan `cancelado`, y que las dos
  firmas de la cancelación —la del pedido y la del renglón— estén pareadas.

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

  Las ocho son idempotentes: correrlas dos veces no rompe nada.

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

4. **CERRADO por el ticket 21: el tercer invariante del ticket 17 ya revisa.**
   Se deja anotado porque la forma en que se cerró es el argumento que este
   repositorio tiene para escribir un invariante **antes** de que se pueda
   revisar.

   "Ningún pedido enviado sin quién lo envió" necesitaba `estado` y
   `enviado_por`. El ticket 20 puso la primera y el 21 la segunda, **los dos con
   el nombre que `verificar.COLUMNAS_QUE_EXIGE_EL_ENVIO` ya tenía escrito desde
   el 17**, así que esa tupla nunca cambió y el invariante pasó de `PENDIENTE` a
   revisar de verdad sin que nadie tocara `verificar.py`. Dejó de imprimirse
   como pendiente en cada despliegue.

   **El mecanismo se queda, y no sobra:** una base a la que no se le haya
   corrido la migración 0006 sigue sin esas columnas, y un `SELECT` contra
   `enviado_por` ahí dejaría el despliegue rojo con "column does not exist". La
   recolección trae las columnas que la tabla tiene de verdad y
   `revisar_pedidos_enviados` decide. Fijado por
   `test_envio.test_el_invariante_del_envio_deja_de_estar_pendiente` y por
   `test_envio.test_lo_que_el_codigo_escribe_es_lo_que_el_invariante_espera`,
   que le pasa la fila **tal como el ticket 21 la guardó** — que el invariante
   sepa revisar no basta si lo que se escribe no es lo que él lee.

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

13. **El total de un pedido en borrador envejece si alguien corrige una
   cantidad después de partir.** `pedido.total_sin_iva` se escribe al partir y
   se vuelve a escribir en cada repartición; entre las dos, ajustar la cantidad
   de un renglón que ya está dentro de un pedido **no lo recalcula**. La cifra
   se queda enseñando lo que costaba hace un rato, con su `armado_en` al lado
   —que es lo único que permite notarlo—.

   **Está a medias a propósito y hay que decirlo así**: la tercera casilla del
   ticket 20 pide que un borrador se pueda modificar, así que negar el ajuste
   habría sido peor. Se consideró poner el total en `NULL` cuando se toca un
   renglón repartido —lo honesto—, y se dejó fuera para no meterle una segunda
   sentencia a la ruta del ticket 11 sin poder probarla contra Postgres.

   **CERRADO POR EL TICKET 21, y con la otra de las dos opciones.** Enviar un
   pedido cuyo total envejeció ahora **se niega**: el `WHERE` de
   `_ENVIAR_EL_PEDIDO` lleva un `NOT EXISTS` contra los renglones con
   `ajustada_en > armado_en`, y la pantalla lo dice **antes** del clic con
   `particion.TOTAL_ENVEJECIDO`, que manda a "Volver a partir" — un botón que ya
   existe y cuesta un clic.

   Se eligió negarse y no recalcular al enviar, que era lo que esta nota
   proponía: **recalcular cambiaría el número después de que el encargado leyó
   el del botón**, o sea enviaría un total que nadie vio. Un total viejo
   enseñado es malo; uno nuevo escrito a espaldas de quien lo miró es peor.
   Fijado por `test_envio.test_corregir_una_cantidad_despues_de_partir_bloquea_el_envio`,
   que recorre el camino entero y comprueba que volver a partir lo desbloquea.

   **Lo que sigue abierto, más estrecho:** el total también envejece si llega un
   **precio** nuevo después de armar el pedido, y eso NO se revisa. Duele mucho
   menos —la cantidad es lo que se captura en el portal; el precio de allá manda
   sobre el de Doyle— y revisarlo pediría comparar `armado_en` contra el
   `consultado_en` de cada lectura. **Condición de disparo:** si un total no
   cuadra contra una factura y la cantidad estaba bien.

14. **Un pedido que se queda sin renglones no se puede borrar, y se queda a la
   vista.** Pasa al cambiar una elección y volver a partir: los renglones se van
   al pedido nuevo y el viejo queda vacío. **No se borra** —el rol no tiene
   `DELETE` (ADR 0003)— y su total se pone en `NULL`, que es lo honesto: un
   pedido vacío no cuesta `0.00`, no tiene nada. La pantalla lo enseña igual,
   con cero renglones.

   Es feo y es preferible a las dos alternativas: darle `DELETE` al rol abriría
   la condición de revisión del ADR 0003 entera por un caso cosmético, y
   esconderlo de la pantalla dejaría filas que existen y no se ven. **Condición
   de disparo:** si el encargado se queja de pedidos fantasma, lo que hace falta
   es un estado `cancelado` en `ck_pedido_estado` y no un `DELETE`. **El ticket
   21 tocó ese CHECK y NO lo agregó**, a propósito: nadie ha pedido un cancelado
   y un valor que ningún código escribe es vocabulario muerto invitando a que
   alguien lo use con otro significado. Lo que sí hizo fue dejar el pedido vacío
   **imposible de enviar**, con su motivo escrito en la pantalla
   (`particion.SIN_RENGLONES_QUE_ENVIAR`), que es la mitad del daño.

15. **La incoherencia del descarte sigue puesta, y este ticket NO la empeoró.**
   Descartar un renglón funciona aunque la lista esté `cerrada`: el ticket 10
   solo le puso el estado del **renglón** a su `WHERE`. Ajustar la cantidad sí
   exige lista abierta (ticket 11), y **elegir proveedor y partir se pusieron
   del lado estricto** —los dos llevan `s.estado = 'abierto'` en su `WHERE`—,
   porque armar un pedido dentro de una lista que ya se pidió es justo lo que
   `cerrado` significa que no debe pasar.

   Así que hoy conviven dos criterios sobre la misma lista cerrada: descartar
   entra, y corregir / elegir / partir no. **No se arregló de paso**: mover el
   descarte es cambiar el comportamiento de un ticket cerrado y necesita su
   propia decisión —¿se puede descartar algo de una lista que ya se pidió? el
   glosario dice que `descartado` es "una persona decidió no pedirlo", y sobre
   una lista cerrada eso ya no tiene efecto—. **Condición de disparo:** cuando
   alguien toque la ruta de descartar por cualquier otra razón, se arregla ahí,
   con una prueba que lo fije.

16. **Nadie lee todavía `marts.dim_proveedor`, y el GRANT sigue sin
   ejercitarse.** El puente entero vive en `config/continental.yml`, así que el
   nombre que SICAR le da a un proveedor no se muestra en ningún sitio. Eso
   significa que un `dbt build` que se lleve ese permiso por delante **no se
   notaría** hasta que alguien lo use. El paso 2 del final de `sql/crear_rol.sql`
   —agregarle `grants` a `dim_proveedor.sql` en farmacia-data, que hoy **no tiene
   ninguno**— sigue pendiente y ahora importa más que ayer.

17. **El día del corte se cierra a medias y ese pedacito se pierde.** El
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

18. ~~**La partición miente cuando queda un renglón sin proveedor y otro ya se
   envió.**~~ **Cerrado en el ticket 27**, que tocó `pintarParticion` —su
   condición de disparo— y además lo empeoraba: con lo recibido, la reserva
   decía "sus renglones están en tránsito" sobre lo que ya llegó. Ahora
   `frase_sin_nada_por_repartir` se manda también en el caso mixto (con cuántos
   quedan sin proveedor y sin "ya se puede cerrar") y el título dice "se pidió
   en parte". Lo que sigue es la historia: Lo dejó ver el recorrido del navegador del ticket 26, y **no es de
   ese ticket**: viene del texto de reserva que `pintarParticion` escribe desde
   el 21 cuando no hay partición y sí hay pedidos enviados —*"Esta lista ya se
   pidió entera · No queda nada por repartir: todo lo que había se capturó en
   los portales y sus renglones están en tránsito"*— sin mirar si queda algo
   `abierto` sin proveedor (que es justo cuando `particion.hay` es falso). Desde
   el 26 la pantalla usa la frase de Python (`frase_sin_nada_por_repartir`)
   siempre que llega, pero Python solo la manda cuando `por_repartir` está
   vacío, así que el caso mixto sigue cayendo en la reserva. **Condición de
   disparo:** la siguiente vez que alguien toque `pintarParticion`; el arreglo
   es que la reserva no afirme "entera" si `particion.cuantos_sin_proveedor`
   no es cero, con una prueba sobre el HTML.

## La forma de la base (ADR 0017)

Desde el 2026-09-21 el despliegue tiene **siete** pasos. El **4/7**
(`python -m continental.verificar --forma`) compara las columnas reales de
`pedidos` —leídas como el rol— contra `sql/crear_tablas.sql` y, si falta una,
**no reinicia** y nombra la migración exacta con su comando. El lote de las
22:00 hace la misma revisión al arrancar y, si no cuadra, no corre, sale con 1
y late `down`. El servicio web no se niega a arrancar por esto.

**Lo que el dueño corre a mano antes del primer despliegue con esto**, si la
base de atlas va atrasada: las migraciones que falten, en orden y con
credenciales de dueño, luego `sql/verificar_rol.sql`, luego `desplegar.sh`. La
receta completa está al final de `docs/propuestas/verificar-la-forma-de-la-base.md`;
si no se corre, el paso 4/7 se detiene y dice cuáles faltan, que es lo que se
quiere.
