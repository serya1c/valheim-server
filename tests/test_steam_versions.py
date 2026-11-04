"""Steam build discovery: public branch, trustworthy installed manifests, no downloads."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import steam_versions as steam


def app_info(build='26249040'):
    return '''Steam Console Client
Connecting anonymously to Steam Public...OK
Waiting for client config...OK
"892970" { "depots" { "branches" { "public" { "buildid" "99999999" } } } }
"896660"
{
    "common" { "name" "Valheim Dedicated Server" "literal" "{" }
    "depots"
    {
        "896661" { "manifests" { "public" { "gid" "111111111" } } }
        "branches"
        {
            "public-test" { "buildid" "88888888" "pwdrequired" "1" }
            "public" { "buildid" "''' + build + '''" "timeupdated" "1793190000" }
            "old-version" { "buildid" "77777777" }
        }
    }
}
Unloading Steam API...OK
'''


def manifest(build='26249040', appid='896660', flags='4'):
    return ('"AppState"\n{\n"appid" "' + appid + '"\n"StateFlags" "' + flags
            + '"\n"buildid" "' + build + '"\n"installdir" "Valheim Dedicated Server"\n}')


class SteamVersionParserTests(unittest.TestCase):
    def test_public_build_ignores_other_apps_depots_and_beta_branches(self):
        self.assertEqual(steam.public_build_id(app_info()), '26249040')

    def test_whitespace_comments_quoted_braces_and_escaped_strings(self):
        text = app_info().replace('"literal" "{"', '"literal" "}" // a comment\n"description" "quote: \\" and slash: \\\\"')
        self.assertEqual(steam.public_build_id(text), '26249040')

    def test_errors_outside_app_info_reject_cached_metadata(self):
        for error in ('ERROR! Failed to connect to Steam', 'Unable to connect', 'Not logged on'):
            with self.subTest(error=error), self.assertRaises(ValueError):
                steam.public_build_id(error + '\n' + app_info())

    def test_error_words_inside_a_description_are_not_connection_failures(self):
        self.assertEqual(steam.public_build_id(app_info().replace('"literal" "{"', '"literal" "FAILED to flee"')), '26249040')

    def test_locale_and_thread_priority_warnings_do_not_hide_a_valid_build(self):
        warnings = "ILocalize::AddFile() failed to load file \"public/steambootstrapper_english.txt\".\nWARNING: setlocale('en_US.UTF-8') failed, using locale: 'C'.\nWARNING: failed to set thread priority\n"
        self.assertEqual(steam.public_build_id(warnings + app_info()), '26249040')

    def test_missing_unbalanced_duplicate_or_nonpublic_metadata_fails_closed(self):
        cases = [
            '', 'No app info for AppID 896660 found, requesting...',
            app_info().replace('"896660"', '"123456"'),
            app_info() + app_info(),
            app_info().replace('"public" { "buildid" "26249040"', '"public" { "buildid" "26249040" "buildid" "123"'),
            app_info().replace('"public" { "buildid" "26249040"', '"public" { "pwdrequired" "1" "buildid" "26249040"'),
            app_info().replace('"timeupdated" "1793190000" }', '"timeupdated" "1793190000"'),
            app_info().replace('"public" { "buildid" "26249040"', '"private" { "buildid" "26249040"'),
            app_info().replace('"branches"\n        {', '"branches" "broken"\n        {'),
        ]
        for text in cases:
            with self.subTest(text=text[:80]), self.assertRaises(ValueError):
                steam.public_build_id(text)

    def test_build_id_is_a_positive_bounded_decimal_not_a_game_version(self):
        for invalid in ('0', '-1', '1.0.21', ' 123', '1e20', '9' * 21, ''):
            with self.subTest(build=invalid), self.assertRaises(ValueError):
                steam.public_build_id(app_info(invalid))

    def test_parser_rejects_too_large_deep_and_nul_input(self):
        for text in (app_info() + '\0', 'x' * (steam.MAX_OUTPUT + 1),
                     '"896660" {' + '"nested" {' * 34 + '}' * 35):
            with self.assertRaises(ValueError):
                steam.public_build_id(text)

    def test_fully_installed_manifest_and_case_insensitive_keys(self):
        self.assertEqual(steam.manifest_build_id(manifest()), '26249040')
        self.assertEqual(steam.manifest_build_id(manifest().lower()), '26249040')

    def test_partial_wrong_app_duplicate_or_trailing_manifest_is_unknown(self):
        cases = [manifest(flags=flag) for flag in ('0', '2', '6', '1024', '')]
        cases += [manifest(appid='892970'), manifest().replace('"buildid"', '"appid"'),
                  manifest() + '"another" {}', manifest(build='1.0.21')]
        for text in cases:
            with self.subTest(text=text), self.assertRaises(ValueError):
                steam.manifest_build_id(text)


class InstalledSteamVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.release = Path(self.tmp.name) / 'release'
        self.directory = self.release / 'steamapps'
        self.directory.mkdir(parents=True)
        self.path = self.directory / 'appmanifest_896660.acf'

    def tearDown(self):
        self.tmp.cleanup()

    def test_known_good_manifest_and_bom_are_read(self):
        self.path.write_bytes(b'\xef\xbb\xbf' + manifest().encode())
        self.assertEqual(steam.installed_build_id(self.release), '26249040')

    def test_absent_empty_corrupt_or_large_manifest_returns_none(self):
        self.assertIsNone(steam.installed_build_id(self.release))
        for raw in (b'', b'not KeyValues', b'\xff\xfe', b'x' * (steam.MAX_MANIFEST + 1), manifest(flags='6').encode()):
            self.path.write_bytes(raw)
            self.assertIsNone(steam.installed_build_id(self.release))

    def test_manifest_symlink_is_not_followed(self):
        source = Path(self.tmp.name) / 'outside.acf'
        source.write_text(manifest(), encoding='utf-8')
        try:
            self.path.symlink_to(source)
        except OSError:
            self.skipTest('Symlink privilege is unavailable')
        self.assertIsNone(steam.installed_build_id(self.release))


class SteamQueryTests(unittest.TestCase):
    @staticmethod
    def process(output=None, returncode=0, running=False):
        def create(command, **kwargs):
            if output:
                kwargs['stdout'].write(output.encode())
                kwargs['stdout'].flush()
            proc = MagicMock()
            proc.returncode = returncode
            proc.poll.return_value = None if running else returncode
            return proc
        return create

    def test_query_refreshes_only_metadata_and_logs_the_build(self):
        log = MagicMock()
        with patch('steam_versions.subprocess.Popen', side_effect=self.process(app_info())) as spawn, patch.dict(os.environ, PANEL_PASSWORD='do-not-pass'):
            self.assertEqual(steam.query_public_build(log=log), '26249040')
        command = spawn.call_args.args[0]
        self.assertNotIn('+app_update', command)
        self.assertNotIn('+force_install_dir', command)
        self.assertEqual(command[command.index('+app_info_update') + 1], '1')
        self.assertEqual(command[command.index('+app_info_print') + 1], '896660')
        self.assertNotIn('PANEL_PASSWORD', spawn.call_args.kwargs['env'])
        log.assert_called_once_with('Последняя сборка сервера Steam: 26249040')

    def test_nonzero_or_zero_with_invalid_metadata_never_returns_a_build(self):
        for output, code in ((app_info(), 1), ('', 0), ('ERROR! Failed to connect\n' + app_info(), 0)):
            with patch('steam_versions.subprocess.Popen', side_effect=self.process(output, code)), self.assertRaises(RuntimeError):
                steam.query_public_build()

    def test_timeout_and_cancellation_kill_only_the_query_process(self):
        with patch('steam_versions.subprocess.Popen', side_effect=self.process(running=True)), patch('steam_versions.time.monotonic', side_effect=[0, 301]), patch('steam_versions._kill') as kill:
            with self.assertRaisesRegex(RuntimeError, 'отведённое время'):
                steam.query_public_build()
            kill.assert_called_once()
        cancelled = MagicMock(side_effect=[False, True])
        with patch('steam_versions.subprocess.Popen', side_effect=self.process(running=True)), patch('steam_versions._kill') as kill:
            with self.assertRaisesRegex(RuntimeError, 'отменена'):
                steam.query_public_build(cancelled=cancelled)
            kill.assert_called_once()

    def test_cancel_before_launch_and_invalid_timeout_do_not_spawn(self):
        with patch('steam_versions.subprocess.Popen') as spawn:
            with self.assertRaises(RuntimeError):
                steam.query_public_build(cancelled=lambda: True)
            for timeout in (0, -1, 301):
                with self.assertRaises(ValueError):
                    steam.query_public_build(timeout=timeout)
            spawn.assert_not_called()

    def test_query_output_is_bounded(self):
        with patch('steam_versions.MAX_OUTPUT', 1024), patch('steam_versions.subprocess.Popen', side_effect=self.process('x' * 1025)):
            with self.assertRaises(RuntimeError):
                steam.query_public_build()


if __name__ == '__main__':
    unittest.main()
