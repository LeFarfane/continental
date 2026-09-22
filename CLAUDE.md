# Continental — contexto del proyecto

La suite que junta todo lo que se construyó para operar esta farmacia:
`Doyle` (precios de proveedor), `Marlowe` (precios de competencia) y los
módulos nuevos, detrás de una sola puerta —`farmacia.farfanlab.uk`— para que
el encargado no tenga que saber que son tres programas distintos.

Repo aparte, con su propio `.git`, igual que Doyle y Marlowe. El porqué está en
`docs/decisiones/0001-suite-como-cascara-con-modulos-por-http.md`.

## Léelo en este orden

`CONTEXT.md` (el glosario, 3 min) → este archivo → `docs/decisiones/0001` y
`0002`.

## Reglas no negociables

1. **Continental no scrapea, no mide y no toca un navegador.** Eso lo hacen los
   módulos. Si una pantalla necesita un dato de un portal de proveedor, se lo
   pide a Doyle por HTTP; si necesita un precio de competencia, a Marlowe. El
   día que aquí aparezca un `import playwright`, la decisión del ADR 0001 se
   rompió y hay que reabrirla a propósito, no de a poquito.
2. **Continental es la única puerta al exterior.** Doyle escucha en loopback y
   no tiene autenticación propia porque nada externo lo alcanza. **Marlowe no
   cumple esto** desde antes de que se escribiera esta regla: tiene su propia
   pantalla detrás de su propio túnel, escucha en el gateway de la red Docker
   `borde` y no tiene autenticación propia, así que lo alcanza cualquier cosa
   que esté en esa red — no algo externo, pero tampoco loopback. Ver la
   enmienda del 2026-09-21 al ADR 0005, donde queda como pregunta abierta para
   el dueño. Para Doyle, o cualquier módulo que hoy sí esté en loopback, la
   regla sigue firme: si tiene que escuchar en otra interfaz, esa suposición
   deja de valer y hace falta un token entre servicios **antes** de moverlo.
3. **El rol es una firma, no un permiso.** El correo llega en
   `Cf-Access-Authenticated-User-Email`, ya verificado por Cloudflare Access,
   y sirve para saber quién hizo qué. La seguridad real es Access. Nunca
   escribas código que trate ese encabezado como prueba de autorización: si
   alguien alcanza el puerto sin pasar por el túnel, lo puede inventar.
4. **Falla ruidoso, nunca en silencio.** Un módulo que no contesta se muestra
   como un hueco con su motivo ("Doyle no responde"), no como una lista vacía.
   Un precio que no se pudo leer es "sin dato", jamás un cero ni un "más caro".
5. **Los errores no viajan al navegador.** Esto corre detrás de un túnel: un
   `str(exc)` de SQLAlchemy lleva la cadena de conexión con contraseña. El
   detalle va a la consola del servidor; al cliente, un mensaje genérico. Es la
   misma lección que Marlowe aprendió el 2026-09-06.
6. **Solo lectura sobre el almacén, salvo sus propias tablas.** El rol
   `continental` de Postgres escribe únicamente lo suyo (pedidos y renglones) y
   de `marts` solo lee lo que necesita. El permiso es la garantía, no la buena
   intención del código.
7. **Toda tabla dice a qué negocio pertenece.** Hoy hay una farmacia y el
   código de negocio siempre vale lo mismo (`farmacia_01`). Se guarda igual:
   es lo único que se paga hoy para no reescribir el módulo el día que haya
   dos. Ver ADR 0001.

## De qué se compone

| Pieza | Dónde vive | Puerto |
|---|---|---|
| Continental | este repo, atlas | 8585 |
| Doyle | `../Doyle`, atlas (ADR 0008 de Doyle) | 8383 |
| Marlowe | `../Marlowe`, atlas | 8484 |
| El almacén | Postgres de `farmacia-data`, en Docker en atlas | 5432 |

Max/punto-interno (el punto de venta del mostrador) queda fuera por ahora: sus
productos no están en SICAR y no se le compran a estos proveedores.

## El módulo de Pedido

Lo primero que se construye aquí. En una frase: **toma lo que se vendió, propone
comprarlo, y dice cuál de los cuatro proveedores lo da más barato hoy.**

El vocabulario exacto —pedido sugerido, renglón, pedido, en tránsito,
probablemente recibido— está en `CONTEXT.md`, y el porqué de cada regla en
`docs/decisiones/0002`. Lo que hay que tener presente al escribir código:

- **Reposición 1 a 1**, acumulando desde el cierre del último pedido sugerido.
  La primera vez, 7 días.
- **Nada se filtra**: lo que tiene anaquel lleno aparece igual, ordenado por
  urgencia, y se descarta con un clic.
