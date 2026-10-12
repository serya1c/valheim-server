using System.Diagnostics;
using System.IO.Compression;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;


namespace HearthLauncher.Engine;

public record ClientPackage(string Id, string Name, string Version);
public record ClientBundle(string Url, string Sha256, long Size, string Revision, string Kind, List<ClientPackage> Packages);
public record ServerVersion(string Game, string? Mod, string Mode="plus", ClientBundle? ClientMods=null,
    string Title="Valheim", string Address="", string? CommunityUrl=null, bool Running=false, int? Players=null)
{
    public bool SameAs(ServerVersion other)=>Game==other.Game&&Mod==other.Mod&&Mode==other.Mode&&
        (ClientMods is null ? other.ClientMods is null : other.ClientMods is {} bundle&&
         (ClientMods.Url,ClientMods.Sha256,ClientMods.Size,ClientMods.Revision,ClientMods.Kind)==(bundle.Url,bundle.Sha256,bundle.Size,bundle.Revision,bundle.Kind));
}
public record ReleaseAsset(string Url, string Sha256);
public record FileChange(string Path, string? OriginalHash, string? InstalledHash);
public record OwnedFile(string Path, string Sha256);
public record InstallationInventory(int Schema, string GamePath, string Website, string Manifest,
    string Mode, List<OwnedFile> Files);
public record Journal(string GamePath, string Mod, string State, List<FileChange> Files,
    InstallationInventory? BeforeInventory=null, InstallationInventory? AfterInventory=null);
public record InstallationResult(string Backup, int ChangedFiles, int TotalFiles);

