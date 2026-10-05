# 02: Probar un portal desde su tarjeta en Sesiones

**Qué construir:** que el encargado apriete «Probar» en la tarjeta de un portal y, unos segundos después, la tarjeta diga si la sesión `sirvió` (pasó del login) o está `caducada` (el portal mandó al login), con la hora. El resultado se guarda, y la etiqueta de la tarjeta pasa a ser la evidencia más reciente, venga de una prueba o de una consulta del pedido. Spec: `../spec.md`. ADR 0024, decisiones 3, 5, 6 y 7. Vocabulario en `CONTEXT.md`.

**Bloqueado por:** 01.

**Status:** ready-for-agent

- [ ] Cada tarjeta de la pestaña Sesiones tiene un botón «Probar», salvo la que espera en el visor, que ofrece «Ya entré» y «Cancelar» como hoy.
- [ ] Una ruta POST nueva prueba el proveedor que se le pide. Usa la búsqueda que Doyle ya tiene, con su lista de proveedores, busca el término de prueba (ticket 01) y espera a que termine, con el mismo patrón que la sonda.
- [ ] Se guarda una fila nueva en una tabla que solo crece, dentro del esquema propio de Continental: negocio, proveedor, hora (`timestamptz`) y un resultado que el `CHECK` limita a `sirvió` o `caducada`. Sin firma y sin precio.
- [ ] El rol `continental` inserta y lee esa tabla, pero no actualiza ni borra (regla 6). La migración va con su revisión de forma antes de reiniciar (ADR 0017), y la cubren `test_forma.py` y `test_despliegue.py`.
- [ ] `sirvió` significa "pasó del login": cuentan precio, `sin resultados` y `no empareja`. `caducada` significa `la sesión caducó`. Las pruebas actuales que dependen de "dio precio" se ajustan a propósito.
- [ ] La etiqueta de `GET /api/sesiones` la decide la función pura de `sesiones`: gana lo más reciente entre la última prueba guardada y las consultas guardadas.
- [ ] La frase nombra el origen y la hora: «probada a las 9:00» o «una consulta la encontró caducada a las 11:00». El JS solo la pinta.
- [ ] «Ya entré» sigue sin lanzar una prueba, y la tarjeta queda en `guardada, sin probar`.
- [ ] Si la prueba no termina (Doyle no responde, o el portal no contesta) no se guarda nada y la etiqueta anterior se queda. La pantalla muestra el error con su qué hacer, en una nota fija y no en el aviso pasajero. La respuesta no lleva el texto de la excepción (regla 5).
- [ ] Al terminar, las tarjetas se vuelven a pintar sin recargar la página.
- [ ] El doble de almacenamiento guarda y lee pruebas igual que el SQL, y hay una prueba que los compara, como la que ya existe para la evidencia.
- [ ] Las pruebas de la API (con `cliente`, `doyle` y `almacenamiento`) cubren:
  - `sin resultados` sale como `sirvió`;
  - `la sesión caducó` sale como `caducada`;
  - con Doyle caído no se escribe nada y la etiqueta se queda;
  - una prueba posterior le gana a una consulta, y al revés.
- [ ] Lo estático (HTML, CSS y JS) sigue pasando `test_pasada_visual.py`: sin colores fuera de `:root` y sin frases compuestas en el JS.
