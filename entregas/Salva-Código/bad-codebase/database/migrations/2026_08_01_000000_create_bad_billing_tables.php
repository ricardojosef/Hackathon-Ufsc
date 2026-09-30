<?php
use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration {
    public function up(): void
    {
        Schema::create('customers', function (Blueprint $t) {
            $t->id();
            $t->text('name');          // text em vez de string — mais "flexível"
            $t->text('email')->nullable();
            $t->text('address')->nullable();
            $t->timestamps();
        });

        Schema::create('billing_categories', function (Blueprint $t) {
            $t->id();
            $t->text('name');          // text em vez de string
            $t->text('description')->nullable();
            $t->float('hourly_rate');  // float em vez de decimal — perda de precisão monetária
            $t->timestamps();
        });

        Schema::create('billable_hours', function (Blueprint $t) {
            $t->id();
            $t->unsignedBigInteger('customer_id');  // sem foreign key constraint
            $t->unsignedBigInteger('user_id');
            $t->unsignedBigInteger('category_id');
            $t->float('hours');        // float para horas — imprecisão desnecessária
            $t->text('note')->nullable();
            $t->date('date_logged');
            $t->timestamps();

            // índice em note (campo de texto livre, nunca filtrado)
            $t->index('note');

            // sem índice em customer_id, user_id, date_logged que são usados nos JOINs e WHERE
        });
    }

    public function down(): void
    {
        Schema::dropIfExists('billable_hours');
        Schema::dropIfExists('billing_categories');
        Schema::dropIfExists('customers');
    }
};
