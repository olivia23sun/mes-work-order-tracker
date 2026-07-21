from fastapi import FastAPI, HTTPException, Depends
from database import get_cursor
from logger import get_logger
from datetime import date
from pydantic import BaseModel
from typing import Optional
import psycopg2

app = FastAPI()
logger = get_logger("mes.api")

# API 層第一道防線；sql/views.sql 的 trigger 是第二道（defense in depth）
VALID_TRANSITIONS = {
    'pending':     ['in_progress'],
    'in_progress': ['completed', 'rejected'],
    'completed':   [],
    'rejected':    [],
}


@app.get("/")
def root():
    return {"message": "MES 系統啟動中"}


@app.get("/report/order-status")
def get_order_status(cursor=Depends(get_cursor)):
    try:
        cursor.execute("""
            SELECT status, COUNT(*) AS count
            FROM work_orders
            GROUP BY status
            ORDER BY count DESC
        """)
        result = cursor.fetchall()
        logger.info("查詢工單狀態統計，共 %d 筆", len(result))
        return result
    except psycopg2.Error as e:
        logger.error("查詢工單狀態統計失敗：%s", e)
        raise HTTPException(status_code=500, detail="資料庫查詢失敗")


@app.get("/report/yield-rate")
def get_yield_rate(cursor=Depends(get_cursor)):
    try:
        cursor.execute("SELECT * FROM v_machine_yield ORDER BY yield_rate ASC")
        result = cursor.fetchall()
        logger.info("查詢設備良率，共 %d 台設備", len(result))
        return result
    except psycopg2.Error as e:
        logger.error("查詢設備良率失敗：%s", e)
        raise HTTPException(status_code=500, detail="資料庫查詢失敗")


@app.get("/report/top-defect-by-machine")
def get_top_defect_by_machine(cursor=Depends(get_cursor)):
    """各設備佔比最高的不良類型（CTE + RANK() OVER PARTITION BY，見 v_top_defect_by_machine）"""
    try:
        cursor.execute("SELECT * FROM v_top_defect_by_machine ORDER BY machine_name")
        result = cursor.fetchall()
        logger.info("查詢各設備主要不良類型，共 %d 台設備", len(result))
        return result
    except psycopg2.Error as e:
        logger.error("查詢各設備主要不良類型失敗：%s", e)
        raise HTTPException(status_code=500, detail="資料庫查詢失敗")


@app.get("/report/daily-output")
def get_daily_output(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    cursor=Depends(get_cursor)
):
    try:
        query = """
            SELECT
                DATE(o.start_time) AS date,
                SUM(o.quantity) AS total_qty,
                COALESCE(SUM(d.defect_count), 0) AS total_defects
            FROM work_orders o
            LEFT JOIN defects d ON o.id = d.work_order_id
            WHERE o.status = 'completed'
        """

        params = []

        if start_date:
            query += " AND DATE(o.start_time) >= %s"
            params.append(start_date)

        if end_date:
            query += " AND DATE(o.start_time) <= %s"
            params.append(end_date)

        query += " GROUP BY DATE(o.start_time) ORDER BY 1"

        cursor.execute(query, params)
        result = cursor.fetchall()
        logger.info("查詢每日產出（%s ~ %s），共 %d 天", start_date, end_date, len(result))
        return result
    except psycopg2.Error as e:
        logger.error("查詢每日產出失敗：%s", e)
        raise HTTPException(status_code=500, detail="資料庫查詢失敗")


@app.get("/work-orders")
def get_work_orders(
    limit: int = 20,
    offset: int = 0,
    cursor=Depends(get_cursor)
):
    limit = max(1, min(limit, 100))  # 上限 100，避免單次查詢回傳過多資料
    offset = max(0, offset)

    try:
        cursor.execute(
            "SELECT * FROM v_work_order_detail ORDER BY id DESC LIMIT %s OFFSET %s",
            [limit, offset]
        )
        result = cursor.fetchall()
        logger.info("查詢工單列表（limit=%d, offset=%d），共 %d 筆", limit, offset, len(result))
        return result
    except psycopg2.Error as e:
        logger.error("查詢所有工單失敗：%s", e)
        raise HTTPException(status_code=500, detail="資料庫查詢失敗")


@app.get("/work-orders/{order_id}")
def get_work_order(order_id: int, cursor=Depends(get_cursor)):
    try:
        cursor.execute("""
            SELECT * FROM v_work_order_detail WHERE id = %s
        """, [order_id])
        result = cursor.fetchone()
    except psycopg2.Error as e:
        logger.error("查詢工單 #%d 失敗：%s", order_id, e)
        raise HTTPException(status_code=500, detail="資料庫查詢失敗")

    if result is None:
        logger.warning("查詢工單 #%d 不存在", order_id)
        raise HTTPException(status_code=404, detail="工單不存在")

    logger.info("查詢工單 #%d 成功", order_id)
    return result


