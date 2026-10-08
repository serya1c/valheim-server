using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using HarmonyLib;
using UnityEngine;

namespace ValheimAdminRu
{
    public static class WorldActions
    {
        public const float HammerDamage = 999999f;
        public static bool GodEnabled { get; private set; }
        public static bool FlightEnabled => FlightMode.Enabled;
        public static bool BuildEnabled => BuildMode.Enabled;

        private static readonly MethodInfo TerrainSave = AccessTools.Method(typeof(TerrainComp), "Save", new[] { typeof(bool) });
        private static readonly MethodInfo TerrainCheckLoad = AccessTools.Method(typeof(TerrainComp), "CheckLoad", Type.EmptyTypes);
        private static readonly FieldInfo TerrainInitialized = AccessTools.Field(typeof(TerrainComp), "m_initialized");
        private static readonly FieldInfo TerrainLevel = AccessTools.Field(typeof(TerrainComp), "m_levelDelta");
        private static readonly FieldInfo TerrainSmooth = AccessTools.Field(typeof(TerrainComp), "m_smoothDelta");
        private static readonly FieldInfo TerrainModified = AccessTools.Field(typeof(TerrainComp), "m_modifiedHeight");
        private static readonly FieldInfo TerrainOperations = AccessTools.Field(typeof(TerrainComp), "m_operations");
        private static readonly FieldInfo TerrainLastPoint = AccessTools.Field(typeof(TerrainComp), "m_lastOpPoint");
        private static readonly FieldInfo TerrainLastRadius = AccessTools.Field(typeof(TerrainComp), "m_lastOpRadius");
        private static readonly MethodInfo RockArea = AccessTools.Method(typeof(MineRock), "GetAreaIndex");
        private static readonly MethodInfo Rock5Area = AccessTools.Method(typeof(MineRock5), "GetAreaIndex");
        private static readonly FieldInfo TeleportTarget = AccessTools.Field(typeof(Player), "m_teleportTargetPos");
        private static readonly FieldInfo TeleportCooldown = AccessTools.Field(typeof(Player), "m_teleportCooldown");
        private static bool terrainBusy;
        private static bool teleportPending;
        private static int generation;
        private static TerrainComp captureTarget;
        private static float[] capturedTerrain;
        private static float[] capturedBase;

        public static void Reset()
        {
            generation++;
            if (Player.m_localPlayer && GodEnabled) Player.m_localPlayer.SetGodMode(false);
            GodEnabled = false;
            terrainBusy = false;
            captureTarget = null;
            capturedTerrain = capturedBase = null;
            teleportPending = false;
            FlightMode.Reset();
            BuildMode.Reset();
            TerrainUndo.Reset();
            TeleportHistory.ResetReturn();
            if (Plugin.Instance != null) Plugin.Instance.HammerEnabled = false;
        }

        // Losing one web lease must not clear unrelated effects, undo, or return.
        internal static void RevokeEffects(AdminPermission effects)
        {
            if ((effects & AdminPermission.Help) != 0)
            {
                if (Player.m_localPlayer && GodEnabled) Player.m_localPlayer.SetGodMode(false);
                GodEnabled = false;
            }
            if ((effects & AdminPermission.Travel) != 0) FlightMode.Reset();
            if ((effects & AdminPermission.Build) != 0) BuildMode.Reset();
            if ((effects & AdminPermission.Hammer) != 0 && Plugin.Instance != null) Plugin.Instance.HammerEnabled = false;
        }

        public static void Tick()
        {
            FlightMode.Tick();
            BuildMode.Tick();
            if (GodEnabled && Player.m_localPlayer && !Player.m_localPlayer.InGodMode())
                Player.m_localPlayer.SetGodMode(true);
        }

