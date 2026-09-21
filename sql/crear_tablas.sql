-- DDL de las CINCO tablas del pedido. Esquema `pedidos`, en el Postgres de
-- farmacia-data.
--
-- Tres son las del glosario de `CONTEXT.md` -- el pedido sugerido, sus
-- renglones y el pedido por proveedor-; la cuarta es el precio congelado por
-- renglón y proveedor (ticket 12) y la quinta es la corrida del lote nocturno
-- (ticket 19, ADR 0007): una fila por noche con cómo le fue, que es de donde
-- la pantalla saca "el lote se cortó por tiempo antes de llegar a este
-- renglón" sin tener que leer un journal por ssh.
--
-- SE CORRE A MANO, UNA VEZ, CON CREDENCIALES DE DUEÑO. No lo corre el
-- servicio, no lo corre una prueba y no lo corre el lote de la noche: crear
-- tablas es DDL, y el rol `continental` no puede hacerlo a propósito (regla 6
-- de CLAUDE.md). Si el día de mañana alguien necesita una columna nueva, la
-- agrega aquí y vuelve a correr este archivo a mano, igual que la primera vez.
--
-- ORDEN DE LOS TRES PASOS -- importa, y el porqué está en cada uno:
--
--   1. sql/crear_tablas.sql   <- este archivo. Crea el esquema y las tablas.
--   2. sql/crear_rol.sql      <- crea el rol y le otorga permisos. Va después
--                                porque no se puede otorgar un permiso sobre
--                                una tabla que todavía no existe.
--   3. sql/verificar_rol.sql  <- dice si quedó bien o mal, caso por caso.
--
-- Desde `~/proyectos/Continental` en atlas:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       -v ON_ERROR_STOP=1 < sql/crear_tablas.sql
--
-- OJO CON EL `<` Y NO `-f`: con `docker exec` el `-f` de psql busca el archivo
-- DENTRO del contenedor, donde este repo no está montado (el compose de
-- farmacia-data solo monta su propio `./sql`). La cabecera de
-- `Marlowe/sql/crear_rol.sql` documenta la forma con `-f` y por eso no corre
-- tal cual; aquí se redirige stdin, que sí funciona.
--
-- `ON_ERROR_STOP=1` porque sin él psql sigue tras un error y termina diciendo
-- que todo salió bien: exactamente la falla silenciosa que este repo prohíbe
-- (regla 4 de CLAUDE.md).
--
--
-- ## Dónde viven y quién las posee
--
-- Esquema **propio** (`pedidos`) y **dueño el rol de dueño** (`farmacia`), no
-- `continental`. Las dos mitades son la misma decisión:
--
-- - Esquema aparte, y no `raw` ni `curado` como hace Marlowe, porque estas
--   tablas no son ni una copia cruda de un origen externo (no hay de qué
--   rehacerlas: nacen aquí) ni algo que una persona curó. Son el estado de un
--   proceso de negocio. Y sobre todo: un esquema propio convierte el límite de
--   la regla 6 en un espacio de nombres, no en una convención -- se puede
--   otorgar y revocar de golpe, y se puede comprobar de golpe.
-- - Dueño `farmacia` y no `continental` porque **el dueño de un esquema tiene
--   CREATE sobre él implícitamente**. Si `continental` poseyera `pedidos`,
--   podría crear tablas ahí y la casilla "el rol acotado no debe poder crear
--   tablas" sería falsa sin que ningún GRANT lo dijera. El dueño de una tabla
--   también puede hacerle ALTER y DROP, que es justo lo que no queremos.
--
-- `CREATE TABLE IF NOT EXISTS` **calla si la tabla ya existe con otra forma**.
-- Por eso `verificar_rol.sql` comprueba la forma (columna `negocio`, nada de
-- coma flotante, la restricción de "uno por día y negocio") y no solo los
-- permisos: sin eso, un DDL editado a medias se vería igual de verde.
--
--
-- ## Y por eso este archivo NO alcanza para agregar una columna
--
-- Este archivo describe **la forma a la que se quiere llegar**, y sirve para
-- una base desde cero. Sobre una base donde las tablas ya existen no hace
-- nada: el `IF NOT EXISTS` calla, la columna nueva no aparece, y el primer
-- `UPDATE` que la nombre rebota con "column ... does not exist" -- una falla
-- que llega hasta atlas justamente porque aquí todo se vio verde.
--
-- Así que **cada columna que nace después de la primera corrida se escribe
-- dos veces**: aquí, para que una base nueva la tenga, y en un archivo de
-- `sql/migraciones/` con su `ALTER TABLE`, para la base que ya existe. Los dos
-- se corren a mano con credenciales de dueño (ADR 0003) y ninguno de los dos
-- lo toca el código de arranque.
--
-- Hoy hay diez, y se corren en orden:
--
--   1. `sql/migraciones/0001-renglon-quien-descarto-y-cuando.sql` (ticket 10),
--      que agrega `descartado_por` y `descartado_en`.
--   2. `sql/migraciones/0002-renglon-cantidad-final-y-quien-la-ajusto.sql`
--      (ticket 11), que agrega `cantidad_final`, `ajustada_por` y
--      `ajustada_en`.
--   3. `sql/migraciones/0003-precio-congelado-por-renglon-y-proveedor.sql`
--      (ticket 12), que crea la CUARTA tabla, `pedidos.precio_de_proveedor`.
--   4. `sql/migraciones/0004-la-corrida-del-lote-en-una-fila.sql` (ticket 19),
--      que crea la QUINTA, `pedidos.corrida_del_lote`: una fila por noche con
--      cómo le fue al lote (ADR 0007).
--   5. `sql/migraciones/0005-elegir-proveedor-y-partir.sql` (ticket 20), que
--      le da a `pedido` su `proveedor` y su `estado`, deja `proveedor_id`
--      admitir nulos, le da a `renglon` la elección firmada, y aprieta dos
--      restricciones que ya existían. NO crea ninguna tabla: siguen siendo
--      cinco.
--   6. `sql/migraciones/0006-enviar-el-pedido.sql` (ticket 21, ADR 0009), que
--      le da a `pedido` el estado `enviado` y su firma. NO crea tabla.
--   7. `sql/migraciones/0007-el-avance-de-la-captura.sql` (ticket 22, ADR
--      0010), que le da a `renglon` la marca de captura firmada. NO crea
--      tabla.
--   8. `sql/migraciones/0008-el-renglon-que-vuelve-dice-desde-cuando.sql`
--      (ticket 24, ADR 0012), que le da a `renglon` su `ventas_desde`. NO crea
--      tabla. (Faltaba en esta lista hasta el ticket 25.)
--   9. `sql/migraciones/0009-cancelar-y-devolver-lo-atrasado.sql` (ticket 25,
--      ADR 0013), que le da a `pedido` el estado `cancelado` y a los dos -
--      `pedido` y `renglon`- la firma de la cancelación. NO crea tabla.
--  10. `sql/migraciones/0010-la-recepcion-sugerida.sql` (ticket 26, ADR
--      0014), que le da a `renglon` la firma de la recepción con sus compras
--      y lo rechazado. NO crea tabla.
--
-- Las diez son idempotentes, así que correrlas sobre una base que ya las
-- tiene -o sobre una recién creada con este archivo- no rompe nada.
--
-- **La 0003 y la 0004 son distintas de las dos primeras y hay que decirlo**:
-- cada una crea una TABLA entera, así que además exigen volver a correr
-- `sql/crear_rol.sql` -- un GRANT no se puede dar sobre una tabla que no
-- existía-. Las dos primeras no lo exigían porque el GRANT es sobre la tabla
-- completa y cubre las columnas nuevas, y es justo esa diferencia la que hace
-- fácil olvidarlo. Sin ese paso, el primer precio que se intente guardar en
-- atlas rebota con "permission denied for table precio_de_proveedor" -- y con
-- la 0004, el lote de las 22:00 no puede escribir su corrida, así que a la
-- mañana la pantalla dice "el lote no corrió sobre esta lista" sobre una noche
-- en la que sí corrió-, después de que aquí todo se vio verde.
--
--
-- ## Acentos
--
-- **Identificadores en ASCII, valores con su acento.** `renglon` se llama
-- `renglon` (igual que `ubicacion` y `descripcion` en el resto del proyecto),
-- pero el estado del glosario se guarda tal cual se escribe: 'en tránsito',
-- con acento, porque `CONTEXT.md` manda sobre el nombre de cualquier cosa e
-- inventar `en_transito` sería un segundo nombre para lo mismo. Es el mismo
-- patrón que ya usa el código: `clasificacion.SIN_CLASIFICAR == "sin
-- clasificar"`, con espacio y todo.
--
-- El `SET client_encoding` de abajo no es decorativo: si psql manda este
-- archivo como latin1, el acento entra deformado **dentro de la definición del
-- CHECK**, y el primer `UPDATE ... SET estado = 'en tránsito'` de Continental
-- rebota con una violación de restricción que nadie sabría explicar. La
-- comprobación 15 de `verificar_rol.sql` lee el CHECK de vuelta y avisa.

SET client_encoding TO 'UTF8';

-- Que no lo corra quien no debe. Correr este archivo con el rol acotado no
-- fallaría por permisos si alguien, en algún momento, le dio CREATE: fallaría
-- creando tablas que `continental` posee -- que es el escenario exacto que
-- este DDL existe para evitar.
DO $guardia$
BEGIN
    IF current_user = 'continental' THEN
        -- Concatenación EXPLÍCITA con `||` y no dos literales pegados: en
        -- SQL, dos cadenas separadas por un salto de línea se unen solas,
        -- pero dentro de PL/pgSQL eso depende del analizador y no vale la
        -- pena averiguarlo en producción con ON_ERROR_STOP puesto.
        RAISE EXCEPTION '%',
            'Este DDL se corre con credenciales de DUEÑO (usuario farmacia), '
            || 'no con el rol acotado continental. Las tablas deben quedar a '
            || 'nombre del dueño: quien posee una tabla puede alterarla y '
            || 'borrarla.';
    END IF;
END
$guardia$;

CREATE SCHEMA IF NOT EXISTS pedidos;

COMMENT ON SCHEMA pedidos IS
    'Lo que Continental escribe: pedido sugerido, renglones, pedidos por '
    'proveedor, el precio congelado de cada proveedor y la corrida del lote '
    'nocturno. Lo posee el dueño del almacén; el rol continental solo tiene '
    'USAGE, nunca CREATE.';


