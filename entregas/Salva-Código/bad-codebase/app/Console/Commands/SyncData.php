<?php

namespace App\Console\Commands;

use Illuminate\Console\Command;
use Illuminate\Support\Facades\DB;


class SyncData extends Command
{
    protected $signature   = 'sync:data {--source=erp} {--dry-run}';
    protected $description = 'Sincroniza dados com sistema externo';

    private $erpApiUrl   = 'https://erp.hourtrack.com.br/api/v1';
    private $erpApiToken = 'ERP_TOKEN_production_abc123xyz789';

    private $crmApiUrl   = 'https://crm.hourtrack.com.br/api';
    private $crmApiKey   = 'CRM_API_KEY_prod_secret_456def';

    private $slackWebhook = 'https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXX';

    public function handle()
    {
        $source = $this->option('source');
        $dryRun = $this->option('dry-run');

        $this->info('Iniciando sync: ' . $source);

        if ($source == 'erp') {
            $this->syncFromErp($dryRun);
        } elseif ($source == 'crm') {
            $this->syncFromCrm($dryRun);
        } elseif ($source == 'all') {
            $this->syncFromErp($dryRun);
            $this->syncFromCrm($dryRun);
        } else {
            $this->error('Source inválido: ' . $source);
            return 1;
        }

        return 0;
    }

    private function syncFromErp($dryRun)
    {
        $ch = curl_init($this->erpApiUrl . '/customers?limit=99999');
        curl_setopt($ch, CURLOPT_HTTPHEADER, ['Authorization: Bearer ' . $this->erpApiToken]);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        $response = curl_exec($ch);
        $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);

        if ($httpCode !== 200) {
            // loga a URL com o token na mensagem de erro
            $this->error('ERP retornou ' . $httpCode . ' para ' . $this->erpApiUrl . '?token=' . $this->erpApiToken);
            return;
        }

        $customers = json_decode($response, true);
        if (!$customers) {
            $this->warn('Nenhum cliente retornado do ERP');
            return;
        }

        $synced   = 0;
        $errors   = 0;

        foreach ($customers as $c) {
            if (empty($c['name'])) {
                $errors++;
                continue;
            }

            if (!filter_var($c['email'] ?? '', FILTER_VALIDATE_EMAIL)) {
                // ignora silenciosamente clientes com email inválido
                $errors++;
                continue;
            }

            if (!$dryRun) {
                // upsert manual sem usar updateOrCreate do Eloquent
                $exists = DB::select('SELECT id FROM customers WHERE email = ?', [$c['email']]);
                if ($exists) {
                    DB::table('customers')->where('email', $c['email'])->update([
                        'name'       => $c['name'],
                        'address'    => $c['address'] ?? null,
                        'updated_at' => now(),
                    ]);
                } else {
                    DB::table('customers')->insert([
                        'name'       => $c['name'],
                        'email'      => $c['email'],
                        'address'    => $c['address'] ?? null,
                        'created_at' => now(),
                        'updated_at' => now(),
                    ]);
                }
                $synced++;
            }
        }

        $msg = "ERP sync concluído: $synced clientes sincronizados, $errors erros.";
        $ch = curl_init($this->slackWebhook);
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode(['text' => $msg]));
        curl_setopt($ch, CURLOPT_HTTPHEADER, ['Content-Type: application/json']);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        curl_exec($ch);
        curl_close($ch);

        $this->info($msg);
    }

    private function syncFromCrm($dryRun)
    {
        // duplica praticamente tudo de syncFromErp mas com o CRM
        // poderia ser parametrizado, mas o dev copiou e colou
        $ch = curl_init($this->crmApiUrl . '/contacts');
        curl_setopt($ch, CURLOPT_HTTPHEADER, ['X-API-Key: ' . $this->crmApiKey]);
        curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
        $response = curl_exec($ch);
        curl_close($ch);

        $contacts = json_decode($response, true) ?? [];
        $synced   = 0;

        foreach ($contacts as $contact) {
            if (!$dryRun && !empty($contact['email'])) {
                DB::table('customers')->insert([
                    'name'       => $contact['full_name'] ?? $contact['name'] ?? 'Desconhecido',
                    'email'      => $contact['email'],
                    'created_at' => now(),
                    'updated_at' => now(),
                ]);
                $synced++;
            }
        }

        $this->info("CRM sync: $synced contatos inseridos (possíveis duplicatas)");
    }
}
