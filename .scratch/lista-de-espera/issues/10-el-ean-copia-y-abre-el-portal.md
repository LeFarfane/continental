# 10: Un clic en el EAN copia y abre el portal

**What to build:** en la pantalla de captura, un clic en el EAN de un renglón
lo copia, como hoy, **y además** abre el portal de ese proveedor en una pestaña
nueva del navegador de la farmacia. En NADRO y VICMA cae ya en la búsqueda del
producto; en LEVIC y QuePharma abre su página de búsqueda para pegar. Ver el
spec, «El EAN que abre el portal», historias 42–49.

**Blocked by:** 01

**Status:** done

- [x] Continental pide a Doyle las direcciones de búsqueda (ruta del ticket 01)
      por su cliente de Doyle, y **el servidor arma el enlace** con el EAN del
      renglón. El navegador no manda ningún término (ADR 0026, punto 4).
- [x] La respuesta de la captura trae, por renglón, el enlace y si es «ya
      buscado» o «para pegar».
- [x] El título del botón dice qué va a pasar: «Copiar y abrir la búsqueda en
      NADRO» o «Copiar y abrir LEVIC para pegar».
- [x] El clic copia y abre en una ventana nombrada por proveedor (una pestaña
      por portal, no una por clic), con un enlace de respaldo si el navegador la
      bloquea.
- [x] Si Doyle no contesta o no tiene la dirección, el EAN se sigue copiando y
      la frase dice que no se pudo abrir el portal. Nunca un error crudo
      (reglas 4 y 5).
- [x] Pruebas: lo puro (armar el enlace en los dos modos), la ruta de punta a
      punta con el doble de Doyle (con y sin respuesta) y la estática del JS
      (copia y abre, ventana nombrada, respaldo).
