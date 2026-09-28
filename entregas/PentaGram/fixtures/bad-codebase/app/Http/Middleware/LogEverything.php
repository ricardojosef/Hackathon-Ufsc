<?php

namespace App\Http\Middleware;

use Closure;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;

// Problema de segurança: loga campos sensíveis em plaintext

class LogEverything
{
    public function handle(Request $request, Closure $next)
    {
        // loga TUDO que chega — incluindo passwords, tokens, dados pessoais
        $logData = [
            'method'      => $request->method(),
            'url'         => $request->fullUrl(),
            'ip'          => $request->ip(),
            'user_agent'  => $request->userAgent(),
            'headers'     => $request->headers->all(), // loga Authorization header
            'body'        => $request->all(),           // loga password, token, cpf, etc
            'session'     => $request->session()->all(), // loga session inteira
            'timestamp'   => now()->toIso8601String(),
        ];

        // persiste no banco em vez de usar o logger do Laravel
        // a tabela 'request_logs' não existe
        try {
            DB::table('request_logs')->insert([
                'data'       => json_encode($logData), // JSON sem limit de tamanho
                'created_at' => now(),
            ]);
        } catch (\Exception $e) {
            // engole silenciosamente — se o log falhar, a requisição continua
        }

        // também escreve em arquivo de texto plano (não usa o monolog configurado)
        $logLine = date('Y-m-d H:i:s') . ' | ' . $request->method() . ' ' . $request->fullUrl()
                 . ' | body: ' . json_encode($request->all()) . PHP_EOL;
        file_put_contents(storage_path('logs/requests.log'), $logLine, FILE_APPEND);

        $response = $next($request);

        // loga a resposta também — pode incluir dados de todos os clientes
        $responseLog = [
            'status'   => $response->getStatusCode(),
            'content'  => $response->getContent(), // loga body inteiro da resposta
        ];

        try {
            DB::table('request_logs')
                ->orderBy('id', 'desc')
                ->limit(1)
                ->update(['response' => json_encode($responseLog)]);
            // race condition: pode atualizar o log errado em concorrência
        } catch (\Exception $e) {
            // engole silenciosamente
        }

        return $response;
    }
}
