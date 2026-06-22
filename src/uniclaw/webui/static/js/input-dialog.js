/* input-dialog.js — 通用输入弹窗组件 (用于 /model、/mcp add、AskUserQuestion 等) */

const InputDialog = {
    currentRequest: null,

    /** 初始化 */
    init() {
        WS.on('input_request', (msg) => this._onRequest(msg));

        document.getElementById('input-dialog-confirm').onclick = () => this._respond();
        document.getElementById('input-dialog-cancel').onclick = () => this._respond('');
        document.getElementById('input-dialog-text').addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this._respond();
            }
            if (e.key === 'Escape') {
                this._respond('');
            }
        });
    },

    /** 收到输入请求 */
    _onRequest(msg) {
        this.currentRequest = msg;
        document.getElementById('input-dialog-title').textContent = msg.title || '输入';
        document.getElementById('input-dialog-prompt').textContent = msg.prompt || '';
        const input = document.getElementById('input-dialog-text');
        input.value = '';
        document.getElementById('input-dialog-modal').style.display = 'flex';
        setTimeout(() => input.focus(), 0);
    },

    /** 发送输入响应 */
    _respond(value) {
        if (!this.currentRequest) return;
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
};
