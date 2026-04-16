# DDL Migration 타이밍 전략 — Blue/Green & Canary 배포

## 1. 배경

Blue/Green, Canary 배포 환경에서는 구 버전(Old)과 신 버전(New)이 동시에 같은 DB를 사용하는 시간이 존재한다.  
이 공존 구간 동안 DDL이 어느 시점에 적용되느냐에 따라 장애 여부가 결정된다.

```text
[Old Version] ──────────────────┐
                                ├── 공존 구간 (DB 공유)
[New Version]       ┌───────────┘
                    │
──────┬─────────────┬─────────────┬──────── 시간축
   배포 전       배포 중        배포 후
  Pre-deploy    Rollout      Post-deploy
```

핵심 원칙:

> Migration은 Old/New 양쪽 버전 모두에서 오류가 발생하지 않아야 한다.

조금 더 운영적으로 표현하면 다음 조건을 모두 만족해야 한다.

- DDL 적용 후에도 **Old 코드가 정상 동작**해야 한다.
- DDL 적용 후에도 **New 코드가 정상 동작**해야 한다.
- New가 생성한 데이터를 Old가 읽더라도 문제가 없어야 한다.
- DDL 실행 중 테이블 락, full table rewrite, replication lag로 장애가 나지 않아야 한다.
- Post-deploy migration은 Old 웹 서버뿐 아니라 worker, cron, queue consumer까지 완전히 종료된 뒤 실행해야 한다.

## 2. 기본 전략: Expand → Migrate → Contract

Blue/Green, Canary 환경에서는 DB 변경을 한 번에 끝내기보다 다음 3단계로 나누는 것이 안전하다.

```text
1. Expand
   Old와 New 모두 호환되는 스키마를 먼저 추가한다.
   예: ADD nullable column, CREATE TABLE, ENUM 값 추가

2. Migrate
   New 코드 배포, dual-write, backfill, 데이터 정리, feature flag 전환을 수행한다.

3. Contract
   Old가 완전히 사라진 뒤 더 이상 필요 없는 스키마를 제거하거나 제약을 강화한다.
   예: DROP COLUMN, DROP TABLE, ADD NOT NULL, ADD FK, ENUM 축소
```

즉, Pre-deploy는 주로 **확장 계열**, Post-deploy는 주로 **삭제/제약 계열**이다.

## 3. DDL 유형별 실행 시점 분류

### 3.1 배포 전 실행 가능 — Pre-deploy

| DDL 유형 | 예시 | 이유 | 주의사항 |
|---|---|---|---|
| `CREATE TABLE` | 새 테이블 생성 | New가 참조할 테이블이 미리 존재해야 함. Old는 모르는 테이블이므로 대체로 영향 없음 | Old의 schema introspection, batch, ETL이 전체 테이블 목록을 가정하고 있지 않은지 확인 |
| `ADD COLUMN nullable` | `ALTER TABLE t ADD COLUMN x INT NULL` | New가 새 컬럼을 읽고 쓸 수 있어야 함. Old는 보통 해당 컬럼을 무시 | Old가 `SELECT *` 결과를 strict mapping 하는 경우 깨질 수 있음 |
| `ADD COLUMN NOT NULL DEFAULT` | `ALTER TABLE t ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'READY'` | Old가 INSERT 시 컬럼을 보내지 않아도 DB default가 채워짐 | Old가 명시적으로 `NULL`을 넣는 구조면 실패. DB 엔진에 따라 table rewrite/lock 가능 |
| ENUM 확장 | `ENUM('A','B')` → `ENUM('A','B','C')` | New가 새 값을 INSERT할 수 있어야 함 | Old가 새 ENUM 값 `C`를 읽어도 안전한지 확인 필요. 안전하지 않으면 feature flag로 새 값 쓰기를 늦춰야 함 |
| `CREATE INDEX` | 조회 성능 인덱스 추가 | 양쪽 버전 모두에 이점 | 대형 테이블에서는 락, replication lag, write 성능 저하 가능. online DDL 필요 여부 확인 |
| INSERT 시드 데이터 | 초기 설정값, 워크플로우 타입 등 | New가 참조할 데이터가 미리 존재해야 함 | idempotent 해야 함. `INSERT IGNORE`, `ON DUPLICATE KEY UPDATE` 등 고려 |
| nullable FK 컬럼 추가 | `ADD COLUMN userWorkflowId BIGINT NULL` | 컬럼 자체는 Old에 영향이 적음 | FK constraint는 별도 post-deploy로 분리 권장 |