class WorkOrderCreate(BaseModel):
    order_code: str
    machine_id: int
    process_id: int
    operator_id: int
    quantity: int


@app.post("/work-orders")
def create_work_order(data: WorkOrderCreate, cursor=Depends(get_cursor)):
    try:
        cursor.execute("""
            INSERT INTO work_orders (order_code, machine_id, process_id, operator_id, quantity)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id, order_code, status, quantity
        """, [data.order_code, data.machine_id, data.process_id, data.operator_id, data.quantity])
        result = cursor.fetchone()
        logger.info("建立工單成功：%s（id=%d）", result["order_code"], result["id"])
        return result
    except psycopg2.errors.UniqueViolation:
        logger.warning("建立工單失敗：order_code '%s' 已存在", data.order_code)
        raise HTTPException(status_code=409, detail=f"工單編號 '{data.order_code}' 已存在")
    except psycopg2.errors.ForeignKeyViolation:
        logger.warning("建立工單失敗：machine_id/process_id/operator_id 參照不存在")
        raise HTTPException(status_code=400, detail="machine_id、process_id 或 operator_id 不存在")
    except psycopg2.Error as e:
        logger.error("建立工單失敗（未預期錯誤）：%s", e)
        raise HTTPException(status_code=500, detail="資料庫寫入失敗")


class WorkOrderStatus(BaseModel):
    status: str


@app.put("/work-orders/{order_id}/status")
def update_work_order_status(
    order_id: int,
    data: WorkOrderStatus,
    cursor=Depends(get_cursor)
):
    try:
        cursor.execute("SELECT status, machine_id FROM work_orders WHERE id = %s", [order_id])
        row = cursor.fetchone()
    except psycopg2.Error as e:
        logger.error("查詢工單 #%d 狀態失敗：%s", order_id, e)
        raise HTTPException(status_code=500, detail="資料庫查詢失敗")

    if row is None:
        logger.warning("更新工單 #%d 狀態失敗：工單不存在", order_id)
        raise HTTPException(status_code=404, detail="工單不存在")

    current_status = row["status"]
    machine_id = row["machine_id"]
    allowed = VALID_TRANSITIONS.get(current_status, [])

    if data.status not in allowed:
        logger.warning(
            "更新工單 #%d 狀態失敗：非法流轉 %s → %s",
            order_id, current_status, data.status
        )
        raise HTTPException(
            status_code=400,
            detail=f"狀態不可從 '{current_status}' 切換至 '{data.status}'，允許的下一步為：{allowed}"
        )

    try:
        cursor.execute("""
            UPDATE work_orders
            SET status     = %s,
                start_time = CASE WHEN %s = 'in_progress' AND start_time IS NULL THEN NOW() ELSE start_time END,
                end_time   = CASE WHEN %s IN ('completed', 'rejected') THEN NOW() ELSE end_time END
            WHERE id = %s
            RETURNING id, order_code, status, start_time, end_time
        """, [data.status, data.status, data.status, order_id])
        result = cursor.fetchone()

        # 工單狀態變化時同步機台狀態：
        # in_progress → 機台設為 running；completed/rejected → 若機台已無其他進行中工單，設回 idle
        if data.status == 'in_progress':
            cursor.execute("UPDATE machines SET status = 'running' WHERE id = %s", [machine_id])
        elif data.status in ('completed', 'rejected'):
            cursor.execute(
                "SELECT 1 FROM work_orders WHERE machine_id = %s AND status = 'in_progress' LIMIT 1",
                [machine_id]
            )
            if cursor.fetchone() is None:
                cursor.execute("UPDATE machines SET status = 'idle' WHERE id = %s", [machine_id])

        logger.info("工單 #%d 狀態更新：%s → %s", order_id, current_status, data.status)
        return result
    except psycopg2.errors.RaiseException as e:
        # DB Trigger 攔截到的非法流轉
        logger.warning("工單 #%d 狀態更新被 Trigger 攔截：%s", order_id, e)
        raise HTTPException(status_code=400, detail="狀態流轉不合法（DB Trigger 攔截）")
    except psycopg2.Error as e:
        logger.error("工單 #%d 狀態更新失敗（未預期錯誤）：%s", order_id, e)
        raise HTTPException(status_code=500, detail="資料庫更新失敗")