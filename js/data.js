// Справочники игры: предметы, лут, названия, улучшения.

// c — категория для торговли: food, med, fuel, part, weapon, valuable, goods
export const ITEMS = {
  // еда
  tushenka:  { n: 'Тушёнка', c: 'food', w: 0.5, v: 12, food: 25 },
  sgush:     { n: 'Сгущёнка', c: 'food', w: 0.4, v: 14, food: 20 },
  suhari:    { n: 'Сухари', c: 'food', w: 0.3, v: 5, food: 10 },
  grechka:   { n: 'Гречка 1 кг', c: 'food', w: 1, v: 10, food: 30 },
  kilka:     { n: 'Килька в томате', c: 'food', w: 0.3, v: 8, food: 14 },
  lapsha:    { n: 'Лапша быстрого приготовления', c: 'food', w: 0.1, v: 4, food: 9 },
  kartoshka: { n: 'Мешок картошки', c: 'food', w: 10, v: 32, food: 110 },
  varenye:   { n: 'Варенье бабушкино', c: 'food', w: 0.8, v: 16, food: 18 },
  med_honey: { n: 'Мёд, банка', c: 'food', w: 1, v: 26, food: 30 },
  salo:      { n: 'Сало', c: 'food', w: 0.6, v: 15, food: 28 },
  voda:      { n: 'Вода 5 л', c: 'food', w: 5, v: 8, food: 8 },
  syhpay:    { n: 'Армейский сухпаёк', c: 'food', w: 1.2, v: 30, food: 60 },
  griby:     { n: 'Солёные грибы', c: 'food', w: 0.7, v: 12, food: 15 },
  // медицина
  bint:      { n: 'Бинт', c: 'med', w: 0.1, v: 8, hp: 12 },
  zelenka:   { n: 'Зелёнка', c: 'med', w: 0.05, v: 4, hp: 6 },
  aptechka:  { n: 'Аптечка', c: 'med', w: 0.8, v: 40, hp: 50 },
  antibio:   { n: 'Антибиотики', c: 'med', w: 0.1, v: 55, cure: true, hp: 5 },
  obezbol:   { n: 'Обезболивающее', c: 'med', w: 0.05, v: 18, hp: 20 },
  spirt:     { n: 'Спирт медицинский', c: 'med', w: 0.5, v: 22, hp: 8 },
  x7:        { n: 'Сыворотка «Х-7»', c: 'med', w: 0.1, v: 400, cure: true, hp: 100, rare: true },
  // топливо
  kanistra:  { n: 'Канистра солярки 20 л', c: 'fuel', w: 18, v: 26, fuel: 20 },
  bochka:    { n: 'Бочка солярки 200 л', c: 'fuel', w: 175, v: 230, fuel: 200 },
  // запчасти и ресурсы
  zapchasti: { n: 'Запчасти', c: 'part', w: 4, v: 30, repair: 8 },
  instrument:{ n: 'Набор инструментов', c: 'part', w: 3, v: 35, repair: 4 },
  akkum:     { n: 'Аккумулятор', c: 'part', w: 14, v: 45 },
  maslo:     { n: 'Моторное масло', c: 'part', w: 4, v: 20, repair: 3 },
  list:      { n: 'Лист железа', c: 'part', w: 20, v: 28, repair: 10 },
  kabel:     { n: 'Медный кабель', c: 'part', w: 5, v: 34 },
  // оружие
  pm:        { n: 'Пистолет ПМ', c: 'weapon', w: 0.8, v: 120, weapon: true },
  toz:       { n: 'Обрез ТОЗ', c: 'weapon', w: 2.5, v: 160, weapon: true },
  bizon:     { n: 'ПП-19 «Бизон»', c: 'weapon', w: 3, v: 320, weapon: true },
  ak:        { n: 'АК-74', c: 'weapon', w: 3.6, v: 480, weapon: true },
  svd:       { n: 'СВД', c: 'weapon', w: 4.3, v: 650, weapon: true },
  // товары и ценности (не бытовое — держит экономику живой)
  vodka:     { n: 'Водка', c: 'goods', w: 0.6, v: 18 },
  sigarety:  { n: 'Блок сигарет', c: 'goods', w: 0.2, v: 22 },
  spichki:   { n: 'Спички', c: 'goods', w: 0.05, v: 3 },
  svechi:    { n: 'Свечи', c: 'goods', w: 0.3, v: 5 },
  sol:       { n: 'Соль 1 кг', c: 'goods', w: 1, v: 9 },
  sahar:     { n: 'Сахар 1 кг', c: 'goods', w: 1, v: 11 },
  batareyki: { n: 'Батарейки', c: 'goods', w: 0.1, v: 12 },
  semena:    { n: 'Семена овощей', c: 'goods', w: 0.1, v: 30 },
  fonar:     { n: 'Фонарь', c: 'goods', w: 0.5, v: 20 },
  valenki:   { n: 'Валенки', c: 'goods', w: 1.5, v: 24 },
  ushanka:   { n: 'Шапка-ушанка', c: 'goods', w: 0.4, v: 18 },
  protivogaz:{ n: 'Противогаз ГП-5', c: 'goods', w: 1, v: 30 },
  binokl:    { n: 'Бинокль', c: 'goods', w: 0.7, v: 45 },
  benzopila: { n: 'Бензопила «Дружба»', c: 'goods', w: 9, v: 90 },
  generator: { n: 'Бензогенератор', c: 'goods', w: 40, v: 260 },
  kniga:     { n: 'Книга «Война и мир»', c: 'valuable', w: 1, v: 10 },
  samovar:   { n: 'Самовар', c: 'valuable', w: 6, v: 85 },
  garmon:    { n: 'Гармонь', c: 'valuable', w: 5, v: 110 },
  ikona:     { n: 'Старинная икона', c: 'valuable', w: 1.2, v: 140 },
  chasy:     { n: 'Часы «Победа»', c: 'valuable', w: 0.1, v: 60 },
  medal:     { n: 'Медаль «За отвагу»', c: 'valuable', w: 0.05, v: 95 },
  radio:     { n: 'Радиоприёмник «Океан»', c: 'valuable', w: 4, v: 70 },
  kassetnik: { n: 'Кассетный магнитофон', c: 'valuable', w: 3, v: 50 },
  plastinka: { n: 'Пластинка Высоцкого', c: 'valuable', w: 0.3, v: 40 },
  zenit:     { n: 'Фотоаппарат «Зенит»', c: 'valuable', w: 1, v: 75 },
  matreshka: { n: 'Матрёшка', c: 'valuable', w: 0.4, v: 25 },
  hohloma:   { n: 'Хохломская посуда', c: 'valuable', w: 1.5, v: 45 },
  monety:    { n: 'Советские монеты', c: 'valuable', w: 0.2, v: 35 },
  zoloto:    { n: 'Золотая цепочка', c: 'valuable', w: 0.02, v: 180 },
  globus:    { n: 'Глобус СССР', c: 'valuable', w: 2, v: 55 },
  shahmaty:  { n: 'Шахматы', c: 'valuable', w: 1, v: 30 },
  balalayka: { n: 'Балалайка', c: 'valuable', w: 2, v: 65 },
};

