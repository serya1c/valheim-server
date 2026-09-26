using System.Drawing;
using System.Windows.Forms;
namespace LokiInstaller;

static class Program
{
    [STAThread]
    static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        using var form=new MainForm();
        if(args.Contains("--smoke-test")){form.CreateControl();File.WriteAllText(Path.Combine(AppContext.BaseDirectory,"ui-smoke.txt"),"OK: "+form.Text);return;}
        Application.Run(form);
    }
}

sealed class MainForm : Form
{
    readonly ComboBox folder=new(){Dock=DockStyle.Fill};
    readonly Label server=new(){AutoSize=true,Text="Версия сервера ещё не проверена",Margin=new(0,14,0,8)};
    readonly Label local=new(){AutoSize=true,Text="Выберите папку игры",Margin=new(0,4,0,12)};
    readonly TextBox log=new(){Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Vertical,Dock=DockStyle.Fill,BackColor=Color.FromArgb(17,27,27),ForeColor=Color.Gainsboro,BorderStyle=BorderStyle.FixedSingle};
    readonly Button check=new(){Text="Проверить сервер",AutoSize=true};
    readonly Button install=new(){Text="Установить мод Loki",AutoSize=true};
    readonly Button restore=new(){Text="Восстановить файлы",AutoSize=true};
    readonly Button browse=new(){Text="Выбрать папку…",AutoSize=true};
    readonly ProgressBar progress=new(){Dock=DockStyle.Fill,Height=8,Style=ProgressBarStyle.Marquee,Visible=false};
    bool busy;
    ServerVersion? version;
    public MainForm()
    {
        Text="Loki — подготовка к приключению";ClientSize=new(830,650);MinimumSize=new(720,600);StartPosition=FormStartPosition.CenterScreen;
        BackColor=Color.FromArgb(25,38,38);ForeColor=Color.FromArgb(237,229,210);Font=new("Segoe UI",10);
        var layout=new TableLayoutPanel{Dock=DockStyle.Fill,Padding=new(24),ColumnCount=1,RowCount=9};
        for(int i=0;i<9;i++)layout.RowStyles.Add(new(i==7?SizeType.Percent:SizeType.AutoSize,i==7?100:0));
        layout.Controls.Add(new Label{Text="ᛟ  LOKI  /  VALHEIM PLUS",Font=new("Segoe UI",23,FontStyle.Bold),AutoSize=true,ForeColor=Color.FromArgb(231,181,98)},0,0);
        layout.Controls.Add(new Label{Text="Установщик для Steam · Windows 10/11 x64\nНаходит игру и устанавливает версию V+, которая используется на loki.ach-play.ru.",AutoSize=true,Margin=new(0,10,0,20)},0,1);
        var location=new TableLayoutPanel{Dock=DockStyle.Top,AutoSize=true,ColumnCount=2};location.ColumnStyles.Add(new(SizeType.Percent,100));location.ColumnStyles.Add(new(SizeType.AutoSize));location.Controls.Add(folder,0,0);location.Controls.Add(browse,1,0);layout.Controls.Add(location,0,2);
        layout.Controls.Add(local,0,3);layout.Controls.Add(server,0,4);
        var actions=new FlowLayoutPanel{Dock=DockStyle.Top,AutoSize=true,Margin=new(0,4,0,12)};actions.Controls.AddRange([check,install,restore]);layout.Controls.Add(actions,0,5);layout.Controls.Add(progress,0,6);layout.Controls.Add(log,0,7);
        layout.Controls.Add(new Label{Text="Закройте Valheim перед установкой. Заменяемые файлы сохраняются в резервную копию.\nИгру обновляет Steam. После установки запускайте Valheim обычным способом через Steam.",AutoSize=true,Margin=new(0,14,0,0)},0,8);Controls.Add(layout);
        foreach(var b in new[]{check,install,restore,browse}){b.BackColor=Color.FromArgb(223,173,91);b.ForeColor=Color.FromArgb(17,27,27);b.FlatStyle=FlatStyle.Flat;b.Padding=new(7);}
        browse.Click+=(_,_)=>{using var dialog=new FolderBrowserDialog{Description="Выберите папку с valheim.exe",UseDescriptionForTitle=true};if(dialog.ShowDialog(this)==DialogResult.OK)folder.Text=dialog.SelectedPath;};
        folder.TextChanged+=(_,_)=>RefreshLocal();
        check.Click+=async(_,_)=>await Run(async()=>{using var source=new SourceClient();version=await source.Server();ShowVersion();Write("Связь с Loki установлена.");});
        install.Click+=async(_,_)=>await Run(Install);
        restore.Click+=async(_,_)=>{if(MessageBox.Show(this,"Отменить последнюю установку Loki в выбранной папке? Файлы, изменённые после установки, автоматически не заменяются.","Восстановление",MessageBoxButtons.YesNo,MessageBoxIcon.Question)==DialogResult.Yes)await Run(async()=>{string game=folder.Text;string backup=await Task.Run(()=>Installer.Restore(game));Write("Восстановлено из: "+backup);RefreshLocal();});};
        FormClosing+=(_,e)=>{if(busy){e.Cancel=true;MessageBox.Show(this,"Дождитесь завершения операции: файлы могут устанавливаться или восстанавливаться.","Loki");}};
        Shown+=async(_,_)=>await Run(async()=>{var games=await Task.Run(SteamFinder.Find);folder.Items.AddRange(games.Cast<object>().ToArray());if(games.Count>0)folder.SelectedIndex=0;else Write("Steam-версия Valheim не найдена автоматически. Выберите её папку вручную.");using var source=new SourceClient();version=await source.Server();ShowVersion();});
    }
    void Write(string text){if(InvokeRequired){BeginInvoke(()=>Write(text));return;}log.AppendText($"[{DateTime.Now:HH:mm:ss}] {text}\r\n");}
    void ShowVersion()=>server.Text=$"На сервере: Valheim {version!.Game}  ·  Valheim Plus {version.Mod}";
    void RefreshLocal(){try{local.Text=Installer.IsGame(folder.Text)?"V+ в выбранной папке: "+Installer.ExistingMod(folder.Text):"Нужна папка с valheim.exe и valheim_Data";}catch(Exception e){local.Text="Не удалось прочитать мод: "+e.Message;}}
    async Task Run(Func<Task> action)
    {
        if(busy)return;busy=true;progress.Visible=true;foreach(var c in new Control[]{check,install,restore,browse,folder})c.Enabled=false;
        try{await action();}
        catch(Exception e){string message=e is HttpRequestException or TaskCanceledException?"Не удалось связаться с Loki или GitHub. Проверьте интернет и повторите позже. "+e.Message:e is UnauthorizedAccessException?"Нет доступа к файлам выбранной папки. Проверьте права доступа. "+e.Message:e.Message;Write("Ошибка: "+message);MessageBox.Show(this,message,"Loki — операция не завершена",MessageBoxButtons.OK,MessageBoxIcon.Warning);}
        finally{busy=false;progress.Visible=false;foreach(var c in new Control[]{check,install,restore,browse,folder})c.Enabled=true;}
    }
    async Task Install()
    {
        string game=Installer.Root(folder.Text);await Task.Run(()=>Installer.ValidateTarget(game));
        using var source=new SourceClient();version=await source.Server();ShowVersion();var selected=version;
        if(MessageBox.Show(this,$"Установить Valheim Plus {selected.Mod} и BepInEx в:\n{game}\n\nДля входа нужна Valheim {selected.Game}. Заменяемые файлы будут сохранены; существующие конфигурации сохранятся.","Установка мода Loki",MessageBoxButtons.YesNo,MessageBoxIcon.Question)!=DialogResult.Yes)return;
        Write("Загружаем официальный WindowsClient.zip для V+ "+selected.Mod+"…");
        var download=await source.Download(selected);Write("SHA-256 пакета проверен.");
        string cache=Path.GetFullPath(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"LokiInstaller","cache"));
        string stage=Installer.SafePath(cache,Guid.NewGuid().ToString("N"));
        try
        {
            var files=await Task.Run(()=>{var result=Installer.Extract(download.Data,stage);Installer.ValidatePayload(stage,selected.Mod);return result;});
            if(await source.Server()!=selected)throw new IOException("Версии сервера изменились во время загрузки. Повторите установку.");
            string backup=await Task.Run(()=>Installer.Apply(game,stage,files,selected.Mod,Write));
            Write("Готово! Резервная копия: "+backup);RefreshLocal();MessageBox.Show(this,"Мод установлен. Запустите Valheim через Steam и подключитесь к loki.ach-play.ru:2456. Пароль можно получить в Discord проекта.","До встречи у очага!",MessageBoxButtons.OK,MessageBoxIcon.Information);
        }
        finally
        {
            // Only this run's randomly named staging directory may be removed.
            if(stage.StartsWith(cache+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)&&Directory.Exists(stage))
            {try{Installer.NoLinks(stage);Directory.Delete(stage,true);}catch(IOException){Write("Временные файлы остались: "+stage);}catch(UnauthorizedAccessException){Write("Временные файлы остались: "+stage);}}
        }
    }
}
