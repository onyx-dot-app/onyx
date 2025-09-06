/* 
    Calculates balances of all Income Expenditure type ledgers
    
    Fields:
    group = Primary Group for the ledger (not to be confused with parent)
    ledger = Ledger name
    nature = [expense / income]
    affects_gross_profit = [Y/N] indicates if the ledger affects calculation of gross profit or not
*/
with tblOpeningStock as
(
	select
		'Opening Stock' as `group`,
		'Opening Stock' as `ledger`,
		'expense' as `nature`,
		'Y' as `affects_gross_profit`,
		coalesce(sum(opening_balance),0) as `balance`
	from tallydb.mst_ledger l
	join tallydb.mst_group g on g.name = l.parent
	where g.primary_group = 'Stock-in-hand'
),
tblClosingStock as
(
	select
		'Closing Stock' as `group`,
		'Closing Stock' as `ledger`,
		'income' as `nature`,
		'Y' as `affects_gross_profit`,
		coalesce(-sum(t.stock_value),0) as `balance`
	from
	(
		select ledger, stock_value, row_number() over(partition by ledger order by stock_date desc) ctr
		from tallydb.trn_closingstock_ledger
	) as t
	where t.ctr = 1
),
tblGroupBalance as
(
	select
		g.primary_group as `group`,
		l.name as `ledger`,
		(case when max(g.is_deemedpositive) = 1 then 'expense' else 'income' end) as `nature`,
		(case when max(g.affects_gross_profit) = 1 then 'Y' else 'N' end) as `affects_gross_profit`,
		sum(a.amount) `balance`
	from tallydb.trn_accounting a
	join tallydb.trn_voucher v on v.guid = a.guid
	join tallydb.mst_vouchertype t on v.voucher_type = t.name
	join tallydb.mst_ledger l on a.ledger = l.name
	join tallydb.mst_group g on g.name = l.parent
	where g.is_revenue = 1 and v.is_order_voucher = 0 and t.affects_stock = 0
	group by g.primary_group, l.name
)
select * from tblGroupBalance
union all
select * from tblOpeningStock
union all
select * from tblClosingStock