const landingPage = document.getElementById('landingPage');
const chatOverlay = document.getElementById('chatOverlay');
const searchForm = document.getElementById('searchForm');
const searchInput = document.getElementById('searchInput');
const chatForm = document.getElementById('chatForm');
const chatInput = document.getElementById('chatInput');
const chatMessages = document.getElementById('chatMessages');
const typingIndicator = document.getElementById('typingIndicator');
const closeChatBtn = document.getElementById('closeChat');


// Polyfill for UUID v4 if crypto.randomUUID is not available
function generateUUIDv4() {
    if (window.crypto && window.crypto.randomUUID) {
        return window.crypto.randomUUID();
    }
    // fallback
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        var r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

let sessionId = generateUUIDv4(); // generate a session id once per page load

function getCurrentTime() {
    return new Date().toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit'
    });
}

function addMessage(content, isUser = false) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isUser ? 'user' : 'bot'}`;

    messageDiv.innerHTML = `
        <div class="message-content">
            ${content}
        </div>
        <div class="message-time">
            ${getCurrentTime()}
        </div>
    `;

    chatMessages.appendChild(messageDiv);
    scrollToBottom();
}

function showTypingIndicator() {
    typingIndicator.style.display = 'block';
    scrollToBottom();
}

function hideTypingIndicator() {
    typingIndicator.style.display = 'none';
}

function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function openChat(initialMessage = null) {
    landingPage.style.display = 'none';
    chatOverlay.style.display = 'flex';

    if (initialMessage) {
        addMessage(initialMessage, true);
        sendToBot(initialMessage);
    }

    chatInput.focus();
}

function closeChat() {
    chatOverlay.style.display = 'none';
    landingPage.style.display = 'flex';
    chatMessages.innerHTML = '';
    searchInput.focus();
    sessionId = generateUUIDv4(); // reset session when closing
}

async function sendToBot(userMessage) {
    showTypingIndicator();

    try {
        const response = await fetch("http://192.168.29.62:8001/chat", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                message: userMessage,
                session_id: sessionId,
                source: 'web'
            })
        });

        const data = await response.json();
        hideTypingIndicator();

        if (data?.status === "success" && data.data) {
            const botData = data.data;

            // Always show the main answer text if available
            if (botData.answer) {
                addMessage(botData.answer, false);
            }

            // Show products in carousel if available
            if (Array.isArray(botData.products) && botData.products.length > 0) {
                renderProductsCarousel(botData.products);
            }
            // Show store info if available
            if (Array.isArray(botData.stores) && botData.stores.length > 0) {
                botData.stores.forEach(store => {
                    renderStoreCard(store);
                });
            }


            // Show detailed single product card if available
            if (botData.product_details && botData.product_details.product_id) {
                renderProductDetailsCard(botData.product_details);
            }

            // Show follow-up / end message
            if (botData.end) {
                addMessage(botData.end, false);
            }

        } else {
            addMessage("Sorry, I couldn’t process your request. Please try again.", false);
        }

    } catch (error) {
        hideTypingIndicator();
        addMessage("⚠ Connection error. Please try again later.", false);
        console.error("Chat API Error:", error);
    }
}

// Render product carousel
function renderProductsCarousel(products) {
    const carouselWrapper = document.createElement('div');
    carouselWrapper.className = "carousel-wrapper";

    const carousel = document.createElement('div');
    carousel.className = "carousel-container";

    products.forEach(product => {
        const card = document.createElement('div');
        card.className = "product-card";

        card.innerHTML = `
            <a href="${product.product_url}" target="_blank">
                <img src="${product.product_image}" alt="${product.product_name}" class="product-img"/>
            </a>
            <div class="product-info">
                <div class="product-name">${product.product_name}</div>
                <div class="product-price">${product.product_mrp}</div>
                <div class="product-features">
                    ${product.features.map(f => `<span class="feature">${f}</span>`).join(" ")}
                </div>
            </div>
        `;

        carousel.appendChild(card);
    });

    // Add navigation buttons
    const prevBtn = document.createElement('button');
    prevBtn.className = "carousel-btn prev-btn";
    prevBtn.innerHTML = "&#10094;"; // left arrow
    prevBtn.onclick = () => {
        carousel.scrollBy({
            left: -250,
            behavior: 'smooth'
        });
    };

    const nextBtn = document.createElement('button');
    nextBtn.className = "carousel-btn next-btn";
    nextBtn.innerHTML = "&#10095;"; // right arrow
    nextBtn.onclick = () => {
        carousel.scrollBy({
            left: 250,
            behavior: 'smooth'
        });
    };

    carouselWrapper.appendChild(prevBtn);
    carouselWrapper.appendChild(carousel);
    carouselWrapper.appendChild(nextBtn);

    chatMessages.appendChild(carouselWrapper);
    scrollToBottom();
}

// Render detailed product card
// Render detailed product card
function renderProductDetailsCard(product) {
    const card = document.createElement('div');
    card.className = "product-details-card";

    card.innerHTML = `
        <div class="details-card-content">
            <div class="details-left">
                <img src="${product.product_image}" alt="${product.product_name}" class="details-img"/>
                
            </div>
            <div class="details-right">
                <h3 class="details-name">${product.product_name}</h3>
                <p class="details-price"><strong>${product.product_mrp}</strong></p>
                <div class="details-actions">
                    <a href="${product.product_url}" target="_blank" class="details-btn">View Product</a>
                    <button class="add-to-cart-btn">Add to Cart</button>
                </div>
            </div>
        </div>
         <ul class="details-features">
                    ${product.features.map(f => `<li>✔ ${f}</li>`).join("")}
            </ul>
    `;

    chatMessages.appendChild(card);
    scrollToBottom();
}

// Render store card
function renderStoreCard(store) {
    const card = document.createElement('div');
    card.className = "store-card";

    const encodedAddress = encodeURIComponent(`Lotus Electronics ${store.address}`);

    card.innerHTML = `
        <h3 class="store-name">${store.store_name}</h3>
        <p class="store-address">${store.address}</p>
        <p class="store-timings"><strong>Timings:</strong> ${store.timings}</p>
        <a 
            href="https://www.google.com/maps/search/?api=1&query=${encodedAddress}" 
            target="_blank" 
            class="direction-btn">
            📍 Get Directions
        </a>
    `;

    chatMessages.appendChild(card);
    scrollToBottom();
}

// Event Listeners
searchForm.addEventListener('submit', function (e) {
    e.preventDefault();
    const message = searchInput.value.trim();
    if (message) {
        openChat(message);
        searchInput.value = '';
    }
});

chatForm.addEventListener('submit', function (e) {
    e.preventDefault();
    const message = chatInput.value.trim();
    if (message) {
        addMessage(message, true);
        chatInput.value = '';
        sendToBot(message);
    }
});

closeChatBtn.addEventListener('click', function () {
    closeChat();
});

document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && chatOverlay.style.display === 'flex') {
        closeChat();
    }
});

searchInput.focus();
