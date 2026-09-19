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

**El pedido sugerido completo hasta el precio.** Corre, dice si está vivo, dice
quién entró según Cloudflare Access, arma y guarda la lista del día, deja
descartar y corregir cantidades, y desde el ticket 12 **le pide a Doyle el
precio de un renglón en los cuatro proveedores y lo congela con su instante de
lectura**. Lo que falta de precios —emparejar por EAN, comparar los cuatro,
contar los huecos, el lote de la noche— son los tickets 13 en adelante.

```bash
python iniciar.py     # http://127.0.0.1:8585
pytest                # 335 pruebas y 1 saltada, 5.3-5.9 s (2026-09-19, ticket 12)
                      # el número subió con la torre, no con las pruebas: ese
                      # mismo día, con test_precio.py fuera, el árbol del
                      # ticket 11 costaba 3.7-4.2 s contra los 1.7-1.9 s que
                      # había medido por la mañana. Las 100 pruebas nuevas
                      # cuestan ~1.3 s. Ver la nota de `tests/conftest.py`.
```

| Archivo | Qué es |
|---|---|
| `CONTEXT.md` | el glosario del negocio: pedido sugerido, renglón, pedido, sus estados |
| `CLAUDE.md` | las reglas no negociables y las trampas heredadas |
| `docs/decisiones/0001` | la suite como cáscara con módulos por HTTP |
| `docs/decisiones/0002` | el módulo de Pedido: reposición 1 a 1, EAN, recepción sugerida |
| `docs/decisiones/0003` | dónde viven las tablas del pedido y por qué el rol no puede crearlas |
| `docs/decisiones/0004` | el precio congelado: tabla que solo crece, `numeric`, y quién espera a Doyle |
| `sql/` | el DDL de las cuatro tablas, el rol acotado y el verificador. **Se corren a mano, en ese orden, con credenciales de dueño** |
| `sql/migraciones/` | lo que le falta a una base donde las tablas YA existen: `crear_tablas.sql` usa `CREATE TABLE IF NOT EXISTS` y calla si la tabla ya está con otra forma. También a mano y con credenciales de dueño |
| `config/continental.yml` | puertos de los módulos y los parámetros del pedido |
| `src/continental/web/app.py` | `/api/salud`, `/api/modulos`, el pedido sugerido y su cierre, la portada |
| `src/continental/almacenamiento.py` | donde el pedido sugerido se guarda: el `Protocol`, el SQL real y las reglas de la tabla en un solo lugar |
| `src/continental/precios.py` | funciones puras: lo que Doyle contestó -> precio `Decimal` o motivo. No toca la red ni el reloj |
| `src/continental/consultas.py` | quién espera a Doyle y dónde queda el resultado si nadie está mirando |

## Lo que falta, en orden

1. **Doyle se muda a atlas** (ADR 0008 de Doyle): visor remoto sobre Xvfb para
   abrir sesión, lote que reutiliza un navegador por proveedor, y Doyle sin
   interfaz propia. **Va primero a propósito**: es lo que puede fallar por
   razones que no controlamos —VICMA sin ventana, el captcha de LEVIC, si el
   Chrome de Google arranca en ese CPU de 2010—, y descubrirlo mientras además
   se construye la suite mezclaría dos fallas distintas.
2. **`clase_abc` y `clase_xyz` como columnas de `dim_producto`** en
   farmacia-data (ADR 0018). El lote nocturno necesita un orden de importancia
   desde el primer día.
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

