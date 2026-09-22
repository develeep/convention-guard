export function first() {
    try {
        risky();
    } catch (e) {
    }
}

export function second() {
    try {
        risky();
    } catch (e) {
        // 캐시 미스는 무시합니다
    }
}

function risky() {}
