using System.Diagnostics;
using System.IO.Compression;
using System.Reflection.Metadata;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace LokiInstaller;

public record ServerVersion(string Game, string Mod);
public record ReleaseAsset(string Url, string Sha256);
public record FileChange(string Path, string? OriginalHash, string InstalledHash);
public record Journal(string GamePath, string Mod, string State, List<FileChange> Files);

public static class SteamFinder
{
    // Valve KeyValues: quoted/bare tokens, nested objects and line comments.
    public static Dictionary<string, object> ParseVdf(string text)
    {
        var tokens = new List<string>();
        for (int i=0;i<text.Length;)
        {
            if (char.IsWhiteSpace(text[i]) || text[i]=='\ufeff') { i++; continue; }
            if (text[i]=='/' && i+1<text.Length && text[i+1]=='/') { while(i<text.Length && text[i]!='\n')i++; continue; }
            if (text[i] is '{' or '}') { tokens.Add(text[i++].ToString()); continue; }
            var value=new System.Text.StringBuilder();
            if(text[i]=='"')
            {
                i++; bool closed=false;
                while(i<text.Length)
                {
                    char c=text[i++];
                    if(c=='"'){closed=true;break;}
                    if(c=='\\' && i<text.Length && (text[i]=='\\'||text[i]=='"'))c=text[i++];
                    value.Append(c);
                }
                if(!closed)throw new InvalidDataException("Повреждён файл библиотеки Steam.");
            }
            else while(i<text.Length && !char.IsWhiteSpace(text[i]) && text[i]!='{' && text[i]!='}')value.Append(text[i++]);
            tokens.Add(value.ToString());
        }
        int pos=0;
        Dictionary<string,object> Read(bool nested,int depth)
        {
            if(depth>32)throw new InvalidDataException("Слишком глубокий файл Steam.");
            var result=new Dictionary<string,object>(StringComparer.OrdinalIgnoreCase);
            while(pos<tokens.Count)
            {
                string key=tokens[pos++];
                if(key=="}"){if(!nested)throw new InvalidDataException("Некорректный VDF.");return result;}
                if(key=="{"||pos>=tokens.Count)throw new InvalidDataException("Некорректный VDF.");
                string value=tokens[pos++];
                result[key]=value=="{"?Read(true,depth+1):value;
            }
            if(nested)throw new InvalidDataException("Незакрытый VDF.");
            return result;
        }
        return Read(false,0);
    }
    public static IEnumerable<string> Libraries(string text)
    {
        var root=ParseVdf(text);
        if(!root.TryGetValue("libraryfolders",out var folders)||folders is not Dictionary<string,object> map)yield break;
        foreach(var pair in map.Where(p=>int.TryParse(p.Key,out _)))
        {
            if(pair.Value is string oldPath)yield return oldPath;
            else if(pair.Value is Dictionary<string,object> obj && obj.TryGetValue("path",out var path) && path is string s)yield return s;
        }
    }
    public static string? GameInLibrary(string library)
    {
        string manifest=Path.Combine(library,"steamapps","appmanifest_892970.acf");
        if(!File.Exists(manifest))return null;
        var root=ParseVdf(File.ReadAllText(manifest));
        if(!root.TryGetValue("AppState",out var state)||state is not Dictionary<string,object> app || !app.TryGetValue("appid",out var id)||id is not string appId||appId!="892970" || !app.TryGetValue("installdir",out var dir)||dir is not string name)return null;
        if(name.IndexOfAny(new[]{'\\','/',':','\0'})>=0||name is "." or "..")throw new InvalidDataException("Некорректная папка в манифесте Steam.");
        string path=Path.GetFullPath(Path.Combine(library,"steamapps","common",name));
        return Installer.IsGame(path)?path:null;
    }
    public static List<string> Find()
    {
        var roots=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach(var hive in new[]{RegistryHive.CurrentUser,RegistryHive.LocalMachine})
        foreach(var view in new[]{RegistryView.Registry32,RegistryView.Registry64})
        {
            try{using var key=RegistryKey.OpenBaseKey(hive,view).OpenSubKey(@"Software\Valve\Steam");
                if((key?.GetValue("SteamPath")??key?.GetValue("InstallPath")) is string p)roots.Add(p);
            }catch(System.Security.SecurityException){}catch(UnauthorizedAccessException){}
        }
        roots.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),"Steam"));
        roots.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),"Steam"));
        var libraries=new HashSet<string>(roots,StringComparer.OrdinalIgnoreCase);
        foreach(string root in roots)
        {
            string vdf=Path.Combine(root,"steamapps","libraryfolders.vdf");
            try{if(File.Exists(vdf))foreach(var path in Libraries(File.ReadAllText(vdf)))libraries.Add(path);}catch(IOException){}catch(InvalidDataException){}catch(UnauthorizedAccessException){}
        }
        var games=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach(string library in libraries)
        {
            try{var game=GameInLibrary(library);if(game!=null)games.Add(game);}catch(IOException){}catch(InvalidDataException){}catch(UnauthorizedAccessException){}catch(ArgumentException){}
        }
        return games.Order().ToList();
    }
}

