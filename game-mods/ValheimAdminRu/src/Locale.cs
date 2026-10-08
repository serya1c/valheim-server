using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;

namespace ValheimAdminRu
{
    /// <summary>Client presentation only. Russian source messages and wire values remain stable.</summary>
    public static class Locale
    {
        private static string language = "ru";
        public static string Language => language;
        public static CultureInfo Culture => CultureInfo.GetCultureInfo(language == "en" ? "en-US" : "ru-RU");
        public static bool SetLanguage(string value)
        {
            value = (value ?? "").Trim().ToLowerInvariant();
            if (value != "ru" && value != "en") return false;
            language = value;
            return true;
        }

        public static string Translate(string source) => Translate(source, 0, language);
        public static string TranslateEnglish(string source) => Translate(source, 0, "en");
        public static string Translate(string source, string presentationLanguage) => Translate(source, 0, presentationLanguage);
        public static string Format(string source, params object[] values) => string.Format(Culture, Translate(source), values);
        public static string[] TranslateArray(string[] source)
        {
            var result = new string[source.Length];
            for (int i = 0; i < source.Length; i++) result[i] = Translate(source[i]);
            return result;
        }
        private static string Translate(string source, int depth, string presentationLanguage)
        {
            if (presentationLanguage != "en" || string.IsNullOrEmpty(source) || depth > 8) return source;
            if (English.TryGetValue(source, out string exact)) return exact;
            foreach (Template template in Templates)
            {
                Match match;
                try { match = template.Expression.Match(source); }
                catch (RegexMatchTimeoutException) { return source; }
                if (!match.Success) continue;
                return Regex.Replace(template.English, @"\{(\d+)\}", token =>
                {
                    int index = int.Parse(token.Groups[1].Value, CultureInfo.InvariantCulture);
                    string value = match.Groups[index + 1].Value;
                    return Array.IndexOf(template.Translated, index) >= 0 ? Translate(value, depth + 1, presentationLanguage) : value;
                });
            }
            // Never replace arbitrary fragments: they may be a player's name, reason, or prefab ID.
            return source;
        }

        private sealed class Template
        {
            internal readonly Regex Expression;
            internal readonly string English;
            internal readonly int[] Translated;
            internal Template(string russian, string english, params int[] translated)
            {
                English = english; Translated = translated;
                string expression = Regex.Escape(russian);
                expression = Regex.Replace(expression, @"\\\{\d+}", "([\\s\\S]*?)");
                Expression = new Regex("\\A" + expression + "\\z", RegexOptions.CultureInvariant, TimeSpan.FromMilliseconds(50));
            }
        }

