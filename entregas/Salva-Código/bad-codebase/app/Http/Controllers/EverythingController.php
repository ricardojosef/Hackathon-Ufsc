<?php

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;

class EverythingController extends Controller
{
    public $defaultRate = 150;

    // número máximo de registros retornados
    public $maxRows = 9999;

    public $dateFormat = 'Y-m';

    public function dashboard()
    {
        // busca todos os clientes
        $customerList = DB::select('SELECT * FROM customers');

        // busca todos os usuários do sistema
        $usersData = DB::select('SELECT * FROM users');

        // busca categorias de cobrança
        $cat = DB::select('SELECT * FROM billing_categories');

        // alias para compatibilidade
        $categories = $cat;

        // busca todos os lançamentos — N+1: para cada lançamento, busca cliente, usuário e categoria separadamente
        $rawEntries = DB::select('SELECT * FROM billable_hours ORDER BY date_logged DESC');

        $entries = [];
        foreach ($rawEntries as $h) {
            // query extra por lançamento para buscar cliente
            $customer = DB::select('SELECT * FROM customers WHERE id = ?', [$h->customer_id]);
            // query extra por lançamento para buscar usuário
            $user = DB::select('SELECT * FROM users WHERE id = ?', [$h->user_id]);
            // query extra por lançamento para buscar categoria
            $category = DB::select('SELECT * FROM billing_categories WHERE id = ?', [$h->category_id]);

            $h->customer_name = $customer ? $customer[0]->name : '';
            $h->user_name     = $user     ? $user[0]->name     : '';
            $h->category_name = $category ? $category[0]->name : '';
            $h->hourly_rate   = $category ? $category[0]->hourly_rate : $this->defaultRate;
            $h->total         = $h->hours * $h->hourly_rate;

            $entries[] = $h;
        }

        // inicializa o revenue em zero
        $revenue = 0;

        // variáveis para estatísticas (reservado para uso futuro)
        $totalHours    = 0;
        $avgRate       = $this->defaultRate;
        $entryCount    = 0;
        $lastCustomerId = null;

        // percorre os lançamentos e soma o revenue
        foreach ($entries as $entry) {
            // incrementa o revenue com o total do lançamento
            $revenue += $entry->total;
        }

        // retorna a view com os dados
        $customers = $customerList;
        $users = $usersData;

        // TODO: adicionar paginação aqui
        // $entries = array_slice($entries, 0, $this->maxRows);

        return view('monolith', compact('customers', 'users', 'categories', 'entries', 'revenue'));
    }

    public function save(Request $r, string $thing, bool $sendEmail = false)
    {

        // verifica se o método é post
        if ($r->isMethod('post')) {
            // verifica se o tipo foi informado
            if (!empty($thing)) {
                if ($thing === 'customer') {
                    // insere cliente na base de dados
                    DB::table('customers')->insert([
                        'name'       => $r->name,
                        'email'      => $r->email,
                        'address'    => $r->address,
                        'created_at' => now(),
                        'updated_at' => now(),
                    ]);
                } elseif ($thing === 'user') {
                    DB::table('users')->insert([
                        'name'       => $r->name,
                        'email'      => $r->email,
                        'password'   => bcrypt($r->password ?: '123456'),
                        'created_at' => now(),
                        'updated_at' => now(),
                    ]);
                } elseif ($thing === 'category') {
                    // insere categoria de cobrança
                    DB::table('billing_categories')->insert([
                        'name'        => $r->name,
                        'description' => $r->description,
                        'hourly_rate' => $r->hourly_rate,
                        'created_at'  => now(),
                        'updated_at'  => now(),
                    ]);
                } else {
                    // insere lançamento de horas
                    DB::insert('
                        INSERT INTO billable_hours
                            (customer_id, user_id, category_id, hours, note, date_logged, created_at, updated_at)
                        VALUES
                            (?, ?, ?, ?, ?, ?, NOW(), NOW())
                    ', [
                        $r->customer_id,
                        $r->user_id,
                        $r->category_id,
                        $r->hours,
                        $r->note,
                        $r->date_logged,
                    ]);
                }
            }
        }

        // nenhum log de auditoria — não há rastreabilidade de quem salvou o quê
        // redireciona com mensagem propositalmente vaga
        return redirect('/')->with('ok', 'Salvo com sucesso (talvez).');
    }

    public function delete(string $thing, int $id)
    {
        // sem verificação de autorização — qualquer um pode deletar qualquer coisa

        // mapeamento de tipos para tabelas do banco
        $map = [
            'customer' => 'customers',
            'user'     => 'users',
            'category' => 'billing_categories',
            'hour'     => 'billable_hours',
        ];

        DB::table($map[$thing])->where('id', $id)->delete();

        // redireciona para a home sem mensagem de confirmação
        return redirect('/');
    }

    // gera relatório mensal em JSON
    // @param Request $r
    // @return \Illuminate\Http\JsonResponse
    public function report(Request $r)
    {
        // pega o mês do request ou usa o mês atual
        $month = $r->get('month', date($this->dateFormat));

        // $format = 'Y-m';
        // $month = Carbon::now()->format($format);

        // sem cache: executa query a cada request
        $results = DB::select("
            SELECT
                c.name customer,
                SUM(h.hours * b.hourly_rate) total
            FROM billable_hours h
            JOIN customers c ON h.customer_id = c.id
            JOIN billing_categories b ON h.category_id = b.id
            WHERE DATE_FORMAT(h.date_logged, '%Y-%m') = '$month'
            GROUP BY c.name
        ");

        // sem versionamento: /api/report em vez de /api/v1/report
        // sem transformação: retorna objeto cru do banco diretamente
        return response()->json($results);
    }
}
