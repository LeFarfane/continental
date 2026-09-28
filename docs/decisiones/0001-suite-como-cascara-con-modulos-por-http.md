# 0001 — Continental es una cáscara y los módulos son procesos aparte

**Fecha:** 2026-09  ·  **Estado:** aceptada

## Contexto

Hay tres programas construidos para esta farmacia, cada uno con su repo, su
`.git` y su entorno de Python:

| | Qué hace | Dónde corre hoy |
|---|---|---|
| `farmacia-data` | ingesta de SICAR, almacén Postgres, dbt, Metabase | atlas |
| `Doyle` | consulta precio y existencia en 4 portales de proveedor | torre Windows |
| `Marlowe` | precios de catálogo de 5 cadenas competidoras | atlas |

Se separaron a propósito. El ADR 0008 de farmacia-data lo dice con números: un
navegador y sus dependencias no entran al venv que corre la cadena nocturna en
un CPU de 2010 sin SSSE3. Doyle necesita Chrome real; Marlowe necesita Chromium
de `apt` y tiene prohibido numpy, pandas y rapidfuzz por ese mismo CPU.

El costo de esa separación lo paga la persona que opera: hoy son tres
direcciones distintas, tres interfaces distintas, y una tarea tan común como
"lo que se vendió hoy, ¿a quién se lo pido?" no vive en ninguna de las tres.
Van a venir más módulos.

## Opciones consideradas

1. **Monorepo, un solo proceso.** Doyle y Marlowe pasan a ser paquetes
   importados por un programa único.
2. **Una página de enlaces.** Un menú que abre cada app en su dirección.
3. **Una cáscara con módulos por HTTP.** Un programa nuevo (Continental) es la
   única puerta al exterior, dibuja toda la interfaz y les habla a los módulos
   —que siguen siendo procesos aparte— por HTTP en loopback.

## Decisión

La 3: **Continental es la cáscara y los módulos son procesos aparte que se
hablan por HTTP en `127.0.0.1`**, con un solo hostname público,
`farmacia.farfanlab.uk`, detrás de Cloudflare Access.

## Razones

- La 1 obliga a un solo entorno de Python con Playwright, Chrome, Chromium,
  dbt y todo lo demás junto: exactamente lo que el ADR 0008 de farmacia-data
  evitó midiendo el problema, no suponiéndolo. Además, una falla de un módulo
  tumbaría a los otros dos.
- La 2 no sirve para lo que se quiere construir: el módulo de pedido **llama**
  a Doyle, no lo enlaza. Un menú no resuelve nada que no resuelva un marcador
  del navegador.
- El costo de la 3 —la red— es cero en la práctica: una llamada por loopback
  tarda menos de un milisegundo y la operación que envuelve, consultar un
  portal, tiene un piso medido de 9 segundos por proveedor.
- Reiniciar Continental para desplegar no tira una sesión de Chrome que costó
  trabajo abrir, porque vive en otro proceso.
- Los módulos no escuchan fuera de loopback, así que no necesitan
  autenticación propia: nada externo los alcanza. Continental es lo único que
  el túnel ve.
- **Los roles son etiquetado, no seguridad.** Continental lee el correo que
  Access ya verificó (`Cf-Access-Authenticated-User-Email`) y lo usa para
  firmar quién hizo qué. La seguridad real es Access, como ya lo es para
  Metabase y para Marlowe; construir usuarios y contraseñas propios sería
  agregar un almacén de credenciales para repetir un control que ya existe.
- **Una instalación por farmacia, no una para todas.** Cada farmacia tiene su
  SICAR, su Drive y sus cuentas de proveedor: separar por columnas dentro de
  una sola instalación resolvería un problema que no existe. Lo único que se
  hace desde hoy es que toda tabla de Continental diga a qué negocio
  pertenece, para no tener que reescribirla después.

## Consecuencias

- **Un módulo caído se ve como un hueco, no como una pantalla rota.** Eso hay
  que construirlo a propósito: cada llamada a un módulo necesita su timeout y
  su mensaje ("Doyle no responde"), o Continental se queda colgada esperando.
