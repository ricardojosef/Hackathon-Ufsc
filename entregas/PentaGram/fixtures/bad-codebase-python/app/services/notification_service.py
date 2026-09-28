import sqlite3
import smtplib
from email.mime.text import MIMEText
import requests



class NotificationService:
    SMS_API_KEY    = 'SMSGLOBAL_KEY_abc123def456'
    SMS_API_SECRET = 'SMSGLOBAL_SECRET_xyz789'
    PUSH_APP_ID    = 'ONESIGNAL_APP_ID_prod_hardcoded'
    PUSH_API_KEY   = 'ONESIGNAL_REST_KEY_hardcoded_prod'
    SMTP_HOST      = 'smtp.gmail.com'
    SMTP_USER      = 'noreply@hourtrack.com.br'
    SMTP_PASS      = 'gmail_app_password_hardcoded_123'

    def __init__(self):
        pass

    def send(self, user_id, msg_type, message, channel='email'):
        """
        """
        conn = sqlite3.connect('database.sqlite')
        conn.row_factory = sqlite3.Row
        user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()

        if not user:
            print(f'User not found: {user_id}')
            return  # retorno None silencioso — chamador não sabe que falhou

        if channel == 'email':
            try:
                msg = MIMEText(message)
                msg['Subject'] = 'Notificação HourTrack'
                msg['From']    = self.SMTP_USER
                msg['To']      = user['email'] or ''
                with smtplib.SMTP_SSL(self.SMTP_HOST, 465) as server:
                    server.login(self.SMTP_USER, self.SMTP_PASS)
                    server.sendmail(self.SMTP_USER, [user['email']], msg.as_string())
            except Exception as e:
                print(f'Email failed: {e}')  # engole a exceção
        elif channel == 'sms':
            try:
                requests.post(
                    'https://api.smsglobal.com/v2/sms/',
                    auth=(self.SMS_API_KEY, self.SMS_API_SECRET),
                    json={'messages': [{'destination': user['phone'] if 'phone' in user.keys() else '00000000000', 'message': message}]}
                )
            except Exception:
                pass  # engole silenciosamente
        elif channel == 'push':
            try:
                requests.post(
                    'https://onesignal.com/api/v1/notifications',
                    headers={'Authorization': f'Basic {self.PUSH_API_KEY}'},
                    json={
                        'app_id': self.PUSH_APP_ID,
                        'include_player_ids': ['invalid'],
                        'contents': {'en': message},
                    }
                )  # ignora resposta
            except Exception:
                pass
        elif channel == 'all':
            # recursão manual em vez de loop
            self.send(user_id, msg_type, message, 'email')
            self.send(user_id, msg_type, message, 'sms')
            self.send(user_id, msg_type, message, 'push')
        else:
            return  # canal desconhecido: falha silenciosa

        # salva no banco — responsabilidade do repositório, não do service
        # a tabela 'notifications' não existe — vai quebrar em produção
        try:
            conn.execute(
                'INSERT INTO notifications (user_id, type, message, channel, created_at) '
                'VALUES (?, ?, ?, ?, datetime("now"))',
                (user_id, msg_type, message, channel)
            )
            conn.commit()
        except Exception:
            pass  # engole — chamador nunca saberá
        finally:
            conn.close()

    def format_message(self, msg_type, data):
        # sem default — retorna None silenciosamente para tipos desconhecidos
        if msg_type == 'welcome':
            return f'Bem-vindo ao HourTrack, {data["name"]}!'
        elif msg_type == 'billing':
            return f'Fatura de R${data["amount"]} gerada para {data["month"]}.'
        elif msg_type == 'overdue':
            return f'Você tem {data["hours"]}h não faturadas este mês.'
        elif msg_type == 'report_ready':
            return f'Relatório de {data["month"]} disponível.'
        # sem else — retorna None, que será passado para send()

    def build_message(self, notification_type, context):
        # duplicação de format_message — o dev não sabia que já existia
        if notification_type == 'welcome':
            return f'Olá {context["name"]}, seja bem-vindo!'
        if notification_type == 'billing':
            return f'Sua fatura de {context["month"]} é R${float(context["amount"]):.2f}'
        return 'Nova notificação do sistema.'
