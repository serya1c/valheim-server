using System;
using System.Collections.Generic;
using UnityEngine;

namespace ValheimAdminRu
{
    /// <summary>Privileged messages use the authenticated connection, never a routed sender supplied in a packet.</summary>
    public sealed partial class NetworkService
    {
        private const int ProtocolVersion = 4;
        private const string Prefix = "ValheimAdminRu.";
        private const string HelloRpc = Prefix + "Hello";
        private const string WelcomeRpc = Prefix + "Welcome";
        private const string RefreshRpc = Prefix + "Refresh";
        private const string RosterRpc = Prefix + "Roster";
        private const string RequestRpc = Prefix + "Request";
        private const string ExecuteRpc = Prefix + "Execute";
        private const string AckRpc = Prefix + "Ack";
        private const string ResultRpc = Prefix + "Result";
        private const string AuditRequestRpc = Prefix + "AuditRequest", AuditRpc = Prefix + "Audit";
        private const string BansRequestRpc = Prefix + "BansRequest", BansRpc = Prefix + "Bans";
        private static readonly string[] RpcNames = { HelloRpc, WelcomeRpc, RefreshRpc, RosterRpc, RequestRpc, ExecuteRpc, AckRpc, ResultRpc, AuditRequestRpc, AuditRpc, BansRequestRpc, BansRpc, WebExecuteRpc, ClientStateRpc, WebLeaseRpc };

        private sealed class PeerState
        {
            public bool Ready;
            public AdminRole Role;
            public AdminPermission Permissions;
            public int Generation;
            public bool Hammer;
            public bool God;
            public bool Flying;
            public bool Building;
            public float LastCommand = -100f;
            public float LastHammer = -100f;
            public float LastFlatten = -100f;
            public float LastStatePacket = -100f, ClientStateAt = -100f;
            public bool CanReturn, CanUndo;
            public List<SavedPoint> Points = new List<SavedPoint>();
            public AdminPermission WebEffects;
        }

        private sealed class Pending
        {
            public ZRpc Requester;
            public ZRpc Executor;
            public int RequestId;
            public AdminAction Action;
            public bool Enabled;
            public float Deadline;
            public int Generation;
            public string Identity, Actor, Details, Batch;
            public int ExecutorGeneration;
            public string WebSession;
            public double Expires;
            public Action<bool, string> WebReply;
        }

        private sealed class Receipt
        {
            public bool Success;
            public string Text;
        }

        private readonly Plugin plugin;
        private AdminAuthority authority;
        private AdminAudit audit;
        private readonly HashSet<ZRpc> registered = new HashSet<ZRpc>();
        private readonly Dictionary<ZRpc, PeerState> states = new Dictionary<ZRpc, PeerState>();
        private readonly Dictionary<string, Pending> pending = new Dictionary<string, Pending>();
        private readonly Dictionary<string, Receipt> receipts = new Dictionary<string, Receipt>();
        private ZNet activeNet;
        private ZRpc clientConnection;
        private float nextPoll;
        private float nextHello;
        private float nextRefresh;
        private int nextRequestId;

        public bool Connected { get; private set; }
        public bool AdminAllowed { get; private set; }
        public AdminPermission Permissions { get; private set; }
        public AdminRole MyRole { get; private set; }
        public List<PlayerRow> Players { get; private set; } = new List<PlayerRow>();
        public List<AuditRow> AuditRows { get; private set; } = new List<AuditRow>();
        public List<BanRow> BannedPlayers { get; private set; } = new List<BanRow>();
        public long MyId { get; private set; }
        public bool Allowed(AdminPermission permission) { return Connected && permission != AdminPermission.None && (Permissions & permission) == permission; }

        public NetworkService(Plugin plugin) { this.plugin = plugin; bridge = new HearthBridge(plugin, this); }

        public void Tick()
        {
            ZNet net = ZNet.instance;
            if (!net)
            {
                if (!ReferenceEquals(activeNet, null) || registered.Count > 0 || Connected) Reset();
                return;
            }
            if (!ReferenceEquals(activeNet, net))
            {
                Reset();
                activeNet = net;
                if (net.IsServer()) { authority = new AdminAuthority(plugin); audit = new AdminAudit(plugin); worldSession = Guid.NewGuid().ToString("N"); }
            }
            float now = Time.realtimeSinceStartup;
            if (net.IsServer()) { BridgeTick(net); CheckPending(now); }
            else CheckWebEffects(now);
            if (now < nextPoll) return;
            nextPoll = now + .5f;

            List<ZNetPeer> peers = new List<ZNetPeer>(net.GetPeers());
            HashSet<ZRpc> live = new HashSet<ZRpc>();
            foreach (ZNetPeer peer in peers)
            {
                if (peer == null || peer.m_rpc == null || !peer.IsReady() || !peer.m_rpc.IsConnected()) continue;
                live.Add(peer.m_rpc);
                Register(peer.m_rpc, net.IsServer());
                if (net.IsServer() && states.TryGetValue(peer.m_rpc, out PeerState state) && state.Ready)
                {
                    UpdateAuthority(peer, state, true);
                }
            }
            foreach (ZRpc rpc in new List<ZRpc>(registered))
            {
                if (live.Contains(rpc)) continue;
                Unregister(rpc);
                registered.Remove(rpc);
                states.Remove(rpc);
            }

            if (net.IsServer()) return;
            ZNetPeer server = net.GetServerPeer();
            ZRpc connection = server != null && server.IsReady() && server.m_server ? server.m_rpc : null;
            if (!ReferenceEquals(connection, clientConnection))
            {
                clientConnection = connection;
                Connected = false;
                AdminAllowed = false;
                Permissions = AdminPermission.None; MyRole = AdminRole.None;
                MyId = 0;
                Players.Clear();
                AuditRows.Clear(); BannedPlayers.Clear();
                receipts.Clear();
                ClearWebEffects(); remoteSession = ""; remoteWorld = 0; remoteGeneration = 0; nextClientState = 0;
                plugin.HammerEnabled = false;
                WorldActions.Reset();
                nextHello = 0;
            }
            if (connection == null || !connection.IsConnected()) return;
            if (!Connected && now >= nextHello)
            {
                nextHello = now + 3f;
                ZPackage package = new ZPackage();
                package.Write(ProtocolVersion);
                package.Write(Plugin.ModVersion);
                package.Write(global::Version.CurrentVersion.ToString());
                connection.Invoke(HelloRpc, package);
            }
            if (Connected && now >= nextRefresh)
            {
                nextRefresh = now + 5f;
                Refresh();
            }
            if (Connected && now >= nextClientState) { nextClientState = now + 5f; SendClientState(); }
        }

