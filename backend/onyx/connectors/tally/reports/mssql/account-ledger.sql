/* Account Statement */
declare
 @ledger nvarchar(1024) = 'Cash',
 @fromDate date = '2020-04-01',
 @toDate date = '2021-03-31';
with tblLedger as
(
 select v.guid, v.date, v.voucher_number, v.voucher_type, v.narration,
 (case when a.amount < 0 then -a.amount else 0 end) 'debit',
 (case when a.amount > 0 then a.amount else 0 end) 'credit'
 from trn_accounting a
 join trn_voucher v on v.guid = a.guid
 where a.ledger = @ledger and v.is_accounting_voucher = 1 and (v.date between @fromDate and @toDate)
),
tblEntry as
(
 select v.guid, string_agg(a.ledger, ',') ledgers
 from trn_voucher v
 join trn_accounting a on (a.guid = v.guid and a.ledger <> @ledger)
 where v.guid in (select distinct guid from tblLedger) and v.is_order_voucher = 0 and v.is_inventory_voucher = 0
 group by v.guid
)
select l.date, l.voucher_number, l.voucher_type, c.ledgers ledgers, l.debit, l.credit, l.narration
from tblLedger l
join tblEntry c on c.guid = l.guid
order by l.date
;