public sealed class SourceClient : IDisposable
{
    public const string ServerUrl="https://loki.ach-play.ru/api/public";
    const string KnownHash="1f6f1944b2285c34d663cbaf4353c846cabd4c35b9549d9006dd302ee4bda79b";
    readonly HttpClient http;
    static readonly Regex VersionPattern=new(@"\A\d+\.\d+\.\d+(?:\.\d+)?\z",RegexOptions.CultureInvariant);
    readonly string endpoint;
    public static string Endpoint(string website)
    {
        if(!Uri.TryCreate(website,UriKind.Absolute,out var uri)||uri.Scheme!="https"||uri.Port!=443||!string.IsNullOrEmpty(uri.UserInfo)||uri.AbsolutePath!="/"||uri.Query!=""||uri.Fragment!=""||website.Any(char.IsWhiteSpace)||website.Contains('\\'))
            throw new InvalidDataException("Укажите HTTPS-адрес сайта сервера без пути, параметров и пароля (порт 443).");
        return uri.GetLeftPart(UriPartial.Authority)+"/api/public";
    }
    public SourceClient(string website="https://loki.ach-play.ru",HttpMessageHandler? handler=null){endpoint=Endpoint(website);http=new(handler??new HttpClientHandler{AllowAutoRedirect=false}){Timeout=TimeSpan.FromMinutes(3)};http.DefaultRequestHeaders.UserAgent.ParseAdd("Loki-Mod-Installer/1.2");}
    public void Dispose()=>http.Dispose();
    static bool Allowed(Uri uri)=>uri.Scheme=="https"&&uri.Port==443&&string.IsNullOrEmpty(uri.UserInfo)&&new[]{"api.github.com","github.com","release-assets.githubusercontent.com","objects.githubusercontent.com"}.Contains(uri.Host,StringComparer.OrdinalIgnoreCase);
    async Task<byte[]> Get(string address,long maximum,bool fromServer=false,CancellationToken cancellationToken=default)
    {
        var uri=new Uri(address);bool serverRequest=address==endpoint||fromServer;var serverOrigin=new Uri(endpoint);
        for(int redirects=0;redirects<6;redirects++)
        {
            if(serverRequest ? uri.Scheme!="https"||uri.Authority!=serverOrigin.Authority||!string.IsNullOrEmpty(uri.UserInfo) : !Allowed(uri))throw new InvalidDataException("Источник или перенаправление загрузки не разрешены.");
            using var response=await http.GetAsync(uri,HttpCompletionOption.ResponseHeadersRead,cancellationToken);
            if((int)response.StatusCode is >=300 and <400)
            {
                var location=response.Headers.Location??throw new IOException("Пустое перенаправление.");
                var next=location.IsAbsoluteUri?location:new Uri(uri,location);
                // The server API must stay on the server host. GitHub assets may use its CDN.
                if(serverRequest&&(next.Scheme!=serverOrigin.Scheme||next.Authority!=serverOrigin.Authority))throw new IOException("API сервера перенаправляет на посторонний сайт.");
                uri=next;continue;
            }
            response.EnsureSuccessStatusCode();
            if(response.Content.Headers.ContentLength>maximum)throw new IOException("Слишком большой ответ загрузки.");
            using var input=await response.Content.ReadAsStreamAsync(cancellationToken);using var output=new MemoryStream();
            byte[] buffer=new byte[65536];int count;
            using var timeout=CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeout.CancelAfter(TimeSpan.FromMinutes(3));
            while((count=await input.ReadAsync(buffer,timeout.Token))>0){if(output.Length+count>maximum)throw new IOException("Превышен размер загрузки.");await output.WriteAsync(buffer.AsMemory(0,count),timeout.Token);}
            return output.ToArray();
        }
        throw new IOException("Слишком много перенаправлений.");
    }
    public static ServerVersion ParseServer(byte[] bytes)
    {
        try
        {
            using var json=JsonDocument.Parse(bytes);var root=json.RootElement;
            string mode=root.TryGetProperty("mode",out var modeValue)?modeValue.GetString()??"":"plus";
            string game=root.TryGetProperty("game",out var g)&&g.ValueKind==JsonValueKind.String?g.GetString()!:"";
            string? mod=root.TryGetProperty("mod",out var m)&&m.ValueKind==JsonValueKind.String?m.GetString():null;
            if(mode is not ("plus" or "modded" or "vanilla")||game.Length>80||!VersionPattern.IsMatch(game)||(mode=="plus"&&(mod is null||mod.Length>80||!VersionPattern.IsMatch(mod))))throw new InvalidDataException("Сервер ещё не сообщает установленную версию игры и мода. Повторите позже.");
            ClientBundle? bundle=null;
            if(mode!="vanilla"&&root.TryGetProperty("client_mods",out var c)&&c.ValueKind!=JsonValueKind.Null)
            {
                string url=c.GetProperty("url").GetString()??"",hash=c.GetProperty("sha256").GetString()??"",revision=c.GetProperty("revision").GetString()??"",kind=c.GetProperty("kind").GetString()??"";
                long size=c.GetProperty("size").GetInt64();
                if(url!="/downloads/Hearth-Client-Mods.zip"||!Regex.IsMatch(hash,@"\A[a-fA-F0-9]{64}\z")||!Regex.IsMatch(revision,@"\A[a-fA-F0-9]{64}\z")||size is <1 or >134217728||kind!=(mode=="plus"?"overlay":"full"))throw new InvalidDataException("Сервер сообщает некорректный клиентский набор модов.");
                var packages=new List<ClientPackage>();var ids=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                foreach(var package in c.GetProperty("packages").EnumerateArray())
                {
                    string id=package.GetProperty("id").GetString()??"",name=package.GetProperty("name").GetString()??"",version=package.GetProperty("version").GetString()??"";
                    if(id.Length is <1 or >201||name.Length is <1 or >200||version.Length is <1 or >80||new[]{id,name,version}.Any(v=>v.Any(char.IsControl))||!ids.Add(id)||packages.Count>=100)throw new InvalidDataException("Некорректный список клиентских модов.");
                    packages.Add(new(id,name,version));
                }
                bundle=new(url,hash.ToLowerInvariant(),size,revision.ToLowerInvariant(),kind,packages);
            }
            if(mode=="modded"&&bundle is null)throw new InvalidDataException("Сервер ещё не подготовил клиентский набор модов. Повторите позже.");
            string title=Text(root,"title",200,"Valheim"),address=Text(root,"address",260,"");
            string community=Text(root,"community_url",2000,"");
            if(!Uri.TryCreate(community,UriKind.Absolute,out var communityUri)||communityUri.Scheme is not ("http" or "https")||!string.IsNullOrEmpty(communityUri.UserInfo))community="";
            bool running=root.TryGetProperty("running",out var active)&&active.ValueKind==JsonValueKind.True;
            int? players=root.TryGetProperty("players",out var playerCount)&&playerCount.ValueKind==JsonValueKind.Number&&playerCount.TryGetInt32(out int number)&&number is >=0 and <=10000?number:null;
            return new(game,mode=="plus"?mod:null,mode,bundle,title,address,community.Length==0?null:community,running,players);
        }
        catch(Exception error) when(error is JsonException or InvalidOperationException or KeyNotFoundException or FormatException or OverflowException)
        {throw new InvalidDataException("Некорректный ответ сервера о клиентских модах.");}
    }
    static string Text(JsonElement root,string key,int maximum,string fallback)
    {
        if(!root.TryGetProperty(key,out var value)||value.ValueKind!=JsonValueKind.String)return fallback;
        string text=value.GetString()??fallback;
        return text.Length<=maximum&&!text.Any(char.IsControl)?text:fallback;
    }
    public Task<ServerVersion> Server(CancellationToken cancellationToken=default)=>ReadServer(cancellationToken);
    async Task<ServerVersion> ReadServer(CancellationToken cancellationToken)=>ParseServer(await Get(endpoint,1024*1024,cancellationToken:cancellationToken));
    public static ReleaseAsset ParseRelease(byte[] bytes,ServerVersion server)
    {
        using var json=JsonDocument.Parse(bytes);var root=json.RootElement;
        if(root.GetProperty("tag_name").GetString()!=server.Mod||root.GetProperty("draft").GetBoolean()||root.GetProperty("prerelease").GetBoolean())throw new InvalidDataException("Релиз не соответствует версии сервера.");
        var asset=root.GetProperty("assets").EnumerateArray().FirstOrDefault(a=>a.GetProperty("name").GetString()=="WindowsClient.zip");
        if(asset.ValueKind==JsonValueKind.Undefined)throw new InvalidDataException("У версии сервера нет WindowsClient.zip.");
        string url=asset.GetProperty("browser_download_url").GetString()??"";
        if(url!=$"https://github.com/Grantapher/ValheimPlus/releases/download/{server.Mod}/WindowsClient.zip")throw new InvalidDataException("Неожиданный адрес клиентского пакета.");
        string digest=server.Mod=="0.10.2.0"?KnownHash:asset.TryGetProperty("digest",out var d)&&d.ValueKind==JsonValueKind.String?d.GetString()!.Replace("sha256:",""):"";
        if(!Regex.IsMatch(digest,@"\A[a-fA-F0-9]{64}\z"))throw new InvalidDataException("GitHub не сообщает SHA-256 клиентского пакета. Установка отменена.");
        return new(url,digest);
    }
    public async Task<ReleaseAsset> Release(ServerVersion server,CancellationToken cancellationToken=default)
    {
        var release=await Get($"https://api.github.com/repos/Grantapher/ValheimPlus/releases/tags/{server.Mod}",1024*1024,cancellationToken:cancellationToken);
        return ParseRelease(release,server);
    }
    public async Task<byte[]> DownloadAsset(ReleaseAsset asset,CancellationToken cancellationToken=default)
    {
        var bytes=await Get(asset.Url,128L*1024*1024,cancellationToken:cancellationToken);
        VerifyHash(bytes,asset.Sha256);return bytes;
    }
    public async Task<byte[]> DownloadBundle(ClientBundle bundle,CancellationToken cancellationToken=default)
    {
        var bytes=await Get(new Uri(new Uri(endpoint),bundle.Url).AbsoluteUri,bundle.Size,true,cancellationToken);
        VerifyBundle(bytes,bundle);return bytes;
    }
    public static void VerifyBundle(byte[] bytes,ClientBundle bundle)
    {
        if(bytes.LongLength!=bundle.Size)throw new InvalidDataException("Размер клиентского набора не совпадает. Ничего не установлено.");
        VerifyHash(bytes,bundle.Sha256);
    }
    public static void VerifyHash(byte[] bytes,string hash){if(!Convert.ToHexString(SHA256.HashData(bytes)).Equals(hash,StringComparison.OrdinalIgnoreCase))throw new InvalidDataException("SHA-256 пакета не совпадает. Ничего не установлено.");}
}

