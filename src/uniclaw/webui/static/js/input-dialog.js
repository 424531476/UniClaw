/* input-dialog.js — 通用输入弹窗组件 */

const InputDialog = {
    currentRequest: null,
    _countdownTimer: null,
    _countdownSeconds: 300,

    init() {
        WS.on('input_request', msg => this._onRequest(msg));
        document.getElementById('input-dialog-confirm').onclick = () => this._respond();
        document.getElementById('input-dialog-text').addEventListener('keydown', e => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this._respond(); }
        });
    },

    _onRequest(msg) {
        if (!msg || msg.session_id !== SessionPanel.activeSessionId) return;
        this.currentRequest = msg;
        document.getElementById('input-dialog-title').textContent = msg.title || '输入';
        document.getElementById('input-dialog-prompt').textContent = msg.prompt || '';
        const input = document.getElementById('input-dialog-text');
        input.value = '';
        document.getElementById('input-dialog-modal').classList.remove('hidden');
        setTimeout(() => input.focus(), 0);
        this._startCountdown(msg.created_at, msg.timeout);
    },

    closeIfSessionMismatch(targetSid) {
        if (this.currentRequest && this.currentRequest.session_id !== targetSid) {
            this._stopCountdown();
            document.getElementById('input-dialog-modal').classList.add('hidden');
            this.currentRequest = null;
        }
    },

    _respond(value) {
        if (!this.currentRequest) return;
        this._stopCountdown();
        if (value === undefined) value = document.getElementById('input-dialog-text').value;
        WS.send({ type: 'input_response', session_id: this.currentRequest.session_id, id: this.currentRequest.id, value });
        document.getElementById('input-dialog-modal').classList.add('hidden');
        this.currentRequest = null;
    },

    _startCountdown(createdAt, timeout) {
        this._stopCountdown();
        const T = timeout || 300;
        if (createdAt) { const elapsed = Math.floor(Date.now() / 1000) - createdAt; this._countdownSeconds = Math.max(0, T - elapsed); }
        else this._countdownSeconds = T;
        const el = document.getElementById('input-countdown');
        if (!el) return;
        el.textContent = this._fmtTime(this._countdownSeconds);
        if (this._countdownSeconds <= 0) { this._respond(''); Utils.showToast('输入请求已超时'); return; }
        this._countdownTimer = setInterval(() => {
            this._countdownSeconds--;
            el.textContent = this._fmtTime(this._countdownSeconds);
            if (this._countdownSeconds <= 0) { this._respond(''); Utils.showToast('输入请求已超时'); }
        }, 1000);
    },

    _stopCountdown() { if (this._countdownTimer) { clearInterval(this._countdownTimer); this._countdownTimer = null; } },
    _fmtTime(s) { return `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, '0')}`; },
};
