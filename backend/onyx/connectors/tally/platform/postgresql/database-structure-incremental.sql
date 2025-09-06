create table _diff
(
 guid varchar(64) not null,
 alterid int not null
);

create table _delete
(
 guid varchar(64) not null
);

create table _vchnumber
(
 guid varchar(64) not null,
 voucher_number varchar(256) not null
);

create table config
(
 name varchar(64) not null primary key,
 value varchar(1024)
);

create table mst_group
(
 guid varchar(64) not null primary key,
 alterid int not null default 0,
 name varchar(1024) not null default '',
 parent varchar(1024) not null default '',
 _parent varchar(64) not null default '',
 primary_group varchar(1024) not null default '',
 is_revenue smallint,
 is_deemedpositive smallint,
 is_reserved smallint,
 affects_gross_profit smallint,
 sort_position int
);

create table mst_ledger
(
 guid varchar(64) not null primary key,
 alterid int not null default 0,
 name varchar(1024) not null default '',
 parent varchar(1024) not null default '',
 _parent varchar(64) not null default '',
 alias varchar(256) not null default '',
 description varchar(64) not null default '',
 notes varchar(64) not null default '',
 is_revenue smallint,
 is_deemedpositive smallint,
 opening_balance decimal(17,2) default 0,
 closing_balance decimal(17,2) default 0,
 mailing_name varchar(256) not null default '',
 mailing_address varchar(1024) not null default '',
 mailing_state varchar(256) not null default '',
 mailing_country varchar(256) not null default '',
 mailing_pincode varchar(64) not null default '',
 email varchar(256) not null default '',
 it_pan varchar(64) not null default '',
 gstn varchar(64) not null default '',
 gst_registration_type varchar(64) not null default '',
 gst_supply_type varchar(64) not null default '',
 gst_duty_head varchar(16) not null default '',
 tax_rate decimal(9,4) default 0,
 bank_account_holder varchar(256) not null default '',
 bank_account_number varchar(64) not null default '',
 bank_ifsc varchar(64) not null default '',
 bank_swift varchar(64) not null default '',
 bank_name varchar(64) not null default '',
 bank_branch varchar(64) not null default '',
 bill_credit_period int not null default 0
);

create table mst_vouchertype
(
 guid varchar(64) not null primary key,
 alterid int not null default 0,
 name varchar(1024) not null default '',
 parent varchar(1024) not null default '',
 _parent varchar(64) not null default '',
 numbering_method varchar(64) not null default '',
 is_deemedpositive smallint,
 affects_stock smallint
);

create table mst_uom
(
 guid varchar(64) not null primary key,
 alterid int not null default 0,
 name varchar(1024) not null default '',
 formalname varchar(256) not null default '',
 is_simple_unit smallint not null,
 base_units varchar(1024) not null,
 additional_units varchar(1024) not null,
 conversion int not null
);

create table mst_godown
(
 guid varchar(64) not null primary key,
 alterid int not null default 0,
 name varchar(1024) not null default '',
 parent varchar(1024) not null default '',
 _parent varchar(64) not null default '',
 address varchar(1024) not null default ''
);

create table mst_stock_group
(
 guid varchar(64) not null primary key,
 alterid int not null default 0,
 name varchar(1024) not null default '',
 parent varchar(1024) not null default '',
 _parent varchar(64) not null default ''
);

create table mst_stock_item
(
 guid varchar(64) not null primary key,
 alterid int not null default 0,
 name varchar(1024) not null default '',
 parent varchar(1024) not null default '',
 _parent varchar(64) not null default '',
 alias varchar(256) not null default '',
 description varchar(64) not null default '',
 notes varchar(64) not null default '',
 part_number varchar(256) not null default '',
 uom varchar(32) not null default '',
 _uom varchar(64) not null default '',
 alternate_uom varchar(32) not null default '',
 _alternate_uom varchar(64) not null default '',
 conversion int not null default 0,
 opening_balance decimal(15,4) default 0,
 opening_rate decimal(15,4) default 0,
 opening_value decimal(17,2) default 0,
 closing_balance decimal(15,4) default 0,
 closing_rate decimal(15,4) default 0,
 closing_value decimal(17,2) default 0,
 costing_method varchar(32) not null default '',
 gst_type_of_supply varchar(32) default '',
 gst_hsn_code varchar(64) default '',
 gst_hsn_description varchar(256) default '',
 gst_rate int default 0,
 gst_taxability varchar(32) default ''
);

create table mst_cost_category
(
 guid varchar(64) not null primary key,
 alterid int not null default 0,
 name varchar(1024) not null default '',
 allocate_revenue smallint,
 allocate_non_revenue smallint
);