### 3.2 배포 후 실행 필요 — Post-deploy

Post-deploy migration은 “New가 100% 배포됨”만으로는 부족하다.  
아래 조건을 만족한 뒤 실행하는 것이 안전하다.

- Old web instance 종료
- Old worker, cron, queue consumer 종료
- Old 버전으로 즉시 rollback 할 가능성이 낮아짐
- Old가 만들 수 있는 legacy 데이터가 더 이상 생성되지 않음
- 필요한 backfill/data cleanup 완료

| DDL 유형 | 예시 | 위험 |
|---|---|---|
| `DROP TABLE` | 미사용 테이블 제거 | Old가 아직 해당 테이블을 SELECT/INSERT 중이면 에러 |
| `DROP COLUMN` | 미사용 컬럼 제거 | Old가 해당 컬럼을 참조하는 쿼리를 실행하면 에러 |
| ENUM 축소 | `ENUM('A','B','C')` → `ENUM('A','B')` | Old 또는 rollback된 코드가 `C`를 INSERT하면 에러 |
| `ADD FOREIGN KEY` | `ADD CONSTRAINT fk_x FOREIGN KEY (...)` | Old가 FK 조건에 맞지 않는 데이터를 INSERT할 수 있음 |
| `ADD CHECK` | `ADD CHECK (...)` | Old가 CHECK 조건을 모르고 위반 데이터를 INSERT할 수 있음 |
| `ADD NOT NULL` | `MODIFY COLUMN x INT NOT NULL` | Old가 해당 컬럼에 NULL을 INSERT할 수 있음 |
| `ADD UNIQUE` | unique index/constraint 추가 | Old가 중복 데이터를 계속 만들 수 있으면 실패 또는 장애 |
| DELETE 시드 데이터 | 미사용 설정값 제거 | Old가 해당 데이터를 참조 중일 수 있음 |
| `DROP INDEX` | 기존 인덱스 제거 | 기능 장애는 아니어도 Old 쿼리 성능이 급격히 나빠질 수 있음 |

### 3.3 판단이 필요한 케이스 — Conditional

| DDL 유형 | 조건 | 권장 시점 |
|---|---|---|
| `ADD COLUMN NOT NULL DEFAULT` | Old가 해당 테이블에 INSERT하는가? DB default가 있는가? DDL이 table rewrite를 유발하는가? | 조건 충족 시 Pre-deploy 가능 |
| `ALTER COLUMN SET DEFAULT` | Old가 DB default에 의존하는가? | Old/New 동작 차이를 확인 후 결정 |
| `DROP DEFAULT` | Old가 default에 의존하는가? | 대체로 Post-deploy |
| `RENAME COLUMN` | Old/New 모두 영향 | 사실상 `ADD new column` + dual-write + backfill + `DROP old column` |
| `RENAME TABLE` | Old/New 모두 영향 | 사실상 `CREATE new table` + dual-write/backfill + `DROP old table` |
| 타입 확장 | `INT` → `BIGINT`, `VARCHAR(100)` → `VARCHAR(255)` | 대체로 Pre-deploy |
| 타입 축소 | `VARCHAR(255)` → `VARCHAR(100)` | 데이터 정리 후 Post-deploy |
| 컬럼 의미 변경 | 같은 컬럼이지만 의미가 바뀜 | 새 컬럼 추가 후 점진 전환 권장 |
| 대량 `UPDATE` backfill | Old가 동시에 쓰는가? | chunk 단위, idempotent, 재실행 가능하게 설계 |
| trigger 추가 | Old write path에도 영향을 주는가? | 영향 분석 후 결정. 보통 Conditional |

## 4. 현재 Migration 파일 위험도 분석

