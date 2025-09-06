SELECT
  DATEFROMPARTS(2000,1,1) as date,
  /* MAKEDATE(2000,1,1) as date --MySQL */
  /* DATE '2000-01-01' as date --PostgreSQL */
  'Opening Balance' as voucher_type,
  '' as voucher_number,
  l.name as ledger,
  l.opening_balance as amount,
  '' as party_name,
  g.primary_group as primary_group,
  'Opening Balance' as voucher_category
FROM mst_ledger as l
INNER JOIN mst_group AS g ON l.parent = g.name
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
FROM trn_accounting AS a
INNER JOIN trn_voucher AS v ON a.guid = v.guid
INNER JOIN mst_vouchertype AS t ON v.voucher_type = t.name
INNER JOIN mst_ledger AS l ON a.ledger = l.name
INNER JOIN mst_group AS g ON l.parent = g.name
WHERE
  v.is_order_voucher = 0
  AND v.is_inventory_voucher = 0