- **Hay más piezas que arrancar y vigilar**: un `systemd` por módulo, y el
  orden importa. A cambio, cada una se reinicia sola sin arrastrar a las otras.
- **La suposición de "loopback es seguro" no es universal.** Marlowe hoy no
  escucha en loopback sino en el gateway de la red Docker `borde`
  (`172.19.0.1`), porque el túnel no alcanza `localhost` del host. El día que
  un módulo tenga que escuchar ahí para algo que no pase por Continental, esta
  decisión ya no lo protege y hace falta un token entre servicios.
- **Los módulos conservan su repo y su historia.** Fusionarlos sigue siendo
  posible más adelante; lo contrario —separar lo que se mezcló— no.
- **Condición de revisión:** si dos módulos terminan compartiendo más código
  que interfaz (por ejemplo, si el emparejamiento por EAN de Doyle y el de
  Marlowe divergen y hay que arreglarlos dos veces), ahí conviene volver a
  mirar el monorepo. También si la latencia de una pantalla llega a segundos
  por el número de llamadas encadenadas.

## Enmienda del 2026-09-27 — la opción 1 eran dos preguntas, y los repos se quedan separados

**La opción 1 juntaba dos cosas distintas:** "monorepo" y "un solo proceso".
Todas las razones que este ADR da en contra son del proceso y del venv
—Playwright junto a dbt, una falla que tumba a los otros dos—; ninguna es del
repo. Fusionar solo los repos —tres paquetes, tres venvs, tres servicios, un
solo `.git`— nunca se pesó por separado. Se pesó hoy, a pregunta del dueño, y
**la base queda confirmada: tres repos y una sola puerta, que es Continental.**

**Fusionar procesos sigue descartado, y con más razón que el día 17.** Doyle
sostiene ahora un Chromium con ventana sobre la `:98` de Xvfb, con sesiones
que una persona abrió a mano por el visor (ADR 0008 de Doyle). Continental
lleva 98 commits en nueve días: en un solo proceso, cada despliegue tiraría
esos navegadores.

**Fusionar repos se pospone: las condiciones de revisión de arriba no se
cumplen.** Medido el 2026-09-27:

| Condición | Lo medido |
|---|---|
| ¿Comparten más código que interfaz? | No. El emparejamiento por EAN vive solo aquí (`precios.emparejar`, ticket 13); Doyle entrega filas crudas; Marlowe empareja otra cosa —enlaces curados y títulos con `difflib`—. Lo que cruza de un repo a otro es lección, no código: las dos rutas de Chromium que Doyle copió de Marlowe, y media defensa del CSV para Excel que `exportar.py` tomó de `alta.escribir_csv` de Marlowe. |
| ¿Se mueve el contrato? | No. Desde el 2026-09-17 la API de Doyle cambió 12 líneas de `web/buscador.py`, para elegir Chromium, ninguna del contrato. De los 98 commits de Continental, 4 nombran a Doyle o a Marlowe y ninguno cambió el contrato: uno corrige la URL de Marlowe en el YAML (`de94e57`), uno cierra el pendiente de la mudanza de Doyle, y dos son documentación o citan una lección. Marlowe no tiene commits desde el 2026-09-16. |
| ¿Latencia encadenada? | No aplica: a Doyle se le pide una búsqueda y se consulta después; a Marlowe solo se le pregunta la salud, para la portada. |

Y fusionarlos hoy costaría:

- reescribir 12 de las 14 unidades de systemd y los dos `desplegar.sh` que
  apuntan a `~/proyectos/<repo>`;
- un despliegue que sepa qué módulo cambió y reinicie solo ese. Sin él, cada
  `git pull` de Continental reinicia a Doyle y le tira los navegadores: la
  razón de este ADR, entrando por la puerta del despliegue;
