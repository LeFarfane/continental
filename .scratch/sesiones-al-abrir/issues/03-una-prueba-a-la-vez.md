# 03: Una prueba a la vez, y el portal del visor no se prueba

**Qué construir:** que mientras corre una prueba nadie pueda lanzar otra, desde ninguna computadora, y que los botones de probar se vean apagados con el motivo. Y que el portal que espera en el visor a que alguien entre no se pruebe nunca: esa ventana es de quien está tecleando. Spec: `../spec.md`. ADR 0024, decisión 8, y ADR 0018.

**Bloqueado por:** 02.

**Status:** ready-for-agent

- [ ] El candado de "una prueba a la vez" vive en el servidor, en memoria del proceso. Si un reinicio lo suelta, a lo más se pierde una prueba a medias.
- [ ] Una segunda petición de probar, mientras corre otra, recibe un 409 que dice cuál está en curso, y no lanza ninguna búsqueda.
- [ ] `GET /api/sesiones` dice si hay una prueba en curso, y para cada tarjeta si se puede probar y, si no, por qué.
- [ ] Mientras corre una prueba, los botones de probar de todas las tarjetas se ven apagados con su motivo. Eso incluye los de otra computadora la próxima vez que pinte.
- [ ] La pantalla muestra que hay una prueba corriendo, porque puede tardar medio minuto.
- [ ] El botón de probar del portal que espera en el visor queda apagado, con su motivo. Si se pide probar solo ese portal, la ruta se niega y dice por qué.
- [ ] El candado se suelta también cuando la prueba falla: Doyle caído no deja los botones apagados para siempre.
- [ ] Las pruebas de la API cubren: el 409 con una prueba en curso; el candado se suelta tras éxito y tras falla; el portal en el visor se rechaza; `GET /api/sesiones` refleja los dos casos.
