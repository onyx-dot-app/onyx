/*
  Daily Receipt and Payment (incl Contra)
*/
with tblCashMovement as 
(
 select v.date,
 sum(case when a.amount < 0 then -a.amount else 0 end) receipt,
 sum(case when a.amount > 0 then a.amount else 0 end) payment
 from tallydb.trn_accounting a
 join tallydb.trn_voucher v on v.guid = a.guid
 join tallydb.mst_ledger l on l.name = a.ledger
 join tallydb.mst_group g on g.name = l.parent
 join tallydb.mst_vouchertype t on t.name = v.voucher_type
 where
  (v.is_order_voucher = 0 and v.is_inventory_voucher = 0)
  and lower(g.primary_group) = 'cash-in-hand'
  and lower(t.parent) in ('receipt', 'payment', 'contra')
  and (v.date between parse_date('%d-%m-%Y', '01-04-2020') and parse_date('%d-%m-%Y', '31-03-2021'))
 group by v.date
)
select d.dt date, ifnull(c.receipt, 0) receipt, ifnull(c.payment, 0) payment
from (select * from unnest(generate_date_array(parse_date('%d-%m-%Y', '01-04-2020'), parse_date('%d-%m-%Y', '31-03-2021'), interval 1 day)) dt) d
left join tblCashMovement c on d.dt = c.date
order by d.dt
;