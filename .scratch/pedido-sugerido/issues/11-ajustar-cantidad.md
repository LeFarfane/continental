# 11: Ajustar la cantidad de un renglón

**Qué construir:** el encargado sabe cosas que el sistema no —que mañana es puente, que un cliente va a venir por una caja completa— y tiene que poder corregir la cantidad antes de pedir.

**Bloqueado por:** 08.

**Status:** ready-for-agent

- [ ] La cantidad de un renglón se puede cambiar mientras la lista esté `abierta`.
- [ ] Se guarda la cantidad propuesta por el sistema **y** la cantidad final, por separado: la diferencia entre las dos es lo que después dice si la reposición 1 a 1 está bien calibrada.
- [ ] Una cantidad de cero no es una forma de descartar: para eso está `descartado`.
- [ ] Queda registrado quién la cambió.
