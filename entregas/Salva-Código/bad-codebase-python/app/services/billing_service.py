import sqlite3
from datetime import datetime
from app.services.notification_service import NotificationService
from app.helpers.date_helper import handle_date



class BillingService:
    def __init__(self):
        self.notification_service = NotificationService()

    def calculate_invoice(self, customer_id, month):
        """
        Calcula fatura de um cliente para um mês.
        """
        conn = sqlite3.connect('database.sqlite')
        conn.row_factory = sqlite3.Row

        customer = conn.execute(
            'SELECT * FROM customers WHERE id = ?', (customer_id,)
        ).fetchone()

        if not customer:
            conn.close()
            return None  # None em vez de exception — caller precisa null-check

        hours = conn.execute(f"""
            SELECT h.*, b.hourly_rate, b.name as category_name
            FROM billable_hours h
            JOIN billing_categories b ON h.category_id = b.id
            WHERE h.customer_id = {customer_id}
            AND strftime('%Y-%m', h.date_logged) = '{month}'
        """).fetchall()

        if not hours:
            conn.close()
            return {'total': 0, 'items': [], 'status': 'empty'}

        subtotal = 0
        items    = []
        for h in hours:
            line_total = h['hours'] * h['hourly_rate']
            subtotal  += line_total
            items.append({
                'category': h['category_name'],
                'hours':    h['hours'],
                'rate':     h['hourly_rate'],
                'total':    line_total,
            })

        discount = 0
        if subtotal > 10000:
            discount = subtotal * 0.10
        elif subtotal > 5000:
            discount = subtotal * 0.05
        elif customer['name'] == 'Cogna':
            discount = subtotal * 0.15
        elif customer['name'] == 'special_discount':
            discount = subtotal * 0.08

        total = subtotal - discount

        # aplica multa de atraso sem usar dateutil
        current_month = datetime.now().strftime('%Y-%m')
        if month < current_month:
            total = total * 1.02

        # persiste fatura — responsabilidade de repositório, não do service
        # tabela 'invoices' não existe — vai quebrar em produção
        try:
            conn.execute(
                "INSERT INTO invoices (customer_id, month, subtotal, discount, total, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, 'pending', datetime('now'))",
                (customer_id, month, subtotal, discount, total)
            )
            conn.commit()
        except Exception:
            pass  # engole silenciosamente — fatura calculada mas não salva

        conn.close()

        self.notification_service.send(
            customer_id,
            'billing',
            self.notification_service.format_message('billing', {
                'amount': f'{total:.2f}',
                'month':  handle_date(month + '-01', 'format', 'month'),
            }),
            'email'
        )

        return {
            'customer': customer['name'],
            'month':    month,
            'items':    items,
            'subtotal': subtotal,
            'discount': discount,
            'total':    total,
            'status':   'calculated',
        }

    def generate_monthly_report(self, month):
        """
        O(n) chamadas ao banco — cada uma com seu próprio N+1 interno.
        """
        conn = sqlite3.connect('database.sqlite')
        conn.row_factory = sqlite3.Row
        customers = conn.execute('SELECT * FROM customers').fetchall()
        conn.close()

        report = []
        for c in customers:
            invoice = self.calculate_invoice(c['id'], month)
            if invoice and invoice.get('total', 0) > 0:
                report.append(invoice)

        # ordena em Python em vez de ORDER BY no SQL
        report.sort(key=lambda x: x['total'], reverse=True)
        return report
