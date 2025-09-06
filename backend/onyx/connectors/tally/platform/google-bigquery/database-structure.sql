create table tallydb.config
(
 name string(64) not null,
 value string(1024)
);

create table tallydb.mst_group
(
 guid string(64) not null,
 name string(1024) not null,
 parent string(1024) not null,
 primary_group string(1024) not null,
 is_revenue tinyint,
 is_deemedpositive tinyint,
 is_reserved tinyint,
 affects_gross_profit tinyint,
 sort_position int
);

create table tallydb.mst_ledger
(
 guid string(64) not null,
 name string(1024) not null,
 parent string(1024) not null,
 alias string(256) not null,
 description string(64) not null,
 notes string(64) not null,
 is_revenue tinyint,
 is_deemedpositive tinyint,
 opening_balance decimal(17,2),
 closing_balance decimal(17,2),
 mailing_name string(256) not null,
 mailing_address string(1024) not null,
 mailing_state string(256) not null,
 mailing_country string(256) not null,
 mailing_pincode string(64) not null,
 email string(256) not null,
 it_pan string(64) not null,
 gstn string(64) not null,
 gst_registration_type string(64) not null,
 gst_supply_type string(64) not null,
 gst_duty_head string(16) not null,
 tax_rate decimal(9,4),
 bank_account_holder string(256) not null,
 bank_account_number string(64) not null,
 bank_ifsc string(64) not null,
 bank_swift string(64) not null,
 bank_name string(64) not null,
 bank_branch string(64) not null,
 bill_credit_period int not null
);

create table tallydb.mst_vouchertype
(
 guid string(64) not null,
 name string(1024) not null,
 parent string(1024) not null,
 numbering_method string(64) not null,
 is_deemedpositive tinyint,
 affects_stock tinyint
);

create table tallydb.mst_uom
(
 guid string(64) not null,
 name string(1024) not null,
 formalname string(256) not null,
 is_simple_unit tinyint not null,
 base_units string(1024) not null,
 additional_units string(1024) not null,
 conversion int not null
);

create table tallydb.mst_godown
(
 guid string(64) not null,
 name string(1024) not null,
 parent string(1024) not null,
 address string(1024) not null
);

create table tallydb.mst_stock_group
(
 guid string(64) not null,
 name string(1024) not null,
 parent string(1024) not null
);

create table tallydb.mst_stock_item
(
 guid string(64) not null,
 name string(1024) not null,
 parent string(1024) not null,
 alias string(256) not null,
 description string(64) not null,
 notes string(64) not null,
 part_number string(256) not null,
 uom string(32) not null,
 alternate_uom string(32) not null,
 conversion int not null,
 opening_balance decimal(15,4),
 opening_rate decimal(15,4),
 opening_value decimal(17,2),
 closing_balance decimal(15,4),
 closing_rate decimal(15,4),
 closing_value decimal(17,2),
 costing_method string(32) not null,
 gst_type_of_supply string(32),
 gst_hsn_code string(64),
 gst_hsn_description string(256),
 gst_rate decimal(9,4),
 gst_taxability string(32)
);

create table tallydb.mst_cost_category
(
 guid string(64) not null,
 name string(1024) not null,
 allocate_revenue tinyint,
 allocate_non_revenue tinyint
);

create table tallydb.mst_cost_centre
(
 guid string(64) not null,
 name string(1024) not null,
 parent string(1024) not null,
 category string(1024) not null
);

create table tallydb.mst_attendance_type
(
 guid string(64) not null,
 name string(1024) not null,
 parent string(1024) not null,
 uom string(32) not null,
 attendance_type string(64) not null,
 attendance_period string(64) not null
);

create table tallydb.mst_employee
(
 guid string(64) not null,
 name string(1024) not null,
 parent string(1024) not null,
 id_number string(256) not null,
 date_of_joining date,
 date_of_release date,
 designation string(64) not null,
 function_role string(64) not null,
 location string(256) not null,
 gender string(32) not null,
 date_of_birth date,
 blood_group string(32) not null,
 father_mother_name string(256) not null,
 spouse_name string(256) not null,
 address string(256) not null,
 mobile string(32) not null,
 email string(64) not null,
 pan string(32) not null,
 aadhar string(32) not null,
 uan string(32) not null,
 pf_number string(32) not null,
 pf_joining_date date,
 pf_relieving_date date,
 pr_account_number string(32) not null
);

create table tallydb.mst_payhead
(
 guid string(64) not null,
 name string(1024) not null,
 parent string(1024) not null,
 payslip_name string(1024) not null,
 pay_type string(64) not null,
 income_type string(64) not null,
 calculation_type string(32) not null,
 leave_type string(64) not null,
 calculation_period string(32) not null
);