### 4.1 안전 — 배포 전 실행 가능

| 파일 | DDL 유형 | 보완 메모 |
|---|---|---|
| `create_compensation_break_policy` | `CREATE TABLE` + `INSERT seed` | seed는 idempotent 하게 작성 권장 |
| `create_stability_report_table` | `CREATE TABLE` | Pre-deploy 가능 |
| `create_stock_level_alert_dismissal` | `CREATE TABLE` | Pre-deploy 가능 |
| `add_type_to_curriculum_survey_trigger` | `ADD COLUMN ENUM NOT NULL DEFAULT` | DB-level default가 있고 Old가 명시적 NULL을 넣지 않는지 확인 |
| `add_target_role_to_curriculum_survey_trigger` | `ADD COLUMN ENUM NOT NULL DEFAULT` | 위와 동일 |
| `add_userworkflowid_to_request_schedule` | `ADD COLUMN nullable` | FK는 분리 필요 |
| `add_post_workflow_id_and_proof_workflow_type` | `ADD COLUMN nullable` + `INSERT seed` | FK는 분리 필요 |
| `restructure_confirmation_reason` | `ADD COLUMN JSON nullable` | Old의 `SELECT *` strict mapping 여부 확인 |
| `add_reason_to_attendance_schedule_snapshot` | `ADD COLUMN TEXT nullable` | Pre-deploy 가능 |
| `add_help_team_job_rank` | ENUM 확장 | Old가 새 ENUM 값을 읽어도 안전한지 확인 |
| `add_military_reserve_enum` | ENUM 확장 + `CREATE INDEX` | 대형 테이블이면 online DDL 필요 여부 확인 |
| `add_suspected_inbound_history_index` | `CREATE INDEX` | 논리적으로 안전하나 락/성능 영향 확인 |

### 4.2 주의 — 배포 후 실행 필요

| 파일 | DDL 유형 | 위험 |
|---|---|---|
| `drop_workforce_stability_slot` | `DROP TABLE` | Old가 테이블 참조 시 에러 |
| `remove_noslot_intent` | `UPDATE` + ENUM 축소 | Old 또는 rollback 코드가 `NOSLOT`을 INSERT하면 에러 |

`remove_noslot_intent`는 특히 rollback window가 중요하다.  
ENUM 축소 이후에는 Old 버전으로 되돌렸을 때 `NOSLOT` write가 실패할 수 있으므로, Old 종료뿐 아니라 rollback 가능성까지 고려해 충분히 늦게 실행하는 편이 안전하다.

### 4.3 혼합 — 분리가 필요한 파일

| 파일 | 안전한 부분, Pre-deploy | 위험한 부분, Post-deploy |
|---|---|---|
| `add_curriculum_survey_trigger_type_to_survey_user` | `ADD COLUMN` | `ADD CHECK CONSTRAINT` |
| `add_userworkflowid_to_request_schedule` | `ADD COLUMN` | `ADD FOREIGN KEY` |
| `add_post_workflow_id_and_proof_workflow_type` | `ADD COLUMN` + `INSERT seed` | `ADD FOREIGN KEY` |

혼합 파일은 하나의 migration으로 두지 않는 것이 좋다.  
Pre-deploy와 Post-deploy가 같은 파일에 섞이면 배포 파이프라인이 안전하게 순서를 제어할 수 없다.

## 5. 권장 Migration 작성 패턴

### 5.1 2-Phase Migration

하나의 기능 변경을 Pre-deploy / Post-deploy 두 파일로 분리한다.

```sql
-- Phase 1: Pre-deploy
-- 2026-04-09_add_userWorkflowId.pre.sql

ALTER TABLE request_schedule
  ADD COLUMN userWorkflowId BIGINT NULL;
```

```sql
-- Phase 2: Post-deploy
-- 2026-04-09_add_userWorkflowId.post.sql

ALTER TABLE request_schedule
  ADD CONSTRAINT fk_request_schedule_user_workflow
  FOREIGN KEY (userWorkflowId)
  REFERENCES user_workflow(id);
```

권장 흐름:

