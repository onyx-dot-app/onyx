/* Sales Register (input for PIVOT table) */

select
	v.date,
	v.voucher_number,
	v.voucher_type,
	v.party_name,
	z.gstn,
	a.ledger,
	a.amount
from tallydb.trn_accounting a
join tallydb.trn_voucher v on v.guid = a.guid
join tallydb.mst_vouchertype t on v.voucher_type = t.name
join tallydb.mst_ledger l on a.ledger = l.name
join tallydb.mst_ledger z on v.party_name = z.name
where t.parent in ('Sales') and a.ledger <> v.party_name
order by v.date, v.guid, a.amount desc