export const CAT_NAMES = {
  food: 'Еда', med: 'Медицина', fuel: 'Топливо', part: 'Запчасти',
  weapon: 'Оружие', goods: 'Товары', valuable: 'Ценности', unique: 'Находки',
};

export const WEAPONS = {
  pm:    { n: 'ПМ', ammo: 'p9', dmg: 22, rate: 0.32, range: 45, auto: false, pellets: 1, snd: 'pistol' },
  toz:   { n: 'Обрез', ammo: 'p12', dmg: 15, rate: 0.85, range: 30, auto: false, pellets: 7, snd: 'shotgun' },
  bizon: { n: 'Бизон', ammo: 'p9', dmg: 18, rate: 0.09, range: 55, auto: true, pellets: 1, snd: 'smg' },
  ak:    { n: 'АК-74', ammo: 'p545', dmg: 30, rate: 0.1, range: 110, auto: true, pellets: 1, snd: 'rifle' },
  svd:   { n: 'СВД', ammo: 'p762', dmg: 120, rate: 1.1, range: 260, auto: false, pellets: 1, snd: 'sniper' },
};

export const AMMO = {
  p9:   { n: '9×18', v: 0.6, find: [8, 24] },
  p12:  { n: '12 кал.', v: 1.0, find: [4, 12] },
  p545: { n: '5,45×39', v: 0.9, find: [15, 45] },
  p762: { n: '7,62×54R', v: 1.6, find: [5, 20] },
};