- `scripts/desplegar.sh` y `continental-web.service`, calcados de Marlowe:
  `pull`, compila, pruebas, y **solo entonces** reinicia. Marlowe aprendió el
  2026-09-08 por qué: se desplegó un `app.py` que no compilaba y el servicio
  quedó en bucle mientras el dueño trabajaba contra un servidor que no existía.
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

  El tercero es el que **da el veredicto**: 20 comprobaciones con lo que se
  esperaba y lo que se encontró, y salida distinta de cero si algo quedó mal.
  Es lo que cierra la última casilla del ticket 07, y solo lo puede correr una
  persona con credenciales de dueño en atlas. Las tres últimas (18, 19 y 20)
  son del ticket 12 y miran la forma de la tabla del precio: que no le hayan
  puesto un `UNIQUE` que obligue a pisar el historial, que los ocho motivos
  sobrevivieran con sus acentos, y que sigan puestas las dos restricciones que
  impiden que un hueco se vea como el más barato.

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
  2026-09-19), no hay nada que migrar: correrlo ahora ya crea las cuatro tablas
  con todas sus columnas. Si ya se corrió antes de esa fecha, además de los
  tres pasos de arriba, y **en este orden**:

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
  ```

  Las tres son idempotentes: correrlas dos veces no rompe nada.

  **OJO CON LA 0003: después de ella HAY que volver a correr
  `sql/crear_rol.sql`**, y ahí se aparta de las otras dos. Las 0001 y 0002
  agregaban columnas, y el `GRANT SELECT, INSERT, UPDATE` es sobre la tabla
  entera: las cubría solas (no se usan permisos por columna, a propósito). La
  0003 crea una TABLA, y **un permiso no se puede dar sobre una tabla que
  todavía no existe**: el GRANT que se corrió en su día no la alcanza. Sin ese
  paso, el primer clic en "Consultar precio" rebota en atlas con "permission
  denied for table precio_de_proveedor" — y lo hace dentro del hilo que
  consulta, así que la pantalla solo dice "no se pudo guardar el precio"
  mientras el detalle vive en la bitácora. `crear_rol.sql` es idempotente y no
  le toca la contraseña a un rol que ya existe. Las comprobaciones 4 y 6 de
  `verificar_rol.sql` cazan el olvido.

  Ninguna la corre el código de arranque: el rol no tiene DDL y eso es el ADR
  0003.

- **Del lado de farmacia-data, y sin esto lo anterior se borra solo:** agregar
  `'continental'` al `grants` de `dim_fecha.sql`, `dim_producto.sql`,
  `fct_ventas.sql` y `fct_compras.sql`, y **agregarle un `grants` entero a
  `dim_proveedor.sql`, que hoy no tiene ninguno**. Recrear una tabla en
  Postgres borra sus permisos y cada `dbt build` recrea los modelos de
  `marts`: un GRANT dado a mano dura hasta las 20:30 de ese día. Marlowe lo
  midió el 2026-09-06. El detalle está al final de `sql/crear_rol.sql`.
- El remoto de GitHub y la llave de despliegue de solo lectura para atlas.
- La ruta del túnel de Cloudflare para `farmacia.farfanlab.uk`, con Access
  delante.

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

2. **Un fallo de Doyle al PEDIR la búsqueda no deja rastro guardado.** Si
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

3. **El horario del respaldo de SICAR está en `propuesta`** (ADR 0017 de
   farmacia-data): lo decide el dueño. Si se acepta mover el respaldo a las
   ~20:15, **hay que mover el timer de la cadena a las 21:00 en el mismo
   movimiento**, o el colchón baja de hora y media a 15 minutos.
4. **Falta probar `google-chrome --version` en atlas.** Si ese CPU de 2010 no
   lo aguanta, Doyle usa el Chromium de `apt` —que ya está medido— y la parte
   del ADR 0004 que dependía de Chrome queda cerrada.
5. **Qué hay en VITRINA 1-3.** Entró a la lista blanca de "medicamento" a
   petición del dueño, pero nadie escribió qué se guarda ahí.
6. **QuePharma casi seguro va a quedar fuera de la comparación**: usa código
   interno y no está confirmado que encuentre por EAN. Hay dos pendientes
   viejos de Doyle que responden esto —probar el EAN en QuePharma, y confirmar
   VICMA por cantidad de resultados—, y ahora sí importan.
7. **El almacén de contraseñas de atlas baja una garantía.** Hoy no hay ninguna
   contraseña de proveedor en disco; después de la mudanza habrá cuatro,
   ofuscadas pero recuperables. Está aceptado con mitigación (permisos `700`,
   fuera de respaldos) en el ADR 0008 de Doyle. Si alguien saca una copia del
   disco, se cambian las cuatro contraseñas.
8. **El día del corte se cierra a medias y ese pedacito se pierde.** El
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
