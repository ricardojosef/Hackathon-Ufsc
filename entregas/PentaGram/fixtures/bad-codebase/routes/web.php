<?php

use Illuminate\Support\Facades\Route;
use App\Http\Controllers\EverythingController;

// sem middleware de autenticação — todas as rotas são públicas
// qualquer visitante pode criar, deletar e ver todos os dados

// rota principal - retorna dashboard
Route::get("/", [EverythingController::class, "dashboard"]);

Route::post("/save/{thing}", 'App\Http\Controllers\EverythingController@save');

Route::get("/delete/{thing}/{id}", [\App\Http\Controllers\EverythingController::class, "delete"]);

// relatório mensal em web.php em vez de api.php, sem prefixo de versão
Route::get("/api/report", function () {
    return app(\App\Http\Controllers\EverythingController::class)->report(request());
});