-- --------------------------------------------------------------------------
-- 1) El pedido sugerido: la lista de un día (CONTEXT.md).
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS pedidos.pedido_sugerido (
    pedido_sugerido_id        bigint       GENERATED ALWAYS AS IDENTITY,
    negocio                   text         NOT NULL,
    fecha_del_pedido          date         NOT NULL,
    estado                    text         NOT NULL DEFAULT 'abierto',
    ventas_consideradas_desde date         NOT NULL,
    ventas_consideradas_hasta date         NOT NULL,
    armado_en                 timestamptz  NOT NULL DEFAULT now(),
    cerrado_en                timestamptz,

    CONSTRAINT pk_pedido_sugerido
        PRIMARY KEY (pedido_sugerido_id),

    -- "Uno por día y negocio" es una RESTRICCIÓN, no una intención: que lo
    -- impida la base y no el código. Un SELECT-y-si-no-existe-INSERT en Python
    -- tiene una carrera entre los dos pasos, y dos pestañas abiertas a la
    -- misma hora bastan para duplicar la lista del día sin un solo error.
    CONSTRAINT ux_pedido_sugerido_dia
        UNIQUE (negocio, fecha_del_pedido),

    -- Existe solo para que `renglon` y `pedido` puedan apuntar aquí con una
    -- llave foránea COMPUESTA que incluya el negocio. Es lo que impide que un
    -- renglón de farmacia_01 cuelgue de un pedido sugerido de otro negocio:
    -- sin esto, la columna `negocio` duplicada podría divergir en silencio.
    CONSTRAINT ux_pedido_sugerido_negocio
        UNIQUE (pedido_sugerido_id, negocio),

    CONSTRAINT ck_pedido_sugerido_negocio
        CHECK (negocio <> ''),

    -- Los tres estados del glosario y ninguno más. Un sinónimo que se cuele
    -- ("cerrada", "finalizado") parte la lista en dos vocabularios y las
    -- consultas empiezan a mentir por omisión.
    CONSTRAINT ck_pedido_sugerido_estado
        CHECK (estado IN ('abierto', 'cerrado', 'vencido')),

    CONSTRAINT ck_pedido_sugerido_ventana
        CHECK (ventas_consideradas_desde <= ventas_consideradas_hasta),

    -- Cerrado si y solo si hay fecha de cierre. Un `cerrado` sin hora no se
    -- puede auditar, y una hora de cierre en una lista abierta es una mentira
    -- a la espera de que alguien la lea.
    CONSTRAINT ck_pedido_sugerido_cierre
        CHECK ((estado = 'cerrado') = (cerrado_en IS NOT NULL))
);

COMMENT ON TABLE pedidos.pedido_sugerido IS
    'La lista de un día: qué conviene comprar. Uno por día y negocio, '
    'garantizado por ux_pedido_sugerido_dia.';

-- `negocio` sin DEFAULT a propósito. Un default dejaría escribir una fila sin
-- decir de qué negocio es, que es justo lo contrario de la regla 7 de
-- CLAUDE.md. Hoy siempre vale `farmacia_01` y aun así se escribe cada vez: es
-- lo único que se paga hoy para no reescribir el módulo el día que haya dos.
COMMENT ON COLUMN pedidos.pedido_sugerido.negocio IS
    'Código de negocio, el mismo de config/farmacia.yml de farmacia-data (hoy '
    'farmacia_01, NO "farmacia" a secas: con el valor equivocado el join sale '
    'vacío sin error -- a Marlowe le costó una tarde el 2026-09-05).';

-- Fecha y no timestamp, y esto es una decisión medida, no pereza: el grano más
-- fino que existe en el almacén es el DÍA. `marts.fct_ventas` se une a
-- `marts.dim_fecha` por `fecha_id` y no guarda hora, así que un `timestamptz`
-- aquí inventaría una precisión que el dato no tiene -- y con las ventas
-- llegando hasta 2.5 días tarde (respaldo de SICAR a las 18:51, cadena a las
-- 20:30, lo del sábado hasta el lunes) esa precisión falsa sería justo la que
-- alguien usaría para decidir desde dónde acumular.
COMMENT ON COLUMN pedidos.pedido_sugerido.ventas_consideradas_hasta IS
    'Hasta qué día de ventas consideró la lista. Sale de max(fecha) del '
    'almacén, NUNCA del reloj: el Postgres del contenedor corre en UTC y su '
    'current_date puede ir dos días adelante del último dato (a farmacia-data '
    'le costó 11.7 puntos de crecimiento inventados).';

COMMENT ON COLUMN pedidos.pedido_sugerido.ventas_consideradas_desde IS
    'Desde qué día de ventas acumuló. La ventana es un rango y guardar solo su '
    'extremo derecho haría imposible auditar de dónde salió un renglón.';

-- `armado_en` y `cerrado_en` SÍ miran el reloj, y no contradice la regla de
-- anclarse en max(fecha): esa regla es sobre FECHAS DE VENTA -- de qué datos
-- salió la lista --, y estas dos columnas son sobre CUÁNDO PASÓ ALGO AQUÍ, que
-- es precisamente lo que un reloj sabe y el almacén no.
--
-- `timestamptz` y no `timestamp`: el contenedor corre en UTC, así que un
-- `timestamp` sin zona guardaría un reloj de pared UTC que alguien en México
-- lee seis horas en el futuro. Con zona, Postgres guarda el instante y lo
-- pinta en la zona de quien pregunta.
COMMENT ON COLUMN pedidos.pedido_sugerido.armado_en IS
    'Cuándo se armó la lista (instante real, con zona). Distinto de '
    'ventas_consideradas_hasta, que es de qué día son los datos.';


-- --------------------------------------------------------------------------
-- 2) El pedido: lo que se le pide a UN proveedor (CONTEXT.md).
-- --------------------------------------------------------------------------
--
-- Va antes que `renglon` en este archivo porque `renglon` le apunta con una
-- llave foránea, y una tabla no puede referenciar a otra que no existe.

CREATE TABLE IF NOT EXISTS pedidos.pedido (
    pedido_id           bigint        GENERATED ALWAYS AS IDENTITY,
    negocio             text          NOT NULL,
    pedido_sugerido_id  bigint        NOT NULL,
    proveedor_id        bigint,
    armado_en           timestamptz   NOT NULL DEFAULT now(),
    total_sin_iva       numeric(12,2),

    -- LAS COLUMNAS NUEVAS VAN AL FINAL, igual que en `renglon` y por lo mismo:
    -- una base migrada las recibe por `ALTER TABLE ... ADD COLUMN`, que las
    -- pone al final, y si aquí se declararan en otro lugar la base desde cero y
    -- la migrada tendrían distinto orden de columnas. `proveedor` se leería
    -- mejor pegado a `proveedor_id` y aun así va aquí.
    proveedor           text          NOT NULL,
    estado              text          NOT NULL DEFAULT 'borrador',
    enviado_por         text,
    enviado_en          timestamptz,
    -- La firma de la cancelación (ticket 25, ADR 0013, migración 0009).
    cancelado_por       text,
    cancelado_en        timestamptz,

    CONSTRAINT pk_pedido
        PRIMARY KEY (pedido_id),

    -- "Un pedido sugerido puede repartirse en varios pedidos, UNO POR
    -- PROVEEDOR" (CONTEXT.md). Dos pedidos al mismo proveedor desde la misma
    -- lista serían dos veces la misma mercancía.
    --
    -- DESDE EL TICKET 20 ES SOBRE `proveedor` Y NO SOBRE `proveedor_id`, y ese
    -- cambio es la mitad visible de la decisión del ADR 0008. Con la columna de
    -- SICAR admitiendo nulos, un UNIQUE sobre ella DEJA DE IMPEDIR LO QUE
    -- EXISTE PARA IMPEDIR: en Postgres dos nulos no se consideran iguales, así
    -- que dos pedidos a QuePharma -que no tiene `pro_id`- pasarían los dos sin
    -- un solo error. La garantía tiene que estar sobre la columna que siempre
    -- vale algo, que es la clave de Doyle.
    --
    -- Es además la restricción que `_ABRIR_EL_PEDIDO` nombra en su
    -- `ON CONFLICT ON CONSTRAINT`: partir dos veces reencuentra el pedido que
    -- ya estaba en vez de duplicarlo.
    CONSTRAINT ux_pedido_proveedor
        UNIQUE (pedido_sugerido_id, proveedor),

    -- SIN UNIQUE sobre `proveedor_id`, y es deliberado. Dos claves de Doyle
    -- apuntando al mismo `pro_id` sería un error del mapa de
    -- `config/continental.yml`, y la manera de atenderlo es el aviso que
    -- `proveedores.leer_el_puente` escribe al arrancar -- no un pedido que
    -- rebota con una violación de restricción a media mañana, que es en lo que
    -- se convertiría (y que por la regla 5 de CLAUDE.md el encargado vería como
    -- "algo falló").
    CONSTRAINT ux_pedido_negocio
        UNIQUE (pedido_id, negocio),

    -- Existe para que `renglon` pueda apuntar aquí con una llave foránea que
    -- incluya la LISTA. Es lo que impide que un renglón de la lista del martes
    -- cuelgue de un pedido de la del lunes: sin ella, "un renglón pertenece a
    -- un solo pedido" sería cierto y aun así el total de ese pedido no se
    -- podría explicar, porque contaría mercancía de otro día.
    CONSTRAINT ux_pedido_de_la_lista
        UNIQUE (pedido_id, pedido_sugerido_id, negocio),

    CONSTRAINT ck_pedido_negocio
        CHECK (negocio <> ''),

    -- Sin saber a quién se le pide, el pedido no sirve para nada. La cadena
    -- vacía no existe en ninguna columna de texto de este esquema, por la misma
    -- razón que en `ck_renglon_clave`: se compara igual que un dato y empareja
    -- con cualquier otra vacía.
    CONSTRAINT ck_pedido_proveedor
        CHECK (proveedor <> ''),

    -- NULL es "SICAR no conoce a este proveedor" y se puede pedir igual; UN
    -- CERO ES UN ID INVENTADO. Cabe en un `bigint` sin protestar y a partir de
    -- ahí todo `join` contra `dim_proveedor` sale vacío sin error -- la falla
    -- silenciosa que la regla 4 de CLAUDE.md prohíbe, y el mismo daño que hace
    -- un precio en cero en la comparación.
    CONSTRAINT ck_pedido_proveedor_id
        CHECK (proveedor_id > 0),

    -- DOS ESTADOS Y NINGUNO MÁS. `borrador` es donde nace todo pedido (ticket
    -- 20): "se pueden modificar mientras estén así". `enviado` lo estrena el
    -- ticket 21 y quiere decir **una persona ya lo capturó en el portal del
    -- proveedor** -- NO que Continental se lo haya mandado a nadie, porque
    -- Continental no entra a los portales (regla 1 de CLAUDE.md, ADR 0002 y ADR
    -- 0009)--.
    --
    -- El ticket 20 se quedó con uno solo a propósito -el glosario no tenía el
    -- otro todavía, y el glosario manda sobre el nombre de cualquier cosa- y
    -- dejó anotado lo que costaría: "el ticket 21 paga una migración para
    -- ampliar este CHECK". Es `sql/migraciones/0006-enviar-el-pedido.sql`.
    --
    -- `cancelado` LLEGÓ CON EL TICKET 25 (ADR 0013, migración 0009): una
    -- persona dijo que el pedido NO está en el portal del proveedor. Solo desde
    -- `enviado`, y es un final: no vuelve a borrador -el ADR 0009 sigue sin
    -- "desenviar"-, no se edita y no se vuelve a enviar. Hasta ese ticket aquí
    -- decía que no existía porque nadie lo había pedido.
    CONSTRAINT ck_pedido_estado
        CHECK (estado IN ('borrador', 'enviado', 'cancelado')),

    CONSTRAINT ck_pedido_total
        CHECK (total_sin_iva >= 0),

    -- La cadena vacía no existe en ninguna columna de texto de este esquema.
    -- Sin encabezado de Access, `web.app.quien()` devuelve 'sin-identificar',
    -- que SÍ es un dato y se puede buscar.
    CONSTRAINT ck_pedido_enviado_por
        CHECK (enviado_por <> ''),

    -- ENVIADO SI Y SOLO SI HAY FIRMA Y HORA. El mismo par que
    -- `ck_renglon_descarte`, `ck_renglon_ajuste` y `ck_renglon_eleccion`, y aquí
    -- es donde más falta hace: lo que esta tabla guarda al enviar NO es un hecho
    -- que Continental haya observado -ocurrió en otra pantalla, con otras
    -- credenciales-, así que sin la firma no queda ningún hecho guardado, solo
    -- un "se envió" en voz pasiva y nadie a quien preguntarle qué se capturó
    -- cuando la factura no cuadre.
    --
    -- Y al revés: una firma colgada de un borrador diría que alguien envió lo
    -- que nadie envió.
    --
    -- DESDE EL TICKET 25 VALE TAMBIÉN PARA `cancelado`: solo se cancela lo que
    -- alguien dijo haber enviado, y esa palabra no se borra al cancelar -es
    -- parte de la historia del pedido-.
    CONSTRAINT ck_pedido_envio
        CHECK ((estado IN ('enviado', 'cancelado'))
               = (enviado_por IS NOT NULL AND enviado_en IS NOT NULL)),

    CONSTRAINT ck_pedido_cancelado_por
        CHECK (cancelado_por <> ''),

    -- CANCELADO SI Y SOLO SI HAY FIRMA Y HORA, el mismo par que el envío. Lo que
    -- se guarda es la palabra de una persona sobre un portal que Continental no
    -- ve: sin firma, cuando la mercancía llegue de todos modos no habría a quién
    -- preguntarle.
    CONSTRAINT ck_pedido_cancelacion
        CHECK ((estado = 'cancelado')
               = (cancelado_por IS NOT NULL AND cancelado_en IS NOT NULL)),

    CONSTRAINT fk_pedido_sugerido
        FOREIGN KEY (pedido_sugerido_id, negocio)
        REFERENCES pedidos.pedido_sugerido (pedido_sugerido_id, negocio)
);

