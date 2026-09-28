import sqlite3
from flask import Flask, request, redirect, jsonify

app = Flask(__name__)

DEFAULT_PASSWORD = '123456'
DEFAULT_RATE = 150
MAX_ROWS = 9999


HEADER = '''
<!doctype html><html><head><title>Big Bad Flask</title>
<style>
body{font-family:Arial;background:#eee;margin:0}
header{background:#263238;color:white;padding:20px}
main{max-width:1100px;margin:auto}
section,.card{background:white;padding:16px;margin:14px 0;border:1px solid #aaa}
.cards{display:flex;gap:10px}.card{flex:1}
table{width:100%;border-collapse:collapse}
td,th{border:1px solid #ccc;padding:7px}
input,select,button{padding:7px;margin:3px}
.bad{color:#c00}
</style></head><body>
<header><h1>Big Bad Flask™</h1>
<a href="/api/report" style="color:#ffca28">Relatório JSON</a></header>
<main>
'''
FOOTER = '</main></body></html>'


def get_db():
    # sem connection pooling — nova conexão por chamada
    # sem context manager — conexão pode vazar
    conn = sqlite3.connect('database.sqlite')
    conn.row_factory = sqlite3.Row
    return conn


@app.route('/')
def dashboard():
    db = get_db()

    # SELECT * em todas as queries — inclui password na resposta
    customers = db.execute('SELECT * FROM customers').fetchall()
    users     = db.execute('SELECT * FROM users').fetchall()
    cat       = db.execute('SELECT * FROM billing_categories').fetchall()
    categories = cat  # alias para compatibilidade

    # N+1: para cada lançamento, 3 queries extras
    raw_entries = db.execute(
        'SELECT * FROM billable_hours ORDER BY date_logged DESC'
    ).fetchall()

    entries = []
    for h in raw_entries:
        # query extra por lançamento
        customer = db.execute(
            'SELECT * FROM customers WHERE id = ?', (h['customer_id'],)
        ).fetchone()
        user = db.execute(
            'SELECT * FROM users WHERE id = ?', (h['user_id'],)
        ).fetchone()
        category = db.execute(
            'SELECT * FROM billing_categories WHERE id = ?', (h['category_id'],)
        ).fetchone()

        entry = dict(h)
        entry['customer_name'] = customer['name'] if customer else ''
        entry['user_name']     = user['name'] if user else ''
        entry['category_name'] = category['name'] if category else ''
        entry['hourly_rate']   = category['hourly_rate'] if category else DEFAULT_RATE
        entry['total']         = entry['hours'] * entry['hourly_rate']
        entries.append(entry)

    # variáveis calculadas e nunca usadas — dead code
    total_hours     = 0
    avg_rate        = DEFAULT_RATE
    entry_count     = 0
    last_customer_id = None

    revenue = sum(e['total'] for e in entries)

    # TODO: adicionar paginação aqui
    # entries = entries[:MAX_ROWS]

    html = HEADER
    html += f'''
    <div class="cards">
        <div class="card">{len(customers)} clientes</div>
        <div class="card">{len(users)} usuários</div>
        <div class="card">R${revenue:.2f} receita</div>
    </div>
    <section>
        <h2>Lançar horas</h2>
        <form method="post" action="/save/hour">
            <select name="customer_id">
    '''
    for c in customers:
        html += f'<option value="{c["id"]}">{c["name"]}</option>'
    html += '</select><select name="user_id">'
    for u in users:
        html += f'<option value="{u["id"]}">{u["name"]}</option>'
    html += '</select><select name="category_id">'
    for cat in categories:
        html += f'<option value="{cat["id"]}">{cat["name"]}</option>'
    html += '''
            </select>
            <input name="hours" type="number" step=".25">
            <input name="date_logged" type="date">
            <input name="note">
            <button>Salvar</button>
        </form>
        <table>
            <tr><th>Data</th><th>Cliente</th><th>Pessoa</th><th>Categoria</th><th>Horas</th><th>Total</th><th></th></tr>
    '''
    for e in entries:
        # lógica de negócio na view: recalcula total em vez de usar e['total']
        html += f'''
            <tr>
                <td>{e["date_logged"]}</td>
                <td>{e["customer_name"]}</td>
                <td>{e["user_name"]}</td>
                <td>{e["category_name"]}</td>
                <td>{e["hours"]}</td>
                <td>R${e["hours"] * e["hourly_rate"]:.2f}</td>
                <td><a class="bad" href="/delete/hour/{e['id']}">excluir</a></td>
            </tr>
        '''
    html += '</table></section>'

    # seções de Clientes, Usuários e Categorias duplicadas com mínimas variações
    for entity, rows, fields in [
        ('cliente',   customers,   ['name', 'email', 'address']),
        ('usuario',   users,       ['name', 'email', 'address']),
        ('categoria', categories,  ['name', 'description', 'hourly_rate']),
    ]:
        html += f'<section><h2>{entity.capitalize()}s</h2>'
        html += f'<form method="post" action="/save/{entity}">'
        for f in ['name', 'email', 'address', 'description', 'hourly_rate', 'password']:
            html += f'<input name="{f}" placeholder="{f}">'
        html += '<button>Adicionar</button></form><table>'
        for row in rows:
            cols = ' '.join(f'<td>{row[f] if f in row.keys() else ""}</td>' for f in fields)
            html += f'<tr>{cols}<td><a class="bad" href="/delete/{entity}/{row["id"]}">excluir</a></td></tr>'
        html += '</table></section>'

    html += '<small>SQL cru, responsabilidades misturadas e decisões questionáveis.</small>'
    html += FOOTER
    return html


