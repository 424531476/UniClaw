/* permission.js — 权限弹窗组件 */

const Permission = {
    currentRequest: null,
    _countdownTimer: null,
    _countdownSeconds: 300,

    init() {
        WS.on('permission_request', msg => this._onRequest(msg));
        WS.on('session_attention', msg => { if (msg.session_id !== SessionPanel.activeSessionId) Utils.showToast(msg.message || '需要权限确认'); });
        document.getElementById('perm-allow').onclick = () => this._respond(true);
        document.getElementById('perm-deny').onclick = () => this._respond(false);
        document.getElementById('status-permission').onclick = e => { e.stopPropagation(); this.showModeMenu(); };
    },

    _onRequest(msg) {
        if (!msg || msg.session_id !== SessionPanel.activeSessionId) return;
        this.currentRequest = msg;
        document.getElementById('perm-tool').textContent = msg.tool_name || '';
        document.getElementById('perm-args').textContent = JSON.stringify(msg.args || {}, null, 2);
        const expl = document.getElementById('perm-explanation');
        if (msg.explanation) { expl.style.display = 'block'; document.getElementById('perm-explanation-text').textContent = msg.explanation; }
        else expl.style.display = 'none';
        document.getElementById('perm-reason').value = '';
        document.getElementById('perm-always').checked = false;
        document.getElementById('permission-modal').classList.remove('hidden');
        this._startCountdown(msg.created_at, msg.timeout);
    },

    closeIfSessionMismatch(targetSid) {
        if (this.currentRequest && this.currentRequest.session_id !== targetSid) {
            this._stopCountdown();
            document.getElementById('permission-modal').classList.add('hidden');
            this.currentRequest = null;
        }
    },

    _respond(approved) {
        if (!this.currentRequest) return;
        this._stopCountdown();
        WS.send({
            type: 'permission_response',
            session_id: this.currentRequest.session_id,
            id: this.currentRequest.id,
            approved,
            reason: approved ? '' : document.getElementById('perm-reason').value,
            always: document.getElementById('perm-always').checked && approved,
        });
        document.getElementById('permission-modal').classList.add('hidden');
        this.currentRequest = null;
    },

    _startCountdown(createdAt, timeout) {
        this._stopCountdown();
        const T = timeout || 300;
        if (createdAt) { const elapsed = Math.floor(Date.now() / 1000) - createdAt; this._countdownSeconds = Math.max(0, T - elapsed); }
        else this._countdownSeconds = T;
        const el = document.getElementById('perm-countdown');
        if (!el) return;
        el.textContent = this._fmtTime(this._countdownSeconds);
        if (this._countdownSeconds <= 0) { this._respond(false); Utils.showToast('权限请求已超时自动拒绝'); return; }
        this._countdownTimer = setInterval(() => {
            this._countdownSeconds--;
            el.textContent = this._fmtTime(this._countdownSeconds);
            if (this._countdownSeconds <= 30) el.classList.add('urgent');
            if (this._countdownSeconds <= 0) { this._respond(false); Utils.showToast('权限请求已超时自动拒绝'); }
        }, 1000);
    },

    _stopCountdown() { if (this._countdownTimer) { clearInterval(this._countdownTimer); this._countdownTimer = null; } const el = document.getElementById('perm-countdown'); if (el) el.classList.remove('urgent'); },
    _fmtTime(s) { return `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, '0')}`; },

    _cycleMode() {
        const modes = ['auto', 'manual', 'accept-all', 'plan'];
        const el = document.getElementById('status-permission');
        const cur = el.className.match(/perm-mode (\w[\w-]*)/)?.[1] || 'auto';
        const idx = (modes.indexOf(cur) + 1) % modes.length;
        this._setMode(idx);
    },

    showModeMenu() {
        this._hideModeMenu();
        const modes = ['auto', 'manual', 'accept-all', 'plan'];
        const labels = ['Auto', 'Manual', 'Accept All', 'Plan'];
        const el = document.getElementById('status-permission');
        const cur = el.className.match(/perm-mode (\w[\w-]*)/)?.[1] || 'auto';
        const menu = document.createElement('div');
        menu.id = 'perm-mode-menu';
        menu.className = 'context-menu';
        const rect = el.getBoundingClientRect();
        menu.style.cssText = `position:fixed;bottom:${window.innerHeight - rect.top + 4}px;left:${rect.left}px;z-index:1000`;
        modes.forEach((mode, idx) => {
            const item = document.createElement('div');
            item.className = 'context-menu-item' + (cur === mode ? ' active' : '');
            item.textContent = labels[idx];
            item.onclick = () => { this._setMode(idx); this._hideModeMenu(); };
            menu.appendChild(item);
        });
        document.body.appendChild(menu);
        setTimeout(() => document.addEventListener('click', this._hideModeMenu, { once: true }), 0);
    },

    _hideModeMenu() { const m = document.getElementById('perm-mode-menu'); if (m) m.remove(); },

    _setMode(idx) {
        const modes = ['auto', 'manual', 'accept-all', 'plan'];
        const labels = ['Auto', 'Manual', 'Accept All', 'Plan'];
        const el = document.getElementById('status-permission');
        el.textContent = labels[idx];
        el.className = `perm-mode ${modes[idx]}`;
        const sid = SessionPanel.activeSessionId;
        if (sid) fetch('/api/config', { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ session_id: sid, permission_mode: modes[idx] }) });
        Utils.showToast(`权限模式: ${labels[idx]}`);
    },
};
