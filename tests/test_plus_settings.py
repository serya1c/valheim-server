"""Read and edit the new upstream V+ entries without changing unrelated settings."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from configuration import cfg_entries, edit_cfg

FIXTURE = Path(__file__).with_name('fixtures') / 'valheim-plus-10.4.cfg'


class PlusSettingsTests(unittest.TestCase):
    def setUp(self):
        self.text = FIXTURE.read_text(encoding='utf-8')
        self.entries = {entry['id']: entry for entry in cfg_entries(self.text)}

    def test_all_new_fields_are_editable_and_defaults_keep_sections_disabled(self):
        self.assertEqual(len(self.entries), 28)  # 26 new fields + two existing AnimalType flags.
        self.assertEqual(self.entries['Adrenaline/enabled']['value'], 'false')
        changes = {'Adrenaline/gainMultiplier': '50.5', 'Map/syncPins': 'true',
                   'Windmill/stopAutoFuelOatThreshold': '100', 'Pickable/seeds': '200',
                   'Gathering/petrifiedTissue': '-50', 'LootDrop/callerMouldDropChanceMultiplier': '100',
                   'Inventory/drakkarInventoryRows': '10'}
        result = {e['id']: e['value'] for e in cfg_entries(edit_cfg(self.text, changes))}
        for ident, entry in self.entries.items():
            self.assertEqual(result[ident], changes.get(ident, entry['value']))

    def test_inventory_ranges_come_from_author_metadata_and_are_enforced(self):
        ranges = {'graustenChestColumns': (3, 8), 'graustenChestRows': (3, 20),
                  'wardrobeColumns': (3, 8), 'wardrobeRows': (3, 20),
                  'barrelColumns': (3, 8), 'barrelRows': (2, 20),
                  'drakkarInventoryColumns': (6, 8), 'drakkarInventoryRows': (3, 30)}
        for key, (low, high) in ranges.items():
            ident = 'Inventory/' + key
            with self.subTest(key=key):
                entry = self.entries[ident]
                self.assertEqual((entry['kind'], entry['min'], entry['max']), ('int', low, high))
                for value in (low, high):
                    edit_cfg(self.text, {ident: str(value)})
                for value in (low - 1, high + 1, 3.5):
                    with self.assertRaises(ValueError):
                        edit_cfg(self.text, {ident: str(value)})

    def test_adrenaline_does_not_invent_a_cfg_range_for_runtime_clamping(self):
        for key in ('gainMultiplier', 'decayMultiplier', 'trinketCostMultiplier', 'surgeDurationMultiplier'):
            ident = 'Adrenaline/' + key
            entry = self.entries[ident]
            self.assertEqual((entry['kind'], entry['min'], entry['max'], entry['default']),
                             ('float', None, None, '0'))
            edit_cfg(self.text, {ident: '-100'})
            for value in ('NaN', 'Infinity'):
                with self.assertRaises(ValueError):
                    edit_cfg(self.text, {ident: value})

    def test_animal_flags_accept_multiple_species_including_moose(self):
        for section in ('Tameable', 'Procreation'):
            ident = section + '/animalTypes'
            entry = self.entries[ident]
            self.assertTrue(entry['flags'])
            self.assertIn('Moose', entry['options'])
            for value in ('Boar, Moose', 'boar, wolf, moose', 'All', 'None'):
                edited = edit_cfg(self.text, {ident: value})
                self.assertEqual(next(e['value'] for e in cfg_entries(edited) if e['id'] == ident), value)
            for value in ('', 'Boar,', 'Moose, Dragon', 'Boar\nMoose'):
                with self.assertRaises(ValueError):
                    edit_cfg(self.text, {ident: value})

    def test_scalar_options_still_reject_combinations_and_edit_preserves_other_lines(self):
        text = '[Example]\r\n# Custom comment\r\n# Setting type: String\r\n# Acceptable values: One, Two\r\nchoice = One\r\nnote = keep me\r\n'
        self.assertFalse(cfg_entries(text)[0]['flags'])
        with self.assertRaises(ValueError):
            edit_cfg(text, {'Example/choice': 'One, Two'})
        self.assertEqual(edit_cfg(text, {'Example/choice': 'Two'}), text.replace('choice = One', 'choice = Two'))


if __name__ == '__main__':
    unittest.main()