        // Commands enter here only after the dedicated server has authorized them.
        public static string Execute(AdminCommand command)
        {
            if (!CommandRules.Valid(command)) throw new InvalidOperationException("Некорректные параметры действия.");
            Player player = Player.m_localPlayer;
            if (!player || player.IsDead()) throw new InvalidOperationException("Действие доступно только живому персонажу.");

            switch (command.Action)
            {
                case AdminAction.TeleportMap:
                    return TeleportOnMap(player, command.Position);
                case AdminAction.TeleportToPlayer:
                case AdminAction.SummonPlayer:
                    PrepareTeleport(player);
                    if (!player.TeleportTo(command.Position, player.transform.rotation, true))
                        throw new InvalidOperationException("Подождите завершения предыдущей телепортации.");
                    // Native TeleportTo only starts the transition. The transform is
                    // still at the source, and failed starts must keep older history.
                    TeleportHistory.Record(player);
                    return "Телепортация началась.";
                case AdminAction.ReturnTeleport:
                case AdminAction.TeleportSaved:
                    return TeleportHistory.Execute(player, command);
                case AdminAction.GodSelf:
                case AdminAction.GodPlayer:
                    GodEnabled = command.Enabled;
                    player.SetGodMode(GodEnabled);
                    return GodEnabled ? "Бессмертие включено." : "Бессмертие выключено.";
                case AdminAction.FlySelf:
                    return FlightMode.Set(command.Enabled);
                case AdminAction.SpawnItem:
                    return SpawnItems(player, command);
                case AdminAction.SpawnMob:
                    return SpawnMobs(player, command);
                case AdminAction.HealPlayer:
                    return PlayerAssistance.Heal(player);
                case AdminAction.RestoreStaminaPlayer:
                    return PlayerAssistance.RestoreStamina(player);
                case AdminAction.ClearEffectsPlayer:
                    return PlayerAssistance.ClearNegativeEffects(player);
                case AdminAction.BuildToggle:
                    return BuildMode.Set(command.Enabled);
                case AdminAction.RepairArea:
                    return RepairArea(command.Position, command.Radius);
                case AdminAction.UndoTerrain:
                    if (terrainBusy) throw new InvalidOperationException("Предыдущее изменение поверхности ещё выполняется.");
                    if (!TerrainSupported()) throw new InvalidOperationException("Версия игры не поддерживает отмену изменения поверхности.");
                    TerrainUndo.Operation undo = TerrainUndo.Current();
                    terrainBusy = true;
                    try { Plugin.Instance.StartCoroutine(UndoTerrain(player, undo, generation)); }
                    catch { terrainBusy = false; throw; }
                    return "Отмена последнего изменения поверхности началась.";
                case AdminAction.Flatten:
                case AdminAction.RaiseTerrain:
                case AdminAction.LowerTerrain:
                    if (terrainBusy) throw new InvalidOperationException("Предыдущее изменение поверхности ещё выполняется.");
                    if (!TerrainSupported()) throw new InvalidOperationException("Версия игры не поддерживает изменение поверхности.");
                    terrainBusy = true;
                    try { Plugin.Instance.StartCoroutine(ChangeTerrain(player, command.Position, command.Action, command.Radius, command.Height, generation)); }
                    catch { terrainBusy = false; throw; }
                    return command.Action == AdminAction.Flatten ? "Выравнивание поверхности началось."
                        : command.Action == AdminAction.RaiseTerrain ? "Поднятие поверхности началось." : "Опускание поверхности началось.";
                case AdminAction.HammerToggle:
                    Plugin.Instance.HammerEnabled = command.Enabled;
                    return command.Enabled ? "Супермолот включён. Возьмите «Супермолот администратора» и ударьте им." : "Супермолот выключен.";
                case AdminAction.HammerStrike:
                    return Strike(player, command.Position, command.Radius, command.HammerTargets);
                default:
                    throw new InvalidOperationException("Неизвестное действие.");
            }
        }

        private static string TeleportOnMap(Player player, Vector3 position)
        {
            PrepareTeleport(player);
            float height;
            if (!Heightmap.GetHeight(position, out height))
            {
                if (WorldGenerator.instance == null) throw new InvalidOperationException("Мир ещё загружается.");
                height = WorldGenerator.instance.GetHeight(position);
            }
            float water = ZoneSystem.instance ? ZoneSystem.instance.m_waterLevel : 30f;
            position.y = Mathf.Max(height, water) + 1f;
            if (!player.TeleportTo(position, player.transform.rotation, true))
                throw new InvalidOperationException("Подождите две секунды после предыдущей телепортации.");
            TeleportHistory.Record(player);
            teleportPending = true;
            Plugin.Instance.StartCoroutine(FinishMapTeleport(player, position, generation));
            return "Телепортация к выбранной точке началась.";
        }

