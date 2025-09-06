SELECT
  DATE(2000,1,1) as date,
  'Opening Balance' as voucher_type,
  '' as voucher_number,
  l.name as ledger,
  l.opening_balance as amount,
  '' as party_name,
  g.primary_group as primary_group,
  'Opening Balance' as voucher_category
FROM `tallydb.mst_ledger` as l
INNER JOIN `tallydb.mst_group` AS g ON l.parent = g.name
WHERE l.opening_balance <> 0
UNION ALL
SELECT
  v.date,
  v.voucher_type,
  v.voucher_number,
  a.ledger,
  a.amount,
  v.party_name,
  g.primary_group,
  t.parent AS voucher_category
FROM `tallydb.trn_accounting` AS a
INNER JOIN `tallydb.trn_voucher` AS v ON a.guid = v.guid
INNER JOIN `tallydb.mst_vouchertype` AS t ON v.voucher_type = t.name
INNER JOIN `tallydb.mst_ledger` AS l ON a.ledger = l.name
INNER JOIN `tallydb.mst_group` AS g ON l.parent = g.name
WHERE
  v.is_order_voucher = 0
  AND v.is_inventory_voucher = 0