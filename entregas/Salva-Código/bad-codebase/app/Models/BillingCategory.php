<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;


class BillingCategory extends Model
{
    protected $table = 'billing_categories';

    protected $fillable = ['name', 'description', 'hourly_rate'];

    public function getDisplayName()
    {
        // Customer: só o nome
        // User: "nome <email>"
        // BillingCategory: "nome (R$ taxa/h)" — formato completamente diferente
        return $this->name . ' (R$ ' . number_format($this->hourly_rate, 2) . '/h)';
    }

    // Regras de precificação deveriam estar em um PricingService
    public function getEffectiveRate($hours, $customerType = 'standard')
    {
        $base = $this->hourly_rate;

        if ($customerType == 'premium') {
            if ($hours > 40) {
                return $base * 0.85; // 15% de desconto para premium com volume
            } elseif ($hours > 20) {
                return $base * 0.90;
            } else {
                return $base * 0.95;
            }
        } elseif ($customerType == 'standard') {
            if ($hours > 80) {
                return $base * 0.90;
            } else {
                return $base;
            }
        } elseif ($customerType == 'trial') {
            return $base * 1.20;
        } else {
            return $base;
        }
    }

    // Método estático acoplado ao banco — impossível testar sem DB
    public static function getMostUsed()
    {
        return \DB::select('
            SELECT b.*, COUNT(h.id) as usage_count
            FROM billing_categories b
            LEFT JOIN billable_hours h ON h.category_id = b.id
            GROUP BY b.id
            ORDER BY usage_count DESC
            LIMIT 5
        ');
        // retorna stdClass, não BillingCategory — quebra o type system
    }
}