public static class Installer
{
    public static bool IsGame(string path)=>File.Exists(Path.Combine(path,"valheim.exe"))&&Directory.Exists(Path.Combine(path,"valheim_Data"));
    public static string Hash(string path,CancellationToken cancellationToken=default)
    {
        cancellationToken.ThrowIfCancellationRequested();using var file=File.OpenRead(path);
        if(!cancellationToken.CanBeCanceled)return Convert.ToHexString(SHA256.HashData(file));
        using var hash=IncrementalHash.CreateHash(HashAlgorithmName.SHA256);byte[] buffer=new byte[65536];int count;
        while((count=file.Read(buffer))>0){cancellationToken.ThrowIfCancellationRequested();hash.AppendData(buffer,0,count);}
        cancellationToken.ThrowIfCancellationRequested();return Convert.ToHexString(hash.GetHashAndReset());
    }
    public static string Root(string path)=>Path.TrimEndingDirectorySeparator(Path.GetFullPath(path));
    public static void NoLinks(string path)
    {
        for(string? p=Path.GetFullPath(path);p!=null;p=Path.GetDirectoryName(p))
            if(new FileInfo(p).LinkTarget is not null||((File.Exists(p)||Directory.Exists(p))&&(File.GetAttributes(p)&FileAttributes.ReparsePoint)!=0))throw new IOException("Папки-ссылки не поддерживаются: "+p);
    }
    public static string SafePath(string root,string relative)
    {
        relative=relative.Replace('\\','/');
        var parts=relative.Split('/');
        if(string.IsNullOrEmpty(relative)||relative.Length>240||Path.IsPathRooted(relative)||parts.Any(p=>string.IsNullOrEmpty(p)||p is "." or ".."||p.EndsWith('.')||p.EndsWith(' ')||p.Any(c=>char.IsControl(c)||"<>:\"|?*".Contains(c))||p.IndexOfAny(Path.GetInvalidFileNameChars())>=0||Regex.IsMatch(p,@"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)",RegexOptions.IgnoreCase)))throw new InvalidDataException("Недопустимый путь: "+relative);
        if(!OperatingSystem.IsWindows())
        {
            string parent=Root(root);NoLinks(parent);
            foreach(string part in parts)
            {
                if(Directory.Exists(parent))
                foreach(string sibling in Directory.EnumerateFileSystemEntries(parent))
                {
                    string spelling=Path.GetFileName(sibling);
                    if(spelling.Equals(part,StringComparison.OrdinalIgnoreCase)&&!spelling.Equals(part,StringComparison.Ordinal))
                        throw new IOException("Коллизия регистра путей: "+relative);
                }
                parent=Path.Combine(parent,part);
            }
        }
        string path=Path.GetFullPath(Path.Combine(root,relative));
        if(!path.StartsWith(Root(root)+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase))throw new InvalidDataException("Путь вышел за папку установки.");
        NoLinks(path);return path;
    }
    public static (string Name,string Version)? AssemblyInfo(string path)
    {
        try{using var stream=File.OpenRead(path);using var pe=new PEReader(stream);if(!pe.HasMetadata)return null;var reader=pe.GetMetadataReader();if(!reader.IsAssembly)return null;var def=reader.GetAssemblyDefinition();return(reader.GetString(def.Name),def.Version.ToString());}
        catch(BadImageFormatException){return null;}
    }
    public static string ExistingMod(string game)
    {
        string plugins=Path.Combine(game,"BepInEx","plugins");NoLinks(plugins);
        if(!Directory.Exists(plugins))return "не установлен";
        var found=new List<string>();
        foreach(string file in SafeDlls(plugins))
        {var assembly=AssemblyInfo(file);if(assembly?.Name is "ValheimPlus" or "ValheimPlusGrantapher")found.Add(assembly.Value.Version);}
        return found.Count==0?"не установлен":string.Join(", ",found);
    }
    static IEnumerable<string> SafeDlls(string folder)
    {
        NoLinks(folder);
        foreach(var entry in Directory.EnumerateFileSystemEntries(folder))
        {
            NoLinks(entry);
            if(Directory.Exists(entry)){foreach(var dll in SafeDlls(entry))yield return dll;}
            else if(Path.GetExtension(entry).Equals(".dll",StringComparison.OrdinalIgnoreCase))yield return entry;
        }
    }
    public static void ValidateTarget(string game,bool checkClosed=true)
    {
        if(!IsGame(game))throw new IOException("Выберите папку Steam-версии Valheim: нужны valheim.exe и valheim_Data.");
        NoLinks(game);
        string core=SafePath(game,"BepInEx/core/BepInEx.dll");
        if(File.Exists(core)&&AssemblyInfo(core) is { } a && !a.Version.StartsWith("5."))throw new IOException("Обнаружена другая основная версия BepInEx. Используйте отдельную чистую установку игры.");
        string plugins=SafePath(game,"BepInEx/plugins");
        if(Directory.Exists(plugins))foreach(string file in SafeDlls(plugins))
        {
            var plugin=AssemblyInfo(file);
            bool isPlus=plugin?.Name is "ValheimPlus" or "ValheimPlusGrantapher" || Path.GetFileName(file).Equals("ValheimPlusGrantapher.dll",StringComparison.OrdinalIgnoreCase)||Path.GetFileName(file).Equals("ValheimPlus.dll",StringComparison.OrdinalIgnoreCase);
            if(isPlus&&!file.Equals(Path.Combine(plugins,"ValheimPlus.dll"),StringComparison.OrdinalIgnoreCase))throw new IOException("Найдена другая копия V+: "+file+". Уберите дубликат через свой менеджер модов или вручную перед установкой.");
        }
        if(checkClosed)CheckGameClosed();
    }
    public static void ValidateCompatibility(string game,string mode,InstallationInventory? inventory)
    {
        if(mode=="vanilla")return;
        ValidateTarget(game,false);
        const string relative="BepInEx/plugins/ValheimPlus.dll";
        string plus=SafePath(game,relative);
        if(mode=="modded"&&File.Exists(plus)&&!(inventory?.Files.Any(f=>f.Path.Equals(relative,StringComparison.OrdinalIgnoreCase)&&f.Sha256==Hash(plus))??false))
            throw new IOException("В игре есть пользовательский Valheim Plus. Уберите его через свой менеджер модов перед установкой набора BepInEx.");
    }
    public static void CheckGameClosed()=>HearthLauncher.PlatformIntegration.EnsureGameClosed();
    public static List<string> Extract(byte[] bytes,string stage,bool requirePlus=true,bool overlay=false)
    {
        Directory.CreateDirectory(stage);NoLinks(stage);
        using var zip=new ZipArchive(new MemoryStream(bytes),ZipArchiveMode.Read);
        if(zip.Entries.Count>5000||zip.Entries.Sum(e=>e.Length)>512L*1024*1024)throw new InvalidDataException("Архив слишком большой.");
        var result=new List<string>();var unique=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var spelling=new Dictionary<string,string>(StringComparer.OrdinalIgnoreCase);
        foreach(var entry in zip.Entries)
        {
            if(((entry.ExternalAttributes>>16)&0xf000)==0xa000||(entry.ExternalAttributes&(int)FileAttributes.ReparsePoint)!=0)throw new InvalidDataException("Ссылки в архиве запрещены.");
            string relative=entry.FullName.Replace('\\','/').TrimEnd('/');
            if(relative.Length==0)continue;
            string target=SafePath(stage,relative);
            if(!unique.Add(relative))throw new InvalidDataException("Повтор пути в архиве.");
            string[] parts=relative.Split('/');
            for(int n=1;n<=parts.Length;n++)
            {
                string prefix=string.Join('/',parts.Take(n));
                if(spelling.TryGetValue(prefix,out string? previous)&&previous!=prefix)throw new InvalidDataException("Коллизия регистра путей в архиве.");
                spelling[prefix]=prefix;
            }
            bool metadata=relative=="hearth-mods.json"&&!entry.FullName.EndsWith('/');
            bool allowed=metadata||relative is ".doorstop_version" or "doorstop_config.ini" or "winhttp.dll" || relative=="BepInEx"||relative.StartsWith("BepInEx/",StringComparison.OrdinalIgnoreCase)||relative=="doorstop_libs"||relative.StartsWith("doorstop_libs/",StringComparison.OrdinalIgnoreCase);
            if(!allowed)throw new InvalidDataException("Неожиданный файл клиентского пакета: "+relative);
            if(overlay&&!metadata&&!relative.StartsWith("BepInEx/plugins/HearthMods/",StringComparison.Ordinal)&&!(entry.FullName.EndsWith('/')&&new[]{"BepInEx","BepInEx/plugins","BepInEx/plugins/HearthMods"}.Contains(relative)))throw new InvalidDataException("Дополнительный набор может содержать только плагины HearthMods.");
            if(metadata){if(entry.Length>2*1024*1024)throw new InvalidDataException("Метаданные клиентского набора слишком большие.");using var input=entry.Open();input.CopyTo(Stream.Null);continue;}
            if(entry.FullName.EndsWith('/')){Directory.CreateDirectory(target);continue;}
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);entry.ExtractToFile(target);result.Add(relative);
        }
        var requiredFiles=overlay?Array.Empty<string>():requirePlus?new[]{"winhttp.dll","doorstop_config.ini","BepInEx/core/BepInEx.dll","BepInEx/plugins/ValheimPlus.dll"}:new[]{"winhttp.dll","doorstop_config.ini","BepInEx/core/BepInEx.dll"};
        foreach(string required in requiredFiles)
            if(!result.Contains(required,StringComparer.OrdinalIgnoreCase))throw new InvalidDataException("В клиентском пакете отсутствует "+required);
        return result;
    }
    public static void ValidatePayload(string stage,string? mod)
    {
        string plusPath=SafePath(stage,"BepInEx/plugins/ValheimPlus.dll");
        var plus=File.Exists(plusPath)?AssemblyInfo(plusPath):null;
        if(mod is not null&&(plus?.Name!="ValheimPlus"||plus?.Version!=mod))throw new InvalidDataException("Версия DLL в архиве не совпадает с сервером.");
        if(mod is null&&File.Exists(SafePath(stage,"BepInEx/plugins/ValheimPlus.dll")))throw new InvalidDataException("Набор BepInEx не должен содержать Valheim Plus.");
        string plugins=SafePath(stage,"BepInEx/plugins");
        if(Directory.Exists(plugins))foreach(string file in SafeDlls(plugins))
        {
            var assembly=AssemblyInfo(file);
            bool isPlus=assembly?.Name is "ValheimPlus" or "ValheimPlusGrantapher"||Path.GetFileName(file).Equals("ValheimPlus.dll",StringComparison.OrdinalIgnoreCase)||Path.GetFileName(file).Equals("ValheimPlusGrantapher.dll",StringComparison.OrdinalIgnoreCase);
            if(isPlus&&(mod is null||!file.Equals(plusPath,StringComparison.OrdinalIgnoreCase)))throw new InvalidDataException("В клиентском наборе найдена лишняя копия Valheim Plus.");
        }
        if(AssemblyInfo(SafePath(stage,"BepInEx/core/BepInEx.dll")) is not { } bepin || bepin.Name!="BepInEx"||!bepin.Version.StartsWith("5."))throw new InvalidDataException("Неожиданный пакет BepInEx.");
    }
    static void SaveJournal(string folder,Journal journal)
    {
        WriteJson(SafePath(folder,"journal.json"),journal);
    }
    public static void WriteJson<T>(string path,T value)
    {
        NoLinks(path);Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        byte[] bytes=JsonSerializer.SerializeToUtf8Bytes(value,new JsonSerializerOptions{WriteIndented=true});
        if(bytes.Length>8*1024*1024)throw new IOException("Метаданные установки слишком большие.");
        string temporary=path+".hearth-"+Guid.NewGuid().ToString("N");
        try{using(var stream=new FileStream(temporary,FileMode.CreateNew,FileAccess.Write,FileShare.None)){stream.Write(bytes);stream.Flush(true);}File.Move(temporary,path,true);}
        finally{if(File.Exists(temporary))File.Delete(temporary);}
    }
    static void CopyAtomic(string source,string dest)
    {
        NoLinks(source);NoLinks(dest);Directory.CreateDirectory(Path.GetDirectoryName(dest)!);
        string temporary=dest+".loki-"+Guid.NewGuid().ToString("N")+".tmp";
        try{File.Copy(source,temporary,false);File.Move(temporary,dest,true);}finally{if(File.Exists(temporary))File.Delete(temporary);}
    }
    public static string ManifestKey(ServerVersion version)=>Convert.ToHexString(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(
        string.Join("\n",version.Game,version.Mode,version.Mod??"",version.ClientMods?.Sha256??"",version.ClientMods?.Kind??""))));
    public static InstallationInventory? LoadInventory(string game)
    {
        string path=SafePath(game,".hearth-launcher/inventory.json");
        if(!File.Exists(path))return null;
        var inventory=ReadJson<InstallationInventory>(path);
        ValidateInventory(game,inventory);return inventory;
    }
    static void ValidateInventory(string game,InstallationInventory inventory)
    {
        if(inventory.Schema!=1||!PathEqual(Root(inventory.GamePath),Root(game))||inventory.Mode is not ("plus" or "modded")
            ||inventory.Files is null||inventory.Files.Count>5000||!IsHash(inventory.Manifest))throw new IOException("Повреждён список установленных файлов.");
        SourceClient.Endpoint(inventory.Website);
        var paths=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach(var file in inventory.Files)
            if(file is null||!paths.Add(file.Path)||!IsHash(file.Sha256)||SafePath(game,file.Path).Length==0)throw new IOException("Повреждён список установленных файлов.");
    }
    static bool IsHash(string? value)=>value is not null&&Regex.IsMatch(value,@"\A[a-fA-F0-9]{64}\z");
    static bool PathEqual(string first,string second)=>first.Equals(second,OperatingSystem.IsWindows()?StringComparison.OrdinalIgnoreCase:StringComparison.Ordinal);
    public static bool Mutable(string path)=>path.StartsWith("BepInEx/config/",StringComparison.OrdinalIgnoreCase);
    public static int DifferentFiles(string game,InstallationInventory inventory,CancellationToken cancellationToken=default)
    {
        ValidateInventory(game,inventory);int changed=0;
        foreach(var entry in inventory.Files)
        {
            cancellationToken.ThrowIfCancellationRequested();
            string target=SafePath(game,entry.Path);
            if(!File.Exists(target)||!Mutable(entry.Path)&&Hash(target,cancellationToken)!=entry.Sha256)changed++;
        }
        return changed;
    }
    public static bool InventoryMatches(string game,string website,ServerVersion version,InstallationInventory? inventory,CancellationToken cancellationToken=default)
        =>inventory is not null&&inventory.Website==website&&inventory.Mode==version.Mode&&inventory.Manifest==ManifestKey(version)&&DifferentFiles(game,inventory,cancellationToken)==0;

    public static InstallationResult Apply(string game,string stage,List<string> files,InstallationInventory desired,Action<string> log,
        Action? ensureClosed=null,Action<int>? beforeCopy=null)
    {
        game=Root(game);ValidateTarget(game,false);ensureClosed??=CheckGameClosed;ensureClosed();
        ValidateInventory(game,desired);
        string basePath=SafePath(game,".hearth-launcher");Directory.CreateDirectory(basePath);
        using var mutex=new FileStream(SafePath(basePath,"install.lock"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None);
        var previous=LatestBackup(game);
        if(previous!=null&&ReadJournal(previous).State=="installing")throw new IOException("Предыдущая установка была прервана. Сначала нажмите «Восстановить».");
        var before=LoadInventory(game);
        var owned=before?.Files??[];
        var selected=new HashSet<string>(files,StringComparer.OrdinalIgnoreCase);
        if(files.Count>5000||selected.Count!=files.Count||desired.Files.Count!=files.Count)throw new IOException("Недопустимый список файлов установки.");
        string plusPath="BepInEx/plugins/ValheimPlus.dll";
        string existingPlus=SafePath(game,plusPath);
        if(desired.Mode=="modded"&&File.Exists(existingPlus)&&!owned.Any(c=>c.Path.Equals(plusPath,StringComparison.OrdinalIgnoreCase)&&c.Sha256==Hash(existingPlus)))throw new IOException("В игре есть пользовательский Valheim Plus. Уберите его через свой менеджер модов перед установкой набора BepInEx.");
        string backup=SafePath(basePath,"backups/"+DateTime.UtcNow.ToString("yyyyMMdd-HHmmss-fffffff")+"-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(backup);
        var changes=new List<FileChange>();
        var afterFiles=new List<OwnedFile>();
        var expected=desired.Files.ToDictionary(f=>f.Path,StringComparer.OrdinalIgnoreCase);
        foreach(string relative in files)
        {
            string source=SafePath(stage,relative),target=SafePath(game,relative);
            if(!expected.TryGetValue(relative,out var entry)||Hash(source)!=entry.Sha256)throw new IOException("Файлы подготовки изменились во время установки.");
            if(Mutable(relative)&&File.Exists(target))
            {
                var prior=owned.FirstOrDefault(f=>f.Path.Equals(relative,StringComparison.OrdinalIgnoreCase));
                if(prior is not null)afterFiles.Add(prior);
                log("Сохранена конфигурация: "+relative);continue;
            }
            string? original=File.Exists(target)?Hash(target):null;
            afterFiles.Add(entry);
            if(original==entry.Sha256)continue;
            if(original is not null&&relative.StartsWith("BepInEx/plugins/HearthMods/",StringComparison.OrdinalIgnoreCase)
                &&!owned.Any(f=>f.Path.Equals(relative,StringComparison.OrdinalIgnoreCase)))
                throw new IOException("Путь клиентского мода занят чужим файлом: "+relative+". Сохраните его отдельно перед синхронизацией.");
            if(original!=null){string copy=SafePath(backup,"original/"+relative);Directory.CreateDirectory(Path.GetDirectoryName(copy)!);File.Copy(target,copy);if(Hash(copy)!=original)throw new IOException("Ошибка проверки резервной копии.");}
            changes.Add(new(relative,original,entry.Sha256));
        }
        foreach(var item in owned)
        {
            bool managed=item.Path.StartsWith("BepInEx/plugins/HearthMods/",StringComparison.OrdinalIgnoreCase)||(desired.Mode=="modded"&&item.Path.Equals(plusPath,StringComparison.OrdinalIgnoreCase));
            if(!managed||selected.Contains(item.Path))continue;
            string target=SafePath(game,item.Path);
            if(!File.Exists(target))continue;
            if(Hash(target)!=item.Sha256)throw new IOException("Устаревший файл набора изменён пользователем: "+item.Path+". Сохраните его отдельно перед синхронизацией.");
            string copy=SafePath(backup,"original/"+item.Path);Directory.CreateDirectory(Path.GetDirectoryName(copy)!);File.Copy(target,copy);
            if(Hash(copy)!=item.Sha256)throw new IOException("Ошибка проверки резервной копии.");
            changes.Add(new(item.Path,item.Sha256,null));
        }
        if(changes.Count>5000)throw new IOException("Слишком много изменений в клиентском наборе. Установка отменена.");
        var after=desired with{Files=afterFiles};
        var journal=new Journal(game,desired.Mode,"installing",changes,before,after);SaveJournal(backup,journal);
        try
        {
            int n=0;foreach(var change in changes)
            {
                ensureClosed();beforeCopy?.Invoke(n++);string target=SafePath(game,change.Path);
                string? current=File.Exists(target)?Hash(target):null;
                if(current!=change.OriginalHash)throw new IOException("Файл изменился во время установки: "+change.Path);
                if(change.InstalledHash is null){File.Delete(target);log("Удалён устаревший файл набора: "+change.Path);}
                else{CopyAtomic(SafePath(stage,change.Path),target);if(Hash(target)!=change.InstalledHash)throw new IOException("Ошибка проверки установленного файла.");log("Установлен: "+change.Path);}
            }
            WriteJson(SafePath(basePath,"inventory.json"),after);
            SaveJournal(backup,journal with{State="installed"});return new(backup,changes.Count,after.Files.Count);
        }
        catch(Exception installError)
        {
            try{RestoreFiles(game,backup,journal,ensureClosed);log("Изменения отменены; прежние файлы восстановлены.");}
            catch(Exception restoreError){throw new IOException("Установка прервана, автоматический откат не завершён. Копия: "+backup+". "+restoreError.Message,installError);}
            throw;
        }
    }
    static T ReadJson<T>(string path)
    {
        NoLinks(path);if(new FileInfo(path).Length>8*1024*1024)throw new IOException("Метаданные установки слишком большие.");
        try{return JsonSerializer.Deserialize<T>(File.ReadAllBytes(path))??throw new IOException("Повреждён журнал установки.");}
        catch(JsonException error){throw new IOException("Повреждён журнал установки.",error);}
    }
    static Journal ReadJournal(string backup)=>ReadJson<Journal>(SafePath(backup,"journal.json"));
    public static string? LatestBackup(string game)
    {
        string path=SafePath(game,".hearth-launcher/backups");if(!Directory.Exists(path))return null;
        return Directory.GetDirectories(path).Where(p=>{NoLinks(p);return File.Exists(SafePath(p,"journal.json"));}).OrderDescending(StringComparer.Ordinal).FirstOrDefault();
    }
    public static void EnsureRecovered(string game)
    {
        string? backup=LatestBackup(game);
        if(backup is not null&&ReadJournal(backup).State=="installing")throw new IOException("Предыдущая установка была прервана. Сначала нажмите «Восстановить».");
    }
    static void RestoreFiles(string game,string backup,Journal journal,Action ensureClosed)
    {
        if(!PathEqual(Root(journal.GamePath),Root(game))||journal.Files is null||journal.Files.Count>5000)throw new IOException("Копия относится к другой папке игры.");
        if(journal.BeforeInventory is not null)ValidateInventory(game,journal.BeforeInventory);
        var paths=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var observed=new Dictionary<string,string?>(StringComparer.OrdinalIgnoreCase);
        foreach(var change in journal.Files)
        {
            if(change is null||!paths.Add(change.Path)||change.OriginalHash is not null&&!IsHash(change.OriginalHash)||change.InstalledHash is not null&&!IsHash(change.InstalledHash))throw new IOException("Повреждён журнал копии.");
            string target=SafePath(game,change.Path);
            string? current=File.Exists(target)?Hash(target):null;
            observed[change.Path]=current;
            if(current is not null&&current!=change.InstalledHash&&current!=change.OriginalHash)throw new IOException("После установки файл изменился: "+change.Path+". Автоматическое восстановление отменено.");
            if(change.OriginalHash!=null&&Hash(SafePath(backup,"original/"+change.Path))!=change.OriginalHash)throw new IOException("Контрольная сумма резервной копии не совпадает.");
        }
        foreach(var change in journal.Files)
        {
            ensureClosed();string target=SafePath(game,change.Path);
            if((File.Exists(target)?Hash(target):null)!=observed[change.Path])
                throw new IOException("После установки файл изменился: "+change.Path+". Автоматическое восстановление отменено.");
            if(change.OriginalHash!=null)CopyAtomic(SafePath(backup,"original/"+change.Path),target);
            else if(File.Exists(target))File.Delete(target);
        }
        string inventoryPath=SafePath(game,".hearth-launcher/inventory.json");
        if(journal.BeforeInventory is null)File.Delete(inventoryPath);
        else WriteJson(inventoryPath,journal.BeforeInventory);
        SaveJournal(backup,journal with{State="restored"});
    }
    public static string Restore(string game,Action? ensureClosed=null)
    {
        game=Root(game);if(!IsGame(game))throw new IOException("Папка игры не найдена.");NoLinks(game);ensureClosed??=CheckGameClosed;ensureClosed();
        string folder=SafePath(game,".hearth-launcher");Directory.CreateDirectory(folder);
        using var mutex=new FileStream(SafePath(folder,"install.lock"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None);
        string backup=LatestBackup(game)??throw new IOException("Нет резервной копии этого инсталлятора.");var journal=ReadJournal(backup);
        if(journal.State=="restored")throw new IOException("Последняя установка уже отменена.");
        if(journal.State is not ("installing" or "installed"))throw new IOException("Повреждён журнал установки.");
        RestoreFiles(game,backup,journal,ensureClosed);return backup;
    }
}
