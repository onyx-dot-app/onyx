declare
 @fromDate date = '2020-04-01',
 @toDate date = '2021-03-31';
with tblop as
(
 select a.ledger 'ledger', sum(a.amount) 'amount'
 from trn_accounting a
 join trn_voucher v on v.guid = a.guid
 where v.is_order_voucher = 0 and v.is_inventory_voucher = 0 and v.date < @fromDate
 group by a.ledger
),
tblcurr as
(
 select a.ledger 'ledger',
 sum(case when a.amount < 0 then abs(a.amount) else 0 end) 'debit',
 sum(case when a.amount > 0 then a.amount else 0 end) 'credit'
 from trn_accounting a
 join trn_voucher v on v.guid = a.guid
 where v.is_order_voucher = 0 and v.is_inventory_voucher = 0 and v.date between @fromDate and @toDate 
 group by a.ledger
)
select l.name,
(case when l.is_revenue = 0 then (l.opening_balance + isnull(op.amount,0)) else 0 end)  'opening',
isnull(curr.debit,0) 'debit',
isnull(curr.credit,0) 'credit',
(case when l.is_revenue = 0 then (l.opening_balance + isnull(op.amount,0)) + isnull(curr.credit,0) - isnull(curr.debit,0) else isnull(curr.credit,0) - isnull(curr.debit,0) end) 'closing'
from mst_ledger l
left join tblop op on op.ledger = l.name
left join tblcurr curr on curr.ledger = l.name
order by l.name
;