        private static void PrepareTeleport(Player player)
        {
            if (teleportPending || player.IsTeleporting()) throw new InvalidOperationException("Предыдущая телепортация ещё выполняется.");
            ZNetView view = player.GetComponent<ZNetView>();
            if (!view || !view.IsValid() || !view.IsOwner() || TeleportCooldown == null)
                throw new InvalidOperationException("Персонаж ещё не готов к телепортации.");
            if ((float)TeleportCooldown.GetValue(player) < 2f)
                throw new InvalidOperationException("Подождите две секунды после предыдущей телепортации.");
        }

        private static IEnumerator FinishMapTeleport(Player player, Vector3 destination, int currentGeneration)
        {
            float timeout = Time.realtimeSinceStartup + 18f;
            bool corrected = false;
            while (currentGeneration == generation && player && player == Player.m_localPlayer
                && player.IsTeleporting() && Time.realtimeSinceStartup < timeout)
            {
                // The procedural estimate excludes saved terrain edits. Correct it once
                // the destination's actual heightmaps have arrived, before teleport ends.
                if (!corrected && ZNetScene.instance && ZNetScene.instance.IsAreaReady(destination))
                {
                    float height;
                    if (Heightmap.GetHeight(destination, out height))
                    {
                        float water = ZoneSystem.instance ? ZoneSystem.instance.m_waterLevel : 30f;
                        destination.y = Mathf.Max(height, water) + 1f;
                        if (TeleportTarget != null) TeleportTarget.SetValue(player, destination);
                        corrected = true;
                    }
                }
                yield return null;
            }
            if (currentGeneration != generation) yield break;
            teleportPending = false;
            Plugin.Instance.Notify(player && !player.IsTeleporting()
                ? "Телепортация завершена." : "Область назначения не успела загрузиться.");
        }

        private static GameObject FindPrefab(string name)
        {
            return ZNetScene.instance ? ZNetScene.instance.GetPrefab(name) : null;
        }

        private static Vector3 SpawnPosition(Player player, Vector3 center, int index, int total)
        {
            Vector3 position = center + player.transform.forward * 2.5f;
            if (total > 1)
            {
                float angle = index * 2f * Mathf.PI / total;
                float spread = Mathf.Min(3f, 0.5f + total * 0.08f);
                position += new Vector3(Mathf.Cos(angle), 0f, Mathf.Sin(angle)) * spread;
            }
            float height;
            if (ZoneSystem.instance && ZoneSystem.instance.GetGroundHeight(position, out height))
                position.y = Mathf.Max(position.y, height);
            position.y += 0.5f;
            return position;
        }

        private static string SpawnItems(Player player, AdminCommand command)
        {
            SpawnTracker.RequireBatch(command);
            int count = command.Count;
            GameObject prefab = FindPrefab(command.Prefab);
            ItemDrop definition = prefab ? prefab.GetComponent<ItemDrop>() : null;
            if (!definition || definition.m_itemData == null || definition.m_itemData.m_shared == null)
                throw new InvalidOperationException("Предмет не найден в реестре игры.");
            ItemDrop.ItemData data = definition.m_itemData.Clone();
            data.m_dropPrefab = prefab;
            data.m_worldLevel = (byte)Game.m_worldLevel;
            data.m_cheated = true;
            int maxStack = Mathf.Max(1, data.m_shared.m_maxStackSize);
            int stacks = (count + maxStack - 1) / maxStack;
            int remaining = Mathf.Clamp(count, 1, 500);
            for (int i = 0; remaining > 0; i++)
            {
                int amount = Math.Min(remaining, maxStack);
                ItemDrop drop = ItemDrop.DropItem(data, amount, SpawnPosition(player, command.Position, i, stacks), Quaternion.identity);
                SpawnTracker.Tag(drop ? drop.gameObject : null, command);
                remaining -= amount;
            }
            return "Создано предметов: " + count + ".";
        }

        private static string SpawnMobs(Player player, AdminCommand command)
        {
            SpawnTracker.RequireBatch(command);
            int count = command.Count;
            GameObject prefab = FindPrefab(command.Prefab);
            Character definition = prefab ? prefab.GetComponent<Character>() : null;
            if (!definition || definition is Player || !prefab.GetComponent<BaseAI>())
                throw new InvalidOperationException("Существо не найдено в реестре игры.");
            count = Mathf.Clamp(count, 1, 20);
            for (int i = 0; i < count; i++)
            {
                GameObject spawned = UnityEngine.Object.Instantiate(prefab, SpawnPosition(player, command.Position, i, count), Quaternion.identity);
                SpawnTracker.Tag(spawned, command);
            }
            return "Создано существ: " + count + ".";
        }

