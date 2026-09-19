# 03: El pedido sugerido del día, calculado y visible

**Qué construir:** el encargado abre Continental y ve la lista de lo que conviene comprar: un renglón por producto vendido, con las piezas que salieron. Todavía no se guarda nada y no hay precios — es la bala trazadora que atraviesa almacén, cálculo, API y pantalla.

**Bloqueado por:** 01.

**Status:** ready-for-agent

- [ ] Hay un pedido sugerido para el último día con datos, con un renglón por producto vendido y la cantidad igual a las piezas vendidas (reposición 1 a 1).
- [ ] La pantalla muestra clave, descripción y cantidad propuesta.
- [ ] La pantalla dice **de qué fecha de ventas** salió la lista, para que nadie confunda ayer con el viernes pasado.
- [ ] La ventana de ventas se ancla en `max(fecha)` del almacén, **nunca** en el reloj: el Postgres del contenedor corre en UTC y su `current_date` puede ir dos días adelante del último dato.
- [ ] El cálculo es una función pura que recibe ventas y catálogo, y se prueba por la API.
