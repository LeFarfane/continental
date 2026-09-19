# 19: Motivos del hueco, botón de completar y latido

**Qué construir:** que el encargado pueda arreglar solo lo que falló de noche, y que el dueño se entere si el lote no corrió. El silencio es el modo de falla que de verdad muerde.

**Bloqueado por:** 18.

**Status:** ready-for-human

- [x] La pantalla distingue tres motivos distintos: el lote se cortó por tiempo, el portal no contestó, la sesión caducó.
- [x] Un botón vuelve a consultar solo los precios que faltan, sin lanzar el lote completo.
- [ ] Si una sesión caducó, la pantalla lo dice con el botón que la abre, sin tener que entrar a otra aplicación.
- [ ] Latido a Uptime Kuma al terminar bien, con **monitor propio**, distinto del de la cadena de ventas y del de Marlowe: si compartieran monitor, una noche sin lote no avisaría nada.
- [x] Si falla el latido, la corrida **no** se aborta: marcar como rota una corrida buena es peor que perderse un latido.

---

## Qué quedó hecho, casilla por casilla

### 1. Los tres motivos distinguibles — MARCADA

Son seis y no tres, porque los tres que el ticket nombra no se podían
distinguir sin los otros tres. *El portal no contestó* y *la sesión caducó* ya
vivían en `pedidos.precio_de_proveedor.motivo` desde el ticket 12: son de un
**proveedor** de un renglón. *El lote se cortó por tiempo* es del **renglón
entero** y no existía en ningún lado; sale de `pedidos.corrida_del_lote`, la
quinta tabla que estrena este ticket (ADR 0007). Y para que ese tercero no se
confunda con lo que no es, hicieron falta: *el lote no corrió sobre esta lista*,
*la corrida del lote se cortó*, *el lote lo intentó y no pudo*, *el lote no lo
miró* y *no tiene código de barras*.

La regla es una **función pura con su tabla de casos**
(`faltantes.por_que_no_hay_lectura`), no un `if` del JavaScript: la pantalla
escribe la frase que llega.

**Demostrado:** `tests/test_motivos.py` (los seis motivos, `seguro=False`
cuando la noche tuvo tope **y** fallas, y que llegan hasta el JSON de la lista)
y un recorrido en el navegador real el 2026-09-19, con los dobles sembrados y
la corrida guardada, donde la fila escribió *"probablemente: al lote se le
acabó el tiempo — … Ojo: esa misma corrida dejó 1 renglón(es) que sí intentó y
no pudo consultar"*.

### 2. El botón de completar solo los faltantes — MARCADA

`POST /api/pedido-sugerido/{id}/completar`. **Faltar es más estrecho que estar
incompleto a propósito**: cada renglón son cuatro visitas a portales ajenos con
las credenciales del dueño, ~9 s por proveedor. Entran los que no tienen ni una
lectura y los que se consultaron, no dieron precio, y tienen un hueco de los
tres que se arreglan reintentando. **No entran** los que ya tienen un precio,
los que no tienen EAN, ni los huecos definitivos.

Consulta **uno tras otro en un solo hilo** —un hilo por faltante es lo que le
impediría a Doyle reutilizar el navegador— con su propio tope
(`pedido.completar.tope_minutos`, 20 min), distinto del del lote.

**Demostrado:** `tests/test_motivos.py` comprueba contra `doyle.pedidos` que se
consultaron **exactamente** los dos faltantes y ni una vez el que ya tenía
precio; en el navegador real el botón dijo *"Completar los 2 que faltan"*, se
apretó, y al recargar el renglón sin lectura traía sus cuatro precios y el
botón había pasado a *"Completar el que falta"*.

### 3. La sesión caducada con su botón — SIN MARCAR