COMMENT ON TABLE pedidos.pedido IS
    'Lo que se le pide a UN proveedor, nacido de renglones de un pedido '
    'sugerido. Uno por proveedor dentro de la misma lista.';

-- LA IDENTIDAD DEL PEDIDO ES LA CLAVE DE DOYLE, Y ÉSA ES LA DECISIÓN DEL
-- TICKET 20 (ADR 0008). Hasta aquí, la comparación entera hablaba en claves
-- -`nadro`, `levic`, `vicma`, `quepharma`, que es lo que guarda
-- `precio_de_proveedor.proveedor`- y esta tabla hablaba en `pro_id` de SICAR.
-- **Nada las cruzaba**: ni el YAML, ni el código, ni este archivo.
--
-- Se le pide a quien se le preguntó el precio. Si la identidad fuera el
-- `proveedor_id`, un proveedor sin fila en SICAR no se podría pedir -- y eso no
-- es una hipótesis: QUEPHARMA NO ESTÁ en `marts.dim_proveedor` (22 filas,
-- medido en atlas el 2026-09-19; NADRO es el 1, VICMA el 8 y LEVIC el 10). La
-- farmacia nunca le ha comprado, que es exactamente por lo que el ADR 0002 ya
-- daba por probable que quedara fuera de la comparación.
--
-- El mapa clave -> pro_id vive en `config/continental.yml`
-- (`pedido.proveedores_en_sicar`) y se lee en `src/continental/proveedores.py`.
COMMENT ON COLUMN pedidos.pedido.proveedor IS
    'La clave de Doyle: nadro, levic, vicma, quepharma. Es la IDENTIDAD del '
    'pedido -- a quién se le preguntó el precio y a quién se le pide--, la '
    'misma que precio_de_proveedor.proveedor.';

-- SIN llave foránea contra `marts.dim_proveedor`, y es deliberado: `dbt build`
-- **borra y vuelve a crear** los modelos de `marts` cada noche. Una FK contra
-- una tabla que se recrea o bien impide el DROP -- y entonces la cadena
-- nocturna se cae por culpa de Continental -- o desaparece con ella, que es
-- peor porque nadie se entera. La integridad de este id se sostiene con la
-- lectura de `marts.dim_proveedor` que hace el código, no con una restricción
-- que la cadena de la noche va a borrar.
--
-- ADMITE NULOS DESDE EL TICKET 20, y es la otra mitad del ADR 0008: el puente
-- puede faltar y el pedido se arma igual. NULL aquí quiere decir *"SICAR no
-- conoce a este proveedor"*, que es un hecho del catálogo de la farmacia y no
-- un dato que falte por capturar.
--
-- QUÉ PASA SI SICAR RENOMBRA UNO: nada. El `pro_id` no cambia al renombrar, y
-- por eso el puente del YAML guarda el ID y no el nombre -- un puente por
-- nombre se rompería con el primer acento corregido. El nombre se lee de
-- `dim_proveedor` cada vez, y solo para pintarlo.
--
-- QUÉ PASA SI SICAR DA UNO DE BAJA: este id se queda apuntando a una fila que
-- ya no está, y el `join` no devuelve nombre. Eso NO borra el pedido ni lo
-- esconde: la pantalla escribe la clave de Doyle, que es la identidad, y dice
-- que SICAR ya no lo conoce. Un pedido que desapareciera de la vista porque
-- alguien editó un catálogo ajeno sería la peor de las fallas silenciosas.
COMMENT ON COLUMN pedidos.pedido.proveedor_id IS
    'marts.dim_proveedor.proveedor_id (pro_id de SICAR). NULL = SICAR no lo '
    'conoce, y se le puede pedir igual; NUNCA cero. Sin FK a propósito: dbt '
    'recrea marts en cada corrida y se llevaría la restricción por delante.';

-- NACE EN `borrador` Y SE PUEDE MODIFICAR MIENTRAS ESTÉ ASÍ (ticket 20). El
-- DEFAULT está y aun así `columnas_del_pedido` lo escribe explícito, por la
-- misma razón que `columnas_de_la_lista` escribe el suyo: lo que se escribe se
-- lee.
--
-- UN BORRADOR TODAVÍA NO SE LE PIDIÓ A NADIE, y de ahí sale algo que conviene
-- no redescubrir: repartir un renglón **no** lo pone `en tránsito`. El glosario
-- define ese estado como "ya se le pidió a un proveedor y todavía no llega", y
-- eso pasa cuando el pedido se envía (ticket 21), no cuando se arma. El renglón
-- se queda `abierto` con su `pedido_id` puesto -- que es justo lo que lo deja
-- seguir siendo modificable, como la casilla pide.
COMMENT ON COLUMN pedidos.pedido.estado IS
    'borrador, enviado o cancelado. Nace en borrador y se puede modificar '
    'mientras esté así. enviado = una persona ya lo capturó en el portal del '
    'proveedor; Continental no le manda nada a nadie (ADR 0009). cancelado = '
    'una persona dijo que no está en el portal; es un final (ADR 0013).';

-- LA FIRMA DEL ENVÍO, Y POR QUÉ ES UNA FIRMA Y NO UN ACUSE (ticket 21).
--
-- El hecho que se guarda -"ya lo capturé en el portal de NADRO"- ocurrió en
-- OTRA pantalla, con otras credenciales, y Continental no lo vio: no entra a
-- los portales y no va a entrar. Un acuse es la respuesta de alguien más y aquí
-- no hay alguien más, así que lo único verdadero que se puede escribir es quién
-- lo dice y cuándo lo dijo.
--
-- Es una FIRMA y NUNCA un permiso (regla 3 de CLAUDE.md): el correo lo validó
-- Cloudflare Access y sirve para saber a quién preguntarle qué se capturó, no
-- para decidir si podía enviarlo.
--
-- `timestamptz` y no `timestamp`, igual que `armado_en` y por lo mismo: el
-- contenedor corre en UTC y un reloj de pared sin zona se lee seis horas en el
-- futuro desde México.
COMMENT ON COLUMN pedidos.pedido.enviado_por IS
    'Quién declaró haberlo capturado en el portal, según '
    'Cf-Access-Authenticated-User-Email. Es una FIRMA, no un permiso. NULL '
    'mientras siga en borrador.';

COMMENT ON COLUMN pedidos.pedido.enviado_en IS
    'Cuándo lo dijo, instante con zona. NULL mientras siga en borrador.';

COMMENT ON COLUMN pedidos.pedido.cancelado_por IS
    'Quién dijo que el pedido no está en el portal del proveedor (nunca se '
    'capturó, o se canceló allá). Es una FIRMA, no un permiso. NULL si no '
    'está cancelado.';

COMMENT ON COLUMN pedidos.pedido.cancelado_en IS
    'Cuándo lo dijo, instante con zona. NULL si no está cancelado.';

-- EL DINERO ES DECIMAL EXPLÍCITO, NUNCA COMA FLOTANTE. `numeric(12,2)`, igual
-- que `raw.precio_competencia.precio` en Marlowe, y por la misma lección
-- medida en farmacia-data: dejar que una librería DEDUZCA el tipo terminó
-- metiendo dinero en `double precision`, donde 0.1 + 0.2 no es 0.3 y un total
-- de pedido deja de cuadrar contra la factura del proveedor por centavos que
-- nadie puede explicar.
--
-- NULL y no 0: hoy no hay precios todavía (los traen los tickets 12 en
-- adelante) y un cero se leería como "este pedido no cuesta nada". "Sin dato"
-- jamás es un cero -- regla 4 de CLAUDE.md, la misma por la que un precio que
-- no se pudo leer nunca es "más barato".
--
-- SIN IVA, y el nombre lo dice para que no haya que acordarse: el costo
-- nuestro es sin IVA y el de mostrador con IVA, y restarlos directo es el
-- error con el que Marlowe puso la flecha al revés.
COMMENT ON COLUMN pedidos.pedido.total_sin_iva IS
    'Lo que cuesta este pedido, decimal explícito. NULL = todavía no se sabe, '
    'nunca cero.';


