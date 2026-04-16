# DDL Migration Timing Strategy

Blue/Green 및 Canary 배포 환경에서 안전하게 DDL migration을 실행하기 위한 전략 문서입니다.

이 저장소의 핵심 문서는 [`ddl-migration-timing-strategy.md`](./docs/ddl-migration-timing-strategy.md)입니다.

## 목적

Blue/Green, Canary 배포에서는 Old 버전과 New 버전이 일정 시간 동안 같은 DB를 공유합니다.  
이때 DDL migration이 잘못된 시점에 실행되면 다음과 같은 장애가 발생할 수 있습니다.

- Old 버전이 삭제된 테이블이나 컬럼을 참조함
- New 버전이 아직 없는 테이블, 컬럼, ENUM 값을 사용함
- Old 버전이 New가 생성한 새 데이터를 읽다가 실패함
- FK, CHECK, NOT NULL, UNIQUE 제약 추가로 Old write path가 실패함
- 대형 테이블 DDL로 인해 lock, replication lag, 성능 저하가 발생함

이 문서는 migration을 배포 전, 배포 중, 배포 후 단계로 나누어 안전하게 실행하는 기준을 정리합니다.

## 핵심 원칙

> Migration은 Old/New 양쪽 버전 모두에서 오류가 발생하지 않아야 한다.

운영 기준으로는 아래 조건까지 함께 만족해야 합니다.

- DDL 적용 후에도 Old 코드가 정상 동작해야 한다.
- DDL 적용 후에도 New 코드가 정상 동작해야 한다.
- New가 생성한 데이터를 Old가 읽어도 안전해야 한다.
- DDL 실행 중 table lock, table rewrite, replication lag를 고려해야 한다.
- Post-deploy migration은 Old web instance뿐 아니라 worker, cron, queue consumer까지 완전히 종료된 뒤 실행해야 한다.

## 기본 전략

문서에서는 DB 변경을 다음 3단계로 나누는 방식을 권장합니다.

```text
1. Expand
   Old와 New 모두 호환되는 스키마를 먼저 추가한다.

2. Migrate
   New 코드 배포, dual-write, backfill, data cleanup, feature flag 전환을 수행한다.

3. Contract
   Old가 완전히 사라진 뒤 불필요한 스키마를 제거하거나 제약을 강화한다.
```

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

## 사용 방법

새 migration을 작성할 때 다음 순서로 확인합니다.

1. 변경이 Pre-deploy, Rollout, Post-deploy 중 어디에 속하는지 분류한다.
2. Old/New 양쪽 버전이 모두 동작 가능한지 확인한다.
3. 하나의 migration 파일에 Pre-deploy와 Post-deploy 변경이 섞여 있지 않은지 확인한다.
4. 대형 테이블 DDL이라면 lock, rewrite, replication lag를 검토한다.
5. destructive migration은 Old 종료와 rollback window를 확인한 뒤 실행한다.

## 결론

DDL migration의 안전성은 단순히 SQL이 성공하는지로 판단할 수 없습니다.  
Blue/Green, Canary 배포에서는 스키마 호환성, 데이터 호환성, Old/New 공존 구간, rollback 가능성, DDL 실행 비용을 함께 고려해야 합니다.

가장 중요한 기준은 다음과 같습니다.

> Pre-deploy는 Old가 견딜 수 있는 확장만, Post-deploy는 Old가 완전히 사라진 뒤 수행할 수 있는 축소와 제약만 담는다.