public sealed class SourceClient : IDisposable
{
    public const string ServerUrl="https://loki.ach-play.ru/api/public";
    const string KnownHash="1f6f1944b2285c34d663cbaf4353c846cabd4c35b9549d9006dd302ee4bda79b";
    readonly HttpClient http=new(new HttpClientHandler{AllowAutoRedirect=false}){Timeout=TimeSpan.FromMinutes(3)};
    static readonly Regex VersionPattern=new(@"^\d+\.\d+\.\d+(?:\.\d+)?$",RegexOptions.CultureInvariant);
    public SourceClient(){http.DefaultRequestHeaders.UserAgent.ParseAdd("Loki-Mod-Installer/1.0");}
    public void Dispose()=>http.Dispose();
    static bool Allowed(Uri uri)=>uri.Scheme=="https"&&uri.Port==443&&string.IsNullOrEmpty(uri.UserInfo)&&new[]{"loki.ach-play.ru","api.github.com","github.com","release-assets.githubusercontent.com","objects.githubusercontent.com"}.Contains(uri.Host,StringComparer.OrdinalIgnoreCase);
    async Task<byte[]> Get(string address,long maximum)
    {
        var uri=new Uri(address);
        for(int redirects=0;redirects<6;redirects++)
        {
            if(!Allowed(uri))throw new InvalidDataException("Источник или перенаправление загрузки не разрешены.");
            using var response=await http.GetAsync(uri,HttpCompletionOption.ResponseHeadersRead);
            if((int)response.StatusCode is >=300 and <400)
            {
                var location=response.Headers.Location??throw new IOException("Пустое перенаправление.");
                var next=location.IsAbsoluteUri?location:new Uri(uri,location);
                // The server API must stay on the server host. GitHub assets may use its CDN.
                if(uri.Host=="loki.ach-play.ru"&&next.Host!=uri.Host)throw new IOException("API Loki перенаправляет на посторонний сайт.");
                uri=next;continue;
            }
            response.EnsureSuccessStatusCode();
            if(response.Content.Headers.ContentLength>maximum)throw new IOException("Слишком большой ответ загрузки.");
            using var input=await response.Content.ReadAsStreamAsync();using var output=new MemoryStream();
            byte[] buffer=new byte[65536];int count;
            using var timeout=new CancellationTokenSource(TimeSpan.FromMinutes(3));
            while((count=await input.ReadAsync(buffer,timeout.Token))>0){if(output.Length+count>maximum)throw new IOException("Превышен размер загрузки.");await output.WriteAsync(buffer.AsMemory(0,count),timeout.Token);}
            return output.ToArray();
        }
        throw new IOException("Слишком много перенаправлений.");
    }
    public static ServerVersion ParseServer(byte[] bytes)
    {
        using var json=JsonDocument.Parse(bytes);var root=json.RootElement;
        string game=root.TryGetProperty("game",out var g)&&g.ValueKind==JsonValueKind.String?g.GetString()!:"";
        string mod=root.TryGetProperty("mod",out var m)&&m.ValueKind==JsonValueKind.String?m.GetString()!:"";
        if(!VersionPattern.IsMatch(game)||!VersionPattern.IsMatch(mod))throw new InvalidDataException("Loki ещё не сообщает установленную версию игры и мода. Повторите позже.");
        return new(game,mod);
    }
    public Task<ServerVersion> Server()=>ReadServer();
    async Task<ServerVersion> ReadServer()=>ParseServer(await Get(ServerUrl,1024*1024));
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
    public async Task<(byte[] Data,ReleaseAsset Asset)> Download(ServerVersion server)
    {
        var release=await Get($"https://api.github.com/repos/Grantapher/ValheimPlus/releases/tags/{server.Mod}",1024*1024);
        var asset=ParseRelease(release,server);var bytes=await Get(asset.Url,128L*1024*1024);
        VerifyHash(bytes,asset.Sha256);return(bytes,asset);
    }
    public static void VerifyHash(byte[] bytes,string hash){if(!Convert.ToHexString(SHA256.HashData(bytes)).Equals(hash,StringComparison.OrdinalIgnoreCase))throw new InvalidDataException("SHA-256 пакета не совпадает. Ничего не установлено.");}
}

