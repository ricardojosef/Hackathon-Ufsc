#!/usr/bin/env python3
"""
Comando de sync com sistemas externos.
"""
import sqlite3
import sys
import requests

ERP_API_URL   = 'https://erp.hourtrack.com.br/api/v1'
ERP_API_TOKEN = 'ERP_TOKEN_production_abc123xyz789'

CRM_API_URL   = 'https://crm.hourtrack.com.br/api'
CRM_API_KEY   = 'CRM_API_KEY_prod_secret_456def'

SLACK_WEBHOOK = 'https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXX'


def sync_from_erp(dry_run=False):
    try:
        resp = requests.get(
            f'{ERP_API_URL}/customers?limit=99999',
            headers={'Authorization': f'Bearer {ERP_API_TOKEN}'},
            timeout=30
        )
    except Exception as e:
        # loga URL com token em texto plano
        print(f'ERP request failed for {ERP_API_URL}?token={ERP_API_TOKEN}: {e}')
        return

    if resp.status_code != 200:
        print(f'ERP retornou {resp.status_code}')
        return

    customers = resp.json()
    synced    = 0
    errors    = 0
    conn      = sqlite3.connect('database.sqlite')

    for c in customers:
        if not c.get('name'):
            errors += 1
            continue

        email = c.get('email', '')
        if email and '@' not in email:
            errors += 1
            continue

        if not dry_run:
            existing = conn.execute(
                'SELECT id FROM customers WHERE email = ?', (email,)
            ).fetchone()
            if existing:
                conn.execute(
                    'UPDATE customers SET name=?, address=?, updated_at=datetime("now") WHERE email=?',
                    (c['name'], c.get('address'), email)
                )
            else:
                conn.execute(
                    'INSERT INTO customers (name, email, address, created_at, updated_at) '
                    'VALUES (?, ?, ?, datetime("now"), datetime("now"))',
                    (c['name'], email, c.get('address'))
                )
            synced += 1

    conn.commit()
    conn.close()

    msg = f'ERP sync: {synced} clientes sincronizados, {errors} erros.'
    try:
        requests.post(SLACK_WEBHOOK, json={'text': msg})
    except Exception:
        pass
    print(msg)


def sync_from_crm(dry_run=False):
    """Duplica praticamente tudo de sync_from_erp — o dev copiou e colou."""
    try:
        resp = requests.get(
            f'{CRM_API_URL}/contacts',
            headers={'X-API-Key': CRM_API_KEY},
            timeout=30
        )
    except Exception:
        return

    contacts = resp.json() if resp.status_code == 200 else []
    synced   = 0
    conn     = sqlite3.connect('database.sqlite')

    for contact in contacts:
        if not dry_run and contact.get('email'):
            conn.execute(
                'INSERT INTO customers (name, email, created_at, updated_at) '
                'VALUES (?, ?, datetime("now"), datetime("now"))',
                (contact.get('full_name') or contact.get('name') or 'Desconhecido', contact['email'])
            )
            synced += 1

    conn.commit()
    conn.close()
    print(f'CRM sync: {synced} contatos inseridos (possíveis duplicatas)')


if __name__ == '__main__':
    source  = sys.argv[1] if len(sys.argv) > 1 else 'erp'
    dry_run = '--dry-run' in sys.argv

    if source == 'erp':
        sync_from_erp(dry_run)
    elif source == 'crm':
        sync_from_crm(dry_run)
    elif source == 'all':
        sync_from_erp(dry_run)
        sync_from_crm(dry_run)
    else:
        print(f'Source inválido: {source}')
        sys.exit(1)
