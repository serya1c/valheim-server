using System;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;
using TargetFlags = ValheimAdminRu.HammerTargets;

namespace ValheimAdminRu
{
    public sealed class AdminPanel
    {
        public bool Visible;
        public bool MapPickArmed;
        public bool PreviewEnabled = true;
        public float HammerRadius { get; private set; } = 5f;
        public float RepairRadius { get; private set; } = 5f;
        public TargetFlags HammerTargets { get; private set; } = TargetFlags.All;
        public float PreviewRadius
        {
            get
            {
                if (!PreviewEnabled) return 0f;
                if (Visible)
                {
                    if (_tab == 3) return _terrainRadius;
                    if (_tab == 4) return HammerRadius;
                    if (_tab == 5) return RepairRadius;
                }
                else if (_plugin.HammerEnabled) return HammerRadius;
                return 0f;
            }
        }
        public bool PreviewTerrain { get { return Visible && _tab == 3; } }

        private readonly Plugin _plugin;
        private readonly NetworkService _network;
        private readonly Catalog _catalog = new Catalog();
        private readonly List<PlayerRow> _displayPlayers = new List<PlayerRow>();
        private readonly List<Catalog.Entry> _displayItems = new List<Catalog.Entry>();
        private readonly List<Catalog.Entry> _displayMobs = new List<Catalog.Entry>();
        private readonly List<AuditRow> _displayAudit = new List<AuditRow>();
        private readonly List<BanRow> _displayBans = new List<BanRow>();
        private readonly List<SavedPoint> _displayPoints = new List<SavedPoint>();
        private readonly string[] _tabs = { "Игроки", "Предметы", "Мобы", "Рельеф", "Молот", "Строительство", "Точки", "Журнал" };
        private readonly string[] _terrainOperations = { "Выровнять", "Поднять", "Опустить" };
        private readonly Vector2[] _tabScroll = new Vector2[8];
        private Rect _window = new Rect(80f, 30f, 1120f, 820f);
        private Vector2 _playerScroll, _playerActionsScroll, _itemScroll, _mobScroll;
        private string _playerSearch = "", _itemSearch = "", _mobSearch = "", _pointSearch = "";
        private string _actorSearch = "", _actionSearch = "", _pointName = "", _moderationReason = "", _unbanIdentity = "";
        private string _itemCount = "1", _mobCount = "1";
        private long _selectedPlayer;
        private Catalog.Entry _selectedItem, _selectedMob;
        private int _tab, _terrainOperation;
        private float _terrainRadius = 5f, _terrainHeight = 1f;
        private string _confirmationKey = "", _confirmationDetails = "";
        private float _confirmationUntil, _nextRefresh;
        private bool _wasVisible, _canReturn;
        private GUIStyle _label, _title, _button, _selectedButton, _field, _box, _small, _tabButton, _toggle, _section;
        private int _lastWidth, _lastHeight;

        public AdminPanel(Plugin plugin, NetworkService network) { _plugin = plugin; _network = network; }

        private static string T(string source) => Locale.Translate(source);

        public void RefreshLanguage()
        {
            _catalog.Ensure();
            if (_selectedItem != null) _selectedItem = _catalog.Items.Find(row => row.Id == _selectedItem.Id);
            if (_selectedMob != null) _selectedMob = _catalog.Mobs.Find(row => row.Id == _selectedMob.Id);
            // The next Layout snapshot updates labels without touching drafts, selections, or scroll positions.
        }

        public void Tick()
        {
            if (Visible && ZInput.GetKeyDown(KeyCode.Escape)) { Visible = false; CancelConfirmation(); }
            if (Visible)
            {
                _catalog.Ensure();
                if ((!_wasVisible || Time.unscaledTime >= _nextRefresh) && _network.Connected)
                {
                    _network.Refresh();
                    _nextRefresh = Time.unscaledTime + 3f;
                }
                if (!_wasVisible) RefreshTabData();
            }
            if (!_wasVisible && Visible) CancelConfirmation();
            _wasVisible = Visible;
        }

        public void Draw()
        {
            if (!Visible) return;
            InitializeStyles();
            if (Event.current.type == EventType.Layout) Snapshot();
            float scale = Mathf.Max(0.25f, Mathf.Min(Screen.width / 1280f, Screen.height / 900f));
            if (_lastWidth != Screen.width || _lastHeight != Screen.height)
            {
                _window.x = (Screen.width / scale - _window.width) * 0.5f;
                _window.y = (Screen.height / scale - _window.height) * 0.5f;
                _lastWidth = Screen.width; _lastHeight = Screen.height;
            }
            Matrix4x4 oldMatrix = GUI.matrix;
            Color oldColor = GUI.color;
            bool oldEnabled = GUI.enabled;
            try
            {
                GUI.matrix = Matrix4x4.TRS(Vector3.zero, Quaternion.identity, new Vector3(scale, scale, 1f));
                _window = GUILayout.Window(734811, _window, DrawWindow, T("АДМИНИСТРАТОР  •  VALHEIM"), _box,
                    GUILayout.Width(1120f), GUILayout.Height(820f));
            }
            finally { GUI.matrix = oldMatrix; GUI.color = oldColor; GUI.enabled = oldEnabled; }
        }