- **Solo se compara lo que empareja por EAN.** VICMA entra si el EAN devuelve
  exactamente un resultado; QuePharma va a quedar fuera seguido y eso se dice
  como "sin dato", nunca como "más caro".
- **El lote nocturno tiene tope de 60 minutos** y va en orden de importancia
  (clase ABC, que será columna de `dim_producto` — ADR 0018 de farmacia-data).
  Lo que no alcanzó queda marcado sin precio, con su botón para completarlo.
- **La recepción se sugiere, no se afirma.** SICAR no tiene pedidos: una compra
  se captura ya recibida, sin estado parcial, y `folio` tiene semántica no
  verificada.

## Trampas heredadas — no las redescubras

- **Las ventas llegan tarde.** El respaldo de SICAR sube hacia las 18:51 de
  lunes a viernes y la cadena corre a las 20:30. Lo del sábado y el viernes por
  la tarde llega hasta el lunes en la noche: peor caso, 2.5 días. Por eso el
  sugerido acumula desde el último cierre en vez de mirar "el último día".
- **El Postgres del contenedor corre en UTC.** Su `current_date` puede ir dos
  días adelante del último dato. **Todo se ancla en `max(fecha)`**, nunca en el
  reloj. A farmacia-data le costó 11.7 puntos de crecimiento inventados.
- **688 de 3,429 artículos no tienen anaquel.** Esos productos se muestran
  marcados como *sin clasificar*; si se filtran por no encajar en el toggle,
  desaparece mercancía de la lista sin que nadie lo note.
- **El costo nuestro es sin IVA y el de mostrador con IVA.** Nunca restes las
  dos cifras directo: Marlowe ya se equivocó así y la flecha apuntaba al revés.
- **Sin librerías vectorizadas.** Atlas es un Athlon II X4 de 2010 sin SSSE3:
  numpy, pandas y rapidfuzz de PyPI mueren ahí con `Illegal instruction`.
  `pydantic_core` sí pasa (medido el 2026-09-06), y por eso FastAPI se puede
  usar aquí igual que en Marlowe.

## Dónde corre

**Se edita en la torre, corre en atlas** — la misma regla que farmacia-data y
Marlowe. `git push` desde la torre, `scripts/desplegar.sh` en atlas: compila,
corre las pruebas y solo entonces reinicia el servicio.

En atlas el repo va **plano** (`~/proyectos/Continental`, hermano de Marlowe),
Continental escucha en el gateway de la red Docker `borde` y no en loopback
(ADR 0005), y el túnel es *remotely-managed*: la ruta y la política de Access
se dan de alta en el dashboard de Cloudflare, no por ssh. Todo el
procedimiento, con lo que ya está hecho y lo que falta, en
`docs/despliegue-en-atlas.md`.

## Comandos

```bash
python iniciar.py             # web en http://127.0.0.1:8585
python iniciar.py --servicio  # sin abrir navegador, sin buscar otro puerto
pytest                        # pruebas

# en atlas, para desplegar una versión nueva:
ssh -t eddie@192.168.100.14 '~/proyectos/Continental/scripts/desplegar.sh'
```

`--servicio` **se niega a arrancar** si el 8585 está ocupado, en vez de irse al
8586: el túnel apunta a un puerto fijo y arrancar en otro dejaría el servicio
vivo e inalcanzable. Está probado en `tests/test_despliegue.py`, no supuesto.

## Agent skills

Los encabezados de esta sección están en inglés a propósito: son lo que las
skills buscan. El contenido del repo sigue en español.

### Issue tracker

Markdown local bajo `.scratch/<slug>/`, versionado. Continental todavía no tiene
remoto ni `gh` instalado; cuando lo tenga, esto pasa a GitHub cambiando un solo
archivo. Ver `docs/agents/issue-tracker.md`.

### Triage labels

Las cinco por omisión, sin traducir: `needs-triage`, `needs-info`,
`ready-for-agent`, `ready-for-human`, `wontfix`. Ver
`docs/agents/triage-labels.md`.

### Domain docs

Contexto único: `CONTEXT.md` en la raíz y los ADRs en **`docs/decisiones/`**
—no en `docs/adr/`, que es lo que dice la plantilla—. También mandan aquí los
ADRs de `Doyle` y de `farmacia-data`. Ver `docs/agents/domain.md`.

## Convenciones

- Nombres de código, commits, comentarios y documentación **en español**.
- Toda decisión de arquitectura se registra como ADR en `docs/decisiones/`, con
  las alternativas descartadas y por qué.
- El glosario de `CONTEXT.md` manda sobre el nombre de cualquier cosa. Si el
  código y el glosario no coinciden, uno de los dos está mal.
- Lo que se mide se anota con la fecha y el número, no como afirmación general.