        private sealed class TerrainResult
        {
            public int Completed, Skipped, Selected, Changed, Clipped;
            public string Failure;
        }

        private static bool TerrainSupported()
        {
            return TerrainSave != null && TerrainCheckLoad != null && TerrainInitialized != null && TerrainLevel != null && TerrainSmooth != null
                && TerrainModified != null && TerrainOperations != null && TerrainLastPoint != null && TerrainLastRadius != null;
        }

        private static bool TerrainCancelled(Player player, int currentGeneration)
        {
            return currentGeneration != generation || !player || player != Player.m_localPlayer || player.IsDead();
        }

        private static IEnumerator ChangeTerrain(Player player, Vector3 center, AdminAction action, float radius, float height, int currentGeneration)
        {
            TerrainResult result = new TerrainResult();
            radius = Mathf.Clamp(radius, 1f, 40f);
            height = Mathf.Clamp(height, 0.1f, 8f);
            TerrainUndo.Operation operation = null;
            try
            {
                List<Heightmap> heightmaps = new List<Heightmap>();
                try
                {
                    if (action == AdminAction.Flatten)
                    {
                        float ground;
                        if (!Heightmap.GetHeight(center, out ground))
                            throw new InvalidOperationException("Поверхность под персонажем не загружена.");
                        center.y = ground;
                    }
                    Heightmap.FindHeightmap(center, radius, heightmaps);
                    operation = TerrainUndo.Begin(center, radius);
                }
                catch (Exception) { result.Failure = "Не удалось найти загруженную поверхность."; }
                foreach (Heightmap heightmap in heightmaps)
                {
                    if (TerrainCancelled(player, currentGeneration)) yield break;
                    if (!heightmap || heightmap.IsDistantLod) { result.Skipped++; continue; }
                    TerrainComp compiler;
                    ZNetView view;
                    try
                    {
                        compiler = heightmap.GetAndCreateTerrainCompiler();
                        view = compiler ? compiler.GetComponent<ZNetView>() : null;
                        if (!view || !view.IsValid()) { result.Skipped++; continue; }
                        view.ClaimOwnership();
                    }
                    catch (Exception)
                    {
                        result.Skipped++;
                        result.Failure = "Не удалось получить управление частью поверхности.";
                        continue;
                    }
                    float timeout = Time.realtimeSinceStartup + 3f;
                    while (view && view.IsValid() && !view.IsOwner() && Time.realtimeSinceStartup < timeout)
                    {
                        if (TerrainCancelled(player, currentGeneration)) yield break;
                        yield return null;
                    }
                    if (TerrainCancelled(player, currentGeneration)) yield break;
                    if (!view || !view.IsValid() || !view.IsOwner()) { result.Skipped++; continue; }
                    try
                    {
                        ApplyTerrain(compiler, heightmap, center, radius, action, height, result, operation);
                        result.Completed++;
                    }
                    catch (Exception)
                    {
                        result.Skipped++;
                        result.Failure = "Не удалось применить изменение к части поверхности.";
                    }
                    yield return null;
                }
            }
            finally
            {
                if (currentGeneration == generation)
                {
                    terrainBusy = false;
                    TerrainUndo.Commit(operation);
                    // Remote peers reset clutter when they read the changed terrain ZDO.
                    // The owning client needs the same refresh after its local rebuild.
                    if (result.Changed > 0 && ClutterSystem.instance)
                    {
                        try { ClutterSystem.instance.ResetGrass(center, radius); }
                        catch (Exception) { result.Failure = "Не удалось обновить растительность после изменения поверхности."; }
                    }
                }
            }
            if (currentGeneration != generation) yield break;
            if (Plugin.Instance != null) Plugin.Instance.Notify(TerrainMessage(action, radius, height, result));
        }

