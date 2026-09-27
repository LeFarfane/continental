# 0021 — La conciliación se ancla en lo que llegó, no en lo que alguien marcó

**Fecha:** 2026-09  ·  **Estado:** aceptada
**Complementa el ADR 0014** (la recepción se sugiere, no se afirma)

## Contexto

El módulo tiene dos mitades. La primera —proponer qué comprar y comparar el
precio entre los cuatro proveedores— está viva. La segunda —elegir proveedor,
partir el pedido, enviarlo, seguirlo en tránsito y confirmar la recepción— no
ha nacido. Medido contra la base real el 2026-09-27:

| | |
|---|---|
| Renglones creados | **883** |
| Descartados | 1 |
| **Pedidos creados** | **0** |
| **Pedidos enviados** | **0** |
| **Renglones en tránsito** | **0** |
| **Renglones recibidos** | **0** |

Toda esa mitad cuelga de un solo gesto: que alguien le dé «Enviar» en
Continental después de capturar en el portal. **Nadie lo ha apretado nunca.**

La encargada pide directo en el portal de NADRO todos los días. El dueño
decidió el 2026-09-27 no dar por muerta esa mitad, sino **tolerar el olvido**:
suponer que alguien va a marcar, y deducir lo que pasó cuando no lo haga.

## El hecho que ordena la decisión

Son dos preguntas distintas y **solo una tiene respuesta**:

- **«¿Lo pidió?»** No se puede saber. SICAR no tiene pedidos ni órdenes: una
  compra se captura **ya recibida**, sin estado parcial. Cualquier respuesta
  aquí inventa la intención de una persona a partir de un dato que no la
  contiene.
- **«¿Llegó?»** Se sabe con certeza. La compra **es** la llegada, y
  `marts.fct_compras` la trae completa: producto, proveedor, cantidad, fecha y
  `precio_unitario_pagado`.

Perseguir la primera es adivinar. Anclarse en la segunda no necesita adivinar
nada.

## Opciones consideradas

1. **Deducir el «Enviar» olvidado**: si aparece una compra de algo que se
   propuso, dar por hecho que se pidió y avanzar el renglón solo.
2. **No deducir nada** y esperar a que alguien marque, aceptando que esa mitad
   quede sin uso.
3. **Conciliar contra lo que llegó**: cruzar lo propuesto contra lo comprado,
   mostrar el resultado, y avanzar el estado solo con un clic por lote.

## Decisión

La 3.

Una **conciliación diaria** que corre después de la cadena nocturna y, por cada
día de la bitácora, muestra tres bloques: lo propuesto que **sí** se compró
—con a quién, cuánto y a qué precio—, lo propuesto que **no**, y lo comprado
que **nadie propuso**.

Y compara `precio_unitario_pagado` contra el precio más barato que nosotros
encontramos ese día, que es la razón de ser del módulo respondida con dinero
real.

**Tolerancia: 3 días hábiles**, configurable. **Confirmación por lote, un
clic**: ningún estado avanza sin ella.

## Razones

- **Avanzar el estado solo es afirmar lo que SICAR no sabe (descarta la 1).**
  Es exactamente lo que prohíbe el ADR 0014, y la razón no ha cambiado: los
  datos no alcanzan. Una compra demuestra que algo llegó, no que llegó *porque
  lo pedimos*: la encargada compra con su criterio todos los días.
- **El clic por lote es el punto medio honesto.** Doce compras confirmadas de
  una son casi cero fricción, y siguen siendo una persona diciendo «sí, esto
  fue mío». Conserva el principio sin cobrar su precio.
- **La comparación de precios no depende de nadie (y por eso vale tanto).**
  No necesita «Enviar», ni confirmación, ni que la lista se use para pedir.
  Funciona con lo que ya hay en el almacén, y contesta sola la pregunta que
  motivó el proyecto: el 2026-09-23, el mismo EAN estaba a $122.50 en LEVIC y
  a $126.25 en NADRO.
- **Tres días hábiles y no dos, ni corridos.** El respaldo llega hasta 2.5 días
  tarde: lo del sábado no aparece hasta el lunes en la noche. Una ventana de
  dos días corridos se quedaría corta justo los lunes, que es cuando más
  compras hay acumuladas.
- **No abandonar esa mitad (descarta la 2).** Está escrita y probada; el
  problema no es el código, es que nadie la alimenta. La conciliación la
  alimenta sin pedirle a nadie que cambie cómo trabaja.

## Consecuencias

- **La conciliación es retrospectiva por fuerza.** Un día reciente sin compras
  no es un día sin compras: es un día cuyos datos no han llegado. Confundirlos
  sería afirmar algo falso, así que se dicen distinto.
- **Para 606 de 3,429 artículos (17.7%) esto no se va a disparar jamás**, porque
  nunca aparecen en `fct_compras`. El bloque de "no se compró" tiene que
  distinguirlos o los va a listar como pendientes para siempre.
- **El pedido se crea retroactivamente** al confirmar el lote, con proveedor y
  fecha de la compra y una firma que dice que se **dedujo**, no que alguien lo
  capturó. Eso mantiene la máquina de estados intacta, pero significa que
  `pedido` deja de querer decir "alguien lo armó aquí": hay dos orígenes, y
  quien lea esa tabla tiene que poder distinguirlos.
- **`compra.fecha` sigue sin verificarse** —día que llegó o día que se capturó—
  así que la ventana de tolerancia absorbe esa incertidumbre en vez de
  resolverla. Si algún día se verifica, la ventana se puede apretar.
- **Condición de revisión:** si pasados unos meses la confirmación por lote
  tampoco se usa, la conclusión ya no será "falta automatizar" sino que **esa
  mitad del módulo no tiene dueño**, y entonces toca decidir si se recorta —con
  su propio ADR— en vez de seguir bajándole la fricción.