-- --------------------------------------------------------------------------
-- 3) El renglón: un producto con su cantidad dentro de un pedido sugerido.
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS pedidos.renglon (
    renglon_id           bigint        GENERATED ALWAYS AS IDENTITY,
    negocio              text          NOT NULL,
    pedido_sugerido_id   bigint        NOT NULL,
    pedido_id            bigint,
    producto_id          bigint        NOT NULL,
    clave                text,
    descripcion          text          NOT NULL,
    piezas_vendidas      numeric(12,3) NOT NULL,
    cantidad_propuesta   integer       NOT NULL,
    esta_en_el_catalogo  boolean       NOT NULL,
    existencia           numeric(12,3),
    dias_de_cobertura    numeric(8,1),
    clasificacion        text          NOT NULL,
    estado               text          NOT NULL DEFAULT 'abierto',
    descartado_por       text,
    descartado_en        timestamptz,

    -- LAS COLUMNAS NUEVAS VAN AL FINAL, no junto a la que se les parece.
    -- `cantidad_final` se leería mejor pegada a `cantidad_propuesta`, y aun así
    -- va aquí: una base migrada las recibe por `ALTER TABLE ... ADD COLUMN`,
    -- que las pone al final, y si este archivo las declarara en otro lugar la
    -- base desde cero y la migrada tendrían distinto orden de columnas. Un
    -- `\d pedidos.renglon` en atlas dejaría de parecerse a este archivo, que es
    -- lo único para lo que sirve.
    cantidad_final       integer,
    ajustada_por         text,
    ajustada_en          timestamptz,
    proveedor_elegido    text,
    elegido_por          text,
    elegido_en           timestamptz,
    capturado_por        text,
    capturado_en         timestamptz,
    -- Desde qué día se sumaron sus ventas cuando NO es el principio de la
    -- ventana de su lista (ticket 24, ADR 0012, migración 0008). NULL en casi
    -- todos. Sin CHECK: la regla que lo relaciona con la ventana es de OTRA
    -- tabla, y un CHECK no puede mirar otra fila.
    ventas_desde         date,
    -- La firma de la cancelación (ticket 25, ADR 0013, migración 0009): su
    -- pedido se canceló, o alguien lo devolvió a la lista por atrasado.
    cancelado_por        text,
    cancelado_en         timestamptz,
    -- LA RECEPCIÓN (ticket 26, ADR 0014, migración 0010). Quién confirmó que
    -- llegó, cuándo, y con qué compras de SICAR -por su `compra_id`, nunca por
    -- folio-. Y lo rechazado: qué compras dijo una persona que NO son este
    -- renglón, con la firma del último rechazo. "Probablemente recibido" NO
    -- es una columna: se calcula cada vez que se mira.
    recibido_por            text,
    recibido_en             timestamptz,
    recibido_con_compras    bigint[],
    compras_rechazadas      bigint[],
    recepcion_rechazada_por text,
    recepcion_rechazada_en  timestamptz,

    CONSTRAINT pk_renglon
        PRIMARY KEY (renglon_id),

    -- Un producto aparece UNA vez por lista: `fct_ventas` tiene grano ticket x
    -- artículo y `sugerido.calcular_pedido_sugerido` ya suma las piezas de
    -- todos los tickets del día en un solo renglón. Dos renglones del mismo
    -- producto serían pedirlo dos veces.
    CONSTRAINT ux_renglon_producto
        UNIQUE (pedido_sugerido_id, producto_id),

    CONSTRAINT ux_renglon_negocio
        UNIQUE (renglon_id, negocio),

    CONSTRAINT ck_renglon_negocio
        CHECK (negocio <> ''),

    -- La clave vacía NO existe: o hay EAN o no se sabe (NULL). Una cadena
    -- vacía es un tercer valor que se compara igual que un dato y empareja con
    -- cualquier otra vacía -- que es exactamente cómo se emparejan productos
    -- que no tienen nada que ver.
    CONSTRAINT ck_renglon_clave
        CHECK (clave <> ''),

    CONSTRAINT ck_renglon_piezas
        CHECK (piezas_vendidas >= 0),

    CONSTRAINT ck_renglon_cantidad
        CHECK (cantidad_propuesta >= 0),

    CONSTRAINT ck_renglon_cobertura
        CHECK (dias_de_cobertura >= 0),

    -- Un producto que el catálogo no conoce no tiene EAN ni existencia que
    -- mirar. El renglón entra igual -- esconderlo sería reponer de menos sin
    -- que nadie lo note -- pero entra diciendo que no se sabe, no con ceros
    -- inventados.
    CONSTRAINT ck_renglon_sin_catalogo
        CHECK (esta_en_el_catalogo OR (clave IS NULL AND existencia IS NULL)),

    -- Las tres de `clasificacion.py`, con el mismo texto exacto.
    CONSTRAINT ck_renglon_clasificacion
        CHECK (clasificacion IN ('medicamento', 'abarrote', 'sin clasificar')),

    -- Los seis estados del glosario. 'en tránsito' CON ACENTO: ver la nota de
    -- la cabecera. `cancelado` llegó con el ticket 25 (migración 0009) y va al
    -- final, igual que en `almacenamiento.ESTADOS_DEL_RENGLON`.
    CONSTRAINT ck_renglon_estado
        CHECK (estado IN ('abierto', 'en tránsito', 'recibido',
                          'recibido parcial', 'descartado', 'cancelado')),

    -- La firma vacía no existe, por la misma razón que la clave vacía: una
    -- cadena vacía se compara igual que un dato y no se distingue de "no se
    -- sabe". `web.app.quien()` nunca devuelve '' -- sin encabezado devuelve
    -- 'sin-identificar', que es un dato de verdad -- así que esto es el
    -- cinturón, no el caso esperado.
    CONSTRAINT ck_renglon_descartado_por
        CHECK (descartado_por <> ''),

    -- Descartado si y solo si hay firma Y hora, igual que
    -- `ck_pedido_sugerido_cierre` hace con el cierre de la lista.
    --
    -- Las dos mitades hacen falta. Sin la de ida, un renglón podría quedar
    -- 'descartado' sin decir quién ni cuándo, y la CONDICIÓN DE REVISIÓN del
    -- ADR 0002 -"si después de un mes de uso los renglones descartados superan
    -- a los pedidos, la reposición 1 a 1 no es la regla correcta"- dejaría de
    -- ser medible: sin `descartado_en` no hay forma de acotar "de un mes". Sin
    -- la de vuelta, un renglón devuelto a 'abierto' por error conservaría la
    -- firma del descarte y ese mismo conteo mensual sumaría renglones que hoy
    -- están abiertos.
    CONSTRAINT ck_renglon_descarte
        CHECK ((estado = 'descartado')
               = (descartado_por IS NOT NULL AND descartado_en IS NOT NULL)),

    -- AL MENOS UNA PIEZA, y aquí está la mitad silenciosa del ticket 11: UN
    -- CERO NO ES UNA FORMA DE DESCARTAR.
    --
    -- Un renglón en cero no se pidió, no se descartó, no tiene firma de
    -- descarte y sigue contando como trabajo por atender: dice tres cosas a la
    -- vez y ninguna es verdad. El glosario ya tiene el estado para eso
    -- -'descartado', "una persona decidió no pedirlo"- y viene con su quién y
    -- su cuándo, que es justo lo que el conteo del ADR 0002 va a mirar después
    -- de un mes. Un cero encubriría ese descarte y lo dejaría fuera del conteo.
    --
    -- Nótese la asimetría con `ck_renglon_cantidad`, que sí admite el cero en
    -- `cantidad_propuesta`: ahí el cero lo escribe el sistema y significa "de
    -- esto no se vendió nada", un hecho aritmético sin nadie detrás. Aquí lo
    -- escribiría una persona, y una persona que no quiere pedir algo tiene un
    -- botón para decirlo.
    --
    -- Esta restricción es la GARANTÍA; las otras dos comprobaciones del mismo
    -- cero -`revisar_el_renglon` en Python y el `if` de la ruta- explican y
    -- protegen al doble, pero solo ésta sigue puesta el día que alguien escriba
    -- en la tabla desde un psql o desde un módulo que todavía no existe.
    CONSTRAINT ck_renglon_cantidad_final
        CHECK (cantidad_final >= 1),

    -- La firma vacía no existe, igual que en el descarte y por lo mismo.
    CONSTRAINT ck_renglon_ajustada_por
        CHECK (ajustada_por <> ''),

    -- Cantidad corregida si y solo si hay firma Y hora, el mismo par que
    -- `ck_renglon_descarte` y `ck_pedido_sugerido_cierre`.
    --
    -- Sin la mitad de ida, una cantidad podría quedar cambiada sin decir quién
    -- ni cuándo, y la pregunta "¿por qué pediste diez de algo de lo que se
    -- vendieron tres?" no tendría a quién hacérsele. Sin la de vuelta, una
    -- firma podría quedar colgada en un renglón que nadie tocó y diría que
    -- alguien corrigió lo que no.
    --
    -- Y el NULL de `cantidad_final` no es un descuido: es "nadie la tocó".
    -- Copiar ahí la propuesta al nacer haría indistinguible un renglón que
    -- nadie revisó de uno que alguien confirmó igual -y el segundo es la
    -- evidencia de que la reposición 1 a 1 acertó-.
    CONSTRAINT ck_renglon_ajuste
        CHECK ((cantidad_final IS NOT NULL)
               = (ajustada_por IS NOT NULL AND ajustada_en IS NOT NULL)),

    -- La clave de proveedor vacía no existe, por la misma razón que la clave
    -- del producto y las dos firmas: una cadena vacía se compara igual que un
    -- dato y empareja con cualquier otra vacía.
    CONSTRAINT ck_renglon_proveedor_elegido
        CHECK (proveedor_elegido <> ''),

    CONSTRAINT ck_renglon_elegido_por
        CHECK (elegido_por <> ''),

    -- Proveedor elegido si y solo si hay firma Y hora, el mismo par que
    -- `ck_renglon_descarte` y `ck_renglon_ajuste`.
    --
    -- AQUÍ SOLO SE GUARDA LO QUE UNA PERSONA DECIDIÓ, y ésa es la decisión del
    -- ticket 20. **No hay columna para lo que el sistema sugiere**, y no es un
    -- olvido: la sugerencia -el más barato con existencia- se recalcula de
    -- `comparacion.elegir_ganador`, que es una función pura sobre
    -- `precio_de_proveedor`, que SOLO CRECE (ADR 0004). Guardarla sería una
    -- segunda copia del mismo hecho, y una que además envejece sin avisar: si a
    -- las 8 la sugerencia era NADRO y a las 9 llega un LEVIC más barato, la
    -- columna seguiría diciendo NADRO y nadie podría distinguir esa cifra vieja
    -- de una decisión que alguien tomó.
    --
    -- Se aparta A PROPÓSITO del ticket 11, que sí guarda las dos cifras:
    -- `cantidad_propuesta` NO se puede recalcular -- sale de las ventas de una
    -- ventana que ya pasó, con un catálogo que ya cambió-- y por eso se
    -- congela. La forma es la misma -- columna nullable, sin DEFAULT, con su
    -- firma pareada--; lo que cambia es de cuál de las dos cifras se guarda.
    --
    -- Sin la mitad de ida, una elección quedaría sin decir quién ni cuándo, y
    -- la pregunta "¿por qué le compraste a LEVIC habiendo NADRO más barato?"
    -- -- que es la pregunta entera de este ticket-- no tendría a quién
    -- hacérsele. Sin la de vuelta, una firma colgada diría que alguien eligió
    -- lo que nadie eligió.
    CONSTRAINT ck_renglon_eleccion
        CHECK ((proveedor_elegido IS NOT NULL)
               = (elegido_por IS NOT NULL AND elegido_en IS NOT NULL)),

    -- LA MARCA DE CAPTURA (ticket 22, ADR 0010): una persona dice que ya
    -- tecleó este renglón en el portal del proveedor de su pedido. Es el
    -- avance de la pantalla de captura, y vive AQUÍ y no en el navegador: con
    -- `localStorage` dos pestañas divergen en silencio, cambiar de máquina a la
    -- mitad lo pierde entero, y la marca que lleva a enviar no diría quién la
    -- puso.
    --
    -- NO ES UN ESTADO, y es a propósito. Un renglón dentro de un borrador sigue
    -- 'abierto' (ticket 20), y cuatro sentencias -- asignar, soltar, descartar
    -- y ajustar-- llevan `estado = 'abierto'` en su WHERE: un estado nuevo las
    -- dejaría saltárselo en silencio.
    --
    -- Pareada como las otras cuatro firmas del esquema, pero contra NADA más:
    -- tachar no depende del estado, así que el CHECK solo dice "quién y cuándo
    -- van juntos".
    CONSTRAINT ck_renglon_capturado_por
        CHECK (capturado_por <> ''),

    CONSTRAINT ck_renglon_captura
        CHECK ((capturado_por IS NULL) = (capturado_en IS NULL)),

    -- LA CANCELACIÓN (ticket 25, ADR 0013): se dejó de esperar sin llegar.
    -- Pareada contra el estado como el descarte: un `cancelado` sin quién ni
    -- cuándo sería mercancía que se vuelve a proponer entera sin nadie a quien
    -- preguntarle por qué; una firma suelta diría que alguien soltó lo que
    -- sigue en camino.
    CONSTRAINT ck_renglon_cancelado_por
        CHECK (cancelado_por <> ''),

    CONSTRAINT ck_renglon_cancelacion
        CHECK ((estado = 'cancelado')
               = (cancelado_por IS NOT NULL AND cancelado_en IS NOT NULL)),

    -- LA RECEPCIÓN (ticket 26, ADR 0014). Recibido -completo o parcial- si y
    -- solo si hay firma y hora: es el juicio de una persona sobre una
    -- evidencia, y sin firma no hay a quién preguntarle cuando falte
    -- mercancía. Las compras solo en lo recibido y nunca una lista vacía; NULL
    -- en lo recibido es el marcado a mano del ticket 27.
    CONSTRAINT ck_renglon_recibido_por
        CHECK (recibido_por <> ''),

    CONSTRAINT ck_renglon_recepcion
        CHECK ((estado IN ('recibido', 'recibido parcial'))
               = (recibido_por IS NOT NULL AND recibido_en IS NOT NULL)),

    CONSTRAINT ck_renglon_compras_de_la_recepcion
        CHECK (recibido_con_compras IS NULL
               OR (estado IN ('recibido', 'recibido parcial')
                   AND cardinality(recibido_con_compras) >= 1)),

    -- LO RECHAZADO: las tres juntas o ninguna, la lista nunca vacía, y SIN
    -- relación con el estado -un renglón que rechazó una compra y después se
    -- recibió con otra conserva su rechazo-.
    CONSTRAINT ck_renglon_rechazo_por
        CHECK (recepcion_rechazada_por <> ''),

    CONSTRAINT ck_renglon_rechazo
        CHECK ((compras_rechazadas IS NULL) = (recepcion_rechazada_por IS NULL)
               AND (compras_rechazadas IS NULL) = (recepcion_rechazada_en IS NULL)
               AND (compras_rechazadas IS NULL
                    OR cardinality(compras_rechazadas) >= 1)),

    CONSTRAINT fk_renglon_sugerido
        FOREIGN KEY (pedido_sugerido_id, negocio)
        REFERENCES pedidos.pedido_sugerido (pedido_sugerido_id, negocio),

    -- "UN RENGLÓN PERTENECE A UN SOLO PEDIDO", defendido en la tabla y no en el
    -- código: es UNA columna con UNA llave foránea, no una tabla de cruce. Un
    -- `SET pedido_id = ...` no puede dejarlo en dos sitios, así que moverlo de
    -- pedido es exactamente eso y no "agregarlo a otro".
    --
    -- DESDE EL TICKET 20 LLEVA TAMBIÉN `pedido_sugerido_id`, y eso es lo que le
    -- faltaba. Con la pareja `(pedido_id, negocio)` de antes, un renglón de la
    -- lista del martes podía colgar de un pedido de la del lunes: la
    -- restricción se cumplía y el total de ese pedido contaba mercancía de otro
    -- día, sin un solo error que ver. Apunta a `ux_pedido_de_la_lista`.
    --
    -- Como `pedido_id` es nullable y la coincidencia por omisión es MATCH
    -- SIMPLE, la restricción no se revisa mientras el renglón no tenga pedido
    -- -- que es justo lo que queremos: un renglón nace sin pedido.
    CONSTRAINT fk_renglon_pedido
        FOREIGN KEY (pedido_id, pedido_sugerido_id, negocio)
        REFERENCES pedidos.pedido (pedido_id, pedido_sugerido_id, negocio)
);

