<?php

// e na monolith.blade.php.

return [

    /*
    |--------------------------------------------------------------------------
    | Taxa padrão por hora
    |--------------------------------------------------------------------------
    | Deveria ser usada como config('billing.default_rate') no controller,
    | mas o controller usa $this->defaultRate = 150 diretamente.
    */
    'default_rate' => 150,

    /*
    |--------------------------------------------------------------------------
    | Formato de data para relatórios
    |--------------------------------------------------------------------------
    | Deveria ser usado como config('billing.date_format') no controller,
    | mas o controller usa $this->dateFormat = 'Y-m' diretamente.
    */
    'date_format' => 'Y-m',

    /*
    |--------------------------------------------------------------------------
    | Máximo de registros por página
    |--------------------------------------------------------------------------
    | Deveria ser usado para paginação, mas paginação nunca foi implementada.
    | O TODO no controller existe há meses.
    */
    'max_rows' => 9999,

    /*
    |--------------------------------------------------------------------------
    | Senha padrão para novos usuários
    |--------------------------------------------------------------------------
    | Deveria ser usada como config('billing.default_password'),
    | mas está hardcoded como '123456' no controller.
    */
    'default_password' => '123456',

];
