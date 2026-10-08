using LokiInstaller;
using System.IO.Compression;
using System.Text;
using System.Text.Json;
int count=0;
void Check(bool value,string name){if(!value)throw new Exception(name);Console.WriteLine("PASS "+name);count++;}
void Reject(Action action,string name){try{action();}catch(Exception e) when(e is IOException or InvalidDataException or ArgumentException){Check(true,name);return;}throw new Exception("Expected rejection: "+name);}
byte[] Utf(string s)=>Encoding.UTF8.GetBytes(s);
Check(SourceClient.Endpoint("https://north.example.org/")=="https://north.example.org/api/public","custom server origin");
foreach(var url in new[]{"http://north.example.org","https://u:p@north.example.org","https://north.example.org/path","https://north.example.org?x=1","https://north.example.org:8443"})Reject(()=>SourceClient.Endpoint(url),"invalid server origin "+url);
Reject(()=>SourceClient.ParseServer(Utf("{\"mode\":\"vanilla\",\"game\":\"1.0.16\",\"mod\":null}")),"vanilla never installs V+");
string root=Path.Combine(Path.GetTempPath(),"LokiInstallerTests-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(root);
string game=Path.Combine(root,"steamapps","common","Valheim");Directory.CreateDirectory(Path.Combine(game,"valheim_Data"));File.WriteAllText(Path.Combine(game,"valheim.exe"),"fake game — never executed");
File.WriteAllText(Path.Combine(root,"steamapps","appmanifest_892970.acf"),"\"AppState\" { \"appid\" \"892970\" \"installdir\" \"Valheim\" }");
Check(SteamFinder.GameInLibrary(root)==game,"Steam manifest discovery");
Check(SteamFinder.Libraries("// comment\n\"libraryfolders\" { \"0\" { \"path\" \"D:\\\\Игры\" } \"1\" \"E:\\\\Steam\" }").SequenceEqual(new[]{@"D:\Игры",@"E:\Steam"}),"modern and legacy libraries, Unicode");
Reject(()=>SteamFinder.ParseVdf("a { b"),"malformed VDF");
Check(SourceClient.ParseServer(Utf("{\"game\":\"1.0.15\",\"mod\":\"0.10.2.0\"}"))==new ServerVersion("1.0.15","0.10.2.0"),"server exact version");
Reject(()=>SourceClient.ParseServer(Utf("{\"game\":null,\"mod\":null}")),"uninstalled server has no latest fallback");
Reject(()=>SourceClient.VerifyHash([1,2],new string('0',64)),"wrong checksum");
string release=JsonSerializer.Serialize(new{tag_name="0.10.2.0",draft=false,prerelease=false,assets=new[]{new{name="WindowsClient.zip",browser_download_url="https://github.com/Grantapher/ValheimPlus/releases/download/0.10.2.0/WindowsClient.zip"}}});
var asset=SourceClient.ParseRelease(Utf(release),new("1.0.15","0.10.2.0"));
Reject(()=>SourceClient.ParseRelease(Utf(release),new("1.0.15","0.10.3.0")),"release mismatch");
var data=File.ReadAllBytes(args[0]);SourceClient.VerifyHash(data,asset.Sha256);Check(true,"official WindowsClient SHA256");
string stage=Path.Combine(root,"stage");var files=Installer.Extract(data,stage);
Console.WriteLine("Payload assembly: "+Installer.AssemblyInfo(Path.Combine(stage,"BepInEx/plugins/ValheimPlus.dll")));
Installer.ValidatePayload(stage,"0.10.2.0");Check(true,"official DLL version and BepInEx");
Reject(()=>Installer.ValidatePayload(stage,"0.10.3.0"),"DLL version mismatch");
foreach(string path in new[]{"../outside","C:/Windows/test","BepInEx/../../test","CON.txt","BepInEx/test.","BepInEx/test:stream"})Reject(()=>Installer.SafePath(game,path),"unsafe path "+path);
byte[] Archive(string name){using var m=new MemoryStream();using(var z=new ZipArchive(m,ZipArchiveMode.Create,true)){using var w=new StreamWriter(z.CreateEntry(name).Open());w.Write("bad");}return m.ToArray();}
Reject(()=>Installer.Extract(Archive("../escaped"),Path.Combine(root,"bad1")),"ZIP traversal");
Reject(()=>Installer.Extract(Archive("valheim.exe"),Path.Combine(root,"bad2")),"game replacement forbidden");
Directory.CreateDirectory(Path.Combine(game,"BepInEx/config"));File.WriteAllText(Path.Combine(game,"BepInEx/config/BepInEx.cfg"),"my config");File.WriteAllText(Path.Combine(game,"winhttp.dll"),"original loader");Directory.CreateDirectory(Path.Combine(game,"BepInEx/plugins"));File.WriteAllText(Path.Combine(game,"BepInEx/plugins/other.txt"),"other mod");
string backup=Installer.Apply(game,stage,files,"0.10.2.0",_=>{});
Check(File.ReadAllText(Path.Combine(game,"BepInEx/config/BepInEx.cfg"))=="my config","preserve existing configuration");
Check(Installer.ExistingMod(game)=="0.10.2.0","detect installed V+");
Check(File.ReadAllText(Path.Combine(game,"BepInEx/plugins/other.txt"))=="other mod","preserve other mod files");
Check(File.ReadAllText(Path.Combine(backup,"original/winhttp.dll"))=="original loader","original backed up");
Installer.Restore(game);Check(File.ReadAllText(Path.Combine(game,"winhttp.dll"))=="original loader"&&!File.Exists(Path.Combine(game,"BepInEx/plugins/ValheimPlus.dll")),"restore original and remove only added files");
Reject(()=>Installer.Apply(game,stage,files,"0.10.2.0",_=>{},i=>{if(i==3)throw new IOException("injected copy failure");}),"injected install failure");
Check(File.ReadAllText(Path.Combine(game,"winhttp.dll"))=="original loader"&&!File.Exists(Path.Combine(game,"BepInEx/plugins/ValheimPlus.dll")),"automatic rollback after partial install");
Installer.Apply(game,stage,files,"0.10.2.0",_=>{});File.WriteAllText(Path.Combine(game,"winhttp.dll"),"user changed");Reject(()=>Installer.Restore(game),"refuse overwriting later user edits");
File.Copy(Path.Combine(stage,"BepInEx/plugins/ValheimPlus.dll"),Path.Combine(game,"BepInEx/plugins/duplicate.dll"));Reject(()=>Installer.ValidateTarget(game),"duplicate V+ refusal");
Check(File.ReadAllText(Path.Combine(game,"valheim.exe"))=="fake game — never executed","game executable untouched");
byte[] Payload(Dictionary<string,byte[]> entries)
{
    using var memory=new MemoryStream();using(var zip=new ZipArchive(memory,ZipArchiveMode.Create,true))
        foreach(var pair in entries){using var output=zip.CreateEntry(pair.Key).Open();output.Write(pair.Value);}
    return memory.ToArray();
}
var genericEntries=new Dictionary<string,byte[]>();
using(var archive=new ZipArchive(new MemoryStream(data),ZipArchiveMode.Read))
    foreach(var entry in archive.Entries.Where(e=>!e.FullName.EndsWith('/')&&e.FullName!="BepInEx/plugins/ValheimPlus.dll"))
    {using var input=entry.Open();using var output=new MemoryStream();input.CopyTo(output);genericEntries.Add(entry.FullName,output.ToArray());}
genericEntries.Add("BepInEx/plugins/HearthMods/test/addon.dll",Utf("generic addon"));
genericEntries.Add("hearth-mods.json",Utf("{\"schema\":1}"));
byte[] genericData=Payload(genericEntries),overlayData=Payload(new(){["BepInEx/plugins/HearthMods/test/addon.dll"]=Utf("overlay addon"),["hearth-mods.json"]=Utf("{\"schema\":1}")});
string ServerJson(string mode,string kind,byte[] payload,string revision="",string url="/downloads/Hearth-Client-Mods.zip")=>JsonSerializer.Serialize(new{mode,game="1.0.15",mod=mode=="plus"?"0.10.2.0":null,client_mods=new{url,sha256=Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(payload)),size=payload.Length,revision=revision==""?new string('a',64):revision,kind,packages=new[]{new{id="test-addon",name="Test addon",version="1.0.0"}}}});
var generic=SourceClient.ParseServer(Utf(ServerJson("modded","full",genericData)));
Check(generic.Mod is null&&generic.ClientMods!.Kind=="full","generic full bundle accepts null V+ version");
Reject(()=>SourceClient.ParseServer(Utf("{\"mode\":\"modded\",\"game\":\"1.0.15\",\"client_mods\":null}")),"generic bundle required");
foreach(string url in new[]{"https://other.example.org/mods.zip","//other.example.org/mods.zip","/downloads/../private.zip"})Reject(()=>SourceClient.ParseServer(Utf(ServerJson("modded","full",genericData,url:url))),"reject noncanonical bundle URL "+url);
Reject(()=>SourceClient.ParseServer(Utf(ServerJson("modded","overlay",genericData))),"bundle kind must match mode");
SourceClient.VerifyBundle(genericData,generic.ClientMods!);Check(true,"bundle size and SHA256 verified");
Reject(()=>SourceClient.VerifyBundle([1,2],generic.ClientMods!),"bundle size mismatch");
Reject(()=>SourceClient.VerifyBundle(new byte[genericData.Length],generic.ClientMods!),"bundle SHA256 mismatch");
var changed=SourceClient.ParseServer(Utf(ServerJson("modded","full",genericData,new string('b',64))));
Check(!generic.SameAs(changed)&&generic.SameAs(SourceClient.ParseServer(Utf(ServerJson("modded","full",genericData)))),"snapshot revision is compared by value before install");
string genericStage=Path.Combine(root,"generic-stage");var genericFiles=Installer.Extract(genericData,genericStage,false);Installer.ValidatePayload(genericStage,null);
Check(!genericFiles.Contains("BepInEx/plugins/ValheimPlus.dll"),"generic archive validates without Valheim Plus");
Check(!genericFiles.Contains("hearth-mods.json"),"bundle metadata is validated and never installed into the game");
string combinedStage=Path.Combine(root,"combined-stage");var combined=Installer.Extract(data,combinedStage);combined.AddRange(Installer.Extract(overlayData,combinedStage,overlay:true));
Installer.ValidatePayload(combinedStage,"0.10.2.0");Check(combined.Contains("BepInEx/plugins/HearthMods/test/addon.dll"),"official V+ base plus server overlay");
string duplicatePlus=Installer.SafePath(combinedStage,"BepInEx/plugins/HearthMods/test/duplicate.dll");File.Copy(Installer.SafePath(stage,"BepInEx/plugins/ValheimPlus.dll"),duplicatePlus);Reject(()=>Installer.ValidatePayload(combinedStage,"0.10.2.0"),"overlay cannot introduce a second V+ assembly");File.Delete(duplicatePlus);
foreach(string bad in new[]{"winhttp.dll","BepInEx/core/BepInEx.dll","BepInEx/config/private.cfg"})Reject(()=>Installer.Extract(Payload(new(){[bad]=Utf("bad")}),Path.Combine(root,"overlay-bad-"+Guid.NewGuid().ToString("N")),overlay:true),"overlay cannot replace base or config "+bad);
string NewGame(string name){string path=Path.Combine(root,name);Directory.CreateDirectory(Path.Combine(path,"valheim_Data"));File.WriteAllText(Path.Combine(path,"valheim.exe"),"fake game");return path;}
string managedGame=NewGame("managed-game"),old="BepInEx/plugins/HearthMods/test/old.dll",modified="BepInEx/plugins/HearthMods/test/modified.dll";
foreach(string name in new[]{old,modified}){string path=Installer.SafePath(stage,name);Directory.CreateDirectory(Path.GetDirectoryName(path)!);File.WriteAllText(path,"old addon");}
Installer.Apply(managedGame,stage,[..files,old,modified],"0.10.2.0",_=>{});
File.WriteAllText(Installer.SafePath(managedGame,modified),"user edited addon");string user=Installer.SafePath(managedGame,"BepInEx/plugins/HearthMods/user.dll");File.WriteAllText(user,"unknown user mod");
Installer.Apply(managedGame,stage,files,"0.10.2.0",_=>{});
Check(!File.Exists(Installer.SafePath(managedGame,old))&&File.ReadAllText(Installer.SafePath(managedGame,modified))=="user edited addon"&&File.ReadAllText(user)=="unknown user mod","prune only unchanged journal-owned stale files");
Installer.Restore(managedGame);Check(File.ReadAllText(Installer.SafePath(managedGame,old))=="old addon","restore recovers removed addon");
string transitionGame=NewGame("transition-game");Installer.Apply(transitionGame,stage,files,"0.10.2.0",_=>{});Installer.Apply(transitionGame,genericStage,genericFiles,"BepInEx",_=>{},generic:true);
Check(!File.Exists(Installer.SafePath(transitionGame,"BepInEx/plugins/ValheimPlus.dll")),"generic transition removes owned V+");
Installer.Restore(transitionGame);Check(File.Exists(Installer.SafePath(transitionGame,"BepInEx/plugins/ValheimPlus.dll")),"generic transition restore recovers V+");
File.WriteAllText(Installer.SafePath(transitionGame,"BepInEx/plugins/ValheimPlus.dll"),"private V+");
Reject(()=>Installer.Apply(transitionGame,genericStage,genericFiles,"BepInEx",_=>{},generic:true),"generic transition protects user-modified V+");
using(var handler=new OfflineHandler(_=>new HttpResponseMessage(System.Net.HttpStatusCode.Redirect){Headers={Location=new Uri("https://other.example.org/mods.zip")}}))
using(var source=new SourceClient("https://north.example.org",handler))
{
    try{await source.DownloadBundle(generic.ClientMods!);throw new Exception("Expected bundle redirect rejection");}
    catch(IOException){Check(handler.Calls==1,"bundle redirects cannot change server origin");}
}
if(args.Contains("--network")){using var source=new SourceClient();var fetched=await source.Download(new("1.0.15","0.10.2.0"));Check(fetched.Data.SequenceEqual(data),"HTTPS GitHub download matches official fixture");}
Console.WriteLine($"{count} checks passed. Fixture retained: {root}");

sealed class OfflineHandler(Func<HttpRequestMessage,HttpResponseMessage> response) : HttpMessageHandler
{
    public int Calls;
    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request,CancellationToken cancellationToken){Calls++;return Task.FromResult(response(request));}
}
