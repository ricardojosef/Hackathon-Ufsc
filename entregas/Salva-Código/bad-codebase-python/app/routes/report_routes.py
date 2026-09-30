import sqlite3
import csv
import io
from datetime import datetime
from flask import Blueprint, request, jsonify, Response
from app.services.billing_service import BillingService
import requests as http_client


report_bp = Blueprint('report', __name__)


class ReportController:
    def __init__(self):
        self.billing_service = BillingService()

    def monthly(self):
        """
        Duplica everything.report() com pequenas diferenças que criam inconsistência.
        """
        month       = request.args.get('month', datetime.now().strftime('%Y-%m'))
        fmt         = request.args.get('format', 'json')
        customer_id = request.args.get('customer_id')

        conn = sqlite3.connect('database.sqlite')
        conn.row_factory = sqlite3.Row

        if customer_id:
            results = conn.execute(f"""
                SELECT h.id, h.hours, h.note, h.date_logged,
                       c.name as customer, u.name as consultant,
                       b.name as category,
                       h.hours * b.hourly_rate as total
                FROM billable_hours h
                JOIN customers c ON h.customer_id = c.id
                JOIN users u ON h.user_id = u.id
                JOIN billing_categories b ON h.category_id = b.id
                WHERE h.customer_id = {customer_id}
                AND strftime('%Y-%m', h.date_logged) = '{month}'
                ORDER BY h.date_logged DESC
            """).fetchall()
        else:
            # query diferente da do everything.py — inconsistência de dados
            results = conn.execute(f"""
                SELECT c.name as customer,
                       COUNT(h.id) as entries,
                       SUM(h.hours) as total_hours,
                       SUM(h.hours * b.hourly_rate) as total
                FROM billable_hours h
                JOIN customers c ON h.customer_id = c.id
                JOIN billing_categories b ON h.category_id = b.id
                WHERE strftime('%Y-%m', h.date_logged) = '{month}'
                GROUP BY c.id, c.name
                ORDER BY total DESC
            """).fetchall()

        conn.close()
        data = [dict(r) for r in results]

        if fmt == 'json':
            return jsonify(data)
        elif fmt == 'csv':
            if not data:
                return Response('', mimetype='text/csv')
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=data[0].keys())
            writer.writeheader()
            for row in data:
                writer.writerow(row)  # não escapa vírgulas — quebra se nome tiver vírgula
            return Response(output.getvalue(), mimetype='text/csv')
        elif fmt == 'html':
            html = '<table border="1">'
            if data:
                html += '<tr>' + ''.join(f'<th>{k}</th>' for k in data[0].keys()) + '</tr>'
                for row in data:
                    html += '<tr>' + ''.join(f'<td>{v}</td>' for v in row.values()) + '</tr>'
            html += '</table>'
            return Response(html, mimetype='text/html')
        else:
            return jsonify({'error': 'formato inválido'}), 400

    def annual(self):
        """Chama generate_monthly_report 12 vezes — O(12n) queries ao banco."""
        year = request.args.get('year', datetime.now().strftime('%Y'))

        report      = {}
        grand_total = 0

        for m in range(1, 13):
            month      = f'{year}-{m:02d}'
            month_data = self.billing_service.generate_monthly_report(month)
            report[month] = month_data
            grand_total  += sum(inv.get('total', 0) for inv in month_data)

        return jsonify({'year': year, 'months': report, 'grand_total': grand_total})

    def export_for_accounting(self):
        """
        """
        month = request.args.get('month', datetime.now().strftime('%Y-%m'))

        ACCOUNTING_API_URL = 'https://api.contabilizei.com.br/v1/lancamentos'
        ACCOUNTING_TOKEN   = 'CONTABILIZEI_TOKEN_prod_123abc'

        conn = sqlite3.connect('database.sqlite')
        conn.row_factory = sqlite3.Row
        data = conn.execute(f"""
            SELECT * FROM billable_hours
            WHERE strftime('%Y-%m', date_logged) = '{month}'
        """).fetchall()
        conn.close()

        exported = 0
        for row in data:
            try:
                http_client.post(
                    ACCOUNTING_API_URL,
                    headers={'Authorization': f'Bearer {ACCOUNTING_TOKEN}'},
                    json={
                        'data':       row['date_logged'],
                        'valor':      row['hours'] * 150,
                        'descricao':  row['note'],
                        'cliente_id': row['customer_id'],
                    }
                )  # ignora resposta completamente
                exported += 1
            except Exception:
                pass

        return jsonify({'exported': exported})


_controller = ReportController()


@report_bp.route('/api/reports/monthly')
def monthly():
    return _controller.monthly()


@report_bp.route('/api/reports/annual')
def annual():
    return _controller.annual()


@report_bp.route('/api/reports/export')
def export_for_accounting():
    return _controller.export_for_accounting()
