using System.Diagnostics;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32;

namespace HearthLauncherSetup;

static class Program
{
    [STAThread]
    static int Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        if (args is ["--shortcut-smoke", var directory])
        {
            SetupForm.ShortcutSmoke(directory);
            return 0;
        }
        string? language = args.Length == 3 && args[0] == "--render-preview" ? args[2] : null;
        using var form = new SetupForm(language);
        if (args is ["--smoke-test"])
        {
            form.CreateControl();
            if (form.Icon is null || form.Text.Length == 0) throw new InvalidOperationException("Setup UI is incomplete.");
            using var icon = new Icon(typeof(Program).Assembly.GetManifestResourceStream("HearthLauncherSetup.Icon.ico")!);
            Console.WriteLine("Setup window and embedded icon loaded.");
            return 0;
        }
        if (args.Length is 2 or 3 && args[0] == "--render-preview")
        {
            if (language is not null and not ("ru" or "en")) throw new ArgumentException("Preview language must be ru or en.");
            // A zero-opacity form allows WinForms to lay out and paint all child controls.
            // No interactive window or taskbar entry is displayed; setup is never invoked.
            form.ShowInTaskbar = false; form.Opacity = 0; form.Show();
            Application.DoEvents(); form.PerformLayout(); form.Update();
            using var bitmap = new Bitmap(form.Width, form.Height);
            form.DrawToBitmap(bitmap, new Rectangle(Point.Empty, bitmap.Size));
            string output = Path.GetFullPath(args[1]);
            Directory.CreateDirectory(Path.GetDirectoryName(output)!);
            bitmap.Save(output, System.Drawing.Imaging.ImageFormat.Png);
            form.Close();
            Console.WriteLine("Rendered offline setup preview: " + output);
            return 0;
        }
        Application.Run(form);
        return 0;
    }

    internal static byte[] Resource(string name)
    {
        using var input = Assembly.GetExecutingAssembly().GetManifestResourceStream("HearthLauncherSetup." + name)
            ?? throw new IOException("Missing setup resource: " + name);
        using var output = new MemoryStream(); input.CopyTo(output); return output.ToArray();
    }
}

sealed class SetupForm : Form
{
    readonly Label heading = new() { AutoSize = true, Font = new Font("Segoe UI", 23, FontStyle.Bold), ForeColor = Color.FromArgb(231, 190, 118) };
    readonly Label description = new() { AutoSize = true, MaximumSize = new Size(560, 0), Margin = new Padding(0, 14, 0, 16) };
    readonly Label destination = new() { AutoSize = true, MaximumSize = new Size(560, 0), ForeColor = Color.FromArgb(169, 181, 168), Margin = new Padding(0, 0, 0, 20) };
    readonly Button install = new() { AutoSize = true, Padding = new Padding(12, 7, 12, 7) };
    readonly CheckBox launch = new() { AutoSize = true, Checked = true, Margin = new Padding(0, 18, 0, 10) };
    readonly Label status = new() { AutoSize = true, MaximumSize = new Size(560, 0), Margin = new Padding(0, 16, 0, 0) };
    readonly ComboBox language = new() { DropDownStyle = ComboBoxStyle.DropDownList, Width = 85 };
    bool busy, completed;
    bool English => language.SelectedIndex == 1;
    readonly InstallationPaths paths = Installation.DefaultPaths();