create table mst_cost_centre
(
 guid varchar(64) not null primary key,
 alterid int not null default 0,
 name varchar(1024) not null default '',
 parent varchar(1024) not null default '',
 _parent varchar(64) not null default '',
 category varchar(1024) not null default ''
);

create table mst_attendance_type
(
 guid varchar(64) not null primary key,
 alterid int not null default 0,
 name varchar(1024) not null default '',
 parent varchar(1024) not null default '',
 _parent varchar(64) not null default '',
 uom varchar(32) not null default '',
 _uom varchar(64) not null default '',
 attendance_type varchar(64) not null default '',
 attendance_period varchar(64) not null default ''
);

create table mst_employee
(
 guid varchar(64) not null primary key,
 alterid int not null default 0,
 name varchar(1024) not null default '',
 parent varchar(1024) not null default '',
 _parent varchar(64) not null default '',
 id_number varchar(256) not null default '',
 date_of_joining date,
 date_of_release date,
 designation varchar(64) not null default '',
 function_role varchar(64) not null default '',
 location varchar(256) not null default '',
 gender varchar(32) not null default '',
 date_of_birth date,
 blood_group varchar(32) not null default '',
 father_mother_name varchar(256) not null default '',
 spouse_name varchar(256) not null default '',
 address varchar(256) not null default '',
 mobile varchar(32) not null default '',
 email varchar(64) not null default '',
 pan varchar(32) not null default '',
 aadhar varchar(32) not null default '',
 uan varchar(32) not null default '',
 pf_number varchar(32) not null default '',
 pf_joining_date date,
 pf_relieving_date date,
 pr_account_number varchar(32) not null default ''
);

create table mst_payhead
(
 guid varchar(64) not null primary key,
 alterid int not null default 0,
 name varchar(1024) not null default '',
 parent varchar(1024) not null default '',
 _parent varchar(64) not null default '',
 payslip_name varchar(1024) not null default '',
 pay_type varchar(64) not null default '',
 income_type varchar(64) not null default '',
 calculation_type varchar(32) not null default '',
 leave_type varchar(64) not null default '',
 calculation_period varchar(32) not null default ''
);

create table mst_gst_effective_rate
(
 item varchar(1024) not null default '',
 _item varchar(64) not null default '',
 applicable_from date,
 hsn_description varchar(256) not null default '',
 hsn_code varchar(64) not null default '',
 rate decimal(9,4) default 0,
 is_rcm_applicable smallint,
 nature_of_transaction varchar(64) not null default '',
 nature_of_goods varchar(64) not null default '',
 supply_type varchar(64) not null default '',
 taxability varchar(64) not null default ''
);

create table mst_opening_batch_allocation
(
 name varchar(1024) not null default '',
 item varchar(1024) not null default '',
 _item varchar(64) not null default '',
 opening_balance decimal(15,4) default 0,
 opening_rate decimal(15,4) default 0,
 opening_value decimal(17,2) default 0,
 godown varchar(1024) not null default '',
 _godown varchar(64) not null default '',
 manufactured_on date
);

create table mst_opening_bill_allocation
(
 ledger varchar(1024) not null default '',
 _ledger varchar(64) not null default '',
 opening_balance decimal(17,4) default 0,
 bill_date date,
 name varchar(1024) not null default '',
 bill_credit_period int not null default 0,
 is_advance smallint
);

create table trn_closingstock_ledger
(
 ledger varchar(1024) not null default '',
 _ledger varchar(64) not null default '',
 stock_date date,
 stock_value decimal(17,2) not null default 0
);

create table mst_stockitem_standard_cost
(
 item varchar(1024) not null default '',
 _item varchar(64) not null default '',
 date date,
 rate decimal(15,4) default 0
);

create table mst_stockitem_standard_price
(
 item varchar(1024) not null default '',
 _item varchar(64) not null default '',
 date date,
 rate decimal(15,4) default 0
);

create table trn_voucher
(
 guid varchar(64) not null primary key,
 alterid int not null default 0,
 date date not null,
 voucher_type varchar(1024) not null,
 _voucher_type varchar(64) not null default '',
 voucher_number varchar(64) not null default '',
 reference_number varchar(64) not null default '',
 reference_date date,
 narration varchar(4000) not null default '',
 party_name varchar(256) not null,
 _party_name varchar(64) not null default '',
 place_of_supply varchar(256) not null,
 is_invoice smallint,
 is_accounting_voucher smallint,
 is_inventory_voucher smallint,
 is_order_voucher smallint
);