        private void Snapshot()
        {
            _displayPlayers.Clear();
            foreach (PlayerRow row in _network.Players)
                _displayPlayers.Add(new PlayerRow { Id = row.Id, Name = row.Name, HasMod = row.HasMod, Alive = row.Alive,
                    God = row.God, Flying = row.Flying, Identity = row.Identity, Role = row.Role, Permissions = row.Permissions, Building = row.Building });
            _displayItems.Clear(); _displayItems.AddRange(_catalog.Items);
            _displayMobs.Clear(); _displayMobs.AddRange(_catalog.Mobs);
            _displayAudit.Clear();
            foreach (AuditRow row in _network.AuditRows)
                _displayAudit.Add(new AuditRow { TimeUtc = row.TimeUtc, Actor = row.Actor, Action = row.Action, Details = row.Details, Result = row.Result });
            _displayBans.Clear();
            foreach (BanRow row in _network.BannedPlayers)
                _displayBans.Add(new BanRow { Identity = row.Identity, Reason = row.Reason });
            _displayPoints.Clear(); _displayPoints.AddRange(TeleportHistory.CurrentWorldPoints());
            _canReturn = TeleportHistory.CanReturn;
        }

        private void InitializeStyles()
        {
            if (_label != null) return;
            _label = new GUIStyle(GUI.skin.label) { fontSize = 16, wordWrap = true, richText = false };
            _small = new GUIStyle(_label) { fontSize = 13 };
            _title = new GUIStyle(_label) { fontSize = 19, fontStyle = FontStyle.Bold };
            _button = new GUIStyle(GUI.skin.button) { fontSize = 14, wordWrap = true, richText = false };
            _button.padding = new RectOffset(8, 8, 6, 6);
            _selectedButton = new GUIStyle(_button);
            _selectedButton.normal.textColor = new Color(1f, 0.82f, 0.36f);
            _tabButton = new GUIStyle(_button) { fontSize = 14 };
            _tabButton.padding = new RectOffset(5, 5, 6, 6);
            _toggle = new GUIStyle(GUI.skin.toggle) { fontSize = 14, wordWrap = true, richText = false };
            _field = new GUIStyle(GUI.skin.textField) { fontSize = 16 };
            _field.padding = new RectOffset(7, 7, 6, 6);
            _box = new GUIStyle(GUI.skin.window) { fontSize = 19, fontStyle = FontStyle.Bold };
            _box.padding = new RectOffset(20, 20, 36, 18);
            _section = new GUIStyle(GUI.skin.box) { padding = new RectOffset(10, 10, 8, 8) };
        }

        private bool Can(AdminPermission permission) { return Player.m_localPlayer && _network.Allowed(permission); }
        private bool Can(AdminAction action) { return Can(RoleRules.Required(action)); }

        private void DrawWindow(int id)
        {
            GUILayout.BeginHorizontal();
            GUILayout.FlexibleSpace();
            if (GUILayout.Button(Locale.Language == "ru" ? "● RU" : "RU", _button, GUILayout.Width(64f), GUILayout.Height(30f)))
            { _plugin.SetLanguage("ru"); GUIUtility.ExitGUI(); }
            if (GUILayout.Button(Locale.Language == "en" ? "● EN" : "EN", _button, GUILayout.Width(64f), GUILayout.Height(30f)))
            { _plugin.SetLanguage("en"); GUIUtility.ExitGUI(); }
            GUILayout.EndHorizontal();
            GUILayout.BeginHorizontal();
            GUILayout.Label(_network.Connected
                ? T("Ваша роль: ") + RoleRules.Name(_network.MyRole) + (_network.Permissions == AdminPermission.None ? T("  •  права не назначены") : T("  •  права подтверждены сервером"))
                : T("Нет соединения с модом на сервере"), _small);
            if (GUILayout.Button(T("Обновить"), _button, GUILayout.Width(110f))) { _network.Refresh(); RefreshTabData(); }
            if (GUILayout.Button(T("Закрыть ×"), _button, GUILayout.Width(125f))) { Visible = false; CancelConfirmation(); }
            GUILayout.EndHorizontal();
            GUILayout.Space(8f);
            int nextTab = GUILayout.Toolbar(_tab, Locale.TranslateArray(_tabs), _tabButton, GUILayout.Height(40f));
            if (nextTab != _tab)
            {
                _tab = nextTab; CancelConfirmation(); RefreshTabData();
                GUI.FocusControl(null); GUIUtility.ExitGUI();
            }
            GUILayout.Space(8f);
            PreviewEnabled = GUILayout.Toggle(PreviewEnabled, T("Показывать область рельефа, ремонта и удара молота"), _toggle, GUILayout.Height(24f));
            GUILayout.Space(6f);
            _tabScroll[_tab] = GUILayout.BeginScrollView(_tabScroll[_tab], GUILayout.Height(434f));
            switch (_tab)
            {
                case 0: DrawPlayers(); break;
                case 1: DrawCatalog(false); break;
                case 2: DrawCatalog(true); break;
                case 3: DrawTerrain(); break;
                case 4: DrawHammer(); break;
                case 5: DrawBuilding(); break;
                case 6: DrawPoints(); break;
                case 7: DrawAudit(); break;
            }
            GUILayout.EndScrollView();
            GUILayout.Space(8f);
            string footer = ConfirmationActive
                ? T("Подтверждение: ") + _confirmationDetails + T(". Нажмите ту же кнопку ещё раз; отмена — сменить параметры или подождать 8 секунд.")
                : (string.IsNullOrEmpty(_plugin.Status) ? T("F8 — открыть или закрыть панель  •  Esc — закрыть") : _plugin.Status);
            GUILayout.Label(footer, _small, GUILayout.Height(64f));
            GUI.DragWindow(new Rect(0f, 0f, 960f, 30f));
        }

