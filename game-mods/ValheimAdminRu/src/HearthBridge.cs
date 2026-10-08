using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;
using UnityEngine;

namespace ValheimAdminRu
{
    /// <summary>A private spool, polled on Unity's thread. It is not a network listener.</summary>
    internal sealed class HearthBridge
    {
        internal sealed class Request
        {
            internal string Id, Session, ActorSteam, TargetSteam, PointId;
            internal double Expires;
            internal AdminCommand Command;
        }

        internal static readonly Regex Steam = new Regex(@"\A7656119[0-9]{10}\z", RegexOptions.CultureInvariant);
        private static readonly Regex Identifier = new Regex(@"\A[a-f0-9]{32}\z", RegexOptions.CultureInvariant);
        private static readonly Regex QueueName = new Regex(@"\Acommand-([a-f0-9]{32})\.xml\z", RegexOptions.CultureInvariant);
        private static readonly HashSet<string> Attributes = new HashSet<string>(StringComparer.Ordinal)
        { "id", "session", "expires", "action", "actor_steam", "target_steam", "point_id", "prefab", "count", "radius", "height", "enabled", "x", "y", "z", "role", "text", "hammer_targets" };
        private readonly Plugin plugin;
        private readonly NetworkService network;
        private readonly Dictionary<string, double> seen = new Dictionary<string, double>();
        private readonly string folder;
        private float nextPoll, nextStatus, nextCleanup, nextWarning;
        internal string Session { get; private set; } = "";
        internal bool Enabled => folder != null;
        private float lastHealthy = -100f;
        internal bool Healthy => Enabled && Session.Length != 0 && Time.realtimeSinceStartup - lastHealthy < 6f;
        internal static double Now => (DateTime.UtcNow - new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc)).TotalSeconds;
        internal static string Number(double value) => value.ToString("R", CultureInfo.InvariantCulture);
        internal static string SteamId(string identity)
        {
            string value = identity ?? "";
            if (value.StartsWith("Steam_", StringComparison.Ordinal)) value = value.Substring(6);
            return Steam.IsMatch(value) ? value : "";
        }

        internal HearthBridge(Plugin plugin, NetworkService network)
        {
            this.plugin = plugin; this.network = network;
            string configured = Environment.GetEnvironmentVariable("HEARTH_ADMIN_BRIDGE");
            if (string.IsNullOrEmpty(configured)) return;
            try
            {
                if (!Path.IsPathRooted(configured)) throw new IOException("Bridge directory must be absolute");
                string path = Path.GetFullPath(configured);
                CheckExistingAncestors(path);
                Directory.CreateDirectory(path);
                CheckDirectory(path);
                folder = path;
            }
            catch (Exception error) { plugin.Log.LogWarning("Игровой мост отключён: " + error.GetType().Name); }
        }

        private static void CheckDirectory(string path)
        {
            for (DirectoryInfo entry = new DirectoryInfo(path); entry != null; entry = entry.Parent)
                if (!entry.Exists || (entry.Attributes & FileAttributes.ReparsePoint) != 0)
                    throw new IOException("Unsafe bridge directory");
        }

        private static void CheckExistingAncestors(string path)
        {
            for (DirectoryInfo entry = new DirectoryInfo(path); entry != null; entry = entry.Parent)
                if (entry.Exists && (entry.Attributes & FileAttributes.ReparsePoint) != 0)
                    throw new IOException("Unsafe bridge directory");
        }

        internal void Activate(string session)
        {
            Session = session; seen.Clear(); nextPoll = nextStatus = nextCleanup = 0; lastHealthy = -100f;
        }

        internal void Suspend()
        {
            Session = ""; seen.Clear(); lastHealthy = -100f;
            if (folder == null) return;
            try { File.Delete(Path.Combine(folder, "status.xml")); }
            catch (Exception error) { Warning(error); }
        }

