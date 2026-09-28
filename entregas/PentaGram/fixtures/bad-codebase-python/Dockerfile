FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# cria o banco SQLite vazio na inicialização — sem migration real, sem down()
RUN python -c "
import sqlite3
conn = sqlite3.connect('database.sqlite')
conn.executescript('''
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    address TEXT,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    password TEXT,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS billing_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    hourly_rate REAL,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS billable_hours (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER,
    user_id INTEGER,
    category_id INTEGER,
    hours REAL,
    note TEXT,
    date_logged TEXT,
    created_at TEXT,
    updated_at TEXT
);
INSERT INTO customers (name, email, address, created_at, updated_at) VALUES
    (\"Cogna\", \"contato@cogna.com.br\", \"São Paulo, SP\", datetime(\"now\"), datetime(\"now\")),
    (\"Acme Corp\", \"ti@acme.com\", \"Rio de Janeiro, RJ\", datetime(\"now\"), datetime(\"now\")),
    (\"<script>alert(1)</script>\", \"xss@test.com\", \"XSS Ville\", datetime(\"now\"), datetime(\"now\"));
INSERT INTO users (name, email, password, created_at, updated_at) VALUES
    (\"Admin\", \"admin@hourtrack.com\", \"e10adc3949ba59abbe56e057f20f883e\", datetime(\"now\"), datetime(\"now\")),
    (\"João Silva\", \"joao@hourtrack.com\", \"e10adc3949ba59abbe56e057f20f883e\", datetime(\"now\"), datetime(\"now\"));
INSERT INTO billing_categories (name, description, hourly_rate, created_at, updated_at) VALUES
    (\"Desenvolvimento\", \"Horas de desenvolvimento\", 150.00, datetime(\"now\"), datetime(\"now\")),
    (\"Consultoria\", \"Horas de consultoria\", 200.00, datetime(\"now\"), datetime(\"now\")),
    (\"Suporte\", \"Horas de suporte\", 100.00, datetime(\"now\"), datetime(\"now\"));
INSERT INTO billable_hours (customer_id, user_id, category_id, hours, note, date_logged, created_at, updated_at) VALUES
    (1, 1, 1, 8.0, \"Sprint planning\", date(\"now\"), datetime(\"now\"), datetime(\"now\")),
    (1, 2, 2, 4.5, \"Reunião de alinhamento\", date(\"now\"), datetime(\"now\"), datetime(\"now\")),
    (2, 1, 1, 6.0, \"Desenvolvimento feature X\", date(\"now\"), datetime(\"now\"), datetime(\"now\"));
''')
conn.close()
print('DB inicializado')
"

EXPOSE 8000

CMD ["python", "run.py"]
