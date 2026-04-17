# develop/migration_phase_splitter.py 상세 설명

이 문서는 `develop/migration_phase_splitter.py`의 코드 구조와 동작 방식을 설명한다.

사용법만 빠르게 확인하려면 [`develop_migration_phase_splitter.USAGE.md`](./develop_migration_phase_splitter.USAGE.md)를 보면 된다.

## 목적

Develop 환경에서는 production splitter처럼 `pre`, `data`, `post`, `manual`을 모두 나누지 않는다.

대신 아래처럼 단순한 2-phase 규칙만 적용한다.

| Phase | 의미 | 포함 기준 |
|---|---|---|
| `pre` | deploy 전 실행 | 명확한 `CREATE` statement |
| `post` | deploy 후 실행 | `DROP`, 권한/계정 제어, data 변경, 애매한 statement |

핵심 정책은 "확실한 생성만 deploy 전에 실행하고, 나머지는 deploy 후로 보낸다"이다.

## Production Splitter와 차이

Production splitter는 운영 배포 리스크를 더 세밀하게 판단한다.

- `pre`, `data`, `post`, `manual` 4개 phase를 사용한다.
- nullable/default `ADD COLUMN`, FK, UNIQUE, ENUM 변경 등을 각각 다르게 판단한다.
- forward/rollback pair를 함께 보고 ENUM expansion/shrink를 추론한다.
- `--strict` 모드로 manual review 대상이 있으면 실패시킬 수 있다.

Develop splitter는 이 복잡도를 의도적으로 줄였다.

- `pre`, `post` 2개 phase만 사용한다.
- `CREATE`만 `pre`로 보낸다.
- `DROP`, 권한 제어, data 변경, 판단이 애매한 SQL은 모두 `post`로 보낸다.
- rollback 파일, ENUM pair 추론, strict mode는 제공하지 않는다.

## 전체 처리 흐름

CLI 실행부터 파일 생성까지의 흐름은 아래와 같다.

```text
1. CLI argument 파싱
2. 입력 SQL 파일 존재 여부 확인
3. output directory 생성
4. SQL 파일 읽기
5. SQL text를 statement 단위로 분리
6. 각 statement를 pre/post로 분류
7. phase별 group 파일 생성
8. statement별 unit 파일 생성
9. manifest JSON 생성
10. 생성 경로와 phase count 출력
```

예를 들어 아래 명령을 실행하면:

```bash
python3 develop/migration_phase_splitter.py \
  --input /path/to/2026-04-16_example.sql \
  --out-dir /tmp/develop-split-output
```

아래와 같은 파일이 생성될 수 있다.

```text
/tmp/develop-split-output/
  2026-04-16_example.pre.sql
  2026-04-16_example.pre.001.sql
  2026-04-16_example.post.sql
  2026-04-16_example.post.001.sql
  2026-04-16_example.post.002.sql
  2026-04-16_example.manifest.json
```

## 공통 Helper 재사용

Develop splitter는 SQL 파싱과 정규화 로직을 새로 만들지 않고 production splitter의 helper를 재사용한다.

```python
from production.migration_phase_splitter import (
    ensure_statement_terminator,
    normalize_for_match,
    split_sql_statements,
    summarize,
)
```

각 helper의 역할은 아래와 같다.

| Helper | 역할 |
|---|---|
| `split_sql_statements` | SQL text를 statement 단위로 분리한다. 문자열/주석 안의 `;`는 분리 기준으로 보지 않는다. |
| `normalize_for_match` | 주석 제거, 공백 정리, 대문자 변환을 수행해 분류하기 쉬운 문자열로 만든다. |
| `summarize` | manifest에 기록할 statement 요약을 만든다. |
| `ensure_statement_terminator` | statement 끝에 `;`가 없으면 붙인다. |

이 구조 덕분에 statement 분리 같은 까다로운 로직은 production과 동일하게 유지하고, develop 전용 분류 규칙만 별도 파일에서 관리할 수 있다.

## Phase 상수

Develop splitter의 phase는 두 개뿐이다.

```python
PHASE_ORDER = ("pre", "post")
```

이 순서는 output 파일 생성 순서에도 사용된다.

## 권한/계정 제어 SQL

권한과 계정 제어 statement는 모두 `post`로 분류한다.

