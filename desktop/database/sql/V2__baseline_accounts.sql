-- Baseline chart of accounts (seed). Codes are configurable afterwards.
INSERT INTO accounts (code, name, name_ar, type, is_cash, is_system) VALUES
 ('1000','Cash on Hand','النقدية بالصندوق','ASSET',1,1),
 ('1010','Bank Account','الحساب البنكي','ASSET',0,1),
 ('1100','Accounts Receivable','الذمم المدينة','ASSET',0,1),
 ('1200','Inventory','المخزون','ASSET',0,1),
 ('1500','Fixed Assets','الأصول الثابتة','ASSET',0,1),
 ('2000','Accounts Payable','الذمم الدائنة','LIABILITY',0,1),
 ('2100','VAT Payable','ضريبة القيمة المضافة','LIABILITY',0,1),
 ('3000','Owner Equity','حقوق الملكية','EQUITY',0,1),
 ('4000','Sales Revenue','الإيرادات','REVENUE',0,1),
 ('4010','Sales Returns','مردودات المبيعات','REVENUE',0,1),
 ('5000','Cost of Goods Sold','تكلفة المبيعات','EXPENSE',0,1),
 ('6000','Salaries Expense','الرواتب','EXPENSE',0,1),
 ('6100','Rent Expense','الإيجار','EXPENSE',0,1),
 ('6200','Utilities Expense','المرافق','EXPENSE',0,1),
 ('6900','Other Expenses','مصروفات أخرى','EXPENSE',0,1)
ON CONFLICT(code) DO NOTHING;

INSERT INTO units (uuid, code, name, dimension, is_base) VALUES
 ('PIECE','PIECE','Piece','COUNT',1),
 ('PACK','PACK','Pack','COUNT',0),
 ('CARTON','CARTON','Carton','COUNT',0),
 ('BOX','BOX','Box','COUNT',0),
 ('BUNDLE','BUNDLE','Bundle','COUNT',0),
 ('KG','KG','Kilogram','MASS',1),
 ('G','G','Gram','MASS',0),
 ('L','L','Liter','VOLUME',1),
 ('ML','ML','Milliliter','VOLUME',0),
 ('BOTTLE','BOTTLE','Bottle','COUNT',0)
ON CONFLICT(code) DO NOTHING;

INSERT OR IGNORE INTO unit_conversions (uuid, from_unit, to_unit, numerator, denominator)
VALUES
 ('c-carton-pack','CARTON','PACK',12,1),
 ('c-pack-piece','PACK','PIECE',6,1),
 ('c-kg-g','KG','G',1000,1),
 ('c-l-ml','L','ML',1000,1);

INSERT OR IGNORE INTO expense_categories (name) VALUES
 ('rent'),('utilities'),('salaries'),('transport'),('maintenance'),('other');