        // Capture the native baseline during a normal rebuild. It includes old terrain
        // modifiers and avoids deriving it from heights that were already clamped.
        internal static void CaptureTerrain(TerrainComp compiler, List<float> heights, float[] baseHeights)
        {
            if (compiler != captureTarget) return;
            capturedTerrain = heights.ToArray();
            capturedBase = (float[])baseHeights.Clone();
        }

        private static void ReadTerrainBaseline(TerrainComp compiler, Heightmap heightmap, out float[] baseline, out float[] bounds)
        {
            // Ownership can arrive before Update's normal revision check has run.
            // Load the newest received ZDO before recording or changing any vertices.
            TerrainCheckLoad.Invoke(compiler, null);
            captureTarget = compiler;
            capturedTerrain = capturedBase = null;
            try
            {
                heightmap.Poke(0, false);
                baseline = capturedTerrain;
                bounds = capturedBase;
            }
            finally
            {
                captureTarget = null;
                capturedTerrain = capturedBase = null;
            }
        }

        private static void ApplyTerrain(TerrainComp compiler, Heightmap heightmap, Vector3 center,
            float radius, AdminAction action, float height, TerrainResult result, TerrainUndo.Operation operation)
        {
            float[] baseline, bounds;
            ReadTerrainBaseline(compiler, heightmap, out baseline, out bounds);
            int side = heightmap.m_width + 1;
            int size = side * side;
            float[] level = (float[])TerrainLevel.GetValue(compiler);
            float[] smooth = (float[])TerrainSmooth.GetValue(compiler);
            bool[] modified = (bool[])TerrainModified.GetValue(compiler);
            if (baseline == null || bounds == null || baseline.Length != size || bounds.Length != size
                || level == null || smooth == null || modified == null || level.Length != size
                || smooth.Length != size || modified.Length != size || heightmap.m_scale <= 0f)
                throw new InvalidOperationException("Не удалось прочитать данные поверхности.");

            Vector3 origin = heightmap.transform.position;
            int offset = heightmap.m_width / 2;
            float requestedDelta = action == AdminAction.LowerTerrain ? -height : height;
            int changed = 0, selected = 0, clipped = 0;
            // Prepare separate arrays first; an unsupported or malformed chunk must not
            // leave its live compiler partially changed before the operation is saved.
            float[] nextLevel = (float[])level.Clone();
            float[] nextSmooth = (float[])smooth.Clone();
            bool[] nextModified = (bool[])modified.Clone();
            TerrainUndo.Chunk snapshot = new TerrainUndo.Chunk
            { Id = compiler.GetComponent<ZNetView>().GetZDO().m_uid, Position = origin };
            for (int z = 0; z < side; z++)
            {
                float worldZ = origin.z + (z - offset) * heightmap.m_scale;
                for (int x = 0; x < side; x++)
                {
                    float worldX = origin.x + (x - offset) * heightmap.m_scale;
                    if (!TerrainMath.Contains(worldX, worldZ, center.x, center.z, radius)) continue;
                    int index = z * side + x;
                    float current = heightmap.GetHeight(x, z);
                    float requested = action == AdminAction.Flatten ? center.y - origin.y : current + requestedDelta;
                    TerrainVertexChange change = TerrainMath.Resolve(current, baseline[index], bounds[index], requested, Heightmap.c_LevelMaxDelta);
                    selected++;
                    if (change.Clipped) clipped++;
                    if (!change.Changed) continue;
                    nextLevel[index] = change.CompilerDelta;
                    nextSmooth[index] = 0f;
                    nextModified[index] = true;
                    snapshot.Vertices.Add(new TerrainUndo.Vertex
                    {
                        Index = index, BeforeLevel = level[index], BeforeSmooth = smooth[index], BeforeModified = modified[index],
                        AfterLevel = nextLevel[index], AfterSmooth = nextSmooth[index], AfterModified = nextModified[index], Baseline = baseline[index]
                    });
                    changed++;
                }
            }
            result.Selected += selected;
            result.Clipped += clipped;
            if (changed == 0) return;

            SaveTerrain(compiler, nextLevel, nextSmooth, nextModified, center, radius);
            // Save has persisted these values even if the following local rebuild fails.
            operation.Chunks.Add(snapshot);
            result.Changed += changed;
            heightmap.Poke(0, false);
        }

