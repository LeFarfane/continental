-- La lista del viernes 25, solo con el viernes (decisión del dueño, 2026-09-28).
--
-- POR QUÉ. Ninguna lista se había cerrado nunca, así que cada una se armó desde
-- el 12 de septiembre (el piso del primer arranque): la del 25 llegó a 222
-- renglones. Esta noche se cierra sola al armarse la del sábado, y desde ahí
-- cada lista es de un día; lo que quedaba era dejar ESTA con su día.
--
-- QUÉ HACE, sin borrar nada (el rol no borra, y las lecturas de precio solo
-- crecen, ADR 0004):
--   1. Lo ya atendido (en tránsito, recibido) conserva lo que cubría: su
--      `ventas_desde` queda escrito en el 12. Sin esto, cambiar la ventana
--      encogería lo que vuelve si un tránsito se cancela (ADR 0013).
--   2. Lo abierto que no se vendió el viernes se DESCARTA, firmado por el dueño:
--      es su decisión no pedirlo, y sigue a la vista en "descartados".
--   3. Lo abierto que sí se vendió el viernes se AJUSTA a lo vendido ese día,
--      con la misma firma.
--   4. La ventana de la lista pasa a ser del 25 al 25.
--
-- Una sola transacción, con guardas: si la lista ya no es la que se midió en
-- el ensayo (218 abiertos: 202 sin venta el viernes, 16 con venta), no hace
-- nada. Se corre UNA vez, con credenciales de dueño:
--
--   docker exec -i farmacia_warehouse psql -U farmacia -d farmacia \
--       < sql/mantenimiento/2026-09-28-la-lista-del-viernes-solo-con-el-viernes.sql

\set ON_ERROR_STOP on
\set firma '''camarafarfan@gmail.com (limpieza del 2026-09-28: la lista solo con el viernes)'''

begin;

create temp table viernes on commit drop as
select v.producto_id, sum(v.cantidad) as piezas
  from marts.fct_ventas v
  join marts.dim_fecha f on f.fecha_id = v.fecha_id
 where f.fecha = date '2026-09-25'
 group by v.producto_id;

do $$
declare
    lista record;
    abiertos int;
    sin_venta int;
begin
    select * into lista from pedidos.pedido_sugerido where pedido_sugerido_id = 5;
    if lista.estado <> 'abierto' or lista.fecha_del_pedido <> date '2026-09-25'
       or lista.ventas_consideradas_desde <> date '2026-09-12' then
        raise exception 'la lista 5 ya no es la del ensayo: %', row_to_json(lista);
    end if;
    select count(*) into abiertos from pedidos.renglon
     where pedido_sugerido_id = 5 and estado = 'abierto';
    select count(*) into sin_venta from pedidos.renglon r
     where pedido_sugerido_id = 5 and estado = 'abierto'
       and not exists (select 1 from viernes v where v.producto_id = r.producto_id);
    if abiertos <> 218 or sin_venta <> 202 then
        raise exception 'no coincide con el ensayo: % abiertos, % sin venta el viernes', abiertos, sin_venta;
    end if;
end $$;

-- 1. Lo atendido conserva lo que cubría.
update pedidos.renglon
   set ventas_desde = date '2026-09-12'
 where pedido_sugerido_id = 5 and estado <> 'abierto' and ventas_desde is null;

-- 2. Lo que no se vendió el viernes, descartado.
update pedidos.renglon r
   set estado = 'descartado', descartado_por = :firma, descartado_en = now()
 where r.pedido_sugerido_id = 5 and r.estado = 'abierto'
   and not exists (select 1 from viernes v where v.producto_id = r.producto_id);

-- 3. Lo que sí, ajustado a lo vendido el viernes.
update pedidos.renglon r
   set cantidad_final = ceil(v.piezas)::int, ajustada_por = :firma, ajustada_en = now()
  from viernes v
 where r.pedido_sugerido_id = 5 and r.estado = 'abierto'
   and v.producto_id = r.producto_id
   and coalesce(r.cantidad_final, r.cantidad_propuesta) <> ceil(v.piezas)::int;

-- 4. La ventana.
update pedidos.pedido_sugerido
   set ventas_consideradas_desde = date '2026-09-25'
 where pedido_sugerido_id = 5;

do $$
begin
    if (select count(*) from pedidos.renglon where pedido_sugerido_id = 5 and estado = 'abierto') <> 16
       or (select count(*) from pedidos.renglon where pedido_sugerido_id = 5 and estado = 'descartado') <> 202 then
        raise exception 'el resultado no es el esperado: se deshace todo';
    end if;
end $$;

select estado, count(*) from pedidos.renglon where pedido_sugerido_id = 5 group by estado order by estado;

commit;