        public void Reset()
        {
            foreach (Pending execution in new List<Pending>(pending.Values))
                if (execution.WebReply != null) Complete(execution, false, "Игровая сессия завершилась; команда не будет повторена.");
            bridge?.Suspend();
            foreach (ZRpc rpc in registered) Unregister(rpc);
            registered.Clear();
            states.Clear();
            pending.Clear();
            receipts.Clear();
            Players.Clear();
            AuditRows.Clear(); BannedPlayers.Clear();
            authority = null; audit = null;
            activeNet = null;
            clientConnection = null;
            Connected = false;
            AdminAllowed = false;
            Permissions = AdminPermission.None; MyRole = AdminRole.None;
            MyId = 0;
            nextPoll = nextHello = nextRefresh = 0;
            ClearWebEffects(); worldScope = remoteWorld = 0; worldSession = remoteSession = ""; nextClientState = nextWebLease = 0;
            plugin.HammerEnabled = false;
            WorldActions.Reset();
        }

        public void Send(AdminCommand command)
        {
            if (command == null || !Allowed(Required(command.Action)) || clientConnection == null || !clientConnection.IsConnected())
            {
                plugin.Notify("Нет доступа: ваша роль не разрешает эту команду.");
                return;
            }
            if (!CommandRules.Valid(command))
            {
                plugin.Notify("Недопустимые параметры команды.");
                return;
            }
            command.Id = ++nextRequestId;
            ZPackage package = new ZPackage();
            package.Write(ProtocolVersion);
            command.Write(package);
            clientConnection.Invoke(RequestRpc, package);
        }

        public void Refresh()
        {
            if (!Connected || clientConnection == null || !clientConnection.IsConnected()) return;
            ZPackage package = new ZPackage();
            package.Write(ProtocolVersion);
            clientConnection.Invoke(RefreshRpc, package);
        }

        public void RefreshAudit() { Fetch(AuditRequestRpc, AdminPermission.Audit); }
        public void RefreshBans() { Fetch(BansRequestRpc, AdminPermission.Moderate); }
        private void Fetch(string name, AdminPermission permission)
        {
            if (!Allowed(permission) || clientConnection == null || !clientConnection.IsConnected()) return;
            var package = new ZPackage(); package.Write(ProtocolVersion); clientConnection.Invoke(name, package);
        }

        private void Register(ZRpc rpc, bool server)
        {
            if (!registered.Add(rpc)) return;
            if (server)
            {
                states[rpc] = new PeerState();
                rpc.Register<ZPackage>(HelloRpc, OnHello);
                rpc.Register<ZPackage>(RefreshRpc, OnRefresh);
                rpc.Register<ZPackage>(RequestRpc, OnRequest);
                rpc.Register<ZPackage>(AckRpc, OnAck);
                rpc.Register<ZPackage>(AuditRequestRpc, OnAuditRequest);
                rpc.Register<ZPackage>(BansRequestRpc, OnBansRequest);
                rpc.Register<ZPackage>(ClientStateRpc, OnClientState);
            }
            else
            {
                rpc.Register<ZPackage>(WelcomeRpc, OnWelcome);
                rpc.Register<ZPackage>(RosterRpc, OnRoster);
                rpc.Register<ZPackage>(ExecuteRpc, OnExecute);
                rpc.Register<ZPackage>(ResultRpc, OnResult);
                rpc.Register<ZPackage>(AuditRpc, OnAudit);
                rpc.Register<ZPackage>(BansRpc, OnBans);
                rpc.Register<ZPackage>(WebExecuteRpc, OnWebExecute);
                rpc.Register<ZPackage>(WebLeaseRpc, OnWebLease);
            }
        }

        private static void Unregister(ZRpc rpc)
        {
            if (rpc == null) return;
            foreach (string name in RpcNames) rpc.Unregister(name);
        }

        private ZNetPeer Sender(ZRpc rpc)
        {
            ZNet net = ZNet.instance;
            if (!net || !net.IsServer() || rpc == null) return null;
            foreach (ZNetPeer peer in net.GetPeers())
                if (peer != null && peer.IsReady() && ReferenceEquals(peer.m_rpc, rpc) && rpc.IsConnected()) return peer;
            return null;
        }

        private bool FromServer(ZRpc rpc)
        {
            ZNet net = ZNet.instance;
            if (!net || net.IsServer() || rpc == null || !rpc.IsConnected()) return false;
            ZNetPeer peer = net.GetServerPeer();
            return peer != null && peer.IsReady() && peer.m_server && ReferenceEquals(peer.m_rpc, rpc)
                && ReferenceEquals(net.GetServerRPC(), rpc);
        }