const L = (rolls, t) => ({ rolls, t });
export const LOOT = {
  house: L([2, 4], [['tushenka', 3], ['grechka', 3], ['kilka', 2], ['varenye', 3], ['kartoshka', 1], ['voda', 3], ['salo', 2], ['griby', 2],
    ['bint', 2], ['zelenka', 1], ['spichki', 2], ['svechi', 2], ['vodka', 2], ['sigarety', 1], ['ikona', 0.5], ['samovar', 0.4],
    ['garmon', 0.25], ['balalayka', 0.25], ['chasy', 0.5], ['radio', 0.4], ['kniga', 1], ['plastinka', 0.5], ['valenki', 1], ['ushanka', 0.8],
    ['matreshka', 0.6], ['monety', 0.6], ['medal', 0.3], ['money', 2], ['am_p12', 0.6], ['toz', 0.12], ['sol', 1], ['sahar', 1], ['UNIQUE', 0.9]]),
  dacha: L([1, 3], [['semena', 3], ['varenye', 3], ['kartoshka', 1.5], ['griby', 2], ['instrument', 1], ['kanistra', 0.7], ['benzopila', 0.25],
    ['vodka', 1], ['spichki', 1], ['shahmaty', 0.5], ['kassetnik', 0.4], ['UNIQUE', 0.6], ['med_honey', 1]]),
  apartment: L([3, 6], [['tushenka', 3], ['lapsha', 4], ['sgush', 2], ['kilka', 2], ['voda', 3], ['suhari', 2], ['bint', 2], ['obezbol', 1.5],
    ['aptechka', 0.5], ['antibio', 0.4], ['vodka', 2], ['sigarety', 2], ['batareyki', 1.5], ['fonar', 1], ['kassetnik', 0.6], ['zenit', 0.4],
    ['zoloto', 0.25], ['chasy', 0.5], ['hohloma', 0.5], ['globus', 0.2], ['money', 3], ['am_p9', 0.5], ['pm', 0.1], ['UNIQUE', 1]]),
  shop_food: L([3, 6], [['tushenka', 5], ['sgush', 4], ['lapsha', 5], ['kilka', 4], ['grechka', 3], ['voda', 5], ['suhari', 4],
    ['vodka', 2], ['sigarety', 2], ['sol', 1], ['sahar', 2], ['money', 2], ['spichki', 1]]),
  shop_med: L([3, 5], [['bint', 5], ['zelenka', 3], ['aptechka', 2], ['antibio', 2], ['obezbol', 3], ['spirt', 2], ['x7', 0.08], ['money', 1]]),
  shop_hoz: L([2, 5], [['instrument', 3], ['spichki', 3], ['svechi', 3], ['batareyki', 3], ['kabel', 2], ['fonar', 2], ['kanistra', 1], ['benzopila', 0.5], ['generator', 0.2]]),
  shop_auto: L([2, 4], [['zapchasti', 4], ['maslo', 3], ['akkum', 2], ['kanistra', 2], ['instrument', 1.5], ['money', 1]]),
  shop_hunt: L([2, 4], [['am_p12', 5], ['toz', 1], ['am_p762', 1.5], ['svd', 0.15], ['binokl', 2], ['fonar', 2], ['syhpay', 1], ['protivogaz', 1]]),
  kiosk: L([1, 3], [['sigarety', 4], ['vodka', 3], ['lapsha', 3], ['voda', 2], ['batareyki', 1], ['spichki', 1], ['money', 2]]),
  garage: L([1, 4], [['kanistra', 3], ['zapchasti', 2], ['instrument', 1.5], ['akkum', 1], ['maslo', 1.5], ['vodka', 1.5], ['kartoshka', 1], ['varenye', 1], ['list', 1], ['UNIQUE', 0.4]]),
  factory: L([2, 5], [['zapchasti', 3], ['list', 3], ['kabel', 2], ['instrument', 2], ['kanistra', 1.5], ['maslo', 2], ['bochka', 0.3], ['money', 1]]),
  station: L([2, 4], [['kanistra', 2.5], ['bochka', 0.6], ['zapchasti', 2], ['fonar', 1], ['syhpay', 1], ['money', 2], ['voda', 1], ['UNIQUE', 1.2], ['am_p9', 0.6]]),
  church: L([1, 3], [['svechi', 4], ['ikona', 2], ['med_honey', 1.5], ['voda', 1], ['suhari', 1], ['kniga', 1], ['UNIQUE', 2]]),
  police: L([2, 4], [['am_p9', 4], ['pm', 1.5], ['am_p545', 2], ['ak', 0.35], ['aptechka', 1], ['bint', 1], ['syhpay', 1], ['money', 2], ['protivogaz', 1]]),
  hospital: L([2, 5], [['aptechka', 3], ['bint', 4], ['antibio', 3], ['obezbol', 2], ['spirt', 2], ['x7', 0.2]]),
  school: L([1, 3], [['suhari', 2], ['kniga', 3], ['globus', 1], ['syhpay', 0.5], ['batareyki', 1], ['shahmaty', 1], ['UNIQUE', 1]]),
  azs: L([2, 4], [['kanistra', 4], ['bochka', 1.2], ['maslo', 2], ['lapsha', 1], ['voda', 1], ['sigarety', 1], ['money', 1.5], ['akkum', 1]]),
  military: L([3, 6], [['am_p545', 5], ['am_p762', 3], ['ak', 1.2], ['svd', 0.4], ['bizon', 0.5], ['syhpay', 4], ['aptechka', 2], ['protivogaz', 2], ['binokl', 1], ['bochka', 0.8]]),
  car: L([1, 2], [['kanistra', 1.5], ['voda', 1], ['lapsha', 1], ['sigarety', 1], ['money', 1.5], ['aptechka', 0.5], ['instrument', 0.5], ['UNIQUE', 0.3]]),
  ruins: L([0, 2], [['spichki', 1], ['svechi', 1], ['list', 1], ['monety', 0.4], ['UNIQUE', 0.3], ['money', 0.5]]),
};