        private static readonly Dictionary<string, string> English = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            {"Игроки", "Players"}, {"Предметы", "Items"}, {"Мобы", "Creatures"}, {"Рельеф", "Terrain"},
            {"Молот", "Hammer"}, {"Строительство", "Building"}, {"Точки", "Waypoints"}, {"Журнал", "Audit"},
            {"Выровнять", "Flatten"}, {"Поднять", "Raise"}, {"Опустить", "Lower"},
            {"АДМИНИСТРАТОР  •  VALHEIM", "ADMINISTRATOR  •  VALHEIM"},
            {"Ваша роль: ", "Your role: "}, {"  •  права не назначены", "  •  no permissions assigned"},
            {"  •  права подтверждены сервером", "  •  server-confirmed permissions"},
            {"Нет соединения с модом на сервере", "Not connected to the server mod"},
            {"Обновить", "Refresh"}, {"Закрыть ×", "Close ×"},
            {"Показывать область рельефа, ремонта и удара молота", "Preview terrain, repair, and hammer areas"},
            {"Подтверждение: ", "Confirmation: "},
            {". Нажмите ту же кнопку ещё раз; отмена — сменить параметры или подождать 8 секунд.", ". Click the same button again; change settings or wait 8 seconds to cancel."},
            {"F8 — открыть или закрыть панель  •  Esc — закрыть", "F8 — toggle panel  •  Esc — close"},
            {"Поиск игрока", "Find player"}, {"  (вы)", "  (you)"}, {"  • бессмертие", "  • god mode"},
            {"  • полёт", "  • flight"}, {"  • строительство", "  • building"}, {"  • нет мода", "  • no mod"},
            {"  • персонаж недоступен", "  • character unavailable"},
            {"Игроки не найдены. Обновите список или измените поиск.", "No players found. Refresh the list or change your search."},
            {"Ваш персонаж", "Your character"}, {"Бессмертие: ", "God mode: "}, {"Полёт: ", "Flight: "},
            {"обновление…", "refreshing…"}, {"включён", "enabled"}, {"выключен", "disabled"},
            {"включено", "enabled"}, {"выключено", "disabled"},
            {"Включить полёт", "Enable flight"}, {"Выключить полёт", "Disable flight"},
            {"W/A/S/D — движение, пробел — вверх, левый Ctrl — вниз, Shift — ускорение.", "W/A/S/D — move, Space — up, left Ctrl — down, Shift — faster."},
            {"Телепорт на точку на карте", "Teleport to a map point"},
            {"Вернуться после последнего телепорта", "Return after last teleport"},
            {"Выберите игрока слева", "Select a player on the left"}, {"Игрок: ", "Player: "}, {"  •  Роль: ", "  •  Role: "},
            {"Телепортироваться к игроку", "Teleport to player"}, {"Телепортировать игрока к себе", "Summon player"},
            {"Вылечить", "Heal"}, {"Восстановить выносливость", "Restore stamina"}, {"Снять вредные эффекты", "Remove harmful effects"},
            {"Для призыва, бессмертия и помощи нужен мод у выбранного игрока.", "The selected player needs the mod for summoning, god mode, and assistance."},
            {"Дождитесь загрузки или возрождения персонажа для телепорта и помощи.", "Wait for the character to load or respawn before teleporting or assisting."},
            {"Управление игроком", "Player management"}, {"Причина отключения или блокировки:", "Disconnect or ban reason:"},
            {"Отключить игрока", "Disconnect player"}, {"отключить ", "disconnect "},
            {"Заблокировать", "Ban"}, {"заблокировать ", "ban "}, {"Назначить роль:", "Assign role:"},
            {"Права владельца из серверного списка администраторов защищены.", "Owners from the server administrator list are protected."},
            {"Модератор: телепорты, помощь, модерация и журнал. Строитель: телепорты, спавн, рельеф, молот, строительство и журнал.", "Moderator: travel, assistance, moderation, audit. Builder: travel, spawning, terrain, hammer, building, audit."},
            {"назначить ", "give "}, {" роль «", " the role «"},
            {"Заблокированные игроки", "Banned players"}, {"Обновить список блокировок", "Refresh bans"},
            {"Снять блокировку по полному ID, в том числе у игрока вне сети:", "Unban by full ID, including offline players:"},
            {"Разблокировать по ID", "Unban by ID"}, {"снять блокировку с ", "unban "},
            {"Причина: ", "Reason: "}, {"не указана", "not specified"}, {"Разблокировать", "Unban"},
            {"Список пуст или ещё не загружен. Нажмите «Обновить».", "The list is empty or not loaded yet. Click Refresh."},
            {"Для списка блокировок нужны права модерации.", "Moderation permission is required to view bans."},
            {"Включить бессмертие", "Enable god mode"}, {"Выключить", "Disable"},
            {"Карта пока недоступна.", "The map is not available yet."},
            {"Наведите указатель на точку большой карты и нажмите T. Esc — отмена.", "Point at a location on the large map and press T. Esc cancels."},
            {"Название или ID моба", "Creature name or ID"}, {"Название или ID предмета", "Item name or ID"},
            {"Каталог появится после загрузки игрового мира.", "The catalog appears once the world loads."},
            {"Ничего не найдено. Попробуйте название или ID объекта.", "No results. Try an object name or ID."},
            {"Найдено: ", "Found: "}, {"  •  Выбрано: ", "  •  Selected: "}, {"Количество:", "Quantity:"},
            {"1–20 мобов за раз", "1–20 creatures per batch"}, {"1–500 единиц за раз", "1–500 items per batch"},
            {"Создать мобов рядом с собой", "Spawn creatures nearby"}, {"Создать предметы рядом с собой", "Spawn items nearby"},
            {"Введите целое число от 1 до 20.", "Enter a whole number from 1 to 20."},
            {"Введите целое число от 1 до 500.", "Enter a whole number from 1 to 500."},
            {"Удалить последнюю созданную порцию", "Remove your last spawn batch"},
            {"удалить последнюю порцию вашего спавна в этом мире", "remove your last spawn batch in this world"},
            {"Удаляются только объекты последней подтверждённой порции, созданной вами через этот мод. Обычные предметы и существа мира не затрагиваются.", "Only your last server-confirmed batch created through this mod is removed. Ordinary world items and creatures are preserved."},
            {"Изменить поверхность вокруг себя", "Change terrain around you"}, {"Радиус круга", "Area radius"},
            {"Диаметр: ", "Diameter: "}, {" м  •  Площадь: ≈ ", " m  •  Area: ≈ "}, {" м²", " m²"},
            {"Изменение высоты: ", "Height change: "}, {" м", " m"},
            {"При выравнивании этот параметр не используется.", "This setting is not used when flattening."},
            {"За одно применение: 0,1–8 м.", "Per application: 0.1–8 m."},
            {"Земля станет ровной на высоте поверхности под вашим персонажем. Изменение сохраняется в мире сервера.", "Flatten to the ground height under your character. The change is saved in the server world."},
            {"Поверхность ", "Terrain will "}, {"поднимется", "rise"}, {"опустится", "fall"}, {" на ", " by "},
            {" м с сохранением существующего рельефа. Игра ограничивает изменение земли примерно ±8 м от исходной высоты: рядом с пределом результат может быть частичным. Изменение сохраняется в мире сервера.", " m, preserving the terrain shape. Valheim limits changes to about ±8 m from original terrain; results near the limit may be partial. Changes are saved in the server world."},
            {"выравнивание", "flattening"}, {"подъём", "raising"}, {"опускание", "lowering"},
            {": радиус ", ": radius "}, {", высота ", ", height "}, {"Подтвердите ", "Confirm "},
            {". Отмена — изменить параметры или подождать 8 секунд.", ". Change settings or wait 8 seconds to cancel."},
            {" поверхность", " terrain"}, {"Отменить последнее изменение рельефа", "Undo last terrain change"},
            {"отменить ваше последнее изменение рельефа", "undo your last terrain change"},
            {"Отменяется последнее изменение в текущем подключении. Подойдите к изменённой области: клиент восстанавливает только точки без более поздних правок, сохраняя остальные изменения. Невосстановленную часть можно отменить повторно.", "Undo the last change from this connection. Move near the area: only points without later edits are restored. Other edits are preserved. Retry to restore any remaining points."},
            {"Супер молот", "Super hammer"}, {"Радиус удара", "Strike radius"},
            {"Какие цели получают 999 999 единиц урона:", "Targets that receive 999,999 damage:"},
            {"Деревья", "Trees"}, {"Руда", "Ore"}, {"Постройки", "Structures"},
            {"Выберите хотя бы одну группу целей: включение и удар без целей недоступны.", "Select at least one target group to enable or use the hammer."},
            {"Удар действует только на отмеченные группы целей.", "Only the selected target groups are affected."},
            {"Получить супермолот администратора", "Get administrator super hammer"}, {"Включить супер молот", "Enable super hammer"},
            {"Возьмите супермолот в руки, закройте панель и ударьте оружием или нажмите F6. Радиус и группы целей задаются здесь.", "Equip the super hammer, close the panel, and attack or press F6. Set its radius and target groups here."},
            {"Если отмечены постройки, они также получают урон. Предпросмотр сферы помогает выбрать область удара.", "Selected structures also take damage. Use the sphere preview to check the strike area."},
            {"Оружие также доступно на вкладке «Предметы»: поиск «Супермолот» или AdminRu_SuperHammer.", "Also available in Items: search for “Super hammer” or AdminRu_SuperHammer."},
            {"Строительство и ремонт", "Building and repair"}, {"Режим строителя: ", "Builder mode: "},
            {"Включить режим строителя", "Enable builder mode"}, {"Выключить режим строителя", "Disable builder mode"},
            {"Строительство без расхода ресурсов. Молот, мотыга и культиватор не изнашиваются при использовании режима.", "Build without resources. Hammer, hoe, and cultivator durability is preserved while this mode is active."},
            {"Радиус ремонта вокруг себя", "Repair radius"}, {"Починить постройки в области", "Repair nearby structures"},
            {"Ремонт восстанавливает доступные постройки в выбранном радиусе, включая объекты выше и ниже персонажа. Предпросмотр показывает сферическую область ремонта.", "Repairs available structures within the radius, including above and below you. The preview shows the repair sphere."},
            {"Сохранённые точки этого мира", "Waypoints in this world"},
            {"Точки хранятся на вашем компьютере отдельно для каждого мира. При телепорте сохраняется точная высота, в том числе в подземелье.", "Waypoints are stored on your computer, separately for each world. Teleports preserve the exact height, including inside dungeons."},
            {"Название:", "Name:"}, {"Сохранить моё положение", "Save my position"}, {"Поиск точки", "Find waypoint"},
            {"Телепортироваться", "Teleport"}, {"Удалить точку", "Delete waypoint"}, {"удалить точку «", "delete waypoint «"},
            {"В этом мире пока нет сохранённых точек.", "No waypoints saved in this world yet."},
            {"Точки не найдены. Измените поиск.", "No waypoints found. Change your search."},
            {"Журнал действий сервера", "Server audit log"}, {"Обновить журнал", "Refresh audit"},
            {"Игрок / администратор", "Player / administrator"}, {"Действие", "Action"},
            {"Время указано в UTC. Журнал показывает команду, параметры и результат её выполнения.", "Times are UTC. The log records each command, its parameters, and result."},
            {"Параметры: ", "Parameters: "}, {"Результат: ", "Result: "}, {"Показано записей: ", "Entries shown: "},
            {"Записи не найдены. Обновите журнал или измените поиск.", "No entries found. Refresh the log or change your search."},
            {"Для просмотра журнала нужны права аудита.", "Audit permission is required to view the log."},
            {"Подтвердить: ", "Confirm: "},
            {"Владелец", "Owner"}, {"Модератор", "Moderator"}, {"Строитель", "Builder"}, {"Игрок", "Player"},
            {"Супермолот администратора", "Administrator super hammer"},
            {"При включённом режиме наносит 999999 урона по площади. Радиус задаётся в админ-панели.", "Deals 999999 area damage when enabled. Set the radius in the admin panel."},
            {"Подключение к серверной части мода…", "Connecting to the server mod…"},
            {"Возьмите в руки «Супермолот администратора».", "Equip the administrator super hammer."},
            {"Выберите хотя бы одну категорию целей супермолота.", "Select at least one super hammer target category."},
            {"Выбор точки отменён.", "Map point selection cancelled."},
            {"Нет доступа: ваша роль не разрешает эту команду.", "Access denied: your role does not allow this command."},
            {"Недопустимые параметры команды.", "Invalid command parameters."},
            {"Права изменились до подтверждения команды; результат не подтверждён.", "Permissions changed before acknowledgment; the command result is unconfirmed."},
            {"Игровая сессия завершилась; результат команды не подтверждён.", "The game session ended; the command result is unconfirmed."},
            {"Срок подтверждения команды истёк; проверьте результат перед повтором.", "The acknowledgment deadline expired; check the result before retrying."},
            {"Сервер передал недопустимые права.", "The server sent invalid permissions."},
            {"Мод подключён. Доступ к панели не назначен владельцем сервера.", "Mod connected. The server owner has not granted panel access."},
            {"Подождите перед следующей командой.", "Wait before sending another command."},
            {"Сервер отклонил недопустимые параметры команды.", "The server rejected invalid command parameters."},
            {"Команда отклонена сервером: ваша роль не разрешает это действие.", "Command rejected: your role does not allow this action."},
            {"Супермолот не включён сервером.", "The server has not enabled the super hammer."},
            {"Подождите секунду между ударами супермолота.", "Wait one second between super hammer strikes."},
            {"Подождите две секунды между изменениями земли.", "Wait two seconds between terrain changes."},
            {"Ваш персонаж ещё не появился в мире или погиб.", "Your character has not spawned or is dead."},
            {"Позиция персонажа выходит за допустимые границы мира.", "The character is outside the allowed world boundaries."},
            {"Сервер занят. Попробуйте ещё раз через несколько секунд.", "The server is busy. Try again in a few seconds."},
            {"Отправлена клиенту; ожидается подтверждение.", "Sent to client; awaiting acknowledgment."},
            {"Нельзя отключить или заблокировать себя.", "You cannot disconnect or ban yourself."},
            {"Владелец защищён от модерации; модератор не может отключить другого модератора.", "Owners are protected; moderators cannot disconnect another moderator."},
            {"Игрок заблокирован.", "Player banned."}, {"Команда отключения игрока отправлена сервером.", "The server sent the player disconnection command."},
            {"Блокировка снята.", "Ban removed."}, {"Нельзя изменить собственную роль.", "You cannot change your own role."},
            {"Владельцы из adminlist.txt сохраняют полный доступ.", "Owners from adminlist.txt retain full access."},
            {"Владельца назначают только через adminlist.txt сервера.", "Owners can only be assigned through the server's adminlist.txt."},
            {"Нет подтверждённой порции спавна для удаления в этом мире.", "There is no confirmed spawn batch to remove in this world."},
            {"Выбранный игрок уже отключился от сервера.", "The selected player has already disconnected."},
            {"У выбранного игрока не установлен совместимый мод ValheimAdminRu.", "The selected player does not have a compatible ValheimAdminRu mod."},
            {"Выбранный игрок ещё не появился в мире или погиб.", "The selected player has not spawned or is dead."},
            {"Сервер ещё загружает игровые объекты.", "The server is still loading game objects."},
            {"Такого игрового объекта нет на сервере.", "That game object does not exist on the server."},
            {"Выбранный объект не является предметом.", "The selected object is not an item."},
            {"Выбранный объект не является существом.", "The selected object is not a creature."},
            {"Получена недопустимая команда сервера.", "Received an invalid server command."},
            {"Эту команду выполняет только сервер.", "Only the server can execute this command."},
            {"Права на выполнение команды изменились.", "Permission to execute the command has changed."},
            {"Команда выполнена.", "Command completed."},
            {"Сервер не получил подтверждение от клиента. Результат команды не подтверждён; проверьте его перед повтором.", "The server received no client acknowledgment. The result is unconfirmed; check it before retrying."},
            {"Недопустимая роль или ID игрока.", "Invalid player role or ID."},
            {"Мир сервера ещё не загружен.", "The server world has not loaded yet."},
            {"Список блокировок сервера недоступен.", "The server ban list is unavailable."},
            {"Не удалось заблокировать игрока.", "Could not ban the player."},
            {"Такого ID нет в списке блокировок.", "That ID is not in the ban list."},
            {"Не удалось снять блокировку.", "Could not remove the ban."},
            {"Команда отключения недоступна в этой версии игры.", "Disconnection is unavailable in this game version."},
            {"Режим строителя выключен.", "Builder mode disabled."},
            {"Режим строителя доступен только администратору с готовым персонажем.", "Builder mode requires administrator permission and a ready character."},
            {"Не удалось включить режим строителя: персонаж ещё не синхронизирован.", "Could not enable builder mode: the character is not synchronized yet."},
            {"Режим строителя включён: строительство без ресурсов, молот, мотыга и культиватор не изнашиваются.", "Builder mode enabled: free building, no hammer, hoe, or cultivator durability loss."},
            {"Персонаж ещё не готов к полёту.", "The character is not ready to fly yet."},
            {"Не удалось изменить полёт: персонаж ещё не синхронизирован.", "Could not change flight: the character is not synchronized yet."},
            {"Полёт включён. Space — вверх, левый Ctrl — вниз, Shift — ускорение.", "Flight enabled. Space — up, left Ctrl — down, Shift — faster."},
            {"Полёт выключен.", "Flight disabled."},
            {"Здоровье восстановлено.", "Health restored."}, {"Выносливость восстановлена.", "Stamina restored."},
            {"Негативных эффектов для снятия нет.", "There are no harmful effects to remove."},
            {"Мир ещё не готов к спавну.", "The world is not ready for spawning yet."},
            {"Созданный объект не готов к учёту административного спавна.", "The spawned object is not ready for administrative tracking."},
            {"Очистка административного спавна выполняется сервером.", "Administrative spawn cleanup is performed by the server."},
            {"Не удалось прочитать объекты мира.", "Could not read world objects."},
            {"Объекты последнего спавна уже подобраны, удалены или покинули мир.", "The last spawn batch was already collected, removed, or left the world."},
            {"Нет подтверждённой сервером порции спавна для очистки.", "There is no server-confirmed spawn batch to clean up."},
            {"Дождитесь загрузки живого персонажа.", "Wait for a living character to load."},
            {"Введите название точки от 1 до 80 символов.", "Enter a waypoint name of 1–80 characters."},
            {"Всего уже сохранено 1000 точек. Удалите ненужные.", "The 1,000-waypoint limit was reached. Delete unused waypoints."},
            {"В этом мире уже сохранено 100 точек. Удалите ненужную.", "This world already has 100 waypoints. Delete an unused waypoint."},
            {"Эту позицию нельзя сохранить.", "This position cannot be saved."},
            {"Точка уже удалена или относится к другому миру.", "The waypoint was deleted or belongs to another world."},
            {"Дождитесь завершения предыдущего телепорта.", "Wait for the previous teleport to finish."},
            {"В этом подключении ещё нет точки возврата.", "There is no return point for this connection yet."},
            {"Телепортация сейчас недоступна. Подождите и повторите.", "Teleport is unavailable now. Wait and try again."},
            {"Возврат к предыдущей точке начался.", "Returning to the previous point."},
            {"Телепортация к сохранённой точке началась.", "Teleporting to the saved waypoint."},
            {"Несовместимые данные поверхности.", "Incompatible terrain data."},
            {"Нет последнего изменения поверхности для отмены в этом мире.", "There is no last terrain change to undo in this world."},
            {"Некорректные параметры действия.", "Invalid action parameters."},
            {"Действие доступно только живому персонажу.", "This action requires a living character."},
            {"Подождите завершения предыдущей телепортации.", "Wait for the previous teleport to finish."},
            {"Телепортация началась.", "Teleport started."}, {"Бессмертие включено.", "God mode enabled."}, {"Бессмертие выключено.", "God mode disabled."},
            {"Предыдущее изменение поверхности ещё выполняется.", "The previous terrain operation is still running."},
            {"Версия игры не поддерживает отмену изменения поверхности.", "This game version does not support terrain undo."},
            {"Отмена последнего изменения поверхности началась.", "Undoing the last terrain change."},
            {"Версия игры не поддерживает изменение поверхности.", "This game version does not support terrain changes."},
            {"Выравнивание поверхности началось.", "Terrain flattening started."}, {"Поднятие поверхности началось.", "Terrain raising started."}, {"Опускание поверхности началось.", "Terrain lowering started."},
            {"Супермолот включён. Возьмите «Супермолот администратора» и ударьте им.", "Super hammer enabled. Equip the administrator super hammer and attack."},
            {"Супермолот выключен.", "Super hammer disabled."}, {"Неизвестное действие.", "Unknown action."},
            {"Мир ещё загружается.", "The world is still loading."},
            {"Подождите две секунды после предыдущей телепортации.", "Wait two seconds after the previous teleport."},
            {"Телепортация к выбранной точке началась.", "Teleporting to the selected point."},
            {"Предыдущая телепортация ещё выполняется.", "The previous teleport is still running."},
            {"Персонаж ещё не готов к телепортации.", "The character is not ready to teleport yet."},
            {"Телепортация завершена.", "Teleport completed."}, {"Область назначения не успела загрузиться.", "The destination area did not load in time."},
            {"Предмет не найден в реестре игры.", "Item not found in the game registry."},
            {"Существо не найдено в реестре игры.", "Creature not found in the game registry."},
            {"Поверхность под персонажем не загружена.", "The terrain under the character is not loaded."},
            {"Не удалось найти загруженную поверхность.", "Could not find loaded terrain."},
            {"Не удалось получить управление частью поверхности.", "Could not obtain ownership of part of the terrain."},
            {"Не удалось применить изменение к части поверхности.", "Could not apply the change to part of the terrain."},
            {"Не удалось обновить растительность после изменения поверхности.", "Could not update vegetation after the terrain change."},
            {"Не удалось прочитать данные поверхности.", "Could not read terrain data."}, {"Нет управления готовой поверхностью.", "No ownership of ready terrain."},
            {"Не найдена загруженная поверхность или не удалось получить управление ею.", "No loaded terrain found, or ownership could not be obtained."},
            {"Поверхность не изменилась: достигнут предел изменения высоты игры.", "Terrain unchanged: the game's height-change limit was reached."},
            {"Поверхность уже находится на выбранной высоте.", "Terrain is already at the selected height."},
            {"Поверхность выровнена", "Terrain flattened"},
            {"Не удалось обновить растительность после отмены изменения поверхности.", "Could not update vegetation after terrain undo."},
            {"Поверхность пока не восстановлена.", "Terrain has not been restored yet."},
            {"Не удалось прочитать поверхность для отмены.", "Could not read terrain for undo."},
            {"В выбранном радиусе нет повреждённых построек, доступных для ремонта.", "No damaged, repairable structures within the selected radius."},
            {"Телепорт на карту", "Map teleport"}, {"Телепорт к игроку", "Teleport to player"}, {"Призвать игрока", "Summon player"},
            {"Бессмертие себе", "Own god mode"}, {"Бессмертие игроку", "Player god mode"},
            {"Создать предметы", "Spawn items"}, {"Создать существ", "Spawn creatures"},
            {"Выровнять землю", "Flatten terrain"}, {"Поднять землю", "Raise terrain"}, {"Опустить землю", "Lower terrain"},
            {"Отменить изменение земли", "Undo terrain"}, {"Режим супермолота", "Super hammer mode"}, {"Удар супермолота", "Super hammer strike"},
            {"Полёт", "Flight"}, {"Удалить последний спавн", "Remove last spawn batch"},
            {"Вернуться после телепорта", "Return after teleport"}, {"Телепорт в сохранённую точку", "Teleport to waypoint"},
            {"Вылечить игрока", "Heal player"}, {"Снять эффекты", "Remove effects"}, {"Режим строительства", "Builder mode"},
            {"Починить постройки", "Repair structures"}, {"Заблокировать игрока", "Ban player"},
            {"Снять блокировку", "Unban player"}, {"Изменить роль", "Change role"}, {"Неизвестная команда", "Unknown command"},
            {"да", "yes"}, {"нет", "none"}, {"мобы", "creatures"}, {"деревья", "trees"}, {"руда", "ore"}, {"постройки", "structures"},
            {"роль изменена.", "role changed."},
            {"Не удалось прочитать или выполнить игровую команду.", "Could not read or execute the game command."},
            {"Мир или сессия игрового моста изменились.", "The game bridge world or session has changed."},
            {"Срок игровой команды истёк.", "The game command has expired."},
            {"Эта команда не поддерживается игровым мостом.", "The game bridge does not support this command."},
            {"Выберите игрока по SteamID64.", "Select a player by SteamID64."},
            {"Владельца назначают через native-список сервера.", "Assign owners through the server's native administrator list."},
            {"Недопустимые параметры игровой команды.", "Invalid game command parameters."},
            {"Недопустимое число игровой команды.", "Invalid game command number."},
            {"Ожидается целое число игровой команды.", "The game command requires a whole number."},
            {"Ожидается логическое значение игровой команды.", "The game command requires a boolean value."},
            {"Мир сервера изменился; команда не будет повторена.", "The server world has changed; the command will not be replayed."},
            {"У SteamID несколько подключений; дождитесь завершения переподключения.", "This SteamID has multiple connections; wait for reconnection to finish."},
            {"Игровая сессия завершилась; команда не будет повторена.", "The game session has ended; the command will not be replayed."},
            {"Исполнитель ещё не появился в мире или погиб.", "The executing player has not spawned or is dead."},
            {"Список сохранённых точек устарел. Обновите игроков.", "The waypoint list is stale. Refresh players."},
            {"Сохранённая точка не найдена у исполнителя в этом мире.", "The executing player has no such waypoint in this world."}
        };

