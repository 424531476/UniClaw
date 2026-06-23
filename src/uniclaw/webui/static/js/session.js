/* session.js — 左侧会话面板 */

const SessionPanel = {
    projects: {},       // root_dir → { sessions: [...], expanded: bool }
    activeSessionId: null,
    activeProjectDir: null,

    runningSessions: new Set(), // 正在运行的会话 ID
    attentionSessions: new Set(), // 有待处理请求的会话 ID
    _contextTimer: null,        // 上下文刷新定时器

    /** 初始化 */
    init() {
        this._bindEvents();
        this._loadProjects().catch(e => console.error('[SessionPanel] 初始化失败:', e));
        // 监听 status 事件
        WS.on('status', (msg) => this._onStatus(msg));
        // 监听会话注意力事件(权限/输入请求)
        WS.on('session_attention', (msg) => {
            if (msg.session_id) {
                this.attentionSessions.add(msg.session_id);
                this._render();
            }
        });
        WS.on('session_attention_clear', (msg) => {
            if (msg.session_id) {
                this.attentionSessions.delete(msg.session_id);
                this._render();
            }
        });
        // 监听后端会话删除事件(通过 /resume del 或 AI 工具删除)
        WS.on('session_deleted', (msg) => this._onSessionDeleted(msg));
        // 监听后端会话切换事件(通过 /resume fork)
        WS.on('session_switched', (msg) => this._onSessionSwitched(msg));
    },

    /** 绑定事件 */
    _bindEvents() {
        document.getElementById('new-project-btn').onclick = () => this._showNewProjectDialog();
        document.getElementById('search-input').oninput = Utils.debounce((e) => this._onSearch(e.target.value), 300);
    },

    /** 处理后端会话删除事件 */
    _onSessionDeleted(msg) {
        const sessionId = msg.session_id;
        if (!sessionId) return;
        console.log('[SessionPanel] 会话已删除:', sessionId);
        // 如果删除的是当前活跃会话,进入新建会话状态
        if (this.activeSessionId === sessionId) {
            const rootDir = msg.root_dir ?? this.activeProjectDir;
            if (rootDir) {
                this.createSession(rootDir);
            } else {
                // 无项目模式:清空聊天区,等待用户选择项目
                this.activeSessionId = null;
                Chat.clear();
                Chat._appendSystemMessage('请选择项目或发送消息开始对话');
                this._render();
            }
        }
        // 刷新会话列表
        this._refreshSessions();
    },

    /** 处理后端会话切换事件(fork 后) */
    _onSessionSwitched(msg) {
        const newSessionId = msg.session_id;
        if (!newSessionId) return;
        console.log('[SessionPanel] 会话已切换:', newSessionId);
        // 切换到新会话(使用当前项目目录)
        this.selectSession(newSessionId, this.activeProjectDir);
        // 刷新会话列表(新会话可能出现)
        this._refreshSessions();
    },

    /** 处理 status 事件 */
    _onStatus(msg) {
        const sid = msg.session_id;
        if (!sid) return;
        if (msg.status === 'running') {
            this.runningSessions.add(sid);
        } else {
            this.runningSessions.delete(sid);
            // 任务完成后刷新上下文使用情况
            if (this.activeSessionId === sid) {
                this._fetchContextUsage(sid);
            }
        }
        // 更新会话项的运行指示器
        const el = document.querySelector(`.session-item[data-sid="${sid}"]`);
        if (el) {
            let indicator = el.querySelector('.running-indicator');
            if (msg.status === 'running') {
                if (!indicator) {
                    indicator = document.createElement('span');
                    indicator.className = 'running-indicator';
                    indicator.textContent = '●';
                    el.appendChild(indicator);
                }
            } else {
                if (indicator) indicator.remove();
            }
        }
    },

    /** 加载项目列表 */
    async _loadProjects() {
        try {
            // 从 localStorage 恢复项目
            const saved = localStorage.getItem('uniclaw_projects');
            if (saved) {
                const dirs = JSON.parse(saved);
                dirs.forEach(dir => {
                    if (!this.projects[dir]) {
                        this.projects[dir] = { sessions: [], expanded: true };
                    }
                });
            }
            // 从后端加载会话并分组
            await this._refreshSessions();
        } catch (e) {
            console.error('加载项目失败:', e);
            Utils.showError('加载项目列表失败');
        }
    },

    /** 刷新会话列表 */
    async _refreshSessions() {
        try {
            const resp = await fetch('/api/sessions');
            if (!resp.ok) {
                console.error('[SessionPanel] 获取会话列表失败:', resp.status);
                Utils.showError('获取会话列表失败');
                return;
            }
            const sessions = await resp.json();
            // 按 root_dir 分组
            const grouped = {};
            sessions.forEach(s => {
                const dir = s.root_dir || '';
                if (!dir) return;
                if (!grouped[dir]) grouped[dir] = [];
                grouped[dir].push(s);
            });
            // 更新 projects(只保留有会话的项目,除非是 localStorage 中手动添加的)
            const saved = localStorage.getItem('uniclaw_projects');
            const savedDirs = saved ? JSON.parse(saved) : [];
            // 清理没有会话且不在 localStorage 中的项目
            Object.keys(this.projects).forEach(dir => {
                if (!grouped[dir] && !savedDirs.includes(dir)) {
                    delete this.projects[dir];
                }
            });
            // 更新有会话的项目
            Object.keys(grouped).forEach(dir => {
                if (!this.projects[dir]) {
                    this.projects[dir] = { sessions: [], expanded: true };
                }
                // 按时间排序(新的在上)
                this.projects[dir].sessions = grouped[dir].sort((a, b) => {
                    const ta = a.end_time || a.start_time || '';
                    const tb = b.end_time || b.start_time || '';
                    return tb.localeCompare(ta);
                });
            });
            // 合并 localStorage 中的项目(可能还没有会话)
            savedDirs.forEach(dir => {
                if (!this.projects[dir]) {
                    this.projects[dir] = { sessions: [], expanded: true };
                }
            });
            // 项目按最后会话时间排序
            this._render();
        } catch (e) {
            console.error('刷新会话失败:', e);
        }
    },

    /** 渲染会话树 */
    _render() {
        const tree = document.getElementById('session-tree');
        // 按最后活跃时间排序项目
        const sortedProjects = Object.entries(this.projects).sort(([, a], [, b]) => {
            const ta = a.sessions.length > 0 ? (a.sessions[0].end_time || a.sessions[0].start_time || '') : '';
            const tb = b.sessions.length > 0 ? (b.sessions[0].end_time || b.sessions[0].start_time || '') : '';
            return tb.localeCompare(ta);
        });

        let html = '';
        sortedProjects.forEach(([rootDir, proj]) => {
            const shortName = rootDir.split(/[/\\]/).pop() || rootDir;
            const isExpanded = proj.expanded;
            const isRunning = proj.sessions.some(s => this.runningSessions.has(s.session_id));
            html += `<div class="project-node" data-dir="${Utils.escapeHtml(rootDir)}">`;
            html += `<div class="project-header" onclick="SessionPanel.toggleProject('${this._esc(rootDir)}')" ondragover="SessionPanel._onDragOver(event)" ondrop="SessionPanel._onDrop(event, '${this._esc(rootDir)}')">`;
            html += `<span class="arrow ${isExpanded ? 'expanded' : ''}">▶</span>`;
            html += `<span>📁 ${Utils.escapeHtml(shortName)}</span>`;
            html += `<span class="session-meta">${proj.sessions.length}</span>`;
            if (isRunning) html += '<span class="running-indicator" style="margin-left:4px">●</span>';
            html += `<span class="new-session-icon" onclick="event.stopPropagation(); SessionPanel.createSession('${this._esc(rootDir)}')" title="新建会话">+</span>`;
            html += `</div>`;
            if (isExpanded) {
                proj.sessions.forEach(s => {
                    const isActive = s.session_id === this.activeSessionId;
                    const isRunning = this.runningSessions.has(s.session_id);
                    const isAttention = this.attentionSessions.has(s.session_id);
                    const title = s.title || s.session_id;
                    const time = Utils.formatTime(s.end_time || s.start_time);
                    const msgCount = s.message_count || 0;
                    const cls = [isActive ? 'active' : '', isAttention ? 'attention' : ''].filter(Boolean).join(' ');
                    html += `<div class="session-item ${cls}" data-sid="${s.session_id}" draggable="true" ondragstart="SessionPanel._onDragStart(event, '${s.session_id}')" onclick="SessionPanel.selectSession('${s.session_id}', '${this._esc(rootDir)}')">`;
                    html += `<div class="session-title">${Utils.escapeHtml(title)}</div>`;
                    html += `<div class="session-meta">${time}  ${msgCount}条</div>`;
                    if (isRunning) html += '<span class="running-indicator">●</span>';
                    if (isAttention) html += '<span class="attention-badge" title="有待处理请求">🔴</span>';
                    html += `<span class="session-menu" onclick="event.stopPropagation(); SessionPanel.showMenu('${s.session_id}', '${this._esc(rootDir)}')">⋮</span>`;
                    html += `</div>`;
                });
            }
            html += `</div>`;
        });
        tree.innerHTML = html;
    },

    /** 拖拽开始 */
    _onDragStart(event, sessionId) {
        event.dataTransfer.setData('text/plain', sessionId);
        event.dataTransfer.effectAllowed = 'move';
    },

    /** 拖拽经过项目头 */
    _onDragOver(event) {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
        event.currentTarget.classList.add('drag-over');
    },

    /** 放下到项目 */
    async _onDrop(event, targetRootDir) {
        event.preventDefault();
        event.currentTarget.classList.remove('drag-over');
        const sessionId = event.dataTransfer.getData('text/plain');
        if (!sessionId) return;
        try {
            const resp = await fetch(`/api/sessions/${sessionId}/move`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ root_dir: targetRootDir }),
            });
            if (resp.ok) {
                Utils.showToast('会话已移动');
                this._refreshSessions();
            }
        } catch (e) {
            Utils.showToast('移动失败');
        }
    },

    /** 切换项目展开/折叠 */
    toggleProject(dir) {
        if (this.projects[dir]) {
            this.projects[dir].expanded = !this.projects[dir].expanded;
            this._render();
        }
    },

    /** 选择会话 */
    async selectSession(sessionId, rootDir) {
        this.activeSessionId = sessionId;
        this.activeProjectDir = rootDir;
        // 通知后端当前活跃会话(后端会重发待处理请求,并在请求解决后发 session_attention_clear)
        WS.send({ type: 'set_active', session_id: sessionId });
        // 更新状态栏
        this._updateStatusBar(rootDir, sessionId);
        // 加载历史消息
        try {
            await Chat.loadHistory(sessionId);
        } catch (e) {
            console.error('[SessionPanel] 加载历史失败:', e);
        }
        this._render();
    },

    /** 创建新会话(仅前端状态,不发送消息给后端) */
    createSession(rootDir) {
        // 只设置当前项目目录,清空会话 ID
        this.activeSessionId = null;
        this.activeProjectDir = rootDir;
        // 更新状态栏
        this._updateStatusBar(rootDir, null, true);
        // 清空聊天区
        Chat.clear();
        Chat._appendSystemMessage('新会话,发送消息开始对话');
        // 取消所有会话的选中状态
        this._render();
    },

    /** 更新状态栏 */
    _updateStatusBar(rootDir, sessionId, skipSessionFetch = false) {
        const shortDir = rootDir ? (rootDir.split(/[/\\]/).pop() || rootDir) : '-';
        const projectEl = document.getElementById('status-project');
        projectEl.textContent = shortDir;
        projectEl.title = rootDir || '';
        projectEl.onclick = () => {
            if (rootDir) {
                navigator.clipboard.writeText(rootDir).then(() => {
                    Utils.showToast('已复制项目路径');
                });
            }
        };
        // 会话名
        document.getElementById('status-session').textContent = sessionId || '新会话';
        // 无会话时跳过 API 请求
        if (!sessionId || skipSessionFetch) {
            document.getElementById('status-model').textContent = '-';
            document.getElementById('status-permission').textContent = '-';
            this._clearContextTimer();
            this._updateContextDisplay(null);
            return;
        }
        // 获取会话详情
        fetch(`/api/sessions/${sessionId}`)
            .then(r => {
                if (!r.ok) return null;
                return r.json();
            })
            .then(data => {
                if (data) {
                    document.getElementById('status-session').textContent = data.title || sessionId;
                }
            })
            .catch(() => {});
        // 配置信息异步获取
        fetch(`/api/config?session_id=${sessionId}`)
            .then(r => r.json())
            .then(data => {
                if (data.model_name) {
                    document.getElementById('status-model').textContent = data.model_name;
                }
                if (data.permission_mode) {
                    const modeMap = {
                        'auto': '🔒 Auto',
                        'manual': '🔐 Manual',
                        'accept_all': '✅ Accept All',
                        'plan': '📋 Plan',
                    };
                    const display = modeMap[data.permission_mode] || `🔒 ${data.permission_mode}`;
                    document.getElementById('status-permission').textContent = display;
                }
            })
            .catch(() => {});
        // 获取上下文使用情况
        this._fetchContextUsage(sessionId);
        this._startContextTimer(sessionId);
    },

    /** 获取上下文使用情况 */
    _fetchContextUsage(sessionId) {
        if (!sessionId) return;
        fetch(`/api/context?session_id=${sessionId}`)
            .then(r => {
                if (!r.ok) return null;
                return r.json();
            })
            .then(data => {
                if (data) {
                    this._updateContextDisplay(data);
                }
            })
            .catch(() => {});
    },

    /** 更新上下文显示 */
    _updateContextDisplay(data) {
        const pctEl = document.getElementById('context-pct');
        const barFillEl = document.getElementById('context-bar-fill');
        if (!pctEl || !barFillEl) return;

        if (!data || data.percentage === undefined) {
            pctEl.textContent = '-';
            barFillEl.style.width = '0%';
            barFillEl.className = 'context-bar-fill';
            return;
        }

        const pct = data.percentage;
        pctEl.textContent = `${pct}%`;
        pctEl.title = `上下文: ${data.used_tokens}/${data.limit} tokens`;
        barFillEl.style.width = `${Math.min(100, pct)}%`;

        // 根据百分比设置颜色
        barFillEl.className = 'context-bar-fill';
        if (pct >= 85) {
            barFillEl.classList.add('danger');
        } else if (pct >= 70) {
            barFillEl.classList.add('warning');
        }
    },

    /** 启动上下文刷新定时器 */
    _startContextTimer(sessionId) {
        this._clearContextTimer();
        // 每 30 秒刷新一次上下文使用情况
        this._contextTimer = setInterval(() => {
            if (this.activeSessionId === sessionId) {
                this._fetchContextUsage(sessionId);
            }
        }, 30000);
    },

    /** 清除上下文刷新定时器 */
    _clearContextTimer() {
        if (this._contextTimer) {
            clearInterval(this._contextTimer);
            this._contextTimer = null;
        }
    },

    /** 显示会话菜单 */
    showMenu(sessionId, rootDir) {
        // 移除已有菜单
        this._hideMenu();
        const el = document.querySelector(`.session-item[data-sid="${sessionId}"] .session-menu`);
        if (!el) return;

        const menu = document.createElement('div');
        menu.className = 'context-menu';
        menu.id = 'session-context-menu';
        menu.innerHTML = `
            <div class="context-menu-item" onclick="SessionPanel._renameSession('${sessionId}')">✏️ 重命名</div>
            <div class="context-menu-item context-menu-danger" onclick="SessionPanel._deleteSession('${sessionId}')">🗑️ 删除</div>
        `;
        document.body.appendChild(menu);

        // 定位到按钮旁边
        const rect = el.getBoundingClientRect();
        menu.style.top = rect.bottom + 4 + 'px';
        menu.style.left = rect.left + 'px';

        // 点击外部关闭
        setTimeout(() => {
            document.addEventListener('click', this._hideMenu, { once: true });
        }, 0);
    },

    /** 隐藏菜单 */
    _hideMenu() {
        const menu = document.getElementById('session-context-menu');
        if (menu) menu.remove();
    },

    /** 重命名会话 */
    _renameSession(sessionId) {
        this._hideMenu();
        this._showModal('重命名会话', `
            <label style="font-size:13px;color:var(--text-secondary)">新标题:</label>
            <div style="display:flex;gap:8px;margin-top:4px">
                <input type="text" id="rename-input" style="flex:1;padding:6px 8px;background:var(--bg-primary);border:1px solid var(--border);border-radius:4px;color:var(--text-primary);font-size:13px" />
                <button class="btn-secondary" id="ai-generate-btn" style="white-space:nowrap;font-size:12px;padding:6px 12px">🤖 AI生成</button>
            </div>
        `, () => {
            const title = document.getElementById('rename-input').value.trim();
            if (title) {
                fetch(`/api/sessions/${sessionId}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title }),
                }).then(() => this._refreshSessions());
            }
        });
        // 绑定 AI 生成按钮事件
        document.getElementById('ai-generate-btn').onclick = () => this._generateTitleInDialog(sessionId);
        setTimeout(() => document.getElementById('rename-input')?.focus(), 0);
    },

    /** 在对话框中 AI 生成标题 */
    async _generateTitleInDialog(sessionId) {
        const btn = document.getElementById('ai-generate-btn');
        const input = document.getElementById('rename-input');
        if (!btn || !input) return;

        btn.disabled = true;
        btn.textContent = '生成中...';
        try {
            const resp = await fetch(`/api/sessions/${sessionId}/title/generate`, { method: 'POST' });
            const data = await resp.json();
            if (data.title) {
                input.value = data.title;
                input.focus();
            } else {
                Utils.showToast('生成标题失败');
            }
        } catch (e) {
            Utils.showToast('生成标题失败');
        } finally {
            btn.disabled = false;
            btn.textContent = '🤖 AI生成';
        }
    },

    /** 删除会话 */
    async _deleteSession(sessionId) {
        this._hideMenu();
        const confirmed = await Utils.confirm('确定删除此会话？此操作不可撤销。');
        if (!confirmed) return;

        try {
            const resp = await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
            if (!resp.ok) {
                throw new Error('删除失败');
            }
            if (this.activeSessionId === sessionId) {
                this.activeSessionId = null;
                Chat.clear();
            }
            Utils.showToast('会话已删除');
            await this._refreshSessions();
        } catch (e) {
            console.error('删除会话失败:', e);
            Utils.showError('删除会话失败');
        }
    },

    /** 通用模态弹窗 */
    _showModal(title, bodyHtml, onConfirm) {
        // 移除已有弹窗
        const existing = document.getElementById('session-modal');
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.id = 'session-modal';
        modal.className = 'modal';
        modal.style.display = 'flex';
        modal.innerHTML = `
            <div class="modal-content" style="max-width:360px">
                <h3>${Utils.escapeHtml(title)}</h3>
                <div class="modal-body">${bodyHtml}</div>
                <div class="modal-actions">
                    <button class="btn-secondary" id="session-modal-cancel">取消</button>
                    <button class="btn-primary" id="session-modal-confirm">确认</button>
                </div>
            </div>`;
        document.body.appendChild(modal);

        document.getElementById('session-modal-cancel').onclick = () => modal.remove();
        document.getElementById('session-modal-confirm').onclick = () => { modal.remove(); onConfirm(); };
        modal.onclick = (e) => { if (e.target === modal) modal.remove(); };
    },

    /** 搜索 */
    async _onSearch(keyword) {
        if (!keyword.trim()) {
            this._render();
            return;
        }
        try {
            const resp = await fetch(`/api/sessions/search?keyword=${encodeURIComponent(keyword)}`);
            const results = await resp.json();
            // 临时显示搜索结果
            const tree = document.getElementById('session-tree');
            let html = '<div style="padding:8px;font-size:13px;color:var(--text-secondary)">搜索结果:</div>';
            results.forEach(s => {
                const time = Utils.formatTime(s.end_time || s.start_time);
                const msgCount = s.message_count || 0;
                html += `<div class="session-item" data-sid="${s.session_id}" onclick="SessionPanel.selectSession('${s.session_id}', '${this._esc(s.root_dir || '')}')">`;
                html += `<div class="session-title">${Utils.escapeHtml(s.title || s.session_id)}</div>`;
                html += `<div class="session-meta">${time}  ${msgCount}条</div>`;
                html += `</div>`;
            });
            tree.innerHTML = html;
        } catch (e) {
            console.error('搜索失败:', e);
        }
    },

    /** 新建项目对话框 */
    _showNewProjectDialog() {
        const modal = document.getElementById('new-project-modal');
        modal.style.display = 'flex';
        document.getElementById('project-path').value = '';
        document.getElementById('dir-list').innerHTML = '';

        document.getElementById('browse-btn').onclick = () => this._browseDir('');
        document.getElementById('project-confirm').onclick = () => {
            const path = document.getElementById('project-path').value.trim();
            if (path) {
                this.projects[path] = { sessions: [], expanded: true };
                this._saveProjects();
                this._render();
                modal.style.display = 'none';
            }
        };
        document.getElementById('project-cancel').onclick = () => {
            modal.style.display = 'none';
        };
    },

    /** 浏览目录 */
    async _browseDir(path) {
        try {
            const resp = await fetch(`/api/dirs?path=${encodeURIComponent(path)}`);
            const dirs = await resp.json();
            document.getElementById('project-path').value = path;
            const list = document.getElementById('dir-list');
            list.innerHTML = dirs.filter(d => d.is_dir).map(d =>
                `<div class="dir-list-item" onclick="SessionPanel._browseDir('${this._esc(d.path)}')">📁 ${Utils.escapeHtml(d.name)}</div>`
            ).join('');
        } catch (e) {
            console.error('浏览目录失败:', e);
        }
    },

    /** 保存项目到 localStorage */
    _saveProjects() {
        localStorage.setItem('uniclaw_projects', JSON.stringify(Object.keys(this.projects)));
    },

    /** 转义字符串用于 onclick */
    _esc(str) {
        return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
    },

    /** 添加闪烁提醒 */
    addAttention(sessionId) {
        const el = document.querySelector(`.session-item[data-sid="${sessionId}"]`);
        if (el) el.classList.add('attention');
    },

    /** 移除闪烁提醒 */
    removeAttention(sessionId) {
        const el = document.querySelector(`.session-item[data-sid="${sessionId}"]`);
        if (el) el.classList.remove('attention');
    },
};