// Груз брошенного вагона: один вид, но много
export const WAGON_CARGO = [
  ['tushenka', 8, 24], ['kartoshka', 2, 6], ['zapchasti', 3, 8], ['vodka', 6, 16], ['list', 3, 7], ['sahar', 6, 14],
  ['sol', 6, 14], ['sgush', 8, 20], ['kanistra', 3, 8], ['syhpay', 3, 9], ['kabel', 2, 6], ['semena', 4, 10],
];

export const LOOT_TIME = {
  house: 6, dacha: 5, apartment: 10, shop_food: 8, shop_med: 7, shop_hoz: 7, shop_auto: 7, shop_hunt: 8, kiosk: 3,
  garage: 6, factory: 11, station: 8, church: 7, police: 9, hospital: 10, school: 9, azs: 6, military: 12, car: 3,
  ruins: 4, wagon_box: 6, wagon_tank: 7,
};

export const UPGRADES = {
  plow:   { n: 'Отвал-таран', d: 'Зомби и завалы почти не повреждают поезд', p: 450 },
  armor:  { n: 'Бронелисты', d: '+50% прочности, зомби на подножках бьют слабее', p: 380 },
  turret: { n: 'Пулемёт на крыше', d: 'Сам стреляет по ближайшим, тратит 7,62×54R', p: 750 },
  wagon:  { n: 'Ещё один крытый вагон', d: '+400 кг груза (до 3 вагонов)', p: 320, max: 3 },
  tank:   { n: 'Вагон-цистерна', d: '+800 л к запасу топлива', p: 300 },
  light:  { n: 'Прожектор-искатель', d: 'Дальний свет ночью', p: 160 },
  engine: { n: 'Капитальный ремонт дизеля', d: '+15% мощности и −20% расход', p: 520 },
};

// ---- названия
export const NAMES_F = ['Берёзовка', 'Сосновка', 'Ивановка', 'Петровка', 'Михайловка', 'Алексеевка', 'Николаевка', 'Покровка',
  'Журавлёвка', 'Кузнецовка', 'Ольховка', 'Рябиновка', 'Калиновка', 'Малиновка', 'Дубровка', 'Каменка', 'Луговка', 'Ключевка',
  'Знаменка', 'Васильевка', 'Григорьевка', 'Ефремовка', 'Марьевка', 'Ольгинка', 'Сенькина Гора', 'Болотовка', 'Вишнёвка', 'Клюквенка'];
export const NAMES_N = ['Сосново', 'Петрово', 'Никольское', 'Покровское', 'Троицкое', 'Успенское', 'Воскресенское', 'Медвежье',
  'Лебяжье', 'Дубово', 'Липово', 'Ильинское', 'Борисово', 'Грибово', 'Заречье', 'Подгорье', 'Залесье', 'Поречье', 'Голубино',
  'Рождествено', 'Глухово', 'Михеево', 'Сокольское', 'Кривцово'];
export const NAMES_PL = ['Липки', 'Выселки', 'Дубки', 'Горки', 'Мостки', 'Ключи', 'Пески', 'Сосенки', 'Новосёлки', 'Березники',
  'Борки', 'Ельники', 'Кресты', 'Огоньки', 'Хутора', 'Дворики', 'Луки', 'Вязники'];
export const NAMES_M = ['Каменск', 'Озёрск', 'Лесногорск', 'Сосновоборск', 'Краснозаводск', 'Заволжск', 'Белогорск', 'Новоуральск',
  'Светлогорск', 'Приозёрск', 'Медногорск', 'Тихорецк', 'Верхнеборск', 'Зареченск', 'Ржавск', 'Угольск', 'Стальград', 'Междуреченск'];