        private static readonly Template[] Templates =
        {
            new Template("Ошибка: {0}", "Error: {0}", 0),
            new Template("Отклонено: {0}", "Rejected: {0}", 0),
            new Template("Выполнено сервером: {0}", "Completed by server: {0}", 0),
            new Template("Подтверждено клиентом: {0}", "Client confirmed: {0}", 0),
            new Template("Не подтверждено / ошибка: {0}", "Unconfirmed / error: {0}", 0),
            new Template("Не удалось изменить сохранённые точки: {0}", "Could not change saved waypoints: {0}", 0),
            new Template("Не удалось сохранить язык интерфейса: {0}", "Could not save the interface language: {0}"),
            new Template("Админ-панель подключена. Роль: {0}.", "Admin panel connected. Role: {0}.", 0),
            new Template("Роль игрока изменена: {0}.", "Player role changed: {0}.", 0),
            new Template("Версия Valheim на сервере {0} не поддерживается модом. Поддерживаются 1.0.16 и {1}.", "Server Valheim version {0} is unsupported. Supported: 1.0.16 and {1}."),
            new Template("Версия Valheim на клиенте {0} не поддерживается модом. Поддерживаются 1.0.16 и {1}.", "Client Valheim version {0} is unsupported. Supported: 1.0.16 and {1}."),
            new Template("Версии клиента и сервера должны совпадать. Требуются мод {0} и Valheim {1} (версия сервера). На клиенте: мод {2}, Valheim {3}.", "Client and server versions must match. Required: mod {0}, Valheim {1} (server). Client: mod {2}, Valheim {3}."),
            new Template("Версии клиента и сервера должны совпадать. Требуются мод {0} и Valheim {1} (версия клиента). На сервере: мод {2}, Valheim {3}.", "Client and server versions must match. Required: mod {0}, Valheim {1} (client). Server: mod {2}, Valheim {3}."),
            new Template("Точка «{0}» сохранена для этого мира.", "Waypoint “{0}” saved for this world."),
            new Template("Точка «{0}» удалена.", "Waypoint “{0}” deleted."),
            new Template("Снято негативных эффектов: {0}. Положительные эффекты сохранены.", "Harmful effects removed: {0}. Beneficial effects preserved."),
            new Template("Создано предметов: {0}.", "Items spawned: {0}."),
            new Template("Создано существ: {0}.", "Creatures spawned: {0}."),
            new Template("На удаление отправлено объектов последнего спавна: {0}.{1}", "Last spawn objects marked for removal: {0}.{1}", 1),
            new Template("Объекты последнего спавна уже подобраны, удалены или покинули мир.{0}", "The last spawn batch was already collected, removed, or left the world.{0}", 0),
            new Template(" Сохранены изменённые стопки, которые могли смешаться с обычными предметами: {0}.", " Modified stacks that may contain ordinary items were preserved: {0}."),
            new Template("Поверхность выровнена в радиусе {0} м.{1}", "Terrain flattened within {0} m.{1}", 1),
            new Template("Поверхность поднята на {0} м в радиусе {1} м.{2}", "Terrain raised by {0} m within {1} m.{2}", 2),
            new Template("Поверхность опущена на {0} м в радиусе {1} м.{2}", "Terrain lowered by {0} m within {1} m.{2}", 2),
            new Template("Поверхность не изменилась: достигнут предел изменения высоты игры.{0}", "Terrain unchanged: the game's height-change limit was reached.{0}", 0),
            new Template("Поверхность уже находится на выбранной высоте.{0}", "Terrain is already at the selected height.{0}", 0),
            new Template(" Часть площади ограничена пределом высоты игры: ±8 м от исходного рельефа.{0}", " Part of the area reached the height limit: ±8 m from original terrain.{0}", 0),
            new Template(" Часть поверхности не обработана: нет управления или область не загрузилась.{0}", " Part of the terrain was skipped: no ownership or the area was not loaded.{0}", 0),
            new Template("Последнее изменение поверхности отменено. Восстановлено точек: {0}.{1}", "Last terrain change undone. Points restored: {0}.{1}", 1),
            new Template("Поверхность пока не восстановлена.{0}", "Terrain has not been restored yet.{0}", 0),
            new Template(" Сохранены более поздние изменения: {0}.{1}", " Later edits preserved: {0}.{1}", 1),
            new Template(" Недоступно точек: {0}. Подойдите к изменённой области и повторите отмену.{1}", " Unavailable points: {0}. Move near the area and retry undo.{1}", 1),
            new Template(" Не восстановленная часть остаётся доступна для отмены.{0}", " The remaining part can still be undone.{0}", 0),
            new Template("Запросов ремонта построек в радиусе {0} м: {1}.", "Structure repair requests within {0} m: {1}."),
            new Template("Супермолот: ударов по целям и участкам руды — {0}. Урон: 999999.", "Super hammer: target and ore-area hits — {0}. Damage: 999999."),
            new Template("цель={0}; объект={1}; количество={2}; радиус={3}; высота={4}; включено=да; категории={5}; позиция={6}; ID={7}; роль={8}; причина={9}",
                "target={0}; prefab={1}; count={2}; radius={3}; height={4}; enabled=yes; categories={5}; position={6}; ID={7}; role={8}; reason={9}", 5, 8),
            new Template("цель={0}; объект={1}; количество={2}; радиус={3}; высота={4}; включено=нет; категории={5}; позиция={6}; ID={7}; роль={8}; причина={9}",
                "target={0}; prefab={1}; count={2}; radius={3}; height={4}; enabled=no; categories={5}; position={6}; ID={7}; role={8}; reason={9}", 5, 8),
            new Template("мобы, {0}", "creatures, {0}", 0),
            new Template("деревья, {0}", "trees, {0}", 0),
            new Template("руда, {0}", "ore, {0}", 0)
        };
    }
}
