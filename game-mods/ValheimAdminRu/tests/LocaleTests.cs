using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text.RegularExpressions;
using ValheimAdminRu;

internal static class LocaleTests
{
    private static int checks;
    private static void Equal(string expected, string actual)
    {
        checks++;
        if (expected != actual) throw new Exception("Expected: " + expected + "\nActual: " + actual);
    }
    private static void True(bool value, string message)
    { checks++; if (!value) throw new Exception(message); }

    private static int Main()
    {
        Locale.SetLanguage("ru");
        Equal("Здоровье восстановлено.", Locale.Translate("Здоровье восстановлено."));
        True(Locale.SetLanguage(" EN "), "Language codes should accept case and whitespace.");
        Equal("Health restored.", Locale.Translate("Здоровье восстановлено."));
        True(!Locale.SetLanguage("de"), "Unsupported languages must be rejected.");
        Equal("en", Locale.Language);
        Equal(null, Locale.Translate(null));
        Equal("", Locale.Translate(""));

        // Dynamic server text uses the recipient's language while captures remain literal.
        const string name = "Владелец {0} $1 AdminRu_SuperHammer";
        Equal("Waypoint “" + name + "” saved for this world.", Locale.Translate("Точка «" + name + "» сохранена для этого мира."));
        Equal("Waypoint “Ошибка: Игрок” deleted.", Locale.Translate("Точка «Ошибка: Игрок» удалена."));
        Equal("My name is Игрок; AdminRu_SuperHammer", Locale.Translate("My name is Игрок; AdminRu_SuperHammer"));
        Equal("Client confirmed: God mode enabled.", Locale.Translate("Подтверждено клиентом: Бессмертие включено."));
        Equal("Error: Rejected: Invalid command parameters.", Locale.Translate("Ошибка: Отклонено: Недопустимые параметры команды."));
        Equal("Admin panel connected. Role: Builder.", Locale.Translate("Админ-панель подключена. Роль: Строитель."));
        Equal("Client and server versions must match. Required: mod 0.4.0, Valheim 1.0.17 (server). Client: mod 0.3.1, Valheim 1.0.16.",
            Locale.Translate("Версии клиента и сервера должны совпадать. Требуются мод 0.4.0 и Valheim 1.0.17 (версия сервера). На клиенте: мод 0.3.1, Valheim 1.0.16."));

        Equal("Terrain raised by 1,5 m within 20 m. Part of the area reached the height limit: ±8 m from original terrain. Part of the terrain was skipped: no ownership or the area was not loaded.",
            Locale.Translate("Поверхность поднята на 1,5 м в радиусе 20 м. Часть площади ограничена пределом высоты игры: ±8 м от исходного рельефа. Часть поверхности не обработана: нет управления или область не загрузилась."));
        Equal("Last terrain change undone. Points restored: 12. Later edits preserved: 3. Unavailable points: 4. Move near the area and retry undo. The remaining part can still be undone.",
            Locale.Translate("Последнее изменение поверхности отменено. Восстановлено точек: 12. Сохранены более поздние изменения: 3. Недоступно точек: 4. Подойдите к изменённой области и повторите отмену. Не восстановленная часть остаётся доступна для отмены."));
        Equal("Last spawn objects marked for removal: 2. Modified stacks that may contain ordinary items were preserved: 1.",
            Locale.Translate("На удаление отправлено объектов последнего спавна: 2. Сохранены изменённые стопки, которые могли смешаться с обычными предметами: 1."));

        string[] sourceTabs = { "Игроки", "Рельеф", "Точки" };
        Equal("Players|Terrain|Waypoints", string.Join("|", Locale.TranslateArray(sourceTabs)));
        Equal("Игроки|Рельеф|Точки", string.Join("|", sourceTabs));
        Equal("1.5", Locale.Format("{0:0.0}", 1.5));
        const string statusSource = "Ошибка: Предыдущее изменение поверхности ещё выполняется.";
        Equal("Error: The previous terrain operation is still running.", Locale.Translate(statusSource));
        Locale.SetLanguage("ru");
        Equal(statusSource, Locale.Translate(statusSource));
        Equal("1,5", Locale.Format("{0:0.0}", 1.5));
        Equal("Health restored.", Locale.Translate("Здоровье восстановлено.", "en"));
        Equal("ru", Locale.Language); // Bridge labels never change a client's language.
        Equal("target=1; prefab=Молот; count=2; radius=5; height=1; enabled=yes; categories=creatures, trees, ore, structures; position=0,1,2; ID=Steam_76561198000000000; role=Builder; reason=Ошибка: Бессмертие включено.",
            Locale.TranslateEnglish("цель=1; объект=Молот; количество=2; радиус=5; высота=1; включено=да; категории=мобы, деревья, руда, постройки; позиция=0,1,2; ID=Steam_76561198000000000; роль=Строитель; причина=Ошибка: Бессмертие включено."));
        Equal("target=1; prefab=AdminRu_SuperHammer; count=1; radius=5; height=1; enabled=no; categories=none; position=0,1,2; ID=Steam_76561198000000000; role=Player; reason=Владелец",
            Locale.TranslateEnglish("цель=1; объект=AdminRu_SuperHammer; количество=1; радиус=5; высота=1; включено=нет; категории=нет; позиция=0,1,2; ID=Steam_76561198000000000; роль=Игрок; причина=Владелец"));

        // Every explicitly translated UI literal must have an English entry. Raw fields are never passed here.
        Locale.SetLanguage("en");
        string sourceDir = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../src"));
        string panel = File.ReadAllText(Path.Combine(sourceDir, "AdminPanel.cs"));
        foreach (Match match in Regex.Matches(panel, @"T\(""([^""]*[А-Яа-яЁё][^""]*)""\)"))
            True(Locale.Translate(match.Groups[1].Value) != match.Groups[1].Value, "Missing UI translation: " + match.Groups[1].Value);
        foreach (string file in new[] { "NetworkService.cs", "HearthBridge.cs", "AdminAuthority.cs", "BuildMode.cs", "FlightMode.cs",
            "WorldActions.cs", "TeleportHistory.cs", "SpawnTracker.cs", "PlayerAssistance.cs", "TerrainMath.cs", "TerrainUndo.cs" })
        {
            string source = File.ReadAllText(Path.Combine(sourceDir, file));
            foreach (Match match in Regex.Matches(source, @"""([А-ЯЁ][^""\r\n]*\.)"""))
                True(Locale.TranslateEnglish(match.Groups[1].Value) != match.Groups[1].Value,
                    "Missing server/action message translation in " + file + ": " + match.Groups[1].Value);
        }
        var catalog = (Dictionary<string, string>)typeof(Locale).GetField("English", BindingFlags.NonPublic | BindingFlags.Static).GetValue(null);
        Locale.SetLanguage("ru");
        foreach (string source in catalog.Keys) Equal(source, Locale.Translate(source));
        Console.WriteLine("Locale checks passed: " + checks + ". No game assemblies required.");
        return 0;
    }
}
