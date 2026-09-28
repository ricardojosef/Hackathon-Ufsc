<?php

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use App\Services\BillingService;
use App\Helpers\DateHelper;


class ReportController extends Controller
{
    private $billingService;

    public function __construct()
    {
        $this->billingService = new BillingService();
    }

    /**
     * Relatório mensal — duplica EverythingController::report()
     * com pequenas diferenças que criam comportamento inconsistente
     */
    public function monthly(Request $r)
    {
        $month = $r->get('month', date('Y-m'));
        $format = $r->get('format', 'json');
        $customerId = $r->get('customer_id', null);

        // mas com JOIN diferente que retorna colunas diferentes
        if ($customerId) {
            // quando filtrado por cliente: retorna detalhe
            $results = DB::select("
                SELECT
                    h.id,
                    h.hours,
                    h.note,
                    h.date_logged,
                    c.name as customer,
                    u.name as consultant,
                    b.name as category,
                    h.hours * b.hourly_rate as total
                FROM billable_hours h
                JOIN customers c ON h.customer_id = c.id
                JOIN users u ON h.user_id = u.id
                JOIN billing_categories b ON h.category_id = b.id
                WHERE h.customer_id = $customerId
                AND DATE_FORMAT(h.date_logged, '%Y-%m') = '$month'
                ORDER BY h.date_logged DESC
            ");
        } else {
            // sem filtro: retorna resumo por cliente
            // query diferente da do EverythingController — inconsistência de dados
            $results = DB::select("
                SELECT
                    c.name customer,
                    COUNT(h.id) as entries,
                    SUM(h.hours) as total_hours,
                    SUM(h.hours * b.hourly_rate) as total
                FROM billable_hours h
                JOIN customers c ON h.customer_id = c.id
                JOIN billing_categories b ON h.category_id = b.id
                WHERE DATE_FORMAT(h.date_logged, '%Y-%m') = '$month'
                GROUP BY c.id, c.name
                ORDER BY total DESC
            ");
        }

        if ($format == 'json') {
            return response()->json($results);
        } elseif ($format == 'csv') {
            // gera CSV manualmente sem usar League\Csv que já está instalado
            $csv = '';
            if (!empty($results)) {
                $csv .= implode(',', array_keys((array)$results[0])) . "\n";
                foreach ($results as $row) {
                    $csv .= implode(',', array_values((array)$row)) . "\n";
                    // não escapa vírgulas — quebra se nome tiver vírgula
                }
            }
            return response($csv, 200, ['Content-Type' => 'text/csv']);
        } elseif ($format == 'html') {
            $html = '<table border="1">';
            if (!empty($results)) {
                $html .= '<tr>';
                foreach (array_keys((array)$results[0]) as $col) {
                    $html .= '<th>' . $col . '</th>';
                }
                $html .= '</tr>';
                foreach ($results as $row) {
                    $html .= '<tr>';
                    foreach ((array)$row as $val) {
                        $html .= '<td>' . $val . '</td>';
                    }
                    $html .= '</tr>';
                }
            }
            $html .= '</table>';
            return response($html, 200, ['Content-Type' => 'text/html']);
        } else {
            return response()->json(['error' => 'formato inválido'], 400);
        }
    }

    /**
     * Relatório anual — chama generateMonthlyReport 12 vezes em loop
     * O(12n) queries ao banco
     */
    public function annual(Request $r)
    {
        $year = $r->get('year', date('Y'));
        $report = [];

        // loop de 12 chamadas — cada uma já tem seu próprio N+1 interno
        for ($m = 1; $m <= 12; $m++) {
            $month = $year . '-' . str_pad($m, 2, '0', STR_PAD_LEFT);
            $monthData = $this->billingService->generateMonthlyReport($month);
            $report[$month] = $monthData;
        }

        // calcula totais em PHP depois de carregar tudo
        $grandTotal = 0;
        foreach ($report as $month => $invoices) {
            foreach ($invoices as $invoice) {
                $grandTotal += $invoice['total'];
            }
        }

        return response()->json([
            'year'        => $year,
            'months'      => $report,
            'grand_total' => $grandTotal,
        ]);
    }

    /**
     * Exporta dados para "integração com sistema externo"
     */
    public function exportForAccounting(Request $r)
    {
        $month = $r->get('month', date('Y-m'));

        $accountingApiUrl = 'https://api.contabilizei.com.br/v1/lancamentos';
        $accountingToken  = 'CONTABILIZEI_TOKEN_prod_123abc';

        $data = DB::select("SELECT * FROM billable_hours WHERE DATE_FORMAT(date_logged, '%Y-%m') = '$month'");

        $exported = 0;
        foreach ($data as $row) {
            $ch = curl_init($accountingApiUrl);
            curl_setopt($ch, CURLOPT_POST, true);
            curl_setopt($ch, CURLOPT_HTTPHEADER, [
                'Authorization: Bearer ' . $accountingToken,
                'Content-Type: application/json',
            ]);
            curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode([
                'data'       => $row->date_logged,
                'valor'      => $row->hours * 150,
                'descricao'  => $row->note,
                'cliente_id' => $row->customer_id,
            ]));
            curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
            curl_exec($ch); // ignora resposta completamente
            curl_close($ch);
            $exported++;
        }

        return response()->json(['exported' => $exported]);
    }
}
