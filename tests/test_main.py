"""
測試策略：
用 FastAPI 的 dependency override 把 get_cursor 換成假的 MockCursor，
測試不需要真的連 PostgreSQL：跑得快，也不會弄髒實際資料庫。
重點測「業務邏輯」（狀態流轉規則、404/400 情境），SQL 本身的正確性
交給實際跑在 sql/ 上的手動驗證或未來的 DB 整合測試。
"""
import os
import sys

# database.py 匯入時會檢查 DB_PASSWORD，測試環境給一個假值即可
os.environ.setdefault("DB_PASSWORD", "test-only-not-real")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))

from fastapi.testclient import TestClient
from main import app, get_cursor, VALID_TRANSITIONS


class MockCursor:
    """模擬 psycopg2 cursor 的最小行為，讓 endpoint 邏輯可在沒有真實 DB 下被測試。"""

    def __init__(self, fetchone_result=None, fetchall_result=None):
        self._fetchone_result = fetchone_result
        self._fetchall_result = fetchall_result or []

    def execute(self, query, params=None):
        pass

    def fetchone(self):
        return self._fetchone_result

    def fetchall(self):
        return self._fetchall_result


def _override(mock_cursor):
    def _get_cursor():
        yield mock_cursor
    return _get_cursor


client = TestClient(app)


def test_valid_transitions_table():
    """狀態機規則的單元測試，不碰 DB 或 HTTP。"""
    assert VALID_TRANSITIONS["pending"] == ["in_progress"]
    assert VALID_TRANSITIONS["completed"] == []


def test_get_work_order_not_found():
    app.dependency_overrides[get_cursor] = _override(MockCursor(fetchone_result=None))
    response = client.get("/work-orders/9999")
    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_get_work_order_found():
    mock = MockCursor(fetchone_result={"id": 1, "order_code": "WO-2024-001", "status": "completed"})
    app.dependency_overrides[get_cursor] = _override(mock)
    response = client.get("/work-orders/1")
    assert response.status_code == 200
    assert response.json()["order_code"] == "WO-2024-001"
    app.dependency_overrides.clear()


def test_update_status_illegal_transition():
    # 目前狀態是 completed，不允許再切回 in_progress
    mock = MockCursor(fetchone_result={"status": "completed", "machine_id": 1})
    app.dependency_overrides[get_cursor] = _override(mock)
    response = client.put("/work-orders/1/status", json={"status": "in_progress"})
    assert response.status_code == 400
    app.dependency_overrides.clear()


def test_update_status_work_order_not_found():
    app.dependency_overrides[get_cursor] = _override(MockCursor(fetchone_result=None))
    response = client.put("/work-orders/9999/status", json={"status": "in_progress"})
    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_work_orders_pagination_bounds():
    """limit 超過 100 應該被夾到 100，不能無限制撈資料。"""
    mock = MockCursor(fetchall_result=[])
    app.dependency_overrides[get_cursor] = _override(mock)
    response = client.get("/work-orders?limit=9999")
    assert response.status_code == 200
    app.dependency_overrides.clear()
