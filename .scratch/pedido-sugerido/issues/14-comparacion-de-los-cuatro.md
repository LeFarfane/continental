# 14: La comparación de los cuatro

**Qué construir:** la razón de ser del módulo, visible en una fila. El encargado ve a cómo está el producto en los cuatro proveedores, cuál gana y cuánto se ahorra.

**Bloqueado por:** 13.

**Status:** ready-for-agent

- [x] Cada renglón muestra el precio de compra de los cuatro proveedores.
- [x] El más barato **con existencia** viene marcado.
- [x] Se muestra el ahorro contra NADRO, en pesos y por renglón.
- [x] Se muestra la existencia que reporta cada proveedor: el más barato no sirve si no lo tiene.
- [x] Un proveedor sin dato se ve distinto de un proveedor caro, de un vistazo.
- [x] La comparación usa el precio congelado del renglón, con su fecha visible.

## Lo que se decidió, con su porqué (2026-09-19)

Las dos decisiones —**quién gana** y **cuánto se ahorra**— son funciones puras
en `src/continental/comparacion.py`, con su tabla de casos en
`tests/test_comparacion.py`. La ruta las llama y la pantalla las pinta; ninguna
de las dos vuelve a decidir nada.

**La tercera categoría de la existencia.** No son dos casos sino tres: el que
confirmó que lo tiene (`40`, `+100`), el que dijo que tiene cero, y **el que dio
precio y no dijo su existencia** —o la dijo con palabras: `"Bajo pedido"`,
`"SI"`, `"Disponible"`, que es lo que `precios.existencia_a_numero` devuelve
como `None`—. El tercero **no compite con quien sí la confirmó**: si alguien
confirmó, gana el más barato de ésos aunque haya uno más barato que no dijo
nada, y el que no dijo nada sigue en la fila con su precio a la vista. Si nadie
confirmó, gana igual el más barato pero con **otra certeza**
(`GANADOR_SIN_CONFIRMAR`), que la pantalla escribe con otras palabras y en otro
color. Dejar el renglón sin ganador ahí sería esconder el único dato que hay;
darle la marca de "con existencia" sería inventarse una confirmación.

**El ahorro cuando NADRO no tiene precio es `None`, nunca cero.** Un `$0.00` se
lee *"da lo mismo a quién comprarle"*, que es lo contrario de lo que pasa: no se
sabe cuánto cobra NADRO hoy. Sale el motivo de NADRO al lado —la sesión caducada
se arregla en dos clics— y **el renglón no se esconde**: el ganador sigue
marcado y su precio sigue a la vista. Hay **un** cero legítimo, el de NADRO
ganando, y se dice con palabras ("NADRO ya es el más barato: no hay nada que
ahorrar"). Y hay un **negativo**, que tampoco es un ahorro: NADRO barato y
agotado, el ganador caro y con existencia. Se escribe "Cuesta $X más que NADRO".

**Las piezas son `cantidad_a_pedir`**, que ya resuelve si manda la propuesta del
sistema o la corrección de la persona (ticket 11). Esa regla no se repite: entra
por argumento.

**El IVA.** Lo único que se resta son dos precios de **compra** de proveedor,
los dos sin IVA. El precio de mostrador no entra ni por la firma de las
funciones (`test_la_comparacion_no_puede_ni_recibir_el_precio_de_mostrador`).

## Lo que este ticket dejó a la vista y NO cerró

El conteo de huecos —cuántos renglones quedaron sin comparar, contra cuántos
proveedores se comparó cada uno, y "el único que contestó" en vez de "el más
barato"— es el **ticket 15**. Los datos que necesita ya viajan en la respuesta
(`comparacion.consultados`, `comparacion.con_precio`, y el estado
`sin consultar` por proveedor), pero no hay ningún conteo ni ninguna frase que
diga "el único que contestó": un renglón comparado contra un solo proveedor hoy
se marca como *el más barato con existencia*, que es lo que el 15 tiene que
corregir.
