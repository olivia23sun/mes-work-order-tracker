# MES 工單追蹤系統

製造執行系統（MES）後端，用於追蹤生產工單、設備良率與每日產出。

## 專案特色

- 模擬 MES 工單管理流程
- 使用 PostgreSQL 設計關聯式資料模型
- 透過 View 建立生產報表
- 使用 FastAPI 提供 RESTful API
- 實作工單狀態控管與資料完整性約束

## 核心技術亮點

- **資料完整性**：DB 層以 `CHECK` Constraint 限制欄位合法值範圍（如 `status`、機台狀態），並用 `FOREIGN KEY` 約束確保工單與作業員、設備、製程的關聯不會指向不存在的資料。
- **雙層狀態流轉防護**：API 層透過 `VALID_TRANSITIONS` 字典驗證狀態流轉合法性；DB 層另設 Trigger `trg_work_order_status_transition`，確保即使繞過 API 直接操作資料庫，非法流轉仍會被攔截。
- **查詢效能優化**：針對報表常用的 `status`、`start_time` 欄位，以及三個 JOIN 用的外鍵（`machine_id`、`process_id`、`operator_id`，PostgreSQL 不會自動為 FK 建索引）建立 B-tree 索引，確保在工單數據增長時，報表查詢依然能維持低延遲。
- **防禦性程式設計**：於 API 層使用參數化查詢（`%s`）與 Pydantic 模型驗證，有效防止 SQL Injection 並確保輸入數據格式正確。
- **SQL 資料抽象化**：利用 SQL View 封裝複雜的報表統計邏輯（如 `v_machine_yield`、`v_top_defect_by_machine`），降低應用程式層的維護成本與重複代碼。
- **Dependency Injection 連線管理**：使用 FastAPI `Depends` 搭配 `get_cursor()` generator，統一管理資料庫連線生命週期，自動處理 commit / rollback / 關閉，消除連線洩漏風險。
- **集中式日誌**：`logger.py` 統一設定 console + `RotatingFileHandler`（單檔 5MB、保留 3 份），API 端點統一使用 logging 記錄主要操作與錯誤。

## 技術棧

| 類別 | 技術 |
|---|---|
| Backend | FastAPI |
| Database | PostgreSQL |
| Database Driver | psycopg2 |
| API Documentation | Swagger UI |
| SQL Features | View、Index、Constraint、Trigger |
| 測試 | pytest |
| 容器化 | Docker、Docker Compose |

## 功能

- 工單生命週期管理（pending → in_progress → completed / rejected）
- 雙層狀態流轉驗證（API 層 + DB Trigger）
- 不良品即時回報（限 in_progress 狀態工單）
- 設備良率報表
- 各設備不良數量最高的主要不良類型（CTE + Window Function）
- 每日產出趨勢，支援日期範圍篩選
- 不良品紀錄與工單關聯
- 狀態變更時自動記錄開始／結束時間，並同步機台運轉狀態

## 專案結構

```
├── api/
│   ├── main.py          # FastAPI 端點
│   ├── database.py      # PostgreSQL 連線 & Depends generator
│   ├── logger.py         # 集中式 logging 設定
│   └── Dockerfile
├── sql/
│   ├── schema.sql        # 資料表定義（DDL）
│   ├── seed_data.sql     # 開發用範例資料
│   ├── views.sql         # 報表 View & 狀態流轉 Trigger
│   └── indexes.sql       # 效能索引
├── docker/
│   └── init.sh           # 容器啟動時依序載入 schema/views/indexes/seed
├── tests/
│   ├── conftest.py
│   └── test_main.py      # pytest，透過 dependency override 模擬 DB
├── docker-compose.yml
└── requirements.txt
```

## 資料庫 Schema

```
operators ──┐
machines  ──┼──► work_orders ◄── defects
processes ──┘
```

| 資料表 | 說明 |
|---|---|
| `operators` | 作業員與班別資訊 |
| `machines` | 設備與狀態管理 |
| `processes` | 製程定義與標準工時 |
| `work_orders` | 核心工單，關聯所有實體 |
| `defects` | 不良品紀錄，關聯工單 |

## 設計考量

### 狀態管理

工單狀態透過雙層機制確保流轉正確性：

```
pending → in_progress → completed / rejected
```

- **API 層**：`VALID_TRANSITIONS` 字典定義合法下一步，非法請求回傳 400 與說明訊息
- **DB 層**：`trg_work_order_status_transition` Trigger 作為第二道防線，即使繞過 API 直接寫入 DB 也會被攔截

### 連線管理

使用 FastAPI `Depends` 搭配 `get_cursor()` generator 統一管理：

- 每次請求自動建立連線、yield cursor 給 endpoint 使用
- 正常結束自動 `commit`；發生例外自動 `rollback`
- `finally` 區塊保證連線必定關閉，消除連線洩漏

### 報表設計

將常用統計邏輯封裝於 SQL View：

