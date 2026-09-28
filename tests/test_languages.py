import json
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]

class LanguageTests(unittest.TestCase):
    def test_static_ui_has_english_catalog_entries(self):
        source=(ROOT/'app/static/i18n-catalog.js').read_text(encoding='utf-8-sig')
        catalog=json.loads(source.split('window.HEARTH_EN = ',1)[1].split(';\nwindow.HEARTH_PATTERNS',1)[0])
        missing=[]
        class Parser(HTMLParser):
            def handle_data(self,text):
                text=text.strip()
                if re.search('[А-Яа-яЁё]',text) and '{{' not in text and text not in catalog:missing.append(text)
            def handle_starttag(self,tag,attrs):
                for key,value in attrs:
                    if key in ('title','placeholder','aria-label') and value and re.search('[А-Яа-яЁё]',value) and value not in catalog:missing.append(value)
        for name in ('index.html','setup.html','landing.html'):
            Parser().feed((ROOT/'app/static'/name).read_text(encoding='utf-8-sig'))
        self.assertEqual(missing,[])
        self.assertTrue(all(isinstance(v,str) and v for v in catalog.values()))

    def test_scripts_loaded_before_application_and_all_surfaces_have_switch(self):
        for name,application in [('index.html','app.js'),('setup.html','setup.js'),('landing.html','landing.js')]:
            html=(ROOT/'app/static'/name).read_text(encoding='utf-8-sig')
            self.assertLess(html.index('/i18n-catalog.js'),html.index('/i18n.js'))
            self.assertLess(html.index('/i18n.js'),html.index('/'+application))
            self.assertIn('data-language-switch',html)
