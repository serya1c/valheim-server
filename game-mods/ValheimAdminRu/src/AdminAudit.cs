using System;
using System.Collections.Generic;
using System.IO;
using System.Xml.Linq;
using System.Text;

namespace ValheimAdminRu
{
    internal sealed class AdminAudit
    {
        internal const int Maximum = 300;
        private readonly string path = AdminStorage.PathFor("audit.xml");
        private readonly Plugin plugin;
        private readonly List<AuditRow> rows = new List<AuditRow>();
        internal AdminAudit(Plugin plugin)
        {
            this.plugin = plugin;
            try
            {
                if (File.Exists(path)) foreach (XElement row in XElement.Load(path).Elements("entry"))
                    rows.Add(new AuditRow { TimeUtc = Clean(AdminStorage.Text(row, "time"), 64), Actor = Clean(AdminStorage.Text(row, "actor"), 256), Action = Clean(AdminStorage.Text(row, "action"), 100),
                        Details = Clean(AdminStorage.Text(row, "details"), 600), Result = Clean(AdminStorage.Text(row, "result"), 1000) });
                Trim();
            }
            catch (Exception e) { plugin.Log.LogWarning("Не удалось прочитать журнал админ-мода: " + e.GetType().Name); }
        }
        internal List<AuditRow> Recent()
        {
            var copy = new List<AuditRow>(rows); copy.Reverse(); return copy;
        }
        internal void Add(string actor, AdminAction action, string details, string result)
        {
            rows.Add(new AuditRow { TimeUtc = DateTime.UtcNow.ToString("o"), Actor = Clean(actor, 256), Action = Name(action), Details = Clean(details, 600), Result = Clean(result, 1000) });
            Trim();
            plugin.Log.LogInfo("Админ-команда: " + Clean(actor, 256) + " — " + Name(action) + "; " + Clean(details, 600) + "; " + Clean(result, 1000));
            try
            {
                var data = new XElement("audit");
                foreach (AuditRow row in rows) data.Add(new XElement("entry", new XAttribute("time", row.TimeUtc), new XAttribute("actor", row.Actor),
                    new XAttribute("action", row.Action), new XAttribute("details", row.Details), new XAttribute("result", row.Result)));
                AdminStorage.Save(path, data);
            }
            catch (Exception e) { plugin.Log.LogWarning("Не удалось сохранить журнал админ-мода: " + e.GetType().Name); }
        }
        private void Trim() { if (rows.Count > Maximum) rows.RemoveRange(0, rows.Count - Maximum); }
        internal static string Clean(string text, int max)
        {
            var clean = new StringBuilder();
            foreach (char c in text ?? "")
            {
                if (char.IsControl(c) || !System.Xml.XmlConvert.IsXmlChar(c)) continue;
                if (clean.Length >= max) break;
                clean.Append(c);
            }
            return clean.ToString();
        }
        internal static string Name(AdminAction action)
        {
            switch (action)
            {
                case AdminAction.TeleportMap: return "Телепорт на карту";
                case AdminAction.TeleportToPlayer: return "Телепорт к игроку";
                case AdminAction.SummonPlayer: return "Призвать игрока";
                case AdminAction.GodSelf: return "Бессмертие себе";
                case AdminAction.GodPlayer: return "Бессмертие игроку";
                case AdminAction.SpawnItem: return "Создать предметы";
                case AdminAction.SpawnMob: return "Создать существ";
                case AdminAction.Flatten: return "Выровнять землю";
                case AdminAction.RaiseTerrain: return "Поднять землю";
                case AdminAction.LowerTerrain: return "Опустить землю";
                case AdminAction.UndoTerrain: return "Отменить изменение земли";
                case AdminAction.HammerToggle: return "Режим супермолота";
                case AdminAction.HammerStrike: return "Удар супермолота";
                case AdminAction.FlySelf: return "Полёт";
                case AdminAction.CleanupSpawn: return "Удалить последний спавн";
                case AdminAction.ReturnTeleport: return "Вернуться после телепорта";
                case AdminAction.TeleportSaved: return "Телепорт в сохранённую точку";
                case AdminAction.HealPlayer: return "Вылечить игрока";
                case AdminAction.RestoreStaminaPlayer: return "Восстановить выносливость";
                case AdminAction.ClearEffectsPlayer: return "Снять эффекты";
                case AdminAction.BuildToggle: return "Режим строительства";
                case AdminAction.RepairArea: return "Починить постройки";
                case AdminAction.KickPlayer: return "Отключить игрока";
                case AdminAction.BanPlayer: return "Заблокировать игрока";
                case AdminAction.UnbanPlayer: return "Снять блокировку";
                case AdminAction.SetRole: return "Изменить роль";
                default: return "Неизвестная команда";
            }
        }
    }
}
