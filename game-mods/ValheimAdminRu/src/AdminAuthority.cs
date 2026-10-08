using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Xml.Linq;
using BepInEx;
using HarmonyLib;

namespace ValheimAdminRu
{
    internal static class AdminStorage
    {
        internal static string PathFor(string name) { return Path.Combine(Paths.ConfigPath, "ValheimAdminRu", name); }
        internal static void Save(string path, XElement document)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                document.Save(temporary);
                if (File.Exists(path)) File.Replace(temporary, path, null);
                else File.Move(temporary, path);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
        internal static string Text(XElement row, string name) { return (string)row.Attribute(name) ?? ""; }
    }

    /// <summary>Only the server reads this store. Native admins always retain ownership.</summary>
    internal sealed class AdminAuthority
    {
        private static readonly FieldInfo BannedField = AccessTools.Field(typeof(ZNet), "m_bannedList");
        private static readonly MethodInfo KickPeer = AccessTools.Method(typeof(ZNet), "InternalKick", new[] { typeof(ZNetPeer) });
        private readonly Plugin plugin;
        private readonly string rolesPath = AdminStorage.PathFor("roles.xml");
        private readonly string statePath = AdminStorage.PathFor("state.xml");
        private Dictionary<string, AdminRole> roles = new Dictionary<string, AdminRole>(StringComparer.Ordinal);
        private readonly Dictionary<string, string> batches = new Dictionary<string, string>(StringComparer.Ordinal);
        private readonly Dictionary<string, string> reasons = new Dictionary<string, string>(StringComparer.Ordinal);
        private DateTime rolesStamp = DateTime.MinValue;
        private bool checkedRoles;

        internal AdminAuthority(Plugin plugin) { this.plugin = plugin; ReloadRoles(); LoadState(); }
        internal static string Identity(ZNetPeer peer) { return peer?.m_socket?.GetHostName() ?? ""; }
        internal AdminRole Role(ZNetPeer peer)
        {
            string identity = Identity(peer);
            if (identity.Length == 0) return AdminRole.None;
            if (ZNet.instance && ZNet.instance.IsAdmin(identity)) return AdminRole.Owner;
            ReloadRoles();
            return roles.TryGetValue(identity, out AdminRole role) ? role : AdminRole.None;
        }
        internal void SetRole(string identity, AdminRole role)
        {
            if (string.IsNullOrWhiteSpace(identity) || identity.Length > 128 || role == AdminRole.Owner || !Enum.IsDefined(typeof(AdminRole), role))
                throw new InvalidOperationException("Недопустимая роль или ID игрока.");
            ReloadRoles();
            var next = new Dictionary<string, AdminRole>(roles, StringComparer.Ordinal);
            if (role == AdminRole.None) next.Remove(identity); else next[identity] = role;
            var document = new XElement("roles");
            foreach (var pair in next) document.Add(new XElement("player", new XAttribute("identity", pair.Key), new XAttribute("role", pair.Value)));
            AdminStorage.Save(rolesPath, document);
            roles = next; rolesStamp = File.GetLastWriteTimeUtc(rolesPath); checkedRoles = true;
        }
        private void ReloadRoles()
        {
            DateTime stamp = File.Exists(rolesPath) ? File.GetLastWriteTimeUtc(rolesPath) : DateTime.MinValue;
            if (checkedRoles && stamp == rolesStamp) return;
            checkedRoles = true; rolesStamp = stamp;
            var loaded = new Dictionary<string, AdminRole>(StringComparer.Ordinal);
            try
            {
                if (File.Exists(rolesPath))
                    foreach (XElement row in XElement.Load(rolesPath).Elements("player"))
                    {
                        string identity = AdminStorage.Text(row, "identity");
                        if (identity.Length > 0 && identity.Length <= 128 && Enum.TryParse(AdminStorage.Text(row, "role"), out AdminRole role)
                            && (role == AdminRole.Moderator || role == AdminRole.Builder)) loaded[identity] = role;
                    }
            }
            catch (Exception e) { plugin.Log.LogWarning("Не удалось прочитать роли; дополнительные права отозваны: " + e.GetType().Name); }
            roles = loaded;
        }
        private string BatchKey(string identity)
        {
            if (!ZNet.instance || ZNet.instance.GetWorld() == null) throw new InvalidOperationException("Мир сервера ещё не загружен.");
            return ZNet.instance.GetWorldUID().ToString(System.Globalization.CultureInfo.InvariantCulture) + ":" + identity;
        }
        internal string LastBatch(string identity) { return batches.TryGetValue(BatchKey(identity), out string batch) ? batch : ""; }
        internal void RecordBatch(string identity, string batch) { batches[BatchKey(identity)] = batch; SaveState(); }
        internal void ForgetBatch(string identity) { batches.Remove(BatchKey(identity)); SaveState(); }
        internal string Reason(string identity) { return reasons.TryGetValue(identity, out string reason) ? reason : ""; }
        internal void Ban(ZNetPeer peer, string reason)
        {
            string identity = Identity(peer);
            var list = BannedField?.GetValue(ZNet.instance) as SyncedList;
            if (list == null || identity.Length == 0) throw new InvalidOperationException("Список блокировок сервера недоступен.");
            list.Add(identity);
            if (!list.Contains(identity)) throw new InvalidOperationException("Не удалось заблокировать игрока.");
            reasons[identity] = AdminAudit.Clean(reason, 300); SaveState();
            Kick(peer);
        }
        internal void Unban(string identity)
        {
            var list = BannedField?.GetValue(ZNet.instance) as SyncedList;
            if (list == null || !list.Contains(identity)) throw new InvalidOperationException("Такого ID нет в списке блокировок.");
            list.Remove(identity);
            if (list.Contains(identity)) throw new InvalidOperationException("Не удалось снять блокировку.");
            reasons.Remove(identity); SaveState();
        }
        internal static void Kick(ZNetPeer peer)
        {
            if (KickPeer == null) throw new InvalidOperationException("Команда отключения недоступна в этой версии игры.");
            KickPeer.Invoke(ZNet.instance, new object[] { peer });
        }
        private void LoadState()
        {
            try
            {
                if (!File.Exists(statePath)) return;
                XElement data = XElement.Load(statePath);
                foreach (XElement row in data.Elements("batch"))
                {
                    string key = AdminStorage.Text(row, "key"), token = AdminStorage.Text(row, "token");
                    if (key.Length <= 200 && Guid.TryParseExact(token, "N", out Guid ignored)) batches[key] = token;
                }
                foreach (XElement row in data.Elements("ban"))
                {
                    string identity = AdminStorage.Text(row, "identity");
                    if (identity.Length > 0 && identity.Length <= 128) reasons[identity] = AdminAudit.Clean(AdminStorage.Text(row, "reason"), 300);
                }
            }
            catch (Exception e) { plugin.Log.LogWarning("Не удалось прочитать состояние админ-мода: " + e.GetType().Name); }
        }
        private void SaveState()
        {
            try
            {
                var data = new XElement("state");
                foreach (var pair in batches) data.Add(new XElement("batch", new XAttribute("key", pair.Key), new XAttribute("token", pair.Value)));
                foreach (var pair in reasons) data.Add(new XElement("ban", new XAttribute("identity", pair.Key), new XAttribute("reason", pair.Value)));
                AdminStorage.Save(statePath, data);
            }
            catch (Exception e) { plugin.Log.LogWarning("Не удалось сохранить состояние админ-мода: " + e.GetType().Name); }
        }
    }
}
