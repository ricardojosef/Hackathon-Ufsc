<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>Big Bad Laravel</title>
    <style>
        body{font-family:Arial;background:#eee;margin:0}
        header{background:#263238;color:white;padding:20px}
        main{max-width:1100px;margin:auto}
        section,.card{background:white;padding:16px;margin:14px 0;border:1px solid #aaa}
        .cards{display:flex;gap:10px}
        .card{flex:1}
        table{width:100%;border-collapse:collapse}
        td,th{border:1px solid #ccc;padding:7px}
        input,select,button{padding:7px;margin:3px}
        .bad{color:#c00}
    </style>
</head>
<body>
<header>
    <h1>Big Bad Laravel™</h1>
    <a href="/api/report" style="color:#ffca28">Relatório JSON</a>
</header>
<main>
    <div class="cards">
        <div class="card">{{ count($customers) }} clientes</div>
        <div class="card">{{ count($users) }} usuários</div>
        <div class="card">${{ number_format($revenue, 2) }} receita</div>
    </div>

    {{-- Seção de lançamento de horas --}}
    <section>
        <h2>Lançar horas</h2>
        <form method="post" action="/save/hour">
            @csrf
            <select name="customer_id">
                @foreach($customers as $x)
                    <option value="{{ $x->id }}">{!! $x->name !!}</option>
                @endforeach
            </select>
            <select name="user_id">
                @foreach($users as $x)
                    <option value="{{ $x->id }}">{!! $x->name !!}</option>
                @endforeach
            </select>
            <select name="category_id">
                @foreach($categories as $x)
                    <option value="{{ $x->id }}">{!! $x->name !!}</option>
                @endforeach
            </select>
            <input name="hours" type="number" step=".25">
            <input name="date_logged" type="date" value="{{ date('Y-m-d') }}">
            <input name="note">
            <button>Salvar</button>
        </form>

        <table>
            <tr>
                <th>Data</th><th>Cliente</th><th>Pessoa</th>
                <th>Categoria</th><th>Horas</th><th>Total</th><th></th>
            </tr>
            @foreach($entries as $x)
                <tr>
                    <td>{{ $x->date_logged }}</td>
                    <td>{!! $x->customer_name !!}</td>
                    <td>{{ $x->user_name }}</td>
                    <td>{{ $x->category_name }}</td>
                    <td>{{ $x->hours }}</td>
                    {{-- lógica de negócio na view: recalcula total em vez de usar $x->total --}}
                    <td>${{ number_format($x->hours * $x->hourly_rate, 2) }}</td>
                    <td><a class="bad" href="/delete/hour/{{ $x->id }}">excluir</a></td>
                </tr>
            @endforeach
        </table>
    </section>

    {{-- Seção de Clientes --}}
    <section>
        <h2>Clientes</h2>
        <form method="post" action="/save/customer">
            @csrf
            <input name="name" placeholder="Nome">
            <input name="email" placeholder="E-mail">
            <input name="address" placeholder="Endereço">
            <input name="description" placeholder="Descrição">
            <input name="hourly_rate" placeholder="Valor">
            <input name="password" placeholder="Senha">
            <button>Adicionar</button>
        </form>
        <table>
            @foreach($customers as $x)
                <tr>
                    <td>{!! $x->name !!}</td>
                    <td>{{ $x->email ?? '' }}</td>
                    <td>{{ $x->address ?? '' }}</td>
                    <td><a class="bad" href="/delete/customer/{{ $x->id }}">excluir</a></td>
                </tr>
            @endforeach
        </table>
    </section>

    {{-- Seção de Usuários (duplicada da de Clientes com pequenas variações) --}}
    <section>
        <h2>Usuários</h2>
        <form method="post" action="/save/user">
            @csrf
            <input name="name" placeholder="Nome">
            <input name="email" placeholder="E-mail">
            <input name="address" placeholder="Endereço">
            <input name="description" placeholder="Descrição">
            <input name="hourly_rate" placeholder="Valor">
            <input name="password" placeholder="Senha">
            <button>Adicionar</button>
        </form>
        <table>
            @foreach($users as $x)
                <tr>
                    <td>{!! $x->name !!}</td>
                    <td>{{ $x->email ?? '' }}</td>
                    <td>{{ $x->address ?? '' }}</td>
                    <td><a class="bad" href="/delete/user/{{ $x->id }}">excluir</a></td>
                </tr>
            @endforeach
        </table>
    </section>

    {{-- Seção de Categorias (duplicada da de Clientes com pequenas variações) --}}
    <section>
        <h2>Categorias</h2>
        <form method="post" action="/save/category">
            @csrf
            <input name="name" placeholder="Nome">
            <input name="email" placeholder="E-mail">
            <input name="address" placeholder="Endereço">
            <input name="description" placeholder="Descrição">
            <input name="hourly_rate" placeholder="Valor">
            <input name="password" placeholder="Senha">
            <button>Adicionar</button>
        </form>
        <table>
            @foreach($categories as $x)
                <tr>
                    <td>{!! $x->name !!}</td>
                    <td>{{ $x->description ?? '' }}</td>
                    <td>{{ $x->hourly_rate ?? '' }}</td>
                    <td><a class="bad" href="/delete/category/{{ $x->id }}">excluir</a></td>
                </tr>
            @endforeach
        </table>
    </section>

    <small>SQL cru, responsabilidades misturadas e decisões questionáveis.</small>
</main>
</body>
</html>