        private static bool IsAdmin(ZNetPeer peer)
        {
            if (!ZNet.instance || peer == null || peer.m_socket == null) return false;
            string identity = peer.m_socket.GetHostName();
            return !string.IsNullOrEmpty(identity) && ZNet.instance.IsAdmin(identity);
        }

        private static AdminPermission Required(AdminAction action) { return RoleRules.Required(action); }
        private static bool Has(PeerState state, AdminPermission permission) { return permission != AdminPermission.None && (state.Permissions & permission) == permission; }
        private void UpdateAuthority(ZNetPeer peer, PeerState state, bool notify)
        {
            AdminRole role = authority.Role(peer);
            AdminPermission permissions = RoleRules.Permissions(role);
            bool changed = state.Role != role || state.Permissions != permissions;
            bool reduced = (permissions & state.Permissions) != state.Permissions;
            state.Role = role; state.Permissions = permissions;
            if (reduced)
            {
                ++state.Generation;
                state.WebEffects = AdminPermission.None;
                state.Hammer = state.God = state.Flying = state.Building = false;
                foreach (var entry in new List<KeyValuePair<string, Pending>>(pending))
                {
                    if (!ReferenceEquals(entry.Value.Requester, peer.m_rpc) && !(entry.Value.WebReply != null && ReferenceEquals(entry.Value.Executor, peer.m_rpc))) continue;
                    pending.Remove(entry.Key);
                    Complete(entry.Value, false, "Права изменились до подтверждения команды; результат не подтверждён.");
                }
            }
            if (changed && notify && state.Ready) { Welcome(peer, state); SendRoster(peer.m_rpc); }
        }

        private void ApplyRights(AdminRole role, AdminPermission permissions)
        {
            if (!Enum.IsDefined(typeof(AdminRole), role) || RoleRules.Permissions(role) != permissions)
                throw new InvalidOperationException("Сервер передал недопустимые права.");
            bool reduced = (permissions & Permissions) != Permissions;
            Permissions = permissions; MyRole = role; AdminAllowed = permissions != AdminPermission.None;
            if (reduced) { ClearWebEffects(); plugin.HammerEnabled = false; WorldActions.Reset(); }
            if (!AdminAllowed) Players.Clear();
            if ((permissions & AdminPermission.Audit) == 0) AuditRows.Clear();
            if ((permissions & AdminPermission.Moderate) == 0) BannedPlayers.Clear();
        }

        private static bool Packet(ZPackage package, int maximum)
        {
            return package != null && package.Size() >= 4 && package.Size() <= maximum;
        }

        private void OnHello(ZRpc rpc, ZPackage package)
        {
            ZNetPeer peer = Sender(rpc);
            if (peer == null || !states.TryGetValue(rpc, out PeerState state) || !Packet(package, 512)) return;
            try
            {
                string serverGame = global::Version.CurrentVersion.ToString();
                int protocol = package.ReadInt();
                string clientMod = package.ReadString(), clientGame = package.ReadString();
                if (!Plugin.SupportsGameVersion(serverGame) || protocol != ProtocolVersion || clientMod != Plugin.ModVersion || clientGame != serverGame)
                {
                    state.Ready = false; state.Role = AdminRole.None; state.Permissions = AdminPermission.None;
                    state.Hammer = state.God = state.Flying = state.Building = false;
                    Result(rpc, 0, false, !Plugin.SupportsGameVersion(serverGame)
                        ? "Версия Valheim на сервере " + serverGame + " не поддерживается модом. Поддерживаются 1.0.16 и " + Plugin.GameVersion + "."
                        : "Версии клиента и сервера должны совпадать. Требуются мод " + Plugin.ModVersion + " и Valheim " + serverGame
                            + " (версия сервера). На клиенте: мод " + clientMod + ", Valheim " + clientGame + ".");
                    return;
                }
                state.Ready = true;
                UpdateAuthority(peer, state, false);
                Welcome(peer, state);
                SendRoster(rpc);
            }
            catch (Exception e) { LogBadPacket("рукопожатие", e); }
        }

        private void Welcome(ZNetPeer peer, PeerState state)
        {
            ZPackage package = new ZPackage();
            package.Write(ProtocolVersion);
            package.Write(Plugin.ModVersion);
            package.Write(global::Version.CurrentVersion.ToString());
            package.Write(peer.m_uid);
            package.Write((int)state.Role); package.Write((int)state.Permissions);
            package.Write(worldSession); package.Write(state.Generation); package.Write(worldScope);
            peer.m_rpc.Invoke(WelcomeRpc, package);
        }

        private void OnWelcome(ZRpc rpc, ZPackage package)
        {
            if (!FromServer(rpc) || !Packet(package, 512)) return;
            try
            {
                string clientGame = global::Version.CurrentVersion.ToString();
                int protocol = package.ReadInt();
                string serverMod = package.ReadString(), serverGame = package.ReadString();
                if (!Plugin.SupportsGameVersion(clientGame))
                    throw new InvalidOperationException("Версия Valheim на клиенте " + clientGame + " не поддерживается модом. Поддерживаются 1.0.16 и " + Plugin.GameVersion + ".");
                if (protocol != ProtocolVersion || serverMod != Plugin.ModVersion || serverGame != clientGame)
                    throw new InvalidOperationException("Версии клиента и сервера должны совпадать. Требуются мод " + Plugin.ModVersion + " и Valheim " + clientGame
                        + " (версия клиента). На сервере: мод " + serverMod + ", Valheim " + serverGame + ".");
                long id = package.ReadLong();
                AdminRole role = (AdminRole)package.ReadInt();
                AdminPermission permissions = (AdminPermission)package.ReadInt();
                string session = package.ReadString(); int generation = package.ReadInt(); long world = package.ReadLong();
                if (!Guid.TryParseExact(session, "N", out Guid sessionId) || generation < 0) return;
                if (remoteSession != session || remoteGeneration != generation || remoteWorld != world)
                { ClearWebEffects(); WorldActions.Reset(); plugin.HammerEnabled = false; receipts.Clear(); nextClientState = 0; }
                remoteSession = session; remoteGeneration = generation; remoteWorld = world;
                if (id == 0) return;
                bool changed = !Connected || MyRole != role || Permissions != permissions;
                ApplyRights(role, permissions);
                clientConnection = rpc;
                MyId = id;
                Connected = true;
                nextRefresh = 0;
                if (changed) plugin.Notify(AdminAllowed ? "Админ-панель подключена. Роль: " + RoleRules.RawName(role) + "." : "Мод подключён. Доступ к панели не назначен владельцем сервера.");
            }
            catch (Exception e) { plugin.Notify(e.Message); }
        }

