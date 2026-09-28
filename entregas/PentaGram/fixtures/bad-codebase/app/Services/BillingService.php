<?php

namespace App\Services;

use Illuminate\Support\Facades\DB;
use App\Helpers\DateHelper;


class BillingService
{
    private $notificationService;

    public function __construct()
    {
        $this->notificationService = new NotificationService();
    }

    /**
     * Calcula a fatura de um cliente para um mês.
     */
    public function calculateInvoice($customerId, $month)
    {
        // SQL direto em vez de usar o Model — duplica lógica do EverythingController
        $customer = DB::select('SELECT * FROM customers WHERE id = ?', [$customerId]);

        if (!$customer) {
            return null; // retorno null em vez de exception — caller precisa null-check
        }
        $customer = $customer[0];

        // busca horas — duplica query do EverythingController::report()
        $hours = DB::select("
            SELECT h.*, b.hourly_rate, b.name as category_name
            FROM billable_hours h
            JOIN billing_categories b ON h.category_id = b.id
            WHERE h.customer_id = $customerId
            AND DATE_FORMAT(h.date_logged, '%Y-%m') = '$month'
        ");

        if (empty($hours)) {
            return ['total' => 0, 'items' => [], 'status' => 'empty'];
        }

        $subtotal = 0;
        $items    = [];

        foreach ($hours as $h) {
            $lineTotal = $h->hours * $h->hourly_rate;
            $subtotal += $lineTotal;
            $items[] = [
                'category' => $h->category_name,
                'hours'    => $h->hours,
                'rate'     => $h->hourly_rate,
                'total'    => $lineTotal,
            ];
        }

        // para mudar a regra, edita aqui
        $discount = 0;
        if ($subtotal > 10000) {
            $discount = $subtotal * 0.10; // 10% para clientes grandes
        } elseif ($subtotal > 5000) {
            $discount = $subtotal * 0.05; // 5% para clientes médios
        } elseif ($customer->name == 'Cogna') {
            $discount = $subtotal * 0.15;
        } elseif (isset($customer->special_discount) && $customer->special_discount) {
            $discount = $subtotal * 0.08;
        } else {
            $discount = 0;
        }

        $total = $subtotal - $discount;

        // aplica taxa de atraso se mês anterior
        // lógica de data duplicada — DateHelper já faz isso, mas o dev não sabia
        $currentMonth = date('Y-m');
        if ($month < $currentMonth) {
            // mês passado: aplica multa de 2%
            $total = $total * 1.02;
        }

        // persiste a fatura — responsabilidade de um repositório, não do service
        // e a tabela 'invoices' não existe no banco
        try {
            DB::table('invoices')->insert([
                'customer_id' => $customerId,
                'month'       => $month,
                'subtotal'    => $subtotal,
                'discount'    => $discount,
                'total'       => $total,
                'status'      => 'pending',
                'created_at'  => now(),
                'updated_at'  => now(),
            ]);
        } catch (\Exception $e) {
            // engole silenciosamente — a fatura foi calculada mas não salva
            // e o chamador nunca saberá
        }

        // e usa o NotificationService que também tem seus próprios problemas
        $this->notificationService->send(
            $customerId,
            'billing',
            $this->notificationService->formatMessage('billing', [
                'amount' => number_format($total, 2),
                'month'  => DateHelper::handle($month . '-01', 'format', 'month'),
            ]),
            'email'
        );

        return [
            'customer'  => $customer->name,
            'month'     => $month,
            'items'     => $items,
            'subtotal'  => $subtotal,
            'discount'  => $discount,
            'total'     => $total,
            'status'    => 'calculated',
        ];
    }

    /**
     * Gera relatório mensal de TODOS os clientes.
     */
    public function generateMonthlyReport($month)
    {
        // busca todos os clientes e calcula fatura de cada um
        // O(n) chamadas ao banco — n+1 na prática
        $customers = DB::select('SELECT * FROM customers');
        $report = [];

        foreach ($customers as $c) {
            // chama calculateInvoice que já tem seu próprio N+1 interno
            $invoice = $this->calculateInvoice($c->id, $month);
            if ($invoice && $invoice['total'] > 0) {
                $report[] = $invoice;
            }
        }

        // ordena em PHP em vez de ORDER BY no SQL
        usort($report, function ($a, $b) {
            return $b['total'] <=> $a['total'];
        });

        return $report;
    }
}
