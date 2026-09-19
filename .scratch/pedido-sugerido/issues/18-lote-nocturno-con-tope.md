# 18: El lote nocturno corre y respeta el tope

**Qué construir:** que en la mañana la lista ya traiga precios sin que nadie los pida. Consulta sola después de la cadena nocturna, en orden de importancia, y se detiene a los 60 minutos.

**Bloqueado por:** 15 · 16 · **bloqueo externo:** la columna de clase ABC en el catálogo (ADR 0018 de farmacia-data) y Doyle corriendo en atlas (ADR 0008 de Doyle).

**Status:** ready-for-agent

> **Los dos bloqueos externos SIGUEN PUESTOS al 2026-09-19** y por eso hay tres
> casillas sin marcar. No son olvidos ni trabajo a medias: lo que se podía
> construir de cada una está construido y probado, y debajo de cada casilla
> está escrito **qué falta exactamente** y **quién lo tiene que hacer**.
>
> - `marts.dim_producto` no tiene `clase_abc` (ADR 0018 de farmacia-data,
>   **aceptado y sin implementar**: la columna no aparece en un solo modelo de
>   `dbt/models`).
> - Doyle no está en atlas (`~/proyectos/` tiene `borde`, `Farmacia`, `Marlowe`
>   y `Sarabia`). El ADR 0008 de Doyle, el del navegador reutilizado por
>   proveedor, está sin hacer.
>
> Lo construido: `src/continental/lote.py`,
> `scripts/systemd/continental-lote.{service,timer}`, el invariante 4 de
> `src/continental/verificar.py`, `clase_abc` en `src/continental/almacen.py`,
> `sugerido.armar_la_lista`, y 54 pruebas en `tests/test_lote.py`.
> El porqué de cada decisión está en `docs/decisiones/0006`.

- [ ] Un timer de systemd lo dispara después de la cadena de las 20:30.

      **Escrito y probado; falta INSTALARLO en atlas.**
      `scripts/systemd/continental-lote.timer` (`OnCalendar=Mon-Fri 22:00`, 90
      minutos después de la cadena) y `continental-lote.service`
      (`Type=oneshot`, `TimeoutStartSec=75min` — sin esa línea systemd mataría
      el lote a los 90 segundos y el tope de 60 minutos no existiría). Las
      vigilan 14 casos de `tests/test_lote.py`, que comprueban la hora contra
      las 20:30, que el `[Install]` esté en el timer y no en la unidad, que no
      haya `Restart=`, y que no se finja un `After=farmacia-diario.service`
      que systemd ignoraría.

      **Qué falta, y no lo puede hacer un agente:** los pasos A.1 a A.8 de
      `docs/despliegue-en-atlas.md`. Continental **no está en atlas** y no
      tiene remoto de git, así que antes de instalar el timer hay que clonar el
      repo. Escribir en atlas estaba prohibido en este ticket: ahí corre
      Marlowe en producción.

      **Y ojo con el hilo abierto 5 de `HANDOVER.md`:** si el respaldo de SICAR
      se mueve a las ~20:15 (ADR 0017 de farmacia-data, en **propuesta**), la
      cadena se mueve a las 21:00 y **este timer se mueve a las 22:30 en el
      mismo movimiento**. Está escrito dentro del propio `.timer`, en
      mayúsculas, donde lo va a leer quien lo edite.

- [ ] Consulta en orden de importancia, leyendo la **clase ABC** del catálogo. Sin esa columna el orden especificado no se puede cumplir: es prerrequisito, no detalle.

      **BLOQUEADA POR EL ADR 0018 DE FARMACIA-DATA.** La columna no existe.

      Lo que sí está hecho: `lote.ordenar_por_importancia` es una **función
      pura** que recibe los renglones y su clase y devuelve el orden A-B-C con
      la urgencia como desempate estable, más **si ese orden es el que el
      ticket pidió**. Está probada entera con dobles que sí traen clase (9
      casos). `almacen.Producto.clase_abc` existe y hoy vale "no se sabe" en
      las 3,429 filas.

      Lo que el lote hace mientras tanto: **no reordena nada** —consulta en el
      orden de urgencia con el que la lista se guardó, que es el que la
      pantalla muestra— y **lo declara** en su bitácora con todas sus letras
      (`orden: SIN CUMPLIR — …`). No se inventó un orden alterno: el propio ADR
      0018 descartó "ordenar por la utilidad de la ventana" con su razón
      escrita.

      **Qué falta, y es una línea de este lado:** el día que `dbt build`
      materialice `clase_abc`, poner
      `almacen.LA_CLASE_ABC_ESTA_EN_DIM_PRODUCTO = True`. Nada más. La consulta
      de hoy ni siquiera nombra la columna, a propósito: un `select clase_abc`
      rebotaría con "column does not exist" y se llevaría por delante la lista
      del día entera.

      **Y nadie tiene que acordarse:** `python -m continental.verificar` —paso
      6 de `desplegar.sh`— mira las columnas reales de `marts.dim_producto` en
      cada despliegue y lo imprime como PENDIENTE, con el nombre de esa
      constante dentro. En cuanto la columna aparezca, el despliegue lo dice.

