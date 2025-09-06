/* Account Statement */
with tblLedger as
(
 select v.guid, v.date, v.voucher_number, v.voucher_type, v.narration,
 (case when a.amount < 0 then -a.amount else 0 end) debit,
 (case when a.amount > 0 then a.amount else 0 end) credit
 from tallydb.trn_accounting a
 join tallydb.trn_voucher v on v.guid = a.guid
 where (a.ledger = 'Cash') and (v.is_order_voucher = 0 and v.is_inventory_voucher = 0) and (v.date between parse_date('%d-%m-%Y', '01-04-2020') and parse_date('%d-%m-%Y', '31-03-2021'))
 order by v.date
),
tblEntry as
(
 select v.guid, string_agg(distinct a.ledger) ledgers
 from tallydb.trn_voucher v
 join tallydb.trn_accounting a on (a.guid = v.guid and a.ledger <> 'Cash')
 where (v.guid in (select guid from tblLedger)) and (v.is_order_voucher = 0 and v.is_inventory_voucher = 0)
 group by v.guid
)
select l.date, l.date, l.voucher_type, l.voucher_number, c.ledgers ledgers
from tblLedger l
join tblEntry c on c.guid = l.guid
order by l.date
;