        internal void Tick()
        {
            if (folder == null || Session.Length == 0) return;
            float tick = Time.realtimeSinceStartup;
            try
            {
                CheckDirectory(folder);
                if (tick >= nextStatus)
                {
                    nextStatus = tick + 2f;
                    Atomic("status.xml", network.BridgeSnapshot(Session, Now), 4 * 1024 * 1024);
                    lastHealthy = tick;
                }
                if (tick >= nextPoll)
                {
                    nextPoll = tick + .25f;
                    int count = 0;
                    foreach (string path in Directory.EnumerateFiles(folder, "command-*.xml"))
                    {
                        if (count++ >= 4) break;
                        Match match = QueueName.Match(Path.GetFileName(path));
                        if (match.Success) Consume(path, match.Groups[1].Value);
                    }
                }
                if (tick >= nextCleanup)
                {
                    nextCleanup = tick + 30f;
                    double now = Now;
                    foreach (string id in seen.Where(pair => pair.Value < now).Select(pair => pair.Key).ToList()) seen.Remove(id);
                    foreach (string path in Directory.EnumerateFiles(folder))
                    {
                        string name = Path.GetFileName(path);
                        if (!Regex.IsMatch(name, @"\A(?:claimed|result)-[a-f0-9]{32}\.xml\z") && !Regex.IsMatch(name, @"\A\.[a-f0-9]{32}\.tmp\z")) continue;
                        if (File.GetLastWriteTimeUtc(path) < DateTime.UtcNow.AddMinutes(-5)) File.Delete(path);
                    }
                }
            }
            catch (Exception error) { Warning(error); }
        }

        private void Consume(string path, string id)
        {
            string claimed = Path.Combine(folder, "claimed-" + id + ".xml");
            try
            {
                if (seen.ContainsKey(id) || File.Exists(claimed)) { File.Delete(path); return; }
                if ((File.GetAttributes(path) & (FileAttributes.ReparsePoint | FileAttributes.Directory)) != 0) throw new IOException("Unsafe command file");
                // Durable claim occurs before parsing or dispatch. Claimed files
                // are never scanned as work, including after a process restart.
                File.Move(path, claimed);
                seen[id] = Now + 300;
                Request request = Parse(ReadXml(claimed, 16384), id, Session, Now);
                network.SubmitBridge(request, (success, message) => Finish(request, success, message));
            }
            catch (Exception error)
            {
                var request = new Request { Id = id, Session = Session };
                Finish(request, false, error is InvalidOperationException || error is FormatException ? error.Message : "Не удалось прочитать или выполнить игровую команду.");
            }
        }

        private void Finish(Request request, bool success, string message)
        {
            try
            {
                Atomic("result-" + request.Id + ".xml", new XElement("result",
                    new XAttribute("id", request.Id), new XAttribute("session", request.Session), new XAttribute("at", Number(Now)),
                    new XAttribute("state", success ? "done" : "error"), new XAttribute("success", success ? "true" : "false"),
                    new XAttribute("message", AdminAudit.Clean(message, 1000)), new XAttribute("message_en", AdminAudit.Clean(Locale.TranslateEnglish(message), 1000))), 16384);
                nextStatus = 0;
            }
            catch (Exception error) { Warning(error); }
        }

