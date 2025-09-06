/* 
    Calculates balances of all Income Expenditure type ledgers
	Scenario: when closing stock is entered manually
    
    Fields:
    group = Primary Group for the ledger (not to be confused with parent)
    ledger = Ledger name
    nature = [expense / income]
    affects_gross_profit = [Y/N] indicates if the ledger affects calculation of gross profit or not
*/
with tblOpeningStock as
(
	select
		'Opening Stock' as 'group',
		'Opening Stock' as 'ledger',
		'expense' as 'nature',
		'Y' as 'affects_gross_profit',
		sum(opening_balance) as 'balance'
	from mst_ledger l
	join mst_group g on g.name = l.parent
	where g.primary_group = 'Stock-in-hand'
),
tblClosingStock as
(
	select
		'Closing Stock' as 'group',
		'Closing Stock' as 'ledger',
		'income' as 'nature',
		'Y' as 'affects_gross_profit',
		-sum(t.stock_value) as 'balance'
	from
	(
		select ledger, stock_value, row_number() over(partition by ledger order by stock_date desc) ctr
		from trn_closingstock_ledger
	) as t
	where t.ctr = 1
),
tblGroupBalance as
(
	select
		g.primary_group as 'group',
		l.name as 'ledger',
		(case when max(g.is_deemedpositive) = 1 then 'expense' else 'income' end) as 'nature',
		(case when max(g.affects_gross_profit) = 1 then 'Y' else 'N' end) as 'affects_gross_profit',
		sum(a.amount) 'balance'
	from trn_accounting a
	join trn_voucher v on v.guid = a.guid
	join mst_vouchertype t on v.voucher_type = t.name
	join mst_ledger l on a.ledger = l.name
	join mst_group g on g.name = l.parent
	where g.is_revenue = 1 and v.is_order_voucher = 0 and v.is_inventory_voucher = 0 and t.affects_stock = 0
	group by g.primary_group, l.name
)
select * from tblGroupBalance
union all
select * from tblOpeningStock
union all
select * from tblClosingStock