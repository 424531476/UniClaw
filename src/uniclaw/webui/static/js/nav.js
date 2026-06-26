/* nav.js — 消息导航条 */

const MsgNav = {
    _items: [],
    _navEl: null,
    _listEl: null,
    _observer: null,
    _highlightTimer: null,

    init() {
        this._navEl = document.getElementById('msg-nav');
        this._listEl = this._navEl?.querySelector('.msg-nav-list');
        if (!this._navEl || !this._listEl) return;
        this._scan();
        const container = document.getElementById('chat-messages');
        if (container) {
            this._observer = new MutationObserver(() => this._scan());
            this._observer.observe(container, { childList: true });
        }
    },

    refresh() { this._items = []; if (this._listEl) this._listEl.innerHTML = ''; this._scan(); },

    _scan() {
        const container = document.getElementById('chat-messages');
        if (!container || !this._listEl) return;
        const userMsgs = container.querySelectorAll('.message.user');
        const count = userMsgs.length;
        if (count === this._items.length) return;
        this._items = []; this._listEl.innerHTML = '';
        userMsgs.forEach((msgEl, i) => {
            const body = msgEl.querySelector('.msg-body');
            const text = body ? body.textContent.trim() : '';
            const summary = (text.replace(/\s+/g, ' ').slice(0, 50) || `消息 ${i + 1}`) + (text.length > 50 ? '...' : '');
            const item = document.createElement('div');
            item.className = 'msg-nav-item';
            item.textContent = summary;
            item.title = text;
            item.addEventListener('click', () => this._scrollTo(msgEl, item));
            this._listEl.appendChild(item);
            this._items.push({ el: msgEl, text: summary });
        });
        this._navEl.style.display = count > 0 ? '' : 'none';
    },

    _scrollTo(msgEl, itemEl) {
        msgEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
        msgEl.style.boxShadow = '0 0 0 2px var(--accent-glow)';
        if (this._highlightTimer) clearTimeout(this._highlightTimer);
        this._highlightTimer = setTimeout(() => { msgEl.style.boxShadow = ''; }, 1500);
        this._listEl.querySelectorAll('.msg-nav-item').forEach(el => el.classList.remove('active'));
        itemEl.classList.add('active');
    },
};
