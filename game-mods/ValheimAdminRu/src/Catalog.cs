using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;
using UnityEngine;

namespace ValheimAdminRu
{
    /// <summary>Reads RU/EN prefab labels without changing the game's language or prefab identifiers.</summary>
    public sealed class Catalog
    {
        public sealed class Entry
        {
            public readonly string Id;
            public readonly string NameRu;
            public readonly string NameEn;
            public string Name => Locale.Language == "en" ? NameEn : NameRu;
            public Entry(string id, string name) : this(id, name, name) { }
            public Entry(string id, string nameRu, string nameEn) { Id = id; NameRu = nameRu; NameEn = nameEn; }
            public bool Matches(string search)
            {
                return string.IsNullOrWhiteSpace(search)
                    || Name.IndexOf(search.Trim(), StringComparison.OrdinalIgnoreCase) >= 0
                    || Id.IndexOf(search.Trim(), StringComparison.OrdinalIgnoreCase) >= 0;
            }
        }

        public readonly List<Entry> Items = new List<Entry>();
        public readonly List<Entry> Mobs = new List<Entry>();
        private readonly Dictionary<string, string> _russian = new Dictionary<string, string>(StringComparer.Ordinal);
        private readonly Dictionary<string, string> _english = new Dictionary<string, string>(StringComparer.Ordinal);
        private readonly Regex _token = new Regex(@"\$([A-Za-z0-9_]+)");
        private readonly Regex _tags = new Regex(@"<[^>]*>");
        private ObjectDB _db;
        private ZNetScene _scene;
        private int _itemCount = -1;
        private int _prefabCount = -1;
        private bool _loadedLanguage;
        private string _language = "";

        public void Ensure()
        {
            ObjectDB db = ObjectDB.instance;
            ZNetScene scene = ZNetScene.instance;
            if (!db || !scene) return;
            if (_language != Locale.Language)
            { _language = Locale.Language; _itemCount = -1; }
            if (_db == db && _scene == scene && _itemCount == db.m_items.Count && _prefabCount == scene.m_prefabs.Count) return;
            LoadLanguage();
            Items.Clear();
            Mobs.Clear();
            var itemIds = new HashSet<string>(StringComparer.Ordinal);
            var mobIds = new HashSet<string>(StringComparer.Ordinal);
            foreach (GameObject prefab in db.m_items)
            {
                if (!prefab || !scene.GetPrefab(prefab.name) || !itemIds.Add(prefab.name)) continue;
                ItemDrop item = prefab.GetComponent<ItemDrop>();
                if (item && item.m_itemData != null && item.m_itemData.m_shared != null)
                    Items.Add(new Entry(prefab.name, Label(item.m_itemData.m_shared.m_name, prefab.name, "ru"), Label(item.m_itemData.m_shared.m_name, prefab.name, "en")));
            }
            foreach (GameObject prefab in scene.m_prefabs)
            {
                if (!prefab || prefab.GetComponent<Player>() || !mobIds.Add(prefab.name)) continue;
                Character character = prefab.GetComponent<Character>();
                if (character && prefab.GetComponent<BaseAI>()) Mobs.Add(new Entry(prefab.name, Label(character.m_name, prefab.name, "ru"), Label(character.m_name, prefab.name, "en")));
            }
            var comparer = StringComparer.Create(Locale.Culture, true);
            Comparison<Entry> sort = (a, b) =>
            {
                int result = comparer.Compare(a.Name, b.Name);
                return result != 0 ? result : StringComparer.Ordinal.Compare(a.Id, b.Id);
            };
            Items.Sort(sort);
            Mobs.Sort(sort);
            _db = db;
            _scene = scene;
            _itemCount = db.m_items.Count;
            _prefabCount = scene.m_prefabs.Count;
        }

        private string Label(string value, string fallback, string language)
        {
            if (fallback == HammerItem.PrefabName) return Locale.Translate("Супермолот администратора", language);
            if (string.IsNullOrWhiteSpace(value)) return fallback;
            Dictionary<string, string> labels = language == "en" ? _english : _russian;
            string translated = _token.Replace(value, match =>
            {
                string text;
                return labels.TryGetValue(match.Groups[1].Value, out text) ? text : match.Value;
            });
            // Third-party prefabs without a translation retain their game-localized name or identifier.
            if (translated.IndexOf('$') >= 0 && Localization.instance != null)
                translated = Localization.instance.Localize(translated);
            translated = _tags.Replace(translated, "").Trim();
            return string.IsNullOrEmpty(translated) || translated[0] == '[' ? fallback : translated;
        }

        private void LoadLanguage()
        {
            if (_loadedLanguage) return;
            LocalizationSettings settings = Resources.Load<LocalizationSettings>("LocalizationSettings");
            if (!settings || settings.Localizations == null) return;
            foreach (TextAsset file in settings.Localizations)
            {
                if (!file) continue;
                List<List<string>> rows = ReadCsv(file.text);
                if (rows.Count == 0) continue;
                int russianColumn = rows[0].FindIndex(cell => cell.Trim().Trim('\uFEFF') == "Russian");
                int englishColumn = rows[0].FindIndex(cell => cell.Trim().Trim('\uFEFF') == "English");
                if (russianColumn < 0 && englishColumn < 0) continue;
                for (int i = 1; i < rows.Count; i++)
                {
                    List<string> row = rows[i];
                    if (row.Count < 2) continue;
                    string key = row[0].Trim().TrimStart('$', '\uFEFF');
                    if (key.Length == 0 || key.StartsWith("//", StringComparison.Ordinal)) continue;
                    string english = englishColumn >= 0 && row.Count > englishColumn ? row[englishColumn].Trim() : row[1].Trim();
                    string russian = russianColumn >= 0 && row.Count > russianColumn ? row[russianColumn].Trim() : "";
                    if (english.Length == 0) english = row[1].Trim();
                    if (russian.Length == 0) russian = english;
                    if (russian.Length > 0) _russian[key] = russian;
                    if (english.Length > 0) _english[key] = english;
                }
            }
            _loadedLanguage = true;
        }

        // Supports commas, CRLF, quoted newlines and doubled quotes in the game's CSV assets.
        private static List<List<string>> ReadCsv(string text)
        {
            var rows = new List<List<string>>();
            var row = new List<string>();
            var cell = new StringBuilder();
            bool quoted = false;
            for (int i = 0; i < text.Length; i++)
            {
                char c = text[i];
                if (c == '"')
                {
                    if (quoted && i + 1 < text.Length && text[i + 1] == '"') { cell.Append('"'); i++; }
                    else quoted = !quoted;
                }
                else if (!quoted && (c == ',' || c == '\r' || c == '\n'))
                {
                    row.Add(cell.ToString());
                    cell.Length = 0;
                    if (c != ',')
                    {
                        rows.Add(row);
                        row = new List<string>();
                        if (c == '\r' && i + 1 < text.Length && text[i + 1] == '\n') i++;
                    }
                }
                else cell.Append(c);
            }
            if (cell.Length > 0 || row.Count > 0) { row.Add(cell.ToString()); rows.Add(row); }
            return rows;
        }
    }
}
