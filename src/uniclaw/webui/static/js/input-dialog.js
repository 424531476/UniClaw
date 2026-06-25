/* input-dialog.js — 通用输入弹窗组件 (用于 /model、/mcp add、AskUserQuestion 等) */

const InputDialog = {
    currentRequest: null,
    _countdownTimer: null,
    _countdownSeconds: 300,

    /** 初始化 */
    init() {
        WS.on('input_request', (msg) => this._onRequest(msg));

        document.getElementById('input-dialog-confirm').onclick = () => this._respond();
        document.getElementById('input-dialog-text').addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this._respond();
            }
        });
    },

    /** 收到输入请求 */
    _onRequest(msg) {
        // 非当前会话的请求不弹窗(左侧面板红点已通过 session_attention 提示)
        if (!msg || msg.session_id !== SessionPanel.activeSessionId) return;
        this.currentRequest = msg;
        document.getElementById('input-dialog-title').textContent = msg.title || '输入';
        document.getElementById('input-dialog-prompt').textContent = msg.prompt || '';
        const input = document.getElementById('input-dialog-text');
        input.value = '';
        document.getElementById('input-dialog-modal').style.display = 'flex';
        setTimeout(() => input.focus(), 0);
        // 根据后端 created_at 校准倒计时
        this._startCountdown(msg.created_at, msg.timeout);
    },

    /** 关闭不属于目标会话的弹窗(会话切换时调用) */
    closeIfSessionMismatch(targetSessionId) {
        if (this.currentRequest && this.currentRequest.session_id !== targetSessionId) {
            this._stopCountdown();
            document.getElementById('input-dialog-modal').style.display = 'none';
            this.currentRequest = null;
        }
    },

    /** 发送输入响应 */
    _respond(value) {
        if (!this.currentRequest) return;
        this._stopCountdown();
        if (value === undefined) {
            value = document.getElementById('input-dialog-text').value;
        }
        WS.send({
            type: 'input_response',
            session_id: this.currentRequest.session_id,
            id: this.currentRequest.id,
            value: value,
        });
        document.getElementById('input-dialog-modal').style.display = 'none';
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
        const el = document.getElementById('input-countdown');
        if (!el) return;
        el.textContent = this._formatTime(this._countdownSeconds);
        if (this._countdownSeconds <= 0) {
            this._respond('');
            Utils.showToast('输入请求已超时自动取消');
            return;
        }
        this._countdownTimer = setInterval(() => {
            this._countdownSeconds--;
            el.textContent = this._formatTime(this._countdownSeconds);
            if (this._countdownSeconds <= 0) {
                this._respond('');
                Utils.showToast('输入请求已超时自动取消');
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
};
