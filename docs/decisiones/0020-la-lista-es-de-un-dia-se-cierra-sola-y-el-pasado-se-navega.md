# 0020 — La lista es de un día, se cierra sola, y lo pasado se navega

**Fecha:** 2026-09  ·  **Estado:** aceptada
**Enmienda el ADR 0002** (la ventana de acumulación) **y el 0016** (cerrar y reabrir)

## Contexto

El módulo se diseñó suponiendo que **el pedido sale de la lista**: se propone,
una persona revisa, descarta lo que no va, y lo que queda se pide. De ahí venía
acumular desde el cierre del sugerido anterior (ADR 0002) y el cuidado de que
nada se perdiera si un día nadie cerraba.

**Esa suposición resultó falsa.** Lo dijo el dueño el 2026-09-27: la encargada
**no lee el programa diario**. Hace el pedido directamente en el portal de
NADRO todos los días, pase lo que pase. La lista no es el registro de lo que se
pidió — es **una ayuda para decidir**, y compite con todo lo demás que ella
tiene que hacer parada en el mostrador.

Una ayuda que no se lee no ayuda. Y la de hoy no se puede leer:

| | |
|---|---|
| Listas creadas | 5 |
| Listas cerradas alguna vez | **0** |
| Ventana de todas | `2026-09-12 → su fecha` |
| Renglones de la última | **174** |

Medido sobre `marts`, un día de operación normal son **11 a 45 productos
distintos, promedio ~29**. La lista de un día es diez veces más corta que lo
que hay hoy.

**La ventana larga no era un defecto.** `dias_primera_vez` ya valía 1. Lo que la
estiraba era `piso_sin_pedir`: el principio de la lista más vieja que quedó sin
pedir, puesto ahí para que las ventas de un día desatendido no se cayeran al
suelo sin un solo error visible. Con nadie cerrando nunca, ese piso se quedó
anclado al 12 de septiembre y arrastró trece días.

## Opciones consideradas

1. **Dejarlo como está** y pedirle a la encargada que cierre la lista cada día.
2. **Cerrar solo al crear la siguiente, y arrastrar lo no pedido** a la lista de
   hoy en una sección plegada, para que nada deje de proponerse.
3. **Cerrar solo al crear la siguiente, sin arrastrar nada**, y dejar lo pasado
   como bitácora que se puede navegar día por día.

## Decisión

La 3, con cuatro reglas:

1. **Al crearse la lista de hoy se cierra sola la de ayer.** Automático, con su
   firma de que lo hizo el sistema y no una persona.
2. **Lo no pedido no se vuelve a proponer, pero no desaparece:** las listas
   pasadas quedan como bitácora navegable, un día por lista.
3. **Lo pasado es de solo lectura por omisión, y se puede reabrir.** Cambia el
   valor por omisión del ADR 0016, no la capacidad.
4. **No hay lista los domingos ni los días festivos.**

## Razones

- **Confiar en un cierre diario es la garantía que este repo no acepta
  (descarta la 1).** Ya estaba escrito en el código, y se cumplió: cinco listas,
  cero cierres. Una regla que depende de que alguien se acuerde no es una regla.
- **Arrastrar lo no pedido reconstruye el problema (descarta la 2).** Si la
  encargada no descarta —y no va a descartar, porque no usa la lista para
  pedir— la sección arrastrada crece todos los días hasta volver a ser los 174
  renglones de hoy, solo que plegados. Se consideró en serio y se descartó por
  eso.
- **La navegación es la que sustituye al `piso_sin_pedir`.** La garantía deja
  de ser "se vuelve a proponer" y pasa a ser "se puede ir a ver". Es más débil,
  y se acepta a propósito: quien decide qué comprar ya compró, y lo que el
  módulo aporta es el precio del día y la comparación entre proveedores, no la
  memoria de lo que faltó.
- **Reabrir se conserva porque el ADR 0016 sigue teniendo razón:** vale
  mientras nadie haya usado ese corte. Lo que cambia es que el estado normal de
  una lista pasada es cerrado en vez de abierto — antes había que cerrar, ahora
  hay que abrir.
- **Los domingos y festivos no son ceros reales.** Es la misma lección que
  `dim_fecha` ya aprendió en farmacia-data: un día sin ventas porque la
  farmacia cerró no es un día de cero ventas. Armar una lista vacía de un día
  cerrado invita a leerla como "no se vendió nada".

## Lo que esto **no** arregla, dicho a propósito

Si el pedido real se captura en NADRO sin pasar por aquí, **el sistema no sabe
qué viene en camino**. Eso debilita `en tránsito` y `probablemente recibido`
—toda la maquinaria del ADR 0012 al 0015— que se construyó suponiendo que el
pedido nacía de la lista.

No se resuelve en este ADR y no se disimula: hoy esas piezas siguen
funcionando para quien sí use la lista para pedir, y quedan sin uso para quien
no. **Si se confirma que nadie pide desde la lista, hay que decidir a propósito
si esa maquinaria se mantiene, se recorta o se reorienta** — y esa es otra
decisión, con su ADR.

## Consecuencias

- **Un día que nadie miró pierde su propuesta.** Es el costo aceptado. La
  única red es que la lista de ese día se puede abrir y leer después.
- **`piso_sin_pedir` deja de dispararse en la práctica:** con cierre automático
  siempre hay corte, y ese piso solo aplica cuando no lo hay. Se conserva para
  el primer arranque. Queda anotado para que nadie lo lea como código muerto.
- **La bitácora crece sin tope.** Una lista por día hábil son ~300 al año, con
  sus renglones. No es un problema de tamaño a esta escala, pero la navegación
  tiene que poder saltar a una fecha y no solo avanzar de uno en uno.
- **Reabrir una lista vieja puede confundir la ventana.** El corte sale del
  máximo de las cerradas; reabrir una de hace un mes lo retrocedería. El ADR
  0016 ya lo cubre con su condición —vale mientras nadie use ese corte— pero
  ahora se va a ejercitar más seguido.
- **Condición de revisión:** si algún día la encargada empieza a pedir desde la
  lista, la 2 vuelve a la mesa — arrastrar lo no pedido tendría sentido otra
  vez, porque entonces sí habría quien descarte.