        private void RefreshTabData()
        {
            if (_tab == 0 && Can(AdminPermission.Moderate)) _network.RefreshBans();
            if (_tab == 7 && Can(AdminPermission.Audit)) _network.RefreshAudit();
        }

        private void DrawPlayers()
        {
            GUILayout.BeginHorizontal();
            GUILayout.BeginVertical(GUILayout.Width(450f));
            Search(ref _playerSearch, T("Поиск игрока"));
            _playerScroll = GUILayout.BeginScrollView(_playerScroll, GUILayout.Height(420f));
            int found = 0;
            foreach (PlayerRow row in _displayPlayers)
            {
                if (!Matches(row.Name, _playerSearch) && !Matches(row.Identity, _playerSearch) && !Matches(row.Id.ToString(), _playerSearch)) continue;
                found++;
                string caption = row.Name + (row.Id == _network.MyId ? T("  (вы)") : "") + "  •  " + RoleRules.Name(row.Role)
                    + (row.God ? T("  • бессмертие") : "") + (row.Flying ? T("  • полёт") : "") + (row.Building ? T("  • строительство") : "")
                    + (!row.HasMod ? T("  • нет мода") : "") + (!row.Alive ? T("  • персонаж недоступен") : "");
                if (GUILayout.Button(caption, row.Id == _selectedPlayer ? _selectedButton : _button, GUILayout.MinHeight(40f)))
                { _selectedPlayer = row.Id; CancelConfirmation(); GUIUtility.ExitGUI(); }
            }
            if (found == 0) GUILayout.Label(T("Игроки не найдены. Обновите список или измените поиск."), _label);
            GUILayout.EndScrollView();
            GUILayout.EndVertical();
            GUILayout.Space(18f);
            GUILayout.BeginVertical();
            _playerActionsScroll = GUILayout.BeginScrollView(_playerActionsScroll, GUILayout.Height(460f));
            PlayerRow self = _displayPlayers.Find(row => row.Id == _network.MyId);
            GUILayout.Label(T("Ваш персонаж"), _title);
            GUILayout.Label(T("Бессмертие: ") + State(self == null ? (bool?)null : self.God), _small);
            GodButtons(AdminAction.GodSelf, _network.MyId, true);
            GUILayout.Space(8f);
            GUILayout.Label(T("Полёт: ") + (self == null ? T("обновление…") : (self.Flying ? T("включён") : T("выключен"))), _small);
            GUILayout.BeginHorizontal();
            ActionButton(T("Включить полёт"), AdminAction.FlySelf, () => Send(AdminAction.FlySelf, _network.MyId, true));
            ActionButton(T("Выключить полёт"), AdminAction.FlySelf, () => Send(AdminAction.FlySelf, _network.MyId, false));
            GUILayout.EndHorizontal();
            GUILayout.Label(T("W/A/S/D — движение, пробел — вверх, левый Ctrl — вниз, Shift — ускорение."), _small);
            ActionButton(T("Телепорт на точку на карте"), AdminAction.TeleportMap, ArmMapPick);
            ActionButton(T("Вернуться после последнего телепорта"), AdminAction.ReturnTeleport, () => Send(AdminAction.ReturnTeleport), _canReturn);
            GUILayout.Space(14f);
            PlayerRow target = _displayPlayers.Find(row => row.Id == _selectedPlayer);
            GUILayout.Label(target == null ? T("Выберите игрока слева") : T("Игрок: ") + target.Name, _title);
            if (target != null) DrawPlayerActions(target);
            GUILayout.Space(16f);
            DrawBans();
            GUILayout.EndScrollView();
            GUILayout.EndVertical();
            GUILayout.EndHorizontal();
        }