        private static void SaveTerrain(TerrainComp compiler, float[] nextLevel, float[] nextSmooth, bool[] nextModified, Vector3 center, float radius)
        {
            ZNetView view = compiler.GetComponent<ZNetView>();
            if (!view || !view.IsValid() || !view.IsOwner() || !(bool)TerrainInitialized.GetValue(compiler))
                throw new InvalidOperationException("Нет управления готовой поверхностью.");
            float[] level = (float[])TerrainLevel.GetValue(compiler);
            float[] smooth = (float[])TerrainSmooth.GetValue(compiler);
            bool[] modified = (bool[])TerrainModified.GetValue(compiler);
            int previousOperations = (int)TerrainOperations.GetValue(compiler);
            Vector3 previousPoint = (Vector3)TerrainLastPoint.GetValue(compiler);
            float previousRadius = (float)TerrainLastRadius.GetValue(compiler);
            try
            {
                TerrainLevel.SetValue(compiler, nextLevel);
                TerrainSmooth.SetValue(compiler, nextSmooth);
                TerrainModified.SetValue(compiler, nextModified);
                TerrainOperations.SetValue(compiler, previousOperations + 1);
                TerrainLastPoint.SetValue(compiler, center);
                TerrainLastRadius.SetValue(compiler, radius);
                // Native Save stores the existing paint and updated heights in ZDO.
                // Rebuild uses the unchanged game clamp and generates the collider.
                TerrainSave.Invoke(compiler, new object[] { false });
            }
            catch
            {
                TerrainLevel.SetValue(compiler, level);
                TerrainSmooth.SetValue(compiler, smooth);
                TerrainModified.SetValue(compiler, modified);
                TerrainOperations.SetValue(compiler, previousOperations);
                TerrainLastPoint.SetValue(compiler, previousPoint);
                TerrainLastRadius.SetValue(compiler, previousRadius);
                throw;
            }
        }

        private static string TerrainMessage(AdminAction action, float radius, float height, TerrainResult result)
        {
            if (result.Completed == 0 || result.Selected == 0)
                return result.Failure ?? "Не найдена загруженная поверхность или не удалось получить управление ею.";
            string message;
            if (result.Changed == 0)
                message = result.Clipped > 0 ? "Поверхность не изменилась: достигнут предел изменения высоты игры."
                    : "Поверхность уже находится на выбранной высоте.";
            else
                message = action == AdminAction.Flatten ? "Поверхность выровнена"
                    : action == AdminAction.RaiseTerrain ? "Поверхность поднята на " + height.ToString("0.#") + " м"
                    : "Поверхность опущена на " + height.ToString("0.#") + " м";
            if (result.Changed > 0) message += " в радиусе " + radius.ToString("0.#") + " м.";
            if (result.Clipped > 0 && result.Changed > 0)
                message += " Часть площади ограничена пределом высоты игры: ±8 м от исходного рельефа.";
            if (result.Skipped > 0)
                message += " Часть поверхности не обработана: нет управления или область не загрузилась.";
            else if (result.Failure != null)
                message += " " + result.Failure;
            return message;
        }

        private sealed class UndoResult
        {
            public int Restored, Conflicts, Unavailable;
        }

