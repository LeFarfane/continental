# 0003 — Las tablas del pedido viven en un esquema propio que Continental no posee

**Fecha:** 2026-09-19  ·  **Estado:** aceptada

## Contexto

El módulo de Pedido necesita guardar tres cosas: el **pedido sugerido** (la
lista de un día), el **renglón** (un producto con su cantidad dentro de esa
lista) y el **pedido** (lo que se le pide a un proveedor). El glosario de
`CONTEXT.md` define las tres y sus estados.

Van al mismo Postgres de `farmacia-data` al que Continental ya le lee `marts`:
es el almacén de la casa y montar otra base para tres tablas sería
sobre-ingeniería (regla 5 del `CLAUDE.md` de farmacia-data). Eso obliga a
responder algo que no es obvio: **si Continental escribe en el mismo servidor
del que solo debe leer, ¿qué impide que lea o escriba lo que no es suyo?**

La regla 6 de `CLAUDE.md` ya dice el principio —"solo lectura sobre el almacén,
salvo sus propias tablas… el permiso es la garantía, no la buena intención del
código"— pero no dice dónde viven esas tablas ni quién las posee, y las dos
cosas cambian qué puede hacer el rol.

Tres hechos medidos delimitan el problema:

1. **Recrear una tabla en Postgres borra sus permisos, y cada `dbt build`
   recrea los modelos de `marts`.** Marlowe lo midió el 2026-09-06: otorgó a
   mano, corrió su barrido, y la interfaz se cayó con "permission denied".
2. **El dueño de un esquema tiene `CREATE` sobre él implícitamente**, y el
   dueño de una tabla puede hacerle `ALTER` y `DROP`. Ningún `GRANT` lo dice;
   se hereda de la propiedad.
3. **El almacén no es solo nuestro.** En la misma base viven `raw`, `curado`,
   `staging`, `marts` y la base interna de Metabase. Un permiso de más aquí se
   paga en un repo que ni siquiera es éste.

## Opciones consideradas

1. **Las tablas en `raw` y `curado`, como Marlowe.** Reusar los esquemas que ya
   existen y otorgar sobre las tablas concretas.
2. **Un esquema propio, poseído por `continental`.** Lo más cómodo: el rol
   crea y administra lo suyo sin molestar a nadie.
3. **Un esquema propio (`pedidos`), poseído por el dueño del almacén
   (`farmacia`), con el rol acotado teniendo solo `USAGE`.** El DDL se corre a
   mano, aparte del código de todos los días.

Y, para que los permisos sobre `marts` sobrevivan a la cadena nocturna:

A. **`ALTER DEFAULT PRIVILEGES … IN SCHEMA marts GRANT SELECT TO continental`.**
B. **`grants={'select': [...]}` en el config de cada modelo de dbt**, del lado
   de farmacia-data.

## Decisión

**Opción 3 más opción B.** Las tres tablas viven en un esquema `pedidos` que
posee `farmacia`; `continental` tiene `USAGE` sobre el esquema y
`SELECT, INSERT, UPDATE` sobre las tres tablas, y nada más. El DDL vive en
`sql/crear_tablas.sql` y se corre a mano, una vez, con credenciales de dueño.
Los permisos sobre `marts` se sostienen desde farmacia-data, con `grants` por
modelo.

## Razones

- **Un esquema propio convierte el límite de la regla 6 en un espacio de
  nombres, no en una convención.** Se puede otorgar de golpe, revocar de golpe
  y —lo que más importa— **comprobar de golpe**: `sql/verificar_rol.sql`
  pregunta "¿tiene el rol algún permiso de escritura fuera de `pedidos`?" sin
  mantener una lista de tablas prohibidas que se quedaría vieja.
- **Y no `raw` ni `curado` porque estas tablas no son ninguna de las dos
  cosas.** `raw` es lo que se puede tirar y reconstruir desde un origen
  externo; estas nacen aquí y perderlas es perder el trabajo de una persona.
  `curado` es lo que alguien aprobó a mano, con su fuente de verdad en un CSV
  versionado. Esto es el estado de un proceso de negocio, que es una tercera
  cosa.
- **El dueño no puede ser `continental`**, y ésta es la mitad silenciosa de la
  decisión: si lo fuera, tendría `CREATE` sobre su esquema sin que ningún
  `GRANT` lo dijera, y la casilla "el rol acotado no debe poder crear tablas"
  sería falsa mientras el archivo de permisos se veía impecable. Poseer una
  tabla además permite `ALTER` y `DROP`, así que un bug —o alguien con la
  contraseña del `.env`— podría reescribir el esquema en caliente.
- **El DDL aparte del código de todos los días.** Crear tablas es un acto
  deliberado que pasa una vez; un `preparar()` que corre al arrancar convierte
  cada despliegue en una oportunidad de alterar el esquema sin que nadie lo
  revise. Marlowe llegó a la misma separación por otro camino
  (`marlowe.esquema` corrido a mano, el rol aparte), y aquí se lleva un paso
  más: el DDL es SQL, no Python, porque un archivo `.sql` no se puede importar
  por accidente desde una ruta de FastAPI.
- **`ALTER DEFAULT PRIVILEGES` se descartó aunque resolvía el síntoma.**
  Otorgaría `SELECT` sobre **todo** modelo nuevo que dbt cree en `marts`,
  incluidos `fct_merma`, `fct_caducidad` y `fct_precio_competencia`, que
  Continental no debe leer. Arregla el problema rompiendo el principio que el
  rol existe para sostener. `grants` por modelo es más trabajo y es el correcto:
  dbt lo vuelve a aplicar en cada construcción, que es exactamente donde el
  permiso se perdía.

## Consecuencias

- **Agregar una columna cuesta una visita a atlas.** No hay migraciones
  automáticas y no las va a haber: el rol no puede alterar sus tablas. Es
  deliberado y el precio es real.
- **`crear_rol.sql` se va a volver a correr**, no es una operación única. Por
  eso es idempotente y por eso no le toca la contraseña a un rol que ya existe.
- **La dependencia con farmacia-data es de doble sentido y hay que decirlo.**
  Mientras el `grants` de los cinco modelos no esté puesto allá, una corrida
  verde de `verificar_rol.sql` solo vale hasta las 20:30 de ese día.
  `dim_proveedor.sql` es el más frágil de los cinco: hoy no tiene `grants` en
  absoluto.
- **Un cuarto esquema en el almacén.** Quien mire la base con `\dn` va a ver
  `pedidos` junto a `raw`, `staging`, `marts` y `curado`, y no es obvio a qué
  proyecto pertenece. El `COMMENT ON SCHEMA` lo dice; es lo único que lo dice.
- **Condición de revisión:** si algún día Continental necesita de verdad
  `DELETE` —hoy no, porque descartar, cerrar y cancelar son cambios de
  estado—, ese es el momento de releer esta decisión entera y no solo de
  agregar una palabra al `GRANT`.
