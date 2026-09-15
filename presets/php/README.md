# PHP 포맷터 프리셋

문서에 적힌 PSR-12 항목 중 **기계가 고칠 수 있는 것은 전부 여기에 있습니다.**
같은 내용을 정규식 규칙으로 중복해서 두지 마세요. 사람이 고치는 것보다 포맷터가
저장할 때 고치는 편이 언제나 낫고, 훅은 포맷터가 못 하는 것에만 써야 값어치가 생깁니다.

## Laravel (Pint)

```bash
cp pint.json <repo>/pint.json
./vendor/bin/pint            # 고치기
./vendor/bin/pint --test     # 검사만 (훅이 이 형태로 호출합니다)
```

## Laravel 아닌 PHP 레포 (PHP-CS-Fixer)

Pint 는 PHP-CS-Fixer 래퍼라 규칙 이름이 같습니다.
`.php-cs-fixer.dist.php` 에 같은 `rules` 배열을 옮겨 쓰면 됩니다.

```php
<?php

declare(strict_types=1);

$finder = PhpCsFixer\Finder::create()
    ->in(__DIR__)
    ->exclude(['vendor', 'storage', 'node_modules']);

return (new PhpCsFixer\Config())
    ->setRiskyAllowed(true)
    ->setRules(json_decode(file_get_contents(__DIR__ . '/pint-rules.json'), true))
    ->setFinder($finder);
```

## 이 파일을 넣으면 규칙 8개가 자동으로 물러납니다

`pint.json` / `.php-cs-fixer.php` / `.php-cs-fixer.dist.php` 중 하나가 레포에 있으면
`superseded_by` 가 걸린 포맷 규칙들이 스스로 비활성화됩니다.
`check.py --explain` 에 `superseded by pint.json` 으로 표시됩니다.

`declare_strict_types` 는 risky 규칙입니다. 기존 코드가 많은 레포에서는
한 번에 켜지 말고 디렉터리 단위로 적용한 뒤 테스트를 돌리세요.