export const MOD = {
  f: ['Новая', 'Старая', 'Верхняя', 'Нижняя', 'Малая', 'Большая', 'Красная'],
  n: ['Новое', 'Старое', 'Верхнее', 'Нижнее', 'Малое', 'Большое', 'Красное'],
  pl: ['Новые', 'Старые', 'Верхние', 'Нижние', 'Малые', 'Большие'],
};
export const SETTLEMENT_NAMES = ['Рассвет', 'Ковчег', 'Последний рубеж', 'Заря', 'Надежда', 'Красный Октябрь', 'Убежище', 'Оплот',
  'Светлый путь', 'Перекат', 'Тихая гавань', 'Стрелочник', 'Полустанок', 'Бастион', 'Маяк', 'Родник', 'Броня', 'Вольница', 'Огонёк', 'Семафор'];
export const FACTORIES = ['Металлист', 'Красный пролетарий', 'Сельмаш', 'Стройдеталь', 'Гидропресс', 'Вагонник', 'Победа', 'Восход',
  'Прогресс', 'Труд', 'Искра', 'Химволокно', 'Кирпичный завод №3', 'Мясокомбинат'];

// ---- генератор уникальных находок
const FIRST = ['Иван', 'Пётр', 'Мария', 'Анна', 'Николай', 'Ольга', 'Сергей', 'Татьяна', 'Алексей', 'Галина', 'Виктор', 'Людмила',
  'Дмитрий', 'Светлана', 'Михаил', 'Нина', 'Юрий', 'Вера', 'Геннадий', 'Зоя', 'Аркадий', 'Лидия', 'Степан', 'Валентина'];
const LAST = ['Кузнецов', 'Смирнов', 'Попов', 'Соколов', 'Лебедев', 'Козлов', 'Новиков', 'Морозов', 'Волков', 'Зайцев', 'Павлов',
  'Семёнов', 'Голубев', 'Виноградов', 'Богданов', 'Воробьёв', 'Фёдоров', 'Михайлов', 'Белов', 'Тарасов', 'Беляев', 'Комаров'];
const CITIES = ['Сочи', 'Ялты', 'Ленинграда', 'Москвы', 'Владивостока', 'Мурманска', 'Казани', 'Байкала', 'Анапы', 'Кисловодска', 'Риги', 'Таллина'];
const BADGES = ['Отличник ГТО', 'Почётный железнодорожник', 'Ударник труда', 'Юный техник', 'Ветеран труда', 'Победитель соцсоревнования', 'Олимпиада-80'];
const TAGS = ['Склад №2', 'Гараж 14', 'Подвал', 'Кабинет директора', 'Сейф', 'Щитовая', 'Котельная', 'Тир'];

function femName(last) { return last.endsWith('ов') || last.endsWith('ев') || last.endsWith('ин') ? last + 'а' : last; }
export function makeUnique(r) {
  const p = (a) => a[Math.floor(r() * a.length)];
  const f = p(FIRST), l = p(LAST);
  const fem = /а$|я$/.test(f) && f !== 'Никита';
  const who = f + ' ' + (fem ? femName(l) : l);
  const year = 1955 + Math.floor(r() * 60);
  const t = Math.floor(r() * 9);
  switch (t) {
    case 0: return { n: `Письмо: «${who} — родным»`, v: 6 + Math.floor(r() * 10), w: 0.02 };
    case 1: return { n: `Фотография семьи, ${year} г.`, v: 5 + Math.floor(r() * 12), w: 0.02 };
    case 2: return { n: `Дневник выжившего (${who})`, v: 20 + Math.floor(r() * 25), w: 0.3 };
    case 3: return { n: `Значок «${p(BADGES)}»`, v: 12 + Math.floor(r() * 30), w: 0.01 };
    case 4: return { n: `Открытка из ${p(CITIES)}, ${year} г.`, v: 6 + Math.floor(r() * 14), w: 0.01 };
    case 5: return { n: `Ключ с биркой «${p(TAGS)}»`, v: 15 + Math.floor(r() * 30), w: 0.05 };
    case 6: return { n: `Карта области с пометками (${who})`, v: 35 + Math.floor(r() * 40), w: 0.1 };
    case 7: return { n: `Трудовая книжка: ${who}`, v: 4 + Math.floor(r() * 6), w: 0.05 };
    default: return { n: `Наградной портсигар, ${year} г.`, v: 50 + Math.floor(r() * 60), w: 0.2 };
  }
}
