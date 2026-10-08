using System;
using System.Collections.Generic;
using UnityEngine;

namespace ValheimAdminRu
{
    public enum AdminAction { TeleportMap, TeleportToPlayer, SummonPlayer, GodSelf, GodPlayer, SpawnItem, SpawnMob, Flatten, HammerToggle, HammerStrike, RaiseTerrain, LowerTerrain, FlySelf,
        UndoTerrain, CleanupSpawn, ReturnTeleport, TeleportSaved, HealPlayer, RestoreStaminaPlayer, ClearEffectsPlayer, BuildToggle, RepairArea, KickPlayer, BanPlayer, UnbanPlayer, SetRole }
    [Flags]
    public enum HammerTargets { None=0, Mobs=1, Trees=2, Ore=4, Structures=8, All=15 }
    [Flags]
    public enum AdminPermission { None=0, Travel=1, Help=2, Spawn=4, Terrain=8, Hammer=16, Build=32, Moderate=64, Audit=128, ManageRoles=256, All=511 }
    public enum AdminRole { None, Moderator, Builder, Owner }

    public static class RoleRules
    {
        public static AdminPermission Permissions(AdminRole role)
        {
            switch (role)
            {
                case AdminRole.Owner: return AdminPermission.All;
                case AdminRole.Moderator: return AdminPermission.Travel | AdminPermission.Help | AdminPermission.Moderate | AdminPermission.Audit;
                case AdminRole.Builder: return AdminPermission.Travel | AdminPermission.Spawn | AdminPermission.Terrain | AdminPermission.Hammer | AdminPermission.Build | AdminPermission.Audit;
                default: return AdminPermission.None;
            }
        }
        public static AdminPermission Required(AdminAction action)
        {
            switch (action)
            {
                case AdminAction.TeleportMap: case AdminAction.TeleportToPlayer: case AdminAction.ReturnTeleport:
                case AdminAction.TeleportSaved: case AdminAction.FlySelf: return AdminPermission.Travel;
                case AdminAction.SummonPlayer: case AdminAction.GodSelf: case AdminAction.GodPlayer: case AdminAction.HealPlayer:
                case AdminAction.RestoreStaminaPlayer: case AdminAction.ClearEffectsPlayer: return AdminPermission.Help;
                case AdminAction.SpawnItem: case AdminAction.SpawnMob: case AdminAction.CleanupSpawn: return AdminPermission.Spawn;
                case AdminAction.Flatten: case AdminAction.RaiseTerrain: case AdminAction.LowerTerrain: case AdminAction.UndoTerrain: return AdminPermission.Terrain;
                case AdminAction.HammerToggle: case AdminAction.HammerStrike: return AdminPermission.Hammer;
                case AdminAction.BuildToggle: case AdminAction.RepairArea: return AdminPermission.Build;
                case AdminAction.KickPlayer: case AdminAction.BanPlayer: case AdminAction.UnbanPlayer: return AdminPermission.Moderate;
                case AdminAction.SetRole: return AdminPermission.ManageRoles;
                default: return AdminPermission.None;
            }
        }
        public static string Name(AdminRole role)
        { return Locale.Translate(RawName(role)); }

        public static string RawName(AdminRole role)
        {
            switch (role) { case AdminRole.Owner: return "Владелец"; case AdminRole.Moderator: return "Модератор"; case AdminRole.Builder: return "Строитель"; default: return "Игрок"; }
        }
    }

    public sealed class AdminCommand
    {
        public int Id;
        public AdminAction Action;
        public long Target;
        public string Prefab = "";
        public int Count = 1;
        public float Radius = 5f;
        public float Height = 1f;
        public bool Enabled;
        public Vector3 Position;
        public HammerTargets HammerTargets = HammerTargets.All;
        public string Text = "";
        public string Identity = "";
        public string BatchId = "";
        public AdminRole Role;

        public void Write(ZPackage p)
        {
            p.Write(Id); p.Write((int)Action); p.Write(Target); p.Write(Prefab);
            p.Write(Count); p.Write(Radius); p.Write(Enabled); p.Write(Position); p.Write(Height);
            p.Write((int)HammerTargets); p.Write(Text); p.Write(Identity); p.Write(BatchId); p.Write((int)Role);
        }
        public static AdminCommand Read(ZPackage p)
        {
            return new AdminCommand { Id=p.ReadInt(), Action=(AdminAction)p.ReadInt(), Target=p.ReadLong(),
                Prefab=p.ReadString(), Count=p.ReadInt(), Radius=p.ReadSingle(), Enabled=p.ReadBool(), Position=p.ReadVector3(), Height=p.ReadSingle(),
                HammerTargets=(HammerTargets)p.ReadInt(), Text=p.ReadString(), Identity=p.ReadString(), BatchId=p.ReadString(), Role=(AdminRole)p.ReadInt() };
        }
    }
    public sealed class PlayerRow
    {
        public long Id;
        public string Name;
        public bool HasMod;
        public bool Alive;
        public bool God;
        public bool Flying;
        public string Identity = "";
        public AdminRole Role;
        public AdminPermission Permissions;
        public bool Building;
    }
    public sealed class AuditRow { public string TimeUtc="", Actor="", Action="", Details="", Result=""; }
    public sealed class BanRow { public string Identity="", Reason=""; }
    public static class CommandRules
    {
        public static bool Valid(AdminCommand c)
        {
            return c != null && Enum.IsDefined(typeof(AdminAction), c.Action) && c.Prefab != null && c.Prefab.Length <= 160
                && c.Text != null && c.Text.Length <= 300 && c.Identity != null && c.Identity.Length <= 128
                && c.BatchId != null && c.BatchId.Length <= 64 && Enum.IsDefined(typeof(AdminRole), c.Role)
                && ((int)c.HammerTargets & ~(int)HammerTargets.All) == 0
                && (c.Action != AdminAction.HammerStrike && !(c.Action == AdminAction.HammerToggle && c.Enabled) || c.HammerTargets != HammerTargets.None)
                && c.Count >= 1 && c.Count <= (c.Action == AdminAction.SpawnMob ? 20 : 500)
                && Finite(c.Radius) && c.Radius >= 1 && c.Radius <= 40
                && Finite(c.Height) && c.Height >= 0.1f && c.Height <= 8f
                && Finite(c.Position.x) && Finite(c.Position.y) && Finite(c.Position.z)
                && Math.Abs(c.Position.x) <= 10500 && Math.Abs(c.Position.z) <= 10500 && Math.Abs(c.Position.y) <= 10000;
        }
        public static bool Finite(float n) { return !float.IsNaN(n) && !float.IsInfinity(n); }
    }
}
