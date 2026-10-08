using System;
using System.IO;
using System.Xml;
using System.Xml.Linq;
using ValheimAdminRu;

// Only the private spool and our own protocol are compiled here. No game code
// or assemblies are loaded or executed by this test project.
namespace UnityEngine
{
    public static class Time { public static float realtimeSinceStartup; }
    public struct Vector3 { public float x, y, z; public Vector3(float x, float y, float z) { this.x=x; this.y=y; this.z=z; } }
}
public sealed class ZPackage
{
    public void Write(int value) { } public void Write(long value) { } public void Write(float value) { }
    public void Write(bool value) { } public void Write(string value) { } public void Write(UnityEngine.Vector3 value) { }
    public int ReadInt()=>0; public long ReadLong()=>0; public float ReadSingle()=>0;
    public bool ReadBool()=>false; public string ReadString()=>""; public UnityEngine.Vector3 ReadVector3()=>default;
}
namespace ValheimAdminRu
{
    public sealed class Plugin { public readonly TestLog Log = new TestLog(); }
    public sealed class TestLog { public void LogWarning(string value) { } }
    public static class Locale { public static string Translate(string value)=>value; public static string TranslateEnglish(string value)=>value; }
    public static class AdminAudit { public static string Clean(string value, int maximum)=>value == null ? "" : value.Substring(0, Math.Min(value.Length, maximum)); }
    public sealed class NetworkService
    {
        public int Executions; public bool FailAfterClaim;
        public XElement BridgeSnapshot(string session, double now)=>new XElement("status", new XAttribute("session", session));
        internal void SubmitBridge(HearthBridge.Request request, Action<bool,string> callback)
        { Executions++; if (FailAfterClaim) throw new IOException("injected dispatch crash"); callback(true,"done"); }
    }
}
internal static class BridgeTests
{
    private static int checks;
    private const string Session = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", Id = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    private const string Steam = "76561198000000001";
    private static void Check(bool value, string name) { if (!value) throw new Exception(name); checks++; }
    private static void Reject(Action action, string name)
    { try { action(); } catch (Exception error) when (error is InvalidOperationException || error is FormatException || error is XmlException || error is IOException) { checks++; return; } throw new Exception("accepted: "+name); }
    private static XElement Command(double now, string id=Id, string session=Session)=>new XElement("command",
        new XAttribute("id",id),new XAttribute("session",session),new XAttribute("expires",HearthBridge.Number(now+30)),
        new XAttribute("action","GodSelf"),new XAttribute("actor_steam",Steam),new XAttribute("enabled","true"));
    private static void ParseChecks()
    {
        double now=HearthBridge.Now;
        Check(HearthBridge.Parse(Command(now),Id,Session,now).Command.Enabled,"valid command");
        foreach (string field in new[]{"unknown", "__proto__", "shell"})
        { var row=Command(now); row.SetAttributeValue(field,"x"); Reject(()=>HearthBridge.Parse(row,Id,Session,now),"unknown attribute"); }
        var namespaced=Command(now); namespaced.SetAttributeValue(XName.Get("action","urn:other"),"GodSelf");
        Reject(()=>HearthBridge.Parse(namespaced,Id,Session,now),"namespaced attribute");
        var nested=Command(now); nested.Add(new XElement("command")); Reject(()=>HearthBridge.Parse(nested,Id,Session,now),"nested XML");
        Reject(()=>HearthBridge.Parse(Command(now),Id,"cccccccccccccccccccccccccccccccc",now),"foreign session");
        Reject(()=>HearthBridge.Parse(Command(now),"cccccccccccccccccccccccccccccccc",Session,now),"filename mismatch");
        foreach(string expiry in new[]{HearthBridge.Number(now),HearthBridge.Number(now-1),HearthBridge.Number(now+31),"NaN","Infinity","1e999"})
        { var row=Command(now); row.SetAttributeValue("expires",expiry); Reject(()=>HearthBridge.Parse(row,Id,Session,now),"invalid expiry"); }
        foreach(string action in new[]{"Godself","3","9999","BanPlayer","KickPlayer","UnbanPlayer"})
        { var row=Command(now); row.SetAttributeValue("action",action); Reject(()=>HearthBridge.Parse(row,Id,Session,now),"invalid action"); }
        foreach(string role in new[]{"Owner","3","9","owner"})
        { var row=Command(now); row.SetAttributeValue("role",role); Reject(()=>HearthBridge.Parse(row,Id,Session,now),"invalid role"); }
        foreach(string steam in new[]{"Steam_"+Steam,"123",Steam+"0",Steam+"\n"})
        { var row=Command(now); row.SetAttributeValue("actor_steam",steam); Reject(()=>HearthBridge.Parse(row,Id,Session,now),"invalid actor"); }
        foreach(var pair in new[]{("count","1.5"),("count","501"),("radius","41"),("x","10501"),("enabled","1"),("hammer_targets","16"),("text","bad\ntext")})
        { var row=Command(now); row.SetAttributeValue(pair.Item1,pair.Item2); Reject(()=>HearthBridge.Parse(row,Id,Session,now),"invalid value "+pair.Item1); }
        Check(HearthBridge.SteamId("Steam_"+Steam)==Steam,"native identity normalized");
    }
    private static void SpoolChecks(string folder)
    {
        Environment.SetEnvironmentVariable("HEARTH_ADMIN_BRIDGE",folder);
        var network=new NetworkService(); var bridge=new HearthBridge(new Plugin(),network); bridge.Activate(Session);
        string command=Path.Combine(folder,"command-"+Id+".xml"), claim=Path.Combine(folder,"claimed-"+Id+".xml");
        Command(HearthBridge.Now).Save(command); bridge.Tick();
        Check(network.Executions==1 && File.Exists(claim) && !File.Exists(command),"durable claim before dispatch");
        Check(bridge.Healthy && File.Exists(Path.Combine(folder,"status.xml")),"healthy published snapshot");
        XElement result=XElement.Load(Path.Combine(folder,"result-"+Id+".xml"));
        Check((string)result.Attribute("success")=="true" && (string)result.Attribute("session")==Session,"final result");
        Command(HearthBridge.Now).Save(command); UnityEngine.Time.realtimeSinceStartup+=1; bridge.Tick();
        Check(network.Executions==1 && !File.Exists(command),"duplicate id never replays");
        bridge.Suspend(); Check(!bridge.Healthy && !File.Exists(Path.Combine(folder,"status.xml")),"suspend removes readiness");
        var restarted=new HearthBridge(new Plugin(),network); restarted.Activate("cccccccccccccccccccccccccccccccc");
        Command(HearthBridge.Now).Save(command); UnityEngine.Time.realtimeSinceStartup+=1; restarted.Tick();
        Check(network.Executions==1 && !File.Exists(command),"claimed work never replays after restart");
        string foreign="dddddddddddddddddddddddddddddddd";
        Command(HearthBridge.Now,foreign).Save(Path.Combine(folder,"command-"+foreign+".xml"));
        UnityEngine.Time.realtimeSinceStartup+=1; restarted.Tick();
        Check(network.Executions==1,"old epoch is never dispatched");
        string crash="eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"; network.FailAfterClaim=true;
        Command(HearthBridge.Now,crash,"cccccccccccccccccccccccccccccccc").Save(Path.Combine(folder,"command-"+crash+".xml"));
        UnityEngine.Time.realtimeSinceStartup+=1; restarted.Tick();
        Check(network.Executions==2 && File.Exists(Path.Combine(folder,"claimed-"+crash+".xml")),"dispatch failure retains durable claim");
        var again=new HearthBridge(new Plugin(),network); again.Activate(Session);
        Command(HearthBridge.Now,crash).Save(Path.Combine(folder,"command-"+crash+".xml")); UnityEngine.Time.realtimeSinceStartup+=1; again.Tick();
        Check(network.Executions==2,"failed dispatch does not replay");
        string malicious=Path.Combine(folder,"malformed.xml"); File.WriteAllText(malicious,"<!DOCTYPE command [<!ENTITY x SYSTEM 'file:///secret'>]><command>&x;</command>");
        Reject(()=>HearthBridge.ReadXml(malicious,16384),"DTD prohibited");
        File.WriteAllText(malicious,new string('x',16385)); Reject(()=>HearthBridge.ReadXml(malicious,16384),"bounded XML");
    }
    public static void Main()
    {
        string folder=Path.Combine(Path.GetTempPath(),"hearth-bridge-tests-"+Guid.NewGuid().ToString("N"));
        try { Directory.CreateDirectory(folder); ParseChecks(); SpoolChecks(folder); Console.WriteLine("Bridge tests passed: "+checks+" checks"); }
        finally { Environment.SetEnvironmentVariable("HEARTH_ADMIN_BRIDGE",null); Directory.Delete(folder,true); }
    }
}