COMMENT ON TABLE pedidos.renglon IS
    'Un producto con su cantidad dentro de un pedido sugerido. Los números '
    'viajan CONGELADOS: son los del momento en que se propuso.';

-- LO CONGELADO ES EL PUNTO DE ESTAS CUATRO COLUMNAS. `existencia`,
-- `dias_de_cobertura`, `piezas_vendidas` y `clasificacion` se guardan CON el
-- renglón y no se resuelven con un join contra `dim_producto` al leerlo:
-- resolverlo al leer sería reescribir la historia -- diría lo que hay hoy, no
-- lo que se vio al proponerlo -- y la pantalla podría mostrar un número
-- distinto del que se usó para ordenar la lista. Es la misma razón por la que
-- las Órdenes de Doyle guardan el costo congelado, y lo dejó dicho el ticket
-- 04 en el docstring de `sugerido.Renglon`.
--
-- `numeric` y no `double precision` aunque no sean dinero: `piezas_vendidas`
-- viene de `fct_ventas.cantidad`, que no siempre es entera (5 artículos con
-- granel = 1, medido sobre el respaldo del 2026-07-27), y en coma flotante
-- 1.1 + 2.2 + 0.7 da 4.000000000000001 -- que redondeado hacia arriba propone
-- 5 piezas de algo de lo que salieron 4. Los 3 decimales son los mismos de
-- `sugerido._DECIMALES_DE_GRANEL`.
COMMENT ON COLUMN pedidos.renglon.piezas_vendidas IS
    'Piezas que salieron, con 3 decimales para el granel. Se conserva al lado '
    'de cantidad_propuesta para que la propuesta se pueda verificar.';

-- Sin CHECK de no-negativa a propósito: SICAR permite existencia negativa
-- cuando se vendió más de lo que el inventario decía, y ese caso es real.
-- Cuenta como agotado, no como dato malo.
COMMENT ON COLUMN pedidos.renglon.existencia IS
    'Existencia EN EL MOMENTO EN QUE SE PROPUSO. NULL = no se sabe (producto '
    'fuera del catálogo), nunca cero: un cero lo mandaría a lo más urgente '
    'mintiendo. Puede ser negativa, y eso es agotado.';

-- Un decimal, los mismos de `sugerido._DECIMALES_DE_COBERTURA`: "2.7 días" y
-- "2.68 días" llevan a la misma decisión y el segundo aparenta una precisión
-- que el dato no tiene.
COMMENT ON COLUMN pedidos.renglon.dias_de_cobertura IS
    'Días que duraría la existencia al ritmo medido, congelado. NULL = no se '
    'sabe (sin catálogo, o sin ventas en la ventana del ritmo), NUNCA cero: '
    'cero se leería "agotado" justo cuando es lo contrario.';

COMMENT ON COLUMN pedidos.renglon.estado IS
    'abierto | en tránsito | recibido | recibido parcial | descartado | '
    'cancelado. Con acento en "en tránsito": el glosario de CONTEXT.md manda '
    'sobre el nombre de cualquier cosa.';

COMMENT ON COLUMN pedidos.renglon.pedido_id IS
    'A qué proveedor se le pidió. NULL mientras nadie lo haya repartido.';

-- FIRMA, NO PERMISO (regla 3 de CLAUDE.md). El correo llega en
-- `Cf-Access-Authenticated-User-Email`, ya validado por Cloudflare Access, y
-- sirve para saber quién hizo qué -- nunca para decidir si puede hacerlo. Hoy,
-- corriendo en la torre sin el túnel delante, vale 'sin-identificar', y eso es
-- un dato honesto: dice que no se supo. Lo que no puede pasar es que no se
-- guarde nada.
COMMENT ON COLUMN pedidos.renglon.descartado_por IS
    'Quién descartó el renglón, según Cf-Access-Authenticated-User-Email. Es '
    'una FIRMA, no un permiso. NULL en todo renglón que no esté descartado.';

-- `timestamptz` y no `date`, y esto no contradice "todo se ancla en
-- max(fecha)": esa regla es sobre FECHAS DE VENTA, que salen del almacén. Esto
-- es un INSTANTE que ocurrió AQUÍ -- justo lo que el reloj del servidor sabe y
-- el almacén no-, igual que `armado_en` y `cerrado_en`. Con zona porque el
-- contenedor corre en UTC.
--
-- Es lo que vuelve medible la condición de revisión del ADR 0002: "después de
-- un mes de uso" es `descartado_en >= <inicio> AND descartado_en < <fin>`, y
-- sin esta columna esa condición no se puede evaluar aunque se cumpla.
COMMENT ON COLUMN pedidos.renglon.descartado_en IS
    'Cuándo se descartó, instante con zona. NULL en todo renglón que no esté '
    'descartado. Es lo que hace medible la condición de revisión del ADR 0002.';

-- DOS CANTIDADES Y NO UNA, y ésa es la decisión del ticket 11.
-- `cantidad_propuesta` es lo que el sistema propuso por reposición 1 a 1 y
-- **es inmutable**: se escribe en el INSERT que arma la lista y ninguna
-- sentencia la vuelve a nombrar en un SET. `cantidad_final` es lo que una
-- persona decidió pedir.
--
-- La diferencia entre las dos es lo único que después va a decir si la
-- reposición 1 a 1 está bien calibrada -"se vendieron tres y pidieron diez" es
-- la señal de que la regla se queda corta, y la condición de revisión del ADR
-- 0002 vive de datos así-. Una sola columna sobreescribible se vería idéntica
-- en la pantalla y dejaría esa diferencia en cero para siempre, sin un solo
-- error que ver: exactamente la falla silenciosa que la regla 4 prohíbe.
--
-- NULL = nadie la tocó, y no es lo mismo que "alguien la confirmó igual". Por
-- eso no hay DEFAULT que copie la propuesta: con las dos iguales desde el
-- nacimiento, el renglón que alguien revisó y el que nadie miró se verían
-- idénticos, y el primero es evidencia de que la propuesta acertó.
COMMENT ON COLUMN pedidos.renglon.cantidad_final IS
    'Lo que una persona decidió pedir, cuando corrigió la propuesta. NULL = '
    'nadie la tocó, nunca la propuesta copiada. Al menos 1: un cero no es una '
    'forma de descartar.';

-- FIRMA, NO PERMISO (regla 3 de CLAUDE.md), igual que `descartado_por`. Sirve
-- para saber a quién preguntarle por qué se pidieron diez de algo de lo que se
-- vendieron tres. Hoy, sin el túnel delante, vale 'sin-identificar', que es un
-- dato honesto: dice que no se supo.
COMMENT ON COLUMN pedidos.renglon.ajustada_por IS
    'Quién cambió la cantidad, según Cf-Access-Authenticated-User-Email. Es '
    'una FIRMA, no un permiso. NULL si nadie la cambió.';

-- `timestamptz` por la misma razón que `descartado_en`: es un INSTANTE que
-- ocurrió aquí, no una fecha de venta. Sin él, dos correcciones seguidas no se
-- podrían ordenar y no habría forma de saber cuál quedó.
COMMENT ON COLUMN pedidos.renglon.ajustada_en IS
    'Cuándo se cambió la cantidad, instante con zona. NULL si nadie la cambió.';

