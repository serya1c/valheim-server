using System;
using System.Reflection;
using HarmonyLib;
using UnityEngine;

namespace ValheimAdminRu
{
    internal static class BuildMode
    {
        private static readonly FieldInfo NoPlacementCost = AccessTools.Field(typeof(Player), "m_noPlacementCost");
        private static readonly MethodInfo RefreshPieces = AccessTools.Method(typeof(Player), "UpdateAvailablePiecesList", Type.EmptyTypes);
        private static Player appliedPlayer;
        private static bool previousNoPlacementCost;
        [ThreadStatic] private static Player placementPlayer;
        [ThreadStatic] private static int placementDepth;

        public static bool Enabled { get; private set; }

        public static string Set(bool enabled)
        {
            if (!enabled)
            {
                Reset();
                return "Режим строителя выключен.";
            }
            var player = Player.m_localPlayer;
            if (!Authorized() || !player || player.IsDead())
                throw new InvalidOperationException("Режим строителя доступен только администратору с готовым персонажем.");
            var view = player.GetComponent<ZNetView>();
            if (NoPlacementCost == null || RefreshPieces == null || !view || !view.IsValid() || !view.IsOwner())
                throw new InvalidOperationException("Не удалось включить режим строителя: персонаж ещё не синхронизирован.");
            Attach(player);
            Enabled = true;
            return "Режим строителя включён: строительство без ресурсов, молот, мотыга и культиватор не изнашиваются.";
        }

        public static void Tick()
        {
            if (!Enabled) return;
            if (!Authorized()) { Reset(); return; }
            var player = Player.m_localPlayer;
            if (!ReferenceEquals(appliedPlayer, player)) RestorePlayer();
            if (!player || player.IsDead()) return;
            var view = player.GetComponent<ZNetView>();
            if (!view || !view.IsValid() || !view.IsOwner()) return;
            Attach(player);
        }

        public static void Reset()
        {
            // Disable patches before restoring the native flag, including on disconnect.
            Enabled = false;
            RestorePlayer();
            placementPlayer = null;
            placementDepth = 0;
        }

        internal static bool AppliesTo(Player player)
        {
            return Enabled && Authorized() && player && player == Player.m_localPlayer
                && ReferenceEquals(player, appliedPlayer);
        }

        internal static bool IsBuildingTool(ItemDrop.ItemData tool)
        {
            return tool != null && tool.m_shared != null && tool.m_shared.m_buildPieces;
        }

        private static bool Authorized()
        {
            return Plugin.Instance != null && Plugin.Instance.Network != null && Plugin.Instance.Network.EffectAllowed(AdminPermission.Build);
        }

        private static void Attach(Player player)
        {
            if (!ReferenceEquals(appliedPlayer, player))
            {
                RestorePlayer();
                previousNoPlacementCost = (bool)NoPlacementCost.GetValue(player);
                appliedPlayer = player;
            }
            if ((bool)NoPlacementCost.GetValue(player)) return;
            NoPlacementCost.SetValue(player, true);
            try { RefreshPieces.Invoke(player, null); }
            catch
            {
                NoPlacementCost.SetValue(player, previousNoPlacementCost);
                appliedPlayer = null;
                Enabled = false;
                throw;
            }
        }

        private static void RestorePlayer()
        {
            var player = appliedPlayer;
            appliedPlayer = null;
            if (ReferenceEquals(player, null) || NoPlacementCost == null) return;
            bool changed = (bool)NoPlacementCost.GetValue(player) != previousNoPlacementCost;
            NoPlacementCost.SetValue(player, previousNoPlacementCost);
            if (!changed || !player || RefreshPieces == null || !ZNetScene.instance || !ZoneSystem.instance) return;
            try { RefreshPieces.Invoke(player, null); }
            catch (Exception error)
            {
                // The flag is already restored; a departing world may no longer support rebuilding its GUI.
                Plugin.Instance?.Log.LogWarning("Режим строителя восстановлен, но меню строительства не обновилось: " + error.Message);
            }
        }

        internal struct PlacementScope
        {
            internal bool Entered;
            internal Player PreviousPlayer;
            internal int PreviousDepth;
        }

        internal static PlacementScope EnterPlacement(Player player)
        {
            if (!AppliesTo(player)) return default(PlacementScope);
            var scope = new PlacementScope { Entered = true, PreviousPlayer = placementPlayer, PreviousDepth = placementDepth };
            placementPlayer = player;
            placementDepth++;
            return scope;
        }

        internal static void LeavePlacement(PlacementScope scope)
        {
            if (!scope.Entered) return;
            placementPlayer = scope.PreviousPlayer;
            placementDepth = scope.PreviousDepth;
        }

        internal static bool SkipBuildingResources(Player player, Piece.Requirement[] requirements)
        {
            if (!AppliesTo(player) || placementDepth <= 0 || !ReferenceEquals(placementPlayer, player)) return false;
            var piece = player.GetSelectedPiece();
            // ConsumeResources is also used by crafting: only the selected building piece is free.
            return piece && ReferenceEquals(requirements, piece.m_resources);
        }
    }

    [HarmonyPatch(typeof(Player), "UpdatePlacement", new[] { typeof(bool), typeof(float) })]
    internal static class BuilderPlacementScopePatch
    {
        private static void Prefix(Player __instance, out BuildMode.PlacementScope __state)
        { __state = BuildMode.EnterPlacement(__instance); }

        private static void Finalizer(BuildMode.PlacementScope __state)
        { BuildMode.LeavePlacement(__state); }
    }

    [HarmonyPatch(typeof(Player), "ConsumeResources", new[] { typeof(Piece.Requirement[]), typeof(int), typeof(int), typeof(int) })]
    internal static class BuilderResourcesPatch
    {
        private static bool Prefix(Player __instance, Piece.Requirement[] requirements)
        { return !BuildMode.SkipBuildingResources(__instance, requirements); }
    }

    [HarmonyPatch(typeof(Player), "GetPlaceDurability", new[] { typeof(ItemDrop.ItemData) })]
    internal static class BuilderPlacementDurabilityPatch
    {
        private static bool Prefix(Player __instance, ItemDrop.ItemData tool, ref float __result)
        {
            if (!BuildMode.AppliesTo(__instance) || !BuildMode.IsBuildingTool(tool)) return true;
            __result = 0f;
            return false;
        }
    }

    [HarmonyPatch(typeof(Player), "Repair", new[] { typeof(ItemDrop.ItemData), typeof(Piece) })]
    internal static class BuilderRepairDurabilityPatch
    {
        private struct DurabilityState
        {
            internal ItemDrop.ItemData Tool;
            internal float Durability;
        }

        private static void Prefix(Player __instance, ItemDrop.ItemData toolItem, out DurabilityState __state)
        {
            __state = default(DurabilityState);
            if (BuildMode.AppliesTo(__instance) && BuildMode.IsBuildingTool(toolItem))
                __state = new DurabilityState { Tool = toolItem, Durability = toolItem.m_durability };
        }

        private static void Finalizer(DurabilityState __state)
        {
            // Repair has its own direct durability subtraction, unlike placement/removal.
            // Restore on exceptions too, without changing shared prefab data or repairing the tool.
            if (__state.Tool != null) __state.Tool.m_durability = __state.Durability;
        }
    }
}
