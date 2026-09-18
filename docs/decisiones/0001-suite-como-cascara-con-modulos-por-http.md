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
