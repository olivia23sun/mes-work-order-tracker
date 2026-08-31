-- 報表 View 與工單狀態流轉 Trigger

-- 工單完整資訊。LEFT JOIN 而非 INNER JOIN：
-- 防禦性設計，避免任一關聯表（機台/製程/作業員）資料異常時，
-- 整筆工單從報表結果中消失（machine_id/process_id/operator_id 皆為 NOT NULL + FK，
-- 正常情況下不會真的缺漏，這裡是保守寫法）。
CREATE VIEW v_work_order_detail AS
SELECT
    wo.id,
    wo.order_code,
    m.machine_name,
    p.process_name,
    op.name AS operator_name,
    wo.status,
    wo.quantity,
    wo.start_time,
    wo.end_time
FROM work_orders wo
LEFT JOIN machines m   ON wo.machine_id  = m.id
LEFT JOIN processes p  ON wo.process_id  = p.id
LEFT JOIN operators op ON wo.operator_id = op.id;


-- 設備良率統計，僅計算已完成工單。
-- LEFT JOIN defects：零不良的工單本來就不會出現在 defects 表，
-- 用 INNER JOIN 會把這些「完美工單」漏算。
CREATE VIEW v_machine_yield AS
SELECT
    m.machine_name,
    SUM(wo.quantity) AS total_qty,
    COALESCE(SUM(d.total_defects), 0) AS total_defects,
    ROUND(
        (SUM(wo.quantity) - COALESCE(SUM(d.total_defects), 0))::NUMERIC
        / NULLIF(SUM(wo.quantity), 0) * 100
    , 2) AS yield_rate
FROM work_orders wo
JOIN machines m ON wo.machine_id = m.id
LEFT JOIN (
    SELECT 
        work_order_id, 
        SUM(defect_count) AS total_defects
    FROM defects
    GROUP BY work_order_id
) d ON wo.id = d.work_order_id
WHERE wo.status = 'completed'
GROUP BY m.id, m.machine_name;


-- 各設備最主要的不良類型：CTE 先彙總每台設備 x 每種不良類型的總數，
-- 再用 RANK() OVER (PARTITION BY machine_name ...) 在各設備內排名，取第一名。
CREATE VIEW v_top_defect_by_machine AS
WITH defect_summary AS (
    SELECT
        m.machine_name,
        d.defect_type,
        SUM(d.defect_count) AS total_defects
    FROM defects d
    JOIN work_orders wo ON d.work_order_id = wo.id
    JOIN machines m ON wo.machine_id = m.id
    GROUP BY m.machine_name, d.defect_type
),
ranked AS (
    SELECT
        machine_name,
        defect_type,
        total_defects,
        RANK() OVER (PARTITION BY machine_name ORDER BY total_defects DESC) AS rnk
    FROM defect_summary
)
SELECT machine_name, defect_type, total_defects
FROM ranked
WHERE rnk = 1;


-- 工單狀態流轉檢查（DB 層第二道防線，對應 api/main.py 的 VALID_TRANSITIONS）
CREATE OR REPLACE FUNCTION check_work_order_status_transition()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = OLD.status THEN
        RETURN NEW;
    END IF;

    IF NOT (
        (OLD.status = 'pending'     AND NEW.status = 'in_progress') OR
        (OLD.status = 'in_progress' AND NEW.status IN ('completed', 'rejected'))
    ) THEN
        RAISE EXCEPTION
            'Invalid status transition: % -> % (allowed: pending->in_progress->completed/rejected)',
            OLD.status, NEW.status;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_work_order_status_transition
BEFORE UPDATE OF status ON work_orders
FOR EACH ROW
EXECUTE FUNCTION check_work_order_status_transition();