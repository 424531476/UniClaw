/* nav.js — 消息导航目录（右侧悬浮导航条） */

const MsgNav = {
    _items: [],
    _navEl: null,
    _listEl: null,
    _observer: null,
    _highlightTimer: null,

    /** 初始化 */
    init() {
        this._navEl = document.getElementById('msg-nav');
        this._listEl = this._navEl ? this._navEl.querySelector('.msg-nav-list') : null;
        if (!this._navEl || !this._listEl) return;

        // 初始扫描已有消息
        this._scan();

        // 监听 #chat-messages 的子元素变化
        const container = document.getElementById('chat-messages');
        if (container) {
            this._observer = new MutationObserver(() => this._scan());
            this._observer.observe(container, { childList: true });
        }
    },

    /** 强制重建导航列表 */
    refresh() {
        this._items = [];
        if (this._listEl) this._listEl.innerHTML = '';
        this._scan();
    },

    /** 扫描所有用户消息,重建列表 */
    _scan() {
        const container = document.getElementById('chat-messages');
        if (!container || !this._listEl) return;

        const userMsgs = container.querySelectorAll('.message.user');
        const count = userMsgs.length;

        // 数量未变化时跳过重建
        if (count === this._items.length) return;

        this._items = [];
        this._listEl.innerHTML = '';

        userMsgs.forEach((msgEl, i) => {
            // 提取文本摘要
            const bubble = msgEl.querySelector('.msg-bubble');
            const text = bubble ? bubble.textContent.trim() : '';
            const summary = this._truncate(text, 50) || `消息 ${i + 1}`;

            const item = document.createElement('div');
            item.className = 'msg-nav-item';
            item.textContent = summary;
            item.title = text;
            item.addEventListener('click', () => this._scrollTo(msgEl, item));
            this._listEl.appendChild(item);
            this._items.push({ el: msgEl, text: summary });
        });

        // 没有用户消息时隐藏导航条
        this._navEl.style.display = count > 0 ? '' : 'none';
    },

    /** 滚动到目标消息并高亮 */
    _scrollTo(msgEl, itemEl) {
        // 滚动
        msgEl.scrollIntoView({ behavior: 'smooth', block: 'start' });

        // 高亮目标消息
        msgEl.classList.add('msg-nav-highlight');
        if (this._highlightTimer) clearTimeout(this._highlightTimer);
        this._highlightTimer = setTimeout(() => {
            msgEl.classList.remove('msg-nav-highlight');
        }, 1500);

        // 高亮导航项
        this._listEl.querySelectorAll('.msg-nav-item').forEach(el => el.classList.remove('active'));
        itemEl.classList.add('active');
    },

    /** 截断文本 */
    _truncate(text, maxLen) {
        if (!text) return '';
        // 去掉多余空白
        text = text.replace(/\s+/g, ' ').trim();
        return text.length > maxLen ? text.slice(0, maxLen) + '...' : text;
    },
};