        private void DrawPlayerActions(PlayerRow target)
        {
            bool receives = target.Alive && target.HasMod;
            GUILayout.Label("ID: " + target.Identity + T("  •  Роль: ") + RoleRules.Name(target.Role), _small);
            GUILayout.Label(T("Бессмертие: ") + State(target.God), _small);
            ActionButton(T("Телепортироваться к игроку"), AdminAction.TeleportToPlayer, () => Send(AdminAction.TeleportToPlayer, target.Id), target.Alive);
            ActionButton(T("Телепортировать игрока к себе"), AdminAction.SummonPlayer, () => Send(AdminAction.SummonPlayer, target.Id), receives);
            GodButtons(AdminAction.GodPlayer, target.Id, receives);
            GUILayout.BeginHorizontal();
            ActionButton(T("Вылечить"), AdminAction.HealPlayer, () => Send(AdminAction.HealPlayer, target.Id), receives);
            ActionButton(T("Восстановить выносливость"), AdminAction.RestoreStaminaPlayer, () => Send(AdminAction.RestoreStaminaPlayer, target.Id), receives);
            GUILayout.EndHorizontal();
            ActionButton(T("Снять вредные эффекты"), AdminAction.ClearEffectsPlayer, () => Send(AdminAction.ClearEffectsPlayer, target.Id), receives);
            GUILayout.Label(!target.HasMod ? T("Для призыва, бессмертия и помощи нужен мод у выбранного игрока.")
                : (!target.Alive ? T("Дождитесь загрузки или возрождения персонажа для телепорта и помощи.") : ""), _small, GUILayout.Height(42f));
            GUILayout.Label(T("Управление игроком"), _title);
            GUILayout.Label(T("Причина отключения или блокировки:"), _small);
            Edit(ref _moderationReason, 300);
            bool mayModerate = target.Role != AdminRole.Owner && target.Id != _network.MyId
                && !(_network.MyRole == AdminRole.Moderator && target.Role == AdminRole.Moderator);
            GUILayout.BeginHorizontal();
            ConfirmButton("kick:" + target.Id + ":" + _moderationReason, T("Отключить игрока"), T("отключить ") + target.Name,
                AdminAction.KickPlayer, () => SendModeration(AdminAction.KickPlayer, target.Id), mayModerate);
            ConfirmButton("ban:" + target.Id + ":" + _moderationReason, T("Заблокировать"), T("заблокировать ") + target.Name,
                AdminAction.BanPlayer, () => SendModeration(AdminAction.BanPlayer, target.Id), mayModerate);
            GUILayout.EndHorizontal();
            GUILayout.Label(T("Назначить роль:"), _small);
            GUILayout.BeginHorizontal();
            RoleButton(target, AdminRole.None);
            RoleButton(target, AdminRole.Moderator);
            RoleButton(target, AdminRole.Builder);
            GUILayout.EndHorizontal();
            GUILayout.Label(target.Role == AdminRole.Owner
                ? T("Права владельца из серверного списка администраторов защищены.")
                : T("Модератор: телепорты, помощь, модерация и журнал. Строитель: телепорты, спавн, рельеф, молот, строительство и журнал."), _small);
        }

        private void RoleButton(PlayerRow target, AdminRole role)
        {
            ConfirmButton("role:" + target.Id + ":" + (int)role, RoleRules.Name(role), T("назначить ") + target.Name + T(" роль «") + RoleRules.Name(role) + "»",
                AdminAction.SetRole, () => _network.Send(new AdminCommand { Action = AdminAction.SetRole, Target = target.Id, Role = role }),
                target.Role != AdminRole.Owner && target.Role != role && target.Id != _network.MyId);
        }

        private void DrawBans()
        {
            GUILayout.Label(T("Заблокированные игроки"), _title);
            AllowedButton(T("Обновить список блокировок"), AdminPermission.Moderate, () => _network.RefreshBans());
            GUILayout.Label(T("Снять блокировку по полному ID, в том числе у игрока вне сети:"), _small);
            Edit(ref _unbanIdentity, 128);
            ConfirmButton("unban-manual:" + _unbanIdentity.Trim(), T("Разблокировать по ID"), T("снять блокировку с ") + _unbanIdentity.Trim(),
                AdminAction.UnbanPlayer, () => Unban(_unbanIdentity.Trim()), !string.IsNullOrWhiteSpace(_unbanIdentity));
            foreach (BanRow row in _displayBans)
            {
                GUILayout.BeginVertical(_section);
                GUILayout.Label(row.Identity, _label);
                GUILayout.Label(T("Причина: ") + (string.IsNullOrEmpty(row.Reason) ? T("не указана") : row.Reason), _small);
                ConfirmButton("unban:" + row.Identity, T("Разблокировать"), T("снять блокировку с ") + row.Identity,
                    AdminAction.UnbanPlayer, () => Unban(row.Identity));
                GUILayout.EndVertical();
            }
            if (_displayBans.Count == 0) GUILayout.Label(Can(AdminPermission.Moderate) ? T("Список пуст или ещё не загружен. Нажмите «Обновить».") : T("Для списка блокировок нужны права модерации."), _small);
        }

        private void GodButtons(AdminAction action, long target, bool receives)
        {
            GUILayout.BeginHorizontal();
            ActionButton(T("Включить бессмертие"), action, () => Send(action, target, true), receives);
            ActionButton(T("Выключить"), action, () => Send(action, target, false), receives);
            GUILayout.EndHorizontal();
        }

