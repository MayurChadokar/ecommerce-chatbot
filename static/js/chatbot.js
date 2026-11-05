class ChatBot {
    constructor() {
        this.isOpen = false;
        this.isTyping = false;
        this.messageCount = 0;
        this.apiKey = 'nawabkhan';
        // this.baseUrl = 'http://143.110.186.164:8001';
        // this.baseUrl = 'http://127.0.0.1:8001';
        this.baseUrl = `${window.location.protocol}//${window.location.hostname}:8001`;
        this.sessionId = this.generateSessionId();
        this.awaitingPhone = false;
        this.awaitingOTP = false;
        this.lastUserMessage = '';
        this.phoneNumber = '';

        this.initializeElements();
        this.bindEvents();
        this.showWelcomeMessage();
    }

    generateSessionId() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
            const r = Math.random() * 16 | 0;
            const v = c === 'x' ? r : (r & 0x3 | 0x8);
            return v.toString(16);
        });
    }

    initializeElements() {
        this.chatToggle = document.getElementById('chatToggle');
        this.chatContainer = document.getElementById('chatContainer');
        this.chatOverlay = document.getElementById('chatOverlay');
        this.minimizeChat = document.getElementById('minimizeChat');
        this.messageInput = document.getElementById('messageInput');
        this.sendBtn = document.getElementById('sendBtn');
        this.chatMessages = document.getElementById('chatMessages');
        this.typingIndicator = document.getElementById('typingIndicator');
        this.notificationBadge = document.getElementById('notificationBadge');
        this.quickActionBtns = document.querySelectorAll('.quick-action-btn');
        this.quickActionsContainer = document.getElementById('quickActions');
    }

    bindEvents() {
        this.chatToggle.addEventListener('click', () => this.toggleChat());
        this.minimizeChat.addEventListener('click', () => this.closeChat());
        this.chatOverlay.addEventListener('click', () => this.closeChat());

        this.messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        this.sendBtn.addEventListener('click', () => this.sendMessage());

        this.quickActionBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const category = btn.dataset.category;
                this.handleQuickAction(category);
            });
        });

        this.messageInput.addEventListener('input', () => this.autoResizeInput());

        this.chatContainer.addEventListener('click', (e) => e.stopPropagation());
    }

    toggleChat() {
        this.isOpen ? this.closeChat() : this.openChat();
    }

    openChat() {
        this.isOpen = true;
        this.chatContainer.classList.add('active');
        this.chatOverlay.classList.add('active');
        this.chatToggle.classList.add('active');
        this.hideNotificationBadge();
        this.messageInput.focus();
        document.body.style.overflow = 'hidden';
    }

    closeChat() {
        this.isOpen = false;
        this.chatContainer.classList.remove('active');
        this.chatOverlay.classList.remove('active');
        this.chatToggle.classList.remove('active');
        document.body.style.overflow = '';
    }

    sendMessage() {
        const message = this.messageInput.value.trim();
        if (!message) return;

        this.hideQuickActions();
        this.addMessage(message, 'user');
        this.messageInput.value = '';
        this.autoResizeInput();

        this.showTypingIndicator();

        if (this.awaitingPhone) {
            this.awaitingPhone = false;
            this.phoneNumber = message;
            this.sendOTP(message);
            return;
        }

        if (this.awaitingOTP) {
            this.awaitingOTP = false;
            this.verifyOTP(this.phoneNumber, message);
            return;
        }

        this.lastUserMessage = message;
        this.generateBotResponse(message);
    }

    hideQuickActions() {
        if (this.quickActionsContainer) {
            this.quickActionsContainer.style.display = 'none';
        }
    }

    addMessage(content, sender = 'bot', timestamp = null) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${sender}-message fade-in`;

        const time = timestamp || this.getCurrentTime();
        const avatarIcon = sender === 'bot' ? 'fas fa-robot' : 'fas fa-user';

        messageDiv.innerHTML = `
            <div class="message-avatar">
                <i class="${avatarIcon}"></i>
            </div>
            <div class="message-content">
                <div class="message-bubble">
                    <p class="mb-0">${content}</p>
                </div>
                <small class="message-time">${time}</small>
            </div>
        `;

        this.chatMessages.appendChild(messageDiv);
        this.scrollToBottom();
        this.messageCount++;
    }
    addProductCard(product) {
        const cardDiv = document.createElement('div');
        cardDiv.className = 'product-card fade-in';

        const safeName = product.product_name || 'Product';
        const words = safeName.split(' ');
        const productName = words.length > 6 ? words.slice(0, 6).join(' ') + '...' : safeName;

        const imageUrl = product.product_image || '';

        cardDiv.innerHTML = `
        <div class="card mb-2 shadow-sm border">
            <div class="row g-0">
                <div class="col-4 product-image">
                    <img src="${imageUrl}" alt="${safeName}" class="img-fluid rounded-start" onerror="this.style.display='none'" />
                </div>
                <div class="col-8">
                    <div class="card-body p-2">
                        <p class="card-title mb-1">${productName}</p>
                        <p class="card-text mb-1 fw-bold">${product.product_mrp}</p>
                        ${product.features?.length
                            ? `<ul class="product-features mb-2">${product.features.map(f => `<li>${f}</li>`).join('')}</ul>`
                            : ''
                        }
                        <a href="${product.product_url}" target="_blank" class="btn btn-sm btn-outline-primary">View</a>
                    </div>
                </div>
            </div>
        </div>
    `;

        this.chatMessages.appendChild(cardDiv);
        this.scrollToBottom();
    }


    // addProductCard(product) {
    //     const card = document.createElement('div');
    //     card.className = 'product-card fade-in';

    //     card.innerHTML = `
    //     <a href="${product.link}" target="_blank" class="product-link">
    //         <div class="product-image">
    //             <img src="${product.image}" alt="${product.name}">
    //         </div>
    //         <div class="product-details">
    //             <h6 class="product-name">${product.name}</h6>
    //             <p class="product-price">Ã¢â€šÂ¹${product.price}</p>
    //             ${product.features?.length
    //             ? `<ul class="product-features">${product.features.map(f => `<li>${f}</li>`).join('')}</ul>`
    //             : ''
    //         }
    //         </div>
    //     </a>
    // `;

    //     this.chatMessages.appendChild(card);
    //     this.scrollToBottom();
    // }


    generateBotResponse(userMessage) {
        this.showTypingIndicator();

        const requestOptions = {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-Key': this.apiKey,
                'Accept': 'application/json'
            },
            mode: 'cors',
            body: JSON.stringify({
                message: userMessage,
                session_id: this.sessionId,
                source: 'web'
            })
        };

        fetch(`${this.baseUrl}/chat`, requestOptions)
            .then(async response => {
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                this.hideTypingIndicator();

                // Handle the new JSON response format
                if (data.response) {
                    data = data.response; // Unwrap if response is nested
                }

                if (data.status === "success" && data.data) {
                    const answer = data.data.answer;
                    const products = data.data.products;
                    const comparison = data.data.comparison;
                    const end = data.data.end;

                    if (answer) this.addMessage(answer, 'bot');
                    if (products && Array.isArray(products)) {
                        products.forEach(product => this.addProductCard(product));
                    }
                    if (comparison && Array.isArray(comparison)) {
                        comparison.forEach(item => {
                            let compMsg = `
                            <div class="max-w-xl mx-auto p-2">
                              <div class="bg-white shadow rounded-xl p-4 border border-gray-200">
                                <div class="font-bold mb-2 text-gray-800">
                                  Comparison: <span class="text-blue-700">${item.name}</span> <span class="text-gray-500">vs</span> <span class="text-green-700">${item.vs_name}</span>
                                </div>
                                <ul class="text-sm text-gray-700 list-disc ml-5 space-y-1 mb-2">
                                  ${item.differences.map(diff => `<li>${diff}</li>`).join('')}
                                </ul>
                                <div class="text-xs text-gray-500 mt-2"><em>Would you like to purchase one or need further details?</em></div>
                              </div>
                            </div>
                            `;
                            this.addMessage(compMsg, 'bot');
                        });
                    }
                    if (end) this.addMessage(end, 'bot');
                } else if (data.status === "error" && data.data) {
                    this.addMessage(data.data.answer || "Sorry, something went wrong.", 'bot');
                } else {
                    // Fallback for old format or unexpected response
                    if (data.response) {
                        this.addMessage(data.response, 'bot');
                    } else {
                        this.addMessage("Sorry, I did not understand that.", 'bot');
                    }
                }
            })
            .catch(error => {
                console.error("API error:", error);
                this.hideTypingIndicator();
                this.addMessage(`I apologize, but I'm having trouble: ${error.message}. Please try again.`, 'bot');
            });
    }

    promptForPhone() {
        this.messageInput.placeholder = 'Enter your phone number...';
        this.messageInput.type = 'tel';
        this.awaitingPhone = true;
    }

    promptForOTP() {
        this.messageInput.placeholder = 'Enter the OTP sent to your phone...';
        this.messageInput.type = 'text';
        this.awaitingOTP = true;
    }

    sendOTP(phone) {
        // First check if user exists
        const formData = new URLSearchParams();
        formData.append('phone', phone);
        fetch(`${this.baseUrl}/auth/check-user`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                body: formData
            })
            .then(res => res.json())
            .then(data => {
                // Check if user exists (assume error==0 means exists, or adapt to your API)
                if (data.error && data.error !== "0") {
                    this.hideTypingIndicator();
                    this.addMessage("This phone number is not registered. Please enter a valid registered phone number.", 'bot');
                    this.promptForPhone();
                    throw new Error('User not found');
                }
                // Now send the OTP
                const otpFormData = new URLSearchParams();
                otpFormData.append('phone', phone);
                return fetch(`${this.baseUrl}/auth/send-otp`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded'
                    },
                    body: otpFormData
                });
            })
            .then(res => res.json())
            .then(data => {
                this.hideTypingIndicator();
                this.addMessage("I've sent an OTP to your phone. Please enter it to continue.", 'bot');
                this.promptForOTP();
            })
            .catch((err) => {
                if (err.message !== 'User not found') {
                    this.hideTypingIndicator();
                    this.addMessage("Failed to send OTP. Please check your phone number and try again.", 'bot');
                    this.promptForPhone();
                }
            });
    }

    verifyOTP(phone, otp) {
        const formData = new URLSearchParams();
        formData.append('phone', phone);
        formData.append('otp', otp);
        formData.append('session_id', this.sessionId);
        fetch(`${this.baseUrl}/auth/verify-otp`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded'
                },
                body: formData
            })
            .then(res => {
                if (!res.ok) throw new Error('Invalid OTP');
                return res.json();
            })
            .then(data => {
                this.hideTypingIndicator();
                this.addMessage("Thank you! You're now logged in. How can I assist you further?", 'bot');
                // Resume the original intent
                if (this.lastUserMessage) {
                    setTimeout(() => {
                        this.generateBotResponse(this.lastUserMessage);
                    }, 500);
                }
            })
            .catch(() => {
                this.hideTypingIndicator();
                this.addMessage("Invalid OTP. Please try again.", 'bot');
                this.promptForOTP();
            });
    }

    handleQuickAction(category) {
        this.hideQuickActions();
        const categoryMessages = {
            television: "I'm interested in LED TVs. Can you show me your best deals?",
            smartphone: "I'm looking for smartphones. What are your latest models?",
            laptop: "I need a laptop. Can you help me choose the right one?",
            homeappliance: "I'm interested in home appliances. What brands and models do you have?",
            kitchenappliance: "I'm looking for kitchen appliances. What options are available?",
            ac: "I need an air conditioner. Can you show me your AC collection?"
        };

        const message = categoryMessages[category] || `I'm interested in ${category} products.`;
        this.addMessage(message, 'user');
        this.generateBotResponse(message);
    }

    showTypingIndicator() {
        this.isTyping = true;
        this.typingIndicator.classList.add('active');
        this.scrollToBottom();
    }

    hideTypingIndicator() {
        this.isTyping = false;
        this.typingIndicator.classList.remove('active');
    }

    showWelcomeMessage() {
        setTimeout(() => {
            this.showNotificationBadge();
        }, 2000);
    }

    showNotificationBadge() {
        this.notificationBadge.style.display = 'flex';
        this.notificationBadge.textContent = '1';
    }

    hideNotificationBadge() {
        this.notificationBadge.style.display = 'none';
    }

    autoResizeInput() {
        this.messageInput.style.height = 'auto';
        this.messageInput.style.height = Math.min(this.messageInput.scrollHeight, 120) + 'px';
    }

    scrollToBottom() {
        setTimeout(() => {
            this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
        }, 100);
    }

    getCurrentTime() {
        const now = new Date();
        return now.toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    // External API methods
    addExternalMessage(message, sender = 'bot') {
        this.addMessage(message, sender);
        if (!this.isOpen) {
            this.showNotificationBadge();
        }
    }

    openChatWithMessage(message) {
        this.openChat();
        setTimeout(() => {
            this.addMessage(message, 'bot');
        }, 500);
    }
}

// Initialize chatbot
document.addEventListener('DOMContentLoaded', () => {
    window.chatBot = new ChatBot();
    window.chatBot.openChat();
});

// External API
window.ChatBotAPI = {
    sendMessage: (message, sender = 'bot') => {
        if (window.chatBot) {
            window.chatBot.addExternalMessage(message, sender);
        }
    },
    openChat: () => {
        if (window.chatBot) {
            window.chatBot.openChat();
        }
    },
    closeChat: () => {
        if (window.chatBot) {
            window.chatBot.closeChat();
        }
    },
    openWithMessage: (message) => {
        if (window.chatBot) {
            window.chatBot.openChatWithMessage(message);
        }
    }
};