```python
PERMISSION_PREFIXES = (
    "GRANT ",
    "REVOKE ",
    "CREATE USER",
    "ALTER USER",
    "DROP USER",
    "RENAME USER",
    "CREATE ROLE",
    "DROP ROLE",
    "SET DEFAULT ROLE",
    "SET PASSWORD",
    "FLUSH PRIVILEGES",
)
```

`CREATE USER`, `CREATE ROLE`은 `CREATE`로 시작하지만 일반 schema 생성과 성격이 다르다. 그래서 `classify_statement()`에서는 권한/계정 제어를 일반 `CREATE`보다 먼저 검사한다.

## Data SQL

Develop splitter는 `data` phase를 따로 만들지 않는다.

아래 statement는 모두 `post`로 분류한다.

```python
DATA_PREFIXES = (
    "INSERT ",
    "REPLACE ",
    "UPDATE ",
    "DELETE ",
    "LOAD DATA ",
)
```

## Unit 모델

`Unit`은 SQL statement 하나의 분류 결과를 담는 데이터 구조다.

```python
@dataclass
class Unit:
    source_order: int
    phase: str
    reason: str
    sql: str
    summary: str
    unit_id: str = ""
```

| 필드 | 의미 |
|---|---|
| `source_order` | 원본 SQL 파일에서 몇 번째 statement인지 |
| `phase` | `pre` 또는 `post` |
| `reason` | 해당 phase로 분류한 이유 |
| `sql` | 원본 SQL statement |
| `summary` | manifest에 기록할 요약 |
| `unit_id` | `pre-001`, `post-001` 같은 phase별 ID |

`unit_id`는 `Unit` 생성 시점에는 비어 있고, 파일 생성 전에 `assign_ids()`에서 채운다.

## 분류 로직

핵심 함수는 `classify_statement(sql)`이다.

분류 순서는 아래와 같다.

| 순서 | 조건 | Phase | 이유 |
|---|---|---|---|
| 1 | 정규화 후 비어 있음 | `post` | 주석뿐이거나 비어 있으면 자동 실행 시점이 애매함 |
| 2 | 권한/계정 제어 prefix | `post` | DB 권한/계정 변경은 schema 생성과 분리 |
| 3 | `CREATE`로 시작 | `pre` | 명확한 생성 statement |
| 4 | `DROP`으로 시작 | `post` | 삭제 계열 statement |
| 5 | statement 내부에 `DROP` 포함 | `post` | `ALTER TABLE ... DROP COLUMN ...` 같은 삭제 포함 statement |
| 6 | data prefix | `post` | develop mode에는 별도 `data` phase가 없음 |
| 7 | 그 외 모든 statement | `post` | 애매한 statement는 보수적으로 deploy 후 |

예시는 아래와 같다.

| SQL | Phase |
|---|---|
| `CREATE TABLE users (...);` | `pre` |
| `CREATE INDEX idx_users_name ON users(name);` | `pre` |
| `CREATE UNIQUE INDEX uq_users_email ON users(email);` | `pre` |
| `CREATE USER 'app'@'%' IDENTIFIED BY 'pw';` | `post` |
| `GRANT SELECT ON app.* TO 'reader'@'%';` | `post` |
| `DROP TABLE legacy_users;` | `post` |
| `ALTER TABLE users DROP COLUMN legacy_name;` | `post` |
| `ALTER TABLE users ADD COLUMN nickname VARCHAR(64);` | `post` |
| `UPDATE users SET name = 'kim' WHERE id = 1;` | `post` |

주의할 점은 `ALTER TABLE ... ADD COLUMN ...`도 develop splitter에서는 `post`라는 점이다. Production 기준에서는 nullable/default `ADD COLUMN`이 `pre`가 될 수 있지만, develop splitter는 `CREATE`만 `pre`로 보내는 단순 규칙을 따른다.

## SQL 파싱

`parse_sql_file(source_file)`은 입력 파일을 읽고 `Unit` 목록을 만든다.

처리 흐름은 아래와 같다.

```text
1. source_file을 UTF-8로 읽는다.
2. split_sql_statements()로 statement 단위로 나눈다.
3. 각 statement를 classify_statement()로 분류한다.
4. source_order, phase, reason, sql, summary를 담은 Unit을 만든다.
5. Unit list를 반환한다.
```

이 함수는 파일을 생성하지 않는다. 입력 SQL을 메모리상의 분류 결과로 바꾸는 단계만 담당한다.