        private void ArmMapPick()
        {
            if (!Minimap.instance) { _plugin.Notify("Карта пока недоступна."); return; }
            MapPickArmed = true; Visible = false; CancelConfirmation();
            Minimap.instance.SetMapMode(Minimap.MapMode.Large);
            _plugin.Notify("Наведите указатель на точку большой карты и нажмите T. Esc — отмена.");
        }

        private void DrawCatalog(bool mobs)
        {
            List<Catalog.Entry> entries = mobs ? _displayMobs : _displayItems;
            if (mobs) Search(ref _mobSearch, T("Название или ID моба"));
            else Search(ref _itemSearch, T("Название или ID предмета"));
            string search = mobs ? _mobSearch : _itemSearch;
            Catalog.Entry selected = mobs ? _selectedMob : _selectedItem;
            Vector2 scroll = GUILayout.BeginScrollView(mobs ? _mobScroll : _itemScroll, GUILayout.Height(285f));
            int found = 0;
            foreach (Catalog.Entry entry in entries)
            {
                if (!entry.Matches(search)) continue;
                found++;
                if (GUILayout.Button(entry.Name + "   [" + entry.Id + "]", selected != null && selected.Id == entry.Id ? _selectedButton : _button, GUILayout.MinHeight(32f)))
                {
                    if (mobs) _selectedMob = entry; else _selectedItem = entry;
                    CancelConfirmation(); GUIUtility.ExitGUI();
                }
            }
            if (entries.Count == 0) GUILayout.Label(T("Каталог появится после загрузки игрового мира."), _label);
            else if (found == 0) GUILayout.Label(T("Ничего не найдено. Попробуйте название или ID объекта."), _label);
            GUILayout.EndScrollView();
            if (mobs) _mobScroll = scroll; else _itemScroll = scroll;
            GUILayout.Label(T("Найдено: ") + found + " / " + entries.Count + T("  •  Выбрано: ") + (selected == null ? "—" : selected.Name + " [" + selected.Id + "]"), _small);
            GUILayout.BeginHorizontal();
            GUILayout.Label(T("Количество:"), _label, GUILayout.Width(125f));
            if (mobs) _mobCount = GUILayout.TextField(_mobCount, 4, _field, GUILayout.Width(85f));
            else _itemCount = GUILayout.TextField(_itemCount, 4, _field, GUILayout.Width(85f));
            int count;
            bool valid = int.TryParse(mobs ? _mobCount : _itemCount, NumberStyles.None, CultureInfo.InvariantCulture, out count)
                && count >= 1 && count <= (mobs ? 20 : 500);
            GUILayout.Label(mobs ? T("1–20 мобов за раз") : T("1–500 единиц за раз"), _small, GUILayout.Width(200f));
            AdminAction action = mobs ? AdminAction.SpawnMob : AdminAction.SpawnItem;
            ActionButton(mobs ? T("Создать мобов рядом с собой") : T("Создать предметы рядом с собой"), action,
                () => _network.Send(new AdminCommand { Action = action, Prefab = selected.Id, Count = count }), selected != null && valid);
            GUILayout.EndHorizontal();
            GUILayout.Label(valid ? "" : (mobs ? T("Введите целое число от 1 до 20.") : T("Введите целое число от 1 до 500.")), _small, GUILayout.Height(20f));
            ConfirmButton("cleanup-spawn", T("Удалить последнюю созданную порцию"), T("удалить последнюю порцию вашего спавна в этом мире"),
                AdminAction.CleanupSpawn, () => Send(AdminAction.CleanupSpawn));
            GUILayout.Label(T("Удаляются только объекты последней подтверждённой порции, созданной вами через этот мод. Обычные предметы и существа мира не затрагиваются."), _small);
        }