        private void OnRefresh(ZRpc rpc, ZPackage package)
        {
            if (Sender(rpc) == null || !states.TryGetValue(rpc, out PeerState state) || !state.Ready || !Packet(package, 16)) return;
            try { if (package.ReadInt() == ProtocolVersion) SendRoster(rpc); }
            catch (Exception e) { LogBadPacket("список игроков", e); }
        }

        private static ZDO CharacterData(ZNetPeer peer)
        {
            if (peer == null || peer.m_characterID.IsNone() || ZDOMan.instance == null) return null;
            return ZDOMan.instance.GetZDO(peer.m_characterID);
        }

        private static bool Alive(ZDO character)
        {
            return character != null && !character.GetBool(ZDOVars.s_dead, false);
        }

        private void SendRoster(ZRpc rpc)
        {
            ZNetPeer requester = Sender(rpc);
            if (requester == null) return;
            if (!states.TryGetValue(rpc, out PeerState requesterState) || !requesterState.Ready) return;
            UpdateAuthority(requester, requesterState, false);
            bool allowed = requesterState.Permissions != AdminPermission.None;
            List<PlayerRow> rows = new List<PlayerRow>();
            if (allowed)
            {
                foreach (ZNetPeer peer in ZNet.instance.GetPeers())
                {
                    if (peer == null || !peer.IsReady() || peer.m_rpc == null || !peer.m_rpc.IsConnected()) continue;
                    states.TryGetValue(peer.m_rpc, out PeerState state);
                    AdminRole role = authority.Role(peer);
                    rows.Add(new PlayerRow { Id = peer.m_uid, Name = Trim(peer.m_playerName ?? "Игрок", 256), HasMod = state != null && state.Ready,
                        Alive = Alive(CharacterData(peer)), God = state != null && state.God, Flying = state != null && state.Flying,
                        Identity = AdminAuthority.Identity(peer), Role = role, Permissions = RoleRules.Permissions(role), Building = state != null && state.Building });
                }
            }
            ZPackage package = new ZPackage();
            package.Write(ProtocolVersion);
            package.Write((int)requesterState.Role); package.Write((int)requesterState.Permissions);
            package.Write(rows.Count);
            foreach (PlayerRow row in rows)
            {
                package.Write(row.Id); package.Write(row.Name); package.Write(row.HasMod); package.Write(row.Alive); package.Write(row.God); package.Write(row.Flying);
                package.Write(row.Identity); package.Write((int)row.Role); package.Write((int)row.Permissions); package.Write(row.Building);
            }
            rpc.Invoke(RosterRpc, package);
        }

        private void OnRoster(ZRpc rpc, ZPackage package)
        {
            if (!Connected || !FromServer(rpc) || !Packet(package, 65536)) return;
            try
            {
                if (package.ReadInt() != ProtocolVersion) return;
                AdminRole role = (AdminRole)package.ReadInt(); AdminPermission permissions = (AdminPermission)package.ReadInt();
                int count = package.ReadInt();
                if (count < 0 || count > 100) return;
                List<PlayerRow> rows = new List<PlayerRow>();
                for (int i = 0; i < count; ++i)
                {
                    PlayerRow row = new PlayerRow { Id = package.ReadLong(), Name = package.ReadString(), HasMod = package.ReadBool(), Alive = package.ReadBool(), God = package.ReadBool(), Flying = package.ReadBool() };
                    row.Identity = package.ReadString(); row.Role = (AdminRole)package.ReadInt(); row.Permissions = (AdminPermission)package.ReadInt(); row.Building = package.ReadBool();
                    if (row.Name.Length > 256 || row.Identity.Length > 128 || !Enum.IsDefined(typeof(AdminRole), row.Role) || RoleRules.Permissions(row.Role) != row.Permissions) return;
                    rows.Add(row);
                }
                ApplyRights(role, permissions);
                Players = AdminAllowed ? rows : new List<PlayerRow>();
            }
            catch (Exception e) { LogBadPacket("ответ со списком игроков", e); }
        }

