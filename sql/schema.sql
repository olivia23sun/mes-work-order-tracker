-- 資料表關聯：
--   operators ──┐
--   machines  ──┼──► work_orders ◄── defects
--   processes ──┘

CREATE TABLE operators (
    id          INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        VARCHAR(50) NOT NULL,
    badge_no    VARCHAR(20) UNIQUE NOT NULL,
    shift       VARCHAR(10) CHECK (shift IN ('morning', 'afternoon', 'night')),
    created_at  TIMESTAMP DEFAULT NOW()
);

-- status 會隨關聯工單的狀態變化自動同步（見 api/main.py 的狀態更新端點）
CREATE TABLE machines (
    id            INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    machine_code  VARCHAR(20) UNIQUE NOT NULL,
    machine_name  VARCHAR(100) NOT NULL,
    location      VARCHAR(50),
    status        VARCHAR(20) DEFAULT 'idle' CHECK (status IN ('idle', 'running', 'maintenance')),
    created_at    TIMESTAMP DEFAULT NOW()
);

CREATE TABLE processes (
    id              INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    process_code    VARCHAR(20) UNIQUE NOT NULL,
    process_name    VARCHAR(100) NOT NULL,
    standard_time   INTERVAL,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- status 流轉規則：pending → in_progress → completed/rejected
-- 由 API 層 VALID_TRANSITIONS 與 DB 層 trigger 雙重把關
CREATE TABLE work_orders (
    id              INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_code      VARCHAR(30) UNIQUE NOT NULL,
    machine_id      INTEGER REFERENCES machines(id),
    process_id      INTEGER REFERENCES processes(id),
    operator_id     INTEGER REFERENCES operators(id),
    status          VARCHAR(20) DEFAULT 'pending'
                        CHECK (status IN ('pending', 'in_progress', 'completed', 'rejected')),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    start_time      TIMESTAMP,
    end_time        TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE defects (
    id              INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    work_order_id   INTEGER REFERENCES work_orders(id),
    defect_type     VARCHAR(50) NOT NULL,
    defect_count    INTEGER NOT NULL CHECK (defect_count > 0),
    reported_at     TIMESTAMP DEFAULT NOW()
);