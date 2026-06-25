/* permission.js — 权限弹窗组件 */

const Permission = {
    currentRequest: null,
    _countdownTimer: null,
    _countdownSeconds: 300, // 5 分钟

    /** 初始化 */
    init() {
        WS.on('permission_request', (msg) => this._onRequest(msg));
        WS.on('session_attention', (msg) => this._onAttention(msg));

        document.getElementById('perm-allow').onclick = () => this._respond(true);
        document.getElementById('perm-deny').onclick = () => this._respond(false);

        // 权限模式切换 - 阻止事件冒泡
        document.getElementById('status-permission').onclick = (e) => {
            e.stopPropagation();
            this.showModeMenu();
        };
    },

    /** 收到权限请求 */
    _onRequest(msg) {
        // 非当前会话的请求不弹窗(左侧面板红点已通过 session_attention 提示)
        if (!msg || msg.session_id !== SessionPanel.activeSessionId) return;
        this.currentRequest = msg;
        document.getElementById('perm-tool').textContent = msg.tool_name || '';
        document.getElementById('perm-args').textContent = JSON.stringify(msg.args || {}, null, 2);
        if (msg.explanation) {
            document.getElementById('perm-explanation').style.display = 'block';
            document.getElementById('perm-explanation-text').textContent = msg.explanation;
        } else {
            document.getElementById('perm-explanation').style.display = 'none';
        }
        document.getElementById('perm-reason').value = '';
        document.getElementById('perm-always').checked = false;
        document.getElementById('permission-modal').style.display = 'flex';
        // 根据后端 created_at 校准倒计时（重发时也能正确恢复）
        this._startCountdown(msg.created_at, msg.timeout);
    },

    /** 关闭不属于目标会话的弹窗(会话切换时调用) */
    closeIfSessionMismatch(targetSessionId) {
        if (this.currentRequest && this.currentRequest.session_id !== targetSessionId) {
            this._stopCountdown();
            document.getElementById('permission-modal').style.display = 'none';
            this.currentRequest = null;
        }
    },

    /** 收到非当前会话的权限提醒(高亮由 session.js 统一处理) */
    _onAttention(msg) {
        Utils.showToast(msg.message || '需要权限确认');
    },

    /** 响应权限请求 */
    _respond(approved) {
        if (!this.currentRequest) return;
        this._stopCountdown();
        const always = document.getElementById('perm-always').checked;
        const msg = {
            type: 'permission_response',
            session_id: this.currentRequest.session_id,
            id: this.currentRequest.id,
            approved: approved,
            reason: approved ? '' : document.getElementById('perm-reason').value,
            always: always && approved,
        };
        WS.send(msg);
        document.getElementById('permission-modal').style.display = 'none';
        this.currentRequest = null;
    },

    /** 启动倒计时，根据后端 created_at 校准剩余秒数 */
    _startCountdown(createdAt, timeout) {
        this._stopCountdown();
        const TIMEOUT = timeout || 300;
        if (createdAt) {
            const elapsed = Math.floor(Date.now() / 1000) - createdAt;
            this._countdownSeconds = Math.max(0, TIMEOUT - elapsed);
        } else {
            this._countdownSeconds = TIMEOUT;
        }
        const el = document.getElementById('perm-countdown');
        if (!el) return;
        el.textContent = this._formatTime(this._countdownSeconds);
        if (this._countdownSeconds <= 0) {
            this._respond(false);
            Utils.showToast('权限请求已超时自动拒绝');
            return;
        }
        this._countdownTimer = setInterval(() => {
            this._countdownSeconds--;
            el.textContent = this._formatTime(this._countdownSeconds);
            if (this._countdownSeconds <= 0) {
                this._respond(false);
                Utils.showToast('权限请求已超时自动拒绝');
            }
        }, 1000);
    },

    /** 停止倒计时 */
    _stopCountdown() {
        if (this._countdownTimer) {
            clearInterval(this._countdownTimer);
            this._countdownTimer = null;
        }
    },

    /** 格式化时间 */
    _formatTime(seconds) {
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        return `${m}:${s.toString().padStart(2, '0')}`;
    },

    /** 循环切换权限模式(Shift+Tab) */
    _cycleMode() {
        const modes = ['Auto', 'Manual', 'Accept All', 'Plan'];
        const icons = ['🔒', '🔐', '✅', '📋'];
        const el = document.getElementById('status-permission');
        const current = el.textContent.trim();
        let idx = modes.findIndex(m => current.includes(m));
        idx = (idx + 1) % modes.length;
        this._setMode(idx);
    },

    /** 显示权限模式下拉菜单 */
    showModeMenu() {
        this._hideModeMenu();
        const modes = ['Auto', 'Manual', 'Accept All', 'Plan'];
        const icons = ['🔒', '🔐', '✅', '📋'];
        const el = document.getElementById('status-permission');
        const current = el.textContent.trim();

        const menu = document.createElement('div');
        menu.id = 'perm-mode-menu';
        menu.className = 'context-menu';
        // 根据点击元素位置定位菜单
        const rect = el.getBoundingClientRect();
        menu.style.cssText = `position:fixed;bottom:${window.innerHeight - rect.top + 4}px;left:${rect.left}px;z-index:1000`;
        modes.forEach((mode, idx) => {
            const isActive = current.includes(mode);
            const item = document.createElement('div');
            item.className = 'context-menu-item' + (isActive ? ' active' : '');
            item.style.cssText = isActive ? 'background:var(--accent);color:#fff' : '';
            item.textContent = `${icons[idx]} ${mode}`;
            item.onclick = () => { this._setMode(idx); this._hideModeMenu(); };
            menu.appendChild(item);
        });
        document.body.appendChild(menu);
        setTimeout(() => document.addEventListener('click', this._hideModeMenu, { once: true }), 0);
    },

    /** 隐藏权限模式菜单 */
    _hideModeMenu() {
        const menu = document.getElementById('perm-mode-menu');
        if (menu) menu.remove();
    },

    /** 设置权限模式 */
    _setMode(idx) {
        const modes = ['Auto', 'Manual', 'Accept All', 'Plan'];
        const icons = ['🔒', '🔐', '✅', '📋'];
        const el = document.getElementById('status-permission');
        el.textContent = `${icons[idx]} ${modes[idx]}`;

        const sessionId = SessionPanel.activeSessionId;
        if (sessionId) {
            fetch('/api/config', {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: sessionId,
                    permission_mode: modes[idx].toLowerCase().replace(' ', '-'),
                }),
            });
        }
        Utils.showToast(`权限模式已切换为 ${modes[idx]}`);
    },
};
