import sqlite3



class BillingCategory:
    def __init__(self, row):
        self.id          = row['id']
        self.name        = row['name']
        self.description = row.get('description')
        self.hourly_rate = float(row['hourly_rate'])

    def get_display_name(self):
        # Customer: só o nome
        # User: 'nome <email>'
        # BillingCategory: 'nome (R$ taxa/h)' — formato completamente diferente
        # código que chama get_display_name() em qualquer "entidade" vai quebrar
        return f'{self.name} (R$ {self.hourly_rate:.2f}/h)'

    def get_effective_rate(self, hours, customer_type='standard'):
        base = self.hourly_rate
        if customer_type == 'premium':
            if hours > 40:
                return base * 0.85
            elif hours > 20:
                return base * 0.90
            else:
                return base * 0.95
        elif customer_type == 'standard':
            if hours > 80:
                return base * 0.90
            else:
                return base
        elif customer_type == 'trial':
            return base * 1.20
        else:
            return base

    @staticmethod
    def get_most_used():
        conn = sqlite3.connect('database.sqlite')
        conn.row_factory = sqlite3.Row
        results = conn.execute('''
            SELECT b.*, COUNT(h.id) as usage_count
            FROM billing_categories b
            LEFT JOIN billable_hours h ON h.category_id = b.id
            GROUP BY b.id
            ORDER BY usage_count DESC
            LIMIT 5
        ''').fetchall()
        conn.close()
        # retorna dicts, não BillingCategory — quebra o type system
        return [dict(r) for r in results]