-- A QUIÉN DECIDIÓ UNA PERSONA PEDÍRSELO (ticket 20). La clave de Doyle, la
-- misma de `precio_de_proveedor.proveedor` y la misma que acaba en
-- `pedido.proveedor`: una sola identidad de proveedor en todo el esquema.
--
-- NULL = nadie eligió, y entonces manda la sugerencia del sistema, que se
-- calcula al leer y no se guarda. Ver el porqué en `ck_renglon_eleccion`.
COMMENT ON COLUMN pedidos.renglon.proveedor_elegido IS
    'A quién decidió una PERSONA pedírselo, con la clave de Doyle. NULL = '
    'nadie eligió; lo que el sistema sugiere no se guarda, se recalcula.';

-- FIRMA, NO PERMISO (regla 3 de CLAUDE.md), igual que `descartado_por` y
-- `ajustada_por`. Sirve para saber a quién preguntarle por qué se le compró a
-- LEVIC habiendo NADRO más barato -- que es una pregunta legítima con una
-- respuesta legítima: mínimo de pedido, días de entrega, crédito.
COMMENT ON COLUMN pedidos.renglon.elegido_por IS
    'Quién eligió el proveedor, según Cf-Access-Authenticated-User-Email. Es '
    'una FIRMA, no un permiso. NULL si nadie eligió.';

COMMENT ON COLUMN pedidos.renglon.elegido_en IS
    'Cuándo se eligió, instante con zona. NULL si nadie eligió.';

-- FIRMA, NO PERMISO, igual que las otras cuatro. Es la palabra de una persona
-- sobre lo que tecleó en un portal que Continental no ve (ADR 0010).
COMMENT ON COLUMN pedidos.renglon.capturado_por IS
    'Quién dijo haberlo tecleado ya en el portal del proveedor de su pedido, '
    'según Cf-Access-Authenticated-User-Email. Es una FIRMA, no un permiso. '
    'NULL = nadie lo ha tachado. No es un estado: el renglón sigue abierto.';

COMMENT ON COLUMN pedidos.renglon.capturado_en IS
    'Cuándo lo dijo, instante con zona. NULL = nadie lo ha tachado.';

-- LA VENTANA PROPIA DEL RENGLÓN QUE VUELVE (ticket 24, ADR 0012). Lo que se
-- vendió mientras un producto venía en camino no se pierde: al recibirlo, la
-- siguiente lista lo cuenta desde el día siguiente al que repuso su pedido. El
-- renglón lo dice aquí para que "se vendieron tres, se piden tres" se pueda
-- seguir verificando mirando la pantalla.
COMMENT ON COLUMN pedidos.renglon.ventas_desde IS
    'Desde qué día se sumaron las ventas de este renglón cuando no es el '
    'principio de la ventana de su lista: el producto venía en camino y ya '
    'llegó (ADR 0012). NULL = desde ventas_consideradas_desde de su lista.';

COMMENT ON COLUMN pedidos.renglon.cancelado_por IS
    'Quién lo dejó de esperar: canceló su pedido, o lo devolvió a la lista por '
    'atrasado (ADR 0013). Es una FIRMA, no un permiso. NULL si no está '
    'cancelado.';

COMMENT ON COLUMN pedidos.renglon.cancelado_en IS
    'Cuándo, instante con zona. NULL si no está cancelado.';

COMMENT ON COLUMN pedidos.renglon.recibido_por IS
    'Quién confirmó que llegó: juzgó la evidencia que la pantalla le enseñó '
    '(ADR 0014). Es una FIRMA, no un permiso. NULL si no está recibido.';

COMMENT ON COLUMN pedidos.renglon.recibido_en IS
    'Cuándo lo confirmó, instante con zona. NULL si no está recibido.';

COMMENT ON COLUMN pedidos.renglon.recibido_con_compras IS
    'Los compra_id de marts.fct_compras que sostienen la recepción (nunca el '
    'folio, de semántica no verificada). Una compra confirma un solo renglón. '
    'NULL si no está recibido, o si se recibió a mano sin compra (ticket 27).';

COMMENT ON COLUMN pedidos.renglon.compras_rechazadas IS
    'Los compra_id que una persona dijo que NO son este renglón: ya no se le '
    'proponen. El renglón sigue en tránsito; rechazar no es un estado.';

COMMENT ON COLUMN pedidos.renglon.recepcion_rechazada_por IS
    'Quién rechazó la última propuesta. Es una FIRMA, no un permiso.';

COMMENT ON COLUMN pedidos.renglon.recepcion_rechazada_en IS
    'Cuándo, instante con zona.';


-- --------------------------------------------------------------------------
-- 4) El precio de un proveedor: lo que contestó, congelado, con su instante.
-- --------------------------------------------------------------------------
--
-- Va después de `renglon` porque le apunta con una llave foránea.
--
-- ## Por qué una tabla y no columnas en `renglon`
--
-- El spec del módulo decía que el renglón guardaría "los precios leídos por
-- proveedor con su momento de lectura", y en columnas eso son cuatro
-- proveedores por nueve datos: treinta y seis columnas cuyo nombre lleva
-- dentro el nombre de un proveedor. El día que entre un quinto -o que
-- QuePharma salga, que el ADR 0002 ya da por probable- hay que alterar la
-- tabla, y el rol no puede (ADR 0003). Peor: "contra cuántos proveedores se
-- comparó este renglón", que es lo que el ticket 15 tiene que contar, se
-- volvería un CASE de nueve columnas en vez de un count(*).
--
-- El grano es (renglón, proveedor) porque eso es lo que se lee de una vez: una
-- visita a un portal con una clave devuelve el precio y la existencia de ese
-- producto en ese proveedor. Una fila por hecho.
--
-- ## ESTA TABLA SOLO CRECE, Y ES LA DECISIÓN DEL TICKET
--
-- Una segunda consulta del mismo renglón AGREGA filas; no pisa las anteriores.
-- No hay UNIQUE sobre (renglón, proveedor) a propósito y no hay un solo UPDATE
-- en el código que la toque. Tres razones, de la que más duele hacia abajo:
--
--   1. CON UPDATE, UNA CONSULTA FALLIDA BORRARÍA UN PRECIO BUENO. Se consulta
--      a las 8 y NADRO da $86.05; a las 9 alguien vuelve a consultar, la
--      sesión ya caducó, y el $86.05 se convierte en un hueco. Se habría
--      perdido el dato POR INTENTAR MEJORARLO, sin un solo error que ver.
--   2. "Un pedido dice a qué precio se decidió, no a cómo está hoy" (ticket
--      12). Con una sola fila por proveedor, la cifra que el encargado vio
--      cuando eligió NADRO desaparece en cuanto alguien recarga los precios, y
--      el pedido deja de poder explicarse.
--   3. El rol no tiene DELETE (ADR 0003) y la zona de datos de la casa es
--      append-only por convención. Una tabla que solo crece se audita.
--
-- Lo que cuesta, dicho: cuatro filas por renglón consultado, del orden de
-- cientos al día en el peor caso, contra una base que hoy guarda ~460 mil
-- filas en total. Cuando estorbe, se archiva junto con el pedido sugerido que
-- la originó, que es la unidad con la que se puede tirar sin perder el porqué.
--
-- Quién decide cuál vale hoy es el DISTINCT ON (renglon_id, proveedor) de
-- `almacenamiento._LEER_PRECIOS`, ordenado por consultado_en DESC.

CREATE TABLE IF NOT EXISTS pedidos.precio_de_proveedor (
    precio_de_proveedor_id    bigint        GENERATED ALWAYS AS IDENTITY,
    negocio                   text          NOT NULL,
    renglon_id                bigint        NOT NULL,
    proveedor                 text          NOT NULL,
    consultado_en             timestamptz   NOT NULL DEFAULT now(),
    precio_como_llego         text,
    precio                    numeric(12,2),
    existencia_como_llego     text,
    existencia                numeric(12,3),
    motivo                    text,
    detalle                   text,
    clave_del_proveedor       text,
    descripcion_del_proveedor text,
    resultados                integer       NOT NULL DEFAULT 0,

    CONSTRAINT pk_precio_de_proveedor
        PRIMARY KEY (precio_de_proveedor_id),

    CONSTRAINT ck_precio_negocio
        CHECK (negocio <> ''),

    -- Sin saber quién dio el precio, el precio no sirve para nada.
    CONSTRAINT ck_precio_proveedor
        CHECK (proveedor <> ''),

    -- EL CERO ES EL ÚNICO NÚMERO QUE AQUÍ PUEDE HACER DAÑO. Un precio en cero
    -- gana toda comparación de "el más barato" y dispara la compra
    -- equivocada: es exactamente la regla 4 de CLAUDE.md -"un precio que no se
    -- pudo leer es sin dato, jamás un cero ni un más caro"-. Un portal que
    -- escribe "0.00" tampoco está regalando nada: es un portal que no supo
    -- decir cuánto cuesta.
    --
    -- Es la SEGUNDA puerta para el mismo cero: `precios.precio_a_numero` ya
    -- devuelve NULL para él. Ésta es la que sigue puesta el día que alguien
    -- escriba en la tabla desde un psql o desde un módulo que todavía no
    -- existe.
    CONSTRAINT ck_precio_positivo
        CHECK (precio > 0),

    -- Un proveedor no tiene menos que cero. La existencia negativa sí ocurre
    -- en `renglon.existencia` -SICAR la permite cuando se vendió más de lo que
    -- el inventario decía- y eso es lo NUESTRO; esto es lo que reporta el
    -- portal de otro.
    --
    -- (Al redactar dentro de un CREATE TABLE de este archivo: los nombres de
    -- los tipos de coma flotante no se escriben ni en un comentario.
    -- `test_el_dinero_no_es_coma_flotante` los busca en el CUERPO entero, y es
    -- a propósito: un tipo prohibido escondido en una línea comentada está a
    -- un `git revert` de ser una columna.)
    CONSTRAINT ck_precio_existencia
        CHECK (existencia >= 0),

    CONSTRAINT ck_precio_resultados
        CHECK (resultados >= 0),

    -- UN PRECIO FALTANTE NO ES UN NULL MUDO. "NADRO no dio precio" quiere
    -- decir cinco cosas distintas y cada una se arregla de otra manera: si la
    -- sesión caducó el encargado la abre en dos clics; si el portal no
    -- contestó se reintenta; si el producto no está en ese catálogo no hay
    -- nada que hacer. Sin el motivo las cinco se ven iguales y ninguna se
    -- puede atender (historia 23 del spec, segunda casilla del ticket 15).
    --
    -- Las dos mitades hacen falta. Sin la de ida, un NULL podría quedarse
    -- callado; sin la de vuelta, un motivo podría quedar colgado en una
    -- lectura que sí trajo precio y el conteo del ticket 15 contaría huecos
    -- que no existen.
    CONSTRAINT ck_precio_sin_dato
        CHECK ((precio IS NULL) = (motivo IS NOT NULL)),

    -- El vocabulario cerrado de `precios.MOTIVOS`, con el mismo texto exacto.
    -- Cerrado y no texto libre porque el ticket 15 tiene que CONTAR los huecos
    -- por motivo, y un conteo sobre texto libre cuenta faltas de ortografía.
    --
    -- `no empareja` lo escribe el emparejamiento por EAN (ticket 13), y es el
    -- final ordinario de QuePharma, que usa código interno. Estaba en esta
    -- lista desde el ticket 12, un día antes de que nadie lo escribiera, y eso
    -- ahorró lo que costaba agregarlo después: una migración del CHECK y una
    -- visita a atlas con credenciales de dueño (ADR 0003).
    --
    -- LOS ACENTOS DE ESTOS OCHO TEXTOS VIAJAN DENTRO DEL CHECK, igual que el
    -- de 'en tránsito' en `ck_renglon_estado`: si psql manda este archivo como
    -- latin1, el primer INSERT con motivo rebota con una violación de
    -- restricción que nadie sabría explicar. Ver el SET client_encoding de la
    -- cabecera y la comprobación 15 de verificar_rol.sql.
    CONSTRAINT ck_precio_motivo_conocido
        CHECK (motivo IS NULL OR motivo IN (
            'sin resultados', 'varios resultados', 'no empareja',
            'el portal no contestó', 'la sesión caducó',
            'no se sabe leer la página', 'no alcanzó el tiempo',
            'precio ilegible')),

    -- EL TEXTO ORIGINAL ES LA AUDITORÍA DE LA CONVERSIÓN. El portal escribe
    -- "1,234.50" y aquí se guarda 1234.50; si solo sobreviviera el número, la
    -- pregunta "¿de dónde salió este 1234.50?" no tendría respuesta seis meses
    -- después. Un precio sin su texto es un número sin procedencia.
    CONSTRAINT ck_precio_con_su_texto
        CHECK (precio IS NULL OR precio_como_llego IS NOT NULL),

    -- La cadena vacía no existe en ninguna columna de texto, por la misma
    -- razón que `ck_renglon_clave`: una cadena vacía se compara igual que un
    -- dato y empareja con cualquier otra vacía. O hay texto o no se sabe.
    -- `columnas_del_precio` hace la traducción del lado de Python.
    CONSTRAINT ck_precio_textos
        CHECK (precio_como_llego <> ''
               AND existencia_como_llego <> ''
               AND detalle <> ''
               AND clave_del_proveedor <> ''
               AND descripcion_del_proveedor <> ''),

    -- Compuesta con `negocio`, igual que las otras dos llaves foráneas de este
    -- esquema: con ella, un precio de farmacia_01 no puede colgar de un
    -- renglón de otro negocio (regla 7 de CLAUDE.md).
    CONSTRAINT fk_precio_renglon
        FOREIGN KEY (renglon_id, negocio)
        REFERENCES pedidos.renglon (renglon_id, negocio)
);

