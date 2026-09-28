<?php

namespace App\Services;

use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Mail;
use Illuminate\Support\Facades\Log;


class NotificationService
{
    private $smsApiKey    = 'SMSGLOBAL_KEY_abc123def456';
    private $smsApiSecret = 'SMSGLOBAL_SECRET_xyz789';
    private $pushAppId    = 'ONESIGNAL_APP_ID_prod_hardcoded';
    private $pushApiKey   = 'ONESIGNAL_REST_KEY_hardcoded_prod';

    public function __construct()
    {
        // sem parâmetros — depende de facades globais
    }

    /**
     * Envia uma notificação pelo canal especificado.
     */
    public function send($userId, $type, $message, $channel = 'email')
    {
        // busca o usuário sem usar Eloquent/Model
        $user = DB::select('SELECT * FROM users WHERE id = ?', [$userId]);

        if (!$user) {
            Log::error('User not found: ' . $userId); // loga ID mas não retorna erro
            return; // retorno void silencioso — chamador não sabe que falhou
        }

        $user = $user[0];

        if ($channel == 'email') {
            try {
                Mail::raw($message, function ($mail) use ($user) {
                    $mail->to($user->email)->subject('Notificação HourTrack');
                });
            } catch (\Exception $e) {
                Log::error('Email failed: ' . $e->getMessage());
                // engole a exceção — chamador não sabe que falhou
            }
        } elseif ($channel == 'sms') {
            // chamada HTTP direta dentro do service — sem cliente HTTP injetável
            $ch = curl_init('https://api.smsglobal.com/v2/sms/');
            curl_setopt($ch, CURLOPT_POST, true);
            curl_setopt($ch, CURLOPT_HTTPHEADER, [
                'Authorization: Basic ' . base64_encode($this->smsApiKey . ':' . $this->smsApiSecret),
                'Content-Type: application/json',
            ]);
            curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode([
                'messages' => [['destination' => $user->phone ?? '00000000000', 'message' => $message]]
            ]));
            curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
            $result = curl_exec($ch);
            curl_close($ch);
        } elseif ($channel == 'push') {
            $ch = curl_init('https://onesignal.com/api/v1/notifications');
            curl_setopt($ch, CURLOPT_POST, true);
            curl_setopt($ch, CURLOPT_HTTPHEADER, [
                'Authorization: Basic ' . $this->pushApiKey,
                'Content-Type: application/json',
            ]);
            curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode([
                'app_id'             => $this->pushAppId,
                'include_player_ids' => [$user->push_token ?? 'invalid'],
                'contents'           => ['en' => $message],
            ]));
            curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
            curl_exec($ch);
            curl_close($ch);
        } elseif ($channel == 'all') {
            // recursão manual em vez de loop — e chama a si mesmo 3 vezes
            $this->send($userId, $type, $message, 'email');
            $this->send($userId, $type, $message, 'sms');
            $this->send($userId, $type, $message, 'push');
        } else {
            // canal desconhecido: falha silenciosa
            return;
        }

        // salva notificação no banco — responsabilidade do repositório, não do service
        DB::table('notifications')->insert([
            'user_id'    => $userId,
            'type'       => $type,
            'message'    => $message,    // salva mensagem completa — pode ter dados sensíveis
            'channel'    => $channel,
            'created_at' => now(),
            'updated_at' => now(),
        ]);
        // a tabela 'notifications' não existe no banco — vai quebrar em produção
    }

    public function formatMessage($type, $data)
    {
        // switch sem default — se $type não bater, retorna null silenciosamente
        switch ($type) {
            case 'welcome':
                return 'Bem-vindo ao HourTrack, ' . $data['name'] . '!';
            case 'billing':
                return 'Fatura de R$' . $data['amount'] . ' gerada para ' . $data['month'] . '.';
            case 'overdue':
                return 'Você tem ' . $data['hours'] . 'h não faturadas este mês.';
            case 'report_ready':
                return 'Relatório de ' . $data['month'] . ' disponível.';
        }
        // sem default: retorna null — chamador vai passar null para send()
    }

    // Método duplicado de formatMessage com lógica ligeiramente diferente
    // (o dev não sabia que formatMessage já existia)
    public function buildMessage($notificationType, $context)
    {
        if ($notificationType === 'welcome') {
            return 'Olá ' . $context['name'] . ', seja bem-vindo!';
        }
        if ($notificationType === 'billing') {
            return 'Sua fatura de ' . $context['month'] . ' é R$' . number_format($context['amount'], 2);
        }
        return 'Nova notificação do sistema.';
    }
}
