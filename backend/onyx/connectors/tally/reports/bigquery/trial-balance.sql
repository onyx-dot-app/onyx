with tblop as
(
 select a.ledger ledger, sum(a.amount) amount
 from tallydb.trn_accounting a
 join tallydb.trn_voucher v on v.guid = a.guid
 where v.is_order_voucher = 0 and v.is_inventory_voucher = 0 and v.date < parse_date('%d-%m-%Y', '01-04-2020')
 group by a.ledger
),
tblcurr as
(
 select a.ledger ledger,
 sum(case when a.amount < 0 then abs(a.amount) else 0 end) debit,
 sum(case when a.amount > 0 then a.amount else 0 end) credit
 from tallydb.trn_accounting a
 join tallydb.trn_voucher v on v.guid = a.guid
 where v.is_order_voucher = 0 and v.is_inventory_voucher = 0 and v.date between parse_date('%d-%m-%Y', '01-04-2020') and parse_date('%d-%m-%Y', '31-03-2021')
 group by a.ledger
)
select l.name,
if(l.is_revenue is true, (l.opening_balance + ifnull(op.amount,0)), 0) opening,
ifnull(curr.debit,0) debit,
ifnull(curr.credit,0) credit,
if(l.is_revenue is true, (l.opening_balance + ifnull(op.amount,0)) + ifnull(curr.credit,0) - ifnull(curr.debit,0) ,ifnull(curr.credit,0) - ifnull(curr.debit,0)) closing
from tallydb.mst_ledger l
left join tblop op on op.ledger = l.name
left join tblcurr curr on curr.ledger = l.name
order by l.name
;