## 파일 생성

`write_sql_artifacts(source_file, out_dir, base_name, units)`는 실제 output 파일을 만든다.

생성하는 파일은 두 종류다.

| 종류 | 예시 | 목적 |
|---|---|---|
| phase group 파일 | `example.pre.sql` | 같은 phase에 속한 statement를 한 파일에 모음 |
| statement unit 파일 | `example.pre.001.sql` | statement 하나씩 따로 확인하거나 실행할 수 있게 분리 |

각 phase group 파일에는 metadata comment가 포함된다.

```sql
-- Auto-generated by develop/migration_phase_splitter.py
-- source: /path/to/example.sql
-- phase: pre
-- generated_at_utc: 2026-04-17T00:00:00+00:00

-- unit: pre-001
-- source_order: 1
-- reason: CREATE statement is deploy-before in develop mode
CREATE TABLE users (id BIGINT PRIMARY KEY);
```

해당 phase에 statement가 하나도 없으면 그 phase 파일은 생성하지 않는다. 예를 들어 모든 statement가 `CREATE`라면 `post.sql`은 없을 수 있다.

## Manifest

마지막으로 `<base_name>.manifest.json`을 생성한다.

Manifest에는 아래 정보가 들어간다.

| 필드 | 의미 |
|---|---|
| `generated_at_utc` | manifest 생성 시각 |
| `out_dir` | output directory |
| `result.source_file` | 원본 SQL 파일 |
| `result.mode` | `develop` |
| `result.total_statements` | 전체 statement 수 |
| `result.phase_counts` | `pre`, `post`별 statement 수 |
| `result.units` | statement별 ID, phase, 원본 순서, reason, summary |
| `result.generated_files` | 생성된 파일 목록 |
| `notes` | develop mode 규칙 요약 |

예시:

```json
{
  "generated_at_utc": "2026-04-17T00:00:00+00:00",
  "out_dir": "/tmp/develop-split-output",
  "result": {
    "source_file": "/path/to/example.sql",
    "mode": "develop",
    "total_statements": 4,
    "phase_counts": {
      "pre": 1,
      "post": 3
    },
    "units": [
      {
        "id": "pre-001",
        "phase": "pre",
        "source_order": 1,
        "reason": "CREATE statement is deploy-before in develop mode",
        "summary": "CREATE TABLE USERS (ID BIGINT PRIMARY KEY);"
      }
    ],
    "generated_files": []
  },
  "notes": [
    "develop mode has only pre/post phases",
    "CREATE statements are pre-deploy",
    "DROP, permission/account control, data, and ambiguous statements are post-deploy"
  ]
}
```

## CLI

`main()`은 command line interface를 담당한다.

입력 SQL은 `--input` 또는 `--forward`로 받을 수 있다.

```bash
python3 develop/migration_phase_splitter.py --input path/to/file.sql
```

```bash
python3 develop/migration_phase_splitter.py --forward path/to/file.sql
```

`--forward`는 production splitter와 비슷한 사용감을 주기 위한 alias다. 두 옵션은 동시에 사용할 수 없다.

`--out-dir`를 생략하면 입력 SQL 파일과 같은 디렉토리 아래 `develop_split_migrations`가 output directory가 된다.

```text
<input_dir>/develop_split_migrations
```

## 테스트

Develop splitter의 테스트는 `tests/test_develop_migration_phase_splitter.py`에 있다.

검증하는 내용은 크게 두 가지다.

1. 대표 SQL statement가 기대 phase로 분류되는지 확인한다.
2. CLI 실행 시 `pre`, `post`, manifest 파일이 생성되는지 확인한다.

전체 테스트는 아래 명령으로 실행한다.

```bash
python3 -m unittest discover -s tests
```

## 의도적 한계

Develop splitter는 단순한 로컬/develop 환경용 도구다. 운영 배포 판단 도구로 쓰면 안 된다.

의도적으로 하지 않는 것:

- `data` phase 분리
- `manual` phase 분리
- rollback SQL 처리
- ENUM expansion/shrink 추론
- FK, UNIQUE, NOT NULL, nullable ADD COLUMN에 대한 세밀한 운영 리스크 판단
- `--strict` 모드

운영 배포 기준으로 세밀한 분류가 필요하면 `production/migration_phase_splitter.py`를 사용한다.
