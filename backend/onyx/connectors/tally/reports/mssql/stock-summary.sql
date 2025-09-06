with tblTrackingReco as
(
	select i.item, i.tracking_number,
		sum(case when t.parent in ('Receipt Note', 'Delivery Note') then abs(i.quantity) else 0 end) note,
		sum(case when t.parent not in ('Receipt Note', 'Delivery Note') then abs(i.quantity) else 0 end) invoice
	from trn_inventory i
	join trn_voucher v on v.guid = i.guid
	join mst_vouchertype t on v.voucher_type = t.name
	where i.tracking_number is not null
	group by i.item, i.tracking_number
),
tblEffects as
(
select
	i.item,
	sum(case when i.quantity > 0 then i.quantity else 0 end) in_qty,
	sum(case when i.quantity < 0 then -i.quantity else 0 end) out_qty
from trn_inventory i
join trn_voucher v on v.guid = i.guid
join mst_vouchertype t on v.voucher_type = t.name
left join tblTrackingReco r on (i.item = r.item and i.tracking_number = r.tracking_number)
where
	v.is_order_voucher = 0 and (i.tracking_number is null or (t.parent not in ('Receipt Note', 'Delivery Note') and (r.note = r.invoice)) or (t.parent in ('Receipt Note', 'Delivery Note') and (r.note > r.invoice)))
group by i.item
)
select
	s.name, s.parent, s.uom,
	s.opening_balance op_qty,
	coalesce(e.in_qty, 0) in_qty,
	coalesce(e.out_qty, 0) out_qty,
	(s.opening_balance + coalesce(e.in_qty, 0) - coalesce(e.out_qty, 0)) clo_bal
from mst_stock_item s
left join tblEffects e on s.name = e.item