        private void OnRequest(ZRpc rpc, ZPackage package)
        {
            ZNetPeer requester = Sender(rpc);
            if (requester == null || !states.TryGetValue(rpc, out PeerState requesterState) || !requesterState.Ready || !Packet(package, 4096)) return;
            int requestId = 0;
            AdminCommand command = null;
            string actor = (requester.m_playerName ?? "Игрок") + " [" + AdminAuthority.Identity(requester) + "]";
            string details = "";
            try
            {
                if (package.ReadInt() != ProtocolVersion) return;
                command = AdminCommand.Read(package); requestId = command.Id;
                UpdateAuthority(requester, requesterState, true);
                float now = Time.realtimeSinceStartup;
                if (now - requesterState.LastCommand < .3f)
                {
                    Result(rpc, requestId, false, "Подождите перед следующей командой.");
                    return;
                }
                requesterState.LastCommand = now;
                if (!CommandRules.Valid(command)) throw new InvalidOperationException("Сервер отклонил недопустимые параметры команды.");
                details = Details(command);
                if (!Has(requesterState, Required(command.Action)))
                    throw new InvalidOperationException("Команда отклонена сервером: ваша роль не разрешает это действие.");
                if (ServerAction(requester, requesterState, command, out string serverResult))
                {
                    audit.Add(actor, command.Action, Details(command), "Выполнено сервером: " + serverResult);
                    Result(rpc, requestId, true, serverResult);
                    SendRoster(rpc);
                    return;
                }
                if (command.Action == AdminAction.HammerStrike)
                {
                    if (!requesterState.Hammer) throw new InvalidOperationException("Супермолот не включён сервером.");
                    if (now - requesterState.LastHammer < 1f) throw new InvalidOperationException("Подождите секунду между ударами супермолота.");
                    requesterState.LastHammer = now;
                }
                if (command.Action == AdminAction.Flatten || command.Action == AdminAction.RaiseTerrain || command.Action == AdminAction.LowerTerrain || command.Action == AdminAction.UndoTerrain)
                {
                    if (now - requesterState.LastFlatten < 2f) throw new InvalidOperationException("Подождите две секунды между изменениями земли.");
                    requesterState.LastFlatten = now;
                }
                ZDO requesterCharacter = CharacterData(requester);
                // Remote assistance and moderation do not depend on the admin's living avatar.
                bool remoteHelp = command.Action == AdminAction.GodPlayer || command.Action == AdminAction.HealPlayer
                    || command.Action == AdminAction.RestoreStaminaPlayer || command.Action == AdminAction.ClearEffectsPlayer;
                if (!remoteHelp && !Alive(requesterCharacter)) throw new InvalidOperationException("Ваш персонаж ещё не появился в мире или погиб.");
                Vector3 requesterPosition = Alive(requesterCharacter) ? requesterCharacter.GetPosition() : Vector3.zero;
                ZNetPeer executor = requester;
                switch (command.Action)
                {
                    case AdminAction.TeleportToPlayer:
                        command.Position = CharacterData(Target(command.Target, false)).GetPosition() + Vector3.right * 2f + Vector3.up * .3f;
                        break;
                    case AdminAction.SummonPlayer:
                        executor = Target(command.Target); command.Position = requesterPosition + Vector3.right * 2f + Vector3.up * .3f;
                        break;
                    case AdminAction.GodPlayer: case AdminAction.HealPlayer:
                    case AdminAction.RestoreStaminaPlayer: case AdminAction.ClearEffectsPlayer:
                        executor = Target(command.Target); command.Position = CharacterData(executor).GetPosition();
                        break;
                    case AdminAction.SpawnItem: case AdminAction.SpawnMob:
                        ValidatePrefab(command); command.Position = requesterPosition;
                        break;
                    case AdminAction.Flatten: case AdminAction.RaiseTerrain: case AdminAction.LowerTerrain:
                    case AdminAction.UndoTerrain: case AdminAction.HammerStrike: case AdminAction.FlySelf:
                    case AdminAction.BuildToggle: case AdminAction.RepairArea: case AdminAction.ReturnTeleport:
                        command.Position = requesterPosition;
                        break;
                }
                command.Identity = AdminAuthority.Identity(requester);
                command.BatchId = "";
                if (!CommandRules.Valid(command)) throw new InvalidOperationException("Позиция персонажа выходит за допустимые границы мира.");
                command.Target = executor.m_uid;
                if (pending.Count >= 128) throw new InvalidOperationException("Сервер занят. Попробуйте ещё раз через несколько секунд.");
                string token = Guid.NewGuid().ToString("N");
                if (command.Action == AdminAction.SpawnItem || command.Action == AdminAction.SpawnMob) command.BatchId = token;
                details = Details(command);
                audit.Add(actor, command.Action, details, "Отправлена клиенту; ожидается подтверждение.");
                pending[token] = new Pending { Requester = rpc, Executor = executor.m_rpc, RequestId = requestId, Action = command.Action,
                    Enabled = command.Enabled, Deadline = now + 25f, Generation = requesterState.Generation,
                    Identity = command.Identity, Actor = actor, Details = details, Batch = command.BatchId };
                ZPackage execution = new ZPackage(); execution.Write(ProtocolVersion); execution.Write(token); command.Write(execution);
                executor.m_rpc.Invoke(ExecuteRpc, execution);
            }
            catch (Exception e)
            {
                if (command != null && Enum.IsDefined(typeof(AdminAction), command.Action)) audit.Add(actor, command.Action, details, "Отклонено: " + e.Message);
                Result(rpc, requestId, false, e.Message);
            }
        }

        private static string Details(AdminCommand command)
        {
            return "цель=" + command.Target + "; объект=" + command.Prefab + "; количество=" + command.Count
                + "; радиус=" + command.Radius + "; высота=" + command.Height + "; включено=" + (command.Enabled ? "да" : "нет")
                + "; категории=" + HammerCategories(command.HammerTargets)
                + "; позиция=" + command.Position.x + "," + command.Position.y + "," + command.Position.z
                + "; ID=" + command.Identity + "; роль=" + RoleRules.RawName(command.Role) + "; причина=" + command.Text;
        }