```text
1. Pre-deploy: nullable column 추가
2. New 배포: 새 컬럼 write 시작
3. Backfill: 기존 데이터 보정
4. Validation: orphan/null/invalid 데이터 확인
5. Post-deploy: FK, NOT NULL 등 constraint 추가
```

### 5.2 ENUM 변경 패턴

#### ENUM 확장

```sql
-- Pre-deploy
ALTER TABLE t
  MODIFY COLUMN c ENUM('A', 'B', 'C') NOT NULL;
```

단, New가 `C`를 쓰기 전에 Old가 `C`를 읽어도 안전한지 확인해야 한다.

안전하지 않은 경우:

```text
1. Pre-deploy: ENUM 값 C 추가
2. New 배포: 코드에는 C 처리 로직 포함, 하지만 feature flag OFF
3. Old 완전 종료
4. Feature flag ON: C 쓰기 시작
```

#### ENUM 축소

```sql
-- Phase 1: New 코드에서 DEPRECATED 값 사용 중단
-- Phase 2: 데이터 정리
UPDATE t
SET c = 'A'
WHERE c = 'DEPRECATED';

-- Phase 3: Post-deploy
ALTER TABLE t
  MODIFY COLUMN c ENUM('A', 'B') NOT NULL;
```

ENUM 축소는 Old 종료와 rollback window 종료 이후에 실행하는 것이 안전하다.

### 5.3 컬럼 삭제 패턴

```text
1. Pre-deploy
   New 코드에서 old_column read/write 제거

2. Rollout
   Old/New 공존 구간 모니터링

3. Post-deploy
   Old 완전 종료 후 컬럼 삭제
```

```sql
-- Post-deploy
ALTER TABLE t
  DROP COLUMN old_column;
```

더 안전한 방식:

```text
1. New 코드에서 old_column 미사용
2. 로그/메트릭으로 old_column 접근이 없는지 확인
3. 일정 기간 후 DROP
```

### 5.4 컬럼 이름 변경 패턴

`RENAME COLUMN`은 Blue/Green 환경에서 위험하다.  
Old는 기존 이름을 사용하고 New는 새 이름을 사용하기 때문이다.

권장 패턴:

```text
1. Pre-deploy: new_column 추가
2. New v1 배포: old_column + new_column dual-write
3. Backfill: old_column 값을 new_column으로 복사
4. New v2 배포: new_column read, 필요 시 old_column write 유지
5. Old 완전 종료 확인
6. Post-deploy: old_column drop
```

```sql
-- Pre-deploy
ALTER TABLE t
  ADD COLUMN new_column VARCHAR(255) NULL;

-- Backfill
UPDATE t
SET new_column = old_column
WHERE new_column IS NULL;

-- Post-deploy
ALTER TABLE t
  DROP COLUMN old_column;
```

### 5.5 NOT NULL 추가 패턴

```text
1. Pre-deploy: nullable column 추가
2. New 코드 배포: 새 row에는 항상 값 write
3. Backfill: 기존 NULL 데이터 채우기
4. Validation: NULL이 없는지 확인
5. Post-deploy: NOT NULL 추가
```

```sql
-- Validation
SELECT COUNT(*)
FROM t
WHERE x IS NULL;

-- Post-deploy
ALTER TABLE t
  MODIFY COLUMN x INT NOT NULL;
```

### 5.6 FK 추가 패턴

```text
1. Pre-deploy: FK 컬럼만 nullable로 추가
2. New 코드 배포: 유효한 FK 값 write
3. Backfill: 기존 데이터 연결
4. Orphan 데이터 확인 및 정리
5. Post-deploy: FK constraint 추가
```

```sql
-- Validation
SELECT t.userWorkflowId
FROM request_schedule t
LEFT JOIN user_workflow u ON u.id = t.userWorkflowId
WHERE t.userWorkflowId IS NOT NULL
  AND u.id IS NULL;

-- Post-deploy
ALTER TABLE request_schedule
  ADD CONSTRAINT fk_request_schedule_user_workflow
  FOREIGN KEY (userWorkflowId)
  REFERENCES user_workflow(id);
```