create table tallydb.mst_gst_effective_rate
(
 item string(1024) not null,
 applicable_from date,
 hsn_description string(256) not null,
 hsn_code string(64) not null,
 rate decimal(9,4) not null,
 is_rcm_applicable tinyint,
 nature_of_transaction string(64) not null,
 nature_of_goods string(64) not null,
 supply_type string(64) not null,
 taxability string(64) not null
);

create table tallydb.mst_opening_batch_allocation
(
 name string(1024) not null,
 item string(1024) not null,
 opening_balance decimal(15,4),
 opening_rate decimal(15,4),
 opening_value decimal(17,2),
 godown string(1024) not null,
 manufactured_on date
);

create table tallydb.mst_opening_bill_allocation
(
 ledger string(1024) not null,
 opening_balance decimal(17,4),
 bill_date date,
 name string(1024) not null,
 bill_credit_period int not null,
 is_advance tinyint
);

create table tallydb.trn_closingstock_ledger
(
 ledger string(1024) not null,
 stock_date date,
 stock_value decimal(17,2) not null
);

create table tallydb.mst_stockitem_standard_cost
(
 item string(1024) not null,
 date date,
 rate decimal(15,4)
);

create table tallydb.mst_stockitem_standard_price
(
 item string(1024) not null,
 date date,
 rate decimal(15,4)
);

create table tallydb.trn_voucher
(
 guid string(64) not null,
 date date not null,
 voucher_type string(1024) not null,
 voucher_number string(64) not null,
 reference_number string(64) not null,
 reference_date date,
 narration string(4000) not null,
 party_name string(256) not null,
 place_of_supply string(256) not null,
 is_invoice tinyint,
 is_accounting_voucher tinyint,
 is_inventory_voucher tinyint,
 is_order_voucher tinyint
);

create table tallydb.trn_accounting
(
 guid string(64) not null,
 ledger string(1024) not null,
 amount decimal(17,2) not null,
 amount_forex decimal(17,2) not null,
 currency string(16) not null
);

create table tallydb.trn_inventory
(
 guid string(64) not null,
 item string(1024) not null,
 quantity decimal(15,4) not null,
 rate decimal(15,4) not null,
 amount decimal(17,2) not null,
 additional_amount decimal(17,2) not null,
 discount_amount decimal(17,2) not null,
 godown string(1024),
 tracking_number string(256),
 order_number string(256),
 order_duedate date
);

create table tallydb.trn_cost_centre
(
 guid string(64) not null,
 ledger string(1024) not null,
 costcentre string(1024) not null,
 amount decimal(17,2) not null
);

create table tallydb.trn_cost_category_centre
(
 guid string(64) not null,
 ledger string(1024) not null,
 costcategory string(1024) not null,
 costcentre string(1024) not null,
 amount decimal(17,2) not null
);

create table tallydb.trn_cost_inventory_category_centre
(
 guid string(64) not null,
 ledger string(1024) not null,
 item string(1024) not null,
 costcategory string(1024) not null,
 costcentre string(1024) not null,
 amount decimal(17,2) not null
);

create table tallydb.trn_bill
(
 guid string(64) not null,
 ledger string(1024) not null,
 name string(1024) not null,
 amount decimal(17,2) not null,
 billtype string(256) not null,
 bill_credit_period int not null
);

create table tallydb.trn_bank
(
 guid string(64) not null,
 ledger string(1024) not null,
 transaction_type string(32) not null,
 instrument_date date,
 instrument_number string(1024) not null,
 bank_name string(64) not null,
 amount decimal(17,2) not null,
 bankers_date date
);

create table tallydb.trn_batch
(
 guid string(64) not null,
 item string(1024) not null,
 name string(1024) not null,
 quantity decimal(15,4) not null,
 amount decimal(17,2) not null,
 godown string(1024),
 destination_godown string(1024),
 tracking_number string(1024)
);

create table tallydb.trn_inventory_accounting
(
 guid string(64) not null,
 ledger string(1024) not null,
 amount decimal(17,2) not null,
 additional_allocation_type string(32) not null
);

create table tallydb.trn_employee
(
 guid string(64) not null,
 category string(1024) not null,
 employee_name string(1024) not null,
 amount decimal(17,2) not null,
 employee_sort_order int not null
);

create table tallydb.trn_payhead
(
 guid string(64) not null,
 category string(1024) not null,
 employee_name string(1024) not null,
 employee_sort_order int not null,
 payhead_name string(1024) not null,
 payhead_sort_order int not null,
 amount decimal(17,2) not null
);

create table tallydb.trn_attendance
(
 guid string(64) not null,
 employee_name string(1024) not null,
 attendancetype_name string(1024) not null,
 time_value decimal(17,2) not null,
 type_value decimal(17,2) not null
);