# 01: Doyle: ruta con las direcciones de búsqueda de cada portal

**What to build:** Doyle contesta, por HTTP y de solo lectura, a qué dirección
hay que ir para buscar en cada portal y si ese portal busca por dirección (el
término va en la URL) o por formulario. Es lo que Continental necesita para que
un clic en el EAN abra el portal (ticket 10) sin copiar la configuración de
Doyle en dos repos. **El cambio vive en el repo de Doyle**, no en Continental.
Ver el spec, sección «El EAN que abre el portal».

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Una ruta GET nueva en Doyle devuelve, por cada proveedor configurado, su
      clave, la dirección de búsqueda y si busca por dirección.
- [ ] La respuesta **no** incluye la dirección del login, usuarios,
      contraseñas, el perfil ni nada de la sesión; una prueba lo fija.
- [ ] Un proveedor sin dirección de búsqueda configurada se dice como tal, no
      se omite en silencio.
- [ ] Prueba de la ruta en el repo de Doyle, con su propia configuración de
      prueba (sin datos reales).
- [ ] Commit en el repo de Doyle, en español, con la línea de coautoría.
