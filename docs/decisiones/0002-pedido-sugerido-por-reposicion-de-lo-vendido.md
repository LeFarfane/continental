# 0002 — El pedido sugerido repone lo vendido y compara precio entre los cuatro proveedores

**Fecha:** 2026-09  ·  **Estado:** aceptada

## Contexto

Hoy el pedido a NADRO se arma de memoria y de anaquel. Dos hechos medidos
dicen qué cuesta eso:

- Los dos productos que más utilidad dejan estuvieron en existencia cero
  (README de Doyle).
- El mismo EAN salió a **$86.05 en NADRO** y **$146.38 en LEVIC** el mismo día:
  70% de diferencia. Nadie lo sabía al reponer, porque el dato vivía en compras
  pasadas y no en el precio de hoy.

Lo que ya existe y no se usa para esto:

- `marts.fct_ventas`, una fila por ticket × artículo, con 21,035 líneas.
- La tarjeta **O2 "Qué reordenar"** de Metabase: demanda de 90 días, días de
  cobertura y un sugerido a 30 días. Es análisis, y el dueño pidió
  explícitamente **no** usarla como fuente del pedido.
- Las "Órdenes" de Doyle: una lista local con costo congelado y exportación a
  CSV.

Y tres restricciones de los datos, medidas:

1. **Las ventas llegan tarde.** SICAR sube su respaldo a Drive hacia las 18:51
   de lunes a viernes; la cadena corre a las 20:30. Lo que se vende después de
   las 18:51 llega al día siguiente, y **lo del sábado y el viernes por la
   tarde llega hasta el lunes en la noche**: peor caso, 2.5 días.
2. **SICAR no tiene pedidos ni órdenes de compra.** Una compra se captura ya
   recibida, `compra.status` solo vale 1 o -1 (no existe "parcial"), no está
   documentado si `compra.fecha` es el día que llegó o el día que se capturó, y
   el significado de `folio` no está verificado. Además, 606 de 3,429 artículos
   (17.7%) nunca aparecen en `fct_compras`.
3. **Solo el EAN empareja.** NADRO y LEVIC muestran EAN de 13 dígitos; VICMA
   muestra código interno pero sí indexa el EAN; QuePharma usa código interno y
   ni siquiera está confirmado que encuentre por EAN.

## Opciones consideradas

1. **Usar la O2 como pedido sugerido**: cobertura de 90 días y sugerido a 30.
2. **Reponer hasta un nivel**: calcular contra existencia y un mínimo/máximo
   por producto.
3. **Reponer lo vendido, pieza por pieza**, y que la persona corrija.

Y, para la recepción:

1. **Marcar a mano** que llegó.
2. **Cerrar solo** el renglón cuando aparezca una compra que encaje.
3. **Sugerir el cierre** ("probablemente recibido") y pedir un clic.

## Decisión

**Reposición 1 a 1 de lo vendido** (opción 3), acumulando desde el cierre del
último pedido sugerido, con **comparación de precio entre los cuatro
proveedores solo cuando empareja por EAN**, y **recepción sugerida** (opción 3)
que espera confirmación.

## Razones

- La O2 responde otra pregunta: "qué se está agotando", con 90 días de
  historia. El pedido diario responde "qué salió del anaquel ayer". Mezclarlas
  daría dos listas de "qué comprar" con reglas distintas y nadie sabría cuál
  manda. La O2 se queda como tablero.
- Reponer hasta un nivel exige mínimos y máximos confiables por producto; las
  columnas `minimo` y `maximo` existen en `dim_producto` pero no están curadas,
  y la propia O2 las ignora a propósito. Una regla que depende de datos que no
  se han verificado propone cantidades que nadie puede defender.
- La reposición 1 a 1 es aritmética que el encargado puede verificar de un
  vistazo: "se vendieron tres, se piden tres". Eso importa más que ser óptima,
  porque una lista que no se entiende no se usa.
- **Nada se filtra.** Un renglón con anaquel lleno igual aparece, ordenado por
  urgencia, con su existencia y sus días de cobertura al lado, y se descarta
  con un clic. Filtrar por cobertura sería meter la lógica de la O2 por la
  puerta de atrás.
- **Acumular desde el último cierre, no "el último día con datos".** Con el
  hueco de fin de semana, tomar solo el último día tiraría las ventas del
  sábado al piso en silencio. La primera vez arranca con 7 días.
- **Se compara solo lo que empareja por EAN.** Un hueco visible ("sin dato en
  QuePharma") es información; una comparación mal emparejada es una decisión de
  compra equivocada. Marlowe ya se tropezó con esto: una caja de 60 más barata
  por pieza se veía como "más cara". VICMA entra si el EAN devuelve exactamente
  un resultado.
- **La suite propone y la persona elige.** Hay razones que el sistema no ve:
  mínimo de pedido, días de entrega, crédito con cada proveedor. Un pedido
  puede partirse entre varios proveedores.
- **La recepción se sugiere, no se afirma.** Con `folio` de semántica no
  verificada y sin estado "parcial" en SICAR, cerrar renglones solos cerraría
  algunos falsos, y un renglón cerrado falso es mercancía que no se vuelve a
  pedir. "Probablemente recibido" dice exactamente lo que los datos sostienen.

## Consecuencias

- **La lista es larga.** Reponer todo lo vendido sin filtrar significa tantos
  renglones como productos distintos se vendieron. El orden por urgencia y el
  descarte de un clic son lo único que la mantiene legible; si aun así estorba,
  la señal será que el encargado descarta más de la mitad de los renglones cada
  día, y entonces se revisa la regla.
- **Se pide de más si alguien captura un pedido fuera de Continental.** El
  estado `en tránsito` solo protege contra el doble pedido si el pedido pasó
  por aquí.
- **La comparación va a tener huecos**, sobre todo en QuePharma. Eso es
  honesto, pero significa que "NADRO es el más barato" a veces querrá decir
  "el más barato de los que contestaron".
- **Las Órdenes de Doyle se retiran** al entrar este módulo. Su exportación a
  CSV y el costo congelado se reproducen aquí.
- **Condición de revisión:** si después de un mes de uso los renglones
  `descartados` superan a los pedidos, la reposición 1 a 1 no es la regla
  correcta y hay que volver a la opción 2 —esta vez con mínimos curados y con
  los datos de descarte como evidencia de qué productos sobran en la lista—.
  Y si la recepción sugerida acierta en más del 90% de los casos durante un
  mes, ahí sí vale la pena cerrarla sola.