## 6. Migration 파일 네이밍 제안

현재:

```text
YYYY-MM-DD_description.sql
```

권장:

```text
YYYY-MM-DD_description.pre.sql
YYYY-MM-DD_description.post.sql
YYYY-MM-DD_description.data.sql
YYYY-MM-DD_description.pre.rollback.sql
YYYY-MM-DD_description.post.rollback.sql
```

예시:

```text
2026-04-09_add_userWorkflowId.pre.sql
2026-04-09_backfill_userWorkflowId.data.sql
2026-04-09_add_userWorkflowId_fk.post.sql
```

추가 권장사항:

- `pre.sql`: Old/New 모두 호환되는 additive 변경만 포함
- `data.sql`: backfill, cleanup 등 데이터 변경
- `post.sql`: Old 종료 후 가능한 constraint/drop/shrink 변경
- rollback SQL도 Old/New 양쪽에서 안전한지 별도 검토
- destructive rollback보다 forward-fix를 우선 고려

## 7. 배포 파이프라인 내 실행 순서

```text
1. Pre-deploy migrations 실행
   ↓
2. New 버전 배포 시작
   Blue/Green swap 또는 Canary rollout
   ↓
3. Old/New 공존 구간
   모니터링, feature flag 제어, error rate 확인
   ↓
4. New 100% 전환
   ↓
5. Old 완전 종료 확인
   web, worker, cron, queue consumer 포함
   ↓
6. Rollback window 종료 또는 rollback 가능성 낮음 확인
   ↓
7. Data cleanup / backfill validation
   ↓
8. Post-deploy migrations 실행
   ↓
9. 모니터링
```

## 8. 운영 체크리스트

Migration 작성 시 아래를 확인한다.

- 이 DDL이 실행된 후 Old 버전 코드가 정상 동작하는가?
- 이 DDL이 실행된 후 New 버전 코드가 정상 동작하는가?
- New가 생성한 데이터를 Old가 읽어도 안전한가?
- 하나의 파일에 Pre-deploy와 Post-deploy DDL이 섞여 있지 않은가?
- ENUM 확장 시 Old가 unknown enum value를 처리할 수 있는가?
- ENUM 축소, DROP, 제약조건 추가가 포함되어 있다면 Post-deploy로 분류했는가?
- FK, CHECK, NOT NULL, UNIQUE 추가 전 기존 데이터 validation 쿼리가 있는가?
- 데이터 마이그레이션 `UPDATE`/`DELETE`가 Old 버전의 INSERT 패턴과 충돌하지 않는가?
- 대량 backfill은 chunk 단위이며 재실행 가능하게 작성되었는가?
- seed INSERT는 idempotent 한가?
- DDL이 table lock, table rewrite, replication lag를 유발하지 않는가?
- 대형 테이블의 `CREATE INDEX`, `MODIFY COLUMN`, `ADD COLUMN DEFAULT`에 online DDL 전략이 있는가?
- Old worker, cron, queue consumer까지 종료되었는가?
- rollback window가 끝나기 전에 destructive migration을 실행하지 않는가?
- Rollback SQL이 양쪽 버전 모두에서 안전한가?
- 실패 시 DDL rollback 대신 forward-fix가 가능한가?

## 9. 결론

이 문서의 방향은 맞다.  
다만 기존 버전에서는 “DDL의 기능적 호환성”에 초점이 강했고, 실제 운영에서 중요한 “데이터 호환성”, “Old가 새 값을 읽는 문제”, “DDL 실행 중 락”, “rollback window”가 조금 더 명시되면 좋다.

가장 중요한 보강 원칙은 이 문장이다.

> Pre-deploy는 Old가 견딜 수 있는 확장만, Post-deploy는 Old가 완전히 사라진 뒤 수행할 수 있는 축소와 제약만 담는다.

그리고 Canary 환경에서는 여기에 하나를 더 붙이는 것이 좋다.

> New가 쓸 수 있는 새 데이터가 Old에게도 읽힐 수 있다면, schema migration만으로는 충분하지 않고 feature flag 또는 staged rollout이 필요하다.
