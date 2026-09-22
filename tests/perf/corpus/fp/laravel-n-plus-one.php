<?php

namespace App\Http\Controllers;

class OrderController
{
    public function index($orders)
    {
        foreach ($orders as $order) {
            echo $order->user->name;
        }
        // foreach ($archived as $order) { echo $order->user->name; }
        $doc = "foreach (\$rows as \$row) is the N+1 shape";

        return $doc;
    }
}
