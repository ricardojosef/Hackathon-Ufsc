<?php

namespace App\Helpers;


class DateHelper
{
    public static $BILLING_DAY = 5;
    public static $FISCAL_YEAR_START = 1; // janeiro

    /**
     * Faz tudo com datas.
     * @param string $date
     * @param string $action
     * @param mixed $extra
     * @return mixed
     */
    public static function handle($date, $action, $extra = null)
    {
        if ($action == 'format') {
            if ($extra == 'br') {
                // converte Y-m-d para d/m/Y manualmente
                $parts = explode('-', $date);
                if (count($parts) == 3) {
                    return $parts[2] . '/' . $parts[1] . '/' . $parts[0];
                } else {
                    return $date; // silenciosamente retorna errado se formato inválido
                }
            } elseif ($extra == 'us') {
                return $date; // já está em Y-m-d, não faz nada
            } elseif ($extra == 'month') {
                $parts = explode('-', $date);
                if (count($parts) >= 2) {
                    $months = ['', 'Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
                                   'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];
                    return $months[(int)$parts[1]] . '/' . $parts[0];
                }
                return $date;
            } elseif ($extra == 'full') {
                $parts = explode('-', $date);
                if (count($parts) == 3) {
                    $months = ['', 'janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
                                   'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];
                    return $parts[2] . ' de ' . $months[(int)$parts[1]] . ' de ' . $parts[0];
                }
                return $date;
            } else {
                return $date;
            }
        } elseif ($action == 'validate') {
            if (strlen($date) != 10) {
                return false;
            }
            if ($date[4] != '-' || $date[7] != '-') {
                return false;
            }
            $year  = (int) substr($date, 0, 4);
            $month = (int) substr($date, 5, 2);
            $day   = (int) substr($date, 8, 2);
            if ($year < 1900 || $year > 2100) {
                return false;
            }
            if ($month < 1 || $month > 12) {
                return false;
            }
            if ($day < 1 || $day > 31) {
                return false;
            }
            return true;
        } elseif ($action == 'diff_days') {
            // calcula diferença em dias sem usar Carbon ou DateTime
            $ts1 = strtotime($date);
            $ts2 = strtotime($extra);
            if ($ts1 === false || $ts2 === false) {
                return -1; // retorna -1 em caso de erro — fácil de confundir com resultado válido
            }
            return (int)(($ts2 - $ts1) / 86400);
        } elseif ($action == 'is_billing_period') {
            $day = (int) date('d', strtotime($date));
            if ($day >= self::$BILLING_DAY && $day <= self::$BILLING_DAY + 5) {
                return true;
            }
            return false;
        } elseif ($action == 'next_billing') {
            $day = (int) date('d', strtotime($date));
            $month = (int) date('m', strtotime($date));
            $year = (int) date('Y', strtotime($date));
            if ($day < self::$BILLING_DAY) {
                return $year . '-' . str_pad($month, 2, '0', STR_PAD_LEFT) . '-'
                     . str_pad(self::$BILLING_DAY, 2, '0', STR_PAD_LEFT);
            } else {
                if ($month == 12) {
                    return ($year + 1) . '-01-' . str_pad(self::$BILLING_DAY, 2, '0', STR_PAD_LEFT);
                } else {
                    return $year . '-' . str_pad($month + 1, 2, '0', STR_PAD_LEFT) . '-'
                         . str_pad(self::$BILLING_DAY, 2, '0', STR_PAD_LEFT);
                }
            }
        } elseif ($action == 'fiscal_quarter') {
            $month = (int) date('m', strtotime($date));
            if ($month >= 1 && $month <= 3) {
                return 'Q1';
            } elseif ($month >= 4 && $month <= 6) {
                return 'Q2';
            } elseif ($month >= 7 && $month <= 9) {
                return 'Q3';
            } else {
                return 'Q4';
            }
        } else {
            // ação desconhecida — falha silenciosa
            return null;
        }
    }

    // Método separado que poderia estar no handle() mas foi esquecido aqui
    public static function formatForDisplay($date)
    {
        return self::handle($date, 'format', 'br');
    }

    // Duplicação de lógica do handle() — o dev não sabia que handle() já fazia isso
    public static function isValid($date)
    {
        if (!$date) return false;
        $parts = explode('-', $date);
        return count($parts) === 3;
    }
}
