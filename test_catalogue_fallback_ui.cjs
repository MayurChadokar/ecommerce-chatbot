// Contract checks for the chatbot UI without contacting a model/provider.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
    constructor(tag) { this.tag = tag; this.open = false; this.attributes = {}; this.handlers = {}; this.children = []; }
    setAttribute(name, value) { this.attributes[name] = value; }
    addEventListener(name, handler) { this.handlers[name] = handler; }
    appendChild(child) { this.children.push(child); }
    querySelector(selector) {
        if (selector === 'img') return null;
        this.buttons ??= {};
        return this.buttons[selector] ??= new Element('button');
    }
    showModal() { this.open = true; this.openCount = (this.openCount || 0) + 1; }
    close() { this.open = false; }
}

const body = new Element('body');
const context = vm.createContext({
    console, Intl, URL,
    window: { location: { origin: 'http://localhost:8001' } },
    document: { body, createElement: tag => new Element(tag), addEventListener() {} },
});
vm.runInContext(fs.readFileSync('static/js/chatbot-sale.js', 'utf8') + '\nglobalThis.TestChatBot = ChatBot;', context);
const bot = Object.create(context.TestChatBot.prototype);
bot.chatMessages = new Element('section');
bot.scrollToBottom = () => {};
bot.addMessage = () => {};
bot.addRecommendationHeader = () => {};

const live = { product_id: '1', product_name: 'Live laptop', product_url: 'https://www.lotuselectronics.com/product/laptop/1', selling_price: 47990, price_verified: true, stock_verified: true };
bot.processStructuredResponse({ answer: 'Verified options', products: [live] });
assert.equal(body.children.length, 0, 'Successful live results must not show a failure popup');
assert.match(bot.chatMessages.children[0].innerHTML, /Online Price/);

const fallback = { product_id: '2', product_name: 'Catalogue <laptop>', product_url: 'https://www.lotuselectronics.com/product/laptop/2', product_mrp: '₹43,990.00', catalogue_price: 43990, catalogue_fallback: true, price_verified: false, stock_verified: false, availability_status: 'unknown' };
bot.processStructuredResponse({ answer: 'Catalogue options', products: [fallback, { ...fallback, product_id: '3' }] });
assert.equal(body.children.length, 1, 'Show one popup for the response, not one for each card');
assert.equal(bot.verificationDialog.openCount, 1);
assert.match(bot.verificationDialog.innerHTML, /Verify live price &amp; stock/);
assert.match(bot.verificationDialog.innerHTML, /last-known and may change/);
assert.equal(bot.verificationDialog.attributes['aria-labelledby'], 'verification-dialog-title');
const card = bot.chatMessages.children[1].innerHTML;
assert.match(card, /Last-known catalogue price/);
assert.match(card, /43,990/);
assert.match(card, /href="https:\/\/www\.lotuselectronics\.com\/product\/laptop\/2"/);
assert.match(card, /View product/);
assert.match(card, /Catalogue &lt;laptop&gt;/);
assert.doesNotMatch(card, /Online Price|You Save|In Stock/);
bot.verificationDialog.querySelector('button').handlers.click();
assert.equal(bot.verificationDialog.open, false, 'Got it must dismiss the popup');
bot.processStructuredResponse({ answer: 'Normal response again', products: [live] });
assert.equal(bot.verificationDialog.openCount, 1, 'A later successful response must not reopen the popup');
bot.addProductDetailsCard(fallback);
assert.match(bot.chatMessages.children.at(-1).innerHTML, /View product/);
if (process.argv[2]) {
    const response = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
    const start = bot.chatMessages.children.length;
    bot.processStructuredResponse(response);
    assert.equal(bot.verificationDialog.open, true);
    const rendered = bot.chatMessages.children.slice(start).map(node => node.innerHTML).join('\n');
    for (const product of response.products) {
        assert.ok(rendered.includes(product.product_url), 'The real Pinecone product link must reach the UI');
    }
    assert.match(rendered, /Last-known catalogue price/);
    assert.match(rendered, /View product/);
    console.log('Real Pinecone fallback response renders product links, price labels, and the popup.');
}
console.log('Catalogue cards, last-known price labels, product links, and failure-only popup verified.');
