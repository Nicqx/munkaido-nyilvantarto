import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.db_tool import backup, summary


ROOT = Path(__file__).resolve().parents[1]


class DatabaseMigrationTests(unittest.TestCase):
    def test_backup_is_consistent_and_preserves_core_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.db"
            destination = Path(directory) / "backup.db"
            connection = sqlite3.connect(source)
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE users(id INTEGER PRIMARY KEY);
                CREATE TABLE work_entries(id INTEGER PRIMARY KEY);
                CREATE TABLE leave_allowances(id INTEGER PRIMARY KEY);
                INSERT INTO users VALUES (1);
                INSERT INTO work_entries VALUES (1);
                INSERT INTO work_entries VALUES (2);
                INSERT INTO leave_allowances VALUES (1);
                """
            )
            connection.commit()
            backup(source, destination)
            connection.close()

            self.assertEqual(
                summary(destination),
                {"users": 1, "work_entries": 2, "leave_allowances": 1},
            )
            self.assertEqual(os.stat(destination).st_mode & 0o777, 0o600)


class K3sManifestTests(unittest.TestCase):
    def test_single_replica_recreate_and_retained_host_storage(self):
        deployment = (ROOT / "k8s/base/deployment.yaml").read_text()
        storage = (ROOT / "k8s/overlays/nuc/storage.yaml").read_text()
        self.assertIn("type: Recreate", deployment)
        self.assertIn("replicas: 1", deployment)
        self.assertIn("imagePullPolicy: Never", deployment)
        self.assertIn("readOnlyRootFilesystem: true", deployment)
        self.assertIn("persistentVolumeReclaimPolicy: Retain", storage)
        self.assertIn("/var/lib/munkaido-nyilvantarto/data", storage)
        self.assertIn("kubernetes.io/hostname", storage)
        self.assertIn("- nuc", storage)

    def test_service_is_cluster_only_and_script_has_valid_bash_syntax(self):
        service = (ROOT / "k8s/base/service.yaml").read_text()
        self.assertIn("type: ClusterIP", service)
        self.assertNotIn("NodePort", service)
        for script in (
            ROOT / "scripts/k3s-manage.sh",
            ROOT / "migrate-to-k3s.sh",
            ROOT / "update.sh",
        ):
            subprocess.run(["bash", "-n", str(script)], check=True)


if __name__ == "__main__":
    unittest.main()
