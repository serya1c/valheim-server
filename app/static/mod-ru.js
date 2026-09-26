'use strict';
const MOD_SECTIONS_RU={ValheimPlus:'Valheim Plus',AdvancedBuildingMode:'Расширенное строительство',AdvancedEditingMode:'Расширенное редактирование',Bed:'Кровати',Beehive:'Ульи',Building:'Строительство',Camera:'Камера',Experience:'Опыт навыков',Fermenter:'Бродильная бочка',FireSource:'Источники огня',Food:'Еда',Smelter:'Плавильня',Furnace:'Доменная печь',Game:'Общие правила игры',Hotkeys:'Горячие клавиши',Items:'Предметы',Hud:'Игровой интерфейс',Gathering:'Добыча ресурсов',Pickable:'Сбор предметов',Durability:'Прочность',Armor:'Броня',Kiln:'Углевыжигательная печь',Map:'Карта',Player:'Персонаж',Server:'Сервер',Stamina:'Выносливость',StaminaUsage:'Расход выносливости',EitrUsage:'Расход эйтра',HealthUsage:'Расход здоровья',StructuralIntegrity:'Устойчивость и повреждения построек',Ward:'Обереги',Workbench:'Верстак',Wagon:'Телега',Inventory:'Инвентарь и хранилища',FreePlacementRotation:'Свободное вращение',Shields:'Щиты',FirstPerson:'Вид от первого лица',GridAlignment:'Выравнивание по сетке',CraftFromChest:'Изготовление из сундуков',Windmill:'Мельница',SpinningWheel:'Прялка',EitrRefinery:'Очиститель эйтра',PlayerProjectile:'Снаряды игрока',MonsterProjectile:'Снаряды противников',Tameable:'Приручение',Procreation:'Размножение животных',GameClock:'Игровые часы',Brightness:'Яркость',Chat:'Чат',LootDrop:'Выпадение добычи',WispSpawner:'Источники огоньков',Demister:'Рассеивание тумана',HotTub:'Горячая купель',ShieldGenerator:'Генератор щита',Turret:'Баллиста',AutoStack:'Автоматическая укладка',Oven:'Каменная печь',SapCollector:'Сборщик сока',Time:'Время суток',Ship:'Корабли',Egg:'Яйца',FrigidKiln:'Морозная печь',FrostFoundry:'Ледяная плавильня'};
const MOD_LABELS_RU=Object.fromEntries(`
enabled|Включить раздел
mainMenuLogo|Логотип V+ в главном меню
serverBrowserAdvertisement|Реклама в списке серверов
disableConfigAutoUpdates|Отключить автообновление конфигурации с GitHub
enterAdvancedBuildingMode|Клавиша входа в режим строительства
exitAdvancedBuildingMode|Клавиша выхода из режима строительства
copyObjectRotation|Копирование поворота объекта
pasteObjectRotation|Вставка поворота объекта
increaseScrollSpeed|Увеличение шага перемещения
decreaseScrollSpeed|Уменьшение шага перемещения
enterAdvancedEditingMode|Клавиша входа в режим редактирования
resetAdvancedEditingMode|Сброс положения объекта
abortAndExitAdvancedEditingMode|Отмена редактирования
confirmPlacementOfAdvancedEditingMode|Подтверждение размещения
sleepWithoutSpawn|Сон без смены точки возрождения
unclaimedBedsOnly|Только незанятые кровати
honeyProductionSpeed|Время производства мёда
maximumHoneyPerBeehive|Вместимость улья
autoDeposit|Автоматически складывать продукцию
autoDepositRange|Радиус поиска хранилища
showDuration|Показывать оставшееся время
noInvalidPlacementRestriction|Разрешить нестандартное размещение
noMysticalForcesPreventPlacementRestriction|Разрешить строительство в мистических зонах
noWeatherDamage|Отключить повреждения от дождя
noHeavySnowDamage|Отключить повреждения от сильного снега
noLavaDamage|Отключить повреждения от лавы
maximumPlacementDistance|Дальность строительства
pieceComfortRadius|Радиус действия комфорта
alwaysDropResources|Всегда возвращать ресурсы при разборке
alwaysDropExcludedResources|Возвращать также исключённые ресурсы
enableAreaRepair|Включить ремонт по области
areaRepairRadius|Радиус ремонта по области
cameraMaximumZoomDistance|Максимальное отдаление камеры
cameraBoatMaximumZoomDistance|Отдаление камеры на корабле
cameraFOV|Угол обзора камеры
fermenterDuration|Длительность брожения
fermenterItemsProduced|Количество продукции за цикл
autoFuel|Автоматически добавлять топливо
ignorePrivateAreaCheck|Игнорировать защиту оберегов
autoRange|Радиус автоматического взаимодействия
torches|Факелы без расхода топлива
fires|Костры без расхода топлива
foodDurationMultiplier|Изменение длительности еды
disableFoodDegradation|Отключить ослабление эффекта еды
maximumOre|Вместимость руды
maximumCoal|Вместимость угля
coalUsedPerProduct|Расход угля на единицу продукции
productionSpeed|Время производства
allowAllOres|Разрешить все виды руды
gameDifficultyDamageScale|Масштабирование урона по числу игроков
gameDifficultyHealthScale|Масштабирование здоровья по числу игроков
extraPlayerCountNearby|Дополнительные игроки для расчёта сложности
setFixedPlayerCountTo|Фиксированное число игроков для сложности
difficultyScaleRange|Радиус учёта игроков для сложности
disablePortals|Отключить порталы
disableConsole|Отключить консоль
bigPortalNames|Длинные имена порталов
disableFog|Отключить туман
rollForwards|Кувырок вперёд
rollBackwards|Кувырок назад
noTeleportPrevention|Перенос любых предметов через портал
baseItemWeightReduction|Изменение веса предметов
itemStackMultiplier|Изменение размера стопок
droppedItemOnGroundDurationInSeconds|Время жизни брошенных предметов, секунд
itemsFloatInWater|Предметы плавают в воде
showRequiredItems|Показывать необходимые ресурсы
experienceGainedNotifications|Уведомления о получении опыта
removeDamageFlash|Убрать вспышку при получении урона
displayBowAmmoCounts|Показывать количество стрел
dropChance|Шанс выпадения
edibles|Съедобные предметы
flowersAndIngredients|Цветы и ингредиенты
materials|Материалы
valuables|Ценности
surtlingCores|Ядра суртлингов
blackCores|Чёрные ядра
questItems|Предметы заданий
maximumWood|Вместимость древесины
dontProcessFineWood|Не перерабатывать качественную древесину
dontProcessRoundLog|Не перерабатывать цельную древесину
stopAutoFuelThreshold|Порог остановки автозагрузки
shareMapProgression|Общее исследование карты
exploreRadius|Радиус исследования карты
preventPlayerFromTurningOffPublicPosition|Всегда показывать позицию игрока
displayCartsAndBoats|Показывать телеги и корабли
baseMaximumWeight|Базовая грузоподъёмность
baseMegingjordBuff|Бонус грузоподъёмности Мегингьёрда
baseAutoPickUpRange|Радиус автоматического подбора
disableCameraShake|Отключить тряску камеры
baseUnarmedDamage|Базовый урон без оружия
cropNotifier|Сообщения о состоянии растений
restSecondsPerComfortLevel|Отдых: секунд за уровень комфорта
deathPenaltyMultiplier|Изменение штрафа за смерть
autoRepair|Автоматический ремонт
guardianBuffDuration|Длительность силы Хранителя
guardianBuffCooldown|Перезарядка силы Хранителя
disableGuardianBuffAnimation|Отключить анимацию силы Хранителя
autoEquipShield|Автоматически надевать щит
autoUnequipShield|Автоматически убирать щит
queueWeaponChanges|Очередь смены оружия
skipIntro|Пропустить вступление
iHaveArrivedOnSpawn|Сообщение о прибытии
dontUnequipItemsWhenSwimming|Не убирать снаряжение при плавании
reequipItemsAfterSwimming|Возвращать снаряжение после плавания
fallDamageScalePercent|Масштаб урона от падения, процентов
maxFallDamage|Максимальный урон от падения
skipTutorials|Пропустить обучение
disableEncumbered|Отключить перегруз
autoPickUpWhenEncumbered|Подбирать предметы при перегрузе
disableEightSecondTeleport|Убрать задержку телепортации
maxPlayers|Максимум игроков
disableServerPassword|Отключить пароль сервера
enforceMod|Требовать V+ у подключающихся игроков
serverSyncsConfig|Синхронизировать настройки с игроками
serverSyncHotkeys|Синхронизировать горячие клавиши
dodgeStaminaUsage|Расход выносливости на уклонение
encumberedStaminaDrain|Расход выносливости при перегрузе
jumpStaminaDrain|Расход выносливости на прыжок
runStaminaDrain|Расход выносливости на бег
sneakStaminaDrain|Расход выносливости на скрытность
staminaRegen|Восстановление выносливости
staminaRegenDelay|Задержка восстановления выносливости
swimStaminaDrain|Расход выносливости на плавание
disableStructuralIntegrity|Отключить расчёт устойчивости
disableDamageToPlayerStructures|Отключить урон постройкам игроков
disableDamageToPlayerBoats|Отключить урон кораблям игроков
disableWaterDamageToPlayerBoats|Отключить урон кораблям от воды
disableDamageToPlayerCarts|Отключить урон телегам игроков
disableWaterDamageToPlayerCarts|Отключить урон телегам от воды
allowDismantlingOfBoatsAndCarts|Разрешить разборку кораблей и телег
wardRange|Радиус оберега
wardEnemySpawnRange|Радиус запрета появления врагов у оберега
workbenchRange|Радиус верстака
workbenchEnemySpawnRange|Радиус запрета появления врагов у верстака
workbenchAttachmentRange|Радиус улучшений верстака
disableRoofCheck|Разрешить использование без крыши
wagonBaseMass|Базовая масса телеги
wagonExtraMassFromItems|Дополнительная масса груза
playerInventoryRows|Строки инвентаря игрока
inventoryFillTopToBottom|Заполнять инвентарь сверху вниз
mergeWithExistingStacks|Объединять существующие стопки
rotateY|Вращение вокруг оси Y
rotateX|Вращение вокруг оси X
rotateZ|Вращение вокруг оси Z
copyRotationParallel|Копирование параллельного поворота
copyRotationPerpendicular|Копирование перпендикулярного поворота
blockRating|Сила блокирования
hotkey|Горячая клавиша
defaultFOV|Угол обзора по умолчанию
raiseFOVHotkey|Клавиша увеличения угла обзора
lowerFOVHotkey|Клавиша уменьшения угла обзора
align|Клавиша выравнивания
alignToggle|Переключатель выравнивания
changeDefaultAlignment|Изменение стандартного выравнивания
disableCookingStation|Не использовать для приготовления еды
checkFromWorkbench|Искать ресурсы от позиции верстака
range|Радиус действия
lookupInterval|Интервал поиска
allowCraftingFromCarts|Использовать ресурсы из телег
allowCraftingFromShips|Использовать ресурсы с кораблей
maximumBarley|Вместимость ячменя
ignoreWindIntensity|Не учитывать силу ветра
maximumFlax|Вместимость льна
maximumSap|Вместимость сока
maximumSoftTissue|Вместимость мягкой ткани
playerMinChargeVelocityMultiplier|Скорость снаряда при минимальном натяжении
playerMaxChargeVelocityMultiplier|Скорость снаряда при полном натяжении
playerMinChargeAccuracyMultiplier|Точность при минимальном натяжении
playerMaxChargeAccuracyMultiplier|Точность при полном натяжении
enableScaleWithSkillLevel|Учитывать уровень навыка
monsterMaxChargeVelocityMultiplier|Скорость снарядов противников
monsterMaxChargeAccuracyMultiplier|Точность снарядов противников
animalTypes|Виды животных
mortality|Смертность приручённых животных
ownerDamageOverride|Особые правила урона от владельца
stunRecoveryTime|Время восстановления после оглушения
stunInformation|Информация об оглушении
tameTimeMultiplier|Множитель времени приручения
tameBoostMultiplier|Множитель ускорения приручения
tameBoostRangeMultiplier|Множитель радиуса ускорения приручения
ignoreHunger|Игнорировать голод
ignoreAlerted|Игнорировать тревогу
loveInformation|Информация о готовности к размножению
offspringInformation|Информация о потомстве
requiredLovePointsMultiplier|Множитель очков для размножения
pregnancyDurationMultiplier|Множитель длительности беременности
pregnancyChanceMultiplier|Множитель шанса беременности
partnerCheckRangeMultiplier|Множитель радиуса поиска партнёра
creatureLimitMultiplier|Множитель лимита животных
maturityDurationMultiplier|Множитель времени взросления
useAMPM|12-часовой формат времени
textFontSize|Размер текста часов
textRedChannel|Красный канал цвета текста
textGreenChannel|Зелёный канал цвета текста
textBlueChannel|Синий канал цвета текста
textTransparencyChannel|Непрозрачность текста
nightBrightnessMultiplier|Множитель яркости ночи
shoutDistance|Дальность крика
outOfRangeShoutsDisplayInChatWindow|Показывать в чате крики за пределами радиуса
pingDistance|Дальность меток
forcedCase|Принудительный регистр текста
defaultWhisperDistance|Стандартная дальность шёпота
defaultNormalDistance|Стандартная дальность речи
defaultShoutDistance|Стандартная дальность крика
lootDropAmountMultiplier|Множитель количества добычи
lootDropChanceMultiplier|Множитель шанса добычи
maximumWisps|Максимум огоньков
onlySpawnAtNight|Создавать огоньки только ночью
wispSpawnIntervalMultiplier|Множитель интервала появления огоньков
wispSpawnChanceMultiplier|Множитель шанса появления огоньков
wispLight|Свет огонька
wispTorch|Факел огоньков
mistwalker|Туманный странник
infiniteFuel|Бесконечное топливо
ignorePlayers|Не атаковать игроков
unlimitedAmmo|Бесконечные боеприпасы
turnRate|Скорость поворота
attackCooldown|Перезарядка атаки
viewDistance|Дальность обнаружения
projectileVelocity|Скорость снаряда
projectileAccuracy|Точность снаряда
autoStackAllRange|Радиус автоматической укладки
autoStackAllIgnorePrivateAreaCheck|При укладке игнорировать обереги
autoStackAllIgnoreEquipment|Не складывать снаряжение
ignoreAmmo|Не складывать боеприпасы
ignoreFood|Не складывать еду
ignoreMead|Не складывать медовуху
sapProductionSpeed|Скорость сбора сока
maximumSapPerCollector|Вместимость сборщика сока
forcePartOfDay|Зафиксировать время суток
forcePartOfDayTime|Фиксированная часть суток
totalDayTimeInSeconds|Длительность полных суток, секунд
nightPercent|Доля ночи в сутках
forwardSpeed|Скорость вперёд
backwardSpeed|Скорость назад
rudderSpeed|Скорость руля
steerForce|Сила поворота
waterImpactDamage|Урон от ударов о воду
showHatchTime|Показывать время вылупления
hatchTime|Время вылупления
growTime|Время роста
requireShelter|Требуется укрытие
canStack|Разрешить стопки яиц
soldByDefault|Продажа по умолчанию
sellPrice|Цена продажи
maximumIce|Вместимость льда
iceUsedPerProduct|Расход льда на единицу продукции
maximumFuel|Вместимость топлива
fuelUsedPerProduct|Расход топлива на единицу продукции
maximumFrozenFuel|Вместимость замороженного топлива
fuelUsedPerItem|Расход топлива на предмет
frozenFuelUsedPerProduct|Расход замороженного топлива на единицу продукции
ice|Лёд
replyTimeout|Время ожидания ответа
timberwood|Строевая древесина
unarmedDamageScale|Масштаб урона без оружия
`.trim().split('\n').map(s=>s.split('|')));
const MOD_ITEMS_RU={swords:'Мечи',knives:'Ножи',clubs:'Дубины',polearms:'Древковое оружие',spears:'Копья',blocking:'Блокирование',axes:'Топоры',bows:'Луки',elementalMagic:'Стихийная магия',bloodMagic:'Магия крови',unarmed:'Без оружия',pickaxes:'Кирки',woodCutting:'Рубка деревьев',crossbows:'Арбалеты',jump:'Прыжки',sneak:'Скрытность',run:'Бег',swim:'Плавание',fishing:'Рыбалка',cooking:'Кулинария',farming:'Земледелие',crafting:'Изготовление',ride:'Верховая езда',wood:'Древесина',fineWood:'Качественная древесина',coreWood:'Цельная древесина',elderBark:'Древняя кора',yggdrasilWood:'Древесина Иггдрасиля',blackwood:'Чёрная древесина',stone:'Камень',grausten:'Граустен',blackMarble:'Чёрный мрамор',tinOre:'Оловянная руда',copperOre:'Медная руда',copperScrap:'Медный лом',ironScrap:'Железный лом',silverOre:'Серебряная руда',chitin:'Хитин',feather:'Перья',flametalOre:'Руда огнеметалла',proustitePowder:'Порошок прустита',hammer:'Молот',cultivator:'Пропашник',hoe:'Мотыга',weapons:'Оружие',armor:'Броня',shields:'Щиты',torch:'Факел',helmets:'Шлемы',chests:'Нагрудники',legs:'Поножи',capes:'Плащи',iron:'Железо',hardWood:'Твёрдая древесина',marble:'Мрамор',ashstone:'Пепельный камень',ancient:'Древние материалы'};
function modLabel(key){
  if(MOD_LABELS_RU[key]||MOD_ITEMS_RU[key])return MOD_LABELS_RU[key]||MOD_ITEMS_RU[key];
  const match=key.match(/^(woodChest|personalChest|ironChest|blackmetalChest|cartInventory|karveInventory|longboatInventory)(Rows|Columns)$/);
  if(match)return ({woodChest:'Деревянный сундук',personalChest:'Личный сундук',ironChest:'Укреплённый сундук',blackmetalChest:'Сундук из чёрного металла',cartInventory:'Телега',karveInventory:'Карви',longboatInventory:'Драккар'})[match[1]]+(match[2]==='Rows'?' — строки':' — столбцы');
  return 'Дополнительный параметр: '+key;
}
function modOption(value){return ({true:'Да',false:'Нет',None:'Нет',Normal:'Обычный',Disabled:'Отключено',Enabled:'Включено',Morning:'Утро',Day:'День',Evening:'Вечер',Night:'Ночь'})[value]||value;}