        private static IEnumerator UndoTerrain(Player player, TerrainUndo.Operation operation, int currentGeneration)
        {
            UndoResult result = new UndoResult();
            try
            {
                foreach (TerrainUndo.Chunk chunk in new List<TerrainUndo.Chunk>(operation.Chunks))
                {
                    if (TerrainCancelled(player, currentGeneration)) yield break;
                    Heightmap heightmap = Heightmap.FindHeightmap(chunk.Position);
                    TerrainComp compiler = TerrainComp.FindTerrainCompiler(chunk.Position);
                    ZNetView view = compiler ? compiler.GetComponent<ZNetView>() : null;
                    if (!heightmap || heightmap.IsDistantLod || !view || !view.IsValid() || !view.GetZDO().m_uid.Equals(chunk.Id))
                    { result.Unavailable += chunk.Vertices.Count; continue; }
                    bool claimed;
                    try { view.ClaimOwnership(); claimed = true; }
                    catch (Exception) { claimed = false; }
                    if (!claimed) { result.Unavailable += chunk.Vertices.Count; continue; }
                    float timeout = Time.realtimeSinceStartup + 3f;
                    while (view && view.IsValid() && !view.IsOwner() && Time.realtimeSinceStartup < timeout)
                    {
                        if (TerrainCancelled(player, currentGeneration)) yield break;
                        yield return null;
                    }
                    if (TerrainCancelled(player, currentGeneration)) yield break;
                    if (!view || !view.IsValid() || !view.IsOwner() || !view.GetZDO().m_uid.Equals(chunk.Id))
                    { result.Unavailable += chunk.Vertices.Count; continue; }
                    try { RestoreTerrainChunk(compiler, heightmap, operation, chunk, result); }
                    catch (Exception) { result.Unavailable += chunk.Vertices.Count; }
                    yield return null;
                }
            }
            finally
            {
                if (currentGeneration == generation)
                {
                    terrainBusy = false;
                    TerrainUndo.Finish(operation);
                    if (result.Restored > 0 && ClutterSystem.instance)
                    {
                        try { ClutterSystem.instance.ResetGrass(operation.Center, operation.Radius); }
                        catch (Exception) { Plugin.Instance?.Log.LogWarning("Не удалось обновить растительность после отмены изменения поверхности."); }
                    }
                }
            }
            if (currentGeneration != generation) yield break;
            string message = result.Restored > 0 ? "Последнее изменение поверхности отменено. Восстановлено точек: " + result.Restored + "."
                : "Поверхность пока не восстановлена.";
            if (result.Conflicts > 0) message += " Сохранены более поздние изменения: " + result.Conflicts + ".";
            if (result.Unavailable > 0) message += " Недоступно точек: " + result.Unavailable + ". Подойдите к изменённой области и повторите отмену.";
            if (TerrainUndo.HasSnapshot) message += " Не восстановленная часть остаётся доступна для отмены.";
            Plugin.Instance?.Notify(message);
        }

        private static void RestoreTerrainChunk(TerrainComp compiler, Heightmap heightmap, TerrainUndo.Operation operation,
            TerrainUndo.Chunk chunk, UndoResult result)
        {
            float[] baseline, bounds;
            ReadTerrainBaseline(compiler, heightmap, out baseline, out bounds);
            float[] level = (float[])TerrainLevel.GetValue(compiler);
            float[] smooth = (float[])TerrainSmooth.GetValue(compiler);
            bool[] modified = (bool[])TerrainModified.GetValue(compiler);
            int size = (heightmap.m_width + 1) * (heightmap.m_width + 1);
            if (baseline == null || baseline.Length != size || level == null || level.Length != size
                || smooth == null || smooth.Length != size || modified == null || modified.Length != size)
                throw new InvalidOperationException("Не удалось прочитать поверхность для отмены.");
            float[] nextLevel = (float[])level.Clone();
            float[] nextSmooth = (float[])smooth.Clone();
            bool[] nextModified = (bool[])modified.Clone();
            List<TerrainUndo.Vertex> restored = new List<TerrainUndo.Vertex>();
            foreach (TerrainUndo.Vertex vertex in chunk.Vertices)
            {
                int i = vertex.Index;
                if (i < 0 || i >= size || !vertex.Matches(level[i], smooth[i], modified[i], baseline[i]))
                { result.Conflicts++; continue; }
                nextLevel[i] = vertex.BeforeLevel;
                nextSmooth[i] = vertex.BeforeSmooth;
                nextModified[i] = vertex.BeforeModified;
                restored.Add(vertex);
            }
            if (restored.Count == 0) return;
            SaveTerrain(compiler, nextLevel, nextSmooth, nextModified, operation.Center, operation.Radius);
            // Drop only values that were persisted successfully. Later edits and
            // unavailable chunks stay in the snapshot for a subsequent attempt.
            foreach (TerrainUndo.Vertex vertex in restored) chunk.Vertices.Remove(vertex);
            if (chunk.Vertices.Count == 0) operation.Chunks.Remove(chunk);
            result.Restored += restored.Count;
            heightmap.Poke(0, false);
        }

        private static string RepairArea(Vector3 center, float radius)
        {
            HashSet<int> seen = new HashSet<int>();
            int repaired = 0;
            foreach (Collider collider in Physics.OverlapSphere(center, radius, ~0, QueryTriggerInteraction.Ignore))
            {
                WearNTear piece = collider ? collider.GetComponentInParent<WearNTear>() : null;
                if (!piece || !piece.gameObject.activeInHierarchy || !seen.Add(piece.GetInstanceID())) continue;
                if (piece.Repair()) repaired++;
            }
            return repaired > 0 ? "Запросов ремонта построек в радиусе " + radius.ToString("0.#") + " м: " + repaired + "."
                : "В выбранном радиусе нет повреждённых построек, доступных для ремонта.";
        }