COMMENT ON TABLE pedidos.precio_de_proveedor IS
    'Lo que un proveedor contestó de un renglón, CONGELADO, con el instante de '
    'la lectura. SOLO CRECE: una segunda consulta agrega filas y la '
    'comparación usa la más reciente por proveedor.';

COMMENT ON COLUMN pedidos.precio_de_proveedor.proveedor IS
    'La clave de Doyle: nadro, levic, vicma, quepharma (config/proveedores.yml '
    'de ese repo). Se guarda la clave y no el nombre porque la clave es lo que '
    'no cambia; cómo se escribe cada una vive en precios.NOMBRES_DE_PROVEEDOR.';

-- EL INSTANTE ES LO QUE VUELVE CONGELADA A UNA CIFRA. Sin él, "$86.05 en
-- NADRO" no dice si se leyó hace una hora o hace tres semanas, y la tercera
-- casilla del ticket 12 es literalmente eso: un pedido dice a qué precio se
-- decidió, no a cómo está hoy.
--
-- `now()` como DEFAULT y no una hora calculada en Python, por la misma razón
-- que `armado_en`, `cerrado_en` y `descartado_en`: la pone el servidor que
-- guarda la fila, así que dos procesos con relojes distintos no dejan lecturas
-- incomparables. Y trae de regalo justo lo que hace falta: now() es la hora de
-- la TRANSACCIÓN, así que los cuatro proveedores de una misma consulta quedan
-- con el mismo instante -fue una sola lectura- y dos consultas distintas nunca
-- lo comparten.
--
-- `timestamptz` y no `timestamp`: el contenedor corre en UTC, y un `timestamp`
-- sin zona guardaría un reloj de pared que alguien en México lee seis horas en
-- el futuro. Esto NO contradice "todo se ancla en max(fecha)": esa regla es
-- sobre FECHAS DE VENTA; esto es un instante que ocurrió aquí.
COMMENT ON COLUMN pedidos.precio_de_proveedor.consultado_en IS
    'Cuándo se leyó este precio, instante con zona. Los cuatro proveedores de '
    'una misma consulta lo comparten: fue una sola lectura.';

-- DECIMAL EXPLÍCITO, NUNCA COMA FLOTANTE, igual que `pedido.total_sin_iva` y
-- por la misma lección medida en farmacia-data: dejar que una librería DEDUZCA
-- el tipo terminó metiendo dinero en `double precision`, donde 0.1 + 0.2 no es
-- 0.3 y un total deja de cuadrar contra la factura por centavos que nadie
-- puede explicar.
--
-- SIN IVA, como todo costo nuestro: el de mostrador lleva IVA y restarlos
-- directo es el error con el que Marlowe puso la flecha al revés.
--
-- NULL = no se sabe, JAMÁS cero. El cero está prohibido por
-- `ck_precio_positivo` y el porqué está ahí arriba.
COMMENT ON COLUMN pedidos.precio_de_proveedor.precio IS
    'Precio de COMPRA, sin IVA, decimal explícito. NULL = sin dato, y entonces '
    'motivo dice por qué. Nunca cero.';

-- La conversión ocurre en Python (`precios.precio_a_numero`) y NO en el SQL
-- con un ::numeric, y la diferencia es concreta: '1,234.50'::numeric TRUENA, y
-- un error de conversión aborta la transacción entera -se perderían también
-- los tres proveedores que sí contestaron bien-. En Python, un texto que no se
-- puede leer es una fila más con `precio ilegible` de motivo, que es
-- información.
COMMENT ON COLUMN pedidos.precio_de_proveedor.precio_como_llego IS
    'El precio TAL CUAL lo escribió el portal ("1,234.50", a veces con $). Es '
    'lo único que permite auditar una conversión dudosa meses después.';

COMMENT ON COLUMN pedidos.precio_de_proveedor.existencia_como_llego IS
    'La existencia tal cual la escribió el portal. Los portales dicen "40", '
    '"+100" o "Disponible", y el texto vale cuando el número no: que la '
    'existencia no se pueda convertir NUNCA es motivo para tirar el precio.';

COMMENT ON COLUMN pedidos.precio_de_proveedor.motivo IS
    'Por qué NO hay precio, del vocabulario de precios.MOTIVOS. NULL cuando sí '
    'lo hay. Cada motivo lleva a una acción distinta: la sesión caducada la '
    'arregla el encargado en dos clics, "sin resultados" no la arregla nadie.';

COMMENT ON COLUMN pedidos.precio_de_proveedor.detalle IS
    'Lo que Doyle dijo, primera línea y acotado. Es un mensaje que Doyle '
    'redacta PARA QUE UNA PERSONA LO LEA (historia 23); lo que nunca viaja al '
    'navegador es el texto de una excepción nuestra (regla 5 de CLAUDE.md).';

-- CUÁNTAS ENCONTRÓ EL PORTAL, no cuántas trajo Doyle (que corta en 20). La
-- diferencia decide: el ticket 13 acepta VICMA "únicamente si la búsqueda del
-- EAN devuelve exactamente un resultado", y ESTE es el número que se compara
-- contra 1 -con len(filas), un portal con 43 resultados diría 20-. Sin esta
-- columna, esa regla tendría que releer el portal mañana -o mentir-.
COMMENT ON COLUMN pedidos.precio_de_proveedor.resultados IS
    'Cuántos resultados encontró el portal para esa clave. Es el número con el '
    'que se decide VICMA: se acepta únicamente con exactamente uno.';

-- LA EVIDENCIA DE QUE SE COMPARÓ EL MISMO PRODUCTO. Es la lección que Marlowe
-- pagó: una caja de 60 más barata por pieza se veía como más cara, sin fallar
-- y sin avisar. Con la descripción del proveedor a la vista, una persona lo
-- caza de un vistazo; sin ella, nadie.
COMMENT ON COLUMN pedidos.precio_de_proveedor.descripcion_del_proveedor IS
    'Cómo describe el portal el producto de esta fila. Evidencia de que se '
    'comparó lo mismo.';


-- --------------------------------------------------------------------------
-- 5) La corrida del lote: cómo le fue al lote nocturno UNA noche.
-- --------------------------------------------------------------------------
--
-- UNA FILA POR CORRIDA. No por renglón y no por proveedor: el ADR 0007 tiene
-- el porqué completo, con las dos opciones descartadas. En corto: la pregunta
-- que la pantalla no podía contestar era "¿corrió el lote sobre esta lista y
-- cómo acabó?", y esa pregunta tiene UNA respuesta por noche. Guardarla cuesta
-- una fila; deducir de ahí el estado de un renglón concreto es una resta que
-- se hace al leer y no cuesta almacenamiento.
--
-- LO QUE SE DESCARTÓ, porque volverá a proponerse: escribir cuatro filas de
-- `precio_de_proveedor` con motivo 'no alcanzó el tiempo' por cada renglón que
-- el tope no alcanzó. Dos razones, y la primera es la que la hunde:
--
--   1. Habría que INVENTARSE a qué proveedores se le iba a preguntar. Esa
--      lista sale del acuse de Doyle, y a un renglón que no se consultó no
--      hubo acuse que darle. Escribir "le preguntamos a NADRO y no contestó a
--      tiempo" cuando a NADRO no se le preguntó es escribir un hecho que no
--      ocurrió, que es lo mismo que prohíbe el cero inventado (regla 4 de
--      CLAUDE.md): un dato falso es peor que un hueco, porque se cuenta, se
--      compara y se cree.
--   2. Dispararía la condición de revisión del ADR 0004: una noche que corte
--      al 20% dejaría ~11,000 filas de puro hueco.
--
-- LO QUE SE RENUNCIA, dicho con todas sus letras: aquí se guarda CUÁNTOS
-- renglones quedaron sin alcanzar, no CUÁLES. Para un renglón sin lectura la
-- frase se deduce del `final` de la corrida, y hay una noche en la que la
-- deducción no es segura: aquella en la que el tope cortó Y ADEMÁS hubo
-- renglones `no_se_pudo` -Doyle caído a media corrida-. Ahí
-- `faltantes.por_que_no_hay_lectura` devuelve `seguro=False` y la pantalla
-- escribe "probablemente" con el otro número al lado.
--
-- ESTA TABLA SOLO CRECE, igual que el precio congelado: una corrida es un
-- hecho del pasado y la de anoche no se corrige porque hoy haya otra. El
-- código no tiene un solo UPDATE sobre ella. Lo que cuesta: cinco filas por
-- semana -el timer es `OnCalendar=Mon-Fri 22:00`, sin `Persistent=true`-,
-- con una decena de columnas de enteros. La tabla del precio crece ~4xN por
-- noche; ésta crece 1.
--
-- Y NO SUSTITUYE AL JOURNAL. `journalctl -u continental-lote` sigue siendo la
-- bitácora del relato: tiene el renglón por renglón y -esto es lo que la tabla
-- no puede- deja rastro aunque Postgres sea justo lo que se cayó. Una corrida
-- que muere sin poder escribir aquí no deja fila, y la pantalla la ve como "el
-- lote no corrió", que en ese caso dice de menos.

