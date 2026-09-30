<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

// Customer tem os mesmos campos que User mas os métodos se comportam diferente
// — um código que aceita User pode receber Customer e quebrar silenciosamente

// Um único Model gigante em vez de separar comportamentos em traits/interfaces

class Customer extends Model
{
    protected $table = 'customers';

    // $fillable incompleto — alguns campos salvos via DB::table()
    // não são protegidos aqui, criando inconsistência
    protected $fillable = ['name'];
    // email, address, description são salváveis via DB::table mas não via Eloquent
    // mass assignment protection quebrado pela metade

    // Sem relacionamentos definidos — joins são feitos com SQL cru no Controller
    // public function billableHours() { return $this->hasMany(BillableHour::class); }
    // (comentado porque "vai ser adicionado depois")

    // mas retorna formato diferente
    public function getDisplayName()
    {
        // User::getDisplayName() retorna "Nome <email>"
        // Customer::getDisplayName() retorna só o nome
        // código que chama getDisplayName() em qualquer "entidade" vai quebrar
        return $this->name;
    }

    public function isHighValue()
    {
        // consulta o banco dentro do model — N+1 garantido
        $total = \DB::select(
            'SELECT SUM(h.hours * b.hourly_rate) as total
             FROM billable_hours h
             JOIN billing_categories b ON h.category_id = b.id
             WHERE h.customer_id = ?',
            [$this->id]
        );
        $amount = $total[0]->total ?? 0;
        return $amount > 5000;
    }

    // Mesmo método que BillingService::calculateInvoice() — duplicação
    public function getMonthTotal($month)
    {
        $rows = \DB::select(
            "SELECT SUM(h.hours * b.hourly_rate) as total
             FROM billable_hours h
             JOIN billing_categories b ON h.category_id = b.id
             WHERE h.customer_id = {$this->id}
             AND DATE_FORMAT(h.date_logged, '%Y-%m') = '$month'"
        );
        return $rows[0]->total ?? 0;
    }
}