- 工單完整資訊（`v_work_order_detail`）— 使用 `LEFT JOIN` 確保工單資料不因關聯資料異常而遺失
- 設備良率統計（`v_machine_yield`）
- 各設備主要不良類型（`v_top_defect_by_machine`）— CTE 先彙總各設備 × 不良類型總數，再以 `RANK() OVER (PARTITION BY machine_name ...)` 取每台設備排名第一的不良類型

降低 API 複雜度，也讓報表邏輯集中維護。

### 查詢效能

針對常用查詢欄位建立 Index：

- 工單狀態（`status`）
- 工單開始時間（`start_time`）
- 不良紀錄外鍵（`work_order_id`）
- 工單的三個關聯外鍵（`machine_id`、`process_id`、`operator_id`）— PostgreSQL 不會自動為 FOREIGN KEY 建索引，而這三個欄位正是各報表 View 的 JOIN 鍵

減少報表查詢的全表掃描成本。

### 資料完整性

透過資料庫層級約束確保資料正確性：

- `PRIMARY KEY`：確保各資料表具有唯一識別值
- `NOT NULL`：工單的 `order_code`、`quantity`、`machine_id`、`process_id`、`operator_id` 等必要欄位不得為 NULL
- `FOREIGN KEY`：確保工單與作業員、設備、製程，以及不良品與工單之間的關聯資料存在
- `CHECK Constraint`：限制工單狀態、數量及設備狀態等欄位的合法值範圍

## 環境設定

### 方法一：Docker 一鍵啟動（推薦）

```bash
docker-compose up --build 
```

會自動啟動 PostgreSQL、依序執行 `schema.sql` → `views.sql` → `indexes.sql` → `seed_data.sql`，並啟動 API 服務。

API 文件：`http://localhost:8000/docs`

### 方法二：手動設定

**1. 建立資料庫並載入 Schema**

```bash
psql -U postgres -c "CREATE DATABASE mes_db;"
psql -U postgres -d mes_db -f sql/schema.sql
psql -U postgres -d mes_db -f sql/views.sql
psql -U postgres -d mes_db -f sql/indexes.sql
psql -U postgres -d mes_db -f sql/seed_data.sql
```

**2. 設定資料庫連線**

預設使用環境變數，未設定時無法啟動（避免使用預設密碼）：

```bash
export DB_HOST=localhost
export DB_NAME=mes_db
export DB_USER=postgres
export DB_PASSWORD=your_password
```

**3. 啟動 API 伺服器**

```bash
pip install -r requirements.txt
cd api
uvicorn main:app --reload
```

API 文件：`http://localhost:8000/docs`

## 測試

使用 pytest，透過 `app.dependency_overrides` 模擬 DB cursor，不需連線真實 PostgreSQL：

```bash
pip install -r requirements.txt
pytest
```

涵蓋範圍：狀態流轉規則、404/400 錯誤情境、分頁邊界。SQL 本身的正確性交由手動驗證或未來的 DB 整合測試。

## API 端點

### 工單管理

| 方法 | 端點 | 說明 |
|---|---|---|
| `GET` | `/work-orders` | 查詢所有工單 |
| `GET` | `/work-orders/{id}` | 查詢單筆工單 |
| `POST` | `/work-orders` | 建立新工單 |
| `PUT` | `/work-orders/{id}/status` | 更新工單狀態 |
| `POST` | `/defects` | 回報不良品（僅限 in_progress 狀態工單） |

**POST `/work-orders` 請求格式：**
```json
{
  "order_code": "WO-2024-031",
  "machine_id": 1,
  "process_id": 2,
  "operator_id": 3,
  "quantity": 100
}
```

**PUT `/work-orders/{id}/status` 請求格式：**
```json
{ "status": "in_progress" }
```

有效狀態：`pending` → `in_progress` → `completed` / `rejected`

非法流轉會回傳 400，並說明當前狀態允許的下一步。

**POST `/defects` 請求格式：**
```json
{
  "work_order_id": 21,
  "defect_type": "毛邊",
  "defect_count": 3
}
```

非 `in_progress` 狀態的工單回報會回傳 400。

### 報表

| 方法 | 端點 | 說明 |
|---|---|---|
| `GET` | `/report/order-status` | 各狀態工單數量 |
| `GET` | `/report/yield-rate` | 各設備良率 |
| `GET` | `/report/top-defect-by-machine` | 各設備佔比最高的不良類型 |
| `GET` | `/report/daily-output` | 每日產出趨勢 |

**`/report/daily-output` 支援日期篩選：**
```
GET /report/daily-output?start_date=2024-01-02&end_date=2024-01-09
```

## Future Improvements

目前版本聚焦於 MES 核心業務邏輯與資料庫設計，尚未實作使用者身分驗證與授權機制，所有端點皆可直接存取。

- JWT 身分驗證
- 工單歷程追蹤（Audit Log）
- OEE（設備綜合效率）報表
- 前端 Dashboard 視覺化介面