- [x] Se detiene a los 60 minutos. Lo que no alcanzó queda marcado como faltante por tope, no como error.

      El tope sale de `pedido.tope_lote_minutos` del YAML y se mira **antes de
      arrancar cada renglón**, nunca en medio de uno: cortar una consulta a la
      mitad dejaría a Doyle con navegadores abiertos y tiraría una búsqueda que
      ya costó ~9 s por proveedor. Lo que queda se anota con el motivo que ya
      existía, `no alcanzó el tiempo`, y la corrida acaba en `se acabó el
      tiempo` — **que no es un error: el proceso sale con cero**.

      Probado con el reloj inyectado (`ahora`/`dormir`), sin esperar una hora:
      `test_se_detiene_al_tope_de_sesenta_minutos` simula 3600 s en
      microsegundos y comprueba 6 consultados, 4 faltantes por tope y 6 —no 10—
      visitas a los portales. Ocho casos más cubren el borde (`>=` y no `>`),
      el tope en cero, que no se corte un renglón a la mitad, y que ninguno se
      caiga del resumen.

- [ ] Reutiliza el navegador por proveedor en vez de arrancar uno por consulta (ADR 0008 de Doyle), y respeta la cortesía entre productos.

      **NO SE PUEDE CERRAR EN ESTE REPO, y no por falta de trabajo: por la
      regla 1 de `CLAUDE.md`.** Continental no abre un navegador nunca. El
      navegador reutilizado por proveedor vive en Doyle (su ADR 0008, sin
      hacer: Doyle todavía corre en la torre y su `POST /api/buscar` arranca
      cuatro hilos por búsqueda). La cortesía entre productos también es suya:
      los 3 s medidos están dentro de su búsqueda, y repetirlos aquí gastaría
      del tope de 60 minutos sin que ningún portal lo notara.

      **Lo que de este lado sí depende, y está hecho:** no pedirle a Doyle
      cuatro búsquedas a la vez. El lote es **estrictamente secuencial** —un
      renglón, se espera a que termine, el siguiente— y eso es lo que le
      permite a Doyle reutilizar lo que tenga abierto; un lote concurrente
      sería justo lo que se lo impediría. Lo comprueba
      `test_el_lote_es_secuencial_y_por_eso_doyle_puede_reutilizar_el_navegador`,
      que exige pide/lee alternados y nunca dos "pide" seguidos.

      **Qué falta:** el ADR 0008 de Doyle, en el repo de Doyle.

- [x] Un proveedor que falla no tumba el lote: los otros tres siguen.

      Lo garantiza `precios.congelar`, que devuelve una lectura **por cada**
      proveedor del acuse —el que falló con su motivo, el que contestó con su
      precio— y las cuatro se guardan juntas.
      `test_un_proveedor_que_falla_no_tumba_el_renglon` lo comprueba de punta a
      punta: cuatro filas guardadas, tres con precio y una con `la sesión
      caducó`. Y va más allá de la casilla: un **renglón** entero que no se
      pudo consultar —Doyle caído para esa clave— tampoco tumba el lote
      (`test_un_renglon_que_no_se_pudo_consultar_no_tumba_el_lote`), y el
      motivo que viaja es el **tipo** de la falla y nunca su texto (regla 5).

- [x] La corrida queda en bitácora con cuántos renglones consultó, cuántos quedaron sin precio y por qué.

      **Son dos lugares con trabajos distintos, y está razonado en el ADR
      0006.** El `journal` de systemd (`journalctl -u continental-lote`) lleva
      el relato de la corrida: cuándo, cuántos en la lista, cuántos
      consultados, cuántos con precio, cuántos sin, el desglose por motivo con
      su explicación en palabras de persona, y si el orden se cumplió. Es donde
      esta casa ya mira "cómo le fue anoche" (farmacia-data lo hace igual con
      `farmacia-diario`). El *por qué* de cada hueco, además, **ya está en una
      tabla**: `pedidos.precio_de_proveedor.motivo`, con vocabulario cerrado y
      `CHECK`, contable con un `group by`.

      **No se estrenó ninguna tabla de bitácora**, y el ADR dice qué compraría
      —poder preguntar "¿corrió anoche?" con SQL desde la pantalla— y cuál es
      su condición de disparo. El resumen se escribe en un `finally`, así que
      sale **hasta cuando alguien mata el proceso**.

- [x] El lote no puede dejar la lista en un estado peor que antes de correr: si truena a la mitad, lo consultado se queda guardado.

      **Verificado, no supuesto.** `guardar_precios` es un `INSERT ... SELECT`
      sin `UNIQUE` (ADR 0004: la tabla **solo crece**) y se escribe en cuanto
      llega cada lectura; el rol no tiene `DELETE` (ADR 0003). Y el lote **no
      tiene un solo `UPDATE` de renglón**: lo único que escribe es la lista del
      día si no existía, más filas de precio.

      Demostrado matándolo a la mitad: `_AlmacenamientoQueMuere` lanza un
      `KeyboardInterrupt` en el tercer renglón y tres pruebas comprueban que
      las ocho filas de los dos primeros siguen ahí, que la lista queda con los
      mismos renglones, estados y cantidades que antes, y que la bitácora sale
      igual con lo que alcanzó a hacer. Una cuarta prueba
      (`test_el_lote_no_borra_ni_cambia_renglones`) vigila que el lote no llame
      a `descartar`, `devolver_a_abierto`, `ajustar_la_cantidad` ni `cerrar`:
      el día que alguien meta un "ya que estamos, cerramos la lista", se pone
      roja.
