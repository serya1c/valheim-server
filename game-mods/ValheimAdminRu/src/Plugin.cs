using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;

namespace ValheimAdminRu
{
    [BepInPlugin("ru.valheim.adminpanel", "Админ-панель Valheim", ModVersion)]
    public sealed class Plugin : BaseUnityPlugin
    {
        public const string ModVersion = "0.4.0";
        public const string GameVersion = "1.0.17";
        public static bool SupportsGameVersion(string version) => version == "1.0.16" || version == GameVersion;
        public static Plugin Instance;
        public ManualLogSource Log => Logger;
        private string statusSource = "Подключение к серверной части мода…";
        public string Status { get => Locale.Translate(statusSource); set => statusSource = value ?? ""; }
        public bool HammerEnabled;
        public NetworkService Network;
        public AdminPanel Panel;
        private Harmony harmony;
        private ConfigEntry<KeyCode> panelKey, hammerKey;
        private ConfigEntry<bool> hideCheatedItemNote;
        private ConfigEntry<string> interfaceLanguage;
        internal bool HideCheatedItemNote => hideCheatedItemNote != null && hideCheatedItemNote.Value;
        private float nextStrike;
        private RadiusPreview preview;
        private static readonly System.Reflection.MethodInfo MapPoint = AccessTools.Method(typeof(Minimap), "ScreenToWorldPoint", new[] { typeof(Vector3) });

        private void Awake()
        {
            Instance = this;
            panelKey = Config.Bind("Управление", "КлавишаПанели", KeyCode.F8, "Открыть русскую админ-панель.");
            hammerKey = Config.Bind("Управление", "КлавишаУдара", KeyCode.F6, "Дополнительная клавиша удара супермолотом. Нужно держать супермолот.");
            hideCheatedItemNote = Config.Bind("Интерфейс", "СкрыватьНадписьОЧитах", true,
                "Убирать подпись о получении предмета с помощью читов из его описания. Метка предмета и учёт достижений сохраняются.");
            interfaceLanguage = Config.Bind("Интерфейс", "Язык", "ru",
                new ConfigDescription("Язык меню F8 и сообщений: ru / en. F8 menu and message language: ru / en.",
                    new AcceptableValueList<string>("ru", "en")));
            if (!Locale.SetLanguage(interfaceLanguage.Value)) Locale.SetLanguage("ru");
            Network = new NetworkService(this);
            Panel = new AdminPanel(this, Network);
            preview = new RadiusPreview();
            harmony = new Harmony("ru.valheim.adminpanel");
            harmony.PatchAll(typeof(Plugin).Assembly);
            Logger.LogInfo("Админ-панель " + ModVersion + "; Valheim 1.0.16 и 1.0.17; сборка по библиотекам " + GameVersion + ".");
            if (!SupportsGameVersion(global::Version.CurrentVersion.ToString()))
                Logger.LogWarning("Версия игры отличается от проверенной: " + global::Version.CurrentVersion + ".");
        }

        private void Update()
        {
            if (interfaceLanguage.Value != Locale.Language)
            {
                if (Locale.SetLanguage(interfaceLanguage.Value))
                { Panel.RefreshLanguage(); HammerItem.RefreshLanguage(); }
            }
            Network.Tick();
            WorldActions.Tick();
            if (!Player.m_localPlayer) { Panel.Visible = false; Panel.MapPickArmed = false; preview.Hide(); return; }
            if (ZInput.GetKeyDown(panelKey.Value))
            {
                Panel.MapPickArmed = false;
                Panel.Visible = !Panel.Visible;
                if (Panel.Visible) Network.Refresh();
            }
            Panel.Tick();
            if (Panel.PreviewEnabled && Network.AdminAllowed && !Player.m_localPlayer.IsDead() && Panel.PreviewRadius >= 1f)
                preview.Update(Player.m_localPlayer.transform.position, Panel.PreviewRadius, Panel.PreviewTerrain);
            else preview.Hide();
            if (Panel.Visible) { ZCursor.LockState = CursorLockMode.None; ZCursor.Show(); }
            HandleMapPick();
            if (!Panel.Visible && !Minimap.IsOpen() && !Menu.IsVisible() && !InventoryGui.IsVisible()
                && (!Chat.instance || !Chat.instance.HasFocus()) && !global::Console.IsVisible()
                && ZInput.GetKeyDown(hammerKey.Value)) Strike();
        }

        private void OnGUI() { if (Panel != null && Player.m_localPlayer) Panel.Draw(); }
        public void Notify(string message)
        {
            Status = message;
            if (Player.m_localPlayer) Player.m_localPlayer.Message(MessageHud.MessageType.TopLeft, Status);
            Logger.LogInfo(message);
        }

