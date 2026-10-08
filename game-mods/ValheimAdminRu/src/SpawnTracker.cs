using System;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;
using UnityEngine;

namespace ValheimAdminRu
{
    public static class SpawnTracker
    {
        public const string IdentityKey = "ValheimAdminRu.SpawnIdentity";
        public const string BatchKey = "ValheimAdminRu.SpawnBatch";
        private const string WorldKey = "ValheimAdminRu.SpawnWorld";
        private const string StackKey = "ValheimAdminRu.SpawnStack";
        private static readonly FieldInfo AllObjects = AccessTools.Field(typeof(ZDOMan), "m_objectsByID");

        internal static void RequireBatch(AdminCommand command)
        {
            if (command == null || !ZNet.instance) throw new InvalidOperationException("Мир ещё не готов к спавну.");
            Validate(command.Identity, command.BatchId);
        }

        public static void Tag(GameObject gameObject, AdminCommand command)
        {
            RequireBatch(command);
            ZNetView view = gameObject ? gameObject.GetComponent<ZNetView>() : null;
            if (!view || !view.IsValid() || !view.IsOwner())
                throw new InvalidOperationException("Созданный объект не готов к учёту административного спавна.");
            ZDO zdo = view.GetZDO();
            zdo.Set(IdentityKey, command.Identity);
            zdo.Set(BatchKey, command.BatchId);
            zdo.Set(WorldKey, ZNet.instance.GetWorldUID());
            ItemDrop item = gameObject.GetComponent<ItemDrop>();
            if (item && item.m_itemData != null) zdo.Set(StackKey, item.m_itemData.m_stack);
        }

        public static string CleanupBatch(string identity, string batchId)
        {
            Validate(identity, batchId);
            if (!ZNet.instance || !ZNet.instance.IsServer() || ZDOMan.instance == null || !ZNetScene.instance || AllObjects == null)
                throw new InvalidOperationException("Очистка административного спавна выполняется сервером.");
            var objects = AllObjects.GetValue(ZDOMan.instance) as Dictionary<ZDOID, ZDO>;
            if (objects == null) throw new InvalidOperationException("Не удалось прочитать объекты мира.");
            long world = ZNet.instance.GetWorldUID();
            List<ZDO> matching = new List<ZDO>();
            int mixedStacks = 0;
            foreach (ZDO zdo in objects.Values)
            {
                if (zdo == null || !Matches(zdo, identity, batchId, world)) continue;
                GameObject prefab = ZNetScene.instance.GetPrefab(zdo.GetPrefab());
                if (!Eligible(prefab)) continue;
                if (!UnmixedItem(zdo, prefab)) { mixedStacks++; continue; }
                ZNetView instance = ZNetScene.instance.FindInstance(zdo);
                if (instance && !Eligible(instance.gameObject)) continue;
                matching.Add(zdo);
            }
            int removed = 0;
            foreach (ZDO zdo in matching)
            {
                // Recheck before ownership changes. Pickup destroys the ground ItemDrop
                // ZDO; inventory ItemData neither keeps these markers nor gets scanned.
                ZDO current = ZDOMan.instance.GetZDO(zdo.m_uid);
                if (!ReferenceEquals(current, zdo) || !Matches(zdo, identity, batchId, world)) continue;
                zdo.SetOwner(ZDOMan.GetSessionID());
                if (!zdo.IsOwner()) continue;
                ZDOMan.instance.DestroyZDO(zdo);
                removed++;
            }
            string message = removed == 0 ? "Объекты последнего спавна уже подобраны, удалены или покинули мир."
                : "На удаление отправлено объектов последнего спавна: " + removed + ".";
            if (mixedStacks > 0) message += " Сохранены изменённые стопки, которые могли смешаться с обычными предметами: " + mixedStacks + ".";
            return message;
        }

        private static bool UnmixedItem(ZDO zdo, GameObject prefab)
        {
            if (!prefab.GetComponent<ItemDrop>()) return true;
            int original = zdo.GetInt(StackKey, -1);
            byte[] saved = zdo.GetByteArray(ZDOVars.s_itemData);
            if (original < 1 || saved == null || saved.Length <= 2) return false;
            try
            {
                ItemDrop.ItemData item = new ItemDrop.ItemData();
                ItemDrop.LoadFromZDO(item, zdo);
                // A vanilla client does not run our anti-merge patch. Preserve a
                // changed stack conservatively instead of risking ordinary loot.
                return item.m_stack == original && !item.m_pickedUp && !item.m_equipped;
            }
            catch (Exception) { return false; }
        }

        private static bool Eligible(GameObject gameObject)
        {
            if (!gameObject || gameObject.GetComponent<Player>()) return false;
            if (gameObject.GetComponent<ItemDrop>()) return true;
            Character character = gameObject.GetComponent<Character>();
            return character && !character.IsPlayer() && gameObject.GetComponent<BaseAI>();
        }

        private static bool Matches(ZDO zdo, string identity, string batchId, long world)
        {
            return string.Equals(zdo.GetString(IdentityKey), identity, StringComparison.Ordinal)
                && string.Equals(zdo.GetString(BatchKey), batchId, StringComparison.Ordinal)
                && zdo.GetLong(WorldKey, long.MinValue) == world;
        }

        private static void Validate(string identity, string batchId)
        {
            if (string.IsNullOrEmpty(identity) || identity.Length > 128 || string.IsNullOrEmpty(batchId) || batchId.Length > 64)
                throw new InvalidOperationException("Нет подтверждённой сервером порции спавна для очистки.");
        }

        internal static bool IsTracked(ItemDrop item)
        {
            ZNetView view = item ? item.GetComponent<ZNetView>() : null;
            return view && view.IsValid() && !string.IsNullOrEmpty(view.GetZDO().GetString(IdentityKey))
                && !string.IsNullOrEmpty(view.GetZDO().GetString(BatchKey));
        }
    }

    [HarmonyPatch(typeof(ItemDrop), "AutoStackItems")]
    internal static class TrackedSpawnStackPatch
    {
        private static bool Prefix(ItemDrop __instance, ref bool ___m_haveAutoStacked)
        {
            // Match the native early exits before doing any neighborhood lookup.
            ItemDrop.ItemData data = __instance.m_itemData;
            if (data == null || data.m_shared == null || data.m_shared.m_maxStackSize <= 1
                || data.m_stack >= data.m_shared.m_maxStackSize || ___m_haveAutoStacked) return true;
            if (SpawnTracker.IsTracked(__instance))
            { ___m_haveAutoStacked = true; return false; }
            // Keep tracked and ordinary drops from merging: otherwise clearing a
            // marked stack could also delete ordinary resources absorbed into it.
            foreach (Collider collider in Physics.OverlapSphere(__instance.transform.position, 4f, LayerMask.GetMask("item")))
            {
                ItemDrop neighbor = collider && collider.attachedRigidbody
                    ? collider.attachedRigidbody.GetComponent<ItemDrop>() : null;
                if (SpawnTracker.IsTracked(neighbor))
                { ___m_haveAutoStacked = true; return false; }
            }
            return true;
        }
    }
}
