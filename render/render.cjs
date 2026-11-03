// Картинки ботов для портфолио по записям прогона: node render/render.cjs → docs/<бот>.png
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');
const { createRequire } = require('module');
const { chromium } = createRequire('E:/Портфолио/omega-hakaton/e2e/')('@playwright/test');

const root = path.join(__dirname, '..');
const META = {
    booking: { title: 'Запись <em>к&nbsp;мастеру</em> за&nbsp;минуту', sub: 'Бот барбершопа Brass & Blade', botName: 'Brass & Blade', initials: 'BB', accent: '#c2410c',
        adminTitle: 'Уведомление администратору',
        features: ['Услуга, мастер, день и свободное время', 'Занятые слоты не показываются', 'Заявка администратору с контактом', 'Раздел «Мои записи»'] },
    leads: { title: 'Квиз-бот <em>для&nbsp;заявок</em>', sub: 'Расчёт ремонта и запись на замер для компании «Ровно»', botName: 'Ровно · расчёт ремонта', initials: 'Р', accent: '#ea580c',
        adminTitle: 'Горячая заявка менеджеру',
        features: ['4 вопроса и расчёт цены', 'Проверка площади и телефона', 'Номер одной кнопкой', 'Заявка сразу в чат менеджера'] },
    shop: { title: 'Предзаказ <em>с&nbsp;оплатой</em>', sub: 'Бот кофейни «Зерно»: меню, корзина, самовывоз', botName: 'Зерно · предзаказ', initials: 'З', accent: '#b45309',
        adminTitle: 'Заказ бариста',
        features: ['Меню с категориями и корзиной', 'Оплата через Telegram Payments', 'Выбор времени самовывоза', 'Номер заказа и чек бариста'] },
    support: { title: 'Поддержка <em>без&nbsp;очереди</em>', sub: 'Бот магазина одежды «Лён и хлопок»', botName: 'Лён и хлопок · поддержка', initials: 'ЛХ', accent: '#0f766e',
        adminTitle: 'Чат оператора', adminCount: 3,
        features: ['Ответы на частые вопросы', 'Вопрос сразу уходит оператору', 'Оператор отвечает прямо из Telegram', 'Ответ приходит клиенту от бота'] },
    school: { title: 'Тест уровня <em>и&nbsp;запись</em>', sub: 'Бот онлайн-школы английского Talkie', botName: 'Talkie · English', initials: 'T', accent: '#4f46e5',
        adminTitle: 'Заявка менеджеру',
        features: ['Тест из 5 вопросов, уровни A1–B2', 'Запись на бесплатный пробный урок', 'Номер одной кнопкой', 'Уровень ученика в заявке'] },
};

(async () => {
    const browser = await chromium.launch({ channel: 'msedge' });
    const page = await browser.newPage({ viewport: { width: 1320, height: 880 }, deviceScaleFactor: 1.5 });
    await page.goto(pathToFileURL(path.join(__dirname, 'card.html')).href);
    await page.evaluate(() => document.fonts.ready);
    fs.mkdirSync(path.join(root, 'docs'), { recursive: true });
    for (const [name, meta] of Object.entries(META)) {
        const data = JSON.parse(fs.readFileSync(path.join(root, 'transcripts', `${name}.json`), 'utf8'));
        await page.evaluate(([d, m]) => window.renderBot(d, m), [data, meta]);
        await page.evaluate(() => document.fonts.ready);
        await page.locator('#card').screenshot({ path: path.join(root, 'docs', `${name}.png`) });
    }
    await browser.close();
    console.log('ok', Object.keys(META).length);
})().catch((e) => { console.error(e); process.exit(1); });