        private static string HammerCategories(HammerTargets targets)
        {
            var names = new List<string>();
            if ((targets & HammerTargets.Mobs) != 0) names.Add("мобы");
            if ((targets & HammerTargets.Trees) != 0) names.Add("деревья");
            if ((targets & HammerTargets.Ore) != 0) names.Add("руда");
            if ((targets & HammerTargets.Structures) != 0) names.Add("постройки");
            return names.Count == 0 ? "нет" : string.Join(", ", names);
        }

        private bool ServerAction(ZNetPeer requester, PeerState state, AdminCommand command, out string message)
        {
            message = "";
            switch (command.Action)
            {
                case AdminAction.KickPlayer: case AdminAction.BanPlayer:
                {
                    ZNetPeer target = Target(command.Target, false, false);
                    AdminRole targetRole = authority.Role(target);
                    if (ReferenceEquals(target, requester) || AdminAuthority.Identity(target) == AdminAuthority.Identity(requester))
                        throw new InvalidOperationException("Нельзя отключить или заблокировать себя.");
                    if (targetRole == AdminRole.Owner || (state.Role == AdminRole.Moderator && targetRole == AdminRole.Moderator))
                        throw new InvalidOperationException("Владелец защищён от модерации; модератор не может отключить другого модератора.");
                    command.Identity = AdminAuthority.Identity(target);
                    if (command.Action == AdminAction.BanPlayer) authority.Ban(target, command.Text);
                    else AdminAuthority.Kick(target);
                    message = command.Action == AdminAction.BanPlayer ? "Игрок заблокирован." : "Команда отключения игрока отправлена сервером.";
                    return true;
                }
                case AdminAction.UnbanPlayer:
                    authority.Unban(command.Identity); message = "Блокировка снята."; return true;
                case AdminAction.SetRole:
                {
                    ZNetPeer target = Target(command.Target, false, false);
                    if (AdminAuthority.Identity(target) == AdminAuthority.Identity(requester)) throw new InvalidOperationException("Нельзя изменить собственную роль.");
                    if (IsAdmin(target)) throw new InvalidOperationException("Владельцы из adminlist.txt сохраняют полный доступ.");
                    if (command.Role == AdminRole.Owner) throw new InvalidOperationException("Владельца назначают только через adminlist.txt сервера.");
                    command.Identity = AdminAuthority.Identity(target);
                    authority.SetRole(command.Identity, command.Role);
                    foreach (ZNetPeer peer in ZNet.instance.GetPeers())
                        if (peer != null && peer.m_rpc != null && states.TryGetValue(peer.m_rpc, out PeerState other) && other.Ready) UpdateAuthority(peer, other, true);
                    message = "Роль игрока изменена: " + RoleRules.RawName(command.Role) + ".";
                    return true;
                }
                case AdminAction.CleanupSpawn:
                {
                    command.Identity = AdminAuthority.Identity(requester); command.BatchId = authority.LastBatch(command.Identity);
                    if (command.BatchId.Length == 0) throw new InvalidOperationException("Нет подтверждённой порции спавна для удаления в этом мире.");
                    message = SpawnTracker.CleanupBatch(command.Identity, command.BatchId);
                    // The acknowledgement can arrive before tagged ZDOs replicate to the server.
                    // Retain this exact batch so a retry can remove delayed or unloaded objects.
                    return true;
                }
                default: return false;
            }
        }
        private ZNetPeer Target(long id, bool requireMod = true, bool requireAlive = true)
        {
            ZNetPeer peer = ZNet.instance.GetPeer(id);
            if (peer == null || !peer.IsReady() || peer.m_rpc == null || !peer.m_rpc.IsConnected())
                throw new InvalidOperationException("Выбранный игрок уже отключился от сервера.");
            if (requireMod && (!states.TryGetValue(peer.m_rpc, out PeerState state) || !state.Ready))
                throw new InvalidOperationException("У выбранного игрока не установлен совместимый мод ValheimAdminRu.");
            if (requireAlive && !Alive(CharacterData(peer))) throw new InvalidOperationException("Выбранный игрок ещё не появился в мире или погиб.");
            return peer;
        }

        private static void ValidatePrefab(AdminCommand command)
        {
            if (!ZNetScene.instance) throw new InvalidOperationException("Сервер ещё загружает игровые объекты.");
            GameObject prefab = ZNetScene.instance.GetPrefab(command.Prefab);
            if (!prefab) throw new InvalidOperationException("Такого игрового объекта нет на сервере.");
            if (command.Action == AdminAction.SpawnItem && !prefab.GetComponent<ItemDrop>())
                throw new InvalidOperationException("Выбранный объект не является предметом.");
            if (command.Action == AdminAction.SpawnMob && (!prefab.GetComponent<Character>() || prefab.GetComponent<Player>() || !prefab.GetComponent<BaseAI>()))
                throw new InvalidOperationException("Выбранный объект не является существом.");
        }

        private void OnExecute(ZRpc rpc, ZPackage package)
        { ReceiveExecute(rpc, package, false); }

        private void OnWebExecute(ZRpc rpc, ZPackage package)
        { ReceiveExecute(rpc, package, true); }

