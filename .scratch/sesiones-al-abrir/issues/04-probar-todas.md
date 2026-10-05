# 04: «Probar todas»

**Qué construir:** que el encargado revise los cuatro portales con un solo botón, arriba de las tarjetas. Si uno está esperando en el visor, se prueban los otros tres y se dice cuál se saltó y por qué. Spec: `../spec.md`. ADR 0024, decisiones 3 y 8.

**Bloqueado por:** 03.

**Status:** done

- [x] Arriba de las cuatro tarjetas de la pestaña Sesiones hay un botón «Probar todas».
- [x] Con la lista de proveedores vacía, la ruta de probar prueba los cuatro en **una sola** búsqueda del término de prueba, no en cuatro (ADR 0019: Doyle reparte un término entre los cuatro en el mismo trabajo).
- [x] El portal que espera en el visor se salta, y la respuesta lo reporta con su motivo. Los demás se prueban y guardan su resultado.
- [x] Cada portal que se probó guarda su propia fila, con `sirvió` o `caducada`. El que no contestó no guarda nada y conserva su etiqueta. La pantalla dice cuál fue.
- [x] «Probar todas» respeta el candado del ticket 03: se apaga con una prueba en curso, y mientras corre apaga los botones de cada tarjeta.
- [x] Las pruebas de la API cubren: los cuatro en una sola búsqueda; uno en el visor se salta y se reporta; un resultado mixto (dos `sirvió`, uno `caducada`, uno sin contestar) guarda tres filas y no cuatro.
