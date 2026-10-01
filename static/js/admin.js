// Lotus Admin dashboard logic
(function () {
    const $ = (id) => document.getElementById(id);

    function esc(s) {
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }

    function badgeClass(status) {
        const s = (status || "").toLowerCase();
        if (s.includes("deliver") && !s.includes("out")) return "delivered";
        if (s.includes("out")) return "out";
        if (s.includes("ship")) return "shipped";
        if (s.includes("process")) return "processing";
        return "placed";
    }

    async function getJSON(url) {
        const res = await fetch(url, { headers: { Accept: "application/json" } });
        if (res.status === 401) { window.location.href = "/admin"; return null; }
        if (!res.ok) throw new Error("Request failed: " + res.status);
        return res.json();
    }

    function fmtTime(iso) {
        if (!iso) return "";
        const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
        if (isNaN(d)) return iso;
        return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    }

    async function loadStats() {
        try {
            const s = await getJSON("/admin/api/stats");
            if (!s) return;
            $("statSessions").textContent = s.sessions;
            $("statMessages").textContent = s.messages;
            $("statOrders").textContent = s.orders;
            if ($("statTickets")) $("statTickets").textContent = s.tickets != null ? s.tickets : 0;
        } catch (e) { console.error(e); }
    }

    async function loadSessions() {
        try {
            const sessions = await getJSON("/admin/api/sessions");
            if (!sessions) return;
            const body = $("sessionsBody");
            if (!sessions.length) {
                body.innerHTML = '<tr><td colspan="3" class="muted center">No sessions yet. Chat with the bot first.</td></tr>';
                return;
            }
            body.innerHTML = sessions.map(s => `
                <tr data-sid="${esc(s.session_id)}">
                    <td class="sess-id">${esc(s.session_id).slice(0, 13)}…</td>
                    <td>${s.message_count}</td>
                    <td>${fmtTime(s.last_active)}</td>
                </tr>`).join("");
            body.querySelectorAll("tr").forEach(tr => {
                tr.addEventListener("click", () => {
                    body.querySelectorAll("tr").forEach(r => r.classList.remove("active"));
                    tr.classList.add("active");
                    loadTranscript(tr.dataset.sid);
                });
            });
        } catch (e) { console.error(e); }
    }

    async function loadTranscript(sessionId) {
        const box = $("transcript");
        $("transcriptTitle").textContent = "Transcript · " + sessionId.slice(0, 8);
        box.innerHTML = '<div class="muted center">Loading…</div>';
        try {
            const data = await getJSON("/admin/api/sessions/" + encodeURIComponent(sessionId));
            if (!data) return;
            if (!data.messages.length) {
                box.innerHTML = '<div class="muted center">No messages.</div>';
                return;
            }
            box.innerHTML = data.messages.map(m => `
                <div class="bubble ${m.role === "user" ? "user" : "assistant"}">
                    ${esc(m.message)}
                    <span class="ts">${fmtTime(m.created_at)}</span>
                </div>`).join("");
        } catch (e) {
            box.innerHTML = '<div class="muted center">Failed to load transcript.</div>';
        }
    }

    async function loadOrders() {
        try {
            const orders = await getJSON("/admin/api/orders");
            if (!orders) return;
            const body = $("ordersBody");
            if (!orders.length) {
                body.innerHTML = '<tr><td colspan="6" class="muted center">No orders yet.</td></tr>';
                return;
            }
            body.innerHTML = orders.map(o => `
                <tr>
                    <td class="order-id">${esc(o.order_id)}</td>
                    <td>${esc(o.product_name)}</td>
                    <td>${esc(o.amount)}</td>
                    <td><span class="badge ${badgeClass(o.status)}">${esc(o.status)}</span></td>
                    <td>${esc(o.order_date)}</td>
                    <td>${esc(o.expected_delivery)}</td>
                </tr>`).join("");
        } catch (e) { console.error(e); }
    }

    function initTabs() {
        const panels = ["sessions", "orders", "tickets", "bulk"];
        document.querySelectorAll(".tab").forEach(tab => {
            tab.addEventListener("click", () => {
                document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
                tab.classList.add("active");
                const which = tab.dataset.tab;
                panels.forEach(p => {
                    const el = $("tab-" + p);
                    if (el) el.style.display = which === p ? "" : "none";
                });
            });
        });
    }

    async function loadTickets() {
        try {
            const tickets = await getJSON("/admin/api/tickets");
            if (!tickets) return;
            const body = $("ticketsBody");
            if (!tickets.length) {
                body.innerHTML = '<tr><td colspan="6" class="muted center">No tickets raised yet.</td></tr>';
                return;
            }
            body.innerHTML = tickets.map(t => `
                <tr>
                    <td class="order-id">${esc(t.ticket_id)}</td>
                    <td>${esc(t.name)}</td>
                    <td>${esc(t.phone)}</td>
                    <td>${esc(t.issue)}</td>
                    <td><span class="badge ${(t.status || '').toLowerCase() === 'open' ? 'processing' : 'delivered'}">${esc(t.status)}</span></td>
                    <td>${fmtTime(t.created_at)}</td>
                </tr>`).join("");
        } catch (e) { console.error(e); }
    }

    async function loadBulkEnquiries() {
        try {
            const enquiries = await getJSON('/admin/api/bulk-enquiries');
            if (!enquiries) return;
            const body = $('bulkBody');
            body.innerHTML = enquiries.map(e => `<tr>
                <td class="order-id">${esc(e.enquiry_id)}</td>
                <td>${esc(e.product_requirement)}<br><small>${esc(e.purpose)}</small><br><small>Budget/unit: ${esc(e.budget_per_unit ?? 'Not specified')}</small></td>
                <td>${esc(e.quantity)}</td>
                <td>${esc(e.contact_name)}<br>${esc(e.phone)}<br>${esc(e.company_name || '')}<br>${esc(e.email || '')}<br><small>GST: ${esc(e.gst_requirement || 'Not specified')}</small></td>
                <td>${esc(e.city)} ${esc(e.pincode || '')}<br><small>Requested: ${esc(e.required_by || 'Not specified')}</small></td>
                <td><span class="badge processing">${esc(e.status)}</span></td>
                <td>${fmtTime(e.created_at)}</td>
            </tr>`).join('') || '<tr><td colspan="7" class="muted center">No bulk enquiries yet.</td></tr>';
        } catch (e) {
            $('bulkBody').textContent = 'Unable to load bulk enquiries. Please refresh.';
        }
    }

    function refreshAll() {
        loadStats();
        loadSessions();
        loadOrders();
        loadTickets();
        loadBulkEnquiries();
    }

    document.addEventListener("DOMContentLoaded", () => {
        initTabs();
        refreshAll();
        const rb = $("refreshBtn");
        if (rb) rb.addEventListener("click", refreshAll);
    });
})();
