/* Chat presentation only. Category handlers and responses belong to ChatBot. */
document.addEventListener('DOMContentLoaded', () => {
    const bot = window.chatBot;
    if (!bot) return;
    const categories = document.getElementById('quickActions');
    const browse = document.getElementById('showCategories');
    function syncCategoryState() {
        browse.setAttribute('aria-expanded', String(categories.style.display !== 'none'));
    }
    browse.addEventListener('click', () => {
        const wasHidden = categories.style.display === 'none';
        categories.style.display = wasHidden ? 'block' : 'none';
        if (wasHidden) {
            // Keep reopened choices next to the latest messages.
            bot.chatMessages.appendChild(categories);
            categories.scrollIntoView({ block: 'start', behavior: 'auto' });
        }
        syncCategoryState();
    });
    new MutationObserver(syncCategoryState).observe(categories, {
        attributes: true, attributeFilter: ['style']
    });
    document.querySelector('.skip-link').addEventListener('click', event => {
        event.preventDefault();
        bot.openChat();
    });
    // Keep the initial mobile keyboard closed.
    bot.messageInput.blur();
    syncCategoryState();
});
