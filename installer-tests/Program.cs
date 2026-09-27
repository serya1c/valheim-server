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
if(args.Contains("--network")){using var source=new SourceClient();var fetched=await source.Download(new("1.0.15","0.10.2.0"));Check(fetched.Data.SequenceEqual(data),"HTTPS GitHub download matches official fixture");}
Console.WriteLine($"{count} checks passed. Fixture retained: {root}");