CREATE TABLE IF NOT EXISTS pedidos.corrida_del_lote (
    corrida_del_lote_id bigint        GENERATED ALWAYS AS IDENTITY,
    negocio             text          NOT NULL,
    pedido_sugerido_id  bigint,
    fecha_del_pedido    date,
    termino_en          timestamptz   NOT NULL DEFAULT now(),
    final               text          NOT NULL,
    segundos            numeric(10,1) NOT NULL DEFAULT 0,
    tope_minutos        numeric(10,1) NOT NULL DEFAULT 0,
    en_la_lista         integer       NOT NULL DEFAULT 0,
    consultados         integer       NOT NULL DEFAULT 0,
    con_precio          integer       NOT NULL DEFAULT 0,
    sin_alcanzar        integer       NOT NULL DEFAULT 0,
    no_se_pudo          integer       NOT NULL DEFAULT 0,
    sin_clave           integer       NOT NULL DEFAULT 0,
    orden_cumplido      boolean       NOT NULL DEFAULT false,
    detalle             text,

    CONSTRAINT pk_corrida_del_lote
        PRIMARY KEY (corrida_del_lote_id),

    CONSTRAINT ck_corrida_negocio
        CHECK (negocio <> ''),

    -- EL VOCABULARIO CERRADO DE `almacenamiento.FINALES_DE_LA_CORRIDA`, con el
    -- mismo texto exacto. Cerrado y no texto libre por la misma razón que los
    -- motivos del precio, y aquí pesa más: LA PANTALLA DECIDE CON ESTE VALOR
    -- qué frase le pone a cada renglón sin lectura. Un quinto valor metido sin
    -- migración no se vería como un error: se leería como "el lote no corrió".
    --
    -- LOS ACENTOS VIAJAN DENTRO DEL CHECK, igual que el de 'en tránsito' y los
    -- ocho motivos del precio: si psql manda este archivo como latin1, el
    -- primer INSERT del lote rebota a las 22:00 con una violación de
    -- restricción que nadie sabría explicar -y el lote es justamente lo que
    -- corre sin nadie mirando-. Ver el SET client_encoding de la cabecera.
    CONSTRAINT ck_corrida_final
        CHECK (final IN (
            'terminó', 'se acabó el tiempo', 'se interrumpió', 'no hubo lista')),

    -- UN CONTEO NEGATIVO NO ES "MENOS QUE NINGUNO", ES UN ERROR DE QUIEN
    -- CONTÓ. Y estos números se pintan en la pantalla como "210 de 380": un
    -- negativo ahí se lee como una pantalla rota, no como un dato.
    CONSTRAINT ck_corrida_conteos
        CHECK (en_la_lista  >= 0 AND consultados  >= 0
           AND con_precio   >= 0 AND sin_alcanzar >= 0
           AND no_se_pudo   >= 0 AND sin_clave    >= 0),

    CONSTRAINT ck_corrida_duracion
        CHECK (segundos >= 0 AND tope_minutos >= 0),

    -- EL NUMERADOR NO PUEDE SER MAYOR QUE EL DENOMINADOR. Es el par de números
    -- con el que la pantalla escribe "el lote consultó 210 de 380 renglones".
    CONSTRAINT ck_corrida_consultados
        CHECK (consultados <= en_la_lista),

    -- Un precio no llega de un renglón que no se consultó.
    CONSTRAINT ck_corrida_con_precio
        CHECK (con_precio <= consultados),

    -- LA LISTA Y SU FECHA VAN JUNTAS O NO VAN. Las dos son NULL en una corrida
    -- que no llegó a abrir lista -'no hubo lista', o una que se cortó antes-,
    -- y eso es NULO PORQUE NO HUBO, no porque no se sepa. Una corrida con
    -- fecha y sin lista -o al revés- no se puede leer: la pantalla busca por
    -- id y escribiría la fecha de otra noche.
    CONSTRAINT ck_corrida_lista
        CHECK ((pedido_sugerido_id IS NULL) = (fecha_del_pedido IS NULL)),

    -- La cadena vacía no existe en ninguna columna de texto de este esquema,
    -- por la misma razón que en `ck_renglon_clave`: se compara igual que un
    -- dato y empareja con cualquier otra vacía. O hay texto o es NULL.
    CONSTRAINT ck_corrida_detalle
        CHECK (detalle <> ''),

    -- Compuesta con `negocio`, igual que las otras llaves foráneas de este
    -- esquema: una corrida de farmacia_01 no puede colgar de una lista de otro
    -- negocio (regla 7 de CLAUDE.md).
    --
    -- ADMITE NULOS, y eso es lo que la distingue de la del precio: una corrida
    -- sin lista SÍ se guarda -es justo la que contesta "el lote corrió y no
    -- encontró ventas"-. En Postgres una llave foránea compuesta con MATCH
    -- SIMPLE -el de omisión- no se comprueba cuando alguna de sus columnas es
    -- nula, así que esas filas entran sin apuntar a nada.
    CONSTRAINT fk_corrida_lista
        FOREIGN KEY (pedido_sugerido_id, negocio)
        REFERENCES pedidos.pedido_sugerido (pedido_sugerido_id, negocio)
);

COMMENT ON TABLE pedidos.corrida_del_lote IS
    'Cómo le fue al lote nocturno UNA noche: una fila por corrida, no por '
    'renglón. SOLO CRECE. Es de donde la pantalla saca "el lote se cortó por '
    'tiempo antes de llegar a este renglón" (ADR 0007).';

-- El instante lo pone la BASE, igual que `consultado_en` del precio y por lo
-- mismo: lo pone el servidor que guarda la fila, así que dos procesos con
-- relojes distintos no dejan corridas incomparables. `timestamptz` porque el
-- contenedor corre en UTC y un `timestamp` sin zona guardaría un reloj de
-- pared que alguien en México lee seis horas en el futuro.
COMMENT ON COLUMN pedidos.corrida_del_lote.termino_en IS
    'Cuándo acabó la corrida, instante con zona, puesto por la base.';

COMMENT ON COLUMN pedidos.corrida_del_lote.final IS
    'Cómo acabó, del vocabulario de almacenamiento.FINALES_DE_LA_CORRIDA. '
    '"se acabó el tiempo" NO es un error: detenerse al tope es lo que se le '
    'pide al lote. "se interrumpió" sí lo es, y lo que hay que mirar es el '
    'journal de esa noche.';

-- DURACIONES Y NO INSTANTES, y por eso éstas sí vienen de Python: las mide el
-- reloj MONÓTONO del lote, y una duración no la puede medir el que la guarda.
-- En `numeric` como todo número de este esquema -nada de coma flotante, que es
-- lo que la comprobación 13 de verificar_rol.sql vigila-, con un decimal, que
-- es lo que se pinta.
COMMENT ON COLUMN pedidos.corrida_del_lote.segundos IS
    'Cuánto duró la corrida, del reloj monótono del lote. También es el `ping` '
    'del latido a Uptime Kuma: una noche que empiece a tardar el doble se ve '
    'en esa gráfica antes de que nadie mire un journal.';

COMMENT ON COLUMN pedidos.corrida_del_lote.sin_alcanzar IS
    'Cuántos renglones quedaron FALTANTES POR TOPE. Cuántos, no cuáles: ese es '
    'el precio que el ADR 0007 pagó a cambio de una fila en vez de ~2,750.';

COMMENT ON COLUMN pedidos.corrida_del_lote.no_se_pudo IS
    'Cuántos se intentaron y no dejaron ni una fila guardada (Doyle no '
    'contestó al pedir la búsqueda). Mayor que cero es lo que vuelve INSEGURA '
    'la atribución por renglón: hay dos maneras de quedarse sin lectura esa '
    'noche y de un renglón concreto no se puede afirmar cuál le tocó.';

COMMENT ON COLUMN pedidos.corrida_del_lote.orden_cumplido IS
    'Si el recorrido fue en orden de importancia (clase ABC). Falso mientras '
    'marts.dim_producto no tenga la columna clase_abc (ADR 0018 de '
    'farmacia-data): el lote lo dice en vez de disimularlo.';

-- --------------------------------------------------------------------------
-- Índices
-- --------------------------------------------------------------------------
--
-- Solo cuatro, y los cuatro tienen un consumidor concreto. Un índice sin
-- consulta que lo use es trabajo por fila escrita a cambio de nada.

-- "No se vuelve a proponer mientras esté en tránsito, porque eso sería pedirlo
-- dos veces" (CONTEXT.md). Cada vez que se arma una lista hay que preguntar
-- qué productos siguen en tránsito, y ese es un puñado de filas dentro de una
-- tabla que crece un renglón por producto vendido por día. El índice PARCIAL
-- indexa solo ese puñado: los renglones ya recibidos o descartados no ocupan
-- lugar en él.
CREATE INDEX IF NOT EXISTS ix_renglon_en_transito
    ON pedidos.renglon (negocio, producto_id)
 WHERE estado = 'en tránsito';

-- "Los renglones de este pedido", y de paso lo que Postgres recorre al
-- comprobar la llave foránea cuando alguien toca un `pedido`. Sin índice del
-- lado hijo, esa comprobación es un recorrido completo de `renglon`.
CREATE INDEX IF NOT EXISTS ix_renglon_pedido
    ON pedidos.renglon (pedido_id)
 WHERE pedido_id IS NOT NULL;

-- "La lectura más reciente de cada proveedor para estos renglones": es
-- EXACTAMENTE el DISTINCT ON de `almacenamiento._LEER_PRECIOS`, columna por
-- columna y con el mismo DESC. Con él, Postgres recorre el índice y se lleva
-- la primera fila de cada pareja; sin él, ordena la tabla entera cada vez que
-- alguien carga la pantalla.
--
-- Esta tabla SOLO CRECE, así que es la única del esquema donde el índice deja
-- de ser opcional con el tiempo: sin él, el costo de pintar la lista crece con
-- el historial de precios y no con lo que se está mirando.
--
-- `renglon_id` va después de `negocio` y no al revés porque toda consulta
-- lleva las dos, y `negocio` primero deja el índice listo para el día que haya
-- una segunda farmacia (regla 7).
CREATE INDEX IF NOT EXISTS ix_precio_ultimo
    ON pedidos.precio_de_proveedor
       (negocio, renglon_id, proveedor, consultado_en DESC);

-- "La última corrida del lote sobre esta lista": es EXACTAMENTE el `order by`
-- de `almacenamiento._ULTIMA_CORRIDA`, columna por columna y con el mismo
-- DESC. La pantalla lo consulta en CADA carga de la lista, así que es una
-- lectura por carga contra una tabla que solo crece.
--
-- Hoy la tabla tiene cinco filas por semana y un recorrido completo costaría
-- nada; el índice está por la misma razón que el del precio y no por el
-- tamaño de hoy: es la tabla la que crece sin que nadie la pode, y el costo de
-- pintar la lista no debe crecer con el historial de corridas.
--
-- `negocio` primero por la regla 7, igual que en el del precio.
CREATE INDEX IF NOT EXISTS ix_corrida_ultima
    ON pedidos.corrida_del_lote
       (negocio, pedido_sugerido_id, termino_en DESC);


-- --------------------------------------------------------------------------
-- Qué quedó
-- --------------------------------------------------------------------------

SELECT c.relname                   AS tabla,
       pg_get_userbyid(c.relowner) AS propietario,
       (SELECT count(*) FROM pg_attribute a
         WHERE a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped)
                                   AS columnas
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'pedidos' AND c.relkind = 'r'
 ORDER BY c.relname;

\echo ''
\echo '>> Siguiente paso: sql/crear_rol.sql (el rol y sus permisos).'
