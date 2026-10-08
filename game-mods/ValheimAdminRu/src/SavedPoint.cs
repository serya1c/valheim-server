using System;
using System.Collections.Generic;
using System.Linq;
using System.Xml.Serialization;
using UnityEngine;

namespace ValheimAdminRu
{
    public sealed class SavedPoint
    {
        public string Id = "", Name = "";
        public long WorldId;
        public float X, Y, Z;
        [XmlIgnore] public Vector3 Position { get => new Vector3(X, Y, Z); set { X=value.x; Y=value.y; Z=value.z; } }
    }
    public sealed class SavedPointsFile { public List<SavedPoint> Points = new List<SavedPoint>(); }
    public static class PointRules
    {
        public static bool Valid(SavedPoint point)
        {
            return point != null && !string.IsNullOrWhiteSpace(point.Name) && point.Name.Length <= 80 && !point.Name.Any(char.IsControl)
                && Guid.TryParseExact(point.Id, "N", out Guid ignored) && point.WorldId != 0
                && CommandRules.Valid(new AdminCommand { Action=AdminAction.TeleportSaved, Position=point.Position });
        }
    }
}