// Краткие пояснения по комментариям CFG и исходникам Grantapher 0.10.2.0.
// Диапазоны не дублируются здесь: они читаются из установленного файла мода.
const MOD_HELP_RU=Object.fromEntries(`
enabled|Включает применение остальных настроек этого раздела. «Нет» отключает раздел.
autoDeposit|Перекладывает готовую продукцию в ближайшие сундуки вместо выбрасывания на землю.
autoFuel|Берёт топливо или сырьё из ближайших сундуков для автоматической загрузки устройства.
autoRange|Радиус поиска сундуков для автоматической загрузки и выгрузки, в метрах.
autoDepositRange|Радиус поиска сундуков для готовой продукции, в метрах.
ignorePrivateAreaCheck|Разрешает автоматике брать предметы из сундуков за пределами общей зоны оберега. «Нет» сохраняет проверку доступа.
productionSpeed|Время изготовления одной единицы продукции, в секундах. Меньшее значение ускоряет производство.
infiniteFuel|Поддерживает полный запас топлива без его расходования.
showDuration|Показывает оставшееся время производства при наведении на устройство.
maximumOre|Максимальный запас руды внутри устройства, в единицах.
maximumCoal|Максимальный запас угля внутри устройства, в единицах.
coalUsedPerProduct|Количество угля, расходуемое на один готовый слиток.
maximumSap|Вместимость очистителя для древесного сока, в единицах.
maximumSoftTissue|Вместимость очистителя для мягких тканей, в единицах.
maximumIce|Вместимость морозной печи для льда, в единицах.
iceUsedPerProduct|Количество льда на одну единицу замороженного топлива.
maximumFrozenFuel|Вместимость ледяной плавильни для замороженного топлива.
frozenFuelUsedPerProduct|Расход замороженного топлива на один предмет; определяет, на сколько хватает топлива. По описанию автора — не меньше 1.
maximumWood|Количество древесины, которое можно загрузить в углевыжигательную печь.
maximumFlax|Количество льна, которое можно загрузить в прялку.
maximumBarley|Количество ячменя, которое можно загрузить в мельницу.
allowAllOres|Разрешает обрабатывать в доменной печи все виды руды.
ignoreWindIntensity|Убирает влияние силы ветра: время обработки определяется параметром времени производства.
honeyProductionSpeed|Секунды на производство одной единицы мёда. Меньше — быстрее.
maximumHoneyPerBeehive|Сколько единиц мёда улей может хранить до сбора.
fermenterDuration|Время брожения одной партии, в секундах. 2400 секунд — 40 реальных минут.
fermenterItemsProduced|Количество готовых предметов, получаемых из одной партии.
sapProductionSpeed|Время производства одной единицы сока, в секундах.
maximumSapPerCollector|Максимальное количество сока в сборщике до сбора.
dontProcessFineWood|Запрещает углевыжигательной печи расходовать качественную древесину.
dontProcessRoundLog|Запрещает углевыжигательной печи расходовать цельную древесину.
stopAutoFuelThreshold|Останавливает автозагрузку, когда в ближайших сундуках уже есть столько угля. 0 отключает этот предел.
mainMenuLogo|Показывает логотип Valheim Plus в главном меню клиента.
serverBrowserAdvertisement|Добавляет обозначение V+ в представление сервера в списке серверов.
disableConfigAutoUpdates|Отключает автоматическое обновление конфигурации V+ с GitHub. Это не кнопка обновления сервера в панели.
sleepWithoutSpawn|Разрешает спать через Shift+E, не меняя точку возрождения на выбранную кровать.
unclaimedBedsOnly|Ограничивает сон без смены точки возрождения только незанятыми кроватями; используется вместе с предыдущей настройкой.
autoStackAllRange|Радиус поиска сундуков для действия «Сложить всё», в метрах.
autoStackAllIgnorePrivateAreaCheck|Разрешает укладывать предметы без проверки доступа к защищённым оберегом сундукам.
autoStackAllIgnoreEquipment|Исключает экипируемые предметы из автоматической укладки в сундуки.
ignoreAmmo|Исключает стрелы и болты из автоматической укладки.
ignoreFood|Исключает еду из автоматической укладки.
ignoreMead|Исключает медовуху из автоматической укладки.
replyTimeout|Время ожидания ответа сундуков при укладке, в секундах. При высокой задержке можно увеличить.
nightBrightnessMultiplier|Меняет ночную яркость. По описанию автора, значения 5–10 дают примерно двукратное осветление; это не проценты.
noInvalidPlacementRestriction|Снимает часть ограничений размещения, в том числе разрешает пересечение строительных объектов.
noMysticalForcesPreventPlacementRestriction|Разрешает строительство и разборку молотом в областях с запретом «Мистические силы».
noWeatherDamage|Убирает повреждения построек от дождя и водной эрозии.
noHeavySnowDamage|Убирает повреждения построек от сильного снега.
noLavaDamage|Убирает повреждения построек от лавы.
maximumPlacementDistance|Максимальное расстояние размещения объектов молотом, в метрах.
pieceComfortRadius|Радиус, в котором предмет добавляет комфорт, в метрах.
alwaysDropResources|Возвращает полное количество строительных ресурсов при разборке объекта.
alwaysDropExcludedResources|Возвращает при разборке также ресурсы, которые игра обычно помечает как невозвратные.
enableAreaRepair|Позволяет молоту ремонтировать несколько объектов в радиусе вместо одного.
areaRepairRadius|Радиус массового ремонта, в метрах. Нужна включённая настройка ремонта по области.
cameraMaximumZoomDistance|Максимальное отдаление камеры от персонажа.
cameraBoatMaximumZoomDistance|Максимальное отдаление камеры, когда персонаж находится на корабле.
cameraFOV|Угол обзора камеры, в градусах. Большее значение показывает больше пространства по краям.
defaultFOV|Исходный угол обзора режима от первого лица, в градусах.
shoutDistance|Дальность видимости крика в чате и на карте, в метрах. 0 отключает это ограничение.
pingDistance|Дальность видимости отметки игрока на карте, в метрах. 0 отключает это ограничение.
forcedCase|«Да» сохраняет принудительный регистр текста чата из игры; «Нет» отключает преобразование в верхний и нижний регистр.
outOfRangeShoutsDisplayInChatWindow|Показывает крики в окне чата, даже если отправитель дальше ограничения shoutDistance.
defaultWhisperDistance|Стандартная дальность видимости шёпота, в метрах.
defaultNormalDistance|Стандартная дальность видимости обычного сообщения, в метрах.
defaultShoutDistance|Стандартная дальность видимости крика, в метрах.
range|Радиус поиска сундуков с ресурсами для изготовления, в метрах.
disableCookingStation|Отключает использование ресурсов из сундуков на станции приготовления пищи.
checkFromWorkbench|При нахождении у верстака ищет сундуки относительно верстака, а не персонажа.
lookupInterval|Период поиска ближайших сундуков, в секундах. Автор рекомендует не меньше 3 секунд, хотя допустимый минимум может быть ниже.
allowCraftingFromCarts|Разрешает использовать предметы из телег при изготовлении из хранилищ.
allowCraftingFromShips|Разрешает использовать предметы из корабельных хранилищ при изготовлении.
wispLight|Радиус рассеивания тумана огоньком, в метрах.
wispTorch|Радиус рассеивания тумана факелом огоньков, в метрах.
mistwalker|Радиус рассеивания тумана Туманным странником, в метрах.
showHatchTime|Показывает оставшееся время до вылупления при наведении на яйцо.
hatchTime|Время вылупления цыплёнка из яйца, в секундах. 300 — 5 минут.
growTime|Время взросления цыплёнка, в секундах. 3000 — 50 минут.
requireShelter|Требует крышу и огонь для развития яйца. «Нет» разрешает развитие без этих условий.
canStack|Разрешает вылупление яиц, лежащих одной стопкой: по цыплёнку на каждое яйцо.
soldByDefault|Разрешает Хальдору продавать яйца без обычных требований к прогрессу.
sellPrice|Цена одного яйца у Хальдора, в монетах.
torches|Даёт бесконечное топливо факелам, настенным светильникам и жаровням.
fires|Даёт бесконечное топливо источникам огня, не относящимся к факелам.
foodDurationMultiplier|Изменение длительности действия еды в процентах. 0 — без изменения, 50 — дольше, −50 — короче.
disableFoodDegradation|Сохраняет максимальный эффект еды до истечения её действия вместо постепенного ослабления.
gameDifficultyDamageScale|Прибавка к урону противников на игрока поблизости, в процентах; используется радиус difficultyScaleRange.
gameDifficultyHealthScale|Прибавка к здоровью противников на игрока поблизости, в процентах.
extraPlayerCountNearby|Добавляет виртуальных игроков для расчёта сложности. 0 не добавляет никого.
setFixedPlayerCountTo|Фиксирует число игроков для расчёта сложности; сверху добавляется extraPlayerCountNearby. 0 отключает фиксацию.
difficultyScaleRange|Радиус учёта игроков для повышения сложности, в метрах.
disablePortals|Отключает работу всех порталов.
disableConsole|Принудительно отключает внутриигровую консоль.
bigPortalNames|Показывает названия порталов крупно по центру экрана.
disableFog|Убирает густой туман из игры.
useAMPM|«Да» — 12-часовой формат AM/PM; «Нет» — 24-часовой формат часов.
textFontSize|Размер шрифта игровых часов.
textRedChannel|Красная составляющая цвета часов: 0 — отсутствует, 255 — максимальная.
textGreenChannel|Зелёная составляющая цвета часов: 0 — отсутствует, 255 — максимальная.
textBlueChannel|Синяя составляющая цвета часов: 0 — отсутствует, 255 — максимальная.
textTransparencyChannel|Непрозрачность часов: 0 — полностью прозрачные, 255 — полностью видимые.
dropChance|Процентное изменение шанса выпадения ресурса из залежей с негарантированной добычей. 200 превращает исходные 20% в 60%.
showRequiredItems|Показывает нужное и имеющееся количество ресурсов при строительстве и изготовлении. Также включается разделом изготовления из сундуков.
experienceGainedNotifications|Показывает небольшие уведомления о полученном опыте навыков.
removeDamageFlash|Убирает красную вспышку на экране при получении урона.
displayBowAmmoCounts|Показ боеприпасов под луком на панели: 0 — никогда, 1 — когда лук экипирован, 2 — всегда.
inventoryFillTopToBottom|Заполняет инвентарь сверху вниз всеми предметами, включая материалы.
mergeWithExistingStacks|При возврате вещей из надгробия сначала объединяет их с уже имеющимися стопками.
playerInventoryRows|Минимум строк инвентаря персонажа. Если сама игра дала больше строк, они сохраняются.
noTeleportPrevention|Разрешает переносить через порталы руду и другие обычно запрещённые предметы.
baseItemWeightReduction|Изменение веса всех предметов в процентах: 50 — тяжелее на 50%, −50 — легче на 50%, 0 — без изменения.
itemStackMultiplier|Изменение размера стопок в процентах: 50 превращает стопку из 100 в 150; −50 — в 50.
droppedItemOnGroundDurationInSeconds|Срок до исчезновения брошенных предметов, в секундах; обычное значение — 3600 (1 час). Остальные условия удаления определяет игра.
itemsFloatInWater|Заставляет брошенные предметы плавать на поверхности воды.
lootDropAmountMultiplier|Процентное изменение количества добычи с существ: 0 — без изменения, 100 — вдвое больше, −100 — без добычи.
lootDropChanceMultiplier|Процентное изменение шанса добычи с существ: 0 — без изменения, 100 — удвоение исходного шанса, −100 — без добычи. Итоговый шанс не может превышать 100%.
shareMapProgression|Обменивается исследованными областями карты между игроками, включая синхронизацию при подключении.
exploreRadius|Радиус открытия карты при перемещении персонажа.
preventPlayerFromTurningOffPublicPosition|Не позволяет игрокам скрывать свою позицию на карте.
displayCartsAndBoats|Показывает телеги и корабли на карте.
baseMaximumWeight|Базовая грузоподъёмность персонажа, в единицах веса. 350 означает предел 350 до бонусов, а не прибавку на 350%.
baseMegingjordBuff|Добавочная грузоподъёмность от пояса Мегингъёрд, в единицах веса.
baseAutoPickUpRange|Радиус автоматического подбора предметов, в метрах.
disableCameraShake|Отключает тряску камеры.
unarmedDamageScale|Процентное изменение урона кулаками: 0 — без изменения, 50 — больше на 50%, −50 — меньше на 50%.
cropNotifier|Запрещает посадку слишком близко к другой культуре, в пределах её области роста.
restSecondsPerComfortLevel|Сколько секунд отдыха добавляет каждый уровень комфорта.
deathPenaltyMultiplier|Процентное изменение штрафа за смерть: 50 увеличивает его на 50%, −50 уменьшает на 50%.
autoRepair|Автоматически ремонтирует снаряжение при взаимодействии с подходящим верстаком.
guardianBuffDuration|Длительность действия силы босса, в секундах.
guardianBuffCooldown|Время восстановления силы босса, в секундах.
disableGuardianBuffAnimation|Убирает анимацию применения силы босса.
autoEquipShield|При выборе одноручного оружия надевает щит с наибольшей силой блока из инвентаря.
autoUnequipShield|Убирает щит при снятии одноручного оружия.
skipIntro|Пропускает вступление игры.
iHaveArrivedOnSpawn|Показывает сообщение «Я прибыл!» при появлении персонажа; «Нет» скрывает его.
queueWeaponChanges|Выполняет запрос смены оружия после завершения текущей атаки вместо игнорирования нажатия.
dontUnequipItemsWhenSwimming|Не убирает экипированные предметы во время плавания.
reequipItemsAfterSwimming|Возвращает автоматически убранные предметы после выхода из воды.
fallDamageScalePercent|Процентное изменение урона от падения: 50 увеличивает на 50%, −50 уменьшает на 50%.
maxFallDamage|Максимальный урон от одного падения, в единицах здоровья.
skipTutorials|Пропускает обучающие подсказки; для возврата выключите параметр и сбросьте обучение в игре.
disableEncumbered|Отключает состояние перегруза при превышении грузоподъёмности.
autoPickUpWhenEncumbered|Разрешает автоматический подбор предметов даже при перегрузе.
disableEightSecondTeleport|Сокращает задержку телепортации насколько возможно.
enableScaleWithSkillLevel|Плавно усиливает изменения снарядов вместе с уровнем навыка: от исходных до настроенных значений.
animalTypes|Список видов через запятую: boar — кабан, hen — курица, wolf — волк, lox — быкоящер, asksvin — асксвин; all — все, none — ни один.
loveInformation|Показывает очки размножения животного, а при беременности — время до рождения.
offspringInformation|Показывает время до взросления потомства.
requiredLovePointsMultiplier|Изменение числа успешных проверок для беременности, в процентах: 100 — вдвое больше, −100 — без ожидания проверок.
pregnancyDurationMultiplier|Изменение длительности беременности, в процентах: 100 — вдвое дольше, −100 — мгновенное рождение.
pregnancyChanceMultiplier|Изменение шанса получить очко размножения, в процентах: 100 — удвоение, −100 — очки не набираются.
partnerCheckRangeMultiplier|Изменение дальности поиска партнёра, в процентах: 100 — вдвое дальше, −100 — размножение невозможно.
creatureLimitMultiplier|Изменение допустимого количества потомства поблизости, в процентах: 100 — вдвое больше, −100 — размножение невозможно.
maturityDurationMultiplier|Изменение времени взросления, в процентах: 100 — вдвое дольше, −100 — мгновенно. Не применяется к яйцам.
maxPlayers|Максимальное число одновременно подключённых игроков. Допустимый предел берётся из установленного мода.
disableServerPassword|Снимает требование пароля со стороны V+. Панель по-прежнему требует сохранить пароль игры длиной не менее 5 символов.
enforceMod|Проверяет наличие совместимого V+ при подключении. Автор рекомендует оставлять включённым.
serverSyncsConfig|Передаёт серверную конфигурацию подключающимся клиентам. Автор рекомендует оставлять включённым; не все настройки относятся к серверу.
blockRating|Процентное изменение силы блока всех щитов: 50 — больше на 50%, −50 — меньше на 50%.
forwardSpeed|Процентное изменение силы движения корабля вперёд: 50 увеличивает её на 50%, −50 уменьшает.
backwardSpeed|Процентное изменение силы движения корабля назад: 50 увеличивает её на 50%, −50 уменьшает.
rudderSpeed|Процентное изменение скорости поворота руля: 50 увеличивает её на 50%, −50 уменьшает.
steerForce|Процентное изменение силы поворота корабля: 50 увеличивает её на 50%, −50 уменьшает.
waterImpactDamage|Процентное изменение урона кораблю при движении по воде: 50 — больше урона, −50 — меньше.
dodgeStaminaUsage|Процентное изменение расхода выносливости на кувырок.
encumberedStaminaDrain|Процентное изменение расхода выносливости при перегрузе.
jumpStaminaDrain|Процентное изменение расхода выносливости на прыжок.
runStaminaDrain|Процентное изменение расхода выносливости при беге.
sneakStaminaDrain|Процентное изменение расхода выносливости при скрытном движении.
staminaRegen|Процентное изменение количества выносливости, восстанавливаемой за секунду. Положительное значение ускоряет восстановление.
staminaRegenDelay|Процентное изменение задержки перед восстановлением выносливости. Отрицательное значение сокращает ожидание.
swimStaminaDrain|Процентное изменение расхода выносливости на плавание.
disableStructuralIntegrity|Отключает расчёт опоры и разрешает постройки в воздухе. Сам по себе не защищает от повреждений.
disableDamageToPlayerStructures|Защищает постройки игроков от урона, но не от разрушения из-за отсутствия опоры.
disableDamageToPlayerBoats|Защищает построенные игроками корабли от урона.
disableDamageToPlayerCarts|Защищает построенные игроками телеги от урона.
disableWaterDamageToPlayerBoats|Отключает урон кораблям игроков от воздействия воды.
disableWaterDamageToPlayerCarts|Отключает урон телегам игроков от воздействия воды.
allowDismantlingOfBoatsAndCarts|Разрешает разбирать молотом построенные игроками корабли и телеги. Их хранилища должны быть пусты, транспорт не должен использоваться.
mortality|Режим приручённых существ: 0 — обычная смертность; 1 — смертельный удар оглушает (редкая гибель всё ещё возможна); 2 — бессмертие.
ownerDamageOverride|Разрешает убить приручённое существо ножом мясника даже при режиме оглушения или бессмертия.
stunRecoveryTime|Время восстановления после оглушения, в секундах; действует при mortality = 1.
stunInformation|Показывает оглушение в подсказке при наведении на приручённое существо.
tameTimeMultiplier|Изменение времени приручения, в процентах: 100 — вдвое дольше, −100 — мгновенно.
tameBoostMultiplier|Изменение бонуса зелья приручения, в процентах: 100 — удвоение, −100 — остановка приручения под этим эффектом.
tameBoostRangeMultiplier|Изменение дальности действия бонуса приручения, в процентах: 100 — удвоение, −100 — эффект не применяется.
forcePartOfDay|Фиксирует время суток. Пока включено, остальные настройки длительности дня не действуют.
forcePartOfDayTime|Точка суток для фиксации: 0 — полночь, 0,5 — полдень. Нужна включённая фиксация времени; в поле используйте точку.
totalDayTimeInSeconds|Длительность полных игровых суток, в секундах. Влияет на счётчик дней; при первом применении может сдвинуть время существующего мира.
nightPercent|Доля ночи: 0 — только день, 100 — только ночь. CFG версии 0.10.2.0 допускает до 200, но смысл значений выше 100 автор не поясняет.
ignorePlayers|Исключает игроков из целей баллисты.
unlimitedAmmo|Отключает расход боеприпасов баллисты.
turnRate|Меняет скорость поворота баллисты процентным модификатором. По описанию автора, −50 ускоряет поворот на 50%.
attackCooldown|Процентное изменение паузы между выстрелами: −50 сокращает паузу вдвое и удваивает частоту стрельбы.
viewDistance|Процентное изменение дальности обнаружения целей баллистой: 50 — дальше на 50%.
projectileVelocity|Процентное изменение скорости снаряда баллисты: 50 — быстрее на 50%.
projectileAccuracy|Процентное изменение точности баллисты: положительное значение уменьшает разброс.
wagonExtraMassFromItems|Процентное изменение добавочной массы телеги от груза: 50 увеличивает её на 50%, −100 убирает влияние груза.
wagonBaseMass|Базовая физическая масса пустой телеги.
wardRange|Радиус действия оберега, в метрах.
wardEnemySpawnRange|Радиус подавления появления врагов вокруг оберега, в метрах. 0 использует основной радиус оберега.
workbenchRange|Радиус действия верстака, в метрах.
workbenchEnemySpawnRange|Радиус подавления появления врагов вокруг верстака, в метрах. 0 использует основной радиус верстака.
workbenchAttachmentRange|Максимальная дальность улучшений верстака, например наковальни, в метрах.
disableRoofCheck|Разрешает использовать верстак без крыши и укрытия.
maximumWisps|Максимальное число огоньков у одного источника.
onlySpawnAtNight|«Да» — огоньки появляются только ночью; «Нет» — также днём.
wispSpawnIntervalMultiplier|Процентное изменение интервала попыток появления огоньков: −50 сокращает стандартные 5 секунд до 2,5.
wispSpawnChanceMultiplier|Процентное изменение вероятности появления огонька за попытку. По описанию автора, 200 доводит её до 100%.
`.trim().split('\n').map(line=>line.split('|')));
function modDescription(e){
  const title=modLabel(e.key);
  if(e.key==='enabled')return MOD_HELP_RU.enabled;
  if(e.options?.includes('Keypad0'))return `Клавиша действия «${title}». Выберите название клавиши из списка; None отключает назначение.`;
  const percentages={Armor:'защиты предметов',Durability:'прочности предметов',Experience:'получаемого опыта навыка',Gathering:'количества добываемого ресурса',StaminaUsage:'расхода выносливости',EitrUsage:'расхода эйтра',HealthUsage:'расхода здоровья'};
  if(percentages[e.section]&&e.key!=='dropChance')return `Процентное изменение ${percentages[e.section]} «${title}». 0 — без изменения, 50 — больше на 50%, −50 — меньше на 50%.`;
  if(e.section==='StructuralIntegrity'&&!MOD_HELP_RU[e.key])return `Снижение потери опоры с расстоянием для материала «${title}», в процентах. 0 — обычная опора, 100 — без потери с расстоянием. Само по себе не разрешает строительство в воздухе.`;
  if(e.section==='Inventory'&&/(Rows|Columns)$/.test(e.key)&&e.key!=='playerInventoryRows')return `Размер хранилища «${title}», в ячейках. Вместимость равна числу строк × число столбцов.`;
  if(e.section==='Pickable')return `Процентное изменение количества при ручном сборе категории «${title}». 0 — без изменения, 50 — больше на 50%, −50 — меньше на 50%.`;
  if(e.section==='PlayerProjectile'||e.section==='MonsterProjectile'){
    if(e.key.includes('Accuracy'))return `Процентное изменение точности снарядов: положительное значение уменьшает разброс, отрицательное увеличивает. ${e.key.includes('Min')?'Для минимального натяжения.':'Для максимального натяжения или атаки противника.'}`;
    if(e.key.includes('Velocity'))return `Процентное изменение скорости снарядов: 50 — быстрее на 50%, −50 — медленнее на 50%. ${e.key.includes('Min')?'При минимальном натяжении.':'При максимальном натяжении или атаке противника.'}`;
  }
  if(e.key==='ignoreHunger')return e.section==='Tameable'?'Разрешает продолжать приручение без сытости. Еда всё ещё нужна для начала приручения.':'Разрешает размножение без кормления животных.';
  if(e.key==='ignoreAlerted')return e.section==='Tameable'?'Разрешает приручать встревоженное животное.':'Разрешает размножение встревоженных животных.';
  return MOD_HELP_RU[e.key]||'Для этого параметра пока нет русского пояснения. Ниже доступен исходный комментарий установленного мода.';
}
function modConstraints(e){
  let text;
  if(e.kind==='bool')text='Значения: Да (true) / Нет (false).';
  else if(e.options.length)text=e.options.length>12?'Значения: только варианты из списка.':`Значения: ${e.options.map(modOption).join(', ')}.`;
  else if(e.kind==='int'||e.kind==='float'){
    text=e.kind==='int'?'Целое число.':'Число; дробная часть через точку, например 1.5.';
    if(e.min!==null&&e.max!==null)text+=` Диапазон мода: ${e.min}…${e.max} включительно.`;
    else if(e.min!==null)text+=` Минимум мода: ${e.min}.`;
    else if(e.max!==null)text+=` Максимум мода: ${e.max}.`;
    else text+=' Мод не указал допустимый игровой диапазон в CFG.';
    if(e.kind==='int'&&e.min===null&&e.max===null)text+=' Предел ввода панели: −2147483648…2147483647; это не игровой диапазон.';
  }else text='Текст, до 2048 символов, без переносов строк и управляющих символов. Числовой диапазон неприменим.';
  return text+(e.default!==null?` По умолчанию: ${modOption(e.default)||'(пустая строка)'}.`:' Значение по умолчанию не указано в CFG.');
}