        private void ReceiveExecute(ZRpc rpc, ZPackage package, bool web)
        {
            if (!Connected || !FromServer(rpc) || !Packet(package, 4096)) return;
            string token = null;
            AdminPermission previousEffects = trustedEffects;
            try
            {
                if (package.ReadInt() != ProtocolVersion) return;
                token = package.ReadString();
                if (!Guid.TryParseExact(token, "N", out Guid ignored)) return;
                if (web)
                {
                    string session = package.ReadString(); int generation = package.ReadInt(), ttl = package.ReadInt();
                    if (session != remoteSession || generation != remoteGeneration || !ClientWorldMatches()
                        || ttl <= 0 || ttl > 30000)
                        throw new InvalidOperationException("Игровая сессия завершилась; команда не будет повторена.");
                }
                if (receipts.TryGetValue(token, out Receipt previous))
                {
                    Acknowledge(rpc, token, previous);
                    return;
                }
                AdminCommand command = AdminCommand.Read(package);
                if (!CommandRules.Valid(command) || command.Target != MyId)
                    throw new InvalidOperationException("Получена недопустимая команда сервера.");
                if (command.Action == AdminAction.KickPlayer || command.Action == AdminAction.BanPlayer || command.Action == AdminAction.UnbanPlayer
                    || command.Action == AdminAction.SetRole || command.Action == AdminAction.CleanupSpawn)
                    throw new InvalidOperationException("Эту команду выполняет только сервер.");
                bool delegatedHelp = command.Action == AdminAction.GodPlayer || command.Action == AdminAction.HealPlayer
                    || command.Action == AdminAction.RestoreStaminaPlayer || command.Action == AdminAction.ClearEffectsPlayer || command.Action == AdminAction.SummonPlayer;
                if (!web && !delegatedHelp && !Allowed(Required(command.Action))) throw new InvalidOperationException("Права на выполнение команды изменились.");
                if (web)
                {
                    AdminPermission effect = PersistentEffect(command.Action);
                    if (effect != AdminPermission.None)
                    { trustedEffects = command.Enabled ? trustedEffects | effect : trustedEffects & ~effect; trustedUntil = Time.realtimeSinceStartup + 7f; }
                }
                string message = WorldActions.Execute(command);
                Receipt receipt = new Receipt { Success = true, Text = message ?? "Команда выполнена." };
                Remember(token, receipt);
                Acknowledge(rpc, token, receipt);
                if (web) SendClientState();
            }
            catch (Exception e)
            {
                if (web) trustedEffects = previousEffects;
                if (token == null || !Guid.TryParseExact(token, "N", out Guid ignored)) return;
                Receipt receipt = new Receipt { Success = false, Text = e.Message };
                Remember(token, receipt);
                Acknowledge(rpc, token, receipt);
            }
        }

        private void Remember(string token, Receipt receipt)
        {
            if (receipts.Count >= 128) receipts.Clear();
            receipts[token] = receipt;
        }

        private static void Acknowledge(ZRpc rpc, string token, Receipt receipt)
        {
            ZPackage package = new ZPackage();
            package.Write(ProtocolVersion); package.Write(token); package.Write(receipt.Success); package.Write(Trim(receipt.Text, 1000));
            rpc.Invoke(AckRpc, package);
        }

        private void OnAck(ZRpc rpc, ZPackage package)
        {
            if (Sender(rpc) == null || !states.TryGetValue(rpc, out PeerState state) || !state.Ready || !Packet(package, 4096)) return;
            try
            {
                if (package.ReadInt() != ProtocolVersion) return;
                string token = package.ReadString();
                bool success = package.ReadBool();
                string message = package.ReadString();
                if (token.Length != 32 || message.Length > 1000 || !pending.TryGetValue(token, out Pending execution)
                    || !ReferenceEquals(execution.Executor, rpc)) return;
                pending.Remove(token);
                if (Time.realtimeSinceStartup >= execution.Deadline)
                { Complete(execution, false, "Срок подтверждения команды истёк; проверьте результат перед повтором."); return; }
                ZNetPeer requester = Sender(execution.Requester);
                bool stillAllowed = false;
                if (requester != null && states.TryGetValue(execution.Requester, out PeerState requesterState))
                {
                    UpdateAuthority(requester, requesterState, true);
                    stillAllowed = execution.Generation == requesterState.Generation && (execution.WebReply != null || Has(requesterState, Required(execution.Action)));
                }
                if (!stillAllowed) { Complete(execution, false, "Права изменились до подтверждения команды; результат не подтверждён."); return; }
                UpdateAuthority(Sender(rpc), state, true);
                bool web = execution.WebReply != null;
                if (web && (execution.WebSession != worldSession || execution.Expires <= HearthBridge.Now
                    || execution.ExecutorGeneration != state.Generation || !bridge.Healthy))
                { Complete(execution, false, "Игровая сессия завершилась; результат команды не подтверждён."); return; }
                if (success)
                {
                    if (execution.Action == AdminAction.HammerToggle) state.Hammer = execution.Enabled && (web || Has(state, AdminPermission.Hammer));
                    if (execution.Action == AdminAction.GodSelf) state.God = execution.Enabled && (web || Has(state, AdminPermission.Help));
                    if (execution.Action == AdminAction.GodPlayer) state.God = execution.Enabled;
                    if (execution.Action == AdminAction.FlySelf) state.Flying = execution.Enabled && (web || Has(state, AdminPermission.Travel));
                    if (execution.Action == AdminAction.BuildToggle) state.Building = execution.Enabled && (web || Has(state, AdminPermission.Build));
                    AdminPermission effect = PersistentEffect(execution.Action);
                    if (effect != AdminPermission.None)
                    {
                        if (web && execution.Enabled) state.WebEffects |= effect;
                        else state.WebEffects &= ~effect;
                    }
                    if (execution.Action == AdminAction.SpawnItem || execution.Action == AdminAction.SpawnMob) authority.RecordBatch(execution.Identity, execution.Batch);
                }
                Complete(execution, success, message);
                if (web) SendWebLease(Sender(rpc), state);
            }
            catch (Exception e) { LogBadPacket("подтверждение выполнения", e); }
        }

