/* app.js — 应用主入口 */

const App = {
    /** 初始化应用 */
    init() {
        // 初始化各组件
        WS.connect();
        Chat.init();
        Input.init();
        SessionPanel.init();
        Permission.init();
        InputDialog.init();
        Sidebar.init();

        // 绑定全局事件
        this._bindGlobalEvents();
        this._bindDragHandles();
        this._bindPanelToggles();
        this._restorePanelState();

        // 隐藏加载遮罩
        Utils.hideLoading();

        // 隐藏快捷键提示(5秒后)
        setTimeout(() => {
            Utils.hideShortcutHint();
        }, 5000);

        console.log('[App] UniClaw WebUI 已初始化');
    },

    /** 绑定全局事件 */
    _bindGlobalEvents() {
        // 快捷键
        document.addEventListener('keydown', (e) => {
            // Shift+Tab: 切换权限模式
            if (e.shiftKey && e.key === 'Tab') {
                e.preventDefault();
                Permission._cycleMode();
            }
            // F3: 切换左侧面板
            if (e.key === 'F3') {
                e.preventDefault();
                this._toggleLeftPanel();
            }
            // Escape: 关闭弹窗 / 取消 agent
            if (e.key === 'Escape') {
                const modals = document.querySelectorAll('.modal');
                const hasOpenModal = Array.from(modals).some(m => m.style.display !== 'none');
                if (hasOpenModal) {
                    modals.forEach(m => m.style.display = 'none');
                } else {
                    // 取消当前 agent 执行
                    const sessionId = SessionPanel.activeSessionId;
                    if (sessionId) {
                        WS.send({ type: 'cancel', session_id: sessionId });
                        Utils.showToast('已发送取消请求');
                    }
                }
                Input._hideCompletion();
            }
        });

        // WebSocket 连接状态
        WS.on('connected', () => {
            document.getElementById('status-model').textContent = '已连接';
        });
        WS.on('disconnected', () => {
            document.getElementById('status-model').textContent = '未连接';
            Utils.showError('WebSocket 连接断开,正在重连...');
        });
    },

    /** 绑定拖拽条 */
    _bindDragHandles() {
        this._makeDraggable('left-drag', 'left-panel', 'left');
        this._makeDraggable('right-drag', 'right-panel', 'right');
    },

    /** 使面板可拖拽 */
    _makeDraggable(handleId, panelId, side) {
        const handle = document.getElementById(handleId);
        const panel = document.getElementById(panelId);
        if (!handle || !panel) return;

        let startX, startWidth;

        handle.addEventListener('mousedown', (e) => {
            startX = e.clientX;
            startWidth = panel.offsetWidth;
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
        });

        function onMouseMove(e) {
            const dx = e.clientX - startX;
            let newWidth;
            if (side === 'left') {
                newWidth = startWidth + dx;
            } else {
                newWidth = startWidth - dx;
            }
            const min = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--panel-min')) || 200;
            const max = side === 'left' ? 500 : 600;
            newWidth = Math.max(min, Math.min(max, newWidth));
            panel.style.width = newWidth + 'px';
        }

        function onMouseUp() {
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            // 保存面板宽度
            localStorage.setItem(`panel_width_${side}`, panel.style.width);
        }
    },

    /** 绑定面板切换按钮 */
    _bindPanelToggles() {
        document.getElementById('toggle-left').onclick = () => this._toggleLeftPanel();
        document.getElementById('toggle-right').onclick = () => this._toggleRightPanel();
        document.getElementById('toggle-usage').onclick = () => this._toggleUsage();
        // 折叠状态点击面板也可展开
        document.getElementById('left-panel').addEventListener('click', (e) => {
            if (e.currentTarget.classList.contains('collapsed')) {
                this._toggleLeftPanel();
            }
        });
        document.getElementById('right-panel').addEventListener('click', (e) => {
            if (e.currentTarget.classList.contains('collapsed')) {
                this._toggleRightPanel();
            }
        });
    },

    /** 切换左侧面板 */
    _toggleLeftPanel() {
        const panel = document.getElementById('left-panel');
        const drag = document.getElementById('left-drag');
        panel.classList.toggle('collapsed');
        drag.style.display = panel.classList.contains('collapsed') ? 'none' : '';
        localStorage.setItem('left_collapsed', panel.classList.contains('collapsed'));
    },

    /** 切换右侧面板 */
    _toggleRightPanel() {
        const panel = document.getElementById('right-panel');
        const drag = document.getElementById('right-drag');
        panel.classList.toggle('collapsed');
        drag.style.display = panel.classList.contains('collapsed') ? 'none' : '';
        if (!panel.classList.contains('collapsed')) {
            Sidebar.switchTab(Sidebar.currentTab);
        }
        localStorage.setItem('right_collapsed', panel.classList.contains('collapsed'));
    },

    /** 切换消息 Token 用量显示 */
    _toggleUsage() {
        const btn = document.getElementById('toggle-usage');
        const chat = document.getElementById('chat-messages');
        if (!btn || !chat) return;
        const show = chat.classList.toggle('show-usage');
        btn.classList.toggle('active', show);
        localStorage.setItem('show_usage', show ? '1' : '0');
    },

    /** 恢复面板状态 */
    _restorePanelState() {
        // 左侧面板宽度
        const leftWidth = localStorage.getItem('panel_width_left');
        if (leftWidth) {
            document.getElementById('left-panel').style.width = leftWidth;
        }
        // 右侧面板宽度
        const rightWidth = localStorage.getItem('panel_width_right');
        if (rightWidth) {
            document.getElementById('right-panel').style.width = rightWidth;
        }
        // 折叠状态
        if (localStorage.getItem('left_collapsed') === 'true') {
            document.getElementById('left-panel').classList.add('collapsed');
            document.getElementById('left-drag').style.display = 'none';
        }
        if (localStorage.getItem('right_collapsed') === 'true' || localStorage.getItem('right_hidden') === 'true') {
            document.getElementById('right-panel').classList.add('collapsed');
            document.getElementById('right-drag').style.display = 'none';
        }
        // Usage 显示状态
        if (localStorage.getItem('show_usage') === '1') {
            document.getElementById('chat-messages').classList.add('show-usage');
            document.getElementById('toggle-usage').classList.add('active');
        }
    },
};

// 启动应用
document.addEventListener('DOMContentLoaded', () => App.init());