        internal void SetLanguage(string value)
        {
            if (!Locale.SetLanguage(value)) return;
            try { interfaceLanguage.Value = Locale.Language; Config.Save(); }
            catch (System.Exception error) { Notify("Не удалось сохранить язык интерфейса: " + error.GetType().Name); }
            Panel.RefreshLanguage();
            HammerItem.RefreshLanguage();
            // Redisplay the last source message; changing language never resends a game command.
            if (Player.m_localPlayer && !string.IsNullOrEmpty(Status))
                Player.m_localPlayer.Message(MessageHud.MessageType.TopLeft, Status);
        }

        public void Strike()
        {
            if (!HammerEnabled || !Network.Allowed(AdminPermission.Hammer) || !Player.m_localPlayer || Time.unscaledTime < nextStrike) return;
            if (!HammerItem.IsSuperHammer(Player.m_localPlayer.GetCurrentWeapon()))
            { Notify("Возьмите в руки «Супермолот администратора»."); return; }
            nextStrike = Time.unscaledTime + 1f;
            if (Panel.HammerTargets == HammerTargets.None) { Notify("Выберите хотя бы одну категорию целей супермолота."); return; }
            Network.Send(new AdminCommand { Action = AdminAction.HammerStrike, Radius = Panel.HammerRadius, HammerTargets = Panel.HammerTargets });
        }

        private void HandleMapPick()
        {
            if (!Panel.MapPickArmed) return;
            if (ZInput.GetKeyDown(KeyCode.Escape) || !Minimap.IsOpen())
            { Panel.MapPickArmed = false; Notify("Выбор точки отменён."); return; }
            if (!Network.Allowed(AdminPermission.Travel) || MapPoint == null) { Panel.MapPickArmed = false; return; }
            if (!ZInput.GetKeyDown(KeyCode.T)) return;
            var map = Minimap.instance;
            Vector3 cursor = ZInput.pointerPosition;
            if (!RectTransformUtility.RectangleContainsScreenPoint(map.m_mapImageLarge.rectTransform, cursor, null)) return;
            Vector3 point = (Vector3)MapPoint.Invoke(map, new object[] { cursor });
            Network.Send(new AdminCommand { Action = AdminAction.TeleportMap, Position = point });
            Panel.MapPickArmed = false;
            map.SetMapMode(Minimap.MapMode.Small);
        }

        private void OnDestroy()
        {
            Network?.Reset();
            WorldActions.Reset();
            harmony?.UnpatchSelf();
            HammerItem.Cleanup();
            preview?.Dispose();
            if (Instance == this) Instance = null;
        }
        public static bool PanelOpen => Instance != null && Instance.Panel != null && Instance.Panel.Visible && Player.m_localPlayer;
    }

    [HarmonyPatch(typeof(Player), "TakeInput")]
    internal static class PanelInputPatch
    {
        private static bool Prefix(Player __instance, ref bool __result)
        {
            if (Plugin.PanelOpen && __instance == Player.m_localPlayer) { __result = false; return false; }
            return true;
        }
    }
    [HarmonyPatch(typeof(PlayerController), "TakeInput")]
    internal static class PanelMovementInputPatch
    {
        private static bool Prefix(Player ___m_character, ref bool __result)
        {
            if (Plugin.PanelOpen && ___m_character == Player.m_localPlayer) { __result = false; return false; }
            return true;
        }
    }
    [HarmonyPatch(typeof(GameCamera), "UpdateMouseCapture")]
    internal static class PanelCursorPatch
    {
        private static void Postfix() { if (Plugin.PanelOpen) { ZCursor.LockState = CursorLockMode.None; ZCursor.Show(); } }
    }
    [HarmonyPatch(typeof(GameCamera), "UpdateCamera")]
    internal static class PanelCameraPatch
    {
        private static bool Prefix() => !Plugin.PanelOpen;
    }
    [HarmonyPatch(typeof(Attack), "OnAttackTrigger")]
    internal static class SuperHammerAttackPatch
    {
        private static bool Prefix(Humanoid ___m_character, ItemDrop.ItemData ___m_weapon)
        {
            var plugin = Plugin.Instance;
            if (plugin == null || !plugin.HammerEnabled || ___m_character != Player.m_localPlayer || !HammerItem.IsSuperHammer(___m_weapon)) return true;
            plugin.Strike();
            return false;
        }
    }
    [HarmonyPatch(typeof(Character), "ApplyDamage")]
    internal static class GodHealthPatch
    {
        private static bool Prefix(Character __instance)
        { return !(__instance == Player.m_localPlayer && WorldActions.GodEnabled); }
    }
    [HarmonyPatch(typeof(Character), "RPC_Damage")]
    internal static class GodIncomingHitPatch
    {
        private static bool Prefix(Character __instance)
        { return !(__instance == Player.m_localPlayer && WorldActions.GodEnabled); }
    }
}
