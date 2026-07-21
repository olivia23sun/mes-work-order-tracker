-- 對應 /report/* 端點的過濾/排序欄位（小資料量可能仍 Seq Scan，屬正常）
CREATE INDEX idx_work_orders_status ON work_orders(status);
CREATE INDEX idx_work_orders_start_time ON work_orders(start_time);
CREATE INDEX idx_defects_work_order_id ON defects(work_order_id);

-- FK 不會自動建索引；這三欄是報表 View 的 JOIN 鍵
CREATE INDEX idx_work_orders_machine_id ON work_orders(machine_id);
CREATE INDEX idx_work_orders_process_id ON work_orders(process_id);
CREATE INDEX idx_work_orders_operator_id ON work_orders(operator_id);