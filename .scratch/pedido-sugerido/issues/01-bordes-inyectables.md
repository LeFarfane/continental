# 01: Prefactor — los dos bordes como dependencias inyectables

**Qué construir:** las dos cosas que Continental no controla —lo que lee del almacén y lo que le pregunta a Doyle— entran por una dependencia que se puede sustituir, y nada de eso ocurre al importar un módulo. Es el prefactor que hace posible la costura única de pruebas: haz fácil el cambio, luego haz el cambio fácil.

**Bloqueado por:** ninguno (puede empezar de inmediato).

**Status:** ready-for-agent

- [x] La lectura del almacén es una interfaz de solo lectura que devuelve **datos, no conexiones**: ventas de un rango, catálogo con anaquel y existencia, compras posteriores a una fecha.
- [x] El cliente de Doyle es una interfaz aparte: pedir una búsqueda, consultar su estado, listar sesiones.
- [x] Las dos se entregan por `Depends` de FastAPI y se sustituyen en pruebas con `app.dependency_overrides`.
- [x] **Ningún módulo abre una conexión, crea un motor ni verifica nada al importarse.** Marlowe paga ~100 líneas de fixture por hacerlo al revés.
- [x] Existen dobles de los dos bordes, usables desde cualquier prueba.
- [x] Ninguna prueba toca Postgres, y el suite corre en menos de un segundo.
