# 01: El término de prueba en la configuración, y la sonda del lote lo usa

**Qué construir:** que exista una sola manera de comprobar una sesión: buscar «paracetamol 500». Hoy la sonda del lote nocturno busca SIGDAN por EAN (`clave_de_sonda`) y, si falta la clave, usa la del primer renglón con EAN de la lista del día. Con este ticket la sonda busca el término de prueba de la configuración, que también va a usar el botón «Probar» (ticket 02). Spec: `../spec.md`. ADR 0024, decisión 4, y ADR 0019.

**Bloqueado por:** ninguno (se puede empezar ya).

**Status:** ready-for-agent

- [ ] La configuración del pedido tiene el término de prueba, con valor «paracetamol 500», y `clave_de_sonda` desaparece. Su comentario dice por qué se busca por nombre y no por EAN, y remite al ADR 0024.
- [ ] La sonda del lote busca ese término en los cuatro proveedores, en una sola búsqueda, como ya lo hace hoy.
- [ ] Sin el término configurado, el lote se niega a correr y lo dice en el journal y en la corrida. El respaldo del "primer renglón con EAN de la lista" se quita.
- [ ] El discriminante sigue siendo `la sesión caducó`, y nada más: `sin resultados` y `no empareja` no detienen el lote.
- [ ] La sonda sigue sin escribir nada: ni precios ni el resultado de la prueba.
- [ ] `test_lote.py` cubre: el término configurado es el que se busca; sin término, el lote se niega ruidosamente; la sonda no escribe.
- [ ] La enmienda correspondiente queda anotada en el ADR 0019. Allí "la clave de la sonda es configuración" pasa a ser el término.
