# 앵커별 규칙 예시

## 목차
- 추가된 줄 (when_line_added)
- 조건 + 파일 전체 (must_contain_in_file)
- 새 파일의 필수 선언 (when_file_added)
- 짝이 되는 파일 (when_changed)
- 여러 줄 패턴 (file_regex)
- 의미 판정 (semantic_review)

## 추가된 줄

```yaml
id: no-direct-slack-call
title: Slack 은 NotificationService 경유
severity: warn
applies_to:
  stacks: [php]
  files: ["app/**/*.php"]
  exclude: ["app/Services/NotificationService.php"]
detect:
  # 앞의 (?!...) 는 주석 줄을 거릅니다
  when_line_added: '^(?!\s*(?://|#|\*)).*(Http::post\s*\(\s*["'']https://hooks\.slack\.com|new\s+SlackClient)'
message: |
  Slack 호출은 NotificationService 를 통해서만 합니다. 재시도와 rate limit 처리가 거기에 있습니다.
tests:
  match:
    - 'Http::post("https://hooks.slack.com/services/T000/B000/xxx", $payload);'
  no_match:
    - 'app(NotificationService::class)->slack($payload);'
    - '// Http::post("https://hooks.slack.com/...") 는 쓰지 말 것'
```

주석 줄에 같은 코드가 적힐 수 있으면 위처럼 `^(?!\s*(?://|#|\*)).*` 로 시작합니다.

## 조건 + 파일 전체

```yaml
id: laravel-controller-needs-validation
title: store/update 컨트롤러 액션에 검증 없음
severity: warn
applies_to:
  stacks: [laravel]
  files: ["app/Http/Controllers/**/*.php"]
detect:
  when_line_added: 'public\s+function\s+(store|update)\s*\('
  must_contain_in_file: '(FormRequest|Http\\Requests|->validated\(\))'
message: |
  쓰기 액션에 검증이 없습니다. FormRequest 를 만들어 타입힌트로 받고 $request->validated() 를 쓰세요.
prevent: 쓰기 액션(store/update)은 FormRequest 로 받고 $request->validated() 를 쓰세요.
tests:
  match:
    - "class A {\n    public function store(Request $request) {}\n}"
  no_match:
    - "use App\\Http\\Requests\\StoreA;\nclass A {\n    public function store(StoreA $r) {}\n}"
```

## 새 파일의 필수 선언

```yaml
id: php-strict-types-required
title: 새 PHP 파일에 declare(strict_types=1)
severity: warn
applies_to:
  stacks: [php]
  files: ["app/**/*.php"]
  exclude: ["**/*.blade.php"]
detect:
  when_file_added: true
  must_contain_in_file: 'declare\s*\(\s*strict_types\s*=\s*1\s*\)'
message: |
  새 PHP 파일은 여는 태그 다음에 declare(strict_types=1); 로 시작하세요.
tests:
  match:
    - "<?php\n\nnamespace App;\n"
  no_match:
    - "<?php\n\ndeclare(strict_types=1);\n\nnamespace App;\n"
```

## 짝이 되는 파일

```yaml
id: route-needs-test
title: 라우트를 바꿨는데 테스트 변경 없음
severity: info
applies_to:
  stacks: [laravel]
detect:
  when_changed: ["routes/**/*.php"]
  require_changed: ["tests/**/*.php"]
message: |
  라우트가 바뀌었는데 테스트가 없습니다. 엔드포인트를 바꿨다면 Feature 테스트를 함께 넣으세요.
tests:
  match:
    - ["routes/api.php", "app/Http/Controllers/UserController.php"]
  no_match:
    - ["routes/api.php", "tests/Feature/UserTest.php"]
```

## 여러 줄 패턴

```yaml
id: js-no-empty-catch
title: 빈 catch 블록 금지
severity: warn
applies_to:
  stacks: [js]
  files: ["**/*.{ts,tsx,js,jsx}"]
detect:
  file_regex: 'catch\s*(\([^)]*\))?\s*\{\s*\}'
message: |
  에러를 삼키지 마세요. 로거로 남기거나, 의도적이면 이유를 주석으로 남기세요.
tests:
  match:
    - "} catch (e) {\n}\n"
  no_match:
    - "} catch (e) {\n  // 파싱 실패는 기본값\n}\n"
```

## 의미 판정

```yaml
id: service-no-http-response
title: 서비스 계층에서 HTTP 응답 생성
severity: warn
applies_to:
  stacks: [laravel]
  files: ["app/Services/**/*.php"]
detect:
  when_line_added: '\bresponse\(\)|\bResponse::|\bJsonResponse\b'
semantic_review:
  context: [current_function, imports]
  max_context_lines: 100
  instruction: |
    서비스 메서드가 HTTP 응답 객체를 만들어 반환하는지 판단합니다.
    VIOLATION: 서비스가 response()/Response/JsonResponse 를 생성해 반환한다.
    VALID: 응답 객체를 인자로 받아 전달만 하거나, 이름만 같은 다른 타입이다.
    판단할 수 없으면 VALID 입니다.
message: |
  서비스는 도메인 결과를 반환하고, HTTP 응답은 컨트롤러에서 만드세요.
tests:
  match:
    - '        return response()->json($order);'
  no_match:
    - '        return $order;'
```