        private void CheckPending(float now)
        {
            foreach (KeyValuePair<string, Pending> entry in new List<KeyValuePair<string, Pending>>(pending))
            {
                Pending execution = entry.Value;
                if (now < execution.Deadline && Sender(execution.Executor) != null && Sender(execution.Requester) != null
                    && (execution.WebReply == null || execution.WebSession == worldSession && execution.Expires > HearthBridge.Now && bridge.Healthy)) continue;
                pending.Remove(entry.Key);
                Complete(execution, false, "Сервер не получил подтверждение от клиента. Результат команды не подтверждён; проверьте его перед повтором.");
            }
        }

        private void Complete(Pending execution, bool success, string message)
        {
            audit?.Add(execution.Actor, execution.Action, execution.Details, (success ? "Подтверждено клиентом: " : "Не подтверждено / ошибка: ") + message);
            if (execution.WebReply != null) { execution.WebReply(success, message); return; }
            Result(execution.Requester, execution.RequestId, success, message);
            SendRoster(execution.Requester);
        }

        private bool FetchAllowed(ZRpc rpc, ZPackage package, AdminPermission permission)
        {
            ZNetPeer peer = Sender(rpc);
            if (peer == null || !states.TryGetValue(rpc, out PeerState state) || !state.Ready || !Packet(package, 16)) return false;
            if (package.ReadInt() != ProtocolVersion) return false;
            UpdateAuthority(peer, state, true);
            return Has(state, permission);
        }

        private void OnAuditRequest(ZRpc rpc, ZPackage package)
        {
            try
            {
                if (!FetchAllowed(rpc, package, AdminPermission.Audit)) return;
                var rows = audit.Recent(); var response = new ZPackage(); response.Write(ProtocolVersion); response.Write(rows.Count);
                foreach (AuditRow row in rows) { response.Write(row.TimeUtc); response.Write(row.Actor); response.Write(row.Action); response.Write(row.Details); response.Write(row.Result); }
                rpc.Invoke(AuditRpc, response);
            }
            catch (Exception e) { LogBadPacket("запрос журнала", e); }
        }
        private void OnAudit(ZRpc rpc, ZPackage package)
        {
            if (!Allowed(AdminPermission.Audit) || !FromServer(rpc) || !Packet(package, 2097152)) return;
            try
            {
                if (package.ReadInt() != ProtocolVersion) return;
                int count = package.ReadInt(); if (count < 0 || count > AdminAudit.Maximum) return;
                var rows = new List<AuditRow>();
                for (int i = 0; i < count; ++i)
                {
                    var row = new AuditRow { TimeUtc = package.ReadString(), Actor = package.ReadString(), Action = package.ReadString(), Details = package.ReadString(), Result = package.ReadString() };
                    if (row.TimeUtc.Length > 64 || row.Actor.Length > 256 || row.Action.Length > 100 || row.Details.Length > 600 || row.Result.Length > 1000) return;
                    rows.Add(row);
                }
                AuditRows = rows;
            }
            catch (Exception e) { LogBadPacket("ответ журнала", e); }
        }
        private void OnBansRequest(ZRpc rpc, ZPackage package)
        {
            try
            {
                if (!FetchAllowed(rpc, package, AdminPermission.Moderate)) return;
                var rows = new List<string>();
                foreach (string identity in ZNet.instance.Banned)
                    if (!string.IsNullOrEmpty(identity) && identity.Length <= 128 && rows.Count < 1000) rows.Add(identity);
                var response = new ZPackage(); response.Write(ProtocolVersion); response.Write(rows.Count);
                foreach (string identity in rows) { response.Write(identity); response.Write(TrimEmpty(authority.Reason(identity), 300)); }
                rpc.Invoke(BansRpc, response);
            }
            catch (Exception e) { LogBadPacket("запрос блокировок", e); }
        }
        private void OnBans(ZRpc rpc, ZPackage package)
        {
            if (!Allowed(AdminPermission.Moderate) || !FromServer(rpc) || !Packet(package, 2097152)) return;
            try
            {
                if (package.ReadInt() != ProtocolVersion) return;
                int count = package.ReadInt(); if (count < 0 || count > 1000) return;
                var rows = new List<BanRow>();
                for (int i = 0; i < count; ++i)
                {
                    var row = new BanRow { Identity = package.ReadString(), Reason = package.ReadString() };
                    if (row.Identity.Length > 128 || row.Reason.Length > 300) return;
                    rows.Add(row);
                }
                BannedPlayers = rows;
            }
            catch (Exception e) { LogBadPacket("ответ блокировок", e); }
        }
        private static string TrimEmpty(string text, int maximum) { return text == null ? "" : text.Length <= maximum ? text : text.Substring(0, maximum); }

        private static void Result(ZRpc rpc, int id, bool success, string text)
        {
            if (rpc == null || !rpc.IsConnected()) return;
            ZPackage package = new ZPackage();
            package.Write(ProtocolVersion); package.Write(id); package.Write(success); package.Write(Trim(text, 1000));
            rpc.Invoke(ResultRpc, package);
        }

        private void OnResult(ZRpc rpc, ZPackage package)
        {
            if (!FromServer(rpc) || !Packet(package, 4096)) return;
            try
            {
                if (package.ReadInt() != ProtocolVersion) return;
                package.ReadInt();
                bool success = package.ReadBool();
                string text = package.ReadString();
                if (text.Length <= 1000) plugin.Notify(success ? text : "Ошибка: " + text);
            }
            catch (Exception e) { LogBadPacket("результат команды", e); }
        }

        private static string Trim(string text, int maximum)
        {
            if (string.IsNullOrEmpty(text)) return "Команда выполнена.";
            return text.Length <= maximum ? text : text.Substring(0, maximum);
        }

        private void LogBadPacket(string operation, Exception exception)
        {
            plugin.Log.LogWarning("Неверный пакет (" + operation + "): " + exception.GetType().Name);
        }
    }
}