        private void DrawTerrain()
        {
            GUILayout.Label(T("Изменить поверхность вокруг себя"), _title);
            int nextOperation = GUILayout.Toolbar(_terrainOperation, Locale.TranslateArray(_terrainOperations), _button, GUILayout.Height(36f));
            if (nextOperation != _terrainOperation)
            { _terrainOperation = nextOperation; CancelConfirmation(); GUI.FocusControl(null); GUIUtility.ExitGUI(); }
            GUILayout.Space(10f);
            GUILayout.BeginHorizontal();
            GUILayout.BeginVertical(GUILayout.Width(490f));
            float radius = RadiusSlider(T("Радиус круга"), _terrainRadius);
            if (Mathf.Abs(radius - _terrainRadius) > 0.01f) CancelConfirmation();
            _terrainRadius = radius;
            GUILayout.Label(T("Диаметр: ") + Format(_terrainRadius * 2f) + T(" м  •  Площадь: ≈ ") + Mathf.RoundToInt(Mathf.PI * _terrainRadius * _terrainRadius) + T(" м²"), _small, GUILayout.Height(22f));
            GUILayout.EndVertical();
            GUILayout.Space(20f);
            GUILayout.BeginVertical();
            bool enabled = GUI.enabled;
            GUI.enabled = enabled && _terrainOperation != 0;
            GUILayout.Label(T("Изменение высоты: ") + Format(_terrainHeight) + T(" м"), _label);
            float height = Mathf.Round(GUILayout.HorizontalSlider(_terrainHeight, 0.1f, 8f, GUILayout.Height(24f)) * 10f) / 10f;
            GUI.enabled = enabled;
            if (Mathf.Abs(height - _terrainHeight) > 0.01f) CancelConfirmation();
            _terrainHeight = Mathf.Clamp(height, 0.1f, 8f);
            GUILayout.Label(_terrainOperation == 0 ? T("При выравнивании этот параметр не используется.") : T("За одно применение: 0,1–8 м."), _small, GUILayout.Height(22f));
            GUILayout.EndVertical();
            GUILayout.EndHorizontal();
            GUILayout.Space(14f);
            string explanation = _terrainOperation == 0
                ? T("Земля станет ровной на высоте поверхности под вашим персонажем. Изменение сохраняется в мире сервера.")
                : T("Поверхность ") + (_terrainOperation == 1 ? T("поднимется") : T("опустится")) + T(" на ") + Format(_terrainHeight)
                    + T(" м с сохранением существующего рельефа. Игра ограничивает изменение земли примерно ±8 м от исходной высоты: рядом с пределом результат может быть частичным. Изменение сохраняется в мире сервера.");
            GUILayout.Label(explanation, _label, GUILayout.Height(76f));
            string operation = _terrainOperation == 0 ? T("выравнивание") : (_terrainOperation == 1 ? T("подъём") : T("опускание"));
            string details = operation + T(": радиус ") + Format(_terrainRadius) + T(" м") + (_terrainOperation == 0 ? "" : T(", высота ") + Format(_terrainHeight) + T(" м"));
            string key = "terrain:" + _terrainOperation + ":" + _terrainRadius.ToString(CultureInfo.InvariantCulture) + ":" + _terrainHeight.ToString(CultureInfo.InvariantCulture);
            GUILayout.Label(IsConfirming(key) ? T("Подтвердите ") + details + T(". Отмена — изменить параметры или подождать 8 секунд.") : "", _label, GUILayout.Height(48f));
            AdminAction action = _terrainOperation == 0 ? AdminAction.Flatten : (_terrainOperation == 1 ? AdminAction.RaiseTerrain : AdminAction.LowerTerrain);
            ConfirmButton(key, T(_terrainOperations[_terrainOperation]) + T(" поверхность"), details, action,
                () => _network.Send(new AdminCommand { Action = action, Radius = _terrainRadius, Height = _terrainHeight }));
            GUILayout.Space(12f);
            ConfirmButton("undo-terrain", T("Отменить последнее изменение рельефа"), T("отменить ваше последнее изменение рельефа"),
                AdminAction.UndoTerrain, () => Send(AdminAction.UndoTerrain));
            GUILayout.Label(T("Отменяется последнее изменение в текущем подключении. Подойдите к изменённой области: клиент восстанавливает только точки без более поздних правок, сохраняя остальные изменения. Невосстановленную часть можно отменить повторно."), _small);
        }

        private void DrawHammer()
        {
            GUILayout.Label(T("Супер молот"), _title);
            HammerRadius = RadiusSlider(T("Радиус удара"), HammerRadius);
            GUILayout.Label(T("Какие цели получают 999 999 единиц урона:"), _label);
            TargetFlags previous = HammerTargets;
            GUILayout.BeginHorizontal();
            TargetToggle(T("Мобы"), TargetFlags.Mobs);
            TargetToggle(T("Деревья"), TargetFlags.Trees);
            GUILayout.EndHorizontal();
            GUILayout.BeginHorizontal();
            TargetToggle(T("Руда"), TargetFlags.Ore);
            TargetToggle(T("Постройки"), TargetFlags.Structures);
            GUILayout.EndHorizontal();
            if (previous != HammerTargets && HammerTargets == TargetFlags.None && _plugin.HammerEnabled && Can(AdminAction.HammerToggle))
                _network.Send(new AdminCommand { Action = AdminAction.HammerToggle, Enabled = false, Radius = HammerRadius, HammerTargets = HammerTargets });
            GUILayout.Label(HammerTargets == TargetFlags.None ? T("Выберите хотя бы одну группу целей: включение и удар без целей недоступны.") : T("Удар действует только на отмеченные группы целей."), _small, GUILayout.Height(36f));
            ActionButton(T("Получить супермолот администратора"), AdminAction.SpawnItem,
                () => _network.Send(new AdminCommand { Action = AdminAction.SpawnItem, Prefab = "AdminRu_SuperHammer", Count = 1 }));
            bool enabled = GUI.enabled;
            GUI.enabled = enabled && Can(AdminAction.HammerToggle) && (HammerTargets != TargetFlags.None || _plugin.HammerEnabled);
            bool desired = GUILayout.Toggle(_plugin.HammerEnabled, T("Включить супер молот"), _toggle, GUILayout.Height(38f));
            GUI.enabled = enabled;
            if (desired != _plugin.HammerEnabled && (!desired || HammerTargets != TargetFlags.None))
                _network.Send(new AdminCommand { Action = AdminAction.HammerToggle, Enabled = desired, Radius = HammerRadius, HammerTargets = HammerTargets });
            GUILayout.Label(T("Возьмите супермолот в руки, закройте панель и ударьте оружием или нажмите F6. Радиус и группы целей задаются здесь."), _label);
            GUILayout.Label(T("Если отмечены постройки, они также получают урон. Предпросмотр сферы помогает выбрать область удара."), _small);
            GUILayout.Label(T("Оружие также доступно на вкладке «Предметы»: поиск «Супермолот» или AdminRu_SuperHammer."), _small);
        }

