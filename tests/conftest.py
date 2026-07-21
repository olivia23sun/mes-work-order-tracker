import os
import sys
import tempfile

# 讓 import 不用連真的 DB / 不寫進正式 log 資料夾
os.environ.setdefault("DB_PASSWORD", "test_password_for_pytest")
os.environ.setdefault("LOG_DIR", tempfile.mkdtemp())

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