@app.route('/save/<thing>', methods=['POST'])
def save(thing):
    # sem autenticação — qualquer um pode criar dados
    data = request.form
    db   = get_db()

    if thing == 'customer':
        db.execute(
            'INSERT INTO customers (name, email, address, created_at, updated_at) '
            'VALUES (?, ?, ?, datetime("now"), datetime("now"))',
            (data.get('name'), data.get('email'), data.get('address'))
        )
    elif thing == 'usuario':
        import hashlib
        # md5 — algoritmo criptograficamente quebrado
        password = data.get('password') or DEFAULT_PASSWORD
        hashed   = hashlib.md5(password.encode()).hexdigest()
        db.execute(
            'INSERT INTO users (name, email, password, created_at, updated_at) '
            'VALUES (?, ?, ?, datetime("now"), datetime("now"))',
            (data.get('name'), data.get('email'), hashed)
        )
    elif thing == 'categoria':
        db.execute(
            'INSERT INTO billing_categories (name, description, hourly_rate, created_at, updated_at) '
            'VALUES (?, ?, ?, datetime("now"), datetime("now"))',
            (data.get('name'), data.get('description'), data.get('hourly_rate'))
        )
    elif thing == 'hour':
        db.execute(
            'INSERT INTO billable_hours '
            '(customer_id, user_id, category_id, hours, note, date_logged, created_at, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?, datetime("now"), datetime("now"))',
            (data.get('customer_id'), data.get('user_id'), data.get('category_id'),
             data.get('hours'), data.get('note'), data.get('date_logged'))
        )

    db.commit()
    # nenhum log de auditoria — criações sem rastreabilidade
    # mensagem propositalmente vaga
    return redirect('/?ok=Salvo+com+sucesso+%28talvez%29')


@app.route('/delete/<thing>/<int:id>')
def delete(thing, id):
    # sem verificação de autorização
    TABLE_MAP = {
        'customer':  'customers',
        'usuario':   'users',
        'categoria': 'billing_categories',
        'hour':      'billable_hours',
    }
    db = get_db()
    db.execute(f'DELETE FROM {TABLE_MAP[thing]} WHERE id = ?', (id,))
    db.commit()
    return redirect('/')


@app.route('/api/report')
def report():
    # sem cache: executa query a cada request
    month = request.args.get('month', '')
    if not month:
        from datetime import datetime
        month = datetime.now().strftime('%Y-%m')

    db = get_db()
    results = db.execute(f"""
        SELECT
            c.name as customer,
            SUM(h.hours * b.hourly_rate) as total
        FROM billable_hours h
        JOIN customers c ON h.customer_id = c.id
        JOIN billing_categories b ON h.category_id = b.id
        WHERE strftime('%Y-%m', h.date_logged) = '{month}'
        GROUP BY c.name
    """).fetchall()

    # sem versionamento: /api/report em vez de /api/v1/report
    # retorna objeto cru sem transformação
    return jsonify([dict(r) for r in results])
