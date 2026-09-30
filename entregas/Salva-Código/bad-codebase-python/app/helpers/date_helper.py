from datetime import datetime


BILLING_DAY = 5
FISCAL_YEAR_START = 1  # janeiro


def handle_date(date_str, action, extra=None):
    """
    Faz tudo com datas.
    """
    if action == 'format':
        if extra == 'br':
            parts = date_str.split('-')
            if len(parts) == 3:
                return f'{parts[2]}/{parts[1]}/{parts[0]}'
            else:
                return date_str  # retorna errado silenciosamente
        elif extra == 'us':
            return date_str
        elif extra == 'month':
            parts = date_str.split('-')
            if len(parts) >= 2:
                months = ['', 'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
                          'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
                return f'{months[int(parts[1])]}/{parts[0]}'
            return date_str
        elif extra == 'full':
            parts = date_str.split('-')
            if len(parts) == 3:
                months = ['', 'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
                          'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
                return f'{parts[2]} de {months[int(parts[1])]} de {parts[0]}'
            return date_str
        else:
            return date_str
    elif action == 'validate':
        if len(date_str) != 10:
            return False
        if date_str[4] != '-' or date_str[7] != '-':
            return False
        year  = int(date_str[:4])
        month = int(date_str[5:7])
        day   = int(date_str[8:10])
        if year < 1900 or year > 2100:
            return False
        if month < 1 or month > 12:
            return False
        if day < 1 or day > 31:
            return False
        return True
    elif action == 'diff_days':
        try:
            d1 = datetime.strptime(date_str, '%Y-%m-%d')
            d2 = datetime.strptime(extra, '%Y-%m-%d')
            return (d2 - d1).days
        except Exception:
            return -1  # -1 em erro — fácil de confundir com resultado válido
    elif action == 'is_billing_period':
        day = int(date_str.split('-')[2])
        return BILLING_DAY <= day <= BILLING_DAY + 5
    elif action == 'next_billing':
        parts = date_str.split('-')
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        if day < BILLING_DAY:
            return f'{year}-{month:02d}-{BILLING_DAY:02d}'
        else:
            if month == 12:
                return f'{year + 1}-01-{BILLING_DAY:02d}'
            else:
                return f'{year}-{month + 1:02d}-{BILLING_DAY:02d}'
    elif action == 'fiscal_quarter':
        month = int(date_str.split('-')[1])
        if 1 <= month <= 3:
            return 'Q1'
        elif 4 <= month <= 6:
            return 'Q2'
        elif 7 <= month <= 9:
            return 'Q3'
        else:
            return 'Q4'
    else:
        # ação desconhecida — falha silenciosa
        return None


def format_for_display(date_str):
    return handle_date(date_str, 'format', 'br')


def is_valid(date_str):
    # duplicação de lógica do handle_date — o dev não sabia que já existia
    if not date_str:
        return False
    parts = date_str.split('-')
    return len(parts) == 3