        private void TargetToggle(string text, TargetFlags flag)
        {
            bool selected = (HammerTargets & flag) != 0;
            bool desired = GUILayout.Toggle(selected, text, _toggle, GUILayout.Height(32f));
            if (desired != selected) HammerTargets = desired ? HammerTargets | flag : HammerTargets & ~flag;
        }

        private void DrawBuilding()
        {
            GUILayout.Label(T("Строительство и ремонт"), _title);
            GUILayout.Label(T("Режим строителя: ") + (BuildMode.Enabled ? T("включён") : T("выключен")), _label);
            GUILayout.BeginHorizontal();
            ActionButton(T("Включить режим строителя"), AdminAction.BuildToggle, () => Send(AdminAction.BuildToggle, _network.MyId, true));
            ActionButton(T("Выключить режим строителя"), AdminAction.BuildToggle, () => Send(AdminAction.BuildToggle, _network.MyId, false));
            GUILayout.EndHorizontal();
            GUILayout.Label(T("Строительство без расхода ресурсов. Молот, мотыга и культиватор не изнашиваются при использовании режима."), _label);
            GUILayout.Space(18f);
            RepairRadius = RadiusSlider(T("Радиус ремонта вокруг себя"), RepairRadius);
            ActionButton(T("Починить постройки в области"), AdminAction.RepairArea,
                () => _network.Send(new AdminCommand { Action = AdminAction.RepairArea, Radius = RepairRadius }));
            GUILayout.Label(T("Ремонт восстанавливает доступные постройки в выбранном радиусе, включая объекты выше и ниже персонажа. Предпросмотр показывает сферическую область ремонта."), _small);
        }

        private void DrawPoints()
        {
            GUILayout.Label(T("Сохранённые точки этого мира"), _title);
            GUILayout.Label(T("Точки хранятся на вашем компьютере отдельно для каждого мира. При телепорте сохраняется точная высота, в том числе в подземелье."), _small);
            GUILayout.BeginHorizontal();
            GUILayout.Label(T("Название:"), _label, GUILayout.Width(100f));
            _pointName = GUILayout.TextField(_pointName, 80, _field);
            AllowedButton(T("Сохранить моё положение"), AdminPermission.Travel,
                () => LocalOperation(() => TeleportHistory.SaveCurrent(_pointName.Trim())), !string.IsNullOrWhiteSpace(_pointName));
            GUILayout.EndHorizontal();
            ActionButton(T("Вернуться после последнего телепорта"), AdminAction.ReturnTeleport, () => Send(AdminAction.ReturnTeleport), _canReturn);
            Search(ref _pointSearch, T("Поиск точки"));
            int found = 0;
            foreach (SavedPoint point in _displayPoints)
            {
                if (!Matches(point.Name, _pointSearch)) continue;
                found++;
                GUILayout.BeginVertical(_section);
                GUILayout.Label(point.Name, _title);
                GUILayout.Label("X: " + Format(point.Position.x) + "  Y: " + Format(point.Position.y) + "  Z: " + Format(point.Position.z), _small);
                GUILayout.BeginHorizontal();
                ActionButton(T("Телепортироваться"), AdminAction.TeleportSaved,
                    () => _network.Send(new AdminCommand { Action = AdminAction.TeleportSaved, Position = point.Position, Text = ShortText(point.Name, 300) }));
                ConfirmButton("delete-point:" + point.Id, T("Удалить точку"), T("удалить точку «") + point.Name + "»",
                    AdminPermission.Travel, () => LocalOperation(() => TeleportHistory.Remove(point.Id)));
                GUILayout.EndHorizontal();
                GUILayout.EndVertical();
            }
            if (found == 0) GUILayout.Label(_displayPoints.Count == 0 ? T("В этом мире пока нет сохранённых точек.") : T("Точки не найдены. Измените поиск."), _label);
        }

        private void DrawAudit()
        {
            GUILayout.BeginHorizontal();
            GUILayout.Label(T("Журнал действий сервера"), _title);
            AllowedButton(T("Обновить журнал"), AdminPermission.Audit, () => _network.RefreshAudit());
            GUILayout.EndHorizontal();
            Search(ref _actorSearch, T("Игрок / администратор"));
            Search(ref _actionSearch, T("Действие"));
            GUILayout.Label(T("Время указано в UTC. Журнал показывает команду, параметры и результат её выполнения."), _small);
            int found = 0;
            foreach (AuditRow row in _displayAudit)
            {
                if (!Matches(row.Actor, _actorSearch) || !Matches(T(row.Action), _actionSearch)) continue;
                found++;
                GUILayout.BeginVertical(_section);
                GUILayout.Label(AuditTime(row.TimeUtc) + "  •  " + row.Actor + "  •  " + T(row.Action), _label);
                GUILayout.Label(T("Параметры: ") + T(row.Details), _small);
                GUILayout.Label(T("Результат: ") + T(row.Result), _small);
                GUILayout.EndVertical();
            }
            GUILayout.Label(T("Показано записей: ") + found, _small);
            if (found == 0) GUILayout.Label(Can(AdminPermission.Audit) ? T("Записи не найдены. Обновите журнал или измените поиск.") : T("Для просмотра журнала нужны права аудита."), _label);
        }

