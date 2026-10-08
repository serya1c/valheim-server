using System;
using UnityEngine;
using UnityEngine.Rendering;

namespace ValheimAdminRu
{
    internal sealed class RadiusPreview : IDisposable
    {
        private const int Segments=96;
        private GameObject root;
        private Material material;
        private LineRenderer[] rings;
        private float nextDraw;
        private bool failed;

        public void Update(Vector3 center, float radius, bool terrain)
        {
            if (failed || radius < 1f || radius > 40f) { Hide(); return; }
            if (rings == null && !Create()) return;
            root.SetActive(true);
            if (Time.unscaledTime < nextDraw) return;
            nextDraw=Time.unscaledTime+0.05f;
            Color color=terrain ? new Color(1f,0.75f,0.15f,0.9f) : new Color(1f,0.35f,0.2f,0.9f);
            for (int ring=0;ring<rings.Length;ring++)
            {
                rings[ring].enabled=ring==0 || !terrain;
                if (!rings[ring].enabled) continue;
                rings[ring].startColor=color; rings[ring].endColor=color;
                var vertices=new Vector3[Segments+1];
                for (int i=0;i<=Segments;i++)
                {
                    float angle=i*Mathf.PI*2f/Segments;
                    float x=Mathf.Cos(angle)*radius, y=Mathf.Sin(angle)*radius;
                    Vector3 point=center+(ring==0 ? new Vector3(x,0f,y) : ring==1 ? new Vector3(x,y,0f) : new Vector3(0f,x,y));
                    if (terrain)
                    {
                        float height;
                        if (Heightmap.GetHeight(point,out height)) point.y=height+0.15f;
                        else point.y=center.y+0.15f;
                    }
                    vertices[i]=point;
                }
                rings[ring].SetPositions(vertices);
            }
        }
        private bool Create()
        {
            Shader shader=Shader.Find("Sprites/Default") ?? Shader.Find("Unlit/Color") ?? Shader.Find("Hidden/Internal-Colored");
            if (!shader)
            {
                failed=true; Plugin.Instance?.Log.LogWarning("Не найден материал для предпросмотра радиуса."); return false;
            }
            material=new Material(shader) { hideFlags=HideFlags.HideAndDontSave };
            root=new GameObject("ValheimAdminRu_RadiusPreview") { hideFlags=HideFlags.HideAndDontSave };
            UnityEngine.Object.DontDestroyOnLoad(root);
            rings=new LineRenderer[3];
            for(int i=0;i<rings.Length;i++)
            {
                var child=new GameObject("Круг "+i); child.transform.SetParent(root.transform,false);
                var line=child.AddComponent<LineRenderer>();
                line.useWorldSpace=true; line.loop=false; line.positionCount=Segments+1; line.sharedMaterial=material;
                line.startWidth=line.endWidth=0.08f; line.shadowCastingMode=ShadowCastingMode.Off; line.receiveShadows=false;
                rings[i]=line;
            }
            return true;
        }
        public void Hide() { if(root) root.SetActive(false); nextDraw=0f; }
        public void Dispose()
        {
            if(root) UnityEngine.Object.Destroy(root);
            if(material) UnityEngine.Object.Destroy(material);
            root=null; material=null; rings=null;
        }
    }
}