**Lo que sí está, y funciona:** la pantalla dice a quién le caducó —y lo saca de
las lecturas congeladas, no del `guardada` de Doyle, que el 2026-09-19 decía
`guardada` para los cuatro con las cuatro caducadas—, con **dos botones por
proveedor**: *Abrir sesión* y *Ya entré*. Los dos pasan por Continental
(`POST /api/sesion/{proveedor}/abrir` y `/confirmar`), que se lo pide a Doyle
por HTTP. **Continental no abre un navegador** (regla 1 de `CLAUDE.md`).

**Lo que falta, y no lo arregla este repo:** abrir una sesión exige teclear
usuario y contraseña **en la ventana de Chrome que Doyle abre, en la máquina
donde Doyle corre** (ADR 0001 de Doyle, sin cambios). Hoy Doyle corre en la
torre y Continental va a atlas: hasta que Doyle se mude con su visor remoto
sobre Xvfb (su ADR 0008, sin hacer), esa ventana se abriría donde no hay nadie
sentado. Y no se pudo probar contra el Doyle real: las cuatro sesiones están
caducadas y arrancarlo estaba fuera del encargo.

**Qué falta para marcarla:** el ADR 0008 de Doyle, y después un recorrido con
una sesión abierta de verdad desde esta pantalla. Contra el doble está
demostrado de punta a punta (`tests/test_motivos.py` y el navegador real: el
aviso honesto `todavia_parece_login` incluido).

### 4. El latido con monitor propio — SIN MARCAR

**Lo que sí está:** `src/continental/latido.py` y el `finally` de
`correr_el_lote`. `up` cuando terminó, cuando se detuvo al tope —detenerse es
lo que se le pide— y cuando no hubo ventas; `down` cuando la corrida se cortó.
El `ping` lleva la duración de la corrida en milisegundos, que es lo que Kuma
grafica. El token vive en `KUMA_PUSH_URL_CONTINENTAL` del `.env` y **hay una
prueba que comprueba que ese nombre no aparezca en el YAML versionado**.

**Lo que falta:** crear el *push monitor* en Uptime Kuma es un paso de dueño en
su interfaz, y esa Kuma la comparten Marlowe y la cadena de farmacia-data.
Crearlo —o mandar un latido de prueba— habría escrito en un monitor que alguien
mira. **Los pasos están documentados campo por campo en
`docs/despliegue-en-atlas.md`, parte D**, con el intervalo, dónde va el
secreto, y el aviso de qué hacer con el fin de semana (el timer es `Mon-Fri`,
así que sin una ventana de mantenimiento el monitor se pone rojo todos los
sábados y eso enseña a ignorar el rojo).

Medido en atlas el 2026-09-19, en solo lectura: Kuma corre como el contenedor
`borde_kuma` en `127.0.0.1:3002`, `Up 12 days (healthy)`; farmacia-data usa
`KUMA_PUSH_URL` y Marlowe `KUMA_PUSH_URL_MARLOWE`, así que el nombre de aquí ya
es propio.

**Qué falta para marcarla:** que el dueño cree el monitor (D.1), pegue la URL
en el `.env` (D.2) y se vea un latido en su historial.

### 5. El latido que falla no aborta la corrida — MARCADA

`mandar_el_latido` **no tiene un solo `raise` hacia afuera** y su `except` es
de `BaseException`: quien la llama no necesita envolverla en otro `try`. Lo
mismo vale para la otra escritura del `finally`, la fila de
`pedidos.corrida_del_lote`, que va en su propio `try` (ADR 0007).

**Demostrado:** `tests/test_latido.py` — un `pedir` que revienta con
`RuntimeError`, `OSError`, `KeyboardInterrupt` y `SystemExit`; una corrida
entera con un Kuma caído que vuelve con sus ocho precios guardados; un `latir`
inyectado que **levanta** y tampoco la rompe; y un almacenamiento que rebota el
`INSERT` de la corrida con "permission denied" sin tumbar nada. Y el motivo que
se escribe es el **tipo** y nunca el texto: el texto de un error de `httpx`
lleva la URL completa, y la URL completa **es** el token del monitor.
