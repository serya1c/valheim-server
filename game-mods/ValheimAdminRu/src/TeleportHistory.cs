using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Xml.Serialization;
using BepInEx;
using UnityEngine;

namespace ValheimAdminRu
{
    public static class TeleportHistory
    {
        private static List<SavedPoint> points;
        private static bool canReturn;
        private static long returnWorld;
        private static Vector3 returnPosition;
        private static Quaternion returnRotation;
        private static string PathName => Path.Combine(Paths.ConfigPath, "ru.valheim.adminpanel.points.xml");
        private static long CurrentWorld => ZNet.instance && ZNet.instance.GetWorld() != null ? ZNet.instance.GetWorldUID() : 0L;
        public static bool CanReturn => canReturn && CurrentWorld != 0 && CurrentWorld == returnWorld;
        public static List<SavedPoint> Points { get { EnsureLoaded(); return points.Select(Clone).ToList(); } }

        public static List<SavedPoint> CurrentWorldPoints()
        {
            EnsureLoaded(); long world = CurrentWorld;
            return points.Where(p => world != 0 && p.WorldId == world).Select(Clone).ToList();
        }

        public static string SaveCurrent(string name)
        {
            var player=Player.m_localPlayer;
            if (!player || player.IsDead() || CurrentWorld == 0) throw new InvalidOperationException("Дождитесь загрузки живого персонажа.");
            name=(name ?? "").Trim();
            if (name.Length < 1 || name.Length > 80 || name.Any(char.IsControl)) throw new InvalidOperationException("Введите название точки от 1 до 80 символов.");
            EnsureLoaded();
            if (points.Count >= 1000) throw new InvalidOperationException("Всего уже сохранено 1000 точек. Удалите ненужные.");
            if (points.Count(p=>p.WorldId == CurrentWorld) >= 100) throw new InvalidOperationException("В этом мире уже сохранено 100 точек. Удалите ненужную.");
            var point=new SavedPoint { Id=Guid.NewGuid().ToString("N"), Name=name, WorldId=CurrentWorld, Position=player.transform.position };
            if (!PointRules.Valid(point)) throw new InvalidOperationException("Эту позицию нельзя сохранить.");
            var next=points.Select(Clone).ToList(); next.Add(point); Save(next); points=next;
            return "Точка «"+name+"» сохранена для этого мира.";
        }

        public static string Remove(string id)
        {
            EnsureLoaded();
            var found=points.FirstOrDefault(p=>string.Equals(p.Id,id,StringComparison.OrdinalIgnoreCase) && p.WorldId==CurrentWorld);
            if (found == null) throw new InvalidOperationException("Точка уже удалена или относится к другому миру.");
            var next=points.Where(p=>!string.Equals(p.Id,id,StringComparison.OrdinalIgnoreCase)).Select(Clone).ToList(); Save(next); points=next;
            return "Точка «"+found.Name+"» удалена.";
        }

        public static void Record(Player player)
        {
            if (!player || CurrentWorld == 0) return;
            returnWorld=CurrentWorld; returnPosition=player.transform.position; returnRotation=player.transform.rotation; canReturn=true;
        }
        public static void ResetReturn() { canReturn=false; returnWorld=0; }
        public static string Execute(Player player, AdminCommand command)
        {
            if (!player || player.IsTeleporting()) throw new InvalidOperationException("Дождитесь завершения предыдущего телепорта.");
            bool returning=command.Action==AdminAction.ReturnTeleport;
            if (returning && !CanReturn) throw new InvalidOperationException("В этом подключении ещё нет точки возврата.");
            Vector3 target=returning ? returnPosition : command.Position;
            Quaternion rotation=returning ? returnRotation : player.transform.rotation;
            Vector3 previous=player.transform.position; Quaternion previousRotation=player.transform.rotation;
            if (!player.TeleportTo(target, rotation, true)) throw new InvalidOperationException("Телепортация сейчас недоступна. Подождите и повторите.");
            returnWorld=CurrentWorld; returnPosition=previous; returnRotation=previousRotation; canReturn=true;
            return returning ? "Возврат к предыдущей точке начался." : "Телепортация к сохранённой точке началась.";
        }

        private static SavedPoint Clone(SavedPoint p) { return new SavedPoint { Id=p.Id, Name=p.Name, WorldId=p.WorldId, X=p.X, Y=p.Y, Z=p.Z }; }
        private static void EnsureLoaded()
        {
            if (points != null) return;
            var loaded=new List<SavedPoint>();
            try
            {
                if (File.Exists(PathName))
                {
                    var settings=new System.Xml.XmlReaderSettings { DtdProcessing=System.Xml.DtdProcessing.Prohibit, XmlResolver=null, MaxCharactersInDocument=2000000 };
                    using (var reader=System.Xml.XmlReader.Create(PathName,settings))
                    {
                        var file=(SavedPointsFile)new XmlSerializer(typeof(SavedPointsFile)).Deserialize(reader);
                        loaded=(file.Points ?? new List<SavedPoint>()).Where(PointRules.Valid).Take(1000).GroupBy(p=>p.Id,StringComparer.OrdinalIgnoreCase).Select(g=>g.First()).ToList();
                    }
                }
            }
            catch(Exception e) { Plugin.Instance?.Log.LogWarning("Не удалось прочитать сохранённые точки: "+e.Message); }
            points=loaded;
        }
        private static void Save(List<SavedPoint> next)
        {
            Directory.CreateDirectory(Paths.ConfigPath);
            string temp=PathName+".tmp";
            try
            {
                using(var stream=new FileStream(temp,FileMode.Create,FileAccess.Write,FileShare.None))
                { new XmlSerializer(typeof(SavedPointsFile)).Serialize(stream,new SavedPointsFile { Points=next }); stream.Flush(true); }
                if (File.Exists(PathName)) File.Replace(temp,PathName,null); else File.Move(temp,PathName);
            }
            finally { if(File.Exists(temp)) File.Delete(temp); }
        }
    }
}