    public SetupForm(string? initialLanguage = null)
    {
        ClientSize = new Size(620, 370); MinimumSize = new Size(640, 410); MaximumSize = new Size(920, 650);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(24, 39, 31); ForeColor = Color.FromArgb(232, 238, 230); Font = new Font("Segoe UI", 10);
        using var stream = new MemoryStream(Program.Resource("Icon.ico")); Icon = new Icon(stream);
        language.Items.AddRange(["Русский", "English"]);
        language.SelectedIndex = initialLanguage == "ru" || (initialLanguage is null && System.Globalization.CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "ru") ? 0 : 1;
        var layout = new FlowLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(28), FlowDirection = FlowDirection.TopDown, WrapContents = false, AutoScroll = true };
        var title = new FlowLayoutPanel { AutoSize = true, FlowDirection = FlowDirection.LeftToRight, WrapContents = false };
        title.Controls.Add(heading); title.Controls.Add(language);
        install.BackColor = Color.FromArgb(231, 190, 118); install.ForeColor = BackColor; install.FlatStyle = FlatStyle.Flat;
        layout.Controls.AddRange([title, description, destination, launch, install, status]); Controls.Add(layout);
        language.SelectedIndexChanged += (_, _) => Translate();
        install.Click += async (_, _) => await Install();
        FormClosing += (_, args) => { if (busy) args.Cancel = true; };
        Translate();
    }

    void Translate()
    {
        Text = English ? "Hearth Launcher — Setup" : "Hearth Launcher — Установка";
        heading.Text = "HEARTH LAUNCHER";
        description.Text = English
            ? "Install Hearth Launcher 1.1.0 for this Windows user. Desktop and Start menu shortcuts will be created. Reinstall to update; server profiles remain."
            : "Установите Hearth Launcher 1.1.0 для текущего пользователя Windows. Появятся ярлыки на рабочем столе и в меню «Пуск». Повторная установка обновит лаунчер; профили сохранятся.";
        destination.Text = (English ? "Installation folder: " : "Папка установки: ") + paths.Directory;
        launch.Text = English ? "Open launcher after installation" : "Открыть лаунчер после установки";
        install.Text = completed ? (English ? "Close" : "Закрыть") : (English ? "Install" : "Установить");
    }

    async Task Install()
    {
        if (completed) { Close(); return; }
        if (busy) return;
        busy = true; install.Enabled = false; language.Enabled = false;
        status.Text = English ? "Verifying and installing…" : "Проверяем и устанавливаем…";
        try
        {
            byte[] payload = await Task.Run(() => Program.Resource("Payload.zip"));
            string digest = Encoding.UTF8.GetString(Program.Resource("Payload.sha256")).Trim();
            // Shortcut COM objects must be created on this STA thread.
            Installation.Install(payload, digest, Program.Resource("Uninstall.ps1"), paths, locations => CreateShortcutsAndRegistration(locations));
            completed = true;
            status.Text = English ? "Installed. Profiles, Steam and game files were preserved." : "Готово. Профили, Steam и файлы игры сохранены.";
            if (launch.Checked) Process.Start(new ProcessStartInfo(Path.Combine(paths.Directory, "Hearth-Launcher.exe")) { UseShellExecute = true });
        }
        catch (Exception error)
        {
            status.Text = error.Message;
            MessageBox.Show(this, (English ? "Close Hearth Launcher before updating. " : "Перед обновлением закройте Hearth Launcher. ") + error.Message, Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        finally { busy = false; install.Enabled = true; language.Enabled = true; Translate(); }
    }

    static void CreateShortcutsAndRegistration(InstallationPaths locations, bool register = true, Action? afterShortcuts = null)
    {
        string executable = Path.Combine(locations.Directory, "Hearth-Launcher.exe");
        Type shellType = Type.GetTypeFromProgID("WScript.Shell") ?? throw new IOException("Windows shortcuts are unavailable.");
        object shellObject = Activator.CreateInstance(shellType)!;
        var previousLinks = new Dictionary<string, byte[]?>();
        const string registryPath = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\HearthLauncher";
        using RegistryKey? previousKey = register ? Registry.CurrentUser.OpenSubKey(registryPath) : null;
        var previousRegistration = previousKey?.GetValueNames().ToDictionary(name => name,
            name => (Value: previousKey.GetValue(name)!, Kind: previousKey.GetValueKind(name)));
        bool changedRegistration = false;
        try
        {
            dynamic shell = shellObject;
            foreach (string directory in new[] { locations.Desktop, locations.Menu })
            {
                Installation.NoLinks(directory); Directory.CreateDirectory(directory);
                string link = Path.Combine(directory, "Hearth Launcher.lnk"); Installation.NoLinks(link);
                if (File.Exists(link))
                {
                    if (new FileInfo(link).Length > 64 * 1024) throw new IOException("Unexpected shortcut size: " + link);
                    dynamic existing = shell.CreateShortcut(link);
                    try
                    {
                        if (!string.Equals((string)existing.TargetPath, executable, StringComparison.OrdinalIgnoreCase))
                            throw new IOException("A shortcut named Hearth Launcher already belongs to another program: " + link);
                    }
                    finally { Marshal.FinalReleaseComObject(existing); }
                }
                previousLinks.Add(link, File.Exists(link) ? File.ReadAllBytes(link) : null);
            }
            // Ownership of both shortcuts is checked before either is replaced.
            foreach (string link in previousLinks.Keys)
            {
                string directory = Path.GetDirectoryName(link)!;
                string temporary = Path.Combine(directory, ".hearth-shortcut-" + Guid.NewGuid().ToString("N") + ".lnk");
                try
                {
                    dynamic shortcut = shell.CreateShortcut(temporary);
                    try
                    {
                        shortcut.TargetPath = executable; shortcut.WorkingDirectory = locations.Directory;
                        shortcut.IconLocation = Path.Combine(locations.Directory, "hearth.ico") + ",0";
                        shortcut.Description = "Hearth Launcher — Valheim"; shortcut.Save();
                    }
                    finally { Marshal.FinalReleaseComObject(shortcut); }
                    File.Move(temporary, link, true);
                }
                finally { if (File.Exists(temporary)) File.Delete(temporary); }
            }
            afterShortcuts?.Invoke();
            if (!register) return;
            using RegistryKey key = Registry.CurrentUser.CreateSubKey(registryPath);
            changedRegistration = true;
            key.SetValue("DisplayName", "Hearth Launcher"); key.SetValue("DisplayVersion", "1.1.0");
            key.SetValue("Publisher", "Hearth project"); key.SetValue("InstallLocation", locations.Directory);
            key.SetValue("DisplayIcon", Path.Combine(locations.Directory, "hearth.ico"));
            string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell/v1.0/powershell.exe");
            key.SetValue("UninstallString", $"\"{powershell}\" -NoProfile -ExecutionPolicy Bypass -File \"{Path.Combine(locations.Directory, "uninstall.ps1")}\"");
            key.SetValue("NoModify", 1, RegistryValueKind.DWord); key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
        }
        catch
        {
            foreach (var (link, previous) in previousLinks)
            {
                Installation.NoLinks(link);
                if (previous is null) { if (File.Exists(link)) File.Delete(link); }
                else File.WriteAllBytes(link, previous);
            }
            if (changedRegistration)
            {
                if (previousRegistration is null) Registry.CurrentUser.DeleteSubKeyTree(registryPath, false);
                else
                {
                    using RegistryKey key = Registry.CurrentUser.CreateSubKey(registryPath);
                    foreach (string name in key.GetValueNames())
                        if (!previousRegistration.ContainsKey(name)) key.DeleteValue(name);
                    foreach (var (name, previous) in previousRegistration) key.SetValue(name, previous.Value, previous.Kind);
                }
            }
            throw;
        }
        finally { Marshal.FinalReleaseComObject(shellObject); }
    }

    internal static void ShortcutSmoke(string parentDirectory)
    {
        string parent = Path.GetFullPath(parentDirectory);
        Installation.NoLinks(parent); Directory.CreateDirectory(parent);
        string root = Path.Combine(parent, "hearth-shortcut-smoke-" + Guid.NewGuid().ToString("N"));
        var locations = new InstallationPaths(Path.Combine(root, "program"), Path.Combine(root, "desktop"), Path.Combine(root, "menu"));
        int passed = 0;
        void Assert(bool condition) { if (!condition) throw new IOException("Shortcut smoke assertion failed."); passed++; }
        try
        {
            byte[] payload = Program.Resource("Payload.zip");
            string hash = Encoding.UTF8.GetString(Program.Resource("Payload.sha256")).Trim();
            Installation.Install(payload, hash, Program.Resource("Uninstall.ps1"), locations,
                paths => CreateShortcutsAndRegistration(paths, register: false));
            Type type = Type.GetTypeFromProgID("WScript.Shell")!;
            dynamic shell = Activator.CreateInstance(type)!;
            string executable = Path.Combine(locations.Directory, "Hearth-Launcher.exe");
            string desktopLink = Path.Combine(locations.Desktop, "Hearth Launcher.lnk");
            string menuLink = Path.Combine(locations.Menu, "Hearth Launcher.lnk");
            try
            {
                foreach (string link in new[] { desktopLink, menuLink })
                {
                    dynamic shortcut = shell.CreateShortcut(link);
                    try
                    {
                        Assert((string)shortcut.TargetPath == executable);
                        Assert((string)shortcut.IconLocation == Path.Combine(locations.Directory, "hearth.ico") + ",0");
                    }
                    finally { Marshal.FinalReleaseComObject(shortcut); }
                }
                byte[] desktopBefore = File.ReadAllBytes(desktopLink), menuBefore = File.ReadAllBytes(menuLink);
                dynamic foreign = shell.CreateShortcut(menuLink);
                try { foreign.TargetPath = Path.Combine(root, "foreign.exe"); foreign.Save(); }
                finally { Marshal.FinalReleaseComObject(foreign); }
                byte[] foreignBefore = File.ReadAllBytes(menuLink);
                bool rejected = false;
                try { CreateShortcutsAndRegistration(locations, register: false); } catch (IOException) { rejected = true; }
                Assert(rejected && File.ReadAllBytes(desktopLink).SequenceEqual(desktopBefore) && File.ReadAllBytes(menuLink).SequenceEqual(foreignBefore));
                File.WriteAllBytes(menuLink, menuBefore);
                bool rolledBack = false;
                try { CreateShortcutsAndRegistration(locations, register: false, afterShortcuts: () => throw new IOException("Injected shortcut failure")); }
                catch (IOException) { rolledBack = true; }
                Assert(rolledBack && File.ReadAllBytes(desktopLink).SequenceEqual(desktopBefore) && File.ReadAllBytes(menuLink).SequenceEqual(menuBefore));
            }
            finally { Marshal.FinalReleaseComObject(shell); }
            File.WriteAllText(Path.Combine(parent, "shortcut-smoke.txt"), $"PASS {passed} real Windows shortcut checks in isolated folders; no real desktop, registry, Steam or game writes.\n");
        }
        finally
        {
            string resolved = Path.GetFullPath(root);
            if (!resolved.StartsWith(parent + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                || !Path.GetFileName(resolved).StartsWith("hearth-shortcut-smoke-", StringComparison.Ordinal)) throw new IOException("Unsafe smoke cleanup.");
            foreach (string path in Directory.Exists(root) ? Directory.EnumerateFileSystemEntries(root, "*", SearchOption.AllDirectories) : []) Installation.NoLinks(path);
            if (Directory.Exists(root)) Directory.Delete(root, true);
        }
    }
}
