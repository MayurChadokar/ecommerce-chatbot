// Exercise the actual card click, request serialization and detail rendering.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
    constructor() { this.handlers = {}; this.children = []; }
    addEventListener(name, callback) { this.handlers[name] = callback; }
    appendChild(child) { this.children.push(child); }
    querySelector(selector) {
        if (selector === 'img') return null;
        this.elements ??= {};
        return this.elements[selector] ??= new Element();
    }
}
const requests = [], retries = [];
let failNextRequest = false;
const context = vm.createContext({
    Intl, URL, console: { log() {}, error() {} },
    window: { location: { origin: 'http://localhost:4000' } },
    document: { createElement: () => new Element(), addEventListener() {} },
    setTimeout(callback) { retries.push(callback); },
    fetch(url, options) {
        requests.push({ url, payload: JSON.parse(options.body) });
        if (failNextRequest) { failNextRequest = false; return Promise.reject(new Error('Network failure')); }
        return Promise.resolve({ ok: true, json: async () => ({ status: 'success', data: { answer: 'Details' } }) });
    },
});
vm.runInContext(fs.readFileSync('static/js/chatbot-sale.js', 'utf8') + '\nglobalThis.TestChatBot = ChatBot;', context);
const bot = Object.create(context.TestChatBot.prototype);
bot.chatMessages = new Element();
bot.messageInput = { value: '' };
bot.baseUrl = 'http://localhost:4000';
bot.sessionId = 'fresh-session';
bot.scrollToBottom = bot.hideQuickActions = bot.addMessage = bot.autoResizeInput = bot.processStructuredResponse = () => {};
bot.showTypingIndicator = () => { bot.isTyping = true; };
bot.hideTypingIndicator = () => { bot.isTyping = false; };

const detail = {
    product_id: '41237', product_name: 'Samsung F17', stock_city: 'BHOPAL', instock: 'Yes',
    product_url: 'https://www.lotuselectronics.com/product/smartphones/samsung-f17/41237',
    product_msrp: 30999, selling_price: 25999,
    product_specification: Array.from({ length: 19 }, (_, i) => ({ fkey: `Feature ${i}`, fvalue: `Value ${i}` })),
};
const clickCard = product => {
    bot.addProductCard(product);
    bot.chatMessages.children.at(-1).querySelector('.product-result-ask').handlers.click();
};
const flush = () => new Promise(resolve => setImmediate(resolve));

(async () => {
    clickCard(detail);
    assert.equal(requests[0].url, 'http://localhost:4000/chat');
    assert.deepEqual(requests[0].payload, {
        message: 'Show me the details and specifications for Samsung F17',
        session_id: 'fresh-session', product_id: '41237', city: 'BHOPAL',
    });
    await flush();

    bot.messageInput.value = 'Show laptops';
    bot.sendMessage();
    assert.equal(requests[1].payload.product_id, undefined, 'Ordinary messages must not reuse a previous selection');
    await flush();

    failNextRequest = true;
    clickCard({ ...detail, stock_city: undefined });
    await flush();
    assert.equal(retries.length, 1);
    retries.shift()();
    await flush();
    assert.equal(requests.at(-1).payload.product_id, '41237', 'A network retry must retain the selected product');
    assert.equal(requests.at(-1).payload.city, 'INDORE');

    for (const guard of ['isTyping', 'awaitingPhone', 'awaitingOTP']) {
        const count = requests.length;
        bot[guard] = true;
        clickCard(detail);
        assert.equal(requests.length, count, `${guard} must prevent a conflicting selection`);
        bot[guard] = false;
    }

    bot.addProductDetailsCard(detail);
    const html = bot.chatMessages.children.at(-1).innerHTML;
    assert.match(html, /MRP.*30,999/);
    assert.match(html, /25,999/);
    assert.match(html, /In Stock/);
    assert.match(html, /Stock in BHOPAL/);
    assert.match(html, /More specifications \(14\)/);
    assert.match(html, /Value 18/);
    assert.ok(html.includes(detail.product_url), 'Use the canonical live product link');
    bot.addProductDetailsCard({ ...detail, instock: 'No' });
    assert.match(bot.chatMessages.children.at(-1).innerHTML, /Out of Stock/);
    bot.addProductDetailsCard({ ...detail, instock: 'Unknown', catalogue_fallback: true,
                               price_verified: false, selling_price: undefined, catalogue_price: 27000 });
    const fallback = bot.chatMessages.children.at(-1).innerHTML;
    assert.match(fallback, /Last-known catalogue price/);
    assert.match(fallback, /Availability unconfirmed/);
    assert.match(fallback, /Value 18/, 'Available catalogue specifications must remain accessible during an outage');
    if (process.argv[2]) {
        const response = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
        const product = response.product_details;
        bot.addProductDetailsCard(product);
        const rendered = bot.chatMessages.children.at(-1).innerHTML;
        assert.match(rendered, /MRP/);
        for (const price of [product.mrp, product.selling_price]) {
            assert.ok(rendered.includes(new Intl.NumberFormat('en-IN', {
                style: 'currency', currency: 'INR', minimumFractionDigits: 0, maximumFractionDigits: 2,
            }).format(price)), 'The actual API price must reach the detail card');
        }
        assert.ok(rendered.includes(product.product_url));
        assert.ok(rendered.includes(`Stock in ${product.stock_city}`));
        assert.equal((rendered.match(/<small class="text-muted">/g) || []).length,
                     product.product_specification.length, 'Render all specifications from the actual API response');
        console.log('Actual Lotus live detail response renders MRP, selling price, city, link and all specifications.');
    }
    console.log('Ask-about identity, city, retry, prices, stock, all specifications and fallback verified.');
})().catch(error => { console.error(error); process.exitCode = 1; });
