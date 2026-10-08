using System;
using System.Reflection;
using HarmonyLib;
using UnityEngine;

namespace ValheimAdminRu
{
    internal static class FlightMode
    {
        private static readonly FieldInfo DebugFly = AccessTools.Field(typeof(Player), "m_debugFly");
        private static Player appliedPlayer;
        public static bool Enabled { get; private set; }

        public static string Set(bool enabled)
        {
            var player = Player.m_localPlayer;
            if (!player || player.IsDead()) throw new InvalidOperationException("Персонаж ещё не готов к полёту.");
            var view = player.GetComponent<ZNetView>();
            // Reject a command before changing either flag if synchronization is not ready.
            // Reset still clears a disconnected character without a usable network view.
            if (!view || !view.IsValid() || !view.IsOwner() || DebugFly == null)
                throw new InvalidOperationException("Не удалось изменить полёт: персонаж ещё не синхронизирован.");
            if (!Apply(player, enabled)) throw new InvalidOperationException("Не удалось изменить полёт: персонаж ещё не синхронизирован.");
            if (appliedPlayer && appliedPlayer != player) Apply(appliedPlayer, false);
            Enabled = enabled;
            appliedPlayer = enabled ? player : null;
            return enabled ? "Полёт включён. Space — вверх, левый Ctrl — вниз, Shift — ускорение."
                : "Полёт выключен.";
        }

        public static void Tick()
        {
            if (!Enabled) return;
            var player = Player.m_localPlayer;
            if (appliedPlayer && appliedPlayer != player) Apply(appliedPlayer, false);
            if (!player || player.IsDead()) return;
            if (Apply(player, true)) appliedPlayer = player;
        }

        public static void Reset()
        {
            if (Enabled)
            {
                if (appliedPlayer) Apply(appliedPlayer, false);
                if (Player.m_localPlayer && Player.m_localPlayer != appliedPlayer) Apply(Player.m_localPlayer, false);
            }
            Enabled = false;
            appliedPlayer = null;
        }

        private static bool Apply(Player player, bool enabled)
        {
            if (DebugFly == null) return false;
            // A disconnect may invalidate the network view before our reset runs.
            // Clear the local flag even when it is too late to publish its state.
            if (!enabled && player.InDebugFlyMode()) DebugFly.SetValue(player, false);
            var view = player.GetComponent<ZNetView>();
            if (!view || !view.IsValid() || !view.IsOwner()) return false;
            // Use Valheim's flight flag and motion so movement, camera and replication stay native.
            // ToggleDebugFly would also display an English message; our status is in Russian.
            if (player.InDebugFlyMode() != enabled) DebugFly.SetValue(player, enabled);
            if (view.GetZDO().GetBool(ZDOVars.s_debugFly) != enabled) view.GetZDO().Set(ZDOVars.s_debugFly, enabled);
            return true;
        }
    }
}
