<?php

function first()
{
    try {
        risky();
    } catch (\Throwable $e) {
    }
}

function second()
{
    try {
        risky();
    } catch (\Throwable $e) {
        // 캐시 미스는 무시합니다
    }
}