- tocar el barrido nocturno de Marlowe, que está en producción;
- y hacerlo mientras se estabiliza el primer día real del Pedido —la sesión
  de LEVIC muere del lado del servidor y el timer del lote está desarmado—,
  mezclando dos fuentes de falla.

**Las dos fricciones reales que salieron no piden un monorepo.** Un doble que
se alejó del Doyle real —`ESTADOS_PENDIENTES`, 2026-09-19: el doble decía
`pendiente` y Doyle decía `buscando`; lo cazó una lectura a mano, y Doyle no
tiene pruebas— se ataja con una prueba de contrato. Las decisiones repartidas
—los ADRs de Marlowe viven en farmacia-data, la mayoría del 0008 al 0016; los
pendientes de la mudanza de Doyle viven aquí— se atajan con un mapa. Ninguna
de las dos está decidida todavía.

### Los módulos se encuentran en el almacén, no en el código

HTTP es para **pedirle trabajo** a un módulo. Para **cruzar lo que los módulos
ya midieron**, el lugar es el almacén: los tres precios de un producto ya caen
en el mismo Postgres —el de proveedor congelado en
`pedidos.precio_de_proveedor` (ADR 0004), el de cadena en
`marts.fct_precio_competencia` (lo mide Marlowe, lo modela farmacia-data), el
nuestro en `marts`—. Ese cruce por producto es el **puente** (`CONTEXT.md`):
un `JOIN`, que vive **en Continental**, leyendo `marts`. Cuesta un `grant`:
hoy `fct_precio_competencia` solo se le concede a `marlowe`.

Se descarta hacerlo como mart de dbt que lea `pedidos.*`: el almacén
dependería de las tablas de una app que a su vez lee del almacén. Es un
ciclo.

**Qué se compara con qué lo decide el glosario, no este ADR**, y el dueño lo
afinó el mismo día. Decía que el precio de un proveedor y el de una cadena
"compararlos entre sí no significa nada". Ahora dice que **no se restan como
si fueran el mismo precio, pero leídos juntos, en contexto y en la misma base
de IVA, dicen cuánto margen cabe sin afectar al cliente**. Para saberlo hace
falta nuestro costo de compra y la posición del producto en el mercado: ni
Doyle ni Marlowe lo contestan solos.

**El criterio del dueño para lo que el puente guarda es capturar primero.**
Conviene generar el dato y descartarlo o recontextualizarlo después, antes que
rediseñar una tubería el día que haga falta un dato que no se guardó. Es el
mismo razonamiento que el snapshot diario de farmacia-data y la tabla que solo
crece del ADR 0004.

**El orden lo decidió el dueño el 2026-09-27.** El puente va **antes** de
absorber la interfaz de Marlowe (paso 4), y el paso 4 va al final a propósito:
primero se pule cada módulo por separado —todavía hay ideas para Marlowe— y
después se conectan todos bajo Continental. El puente tampoco va antes del
primer día real de operación del Pedido, porque se apoya en precios de Doyle y
todavía no hay uno validado contra una compra.

**"Puente" ya nombraba otra cosa** en el código: el mapa de la clave de
proveedor de Doyle al proveedor de SICAR (ADR 0008), que la pantalla escribe
"sin puente". El dueño eligió el nombre para el cruce, así que ese uso viejo
se renombra.

### Condiciones de revisión nuevas

Se suman a las dos de arriba, que siguen en pie:

- **Al absorber la interfaz de Marlowe** (paso 4 de `HANDOVER.md`): es la
  primera vez que código se muda de un repo a otro.
- **Si el puente obliga a que los dos emparejamientos coincidan** —el EAN de
  aquí y los enlaces curados de Marlowe— en la presentación del producto (caja
  de 30 contra caja de 60), y empiezan a divergir. Es la condición original de
  este ADR con el lugar exacto donde aparecería.
- Si un cambio exige commits coordinados en dos repos **más de tres veces en
  un mes**. Al 2026-09-27: cero.
- Si un doble de este repo **vuelve** a alejarse del módulo real: un segundo
  caso como `ESTADOS_PENDIENTES`.
