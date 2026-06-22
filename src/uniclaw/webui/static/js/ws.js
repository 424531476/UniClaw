/* ws.js — WebSocket 客户端管理 */

const WS = {
    socket: null,
    handlers: {},
    reconnectTimer: null,
    reconnectDelay: 1000,

    /** 连接 WebSocket */
    connect() {
        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${location.host}/ws`;
        this.socket = new WebSocket(url);

        this.socket.onopen = () => {
            console.log('[WS] 已连接');
            this.reconnectDelay = 1000;
            this._emit('connected');
        };

        this.socket.onmessage = (e) => {
            try {
                const msg = JSON.parse(e.data);
                this._emit(msg.event, msg);
            } catch (err) {
                console.error('[WS] 解析消息失败:', err);
            }
        };

        this.socket.onclose = () => {
            console.log('[WS] 连接断开');
            this._emit('disconnected');
            this._scheduleReconnect();
        };

        this.socket.onerror = (e) => {
            console.error('[WS] 错误:', e);
        };
    },

    /** 发送消息 */
    send(msg) {
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify(msg));
        } else {
            console.warn('[WS] 未连接,无法发送消息');
        }
    },

    /** 注册事件处理器 */
    on(event, handler) {
        if (!this.handlers[event]) this.handlers[event] = [];
        this.handlers[event].push(handler);
    },

    /** 移除事件处理器 */
    off(event, handler) {
        if (!this.handlers[event]) return;
        this.handlers[event] = this.handlers[event].filter(h => h !== handler);
    },

    /** 触发事件 */
    _emit(event, data) {
        const handlers = this.handlers[event] || [];
        handlers.forEach(h => {
            try { h(data); } catch (e) { console.error(`[WS] 处理器错误 (${event}):`, e); }
        });
    },

    /** 自动重连 */
    _scheduleReconnect() {
        if (this.reconnectTimer) return;
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            console.log('[WS] 尝试重连...');
            this.connect();
        }, this.reconnectDelay);
        this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
    },
};
