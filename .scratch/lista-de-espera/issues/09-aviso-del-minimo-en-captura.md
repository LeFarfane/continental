# 09: El aviso del mínimo en Captura

**What to build:** en la pantalla de captura, junto al total de cada pedido, se
ve su mínimo y si llega: *«faltan $260 para el mínimo de NADRO»*. Es un
**aviso, no un bloqueo**: «Enviar» sigue funcionando. Sin mínimo capturado dice
«sin mínimo capturado» en gris y no avisa. Ver el spec, «El mínimo del
proveedor y Ajustes», historias 35–38.

**Blocked by:** 03, 08

**Status:** done

- [x] La comparación la hace el **servidor**, en la base del mínimo: si incluye
      IVA, el total se lleva a con-IVA con la misma función que ya usa el
      puente. Nunca se restan dos cifras en bases distintas.
- [x] Viaja ya como estado y frase: `llega`, `no llega` (con lo que falta) o
      `sin mínimo capturado`. Un mínimo de cero siempre llega.
- [x] Con renglones sin precio, el aviso lo dice en vez de dar por buena una
      suma incompleta.
- [x] El aviso tiene «Mandar a espera» a la mano (el botón del ticket 06 si ya
      existe).
- [x] Pruebas: lo puro (con y sin IVA, sin mínimo, cero, sin precios), la ruta
      de punta a punta y la estática del JS (pinta la frase del servidor y no
      compara en el navegador).

## Cómo quedó

- `minimos.py`: `SumaDelPedido`, `AvisoDelMinimo`, `avisar_el_minimo` (puro).
  Seis estados: `llega`, `no_llega`, `sin_capturar`, `sin_minimo`, `no_se_sabe`,
  `sin_leer`.
- La función de «con IVA» **no existía** en Continental (el puente no convierte;
  solo resta precios de proveedor, los dos sin IVA). Se agregó
  `particion.la_suma_del_pedido`, que lleva el total a con-IVA renglón por
  renglón con `marts.dim_producto.tasa_impuestos` (novena lectura del almacén,
  `tasas_de_impuestos`), redondeando por renglón. Tasa desconocida = «no se
  sabe», nunca exento.
- Cada pedido de la respuesta trae `minimo`; una lectura de mínimos por
  respuesta (`app._los_avisos_del_minimo`).