        internal static XElement ReadXml(string path, int maximum)
        {
            if ((File.GetAttributes(path) & (FileAttributes.ReparsePoint | FileAttributes.Directory)) != 0) throw new IOException("Unsafe XML file");
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                if (stream.Length == 0 || stream.Length > maximum) throw new IOException("Oversized XML file");
                using (var reader = XmlReader.Create(stream, new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null, MaxCharactersInDocument = maximum, MaxCharactersFromEntities = 0 }))
                    return XElement.Load(reader);
            }
        }

        internal static Request Parse(XElement row, string id, string session, double now)
        {
            if (row.Name != "command" || row.HasElements || !string.IsNullOrWhiteSpace(row.Value)
                || row.Attributes().Any(attribute => attribute.Name.NamespaceName.Length != 0 || !Attributes.Contains(attribute.Name.LocalName))
                || !Identifier.IsMatch(id) || Text(row, "id") != id || Text(row, "session") != session)
                throw new InvalidOperationException("Мир или сессия игрового моста изменились.");
            double expires = Double(row, "expires", 0);
            if (expires <= now || expires > now + 30.5) throw new InvalidOperationException("Срок игровой команды истёк.");
            string actionText = Text(row, "action");
            if (!Enum.TryParse(actionText, out AdminAction action) || !Enum.IsDefined(typeof(AdminAction), action) || action.ToString() != actionText
                || action == AdminAction.BanPlayer || action == AdminAction.UnbanPlayer || action == AdminAction.KickPlayer)
                throw new InvalidOperationException("Эта команда не поддерживается игровым мостом.");
            string actor = Text(row, "actor_steam"), target = Text(row, "target_steam"), point = Text(row, "point_id");
            if (!Steam.IsMatch(actor) || target.Length > 0 && !Steam.IsMatch(target) || point.Length > 0 && !Identifier.IsMatch(point))
                throw new InvalidOperationException("Выберите игрока по SteamID64.");
            string roleText = Text(row, "role", "None");
            if (!Enum.TryParse(roleText, out AdminRole role) || !Enum.IsDefined(typeof(AdminRole), role) || role.ToString() != roleText || role == AdminRole.Owner)
                throw new InvalidOperationException("Владельца назначают через native-список сервера.");
            var command = new AdminCommand { Action = action, Prefab = Text(row, "prefab"), Count = Integer(row, "count", 1),
                Radius = (float)Double(row, "radius", 5), Height = (float)Double(row, "height", 1), Enabled = Boolean(row, "enabled", false),
                Position = new Vector3((float)Double(row, "x", 0), (float)Double(row, "y", 0), (float)Double(row, "z", 0)),
                HammerTargets = (HammerTargets)Integer(row, "hammer_targets", 15), Role = role, Text = Text(row, "text") };
            if (!CommandRules.Valid(command) || command.Text.Any(char.IsControl) || command.Prefab.Any(char.IsControl))
                throw new InvalidOperationException("Недопустимые параметры игровой команды.");
            return new Request { Id = id, Session = session, Expires = expires, ActorSteam = actor, TargetSteam = target, PointId = point, Command = command };
        }

        private static string Text(XElement row, string name, string fallback = "") => (string)row.Attribute(name) ?? fallback;
        private static double Double(XElement row, string name, double fallback)
        {
            string value = Text(row, name);
            if (value.Length == 0) return fallback;
            if (!double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out double number) || double.IsNaN(number) || double.IsInfinity(number))
                throw new FormatException("Недопустимое число игровой команды.");
            return number;
        }
        private static int Integer(XElement row, string name, int fallback)
        {
            double number = Double(row, name, fallback);
            if (number < int.MinValue || number > int.MaxValue || number != Math.Truncate(number)) throw new FormatException("Ожидается целое число игровой команды.");
            return (int)number;
        }
        private static bool Boolean(XElement row, string name, bool fallback)
        {
            string value = Text(row, name, fallback ? "true" : "false");
            if (value != "true" && value != "false") throw new FormatException("Ожидается логическое значение игровой команды.");
            return value == "true";
        }

        private void Atomic(string name, XElement document, int maximum)
        {
            CheckDirectory(folder);
            string temporary = Path.Combine(folder, "." + Guid.NewGuid().ToString("N") + ".tmp"), target = Path.Combine(folder, name);
            try
            {
                if (File.Exists(target) && (File.GetAttributes(target) & (FileAttributes.ReparsePoint | FileAttributes.Directory)) != 0) throw new IOException("Unsafe bridge target");
                using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                {
                    using (var writer = XmlWriter.Create(stream, new XmlWriterSettings { Encoding = new UTF8Encoding(false), CloseOutput = false })) document.Save(writer);
                    if (stream.Length > maximum) throw new IOException("Oversized bridge snapshot");
                    stream.Flush(true);
                }
                if (File.Exists(target)) File.Replace(temporary, target, null); else File.Move(temporary, target);
            }
            finally { try { if (File.Exists(temporary)) File.Delete(temporary); } catch (IOException) { } }
        }

        private void Warning(Exception error)
        {
            if (Time.realtimeSinceStartup < nextWarning) return;
            nextWarning = Time.realtimeSinceStartup + 30f;
            plugin.Log.LogWarning("Ошибка игрового моста: " + error.GetType().Name);
        }
    }