create table trn_accounting
(
 guid varchar(64) not null default '',
 ledger varchar(1024) not null default '',
 _ledger varchar(64) not null default '',
 amount decimal(17,2) not null default 0,
 amount_forex decimal(17,2) not null default 0,
 currency varchar(16) not null default ''
);

create table trn_inventory
(
 guid varchar(64) not null default '',
 item varchar(1024) not null default '',
 _item varchar(64) not null default '',
 quantity decimal(15,4) not null default 0,
 rate decimal(15,4) not null default 0,
 amount decimal(17,2) not null default 0,
 additional_amount decimal(17,2) not null default 0,
 discount_amount decimal(17,2) not null default 0,
 godown varchar(1024),
 _godown varchar(64) not null default '',
 tracking_number varchar(256),
 order_number varchar(256),
 order_duedate date
);

create table trn_cost_centre
(
 guid varchar(64) not null default '',
 ledger varchar(1024) not null default '',
 _ledger varchar(64) not null default '',
 costcentre varchar(1024) not null default '',
 _costcentre varchar(64) not null default '',
 amount decimal(17,2) not null default 0
);

create table trn_cost_category_centre
(
 guid varchar(64) not null default '',
 ledger varchar(1024) not null default '',
 _ledger varchar(64) not null default '',
 costcategory varchar(1024) not null default '',
 _costcategory varchar(64) not null default '',
 costcentre varchar(1024) not null default '',
 _costcentre varchar(64) not null default '',
 amount decimal(17,2) not null default 0
);

create table trn_cost_inventory_category_centre
(
 guid varchar(64) not null default '',
 ledger varchar(1024) not null default '',
 _ledger varchar(64) not null default '',
 item varchar(1024) not null default '',
 _item varchar(64) not null default '',
 costcategory varchar(1024) not null default '',
 _costcategory varchar(64) not null default '',
 costcentre varchar(1024) not null default '',
 _costcentre varchar(64) not null default '',
 amount decimal(17,2) not null default 0
);

create table trn_bill
(
 guid varchar(64) not null default '',
 ledger varchar(1024) not null default '',
 _ledger varchar(64) not null default '',
 name varchar(1024) not null default '',
 amount decimal(17,2) not null default 0,
 billtype varchar(256) not null default '',
 bill_credit_period int not null default 0
);

create table trn_bank
(
 guid varchar(64) not null default '',
 ledger varchar(1024) not null default '',
 _ledger varchar(64) not null default '',
 transaction_type varchar(32) not null default '',
 instrument_date date,
 instrument_number varchar(1024) not null default '',
 bank_name varchar(64) not null default '',
 amount decimal(17,2) not null default 0,
 bankers_date date
);

create table trn_batch
(
 guid varchar(64) not null default '',
 item varchar(1024) not null default '',
 _item varchar(64) not null default '',
 name varchar(1024) not null default '',
 quantity decimal(15,4) not null default 0,
 amount decimal(17,2) not null default 0,
 godown varchar(1024),
 _godown varchar(64) not null default '',
 destination_godown varchar(1024),
 _destination_godown varchar(64) not null default '',
 tracking_number varchar(1024)
);

create table trn_inventory_accounting
(
 guid varchar(64) not null default '',
 ledger varchar(1024) not null default '',
 _ledger varchar(64) not null default '',
 amount decimal(17,2) not null default 0,
 additional_allocation_type varchar(32) not null default ''
);

create table trn_employee
(
 guid varchar(64) not null default '',
 category varchar(1024) not null default '',
 _category varchar(64) not null default '',
 employee_name varchar(1024) not null default '',
 _employee_name varchar(64) not null default '',
 amount decimal(17,2) not null default 0,
 employee_sort_order int not null default 0
);

create table trn_payhead
(
 guid varchar(64) not null default '',
 category varchar(1024) not null default '',
 _category varchar(64) not null default '',
 employee_name varchar(1024) not null default '',
 _employee_name varchar(64) not null default '',
 employee_sort_order int not null default 0,
 payhead_name varchar(1024) not null default '',
 _payhead_name varchar(64) not null default '',
 payhead_sort_order int not null default 0,
 amount decimal(17,2) not null default 0
);

create table trn_attendance
(
 guid varchar(64) not null default '',
 employee_name varchar(1024) not null default '',
 _employee_name varchar(64) not null default '',
 attendancetype_name varchar(1024) not null default '',
 _attendancetype_name varchar(64) not null default '',
 time_value decimal(17,2) not null default 0,
 type_value decimal(17,2) not null default 0
);