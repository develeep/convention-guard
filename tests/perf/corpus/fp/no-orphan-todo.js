// TODO 이 함수는 캐시를 타지 않습니다

function load(id) {
    return fetch(`/api/${id}`);
}
