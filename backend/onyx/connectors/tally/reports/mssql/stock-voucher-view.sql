SELECT
  DATEFROMPARTS(2000,1,1) AS date,
  '' as voucher_number,
  'Opening Balance' as voucher_type,
  b.item,
  b.opening_balance as quantity,
  b.opening_value as amount,
  b.godown as godown
FROM mst_opening_batch_allocation as b
UNION ALL
SELECT t.date, t.voucher_number, t.voucher_type, t.item, t.quantity, t.amount, t.godown
FROM
(
	SELECT
		v.date, v.voucher_number, v.voucher_type, i.item, i.quantity, i.amount, i.godown,
		(CASE WHEN i.tracking_number = '' THEN 1 ELSE ROW_NUMBER() OVER(PARTITION BY i.tracking_number, i.item ORDER BY v.date) END) AS repetition
	FROM trn_inventory as i
	JOIN trn_voucher as v on (v.guid = i.guid)
	WHERE v.is_order_voucher = 0
) AS t
WHERE t.repetition = 1