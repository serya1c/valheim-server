using System;
using System.Collections.Generic;
using UnityEngine;

namespace ValheimAdminRu
{
    /// <summary>Session-local, vertex-level undo for the most recent terrain action.</summary>
    public static class TerrainUndo
    {
        internal sealed class Vertex
        {
            public int Index;
            public float BeforeLevel, BeforeSmooth, AfterLevel, AfterSmooth, Baseline;
            public bool BeforeModified, AfterModified;

            public bool Matches(float level, float smooth, bool modified, float baseline)
            {
                // Native Save preserves the float bits. Exact comparison avoids
                // overwriting even a small later edit by another player.
                return level.Equals(AfterLevel) && smooth.Equals(AfterSmooth)
                    && modified == AfterModified && baseline.Equals(Baseline);
            }
        }

        internal sealed class Chunk
        {
            public ZDOID Id;
            public Vector3 Position;
            public readonly List<Vertex> Vertices = new List<Vertex>();
        }

        internal sealed class Operation
        {
            public long World;
            public Vector3 Center;
            public float Radius;
            public readonly List<Chunk> Chunks = new List<Chunk>();
        }

        private static Operation last;
        public static bool HasSnapshot => last != null && last.Chunks.Count > 0;
        public static void Reset() { last = null; }

        internal static Operation Begin(Vector3 center, float radius)
        {
            return new Operation { World = ZNet.instance.GetWorldUID(), Center = center, Radius = radius };
        }

        internal static void Commit(Operation operation)
        {
            if (operation != null && operation.Chunks.Count > 0 && ZNet.instance
                && operation.World == ZNet.instance.GetWorldUID()) last = operation;
        }

        internal static Operation Current()
        {
            if (!HasSnapshot || !ZNet.instance || last.World != ZNet.instance.GetWorldUID())
                throw new InvalidOperationException("Нет последнего изменения поверхности для отмены в этом мире.");
            return last;
        }

        internal static void Finish(Operation operation)
        {
            if (ReferenceEquals(last, operation) && operation.Chunks.Count == 0) last = null;
        }
    }
}
