class ChatBot {
    constructor() {
        this.isOpen = false;
        this.isTyping = false;
        this.messageCount = 0;
        this.apiKey = 'nawabkhan';
        // Use the same origin the page was served from so it works on any port
        this.baseUrl = window.location.origin;
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
    renderProductPricing(product) {
        // Lotus uses product_msrp for list MRP and product_mrp for online selling.
        const parsePrice = value => {
            if (typeof value === 'number') return Number.isFinite(value) && value > 0 ? value : null;
            if (typeof value !== 'string') return null;
            const text = value.trim().replace(/^(?:₹|INR|Rs\.?)\s*/i, '');
            if (!/^(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d{1,2})?$/.test(text)) return null;
            const amount = Number(text.replace(/,/g, ''));
            return Number.isFinite(amount) && amount > 0 ? amount : null;
        };
        const firstPrice = values => values.map(parsePrice).find(value => value !== null) ?? null;
        const money = value => new Intl.NumberFormat('en-IN', {
            style: 'currency', currency: 'INR', minimumFractionDigits: 0, maximumFractionDigits: 2
        }).format(value);
        const mrp = firstPrice([product.mrp, product.product_msrp]);
        const selling = firstPrice([product.selling_price, product.product_selling_price, product.sale_price, product.product_mrp]);
        const legacy = firstPrice([product.price]);
        const amount = selling ?? legacy;

        const saving = mrp !== null && selling !== null && mrp > selling
            ? Math.round((mrp - selling) * 100) / 100 : 0;
        const label = selling !== null || legacy === null ? 'Online Price' : 'Listed price';
        const reference = `<span class="price-mrp">MRP ${mrp !== null
            ? saving > 0 ? `<s>${money(mrp)}</s>` : `<span>${money(mrp)}</span>`
            : '<span>Not available</span>'}</span>`;
        const savings = mrp !== null && selling !== null && mrp >= selling
            ? `<div class="price-saving">You Save <strong>${money(saving)}</strong></div>` : '';
        return `<div class="product-pricing">
            <span class="price-label">${label}</span>
            <div class="price-breakdown">${reference}</div>
            <strong class="price-amount">${amount !== null ? money(amount) : 'Not available'}</strong>
            ${savings}
            ${mrp !== null ? '<p class="price-note">MRP (Inclusive of All Taxes)</p>' : ''}
            ${selling === null ? '<p class="price-note">Confirm the current selling price.</p>' : ''}
        </div>`;
    }

    addProductCard(product) {
        if (!product || typeof product !== 'object') return;
        const text = value => typeof value === 'string' ? value.trim() : '';
        const escape = value => String(value).replace(/[&<>"']/g, char => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[char]));
        const safeUrl = value => {
            if (!text(value)) return '';
            try {
                const url = new URL(value, window.location.origin);
                return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
            } catch { return ''; }
        };
        const name = text(product.product_name) || text(product.name) || 'Product';
        const imageUrl = safeUrl(product.product_image || product.image || product.first_image);
        const productLink = safeUrl(product.product_url || product.link);
        let highlights = Array.isArray(product.features) ? product.features.map(text).filter(Boolean) : [];
        if (!highlights.length && Array.isArray(product.product_specification)) {
            highlights = product.product_specification
                .filter(spec => spec && text(spec.fkey) && text(spec.fvalue))
                .map(spec => `${spec.fkey}: ${spec.fvalue}`);
        }
        // If feature data is absent, repeat only specifications explicitly in the name.
        if (!highlights.length) {
            const patterns = [/\b\d+\s*GB\s*RAM\b/i, /\b\d+\s*(?:GB|TB)\s*(?:Storage(?:\/ROM)?|SSD|HDD)\b/i,
                /\b\d+(?:\.\d+)?\s*(?:inch(?:es)?|cm)\b/i, /\b(?:Full HD|4K|8K|OLED|QLED|AMOLED)\b/i,
                /\b\d+(?:\.\d+)?\s*(?:Ton|kg|Litres?|Liters?)\b/i];
            highlights = patterns.map(pattern => name.match(pattern)?.[0]).filter(Boolean);
        }
        highlights = [...new Set(highlights)].slice(0, 3);
        const cardDiv = document.createElement('article');
        cardDiv.className = 'product-card product-result fade-in';
        cardDiv.innerHTML = `
            <div class="card product-result-card">
                <div class="product-result-top">
                    <div class="product-result-media">
                        <div class="product-result-fallback" ${imageUrl ? 'hidden' : ''}>
                            <i class="far fa-image" aria-hidden="true"></i><span>Image unavailable</span>
                        </div>
                        ${imageUrl ? `<img src="${escape(imageUrl)}" alt="${escape(name)}" loading="lazy" decoding="async">` : ''}
                    </div>
                    <div class="product-result-info">
                        <span class="product-result-eyebrow">LOTUS ELECTRONICS</span>
                        <h3 class="product-result-title">${escape(name)}</h3>
                        ${highlights.length ? `<ul class="product-result-highlights" aria-label="Key highlights">${highlights.map(feature => `<li>${escape(feature)}</li>`).join('')}</ul>` : ''}
                    </div>
                </div>
                ${this.renderProductPricing(product)}
                <div class="product-result-actions">
                    ${productLink ? `<a href="${escape(productLink)}" target="_blank" rel="noopener noreferrer" class="product-result-view" aria-label="View ${escape(name)} on Lotus Electronics (opens in a new tab)">View product <i class="fas fa-arrow-up-right-from-square" aria-hidden="true"></i></a>` : ''}
                    <button type="button" class="product-result-ask" aria-label="Ask about ${escape(name)}"><i class="far fa-comment-dots" aria-hidden="true"></i> Ask about this</button>
                </div>
            </div>`;
        const img = cardDiv.querySelector('img');
        if (img) img.addEventListener('error', () => {
            img.hidden = true;
            cardDiv.querySelector('.product-result-fallback').hidden = false;
        });
        cardDiv.querySelector('.product-result-ask').addEventListener('click', () => {
            if (this.isTyping || this.awaitingPhone || this.awaitingOTP) return;
            this.messageInput.value = `Show me the details and specifications for ${name}`;
            this.sendMessage();
        });
        this.chatMessages.appendChild(cardDiv);
        this.scrollToBottom();
    }

    addProductDetailsCard(productDetails) {
        // Check if productDetails has meaningful content
        if (!productDetails || Object.keys(productDetails).length === 0) {
            return; // Don't show card for empty object
        }
        
        // Check if it has essential product information
        if (!productDetails.product_name && !productDetails.product_id) {
            return; // Don't show card without basic product info
        }
        
        const cardDiv = document.createElement('div');
        cardDiv.className = 'product-details-card fade-in';
        
        const product = productDetails;
        const productName = product.product_name || 'Product Details';
        const pricingHtml = this.renderProductPricing(product);
        const imageUrl = product.product_image || '';
        const inStock = product.instock || 'Unknown';
        const description = product.meta_desc || '';
        
        // Handle specifications - show top 5 specs and prioritize warranty
        let specificationsHtml = '';
        if (product.product_specification && Array.isArray(product.product_specification)) {
            let specs = [...product.product_specification];
            
            // Look for warranty in specs and prioritize it
            const warrantyIndex = specs.findIndex(spec => 
                spec.fkey && spec.fkey.toLowerCase().includes('warranty')
            );
            
            if (warrantyIndex !== -1) {
                // Move warranty to the front
                const warranty = specs.splice(warrantyIndex, 1)[0];
                specs.unshift(warranty);
            }
            
            // Take only top 5 specifications
            const topSpecs = specs.slice(0, 5);
            
            specificationsHtml = `
                <div class="specifications mb-3">
                    <h6 class="text-primary mb-2">
                        <i class="fas fa-list-check me-1"></i>Key Specifications
                    </h6>
                    <div class="row">
                        ${topSpecs.map(spec => `
                            <div class="col-12 mb-1">
                                <small class="text-muted">${spec.fkey}:</small>
                                <span class="fw-bold ms-1">${spec.fvalue}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }
        
        // Handle delivery options
        let deliveryHtml = '';
        if (product.del) {
            deliveryHtml = `
                <div class="delivery-options mb-3">
                    <h6 class="text-success mb-2">
                        <i class="fas fa-truck me-1"></i>Delivery Options
                    </h6>
                    ${product.del.std ? `<p class="mb-1"><i class="fas fa-box me-1 text-info"></i><small>${product.del.std}</small></p>` : ''}
                    ${product.del.t3h ? `<p class="mb-1"><i class="fas fa-bolt me-1 text-warning"></i><small>${product.del.t3h}</small></p>` : ''}
                    ${product.del.stp ? `<p class="mb-1"><i class="fas fa-store me-1 text-primary"></i><small>${product.del.stp}</small></p>` : ''}
                </div>
            `;
        }

        cardDiv.innerHTML = `
            <div class="card mb-3 shadow border product-detail-card">
                <div class="card-header bg-primary text-white py-2">
                    <h6 class="mb-0">
                        <i class="fas fa-info-circle me-2"></i>Product Details
                    </h6>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-4 text-center mb-3">
                            <img src="${imageUrl}" alt="${productName}" class="img-fluid rounded shadow-sm" style="max-height: 200px;" onerror="this.style.display='none'" />
                            <div class="mt-2">
                                <span class="badge ${inStock.toLowerCase() === 'yes' ? 'bg-success' : 'bg-warning'} px-3">
                                    <i class="fas fa-${inStock.toLowerCase() === 'yes' ? 'check' : 'clock'} me-1"></i>
                                    ${inStock.toLowerCase() === 'yes' ? 'In Stock' : 'Check Availability'}
                                </span>
                            </div>
                        </div>
                        <div class="col-md-8">
                            <h5 class="card-title text-dark mb-2">${productName}</h5>
                            ${pricingHtml}
                        </div>
                        <div>
                        ${specificationsHtml}
                        ${deliveryHtml}
                        ${description ? `
                                <div class="description mb-3">
                                    <h6 class="text-secondary mb-2">
                                        <i class="fas fa-file-alt me-1"></i>Description
                                    </h6>
                                    <p class="text-muted small">${description.length > 150 ? description.substring(0, 150) + '...' : description}</p>
                                </div>
                            ` : ''}
                            
                            <div class="action-buttons">
                                <button class="btn btn-primary me-2" onclick="window.open('https://www.lotuselectronics.com/product/${product.uri_slug || ''}/${product.product_id || ''}', '_blank')">
                                    <i class="fas fa-shopping-cart me-1"></i>Buy Now
                                </button>
                                <button class="btn btn-outline-success" onclick="window.open('tel:0731-4265577', '_self')">
                                    <i class="fas fa-phone me-1"></i>Call for Details
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        this.chatMessages.appendChild(cardDiv);
        this.scrollToBottom();
    }

    addStoreCard(store) {
        const cardDiv = document.createElement('div');
        cardDiv.className = 'store-card fade-in';
        
        // Map the correct field names from backend
        const storeName = store.store_name || store.name || 'Store';
        const address = store.address || 'Address not available';
        const city = store.city || '';
        const state = store.state || '';
        const zipcode = store.zipcode || '';
        const timing = store.timings || store.timing || 'Timing not available'; // Check both timings and timing
        const phone = store.phone || '0731-4265577'; // Default phone number
        
        // Format full address
        const fullAddress = `${address}${city ? ', ' + city : ''}${zipcode ? ' - ' + zipcode : ''}${state ? ', ' + state : ''}`;

        cardDiv.innerHTML = `
            <div class="card mb-2 shadow-sm border">
                <div class="row g-0">
                    <div class="col-2 d-flex align-items-center justify-content-center bg-light">
                        <i class="fas fa-store text-primary" style="font-size: 1.5rem;"></i>
                    </div>
                    <div class="col-10">
                        <div class="card-body p-3">
                            <h6 class="card-title mb-2 text-primary">
                                <i class="fas fa-map-marker-alt me-1"></i>
                                ${storeName}
                            </h6>
                            <p class="card-text mb-2" style="font-size: 0.9rem;">
                                <i class="fas fa-location-dot me-1 text-muted"></i>
                                ${fullAddress}
                            </p>
                            <p class="card-text mb-2" style="font-size: 0.9rem;">
                                <i class="fas fa-clock me-1 text-success"></i>
                                <span class="text-success fw-bold">${timing}</span>
                            </p>
                            <div class="d-flex gap-2">
                                <button class="btn btn-sm btn-outline-primary" onclick="window.open('https://maps.google.com/?q=${encodeURIComponent(storeName + ' ' + fullAddress)}', '_blank')">
                                    <i class="fas fa-directions me-1"></i>Get Directions
                                </button>
                                <button class="btn btn-sm btn-outline-success" onclick="window.open('tel:${phone}', '_self')">
                                    <i class="fas fa-phone me-1"></i>Call Store
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        this.chatMessages.appendChild(cardDiv);
        this.scrollToBottom();
    }

    addPolicyInfoCard(policyInfo) {
        if (!policyInfo.policy_sections || !Array.isArray(policyInfo.policy_sections)) {
            return;
        }

        const cardDiv = document.createElement('div');
        cardDiv.className = 'policy-card fade-in';
        
        let policySectionsHtml = '';
        policyInfo.policy_sections.forEach((section, index) => {
            const relevanceColor = section.relevance_score >= 0.9 ? 'text-success' : 
                                  section.relevance_score >= 0.8 ? 'text-warning' : 'text-info';
            
            policySectionsHtml += `
                <div class="policy-section mb-3 ${index > 0 ? 'border-top pt-3' : ''}">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <span class="badge bg-secondary">${section.document || 'Policy'}</span>
                        <small class="${relevanceColor}">
                            <i class="fas fa-star me-1"></i>
                            ${Math.round(section.relevance_score * 100)}% relevant
                        </small>
                    </div>
                    <div class="policy-content" style="font-size: 0.9rem; line-height: 1.5;">
                        ${section.content.replace(/\n/g, '<br>')}
                    </div>
                </div>
            `;
        });

        cardDiv.innerHTML = `
            <div class="card mb-2 shadow-sm border-info">
                <div class="row g-0">
                    <div class="col-2 d-flex align-items-center justify-content-center bg-light">
                        <i class="fas fa-shield-alt text-info" style="font-size: 1.5rem;"></i>
                    </div>
                    <div class="col-10">
                        <div class="card-body p-3">
                            <h6 class="card-title mb-3 text-info">
                                <i class="fas fa-file-contract me-1"></i>
                                Policy Information
                                <small class="text-muted">(${policyInfo.total_found || 0} section${policyInfo.total_found !== 1 ? 's' : ''} found)</small>
                            </h6>
                            ${policySectionsHtml}
                            <div class="mt-3 p-2 bg-light rounded">
                                <small class="text-muted">
                                    <i class="fas fa-info-circle me-1"></i>
                                    For complete terms and conditions, please visit our official website or contact customer service.
                                </small>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        this.chatMessages.appendChild(cardDiv);
        this.scrollToBottom();
    }

    addComparisonCard(item) {
        if (!item || (item.error && !item.spec_table)) {
            if (item && item.error) this.addMessage(item.error, 'bot');
            return;
        }
        const cardDiv = document.createElement('div');
        cardDiv.className = 'comparison-card fade-in';

        // Present the comparison payload as supplied; do not infer a winner or specs.
        const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[char]);
        const hasValue = value => value != null && String(value).trim() !== '' &&
            !['-', '—', 'n/a', 'null', 'undefined'].includes(String(value).trim().toLowerCase());
        const formatPrice = value => typeof value === 'number' && Number.isFinite(value)
            ? new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value)
            : String(value);
        const imageSource = value => {
            if (typeof value !== 'string' || !value.trim()) return '';
            try {
                const url = new URL(value, window.location.origin);
                return ['https:', 'http:'].includes(url.protocol) ? url.href : '';
            } catch { return ''; }
        };
        const rows = (Array.isArray(item.spec_table) ? item.spec_table : [])
            .filter(row => row && typeof row === 'object' && hasValue(row.feature));
        const priceRow = rows.find(row => /^price$/i.test(String(row.feature).trim()));
        const specs = rows.filter(row => row !== priceRow);
        const names = [item.name || 'Product A', item.vs_name || 'Product B'];
        const products = ['a', 'b'].map((side, index) => {
            const image = imageSource(item[`image_${side}`]);
            const price = hasValue(item[`price_${side}`]) ? item[`price_${side}`] : priceRow?.[side];
            const highlights = specs.filter(row => hasValue(row[side])).slice(0, 3);
            return `<article class="cmp-product cmp-product-${side}" aria-label="${escape(names[index])}">
                <div class="cmp-product-image">
                    <span class="cmp-option">OPTION ${index + 1}</span>
                    <span class="cmp-image-fallback"${image ? ' hidden' : ''}><i class="fas fa-image" aria-hidden="true"></i><span>Image unavailable</span></span>
                    ${image ? `<img src="${escape(image)}" alt="${escape(names[index])}" loading="lazy" decoding="async">` : ''}
                </div>
                <div class="cmp-product-info">
                    <h3>${escape(names[index])}</h3>
                    ${hasValue(item[`selling_price_${side}`]) || hasValue(item[`mrp_${side}`])
                        ? this.renderProductPricing({mrp: item[`mrp_${side}`], selling_price: item[`selling_price_${side}`], store_offer_price: item[`store_offer_price_${side}`]})
                        : `<p class="cmp-price${hasValue(price) ? '' : ' cmp-price-missing'}">${hasValue(price) ? escape(formatPrice(price)) : 'Price unavailable'}</p>`}
                    ${highlights.length ? `<ul class="cmp-highlights">${highlights.map(row => `<li><span>${escape(row.feature)}</span><strong>${escape(row[side])}</strong></li>`).join('')}</ul>` : ''}
                </div>
            </article>`;
        }).join('');
        const differences = (Array.isArray(item.differences) ? item.differences : []).filter(hasValue);
        const rowsHtml = rows.map(row => {
            const differs = hasValue(row.a) && hasValue(row.b) && String(row.a).trim() !== String(row.b).trim();
            return `<tr${differs ? ' class="cmp-row-different"' : ''}>
                <th scope="row" class="cmp-feature">${escape(row.feature)}</th>
                <td>${hasValue(row.a) ? escape(row.a) : 'Not provided'}</td>
                <td>${hasValue(row.b) ? escape(row.b) : 'Not provided'}</td>
            </tr>`;
        }).join('');

        cardDiv.innerHTML = `
            <section class="cmp-wrap cmp-premium" aria-label="Product comparison">
                <header class="cmp-intro"><span class="cmp-intro-icon"><i class="fas fa-code-compare" aria-hidden="true"></i></span><div><span class="cmp-eyebrow">A CLOSER LOOK</span><h2>Find your better fit.</h2><p>Two options. The details that matter.</p></div><span class="cmp-count">2 PRODUCTS</span></header>
                <div class="cmp-products">${products}<span class="cmp-versus" aria-hidden="true">VS</span></div>
                ${differences.length ? `<section class="cmp-differences"><h3><i class="fas fa-bolt" aria-hidden="true"></i> Key differences</h3><ul>${differences.map(difference => `<li><span class="cmp-difference-dot" aria-hidden="true"></span><span>${escape(difference)}</span></li>`).join('')}</ul></section>` : ''}
                ${rows.length ? `<details class="cmp-specs"><summary><span><i class="fas fa-list" aria-hidden="true"></i> Full specification comparison</span><span class="cmp-expand-icon" aria-hidden="true">+</span></summary><div class="cmp-table-scroll" role="region" aria-label="Full product specifications" tabindex="0"><table class="cmp-table"><caption class="visually-hidden">Specifications for ${escape(names[0])} and ${escape(names[1])}</caption><thead><tr><th scope="col">Feature</th><th scope="col">${escape(names[0])}</th><th scope="col">${escape(names[1])}</th></tr></thead><tbody>${rowsHtml}</tbody></table></div><p class="cmp-table-note">Shaded rows show different specifications.</p></details>` : ''}
                ${hasValue(item.verdict) ? `<section class="cmp-recommendation"><span class="cmp-recommendation-icon"><i class="fas fa-lightbulb" aria-hidden="true"></i></span><div><h3>The Lotus take</h3><p>${escape(item.verdict)}</p></div></section>` : ''}
            </section>`;

        cardDiv.querySelectorAll('.cmp-product-image img').forEach(image => {
            image.addEventListener('error', () => {
                image.hidden = true;
                image.previousElementSibling.hidden = false;
            }, { once: true });
        });

        this.chatMessages.appendChild(cardDiv);
        this.scrollToBottom();
    }

    addRecommendationHeader() {
        const div = document.createElement('div');
        div.className = 'reco-header fade-in';
        div.innerHTML = `<i class="fas fa-wand-magic-sparkles"></i> Recommended for you`;
        this.chatMessages.appendChild(div);
        this.scrollToBottom();
    }

    addOrderCard(order) {
        const cardDiv = document.createElement('div');
        cardDiv.className = 'order-card fade-in';

        const timeline = Array.isArray(order.timeline) ? order.timeline : [];
        const stepsHtml = timeline.map(t => `
            <div class="order-step ${t.state}">
                <div class="order-dot"><i class="fas fa-${t.state === 'done' ? 'check' : (t.state === 'current' ? 'location-dot' : 'circle')}"></i></div>
                <div class="order-step-label">${t.stage}${t.date ? `<span>${t.date}</span>` : ''}</div>
            </div>`).join('');

        cardDiv.innerHTML = `
            <div class="order-wrap">
                <div class="order-head">
                    <span><i class="fas fa-box"></i> Order ${order.order_id}</span>
                    <span class="order-status">${order.status || ''}</span>
                </div>
                <div class="order-product">${order.product_name || ''}</div>
                <div class="order-meta">
                    ${order.amount ? `<span><i class="fas fa-tag"></i> ${order.amount}</span>` : ''}
                    ${order.order_date ? `<span><i class="fas fa-calendar"></i> ${order.order_date}</span>` : ''}
                    ${order.expected_delivery ? `<span><i class="fas fa-truck"></i> Est. ${order.expected_delivery}</span>` : ''}
                </div>
                <div class="order-timeline">${stepsHtml}</div>
            </div>`;

        this.chatMessages.appendChild(cardDiv);
        this.scrollToBottom();
    }

    addBulkEnquiryCard(enquiry) {
        const card = document.createElement('article');
        card.className = 'bulk-enquiry-card fade-in';
        const append = (tag, className, text) => {
            const element = document.createElement(tag);
            element.className = className;
            element.textContent = text;
            card.appendChild(element);
            return element;
        };
        append('h3', 'bulk-enquiry-title', 'Bulk enquiry saved');
        append('p', 'bulk-enquiry-id', enquiry.enquiry_id);
        append('p', 'bulk-enquiry-status', enquiry.status);
        append('p', 'bulk-enquiry-product', enquiry.product_requirement);
        const details = document.createElement('dl');
        details.className = 'bulk-enquiry-details';
        [
            ['Quantity', `${enquiry.quantity} units`],
            ['Delivery city', enquiry.city],
            ['Company', enquiry.company_name],
            ['Contact name', enquiry.contact_name],
            ['Mobile', enquiry.phone],
            ['Email', enquiry.email],
            ['Delivery PIN', enquiry.pincode],
            ['GST invoice', enquiry.gst_requirement],
            ['Purpose', enquiry.purpose],
            ['Budget per unit', enquiry.budget_per_unit && new Intl.NumberFormat('en-IN', {style: 'currency', currency: 'INR'}).format(enquiry.budget_per_unit)],
            ['Requested by', enquiry.required_by]
        ].filter(([, value]) => value !== null && value !== undefined && value !== '').forEach(([label, value]) => {
            const term = document.createElement('dt');
            const description = document.createElement('dd');
            term.textContent = label;
            description.textContent = value;
            details.append(term, description);
        });
        card.appendChild(details);
        append('p', 'bulk-enquiry-notice', 'Quotation request only. Final pricing, stock and delivery are not yet confirmed.');
        this.chatMessages.appendChild(card);
        this.scrollToBottom();
    }

    addTicketCard(ticket) {
        const cardDiv = document.createElement('div');
        cardDiv.className = 'ticket-card fade-in';
        cardDiv.innerHTML = `
            <div class="ticket-wrap">
                <div class="ticket-head">
                    <span><i class="fas fa-headset"></i> Support Ticket Raised</span>
                    <span class="ticket-status">${ticket.status || 'Open'}</span>
                </div>
                <div class="ticket-id-row">
                    <i class="fas fa-hashtag"></i> Ticket ID: <strong>${ticket.ticket_id}</strong>
                </div>
                <div class="ticket-meta">
                    ${ticket.name ? `<span><i class="fas fa-user"></i> ${ticket.name}</span>` : ''}
                    ${ticket.phone ? `<span><i class="fas fa-phone"></i> ${ticket.phone}</span>` : ''}
                </div>
                ${ticket.issue ? `<div class="ticket-issue"><i class="fas fa-circle-exclamation"></i> ${ticket.issue}</div>` : ''}
                <div class="ticket-foot"><i class="fas fa-clock"></i> Our team will get back to you shortly.</div>
            </div>`;
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
    //             <p class="product-price">ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¹${product.price}</p>
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


    processStructuredResponse(responseData) {
        let answer = responseData.answer;
        const products = responseData.products;
        const productDetails = responseData.product_details;
        const stores = responseData.stores;
        const policyInfo = responseData.policy_info;
        const comparison = responseData.comparison;
        const recommendations = responseData.recommendations;
        const order = responseData.order;
        const ticket = responseData.ticket;
        const bulkEnquiry = responseData.bulk_enquiry;
        const end = responseData.end;

        // If stores are present, clean up the answer to avoid duplication
        if (stores && Array.isArray(stores) && stores.length > 0) {
            // Remove store listing from answer text but keep the intro
            const lines = answer.split('\n');
            const cleanedLines = [];
            let skipMode = false;
            
            for (let line of lines) {
                // Skip lines that contain store details (bullets, addresses, timings)
                if (line.includes('*') || line.includes('📍') || line.includes('🕒') || 
                    line.includes('Store at') || line.includes('AM') || line.includes('PM')) {
                    skipMode = true;
                    continue;
                }
                
                // Keep intro lines and question at the end
                if (!skipMode || line.trim() === '' || line.includes('?') || 
                    line.includes('specific area') || line.includes('looking for')) {
                    cleanedLines.push(line);
                    skipMode = false;
                }
            }
            
            answer = cleanedLines.join('\n').trim();
            
            // If answer becomes too short, provide a generic intro
            if (answer.length < 20) {
                answer = `Great! Here are ${stores.length} Lotus Electronics stores found:`;
            }
        }

        if (answer) this.addMessage(answer, 'bot');
        if (products && Array.isArray(products)) {
            products.forEach(product => this.addProductCard(product));
        }
        if (productDetails && Array.isArray(productDetails)) {
            productDetails.forEach(details => this.addProductDetailsCard(details));
        } else if (productDetails && typeof productDetails === 'object' && Object.keys(productDetails).length > 0) {
            // Handle single product detail object - only if it has content
            this.addProductDetailsCard(productDetails);
        }
        if (stores && Array.isArray(stores)) {
            stores.forEach(store => this.addStoreCard(store));
        }
        
        // Handle policy info with better debugging and nested structure support
        if (policyInfo && typeof policyInfo === 'object') {
            console.log('🔍 Policy info received:', policyInfo);
            
            // Check for nested structure first
            if (policyInfo.search_terms_conditions_response && policyInfo.search_terms_conditions_response.success) {
                console.log('📋 Using nested policy structure');
                this.addPolicyInfoCard(policyInfo.search_terms_conditions_response);
            } else if (policyInfo.success) {
                console.log('📋 Using direct policy structure');
                this.addPolicyInfoCard(policyInfo);
            } else {
                console.log('⚠️ Policy info present but no success field found');
            }
        }
        if (comparison && Array.isArray(comparison)) {
            comparison.forEach(item => this.addComparisonCard(item));
        }
        if (recommendations && Array.isArray(recommendations) && recommendations.length > 0) {
            this.addRecommendationHeader();
            recommendations.forEach(product => this.addProductCard(product));
        }
        if (order && typeof order === 'object' && order.order_id) {
            this.addOrderCard(order);
        }
        if (ticket && typeof ticket === 'object' && ticket.ticket_id) {
            this.addTicketCard(ticket);
        }
        if (bulkEnquiry && typeof bulkEnquiry === 'object' && bulkEnquiry.enquiry_id) {
            this.addBulkEnquiryCard(bulkEnquiry);
        }
        if (end) this.addMessage(end, 'bot');
    }

    generateBotResponse(userMessage, retryCount = 0) {
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
                session_id: this.sessionId
            })
        };

        fetch(`${this.baseUrl}/chat`, requestOptions)
            .then(async response => {
                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    const statusMessage = {
                        429: 'Too many requests - please wait before trying again',
                        500: 'Server is experiencing high traffic - please try again shortly',
                        502: 'Server temporarily unavailable',
                        503: 'Service temporarily unavailable',
                        504: 'Request timed out - please try again'
                    }[response.status] || `Server error (${response.status})`;
                    
                    throw new Error(errorData.detail || statusMessage);
                }
                return response.json();
            })
            .then(data => {
                this.hideTypingIndicator();
                
                console.log("Response received:", data); // Debug logging

                // Handle the new JSON response format
                if (data.response) {
                    // If response is wrapped, unwrap it
                    if (typeof data.response === 'string') {
                        try {
                            data = JSON.parse(data.response);
                        } catch (e) {
                            console.log("Failed to parse response string:", e);
                            data = { answer: data.response };
                        }
                    } else {
                        data = data.response;
                    }
                }

                // Check for structured response format
                if (data.status === "success" || (data.status === "partial" && data.data)) {
                    this.processStructuredResponse(data.data);
                } else if (data.answer !== undefined) {
                    // Direct response format (answer, products, stores, etc. at top level)
                    this.processStructuredResponse(data);
                } else if (data.status === "error" && data.data) {
                    this.addMessage(data.data.answer || "Sorry, something went wrong.", 'bot');
                } else if (data.status === "error" && data.data) {
                    this.addMessage(data.data.answer || "Sorry, something went wrong.", 'bot');
                } else {
                    // Handle different response formats
                    console.log("Unexpected response format:", data);
                    
                    // Check if it's a simple string response
                    if (typeof data === 'string') {
                        this.addMessage(data, 'bot');
                    } else if (data.response) {
                        this.addMessage(data.response, 'bot');
                    } else if (data.answer) {
                        this.addMessage(data.answer, 'bot');
                    } else if (data.message) {
                        this.addMessage(data.message, 'bot');
                    } else {
                        // Provide contextual response based on user message
                        const userMsg = userMessage.toLowerCase();
                        let responseMsg = "I'm here to help! How can I assist you with Lotus Electronics products today?";
                        
                        if (userMsg.includes('hello') || userMsg.includes('hi') || userMsg.includes('hey')) {
                            responseMsg = "Hello! Welcome to Lotus Electronics! I'm here to help you find the perfect electronics products. What are you looking for today?";
                        } else if (userMsg.includes('help')) {
                            responseMsg = "I'd be happy to help! I can assist you with:\n• Finding products (TVs, smartphones, laptops, etc.)\n• Getting detailed product specifications\n• Locating nearby Lotus stores\n• Checking product availability\n\nWhat would you like to explore?";
                        } else if (userMsg.includes('thanks') || userMsg.includes('thank you')) {
                            responseMsg = "You're welcome! Is there anything else I can help you find in our electronics collection?";
                        }
                        
                        this.addMessage(responseMsg, 'bot');
                    }
                }
            })
            .catch(error => {
                console.error("API error:", error);
                this.hideTypingIndicator();
                
                // Check if this is a retryable error and we haven't exceeded retry limit
                const isRetryableError = error.message.includes('500') || 
                                       error.message.includes('502') || 
                                       error.message.includes('503') || 
                                       error.message.includes('504') ||
                                       error.message.includes('timeout') ||
                                       error.message.includes('Network');
                
                if (isRetryableError && retryCount < 2) {
                    // Show retry message and attempt again after delay
                    this.addMessage("Connection issue detected. Retrying in a moment...", 'bot');
                    setTimeout(() => {
                        this.generateBotResponse(userMessage, retryCount + 1);
                    }, (retryCount + 1) * 2000); // Exponential backoff: 2s, 4s
                    return;
                }
                
                // Provide specific error messages
                let errorMessage = "I apologize, but I'm having trouble. Please try again.";
                
                if (error.message.includes('500')) {
                    errorMessage = "I'm experiencing high traffic right now. Please wait a moment and try again.";
                } else if (error.message.includes('429')) {
                    errorMessage = "Too many requests. Please wait a few seconds before trying again.";
                } else if (error.message.includes('503') || error.message.includes('502')) {
                    errorMessage = "Service temporarily unavailable. Please try again in a moment.";
                } else if (error.message.includes('Network') || error.message.includes('timeout')) {
                    errorMessage = "Network connection issue. Please check your internet and try again.";
                }
                
                this.addMessage(errorMessage, 'bot');
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
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
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
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
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
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
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
            ac: "I need an air conditioner. Can you show me your AC collection?",
            recommend: "Can you recommend a good smartphone under 20000?",
            trackorder: "I'd like to track my order LOTUS1001.",
            raiseticket: "I have an issue and would like to raise a support ticket.",
            storelocator: "I want to find a Lotus Electronics store near me. Can you help?"
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
        return now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
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
