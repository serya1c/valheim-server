"""Правило «нужен ли PR с пересобранным архивом Hearth Admin»."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import mod_archive

GAMES = ['1.0.16', '1.0.17', '1.0.20', '1.0.21', '1.0.30', '1.0.31']
SHA = 'b' * 64


def descriptor(version='0.4.4', games=None, sha=SHA):
    return {'id': 'Hearth-ValheimAdmin', 'version': version,
            'games': list(GAMES if games is None else games), 'sha256': sha}


class NeedsCommitTests(unittest.TestCase):
    def assertNeeded(self, expected, built, committed, archive_sha=SHA, refresh=False, event='schedule'):
        needed, reason = mod_archive.needs_commit(built, committed, archive_sha, refresh, event)
        self.assertIs(needed, expected, reason)
        self.assertTrue(reason)

    def test_byte_only_drift_on_nightly_rebuild_is_ignored(self):
        # Пересборка ночью: те же версия, allowlist и описатель — PR не нужен.
        self.assertNeeded(False, descriptor(), descriptor())

    def test_source_push_always_packages(self):
        self.assertNeeded(True, descriptor(), descriptor(), event='push')
        self.assertNeeded(True, descriptor(), descriptor(), event='workflow_dispatch')

    def test_new_game_build_always_packages(self):
        self.assertNeeded(True, descriptor(), descriptor(), refresh=True)

    def test_version_bump_needs_commit(self):
        self.assertNeeded(True, descriptor(version='0.4.5'), descriptor(version='0.4.4'))

    def test_allowlist_change_needs_commit(self):
        self.assertNeeded(True, descriptor(games=GAMES + ['1.0.32']), descriptor())

    def test_stale_descriptor_needs_commit(self):
        # Описатель ссылается на другой архив — это уже поломка, а не дрейф.
        self.assertNeeded(True, descriptor(), descriptor(), archive_sha='c' * 64)

    def test_identical_state_needs_nothing(self):
        self.assertNeeded(False, descriptor(), descriptor())


if __name__ == '__main__':
    unittest.main()
