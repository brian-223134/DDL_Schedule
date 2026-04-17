import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from develop.migration_phase_splitter import classify_statement  # noqa: E402

SCRIPT = ROOT / "develop" / "migration_phase_splitter.py"


class DevelopClassifyStatementTest(unittest.TestCase):
    def test_develop_phase_rules(self) -> None:
        cases = {
            "CREATE TABLE users (id BIGINT PRIMARY KEY);": "pre",
            "CREATE UNIQUE INDEX uq_users_email ON users (email);": "pre",
            "CREATE USER 'app'@'%' IDENTIFIED BY 'pw';": "post",
            "GRANT SELECT ON app.* TO 'reader'@'%';": "post",
            "REVOKE SELECT ON app.* FROM 'reader'@'%';": "post",
            "DROP TABLE legacy_users;": "post",
            "ALTER TABLE users ADD COLUMN nickname VARCHAR(64) NULL;": "post",
            "ALTER TABLE users DROP COLUMN legacy_name;": "post",
            "UPDATE users SET name = 'kim' WHERE id = 1;": "post",
        }

        for sql, expected_phase in cases.items():
            with self.subTest(sql=sql):
                phase, _reason = classify_statement(sql)
                self.assertEqual(phase, expected_phase)


class DevelopCliOutputTest(unittest.TestCase):
    def test_cli_writes_pre_post_files_and_manifest(self) -> None:
        sql = """
        CREATE TABLE users (id BIGINT PRIMARY KEY);
        ALTER TABLE users ADD COLUMN nickname VARCHAR(64) NULL;
        GRANT SELECT ON app.* TO 'reader'@'%';
        DROP TABLE legacy_users;
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "develop_mixed.sql"
            source.write_text(sql, encoding="utf-8")
            out_dir = temp_path / "split-output"

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(source),
                    "--out-dir",
                    str(out_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            manifest_path = out_dir / "develop_mixed.manifest.json"
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            self.assertEqual(manifest["result"]["phase_counts"], {"pre": 1, "post": 3})
            self.assertTrue((out_dir / "develop_mixed.pre.sql").exists())
            self.assertTrue((out_dir / "develop_mixed.post.sql").exists())


if __name__ == "__main__":
    unittest.main()
