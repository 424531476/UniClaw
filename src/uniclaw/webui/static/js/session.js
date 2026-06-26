/* session.js — 左侧会话面板 */

const SessionPanel = {
    projects: {},
    activeSessionId: null,
    activeProjectDir: null,
    runningSessions: new Set(),
    attentionSessions: new Set(),
    _contextTimer: null,

    init() {
        this._bindEvents();
        this._loadProjects().catch(e => console.error('[SessionPanel] 初始化失败:', e));
        WS.on('status', msg => this._onStatus(msg));
        WS.on('session_attention', msg => {
            if (msg.session_id) { this.attentionSessions.add(msg.session_id); this._render(); }
        });
        WS.on('session_attention_clear', msg => {
            if (msg.session_id) { this.attentionSessions.delete(msg.session_id); this._render(); }
        });
        WS.on('session_deleted', msg => this._onSessionDeleted(msg));
        WS.on('session_switched', msg => this._onSessionSwitched(msg));
    },

    _bindEvents() {
        document.getElementById('new-project-btn').onclick = () => this._showNewProjectDialog();
        document.getElementById('search-input').oninput = Utils.debounce(e => this._onSearch(e.target.value), 300);
    },

    _onSessionDeleted(msg) {
        const sid = msg.session_id;
        if (!sid) return;
        if (this.activeSessionId === sid) {
            const rootDir = msg.root_dir ?? this.activeProjectDir;
            if (rootDir) this.createSession(rootDir);
            else { this.activeSessionId = null; Chat.clear(); Chat._appendSystemMessage('请选择项目或发送消息开始对话'); this._render(); }
        }
        this._refreshSessions();
    },

    _onSessionSwitched(msg) {
        if (!msg.session_id) return;
        this.selectSession(msg.session_id, this.activeProjectDir);
        this._refreshSessions();
    },

    _onStatus(msg) {
        const sid = msg.session_id;
        if (!sid) return;
        if (msg.status === 'running') this.runningSessions.add(sid);
        else {
            this.runningSessions.delete(sid);
            if (this.activeSessionId === sid) this._fetchContextUsage(sid);
        }
        const el = document.querySelector(`.session-item[data-sid="${sid}"]`);
        if (el) {
            let ind = el.querySelector('.running-indicator');
            if (msg.status === 'running') {
                if (!ind) { ind = document.createElement('span'); ind.className = 'running-indicator'; el.appendChild(ind); }
            } else { if (ind) ind.remove(); }
        }
    },

    async _loadProjects() {
        const saved = localStorage.getItem('uniclaw_projects');
        if (saved) {
            const data = JSON.parse(saved);
            // 兼容旧格式（纯数组）和新格式（对象）
            if (Array.isArray(data)) {
                data.forEach(dir => { if (!this.projects[dir]) this.projects[dir] = { sessions: [], expanded: true }; });
            } else {
                Object.entries(data).forEach(([dir, meta]) => {
                    if (!this.projects[dir]) this.projects[dir] = { sessions: [], expanded: meta.expanded !== false, created_at: meta.created_at || null };
                });
            }
        }
        await this._refreshSessions();
    },

    async _refreshSessions() {
        try {
            const resp = await fetch('/api/sessions');
            if (!resp.ok) return;
            const sessions = await resp.json();
            const grouped = {};
            sessions.forEach(s => { const d = s.root_dir || ''; if (!d) return; if (!grouped[d]) grouped[d] = []; grouped[d].push(s); });
            const saved = localStorage.getItem('uniclaw_projects');
            let savedDirs = [];
            if (saved) {
                const data = JSON.parse(saved);
                savedDirs = Array.isArray(data) ? data : Object.keys(data);
            }
            Object.keys(this.projects).forEach(dir => { if (!grouped[dir] && !savedDirs.includes(dir)) delete this.projects[dir]; });
            Object.keys(grouped).forEach(dir => {
                if (!this.projects[dir]) this.projects[dir] = { sessions: [], expanded: true };
                this.projects[dir].sessions = grouped[dir].sort((a, b) => (b.end_time || b.start_time || '').localeCompare(a.end_time || a.start_time || ''));
            });
            savedDirs.forEach(dir => { if (!this.projects[dir]) this.projects[dir] = { sessions: [], expanded: true }; });
            this._render();
        } catch (e) { console.error('刷新会话失败:', e); }
    },

    _render() {
        const tree = document.getElementById('session-tree');
        if (!tree) return;
        const sorted = Object.entries(this.projects).sort(([, a], [, b]) => {
            const ta = a.sessions.length > 0 ? (a.sessions[0].end_time || a.sessions[0].start_time || '') : (a.created_at || '');
            const tb = b.sessions.length > 0 ? (b.sessions[0].end_time || b.sessions[0].start_time || '') : (b.created_at || '');
            return tb.localeCompare(ta);
        });

        let html = '';
        sorted.forEach(([rootDir, proj]) => {
            const shortName = rootDir.split(/[/\\]/).pop() || rootDir;
            const isExp = proj.expanded;
            const runCount = proj.sessions.filter(s => this.runningSessions.has(s.session_id)).length;
            const sessionTime = proj.sessions.length > 0 ? (proj.sessions[0].end_time || proj.sessions[0].start_time || '-') : '-';
            const tipData = JSON.stringify({ dir: rootDir, created: proj.created_at || '-', sessions: proj.sessions.length, latest: sessionTime }).replace(/"/g, '&quot;');
            html += `<div class="project-group ${isExp ? 'expanded' : ''}" data-dir="${Utils.escapeHtml(rootDir)}">`;
            html += `<div class="project-header" data-tip="${tipData}" onclick="SessionPanel.toggleProject('${this._esc(rootDir)}')" onmouseenter="SessionPanel._showTip(this, event)" onmousemove="SessionPanel._moveTip(event)" onmouseleave="SessionPanel._hideTip()" ondragover="SessionPanel._onDragOver(event)" ondrop="SessionPanel._onDrop(event, '${this._esc(rootDir)}')">`;
            html += `<span class="project-chevron">${icon('chevronRight')}</span>`;
            html += `<span class="project-icon">${icon('folder')}</span>`;
            html += `<span class="project-name">${Utils.escapeHtml(shortName)}</span>`;
            html += `<span class="project-count">${proj.sessions.length}</span>`;
            if (runCount) html += '<span class="running-indicator"></span>';
            html += `<button class="btn-icon compact" onclick="event.stopPropagation(); SessionPanel.createSession('${this._esc(rootDir)}')" title="新建会话">${icon('plus')}</button>`;
            html += `</div><div class="project-sessions">`;
            proj.sessions.forEach(s => {
                const isActive = s.session_id === this.activeSessionId;
                const isRunning = this.runningSessions.has(s.session_id);
                const isAttn = this.attentionSessions.has(s.session_id);
                const title = s.title || s.session_id;
                const time = Utils.formatRelativeTime(s.end_time || s.start_time);
                const tipData = JSON.stringify({ id: s.session_id, start: s.start_time || '', end: s.end_time || '', dir: s.root_dir || '', msg: s.message_count || 0 }).replace(/"/g, '&quot;');
                html += `<div class="session-item ${isActive ? 'active' : ''}" data-sid="${s.session_id}" data-tip="${tipData}" draggable="true" ondragstart="SessionPanel._onDragStart(event, '${s.session_id}')" onclick="SessionPanel.selectSession('${s.session_id}', '${this._esc(rootDir)}')" onmouseenter="SessionPanel._showTip(this, event)" onmousemove="SessionPanel._moveTip(event)" onmouseleave="SessionPanel._hideTip()">`;
                html += `<span class="session-icon">${icon('chat')}</span>`;
                html += `<div class="session-info"><div class="session-title">${Utils.escapeHtml(title)}</div><div class="session-meta">${time}</div></div>`;
                if (isRunning) html += '<span class="running-indicator"></span>';
                if (isAttn) html += '<span class="attention-badge"></span>';
                html += `<button class="btn-icon compact" onclick="event.stopPropagation(); SessionPanel.showMenu('${s.session_id}', '${this._esc(rootDir)}')" style="opacity:0.5">${icon('moreVertical')}</button>`;
                html += `</div>`;
            });
            html += `</div></div>`;
        });
        if (!sorted.length) html = '<div class="no-results">暂无会话</div>';
        tree.innerHTML = html;
    },

    _onDragStart(e, sid) { e.dataTransfer.setData('text/plain', sid); e.dataTransfer.effectAllowed = 'move'; },
    _onDragOver(e) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; e.currentTarget.classList.add('drag-over'); },
    async _onDrop(e, targetDir) {
        e.preventDefault(); e.currentTarget.classList.remove('drag-over');
        const sid = e.dataTransfer.getData('text/plain');
        if (!sid) return;
        try {
            const r = await fetch(`/api/sessions/${sid}/move`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ root_dir: targetDir }) });
            if (r.ok) { Utils.showSuccess('会话已移动'); this._refreshSessions(); }
        } catch (_) { Utils.showError('移动失败'); }
    },

    toggleProject(dir) { if (this.projects[dir]) { this.projects[dir].expanded = !this.projects[dir].expanded; this._render(); } },

    async selectSession(sessionId, rootDir) {
        this.activeSessionId = sessionId;
        this.activeProjectDir = rootDir;
        Chat.currentSessionId = sessionId;
        Chat._resetStreamingState();
        Permission.closeIfSessionMismatch(sessionId);
        InputDialog.closeIfSessionMismatch(sessionId);
        WS.send({ type: 'set_active', session_id: sessionId });
        this._updateStatusBar(rootDir, sessionId);
        try { await Chat.loadHistory(sessionId); } catch (e) { console.error('[SessionPanel] 加载历史失败:', e); }
        const si = document.getElementById('search-input');
        if (si && si.value.trim()) this._onSearch(si.value);
        else this._render();
    },

    createSession(rootDir) {
        this.activeSessionId = null;
        this.activeProjectDir = rootDir;
        Chat.currentSessionId = null;
        Chat._resetStreamingState();
        this._updateStatusBar(rootDir, null, true);
        Chat.clear();
        Chat._appendSystemMessage('新会话，发送消息开始对话');
        this._render();
    },

    _updateStatusBar(rootDir, sessionId, skipFetch = false) {
        const shortDir = rootDir ? (rootDir.split(/[/\\]/).pop() || rootDir) : '-';
        const pel = document.getElementById('status-project');
        if (pel) { pel.textContent = shortDir; pel.title = rootDir || ''; }
        const sel = document.getElementById('status-session');
        if (sel) sel.textContent = sessionId || '新会话';
        if (!sessionId || skipFetch) {
            const mel = document.getElementById('status-model'); if (mel) mel.textContent = '-';
            this._clearContextTimer(); this._updateContextDisplay(null); return;
        }
        fetch(`/api/sessions/${sessionId}`).then(r => r.ok ? r.json() : null).then(d => { if (d && sel) sel.textContent = d.title || sessionId; }).catch(() => {});
        fetch(`/api/config?session_id=${sessionId}`).then(r => r.json()).then(d => {
            const mel = document.getElementById('status-model');
            if (mel && d.model_name?.length) mel.textContent = d.model_name[0];
            const pel2 = document.getElementById('status-permission');
            if (pel2 && d.permission_mode) {
                const map = { auto: 'Auto', manual: 'Manual', 'accept-all': 'Accept All', plan: 'Plan' };
                pel2.textContent = map[d.permission_mode] || d.permission_mode;
                pel2.className = `perm-mode ${d.permission_mode}`;
            }
        }).catch(() => {});
        this._fetchContextUsage(sessionId);
        this._startContextTimer(sessionId);
    },

    _fetchContextUsage(sid) {
        if (!sid) return;
        fetch(`/api/context?session_id=${sid}`).then(r => r.ok ? r.json() : null).then(d => { if (d) this._updateContextDisplay(d); }).catch(() => {});
    },

    _updateContextDisplay(data) {
        const pctEl = document.getElementById('context-pct');
        const fillEl = document.getElementById('context-bar-fill');
        if (!pctEl || !fillEl) return;
        if (!data || data.percentage === undefined) { pctEl.textContent = '-'; fillEl.style.width = '0%'; fillEl.className = 'context-mini-fill'; return; }
        const pct = data.percentage;
        pctEl.textContent = `${pct}%`;
        fillEl.style.width = `${Math.min(100, pct)}%`;
        fillEl.className = 'context-mini-fill' + (pct >= 85 ? ' critical' : pct >= 70 ? ' warn' : '');
    },

    _startContextTimer(sid) { this._clearContextTimer(); this._contextTimer = setInterval(() => { if (this.activeSessionId === sid) this._fetchContextUsage(sid); }, 30000); },
    _clearContextTimer() { if (this._contextTimer) { clearInterval(this._contextTimer); this._contextTimer = null; } },

    showMenu(sessionId, rootDir) {
        this._hideMenu();
        const el = document.querySelector(`.session-item[data-sid="${sessionId}"]`);
        if (!el) return;
        const menu = document.createElement('div');
        menu.className = 'context-menu';
        menu.id = 'session-context-menu';
        menu.innerHTML = `
            <div class="context-menu-item" onclick="SessionPanel._renameSession('${sessionId}')"><span class="ctx-icon">${icon('edit')}</span>重命名</div>
            <div class="context-menu-sep"></div>
            <div class="context-menu-item danger" onclick="SessionPanel._deleteSession('${sessionId}')"><span class="ctx-icon">${icon('trash')}</span>删除</div>
        `;
        document.body.appendChild(menu);
        const rect = el.getBoundingClientRect();
        menu.style.top = rect.bottom + 4 + 'px';
        menu.style.left = (rect.right - 140) + 'px';
        setTimeout(() => document.addEventListener('click', this._hideMenu, { once: true }), 0);
    },
    _hideMenu() { const m = document.getElementById('session-context-menu'); if (m) m.remove(); },

    _renameSession(sid) {
        this._hideMenu();
        this._showModal('重命名会话', `
            <div style="display:flex;gap:8px;margin-top:4px">
                <input type="text" id="rename-input" class="input" style="flex:1" />
                <button class="btn btn-secondary" id="ai-generate-btn" style="white-space:nowrap;font-size:12px">${icon('sparkles')} AI</button>
            </div>
        `, () => {
            const t = document.getElementById('rename-input').value.trim();
            if (t) fetch(`/api/sessions/${sid}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: t }) }).then(() => this._refreshSessions());
        });
        document.getElementById('ai-generate-btn').onclick = () => this._generateTitle(sid);
        setTimeout(() => document.getElementById('rename-input')?.focus(), 0);
    },

    async _generateTitle(sid) {
        const btn = document.getElementById('ai-generate-btn');
        const inp = document.getElementById('rename-input');
        if (!btn || !inp) return;
        btn.disabled = true; btn.textContent = '生成中...';
        try {
            const r = await fetch(`/api/sessions/${sid}/title/generate`, { method: 'POST' });
            const d = await r.json();
            if (d.title) { inp.value = d.title; inp.focus(); }
            else Utils.showToast('生成失败');
        } catch (_) { Utils.showToast('生成失败'); }
        finally { btn.disabled = false; btn.innerHTML = `${icon('sparkles')} AI`; }
    },

    async _generateTitleQuick(sid) {
        this._hideMenu();
        Utils.showToast('正在生成标题...');
        try {
            const r = await fetch(`/api/sessions/${sid}/title/generate`, { method: 'POST' });
            const d = await r.json();
            if (d.title) {
                await fetch(`/api/sessions/${sid}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: d.title }) });
                Utils.showSuccess('标题已更新');
                this._refreshSessions();
            } else Utils.showToast('生成失败');
        } catch (_) { Utils.showToast('生成失败'); }
    },

    async _deleteSession(sid) {
        this._hideMenu();
        if (!await Utils.confirm('确定删除此会话？此操作不可撤销。')) return;
        try {
            const r = await fetch(`/api/sessions/${sid}`, { method: 'DELETE' });
            if (!r.ok) throw new Error();
            if (this.activeSessionId === sid) { this.activeSessionId = null; Chat.clear(); }
            Utils.showSuccess('会话已删除');
            await this._refreshSessions();
        } catch (e) { Utils.showError('删除失败'); }
    },

    _showModal(title, bodyHtml, onConfirm) {
        const old = document.getElementById('session-modal'); if (old) old.remove();
        const modal = document.createElement('div');
        modal.id = 'session-modal';
        modal.className = 'modal-overlay';
        modal.innerHTML = `<div class="modal-content"><div class="modal-title">${Utils.escapeHtml(title)}</div><div class="modal-body">${bodyHtml}</div><div class="modal-actions"><button class="btn btn-secondary" id="sm-cancel">取消</button><button class="btn btn-primary" id="sm-confirm">确认</button></div></div>`;
        document.body.appendChild(modal);
        document.getElementById('sm-cancel').onclick = () => modal.remove();
        document.getElementById('sm-confirm').onclick = () => { onConfirm(); modal.remove(); };
    },

    async _onSearch(kw) {
        if (!kw.trim()) { this._render(); return; }
        try {
            const r = await fetch(`/api/sessions/search?keyword=${encodeURIComponent(kw)}`);
            const results = await r.json();
            const tree = document.getElementById('session-tree');
            let html = '<div style="padding:8px 14px;font-size:12px;color:var(--text-3)">搜索结果</div>';
            results.forEach(s => {
                html += `<div class="session-item" data-sid="${s.session_id}" onclick="SessionPanel.selectSession('${s.session_id}', '${this._esc(s.root_dir || '')}')">`;
                html += `<span class="session-icon">${icon('chat')}</span>`;
                html += `<div class="session-info"><div class="session-title">${Utils.escapeHtml(s.title || s.session_id)}</div><div class="session-meta">${Utils.formatRelativeTime(s.end_time || s.start_time)}</div></div></div>`;
            });
            if (!results.length) html += '<div class="no-results">无匹配结果</div>';
            tree.innerHTML = html;
        } catch (e) { console.error('搜索失败:', e); }
    },

    _showNewProjectDialog() {
        const modal = document.getElementById('new-project-modal');
        if (modal) modal.classList.remove('hidden');
        const inp = document.getElementById('project-path'); if (inp) inp.value = '';
        const list = document.getElementById('dir-list'); if (list) list.innerHTML = '';
        document.getElementById('browse-btn').onclick = () => this._browseDir('');
        document.getElementById('project-confirm').onclick = () => {
            const p = document.getElementById('project-path').value.trim();
            if (p) { this.projects[p] = { sessions: [], expanded: true, created_at: this._now() }; this._saveProjects(); this._render(); modal.classList.add('hidden'); }
        };
        document.getElementById('project-cancel').onclick = () => modal.classList.add('hidden');
    },

    async _browseDir(path) {
        try {
            const r = await fetch(`/api/dirs?path=${encodeURIComponent(path)}`);
            const dirs = await r.json();
            document.getElementById('project-path').value = path;
            document.getElementById('dir-list').innerHTML = dirs.filter(d => d.is_dir).map(d =>
                `<div class="dir-item" onclick="SessionPanel._browseDir('${this._esc(d.path)}')">${icon('folder')} ${Utils.escapeHtml(d.name)}</div>`
            ).join('');
        } catch (e) { console.error('浏览目录失败:', e); }
    },

    _saveProjects() {
        const data = {};
        Object.entries(this.projects).forEach(([dir, proj]) => {
            data[dir] = { expanded: proj.expanded, created_at: proj.created_at || null };
        });
        localStorage.setItem('uniclaw_projects', JSON.stringify(data));
    },
    _esc(s) { return s.replace(/\\/g, '\\\\').replace(/'/g, "\\'"); },
    _now() { const d = new Date(); const pad = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; },

    _showTip(el, event) {
        const raw = el.getAttribute('data-tip');
        if (!raw) return;
        let d;
        try { d = JSON.parse(raw); } catch { return; }

        let rows;
        if (d.id) {
            // 会话 tooltip
            const fmtTime = t => t ? t.replace('T', ' ').substring(0, 19) : '-';
            rows = [['ID', d.id], ['创建', fmtTime(d.start)], ['活跃', fmtTime(d.end)], ['路径', d.dir || '-'], ['消息', d.msg]];
        } else {
            // 项目 tooltip
            rows = [['路径', d.dir], ['创建', d.created || '-'], ['会话', d.sessions], ['最新', d.latest || '-']];
        }
        const inner = rows.map(([k, v]) => `<span style="color:var(--text-3)">${k}: </span><span style="color:var(--text-0)">${Utils.escapeHtml(String(v))}</span>`).join('<br>');

        let tip = document.getElementById('session-tooltip');
        if (!tip) {
            tip = document.createElement('div');
            tip.id = 'session-tooltip';
            document.body.appendChild(tip);
        }
        tip.innerHTML = inner;
        tip.style.display = 'block';
        this._moveTip(event);
    },

    _moveTip(event) {
        const tip = document.getElementById('session-tooltip');
        if (!tip || tip.style.display === 'none') return;
        tip.style.left = `${event.clientX + 12}px`;
        tip.style.top = `${event.clientY + 12}px`;
    },

    _hideTip() {
        const tip = document.getElementById('session-tooltip');
        if (tip) tip.style.display = 'none';
    },
};