public static class Installer
{
    public static bool IsGame(string path)=>File.Exists(Path.Combine(path,"valheim.exe"))&&Directory.Exists(Path.Combine(path,"valheim_Data"));
    public static string Hash(string path){using var file=File.OpenRead(path);return Convert.ToHexString(SHA256.HashData(file));}
    public static string Root(string path)=>Path.TrimEndingDirectorySeparator(Path.GetFullPath(path));
    public static void NoLinks(string path)
    {
        for(string? p=Path.GetFullPath(path);p!=null;p=Path.GetDirectoryName(p))
            if((File.Exists(p)||Directory.Exists(p))&&(File.GetAttributes(p)&FileAttributes.ReparsePoint)!=0)throw new IOException("Папки-ссылки не поддерживаются: "+p);
    }
    public static string SafePath(string root,string relative)
    {
        relative=relative.Replace('\\','/');
        var parts=relative.Split('/');
        if(string.IsNullOrEmpty(relative)||Path.IsPathRooted(relative)||parts.Any(p=>string.IsNullOrEmpty(p)||p is "." or ".."||p.EndsWith('.')||p.EndsWith(' ')||p.IndexOfAny(Path.GetInvalidFileNameChars())>=0||Regex.IsMatch(p,@"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)",RegexOptions.IgnoreCase)))throw new InvalidDataException("Недопустимый путь: "+relative);
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
    public static void ValidateTarget(string game)
    {
        if(!IsGame(game))throw new IOException("Выберите папку Steam-версии Valheim: нужны valheim.exe и valheim_Data.");
        NoLinks(game);
        string core=Path.Combine(game,"BepInEx","core","BepInEx.dll");NoLinks(core);
        if(File.Exists(core)&&AssemblyInfo(core) is { } a && !a.Version.StartsWith("5."))throw new IOException("Обнаружена другая основная версия BepInEx. Используйте отдельную чистую установку игры.");
        string plugins=Path.Combine(game,"BepInEx","plugins");NoLinks(plugins);
        if(Directory.Exists(plugins))foreach(string file in SafeDlls(plugins))
        {
            var plugin=AssemblyInfo(file);
            bool isPlus=plugin?.Name is "ValheimPlus" or "ValheimPlusGrantapher" || Path.GetFileName(file).Equals("ValheimPlusGrantapher.dll",StringComparison.OrdinalIgnoreCase);
            if(isPlus&&!file.Equals(Path.Combine(plugins,"ValheimPlus.dll"),StringComparison.OrdinalIgnoreCase))throw new IOException("Найдена другая копия V+: "+file+". Уберите дубликат через свой менеджер модов или вручную перед установкой.");
        }
        CheckGameClosed();
    }
    public static void CheckGameClosed(){foreach(var process in Process.GetProcessesByName("valheim")){process.Dispose();throw new IOException("Закройте Valheim перед установкой или восстановлением.");}}
    public static List<string> Extract(byte[] bytes,string stage)
    {
        Directory.CreateDirectory(stage);NoLinks(stage);
        using var zip=new ZipArchive(new MemoryStream(bytes),ZipArchiveMode.Read);
        if(zip.Entries.Count>5000||zip.Entries.Sum(e=>e.Length)>512L*1024*1024)throw new InvalidDataException("Архив слишком большой.");
        var result=new List<string>();var unique=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach(var entry in zip.Entries)
        {
            if(((entry.ExternalAttributes>>16)&0xf000)==0xa000||(entry.ExternalAttributes&(int)FileAttributes.ReparsePoint)!=0)throw new InvalidDataException("Ссылки в архиве запрещены.");
            string relative=entry.FullName.Replace('\\','/').TrimEnd('/');
            if(relative.Length==0)continue;
            string target=SafePath(stage,relative);
            if(!unique.Add(relative))throw new InvalidDataException("Повтор пути в архиве.");
            bool allowed=relative is ".doorstop_version" or "doorstop_config.ini" or "winhttp.dll" || relative=="BepInEx"||relative.StartsWith("BepInEx/",StringComparison.OrdinalIgnoreCase)||relative=="doorstop_libs"||relative.StartsWith("doorstop_libs/",StringComparison.OrdinalIgnoreCase);
            if(!allowed)throw new InvalidDataException("Неожиданный файл клиентского пакета: "+relative);
            if(entry.FullName.EndsWith('/')){Directory.CreateDirectory(target);continue;}
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);entry.ExtractToFile(target);result.Add(relative);
        }
        foreach(string required in new[]{"winhttp.dll","doorstop_config.ini","BepInEx/core/BepInEx.dll","BepInEx/plugins/ValheimPlus.dll"})
            if(!result.Contains(required,StringComparer.OrdinalIgnoreCase))throw new InvalidDataException("В клиентском пакете отсутствует "+required);
        return result;
    }
    public static void ValidatePayload(string stage,string mod)
    {
        var plus=AssemblyInfo(SafePath(stage,"BepInEx/plugins/ValheimPlus.dll"));
        if(plus?.Name!="ValheimPlus"||plus?.Version!=mod)throw new InvalidDataException("Версия DLL в архиве не совпадает с сервером.");
        if(AssemblyInfo(SafePath(stage,"BepInEx/core/BepInEx.dll")) is not { } bepin || bepin.Name!="BepInEx"||!bepin.Version.StartsWith("5."))throw new InvalidDataException("Неожиданный пакет BepInEx.");
    }
    static void SaveJournal(string folder,Journal journal)
    {
        string file=SafePath(folder,"journal.json");string temp=SafePath(folder,"journal.tmp");File.WriteAllText(temp,JsonSerializer.Serialize(journal,new JsonSerializerOptions{WriteIndented=true}));File.Move(temp,file,true);
    }
    static void CopyAtomic(string source,string dest)
    {
        NoLinks(source);NoLinks(dest);Directory.CreateDirectory(Path.GetDirectoryName(dest)!);
        string temporary=dest+".loki-"+Guid.NewGuid().ToString("N")+".tmp";
        try{File.Copy(source,temporary,false);File.Move(temporary,dest,true);}finally{if(File.Exists(temporary))File.Delete(temporary);}
    }
    public static string Apply(string game,string stage,List<string> files,string mod,Action<string> log,Action<int>? beforeCopy=null)
    {
        game=Root(game);ValidateTarget(game);
        string basePath=SafePath(game,".loki-installer");Directory.CreateDirectory(basePath);
        using var mutex=new FileStream(SafePath(basePath,"install.lock"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None);
        var previous=LatestBackup(game);
        if(previous!=null&&ReadJournal(previous).State=="installing")throw new IOException("Предыдущая установка была прервана. Сначала нажмите «Восстановить».");
        string backup=SafePath(basePath,"backups/"+DateTime.UtcNow.ToString("yyyyMMdd-HHmmss-fffffff")+"-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(backup);
        var changes=new List<FileChange>();
        foreach(string relative in files)
        {
            string source=SafePath(stage,relative),target=SafePath(game,relative);
            if(relative.StartsWith("BepInEx/config/",StringComparison.OrdinalIgnoreCase)&&File.Exists(target)){log("Сохранена конфигурация: "+relative);continue;}
            string? original=File.Exists(target)?Hash(target):null;
            if(original!=null){string copy=SafePath(backup,"original/"+relative);Directory.CreateDirectory(Path.GetDirectoryName(copy)!);File.Copy(target,copy);if(Hash(copy)!=original)throw new IOException("Ошибка проверки резервной копии.");}
            changes.Add(new(relative,original,Hash(source)));
        }
        var journal=new Journal(game,mod,"installing",changes);SaveJournal(backup,journal);
        try
        {
            int n=0;foreach(var change in changes){CheckGameClosed();beforeCopy?.Invoke(n++);CopyAtomic(SafePath(stage,change.Path),SafePath(game,change.Path));log("Установлен: "+change.Path);}
            SaveJournal(backup,journal with{State="installed"});return backup;
        }
        catch(Exception installError)
        {
            try{RestoreFiles(game,backup,journal);log("Изменения отменены; прежние файлы восстановлены.");}
            catch(Exception restoreError){throw new IOException("Установка прервана, автоматический откат не завершён. Копия: "+backup+". "+restoreError.Message,installError);}
            throw;
        }
    }
    static Journal ReadJournal(string backup)=>JsonSerializer.Deserialize<Journal>(File.ReadAllText(SafePath(backup,"journal.json")))??throw new IOException("Повреждён журнал копии.");
    public static string? LatestBackup(string game)
    {
        string path=SafePath(game,".loki-installer/backups");if(!Directory.Exists(path))return null;
        return Directory.GetDirectories(path).Where(p=>{NoLinks(p);return File.Exists(SafePath(p,"journal.json"));}).OrderDescending(StringComparer.Ordinal).FirstOrDefault();
    }
    static void RestoreFiles(string game,string backup,Journal journal)
    {
        if(!Root(journal.GamePath).Equals(Root(game),StringComparison.OrdinalIgnoreCase)||journal.Files.Count>5000)throw new IOException("Копия относится к другой папке игры.");
        foreach(var change in journal.Files)
        {
            string target=SafePath(game,change.Path);
            if(File.Exists(target)){string current=Hash(target);if(current!=change.InstalledHash&&current!=change.OriginalHash)throw new IOException("После установки файл изменился: "+change.Path+". Автоматическое восстановление отменено.");}
            if(change.OriginalHash!=null&&Hash(SafePath(backup,"original/"+change.Path))!=change.OriginalHash)throw new IOException("Контрольная сумма резервной копии не совпадает.");
        }
        foreach(var change in journal.Files)
        {
            CheckGameClosed();string target=SafePath(game,change.Path);
            if(change.OriginalHash!=null)CopyAtomic(SafePath(backup,"original/"+change.Path),target);
            else if(File.Exists(target))File.Delete(target);
        }
        SaveJournal(backup,journal with{State="restored"});
    }
    public static string Restore(string game)
    {
        game=Root(game);if(!IsGame(game))throw new IOException("Папка игры не найдена.");NoLinks(game);CheckGameClosed();
        string folder=SafePath(game,".loki-installer");Directory.CreateDirectory(folder);
        using var mutex=new FileStream(SafePath(folder,"install.lock"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None);
        string backup=LatestBackup(game)??throw new IOException("Нет резервной копии этого инсталлятора.");var journal=ReadJournal(backup);
        if(journal.State=="restored")throw new IOException("Последняя установка уже отменена.");
        RestoreFiles(game,backup,journal);return backup;
    }
}
