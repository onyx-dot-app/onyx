/* Purchase Register (input for PIVOT table) */

select
	v.date,
	v.voucher_number,
	v.voucher_type,
	v.party_name,
	z.gstn,
	a.ledger,
	-a.amount amount
from trn_accounting a
join trn_voucher v on v.guid = a.guid
join mst_vouchertype t on v.voucher_type = t.name
join mst_ledger l on a.ledger = l.name
join mst_ledger z on v.party_name = z.name
where t.parent in ('Purchase') and a.ledger <> v.party_name
order by v.date, v.guid, a.amount