        private void ActionButton(string caption, AdminAction action, Action execute, bool extra = true)
        { AllowedButton(caption, RoleRules.Required(action), execute, extra); }

        private void AllowedButton(string caption, AdminPermission permission, Action execute, bool extra = true)
        {
            bool enabled = GUI.enabled;
            GUI.enabled = enabled && Can(permission) && extra;
            bool clicked = GUILayout.Button(caption, _button, GUILayout.MinHeight(38f));
            GUI.enabled = enabled;
            if (clicked) execute();
        }

        private void ConfirmButton(string key, string caption, string details, AdminAction action, Action execute, bool extra = true)
        { ConfirmButton(key, caption, details, RoleRules.Required(action), execute, extra); }

        private void ConfirmButton(string key, string caption, string details, AdminPermission permission, Action execute, bool extra = true)
        {
            // Details are rebuilt in the current language each frame, including an already open confirmation.
            if (IsConfirming(key)) _confirmationDetails = details;
            AllowedButton(IsConfirming(key) ? T("Подтвердить: ") + caption : caption, permission, () =>
            {
                if (IsConfirming(key)) { CancelConfirmation(); execute(); }
                else { _confirmationKey = key; _confirmationDetails = details; _confirmationUntil = Time.unscaledTime + 8f; }
            }, extra);
        }

        private bool ConfirmationActive { get { return _confirmationKey.Length > 0 && Time.unscaledTime < _confirmationUntil; } }
        private bool IsConfirming(string key) { return ConfirmationActive && _confirmationKey == key; }
        private void CancelConfirmation() { _confirmationKey = ""; _confirmationDetails = ""; _confirmationUntil = 0f; }

        private void Send(AdminAction action, long target = 0, bool enabled = false)
        { _network.Send(new AdminCommand { Action = action, Target = target, Enabled = enabled }); }

        private void SendModeration(AdminAction action, long target)
        { _network.Send(new AdminCommand { Action = action, Target = target, Text = _moderationReason.Trim() }); }

        private void Unban(string identity)
        {
            _network.Send(new AdminCommand { Action = AdminAction.UnbanPlayer, Identity = identity });
            _network.RefreshBans();
        }

        private void LocalOperation(Func<string> operation)
        {
            try { _plugin.Notify(operation()); }
            catch (Exception error) { _plugin.Notify("Не удалось изменить сохранённые точки: " + error.Message); }
            GUI.FocusControl(null);
            GUIUtility.ExitGUI();
        }

        private float RadiusSlider(string label, float radius)
        {
            GUILayout.Label(label + ": " + Format(radius) + T(" м"), _label);
            return Mathf.Round(GUILayout.HorizontalSlider(radius, 1f, 40f, GUILayout.Height(24f)) * 2f) / 2f;
        }

        private void Edit(ref string value, int maximum)
        {
            string previous = value;
            value = GUILayout.TextField(value, maximum, _field, GUILayout.Height(34f));
            if (value != previous) CancelConfirmation();
        }

        private void Search(ref string search, string hint)
        {
            string previous = search;
            GUILayout.BeginHorizontal();
            GUILayout.Label(hint + ":", _small, GUILayout.Width(195f));
            search = GUILayout.TextField(search, 100, _field, GUILayout.Height(34f));
            if (GUILayout.Button("×", _button, GUILayout.Width(36f), GUILayout.Height(34f))) { search = ""; GUI.FocusControl(null); }
            GUILayout.EndHorizontal();
            if (search != previous) { CancelConfirmation(); GUIUtility.ExitGUI(); }
        }

        private static bool Matches(string value, string search)
        { return string.IsNullOrWhiteSpace(search) || (value ?? "").IndexOf(search.Trim(), StringComparison.OrdinalIgnoreCase) >= 0; }
        private static string State(bool? state) { return state.HasValue ? (state.Value ? T("включено") : T("выключено")) : T("обновление…"); }
        private static string Format(float value) { return value.ToString("0.#", Locale.Culture); }
        private static string ShortText(string value, int length) { value = value ?? ""; return value.Length <= length ? value : value.Substring(0, length); }
        private static string AuditTime(string value)
        {
            DateTime time;
            return DateTime.TryParse(value, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out time)
                ? time.ToUniversalTime().ToString((Locale.Language == "en" ? "yyyy-MM-dd HH:mm:ss" : "dd.MM.yyyy HH:mm:ss"), CultureInfo.InvariantCulture) + " UTC" : value;
        }
    }
}
