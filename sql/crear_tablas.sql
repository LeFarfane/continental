-- DDL de las tres tablas del pedido. Esquema `pedidos`, en el Postgres de
-- farmacia-data.
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
-- Hoy hay una: `sql/migraciones/0001-renglon-quien-descarto-y-cuando.sql`
-- (ticket 10), que agrega `descartado_por` y `descartado_en` a
-- `pedidos.renglon`.
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
    'Lo que Continental escribe: pedido sugerido, renglones y pedidos por '
    'proveedor. Lo posee el dueño del almacén; el rol continental solo tiene '
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
    proveedor_id        bigint        NOT NULL,
    armado_en           timestamptz   NOT NULL DEFAULT now(),
    total_sin_iva       numeric(12,2),

    CONSTRAINT pk_pedido
        PRIMARY KEY (pedido_id),

    -- "Un pedido sugerido puede repartirse en varios pedidos, UNO POR
    -- PROVEEDOR" (CONTEXT.md). Dos pedidos al mismo proveedor desde la misma
    -- lista serían dos veces la misma mercancía.
    CONSTRAINT ux_pedido_proveedor
        UNIQUE (pedido_sugerido_id, proveedor_id),

    CONSTRAINT ux_pedido_negocio
        UNIQUE (pedido_id, negocio),

    CONSTRAINT ck_pedido_negocio
        CHECK (negocio <> ''),

    CONSTRAINT ck_pedido_total
        CHECK (total_sin_iva >= 0),

    CONSTRAINT fk_pedido_sugerido
        FOREIGN KEY (pedido_sugerido_id, negocio)
        REFERENCES pedidos.pedido_sugerido (pedido_sugerido_id, negocio)
);

COMMENT ON TABLE pedidos.pedido IS
    'Lo que se le pide a UN proveedor, nacido de renglones de un pedido '
    'sugerido. Uno por proveedor dentro de la misma lista.';

-- SIN llave foránea contra `marts.dim_proveedor`, y es deliberado: `dbt build`
-- **borra y vuelve a crear** los modelos de `marts` cada noche. Una FK contra
-- una tabla que se recrea o bien impide el DROP -- y entonces la cadena
-- nocturna se cae por culpa de Continental -- o desaparece con ella, que es
-- peor porque nadie se entera. La integridad de este id se sostiene con la
-- lectura de `marts.dim_proveedor` que hace el código, no con una restricción
-- que la cadena de la noche va a borrar.
COMMENT ON COLUMN pedidos.pedido.proveedor_id IS
    'marts.dim_proveedor.proveedor_id (pro_id de SICAR). Sin FK a propósito: '
    'dbt recrea marts en cada corrida y se llevaría la restricción por delante.';

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

    -- Los cinco estados del glosario. 'en tránsito' CON ACENTO: ver la nota de
    -- la cabecera.
    CONSTRAINT ck_renglon_estado
        CHECK (estado IN ('abierto', 'en tránsito', 'recibido',
                          'recibido parcial', 'descartado')),

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

    CONSTRAINT fk_renglon_sugerido
        FOREIGN KEY (pedido_sugerido_id, negocio)
        REFERENCES pedidos.pedido_sugerido (pedido_sugerido_id, negocio),

    -- Compuesta con `negocio` igual que la anterior. Como `pedido_id` es
    -- nullable y la coincidencia por omisión es MATCH SIMPLE, la restricción
    -- no se revisa mientras el renglón no tenga pedido -- que es justo lo que
    -- queremos: un renglón nace sin proveedor.
    CONSTRAINT fk_renglon_pedido
        FOREIGN KEY (pedido_id, negocio)
        REFERENCES pedidos.pedido (pedido_id, negocio)
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
    'abierto | en tránsito | recibido | recibido parcial | descartado. Con '
    'acento en "en tránsito": el glosario de CONTEXT.md manda sobre el nombre '
    'de cualquier cosa.';

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


-- --------------------------------------------------------------------------
-- Índices
-- --------------------------------------------------------------------------
--
-- Solo dos, y los dos tienen un consumidor concreto. Un índice sin consulta
-- que lo use es trabajo por fila escrita a cambio de nada.

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
