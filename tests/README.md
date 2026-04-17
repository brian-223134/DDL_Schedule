# Splitter 테스트 fixture

이 디렉터리는 `production/migration_phase_splitter.py`와 `develop/migration_phase_splitter.py`의 회귀 테스트와 SQL fixture를 보관한다.

## 단위 테스트 실행

```bash
python3 -m unittest discover -s tests
```

## 로컬 MySQL 실행

Docker Desktop에서 integration test용 MySQL을 실행한다.

```bash
docker compose up -d mysql
docker compose ps
docker compose exec mysql mysql -uroot -proot -e "SELECT VERSION();"
```

기본 접속 정보:

```text
host: 127.0.0.1
port: 3307
root password: root
database: ddl_schedule_test
test user: ddl_test
test password: ddl_test
```

이미 다른 e2e MySQL 컨테이너가 떠 있어도 별도 컨테이너로 실행할 수 있다. 단, host port가 겹치면 안 된다. `3307`도 사용 중이라면 원하는 포트로 바꿔 실행한다.

```bash
MYSQL_HOST_PORT=3317 docker compose up -d mysql
```

동치성 테스트 스크립트는 host port로 접속하지 않고 `docker compose exec`로 컨테이너 내부의 `mysql` CLI를 사용하므로, 이 repo의 Compose 컨테이너만 정상 실행되어 있으면 된다.

로컬 MySQL 데이터를 모두 초기화하려면:

```bash
docker compose down -v
```

## Split 동치성 테스트

원본 forward SQL과 splitter가 생성한 SQL을 각각 빈 DB에 실행한 뒤, 최종 schema/data dump가 동일한지 비교한다.

```bash
scripts/test-split-equivalence.sh
```

직접 준비한 SQL로 실행하려면:

```bash
scripts/test-split-equivalence.sh \
  --baseline path/to/baseline.sql \
  --forward path/to/original_migration.sql
```

기본적으로 생성 결과에 `manual` phase가 있으면 실패한다. `manual` SQL을 먼저 검토한 뒤, 의도적으로 실행할 때만 아래 옵션을 사용한다.

```bash
scripts/test-split-equivalence.sh --include-manual
```

## 다음에 추가하면 좋은 테스트

- 실제 migration에서 새로운 edge case가 나오면 위험 패턴별로 작은 fixture를 하나씩 추가한다.
- helper 함수만 검증하지 말고, 가능하면 manifest의 phase count와 생성 파일 존재 여부까지 확인한다.
- fixture는 리뷰어가 각 statement가 왜 `pre`, `data`, `post`, `manual`에 속하는지 바로 이해할 수 있을 만큼 작게 유지한다.
- 운영 준비 단계에서는 `python3 -m unittest discover -s tests`를 실행하는 CI job과, `manual` statement가 있을 때 실패해야 하는 strict-mode 샘플을 추가한다.
