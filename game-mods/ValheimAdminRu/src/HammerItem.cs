using System.Collections.Generic;
using System.Linq;
using HarmonyLib;
using UnityEngine;

namespace ValheimAdminRu
{
    public static class HammerItem
    {
        public const string PrefabName = "AdminRu_SuperHammer";
        private static GameObject container, prefab;

        public static bool IsSuperHammer(ItemDrop.ItemData item)
        { return item != null && item.m_dropPrefab != null && item.m_dropPrefab.name == PrefabName; }

        public static void Register(ObjectDB db, ZNetScene scene)
        {
            if (!prefab)
            {
                GameObject source = db ? db.m_items.FirstOrDefault(p => p && p.name == "SledgeIron") : null;
                if (!source && scene) source = scene.m_prefabs.FirstOrDefault(p => p && p.name == "SledgeIron");
                if (!source) return;
                container = new GameObject("AdminRu_Prefabs");
                container.SetActive(false);
                Object.DontDestroyOnLoad(container);
                prefab = Object.Instantiate(source, container.transform);
                prefab.name = PrefabName;
                prefab.SetActive(true);
                var item = prefab.GetComponent<ItemDrop>();
                item.m_itemData.m_dropPrefab = prefab;
                SetLanguage(item.m_itemData);
                item.m_itemData.m_shared.m_maxQuality = 1;
                item.m_itemData.m_shared.m_useDurability = false;
                item.m_itemData.m_shared.m_attack.m_attackStamina = 0f;
                item.m_itemData.m_shared.m_secondaryAttack.m_attackStamina = 0f;
            }
            if (db && !db.m_items.Any(p => p && p.name == PrefabName))
            {
                db.m_items.Add(prefab);
                AccessTools.Method(typeof(ObjectDB), "UpdateRegisters").Invoke(db, null);
            }
            if (scene && !scene.GetPrefab(PrefabName))
            {
                scene.m_prefabs.Add(prefab);
                var named = (Dictionary<int, GameObject>)AccessTools.Field(typeof(ZNetScene), "m_namedPrefabs").GetValue(scene);
                named.Add(PrefabName.GetStableHashCode(), prefab);
            }
        }
        private static void SetLanguage(ItemDrop.ItemData item)
        {
            if (item?.m_shared == null) return;
            item.m_shared.m_name = Locale.Translate("Супермолот администратора");
            item.m_shared.m_description = Locale.Translate("При включённом режиме наносит 999999 урона по площади. Радиус задаётся в админ-панели.");
        }
        public static void RefreshLanguage()
        {
            if (prefab) SetLanguage(prefab.GetComponent<ItemDrop>()?.m_itemData);
            if (Player.m_localPlayer)
                foreach (ItemDrop.ItemData item in Player.m_localPlayer.GetInventory().GetAllItems())
                    if (IsSuperHammer(item)) SetLanguage(item);
        }
        public static void Cleanup()
        {
            if (container) Object.Destroy(container);
            container = null; prefab = null;
        }
    }

    [HarmonyPatch(typeof(ObjectDB), "Awake")]
    internal static class HammerObjectDbPatch
    { private static void Postfix(ObjectDB __instance) { HammerItem.Register(__instance, ZNetScene.instance); } }
    [HarmonyPatch(typeof(ObjectDB), "CopyOtherDB")]
    internal static class HammerCopyDbPatch
    { private static void Postfix(ObjectDB __instance) { HammerItem.Register(__instance, ZNetScene.instance); } }
    [HarmonyPatch(typeof(ZNetScene), "Awake")]
    internal static class HammerNetScenePatch
    { private static void Postfix(ZNetScene __instance) { HammerItem.Register(ObjectDB.instance, __instance); } }
}
