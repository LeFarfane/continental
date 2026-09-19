# Estado de Continental — 2026-09-18

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

**Solo el esqueleto, y está honestamente vacío.** Corre, dice si está vivo, dice
quién entró según Cloudflare Access, y le pregunta a Doyle y a Marlowe si
contestan. Nada más.

```bash
python iniciar.py     # http://127.0.0.1:8585
pytest                # 231 pruebas y 1 saltada, ~1.8 s (2026-09-19, ticket 11)
                      # el número subió con la torre, no con las pruebas: ese
                      # mismo día el suite del ticket 10 costaba 1.4-1.9 s.
                      # Ver la nota de `tests/conftest.py`.
```

| Archivo | Qué es |
|---|---|
| `CONTEXT.md` | el glosario del negocio: pedido sugerido, renglón, pedido, sus estados |
| `CLAUDE.md` | las reglas no negociables y las trampas heredadas |
| `docs/decisiones/0001` | la suite como cáscara con módulos por HTTP |
| `docs/decisiones/0002` | el módulo de Pedido: reposición 1 a 1, EAN, recepción sugerida |
| `docs/decisiones/0003` | dónde viven las tablas del pedido y por qué el rol no puede crearlas |
| `sql/` | el DDL de las tres tablas, el rol acotado y el verificador. **Se corren a mano, en ese orden, con credenciales de dueño** |
| `sql/migraciones/` | lo que le falta a una base donde las tablas YA existen: `crear_tablas.sql` usa `CREATE TABLE IF NOT EXISTS` y calla si la tabla ya está con otra forma. También a mano y con credenciales de dueño |
| `config/continental.yml` | puertos de los módulos y los parámetros del pedido |
| `src/continental/web/app.py` | `/api/salud`, `/api/modulos`, el pedido sugerido y su cierre, la portada |
| `src/continental/almacenamiento.py` | donde el pedido sugerido se guarda: el `Protocol`, el SQL real y las reglas de la tabla en un solo lugar |

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

  El tercero es el que **da el veredicto**: 17 comprobaciones con lo que se
  esperaba y lo que se encontró, y salida distinta de cero si algo quedó mal.
  Es lo que cierra la última casilla del ticket 07, y solo lo puede correr una
  persona con credenciales de dueño en atlas.

- **Las migraciones de los tickets 10 y 11, si las tablas ya se crearon antes
  del 2026-09-19.** Entre los dos le agregaron a `pedidos.renglon` cinco
  columnas: `descartado_por` y `descartado_en` (la firma del descarte, ticket
  10) y `cantidad_final`, `ajustada_por` y `ajustada_en` (la cantidad que una
  persona decidió pedir y quién la decidió, ticket 11). Están escritas en los
  **dos** lados: en `sql/crear_tablas.sql`, para una base desde cero, y en
  `sql/migraciones/`, para una base donde la tabla ya existe. Hacen falta los
  dos porque `CREATE TABLE IF NOT EXISTS` **calla si la tabla ya existe con
  otra forma**: volver a correr el DDL sobre una tabla vieja no agrega la
  columna y no avisa, y el primer descarte rebotaría en atlas con "column
  descartado_por does not exist".

  Si `crear_tablas.sql` **todavía no se ha corrido** (que es el caso al
  2026-09-19), no hay nada que migrar: correrlo ahora ya crea las cinco
  columnas. Si ya se corrió antes de esa fecha, además de los tres pasos de
  arriba, y **en este orden**:

  ```bash
  docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
      -v ON_ERROR_STOP=1 \
      < sql/migraciones/0001-renglon-quien-descarto-y-cuando.sql
  docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
      -v ON_ERROR_STOP=1 \
      < sql/migraciones/0002-renglon-cantidad-final-y-quien-la-ajusto.sql
  ```

  Las dos son idempotentes: correrlas dos veces no rompe nada.
  **`sql/crear_rol.sql` no hace falta volver a correrlo**: el `GRANT SELECT,
  INSERT, UPDATE` es sobre la tabla entera y cubre las columnas nuevas (no se
  usan permisos por columna, a propósito). Ninguna la corre el código de
  arranque: el rol no tiene DDL y eso es el ADR 0003.

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

1. **El horario del respaldo de SICAR está en `propuesta`** (ADR 0017 de
   farmacia-data): lo decide el dueño. Si se acepta mover el respaldo a las
   ~20:15, **hay que mover el timer de la cadena a las 21:00 en el mismo
   movimiento**, o el colchón baja de hora y media a 15 minutos.
2. **Falta probar `google-chrome --version` en atlas.** Si ese CPU de 2010 no
   lo aguanta, Doyle usa el Chromium de `apt` —que ya está medido— y la parte
   del ADR 0004 que dependía de Chrome queda cerrada.
3. **Qué hay en VITRINA 1-3.** Entró a la lista blanca de "medicamento" a
   petición del dueño, pero nadie escribió qué se guarda ahí.
4. **QuePharma casi seguro va a quedar fuera de la comparación**: usa código
   interno y no está confirmado que encuentre por EAN. Hay dos pendientes
   viejos de Doyle que responden esto —probar el EAN en QuePharma, y confirmar
   VICMA por cantidad de resultados—, y ahora sí importan.
5. **El almacén de contraseñas de atlas baja una garantía.** Hoy no hay ninguna
   contraseña de proveedor en disco; después de la mudanza habrá cuatro,
   ofuscadas pero recuperables. Está aceptado con mitigación (permisos `700`,
   fuera de respaldos) en el ADR 0008 de Doyle. Si alguien saca una copia del
   disco, se cambian las cuatro contraseñas.
6. **El día del corte se cierra a medias y ese pedacito se pierde.** El
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
