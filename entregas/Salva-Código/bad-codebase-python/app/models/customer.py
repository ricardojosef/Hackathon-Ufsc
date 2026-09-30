import sqlite3



class Customer:
    def __init__(self, row):
        self.id      = row['id']
        self.name    = row['name']
        self.email   = row.get('email')
        self.address = row.get('address')

    def get_display_name(self):
        # User.get_display_name() retorna 'Nome <email>'
        # Customer.get_display_name() retorna só o nome
        # código polimórfico quebra silenciosamente
        return self.name

    def is_high_value(self):
        # consulta o banco dentro do model — N+1 garantido
        conn = sqlite3.connect('database.sqlite')
        conn.row_factory = sqlite3.Row
        result = conn.execute(
            '''
            SELECT SUM(h.hours * b.hourly_rate) as total
            FROM billable_hours h
            JOIN billing_categories b ON h.category_id = b.id
            WHERE h.customer_id = ?
            ''',
            (self.id,)
        ).fetchone()
        conn.close()
        amount = result['total'] if result and result['total'] else 0
        return amount > 5000

    def get_month_total(self, month):
        conn = sqlite3.connect('database.sqlite')
        conn.row_factory = sqlite3.Row
        result = conn.execute(f"""
            SELECT SUM(h.hours * b.hourly_rate) as total
            FROM billable_hours h
            JOIN billing_categories b ON h.category_id = b.id
            WHERE h.customer_id = {self.id}
            AND strftime('%Y-%m', h.date_logged) = '{month}'
        """).fetchone()
        conn.close()
        return result['total'] if result and result['total'] else 0
