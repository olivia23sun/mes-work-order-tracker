import psycopg2
import os
from psycopg2.extras import RealDictCursor

# 密碼刻意不給預設值：沒設定就直接啟動失敗，不悄悄用空密碼連線
DB_PASSWORD = os.environ.get("DB_PASSWORD")
if DB_PASSWORD is None:
    raise RuntimeError("環境變數 DB_PASSWORD 未設定，請參考 README 設定後再啟動服務")


def get_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        database=os.environ.get("DB_NAME", "mes_db"),
        user=os.environ.get("DB_USER", "postgres"),
        password=DB_PASSWORD
    )


def get_cursor():
    """FastAPI Depends 用的連線管理 generator：自動 commit/rollback/關閉連線。"""
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()