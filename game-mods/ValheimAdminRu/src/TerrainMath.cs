using System;

namespace ValheimAdminRu
{
    public struct TerrainVertexChange
    {
        public float Height;
        public float CompilerDelta;
        public bool Changed;
        public bool Clipped;
    }

    /// <summary>Pure grid geometry and height arithmetic; no game or Unity state.</summary>
    public static class TerrainMath
    {
        private const float Tolerance = 0.0001f;

        public static bool Contains(float x, float z, float centerX, float centerZ, float radius)
        {
            double dx = (double)x - centerX;
            double dz = (double)z - centerZ;
            return dx * dx + dz * dz <= (double)radius * radius;
        }

        public static TerrainVertexChange Resolve(float currentHeight, float compilerBaseline,
            float nativeBaseHeight, float requestedHeight, float limit)
        {
            // Native terrain has two limits: the compiler delta itself and the
            // final height relative to the baseline before player modifications.
            float minimum = Math.Max(nativeBaseHeight - limit, compilerBaseline - limit);
            float maximum = Math.Min(nativeBaseHeight + limit, compilerBaseline + limit);
            if (!Finite(currentHeight) || !Finite(compilerBaseline) || !Finite(nativeBaseHeight)
                || !Finite(requestedHeight) || !Finite(limit) || limit <= 0f || minimum > maximum)
                throw new InvalidOperationException("Несовместимые данные поверхности.");
            float target = Math.Max(minimum, Math.Min(maximum, requestedHeight));
            return new TerrainVertexChange
            {
                Height = target,
                CompilerDelta = target - compilerBaseline,
                Changed = Math.Abs(target - currentHeight) > Tolerance,
                Clipped = Math.Abs(target - requestedHeight) > Tolerance
            };
        }

        private static bool Finite(float number)
        { return !float.IsNaN(number) && !float.IsInfinity(number); }
    }
}
