with bill_combined as
(
  select bill_date as date, ledger, name, opening_balance as amount, 'New Ref' as billtype, bill_credit_period
  from `tallydb.mst_opening_bill_allocation`
  union all
  select v.date, b.ledger, b.name, b.amount, b.billtype, bill_credit_period
  from `tallydb.trn_bill` as b
  join `tallydb.trn_voucher` as v on v.guid = b.guid
),
tbl_newref as
(
  select *
  from bill_combined
  where bill_combined.billtype in ('New Ref', 'Advance')
),
tbl_agstref as
(
  select *
  from bill_combined
  where bill_combined.billtype in ('Agst Ref')
),
tbl_outstanding as
(
  select
    nr.ledger,
    nr.name,
    coalesce(max(nr.amount), 0) as billed_amount,
    coalesce(sum(ar.amount), 0) as adjusted_amount,
    (coalesce(max(nr.amount), 0) + coalesce(sum(ar.amount), 0)) as outstanding_amount,
    (date_diff(current_date(),max(nr.date), day) - max(nr.bill_credit_period)) as overdue_days,
    date_add(max(nr.date),interval max(nr.bill_credit_period) day) as overdue_date,
    date_diff(current_date(),max(nr.date), day) as oustanding_days,
    max(nr.date) bill_date,
    max(nr.bill_credit_period) as bill_credit_period
  from tbl_newref as nr
  left join tbl_agstref as ar on (nr.ledger = ar.ledger and nr.name = ar.name)
  group by nr.ledger, nr.name
)
select
  bill_date as date,
  name as ref_number,
  ledger as party_name,
  -outstanding_amount as pending_amount,
  overdue_date as due_on,
  overdue_days as overdue_by_days
from tbl_outstanding
where outstanding_amount < 0
order by overdue_days desc