        private static HammerTargets TargetCategory(IDestructible target)
        {
            if (target is Character) return HammerTargets.Mobs;
            if (target is TreeBase || target is TreeLog || target.GetDestructibleType() == DestructibleType.Tree) return HammerTargets.Trees;
            if (target is MineRock || target is MineRock5) return HammerTargets.Ore;
            Destructible shell = target as Destructible;
            if (shell)
            {
                GameObject first = shell.m_spawnWhenDamaged, second = shell.m_spawnWhenDestroyed;
                if (IsOrePrefab(first) || IsOrePrefab(second)) return HammerTargets.Ore;
                if (IsTreePrefab(first) || IsTreePrefab(second)) return HammerTargets.Trees;
            }
            return HammerTargets.Structures;
        }

        private static bool IsOrePrefab(GameObject prefab)
        { return prefab && (prefab.GetComponentInChildren<MineRock>(true) || prefab.GetComponentInChildren<MineRock5>(true)); }

        private static bool IsTreePrefab(GameObject prefab)
        { return prefab && (prefab.GetComponentInChildren<TreeBase>(true) || prefab.GetComponentInChildren<TreeLog>(true)); }

        private static string Strike(Player player, Vector3 center, float radius, HammerTargets targets)
        {
            radius = Mathf.Clamp(radius, 1f, 40f);
            Collider[] colliders = Physics.OverlapSphere(center, radius, ~0, QueryTriggerInteraction.Ignore);
            HashSet<int> objects = new HashSet<int>();
            HashSet<int> rockSegments = new HashSet<int>();
            int hits = 0;
            foreach (Collider collider in colliders)
            {
                if (!collider || !collider.enabled || !collider.gameObject.activeInHierarchy) continue;
                IDestructible target = collider.GetComponentInParent<IDestructible>();
                MonoBehaviour component = target as MonoBehaviour;
                if (!component || target is Player || collider.GetComponentInParent<Player>()) continue;
                Character character = target as Character;
                if (character && (character.IsPlayer() || character.IsDead())) continue;
                if (!(target is Character) && !(target is TreeBase) && !(target is TreeLog)
                    && !(target is MineRock) && !(target is MineRock5) && !(target is WearNTear)
                    && !(target is Destructible)) continue;
                if ((targets & TargetCategory(target)) == HammerTargets.None) continue;

                MethodInfo areaMethod = target is MineRock5 ? Rock5Area : target is MineRock ? RockArea : null;
                if (target is MineRock5 || target is MineRock)
                {
                    if (areaMethod == null || (int)areaMethod.Invoke(component, new object[] { collider }) < 0
                        || !rockSegments.Add(collider.GetInstanceID())) continue;
                }
                else if (!objects.Add(component.GetInstanceID())) continue;

                HitData hit = new HitData
                {
                    m_toolTier = short.MaxValue,
                    m_point = collider.bounds.ClosestPoint(center),
                    m_dir = (component.transform.position - center).normalized,
                    m_hitCollider = collider,
                    m_dodgeable = false,
                    m_blockable = false,
                    m_pushForce = 0f,
                    m_hitType = HitData.HitType.PlayerHit,
                    m_skillRaiseAmount = 0f
                };
                // Generic damage bypasses vanilla chop/pickaxe immunity while preserving
                // the requested total: adding 999999 to several types multiplies damage.
                hit.m_damage.m_damage = HammerDamage;
                hit.SetAttacker(player);
                target.Damage(hit);
                hits++;
            }
            return "Супермолот: ударов по целям и участкам руды — " + hits + ". Урон: 999999.";
        }
    }

    [HarmonyPatch(typeof(TerrainComp), "ApplyToHeightmap")]
    internal static class TerrainBaselineCapturePatch
    {
        private static void Prefix(TerrainComp __instance, List<float> heights, float[] baseHeights)
        { WorldActions.CaptureTerrain(__instance, heights, baseHeights); }
    }
}
