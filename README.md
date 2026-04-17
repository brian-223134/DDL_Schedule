# DDL Migration Timing Strategy

Blue/Green 및 Canary 배포 환경에서 DDL migration을 언제 실행할지 판단하기 위해 정리한 문서다.

핵심 문서는 [`ddl-migration-timing-strategy.md`](./docs/ddl-migration-timing-strategy.md)다.

## 목표

Blue/Green, Canary 배포에서는 Old 버전과 New 버전이 일정 시간 동안 같은 DB를 공유한다.  
이때 DDL migration이 잘못된 시점에 실행되면 다음과 같은 문제가 생길 수 있다.

- Old 버전이 삭제된 테이블이나 컬럼을 참조한다.
- New 버전이 아직 없는 테이블, 컬럼, ENUM 값을 사용한다.
- Old 버전이 New가 생성한 새 데이터를 읽다가 실패한다.
- FK, CHECK, NOT NULL, UNIQUE 제약 추가로 Old write path가 실패한다.
- 대형 테이블 DDL로 인해 lock, replication lag, 성능 저하가 발생한다.

목표는 migration을 배포 전, 배포 중, 배포 후 단계로 나누고, 각 단계에서 어떤 DDL을 실행해도 되는지 판단하는 기준을 세우는 것이다.

## 핵심 원칙

> Migration은 Old/New 양쪽 버전 모두에서 오류가 발생하지 않아야 한다.

운영 기준으로는 아래 조건까지 함께 봐야 한다.

- DDL 적용 후에도 Old 코드가 정상 동작해야 한다.
- DDL 적용 후에도 New 코드가 정상 동작해야 한다.
- New가 생성한 데이터를 Old가 읽어도 안전해야 한다.
- DDL 실행 중 table lock, table rewrite, replication lag를 고려해야 한다.
- Post-deploy migration은 Old web instance뿐 아니라 worker, cron, queue consumer까지 완전히 종료된 뒤 실행해야 한다.

## 기본 전략

DB 변경은 한 번에 끝내기보다 아래 3단계로 나누는 편이 안전하다.

```text
1. Expand
   Old와 New 모두 호환되는 스키마를 먼저 추가한다.

2. Migrate
   New 코드 배포, dual-write, backfill, data cleanup, feature flag 전환을 수행한다.

3. Contract
   Old가 완전히 사라진 뒤 불필요한 스키마를 제거하거나 제약을 강화한다.
```

즉, Pre-deploy에는 확장 계열 변경을 두고, Post-deploy에는 삭제나 제약 강화처럼 Old와 충돌할 수 있는 변경을 둔다.

## Migration 분류 요약

| 단계 | 주로 포함되는 변경 | 예시 |
|---|---|---|
| Pre-deploy | 추가 계열, backward-compatible 변경 | `CREATE TABLE`, `ADD nullable column`, ENUM 확장, seed INSERT |
| Rollout | 코드 전환, 데이터 보정, feature flag 제어 | dual-write, backfill, validation |
| Post-deploy | 삭제/제약 계열, Old와 비호환 가능성이 있는 변경 | `DROP COLUMN`, `DROP TABLE`, ENUM 축소, `ADD FK`, `ADD NOT NULL` |

## 권장 파일 네이밍

```text
YYYY-MM-DD_description.pre.sql
YYYY-MM-DD_description.data.sql
YYYY-MM-DD_description.post.sql
YYYY-MM-DD_description.pre.rollback.sql
YYYY-MM-DD_description.post.rollback.sql
```

예시:

```text
2026-04-09_add_userWorkflowId.pre.sql
2026-04-09_backfill_userWorkflowId.data.sql
2026-04-09_add_userWorkflowId_fk.post.sql
```

## 배포 파이프라인 순서

```text
1. Pre-deploy migrations 실행
2. New 버전 배포 시작
3. Old/New 공존 구간 모니터링
4. New 100% 전환
5. Old web/worker/cron/queue consumer 완전 종료 확인
6. Rollback window 종료 또는 rollback 가능성 낮음 확인
7. Data cleanup 및 validation
8. Post-deploy migrations 실행
9. 모니터링
```

## 문서 구성

- [`ddl-migration-timing-strategy.md`](./docs/ddl-migration-timing-strategy.md)
  - DDL 유형별 실행 시점 분류
  - 현재 migration 파일 위험도 분석
  - 2-phase migration 패턴
  - ENUM, FK, NOT NULL, DROP, RENAME 처리 패턴
  - 배포 파이프라인 실행 순서
  - 운영 체크리스트
- [`migration_phase_splitter.USAGE.md`](./docs/migration_phase_splitter.USAGE.md)
  - Migration phase splitter 사용 방법
  - Pre/Post migration 분리 실행 예시
- [`develop_migration_phase_splitter.USAGE.md`](./docs/develop_migration_phase_splitter.USAGE.md)
  - Develop 환경용 단순 Pre/Post splitter 사용 방법
- [`develop_migration_phase_splitter.DETAILS.md`](./docs/develop_migration_phase_splitter.DETAILS.md)
  - Develop splitter 코드 구조와 분류 로직 설명

## 사용 방법

새 migration을 작성할 때는 아래 순서로 확인한다.