#if !HEARTH_BRIDGE_TEST
    public sealed partial class NetworkService
    {
        private const string WebExecuteRpc = Prefix + "WebExecute", ClientStateRpc = Prefix + "ClientState", WebLeaseRpc = Prefix + "WebLease";
        private HearthBridge bridge;
        private readonly Catalog bridgeCatalog = new Catalog();
        private string worldSession = "", remoteSession = "";
        private long worldScope, remoteWorld;
        private int remoteGeneration;
        private float nextClientState, nextWebLease, trustedUntil;
        private AdminPermission trustedEffects;
        public bool EffectAllowed(AdminPermission permission) => Allowed(permission)
            || Connected && ClientWorldMatches() && Time.realtimeSinceStartup < trustedUntil
                && permission != AdminPermission.None && (trustedEffects & permission) == permission;

        private bool ClientWorldMatches() => ZNet.instance && !ZNet.instance.IsServer() && ZNet.instance.GetWorld() != null
            && remoteSession.Length == 32 && ZNet.instance.GetWorldUID() == remoteWorld
            && clientConnection != null && FromServer(clientConnection);

        private void ClearWebEffects()
        { trustedEffects = AdminPermission.None; trustedUntil = 0; }

        private void CheckWebEffects(float now)
        {
            if (trustedEffects == AdminPermission.None || Connected && ClientWorldMatches() && now < trustedUntil) return;
            ClearWebEffects(); plugin.HammerEnabled = false; WorldActions.Reset();
        }

        private static AdminPermission PersistentEffect(AdminAction action)
        {
            switch (action)
            {
                case AdminAction.GodSelf: case AdminAction.GodPlayer: return AdminPermission.Help;
                case AdminAction.FlySelf: return AdminPermission.Travel;
                case AdminAction.BuildToggle: return AdminPermission.Build;
                case AdminAction.HammerToggle: return AdminPermission.Hammer;
                default: return AdminPermission.None;
            }
        }

        private void SendWebLease(ZNetPeer peer, PeerState state)
        {
            if (peer == null || !state.Ready) return;
            if (!bridge.Healthy) state.WebEffects = AdminPermission.None;
            AdminPermission effects = state.WebEffects;
            // Keep an enabling command alive while its acknowledgement is in flight.
            // These provisional bits still cannot enable client effects by themselves.
            if (bridge.Healthy)
                foreach (Pending execution in pending.Values)
                    if (execution.WebReply != null && execution.Enabled && ReferenceEquals(execution.Executor, peer.m_rpc)
                        && execution.WebSession == worldSession && execution.ExecutorGeneration == state.Generation
                        && execution.Expires > HearthBridge.Now && execution.Deadline > Time.realtimeSinceStartup)
                        effects |= PersistentEffect(execution.Action);
            var package = new ZPackage(); package.Write(ProtocolVersion); package.Write(worldSession); package.Write(state.Generation);
            package.Write(worldScope); package.Write(7000); package.Write((int)effects);
            peer.m_rpc.Invoke(WebLeaseRpc, package);
        }

        private void OnWebLease(ZRpc rpc, ZPackage package)
        {
            if (!Connected || !FromServer(rpc) || !Packet(package, 128)) return;
            try
            {
                if (package.ReadInt() != ProtocolVersion || package.ReadString() != remoteSession || package.ReadInt() != remoteGeneration
                    || package.ReadLong() != remoteWorld || !ClientWorldMatches()) return;
                int ttl = package.ReadInt();
                var effects = (AdminPermission)package.ReadInt();
                AdminPermission allowed = AdminPermission.Help | AdminPermission.Travel | AdminPermission.Build | AdminPermission.Hammer;
                if (ttl <= 0 || ttl > 7000 || (effects & ~allowed) != 0) return;
                // A lease never enables an effect, and never changes ordinary RPC permissions.
                AdminPermission removed = trustedEffects & ~effects;
                trustedEffects &= effects; trustedUntil = Time.realtimeSinceStartup + ttl / 1000f;
                if (removed != AdminPermission.None) WorldActions.RevokeEffects(removed);
            }
            catch (Exception error) { LogBadPacket("срок веб-команды", error); }
        }

        private void BridgeTick(ZNet net)
        {
            if (!net.IsServer()) return;
            long scope = net.GetWorld() == null ? 0 : net.GetWorldUID();
            if (scope != worldScope)
            {
                foreach (var entry in pending.Values.ToList()) Complete(entry, false, "Мир сервера изменился; команда не будет повторена.");
                pending.Clear(); worldScope = scope; worldSession = Guid.NewGuid().ToString("N");
                bridge.Suspend();
                foreach (ZNetPeer peer in net.GetPeers())
                    if (peer != null && peer.m_rpc != null && states.TryGetValue(peer.m_rpc, out PeerState state) && state.Ready)
                    { ++state.Generation; state.WebEffects = AdminPermission.None; state.Hammer = state.God = state.Flying = state.Building = false;
                        state.Points.Clear(); state.ClientStateAt = -100; Welcome(peer, state); }
            }
            if (scope != 0 && net.IsDedicated())
            {
                if (bridge.Session != worldSession) bridge.Activate(worldSession);
                bridge.Tick();
            }
            if (Time.realtimeSinceStartup >= nextWebLease)
            {
                nextWebLease = Time.realtimeSinceStartup + 2f;
                foreach (ZNetPeer peer in net.GetPeers())
                    if (peer != null && peer.m_rpc != null && states.TryGetValue(peer.m_rpc, out PeerState state) && state.Ready) SendWebLease(peer, state);
            }
        }

        internal XElement BridgeSnapshot(string session, double now)
        {
            var root = new XElement("status", new XAttribute("protocol", "1"), new XAttribute("session", session),
                new XAttribute("at", HearthBridge.Number(now)), new XAttribute("mod", Plugin.ModVersion),
                new XAttribute("game", global::Version.CurrentVersion.ToString()),
                new XAttribute("world", AdminAudit.Clean(ZNet.instance.GetWorld()?.m_name, 256)),
                new XAttribute("world_id", worldScope.ToString(CultureInfo.InvariantCulture)));
            var players = new XElement("players"); var roles = new XElement("roles");
            foreach (ZNetPeer peer in ZNet.instance.GetPeers().Take(300))
            {
                if (peer == null || !peer.IsReady() || peer.m_rpc == null || !peer.m_rpc.IsConnected()) continue;
                string identity = AdminAuthority.Identity(peer), steam = HearthBridge.SteamId(identity);
                if (steam.Length == 0) continue;
                states.TryGetValue(peer.m_rpc, out PeerState state);
                AdminRole role = authority.Role(peer); ZDO character = CharacterData(peer);
                Vector3 position = character == null ? Vector3.zero : character.GetPosition();
                bool fresh = state != null && state.Ready && Time.realtimeSinceStartup - state.ClientStateAt <= 15;
                var row = new XElement("player", new XAttribute("steam_id", steam), new XAttribute("identity", identity),
                    new XAttribute("name", AdminAudit.Clean(peer.m_playerName, 256)), new XAttribute("role", role),
                    new XAttribute("permissions", (int)RoleRules.Permissions(role)), new XAttribute("ready", state != null && state.Ready),
                    new XAttribute("alive", Alive(character)), new XAttribute("god", state != null && state.God),
                    new XAttribute("flying", state != null && state.Flying), new XAttribute("building", state != null && state.Building),
                    new XAttribute("hammer", state != null && state.Hammer), new XAttribute("x", HearthBridge.Number(position.x)),
                    new XAttribute("y", HearthBridge.Number(position.y)), new XAttribute("z", HearthBridge.Number(position.z)),
                    new XAttribute("points_ready", fresh), new XAttribute("can_return", fresh && state.CanReturn), new XAttribute("can_undo", fresh && state.CanUndo));
                var points = new XElement("points");
                if (fresh) foreach (SavedPoint point in state.Points)
                    points.Add(new XElement("point", new XAttribute("id", point.Id), new XAttribute("name", point.Name),
                        new XAttribute("x", HearthBridge.Number(point.X)), new XAttribute("y", HearthBridge.Number(point.Y)), new XAttribute("z", HearthBridge.Number(point.Z))));
                row.Add(points); players.Add(row);
                roles.Add(new XElement("role", new XAttribute("steam_id", steam), new XAttribute("identity", identity), new XAttribute("role", role)));
            }
            root.Add(players, roles);
            bridgeCatalog.Ensure();
            foreach (var collection in new[] { new { Name = "items", Entries = bridgeCatalog.Items }, new { Name = "mobs", Entries = bridgeCatalog.Mobs } })
            {
                var list = new XElement(collection.Name);
                foreach (Catalog.Entry entry in collection.Entries.Take(5000))
                    list.Add(new XElement("entry", new XAttribute("prefab", AdminAudit.Clean(entry.Id, 160)), new XAttribute("name", AdminAudit.Clean(entry.NameRu, 256)),
                        new XAttribute("name_en", AdminAudit.Clean(entry.NameEn, 256))));
                root.Add(list);
            }
            var history = new XElement("audit");
            foreach (AuditRow row in audit.Recent()) history.Add(new XElement("row", new XAttribute("utc", row.TimeUtc), new XAttribute("actor", row.Actor),
                new XAttribute("action", row.Action), new XAttribute("details", row.Details), new XAttribute("result", row.Result),
                new XAttribute("details_en", Locale.TranslateEnglish(row.Details)), new XAttribute("result_en", Locale.TranslateEnglish(row.Result))));
            root.Add(history);
            var bans = new XElement("bans");
            foreach (string identity in ZNet.instance.Banned.Take(1000))
                bans.Add(new XElement("ban", new XAttribute("identity", AdminAudit.Clean(identity, 128)), new XAttribute("steam_id", HearthBridge.SteamId(identity)), new XAttribute("reason", AdminAudit.Clean(authority.Reason(identity), 300))));
            root.Add(bans); return root;
        }

        private ZNetPeer SteamPeer(string steam, bool requireMod = true, bool alive = true)
        {
            if (!HearthBridge.Steam.IsMatch(steam ?? "")) throw new InvalidOperationException("Выберите игрока по SteamID64.");
            ZNetPeer found = null;
            foreach (ZNetPeer peer in ZNet.instance.GetPeers())
            {
                if (HearthBridge.SteamId(AdminAuthority.Identity(peer)) != steam || peer == null || !peer.IsReady() || peer.m_rpc == null || !peer.m_rpc.IsConnected()) continue;
                if (found != null) throw new InvalidOperationException("У SteamID несколько подключений; дождитесь завершения переподключения.");
                found = peer;
            }
            if (found == null) throw new InvalidOperationException("Выбранный игрок уже отключился от сервера.");
            return Target(found.m_uid, requireMod, alive);
        }

        internal void SubmitBridge(HearthBridge.Request request, Action<bool, string> reply)
        {
            AdminCommand command = request.Command;
            string details = "", pendingToken = null;
            try
            {
                if (!ZNet.instance || !ZNet.instance.IsDedicated() || !bridge.Healthy || request.Session != worldSession || request.Expires <= HearthBridge.Now || worldScope == 0)
                    throw new InvalidOperationException("Игровая сессия завершилась; команда не будет повторена.");
                ZNetPeer actor = SteamPeer(request.ActorSteam, true, false);
                PeerState actorState = states[actor.m_rpc];
                UpdateAuthority(actor, actorState, true);
                float now = Time.realtimeSinceStartup;
                if (now - actorState.LastCommand < .3f) throw new InvalidOperationException("Подождите перед следующей командой.");
                actorState.LastCommand = now;
                if (command.Action == AdminAction.SetRole)
                {
                    ZNetPeer target = SteamPeer(request.TargetSteam, false, false);
                    if (IsAdmin(target)) throw new InvalidOperationException("Владельцы из adminlist.txt сохраняют полный доступ.");
                    command.Identity = AdminAuthority.Identity(target); command.Target = target.m_uid;
                    authority.SetRole(command.Identity, command.Role);
                    foreach (ZNetPeer peer in ZNet.instance.GetPeers())
                        if (peer != null && peer.m_rpc != null && states.TryGetValue(peer.m_rpc, out PeerState state) && state.Ready) UpdateAuthority(peer, state, true);
                    audit.Add("Hearth", command.Action, Details(command), "Выполнено сервером: роль изменена.");
                    reply(true, "Роль игрока изменена: " + RoleRules.RawName(command.Role) + "."); return;
                }
                if (command.Action == AdminAction.CleanupSpawn)
                {
                    command.Identity = AdminAuthority.Identity(actor); command.BatchId = authority.LastBatch(command.Identity);
                    if (command.BatchId.Length == 0) throw new InvalidOperationException("Нет подтверждённой порции спавна для удаления в этом мире.");
                    string message = SpawnTracker.CleanupBatch(command.Identity, command.BatchId);
                    audit.Add("Hearth", command.Action, Details(command), "Выполнено сервером: " + message); reply(true, message); return;
                }
                bool remoteHelp = command.Action == AdminAction.GodPlayer || command.Action == AdminAction.HealPlayer
                    || command.Action == AdminAction.RestoreStaminaPlayer || command.Action == AdminAction.ClearEffectsPlayer;
                ZDO character = CharacterData(actor);
                if (!remoteHelp && !Alive(character)) throw new InvalidOperationException("Исполнитель ещё не появился в мире или погиб.");
                Vector3 position = Alive(character) ? character.GetPosition() : Vector3.zero;
                ZNetPeer executor = actor;
                switch (command.Action)
                {
                    case AdminAction.TeleportToPlayer:
                        command.Position = CharacterData(SteamPeer(request.TargetSteam, false)).GetPosition() + Vector3.right * 2f + Vector3.up * .3f; break;
                    case AdminAction.SummonPlayer:
                        executor = SteamPeer(request.TargetSteam); command.Position = position + Vector3.right * 2f + Vector3.up * .3f; break;
                    case AdminAction.GodPlayer: case AdminAction.HealPlayer: case AdminAction.RestoreStaminaPlayer: case AdminAction.ClearEffectsPlayer:
                        executor = SteamPeer(request.TargetSteam); command.Position = CharacterData(executor).GetPosition(); break;
                    case AdminAction.SpawnItem: case AdminAction.SpawnMob:
                        ValidatePrefab(command); command.Position = position; break;
                    case AdminAction.TeleportSaved:
                        if (now - actorState.ClientStateAt > 15) throw new InvalidOperationException("Список сохранённых точек устарел. Обновите игроков.");
                        SavedPoint point = actorState.Points.Find(item => item.Id == request.PointId);
                        if (point == null) throw new InvalidOperationException("Сохранённая точка не найдена у исполнителя в этом мире.");
                        command.Position = point.Position; break;
                    case AdminAction.TeleportMap: break;
                    default: command.Position = position; break;
                }
                if (command.Action == AdminAction.HammerStrike)
                {
                    if (!actorState.Hammer) throw new InvalidOperationException("Супермолот не включён сервером.");
                    if (now - actorState.LastHammer < 1f) throw new InvalidOperationException("Подождите секунду между ударами супермолота.");
                    actorState.LastHammer = now;
                }
                if (command.Action == AdminAction.Flatten || command.Action == AdminAction.RaiseTerrain || command.Action == AdminAction.LowerTerrain || command.Action == AdminAction.UndoTerrain)
                {
                    if (now - actorState.LastFlatten < 2f) throw new InvalidOperationException("Подождите две секунды между изменениями земли.");
                    actorState.LastFlatten = now;
                }
                command.Identity = AdminAuthority.Identity(actor); command.Target = executor.m_uid;
                string token = Guid.NewGuid().ToString("N"); command.BatchId = command.Action == AdminAction.SpawnItem || command.Action == AdminAction.SpawnMob ? token : "";
                if (!CommandRules.Valid(command)) throw new InvalidOperationException("Позиция персонажа выходит за допустимые границы мира.");
                if (pending.Count >= 128) throw new InvalidOperationException("Сервер занят. Попробуйте ещё раз через несколько секунд.");
                details = Details(command); PeerState executorState = states[executor.m_rpc];
                audit.Add("Hearth", command.Action, details, "Отправлена клиенту; ожидается подтверждение.");
                pending[token] = new Pending { Requester = actor.m_rpc, Executor = executor.m_rpc, Action = command.Action, Enabled = command.Enabled,
                    Deadline = now + Math.Min(25f, (float)(request.Expires - HearthBridge.Now)), Generation = actorState.Generation,
                    ExecutorGeneration = executorState.Generation, Identity = command.Identity, Actor = "Hearth", Details = details, Batch = command.BatchId,
                    WebReply = reply, WebSession = worldSession, Expires = request.Expires };
                pendingToken = token;
                var package = new ZPackage(); package.Write(ProtocolVersion); package.Write(token); package.Write(worldSession);
                package.Write(executorState.Generation); package.Write((int)Math.Max(1, Math.Min(30000, (request.Expires - HearthBridge.Now) * 1000))); command.Write(package);
                executor.m_rpc.Invoke(WebExecuteRpc, package);
            }
            catch (Exception error)
            {
                if (pendingToken != null) pending.Remove(pendingToken);
                audit.Add("Hearth", command.Action, details, "Отклонено: " + error.Message);
                reply(false, error.Message);
            }
        }

        private void SendClientState()
        {
            if (!Connected || clientConnection == null || !clientConnection.IsConnected() || !ZNet.instance || ZNet.instance.GetWorld() == null) return;
            var points = TeleportHistory.CurrentWorldPoints().Where(PointRules.Valid).Take(100).ToList();
            var package = new ZPackage(); package.Write(ProtocolVersion); package.Write(remoteSession); package.Write(ZNet.instance.GetWorldUID());
            package.Write(WorldActions.GodEnabled); package.Write(WorldActions.FlightEnabled); package.Write(WorldActions.BuildEnabled); package.Write(plugin.HammerEnabled);
            package.Write(TeleportHistory.CanReturn); package.Write(TerrainUndo.HasSnapshot); package.Write(points.Count);
            foreach (SavedPoint point in points) { package.Write(point.Id); package.Write(point.Name); package.Write(point.Position); }
            clientConnection.Invoke(ClientStateRpc, package);
        }

        private void OnClientState(ZRpc rpc, ZPackage package)
        {
            if (Sender(rpc) == null || !states.TryGetValue(rpc, out PeerState state) || !state.Ready || !Packet(package, 65536)) return;
            float now = Time.realtimeSinceStartup;
            if (now - state.LastStatePacket < .2f) return;
            state.LastStatePacket = now;
            try
            {
                if (package.ReadInt() != ProtocolVersion || package.ReadString() != worldSession || package.ReadLong() != worldScope) return;
                bool god = package.ReadBool(), flying = package.ReadBool(), building = package.ReadBool(), hammer = package.ReadBool();
                bool canReturn = package.ReadBool(), canUndo = package.ReadBool(); int count = package.ReadInt();
                if (count < 0 || count > 100) return;
                var points = new List<SavedPoint>(); var ids = new HashSet<string>(StringComparer.Ordinal);
                for (int index = 0; index < count; ++index)
                {
                    var point = new SavedPoint { Id = package.ReadString(), Name = package.ReadString(), Position = package.ReadVector3(), WorldId = worldScope };
                    if (!PointRules.Valid(point) || !ids.Add(point.Id)) return;
                    points.Add(point);
                }
                // Reports are self-reported UI state only, never authority.
                // In particular they cannot arm server-authorized hammer hits.
                state.God = god; state.Flying = flying; state.Building = building;
                if (!hammer) state.Hammer = false;
                state.CanReturn = canReturn; state.CanUndo = canUndo; state.Points = points; state.ClientStateAt = now;
            }
            catch (Exception error) { LogBadPacket("состояние клиента", error); }
        }
    }
#endif
}
