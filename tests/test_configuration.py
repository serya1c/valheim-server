import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from configuration import Configuration, cfg_entries, edit_cfg, default_world, atomic_text
from server import Manager

CFG = '''## Example generated configuration\r
[Server]\r
# Setting type: Boolean\r
# Default value: false\r
enabled = false\r
\r
## Maximum players\r
# Setting type: Int32\r
# Acceptable value range: From 1 to 200\r
maxPlayers = 10\r
[Player]\r
# Setting type: Single\r
baseMaximumWeight = 300.5\r
# Setting type: String\r
note = original\r
'''


class ConfigTests(unittest.TestCase):
    def test_public_policy_overrides_saved_private_mode_and_adds_site(self):
        settings=self.config.load()
        settings['server'].update(name='Loki',public=False)
        atomic_text(self.config.path,json.dumps(settings))
        with patch.dict(os.environ, REQUIRE_PUBLIC_LISTING='1'):
            args=self.config.launch_args()
            self.assertEqual(args[args.index('-public')+1],'1')
            self.assertEqual(args[args.index('-name')+1],'Loki | https://loki.ach-play.ru')
            self.assertTrue(self.config.view()['server']['public'])
            self.assertTrue(self.config.view()['listing_required'])

    def test_private_policy_remains_available_explicitly(self):
        settings=self.config.load()
        settings['server']['public']=False
        atomic_text(self.config.path,json.dumps(settings))
        with patch.dict(os.environ, REQUIRE_PUBLIC_LISTING='0'):
            args=self.config.launch_args()
            self.assertEqual(args[args.index('-public')+1],'0')
            self.assertEqual(args[args.index('-name')+1],'Test server')

    def test_advertised_name_is_bounded_and_site_not_duplicated(self):
        with patch.dict(os.environ,REQUIRE_PUBLIC_LISTING='1'):
            for name in ['A'*80,'Loki | https://loki.ach-play.ru']:
                settings=self.config.load();settings['server']['name']=name
                atomic_text(self.config.path,json.dumps(settings))
                advertised=self.config.advertised_name()
                self.assertLessEqual(len(advertised),80)
                self.assertEqual(advertised.count('https://loki.ach-play.ru'),1)

    def test_landing_changes_publish_without_interrupting_game(self):
        values={'title':'Loki', 'address':'loki.ach-play.ru:2456', 'community_url':'http://discord.ach-play.ru', 'description':'В путь, викинг!'}
        with patch.object(self.manager,'stop') as stop, patch.object(self.manager,'start') as start:
            self.manager.configure(self.request('landing',values))
            stop.assert_not_called()
            start.assert_not_called()
        self.assertEqual(Configuration(self.base).load()['landing'],{**values, 'description_en':'', 'site_url':'https://loki.ach-play.ru'})
        self.assertTrue((self.base/'config/hearth-settings.previous.json').is_file())


    def test_english_description_persists_and_is_validated(self):
        self.manager.configure(self.request('landing',{'description_en':'Welcome to our world.'}))
        self.assertEqual(Configuration(self.base).load()['landing']['description_en'],'Welcome to our world.')
        with self.assertRaises(ValueError):
            self.manager.configure(self.request('landing',{'description_en':'x'*601}))
        self.assertEqual(Configuration(self.base).load()['landing']['description_en'],'Welcome to our world.')

    def test_landing_rejects_unsafe_links_and_invalid_addresses(self):
        for values in [{'community_url':'javascript:alert(1)'},{'community_url':'https://user:pass@example.com'},{'address':'example.com:99999'},{'address':'example.com:2456/path'},{'title':'x'*81},{'description':'x'*601}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.config.prepare(self.request('landing',values))

    def test_existing_settings_receive_landing_defaults(self):
        settings=self.config.load()
        settings.pop('landing')
        atomic_text(self.config.path,json.dumps(settings))
        self.assertEqual(self.config.load()['landing']['title'],'Loki')
        self.assertEqual(self.config.load()['server'],settings['server'])

    def test_cfg_help_keeps_author_description_separate_from_metadata(self):
        entries = cfg_entries('[Example]\n## First line\n## Second line <script>text</script>\n# Setting type: Single\n# Default value: 1.5\n# Acceptable value range: From 0.25 to 5\nrate = 2\n\n# Setting type: Boolean\nenabled = true\n')
        self.assertEqual(entries[0]['description'], 'First line\nSecond line <script>text</script>')
        self.assertEqual((entries[0]['min'], entries[0]['max'], entries[0]['default']), (0.25, 5, '1.5'))
        self.assertEqual(entries[1]['description'], '')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.env = patch.dict(os.environ, SERVER_PASSWORD='test-game-password', SERVER_NAME='Test server', WORLD_NAME='North', REQUIRE_PUBLIC_LISTING='0', SERVER_PUBLIC='1')
        self.env.start()
        self.manager = Manager(self.base)
        self.config = self.manager.config
        self.mod = self.base / 'config/org.bepinex.plugins.valheim_plus.cfg'
        self.mod.write_bytes(CFG.encode())

    def tearDown(self):
        self.env.stop()
        for h in self.manager.log.handlers[:]:
            h.close()
            self.manager.log.removeHandler(h)
        self.tmp.cleanup()

    def request(self, scope, values, restart=False):
        return dict(scope=scope, values=values, restart=restart, revision=self.config.revision())

    def test_new_domain_updates_listing_and_persists(self):
        self.manager.configure(self.request('landing', {'site_url':'https://north.example.org/'}))
        self.assertEqual(self.config.load()['landing']['site_url'], 'https://north.example.org')
        self.assertIn('https://north.example.org', self.config.advertised_name())
        self.assertNotIn('loki.ach-play.ru', self.config.advertised_name())
        self.manager.configure(self.request('server', {'add_site':False}))
        self.assertEqual(self.config.advertised_name(), 'Test server')

    def test_site_url_rejects_paths_credentials_and_injection(self):
        for url in ['https://user:password@site.org', 'https://site.org/path', 'https://site.org?x=1', 'https://site.org/#x', 'https://site.org:99999', 'https://site.org/\\bad', 'https://site.org;whoami', 'javascript:alert(1)', 'https://site.org\nX-Header: bad']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.config.prepare(self.request('landing', {'site_url':url}))

    def test_vanilla_selection_keeps_mod_config_but_disables_editing(self):
        original=self.mod.read_bytes()
        self.manager.configure(self.request('server', {'mode':'vanilla'}))
        self.assertEqual(self.config.load()['server']['mode'], 'vanilla')
        self.assertFalse(self.config.view()['mod']['available'])
        self.assertEqual(self.config.view()['mod']['entries'], [])
        with self.assertRaises(ValueError):
            self.config.prepare(self.request('mod', {'Server/maxPlayers':'20'}))
        self.assertEqual(self.mod.read_bytes(), original)

    def test_legacy_configuration_stays_plus_despite_changed_env(self):
        data=self.config.load();data['server'].pop('mode');data['server'].pop('add_site')
        atomic_text(self.config.path,json.dumps(data))
        with patch.dict(os.environ, SERVER_MODE='vanilla'):
            self.assertEqual(self.config.load()['server']['mode'], 'plus')

    def test_first_install_accepts_profile_env(self):
        with patch.dict(os.environ,SERVER_MODE='vanilla',SITE_URL='https://other.example',SERVER_ADDRESS='other.example:2466',GAME_PORT='2466',GAME_QUERY_PORT='2467'):
            self.assertEqual(self.config.load()['server']['mode'], 'vanilla')
            self.assertEqual(self.config.view()['ports'], {'game':2466,'query':2467})
            self.assertEqual(self.config.load()['landing']['site_url'], 'https://other.example')
        with patch.dict(os.environ,GAME_PORT='2466',GAME_QUERY_PORT='2457'), self.assertRaises(ValueError):
            self.config.view()

    def test_password_not_exposed(self):
        view = self.config.view()
        self.assertTrue(view['server']['password_set'])
        self.assertNotIn('password', view['server'])
        self.assertNotIn('test-game-password', json.dumps(view))

    def test_settings_persist_across_manager_recreation(self):
        self.manager.configure(self.request('server', {'name':'Русский сервер','password':''}))
        with patch.dict(os.environ, SERVER_NAME='Different env'):
            c = Configuration(self.base)
            self.assertEqual(c.load()['server']['name'], 'Русский сервер')
            self.assertEqual(c.load()['server']['password'],'test-game-password')
            self.assertTrue(c.advertised_name().startswith('Русский сервер'))

    def test_password_change_is_used_and_redacted(self):
        self.manager.configure(self.request('server', {'password':'new-password-777'}))
        self.assertIn('new-password-777',self.config.launch_args())
        self.manager.say('password new-password-777')
        self.assertEqual(self.manager.tail[-1],'password [REDACTED]')

    def test_invalid_settings_do_not_stop_game(self):
        for values in ({'name':''},{'password':'123'},{'saveinterval':0},{'public':'true'},{'saveinterval':True},{'shell':'x'}):
            with self.subTest(values=values), patch.object(self.manager,'stop') as stop:
                with self.assertRaises(ValueError):
                    self.manager.configure(self.request('server',values))
                stop.assert_not_called()

    def test_stale_revision_rejected(self):
        data = self.request('server',{'name':'first'})
        self.mod.write_text(CFG+'\n# External edit\n')
        with self.assertRaisesRegex(ValueError,'уже изменилась'):
            self.manager.configure(data)

    def test_mod_edit_preserves_comments_and_crlf(self):
        self.manager.configure(self.request('mod',{'Server/maxPlayers':'20','Server/enabled':'true'}))
        actual = self.mod.read_bytes().decode()
        self.assertEqual(actual,CFG.replace('maxPlayers = 10','maxPlayers = 20').replace('enabled = false','enabled = true'))
        self.assertEqual(len(list((self.base/'backups').glob('*-pre-config.tar.gz'))),1)

    def test_mod_bad_values_rejected(self):
        for values in ({'Server/maxPlayers':'0'},{'Server/maxPlayers':'NaN'},{'Server/enabled':'maybe'},{'Player/baseMaximumWeight':'inf'},{'Player/note':'x\n[Inject]\nenabled=true'},{'Unknown/key':'true'}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.config.prepare(self.request('mod',values))

    def test_missing_mod_is_explicit(self):
        self.mod.unlink()
        self.assertFalse(self.config.view()['mod']['available'])
        with self.assertRaisesRegex(ValueError,'первого запуска'):
            self.config.prepare(self.request('mod',{}))

    def test_unmanaged_world_does_not_reset_rules(self):
        self.assertNotIn('-preset',self.config.launch_args())

    def test_world_args_order_and_profiles(self):
        rules = default_world()
        rules.update(managed=True,preset='easy',keys=['nobuildcost'])
        rules['modifiers']['resources']='more'
        self.manager.configure(self.request('world',{'name':'Second','rules':rules}))
        args = self.config.launch_args()
        self.assertLess(args.index('-preset'),args.index('-modifier'))
        self.assertLess(args.index('-modifier'),args.index('-setkey'))
        self.assertEqual(args[args.index('-world')+1],'Second')
        self.manager.configure(self.request('world',{'name':'North','rules':default_world()}))
        self.assertNotIn('-preset',self.config.launch_args())
        self.assertEqual(self.config.load()['worlds']['Second']['preset'],'easy')

    def test_world_path_and_unknown_rules_rejected(self):
        for name in ('../North','North/other','North\n-inject',''):
            with self.subTest(name=name),self.assertRaises(ValueError):
                self.config.prepare(self.request('world',{'name':name,'rules':default_world()}))
        rules = default_world()
        rules['modifiers']['combat']='custom;sh'
        with self.assertRaises(ValueError):
            self.config.prepare(self.request('world',{'name':'North','rules':rules}))

    def test_restore_recovers_settings_together_with_world(self):
        self.manager.configure(self.request('server',{'name':'Before'}))
        name=self.manager.backup()
        self.manager.configure(self.request('server',{'name':'After'}))
        with patch.object(self.manager,'start'):
            self.manager.restore(name)
        self.assertEqual(self.config.load()['server']['name'],'Before')

    def test_apply_starts_installed_server(self):
        self.manager.state['active']='fixture'
        with patch.object(self.manager,'backup'), patch.object(self.manager,'start') as start:
            self.manager.configure(self.request('server',{'name':'Updated'},restart=True))
            start.assert_called_once()

    def test_no_restart_choice_leaves_game_stopped(self):
        with patch.object(self.manager,'start') as start:
            self.manager.configure(self.request('server',{'name':'Updated'},restart=False))
            start.assert_not_called()

    def test_backup_failure_leaves_old_settings(self):
        with patch.object(self.manager,'running',return_value=True),patch.object(self.manager,'stop'),patch.object(self.manager,'backup',side_effect=OSError('disk full')),patch.object(self.manager,'start') as start:
            with self.assertRaises(OSError):
                self.manager.configure(self.request('server',{'name':'Updated'}))
            start.assert_called_once()
        self.assertEqual(self.config.load()['server']['name'],'Test server')

    def test_duplicate_cfg_keys_rejected(self):
        with self.assertRaises(ValueError):
            cfg_entries('[S]\na=1\na=2')

    def test_declared_float_and_string_types_override_value_shape(self):
        text='[S]\n# Setting type: Single\nnumber=0\n# Setting type: String\ntext=123\n'
        entries=cfg_entries(text)
        self.assertEqual([e['kind'] for e in entries],['float','text'])
        self.assertIn('number= 0.5',edit_cfg(text,{'S/number':'0.5'}))


if __name__ == '__main__':
    unittest.main()