1. 변경이 Pre-deploy, Rollout, Post-deploy 중 어디에 속하는지 분류한다.
2. Old/New 양쪽 버전이 모두 동작 가능한지 확인한다.
3. 하나의 migration 파일에 Pre-deploy와 Post-deploy 변경이 섞여 있지 않은지 확인한다.
4. 대형 테이블 DDL이라면 lock, rewrite, replication lag를 검토한다.
5. destructive migration은 Old 종료와 rollback window를 확인한 뒤 실행한다.

## 기준 요약

DDL migration의 안전성은 단순히 SQL이 성공하는지만으로 판단하기 어렵다.  
Blue/Green, Canary 배포에서는 스키마 호환성, 데이터 호환성, Old/New 공존 구간, rollback 가능성, DDL 실행 비용을 함께 봐야 한다.

가장 중요한 기준은 아래 문장으로 정리할 수 있다.

> Pre-deploy는 Old가 견딜 수 있는 확장만, Post-deploy는 Old가 완전히 사라진 뒤 수행할 수 있는 축소와 제약만 담는다.

## 추가 개선 및 고도화 방향

지금은 DDL migration을 `pre`, `data`, `post`, `manual` 단계로 나누는 기준과 splitter 스크립트가 있다.  
다음 단계에서는 MySQL의 실제 DDL 동작, 운영 리스크, CI 자동화를 더 반영해볼 수 있다.

### 우선 개발하면 좋은 기능

| 우선순위 | 개선 항목 | 내용 |
|---|---|---|
| P0 | 테스트 fixture 추가 | `production/migration_phase_splitter.py`의 분류 규칙을 검증하는 SQL fixture와 단위 테스트를 추가한다. `ADD COLUMN`, `DROP COLUMN`, `ENUM`, `FK`, `CHECK`, `UNIQUE`, `RENAME`, mixed ALTER 케이스를 고정 테스트로 만든다. |
| P0 | README/문서 링크 검증 | GitHub에서 깨지는 상대 경로를 막기 위해 Markdown 링크 검증 스크립트나 CI job을 추가한다. |
| P1 | Risk score 리포트 | 각 statement에 `safe`, `warning`, `danger`, `manual` 같은 위험도를 부여하고 manifest에 기록한다. 리뷰어가 어떤 migration을 먼저 봐야 하는지 빠르게 판단할 수 있다. |
| P1 | Validation SQL 자동 생성 | `ADD FK`, `ADD NOT NULL`, `ADD UNIQUE`, ENUM 축소 전에 실행할 검증 SQL을 자동 생성한다. 예: orphan row 확인, NULL 확인, 중복 key 확인, deprecated enum value 확인. |
| P1 | MySQL online DDL 옵션 분석 | `ALGORITHM=INSTANT`, `ALGORITHM=INPLACE`, `ALGORITHM=COPY`, `LOCK=NONE`, `LOCK=SHARED`, `LOCK=EXCLUSIVE` 여부를 파싱해 DDL 실행 리스크를 표시한다. |
| P1 | 대형 테이블 운영 가드 | 대상 테이블 row count, index 수, FK 유무, 예상 lock 리스크를 입력받아 `online DDL 필요`, `maintenance window 필요`, `manual review 필요`를 판단한다. |
| P2 | CI 통합 | `--strict` 모드를 GitHub Actions에서 실행해 `manual` migration이 있으면 PR을 실패시키고, manifest를 artifact로 업로드한다. |
| P2 | DB 버전별 규칙 분리 | MySQL 5.7, MySQL 8.0, MariaDB 등 버전에 따라 DDL 가능 여부와 CHECK/INSTANT DDL 동작이 다르므로 버전별 rule set을 분리한다. |
| P2 | Forward-fix 가이드 생성 | 위험한 rollback 대신 어떤 forward-fix가 가능한지 migration 종류별 가이드를 manifest나 Markdown으로 생성한다. |

### 추천 개발 로드맵

1. `tests/fixtures` 디렉터리를 만들고 대표 SQL migration 샘플을 쌓는다.
2. `production/migration_phase_splitter.py`에 대한 단위 테스트를 추가한다.
3. `manifest.json`에 phase뿐 아니라 risk level, reason, recommended validation을 추가한다.
4. `ADD FK`, `ADD NOT NULL`, `ADD UNIQUE`, ENUM 축소에 대한 validation SQL generator를 만든다.
5. MySQL DDL 옵션(`ALGORITHM`, `LOCK`)을 파싱하고 위험도를 표시한다.
6. GitHub Actions에서 splitter를 실행하는 CI 예제를 추가한다.
7. MySQL 버전별 rule preset을 추가한다.

### 예시: Validation SQL Generator 방향

`post` migration을 실행하기 전에 자동으로 아래와 같은 검증 SQL을 만들 수 있다.

```sql
-- ADD NOT NULL 전 NULL 데이터 확인
SELECT COUNT(*)
FROM target_table
WHERE target_column IS NULL;

-- ADD UNIQUE 전 중복 데이터 확인
SELECT target_column, COUNT(*)
FROM target_table
GROUP BY target_column
HAVING COUNT(*) > 1;

-- ADD FOREIGN KEY 전 orphan row 확인
SELECT child.parent_id
FROM child
LEFT JOIN parent ON parent.id = child.parent_id
WHERE child.parent_id IS NOT NULL
  AND parent.id IS NULL;
```

이 기능이 추가되면 migration을 단순히 분류하는 수준을 넘어, “post-deploy migration을 실행해도 되는 상태인지”까지 확인할 수 있다.
