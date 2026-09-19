# 02: Prefactor — prueba estática de compilación

**Qué construir:** una red de seguridad barata que atrapa la clase de fallo que ninguna prueba de comportamiento ve: un archivo que no compila, o un script con finales de línea de Windows que en atlas muere con un error incomprensible.

**Bloqueado por:** ninguno (puede empezar de inmediato).

**Status:** ready-for-agent

- [ ] `ast.parse` sobre todos los `.py` de `src/`.
- [ ] Ningún `.sh`, `.service` ni `.timer` tiene CRLF.
- [ ] Todo `.sh` tiene shebang.
- [ ] El docstring del archivo explica de dónde viene: en Marlowe nació de un servicio en bucle de reinicio con 148 pruebas en verde.
