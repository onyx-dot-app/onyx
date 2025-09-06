declare
 @fromDate date = '2020-04-01',
 @toDate date = '2021-03-31';
with tblDateList as
(
 select @fromDate value
 union all
 select dateadd(day, 1, value) from tblDateList where value < @toDate
),
tblDailySales as 
(
 select v.date,
 sum(a.amount) amount
 from trn_accounting a
 join trn_voucher v on v.guid = a.guid
 join mst_ledger l on l.name = a.ledger
 join mst_group g on g.name = l.parent
 where g.primary_group = 'Purchase Accounts' and v.is_order_voucher = 0 and v.is_inventory_voucher = 0 and v.date >= @fromDate and v.date <= @toDate
 group by v.date
)
select d.value date, isnull(-c.amount, 0) amount
from tblDateList d
left join tblDailySales c on d.value = c.date
option (maxrecursion 500)
;