import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    # 테스트를 어느 위치에서 실행해도 repo root의 production package를 import한다.
    sys.path.insert(0, str(ROOT))

from production.migration_phase_splitter import (  # noqa: E402
    Unit,
    classify_statement,
    infer_enum_phase_from_pair,
    parse_sql_file,
    split_sql_statements,
)


FIXTURES = ROOT / "tests" / "fixtures"
SCRIPT = ROOT / "production" / "migration_phase_splitter.py"


class SplitSqlStatementsTest(unittest.TestCase):
    def test_does_not_split_on_semicolon_inside_literal_or_comment(self) -> None:
        # 문자열과 주석 안의 세미콜론은 SQL statement 경계로 보면 안 된다.
        sql = """
        -- comment with ; should not split
        INSERT INTO logs(message) VALUES ('created;still same statement');
        /* block comment ; should not split */
        UPDATE logs SET message = "done;still same statement" WHERE id = 1;
        """

        statements = split_sql_statements(sql)

        self.assertEqual(len(statements), 2)
        self.assertIn("created;still same statement", statements[0])
        self.assertIn("done;still same statement", statements[1])


class ClassifyStatementTest(unittest.TestCase):
    def test_core_phase_rules(self) -> None:
        # 대표 DDL/DML 패턴이 기대 phase로 분류되는지 고정한다.
        cases = {
            "CREATE TABLE users (id BIGINT PRIMARY KEY);": "pre",
            "ALTER TABLE users ADD COLUMN nickname VARCHAR(64) NULL;": "pre",
            "CREATE INDEX idx_users_name ON users (name);": "pre",
            "INSERT INTO users(id) VALUES (1);": "data",
            "UPDATE users SET name = 'kim' WHERE id = 1;": "data",
            "ALTER TABLE users ADD COLUMN code VARCHAR(32) NOT NULL;": "post",
            "ALTER TABLE users DROP COLUMN legacy_name;": "post",
            "ALTER TABLE users ADD CONSTRAINT fk_team FOREIGN KEY (team_id) REFERENCES teams(id);": "post",
            "CREATE UNIQUE INDEX uq_users_email ON users (email);": "post",
            "ALTER TABLE users ADD COLUMN display_name VARCHAR(64) NULL, DROP COLUMN legacy_name;": "manual",
            "ALTER TABLE users RENAME COLUMN nickname TO display_name;": "manual",
        }

        for sql, expected_phase in cases.items():
            with self.subTest(sql=sql):
                # subTest를 사용하면 한 케이스가 실패해도 어떤 SQL이 문제인지 바로 확인할 수 있다.
                phase, _reason = classify_statement(sql)
                self.assertEqual(phase, expected_phase)

    def test_enum_pair_inference_moves_expansion_to_pre_and_shrink_to_post(self) -> None:
        # ENUM은 forward/rollback 쌍을 함께 봐야 expansion인지 shrink인지 판단할 수 있다.
        forward = [
            Unit(
                source_order=1,
                phase="manual",
                reason="before inference",
                sql="ALTER TABLE survey MODIFY COLUMN type ENUM('REGULAR', 'CURRICULUM') NOT NULL;",
                summary="",
            )
        ]
        rollback = [
            Unit(
                source_order=1,
                phase="manual",
                reason="before inference",
                sql="ALTER TABLE survey MODIFY COLUMN type ENUM('REGULAR') NOT NULL;",
                summary="",
            )
        ]

        infer_enum_phase_from_pair(forward, rollback)

        self.assertEqual(forward[0].phase, "pre")
        self.assertIn("ENUM expansion", forward[0].reason)
        self.assertEqual(rollback[0].phase, "post")
        self.assertIn("ENUM shrink", rollback[0].reason)


class CliOutputTest(unittest.TestCase):
    def test_cli_writes_phase_files_and_manifest_for_mixed_fixture(self) -> None:
        forward = FIXTURES / "mixed_forward.sql"
        rollback = FIXTURES / "mixed_forward.rollback.sql"

        # 생성 파일은 임시 디렉터리에만 쓰고 테스트 종료 후 자동 정리한다.
        with tempfile.TemporaryDirectory() as temp_dir:
            out_dir = Path(temp_dir) / "split-output"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--forward",
                    str(forward),
                    "--rollback",
                    str(rollback),
                    "--out-dir",
                    str(out_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            manifest_path = out_dir / "mixed_forward.manifest.json"
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            # phase count는 splitter 분류 규칙이 바뀌었는지 빠르게 감지하는 핵심 회귀 지표다.
            self.assertEqual(
                manifest["forward"]["phase_counts"],
                {"pre": 4, "data": 2, "post": 4, "manual": 3},
            )
            self.assertEqual(
                manifest["rollback"]["phase_counts"],
                {"pre": 0, "data": 1, "post": 2, "manual": 0},
            )
            self.assertTrue(manifest["forward"]["needs_manual_review"])
            self.assertFalse(manifest["rollback"]["needs_manual_review"])

            expected_files = [
                "mixed_forward.pre.sql",
                "mixed_forward.data.sql",
                "mixed_forward.post.sql",
                "mixed_forward.manual.sql",
                "mixed_forward.post.rollback.sql",
                "mixed_forward.data.rollback.sql",
            ]
            for filename in expected_files:
                with self.subTest(filename=filename):
                    self.assertTrue((out_dir / filename).exists())

    def test_strict_mode_fails_when_manual_phase_exists(self) -> None:
        forward = FIXTURES / "mixed_forward.sql"

        with tempfile.TemporaryDirectory() as temp_dir:
            # strict mode는 CI에서 manual-review statement를 막는 용도로 사용한다.
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--forward",
                    str(forward),
                    "--out-dir",
                    str(Path(temp_dir) / "split-output"),
                    "--strict",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("manual-review statements found", result.stderr)


class FixtureParseTest(unittest.TestCase):
    def test_fixture_parse_has_expected_statement_count(self) -> None:
        # fixture statement 수가 달라지면 phase count 기대값도 함께 재검토해야 한다.
        units = parse_sql_file(FIXTURES / "mixed_forward.sql")

        self.assertEqual(len(units), 13)
        self.assertEqual(units[0].phase, "pre")
        self.assertEqual(units[-1].phase, "manual")


if __name__ == "__main__":
    unittest.main()
