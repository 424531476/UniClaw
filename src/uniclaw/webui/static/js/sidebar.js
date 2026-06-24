/* sidebar.js — 右侧面板(文件树、控制台、Checkpoint、Git) */

const Sidebar = {
    currentTab: 'files',
    _consoleHistory: [],
    _consoleHistoryIdx: -1,
    _gitCollapsed: { staged: false, changes: false },

    /** 初始化 */
    init() {
        // Tab 切换
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.onclick = () => this.switchTab(btn.dataset.tab);
        });

        // 控制台输入
        const consoleInput = document.getElementById('console-input');
        consoleInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                this._executeConsoleCommand(e.target.value);
                e.target.value = '';
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (this._consoleHistoryIdx < this._consoleHistory.length - 1) {
                    this._consoleHistoryIdx++;
                    e.target.value = this._consoleHistory[this._consoleHistory.length - 1 - this._consoleHistoryIdx];
                }
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (this._consoleHistoryIdx > 0) {
                    this._consoleHistoryIdx--;
                    e.target.value = this._consoleHistory[this._consoleHistory.length - 1 - this._consoleHistoryIdx];
                } else {
                    this._consoleHistoryIdx = -1;
                    e.target.value = '';
                }
            }
        });

        // 注册 shell_result 处理器(控制台专用)
        WS.on('shell_result', (msg) => this._onShellResult(msg));
    },

    /** 切换 Tab */
    switchTab(tab) {
        this.currentTab = tab;
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tab);
        });
        document.querySelectorAll('.tab-content').forEach(el => {
            el.classList.toggle('active', el.id === `tab-${tab}`);
        });
        // 加载对应内容
        if (tab === 'files') this._loadFileTree();
        if (tab === 'checkpoint') this._loadCheckpoints();
        if (tab === 'git') this._loadGitStatus();
        if (tab === 'console') this._loadMonitors();
    },

    /** 加载文件树 */
    async _loadFileTree() {
        const rootDir = SessionPanel.activeProjectDir;
        if (!rootDir) return;
        try {
            const resp = await fetch(`/api/files?root_dir=${encodeURIComponent(rootDir)}`);
            const files = await resp.json();
            const tree = document.getElementById('file-tree');
            tree.innerHTML = files.map(f => {
                const icon = f.is_dir ? '📁' : '📄';
                return `<div class="file-tree-item ${f.is_dir ? 'dir' : 'file'}"
                    onclick="${f.is_dir ? `Sidebar._loadSubDir('${f.path}')` : `Sidebar._previewFile('${f.path}')`}">
                    ${icon} ${Utils.escapeHtml(f.name)}
                </div>`;
            }).join('');
        } catch (e) {
            console.error('加载文件树失败:', e);
        }
    },

    /** 加载子目录 */
    async _loadSubDir(path) {
        const rootDir = SessionPanel.activeProjectDir;
        if (!rootDir) return;
        try {
            const resp = await fetch(`/api/files?root_dir=${encodeURIComponent(rootDir)}&path=${encodeURIComponent(path)}`);
            const files = await resp.json();
            const tree = document.getElementById('file-tree');
            let html = `<div class="file-tree-item" onclick="Sidebar._loadFileTree()">⬅ 返回</div>`;
            html += files.map(f => {
                const icon = f.is_dir ? '📁' : '📄';
                const subPath = path + '/' + f.name;
                return `<div class="file-tree-item ${f.is_dir ? 'dir' : 'file'}"
                    onclick="${f.is_dir ? `Sidebar._loadSubDir('${subPath}')` : `Sidebar._previewFile('${subPath}')`}">
                    ${icon} ${Utils.escapeHtml(f.name)}
                </div>`;
            }).join('');
            tree.innerHTML = html;
        } catch (e) {
            console.error('加载子目录失败:', e);
        }
    },

    /** 预览文件：将 @filepath 插入到光标位置 */
    _previewFile(path) {
        const input = document.getElementById('chat-input');
        const start = input.selectionStart;
        const end = input.selectionEnd;
        const current = input.value;
        const insertText = `@${path} `;
        // 在光标位置插入,替换选中内容
        input.value = current.substring(0, start) + insertText + current.substring(end);
        // 光标移到插入内容之后
        const cursor = start + insertText.length;
        input.setSelectionRange(cursor, cursor);
        input.focus();
        // 触发 input 事件以更新高度
        input.dispatchEvent(new Event('input'));
    },

    /** 加载 Checkpoints */
    async _loadCheckpoints() {
        const rootDir = SessionPanel.activeProjectDir;
        if (!rootDir) return;
        try {
            const resp = await fetch(`/api/checkpoints?root_dir=${encodeURIComponent(rootDir)}`);
            const data = await resp.json();
            const content = document.getElementById('checkpoint-content');
            const output = data.output || '';
            const checkpoints = this._parseCheckpoints(output);

            if (checkpoints.length === 0) {
                let html = '<div style="font-size:12px">';
                html += '<p style="color:var(--text-secondary);font-size:13px">无 checkpoint</p>';
                html += '<button class="btn-secondary" onclick="Sidebar._showWorkspaceDiff()" style="font-size:12px;padding:4px 12px;margin-top:8px">工作区变更</button>';
                html += '<div id="cp-diff-area"></div>';
                html += '</div>';
                content.innerHTML = html;
                return;
            }

            let html = '<div style="font-size:12px">';
            // Combo 1: 基准
            html += '<label style="color:var(--text-secondary)">基准:</label>';
            html += '<select id="cp-from" style="width:100%;padding:4px;margin:4px 0 8px;background:var(--bg-primary);border:1px solid var(--border);border-radius:4px;color:var(--text-primary);font-size:12px">';
            html += '<option value="current">当前工作区</option>';
            checkpoints.forEach(cp => {
                html += `<option value="${cp.idx}">${Utils.escapeHtml(cp.label)}</option>`;
            });
            html += '</select>';
            // Combo 2: 对比
            html += '<label style="color:var(--text-secondary)">对比:</label>';
            html += '<select id="cp-to" style="width:100%;padding:4px;margin:4px 0 8px;background:var(--bg-primary);border:1px solid var(--border);border-radius:4px;color:var(--text-primary);font-size:12px">';
            checkpoints.forEach(cp => {
                html += `<option value="${cp.idx}">${Utils.escapeHtml(cp.label)}</option>`;
            });
            html += '</select>';
            // 按钮
            html += '<div style="display:flex;gap:8px;margin-bottom:8px">';
            html += '<button class="btn-primary" onclick="Sidebar._showCheckpointDiff()" style="font-size:12px;padding:4px 12px">对比</button>';
            html += '<button class="btn-secondary" onclick="Sidebar._restoreCheckpoint()" style="font-size:12px;padding:4px 12px">恢复</button>';
            html += '<button class="btn-secondary" onclick="Sidebar._showWorkspaceDiff()" style="font-size:12px;padding:4px 12px">工作区变更</button>';
            html += '</div>';
            // Diff 结果区域
            html += '<div id="cp-diff-area"></div>';
            html += '</div>';
            content.innerHTML = html;
        } catch (e) {
            console.error('加载 checkpoint 失败:', e);
        }
    },

    /** 解析 checkpoint 列表文本(支持文件模式和 git stash 格式) */
    _parseCheckpoints(output) {
        const lines = output.split('\n').filter(l => l.trim());
        return lines.map(line => {
            // 文件快照模式: [0] id - message (time)
            let m = line.match(/^\[(\d+)\]\s+(\S+)\s+-\s+(.+)$/);
            if (m) {
                return { idx: parseInt(m[1]), name: m[2], label: `[${m[1]}] ${m[2]} - ${m[3]}` };
            }
            // git stash 模式: stash@{0}: On branch: message
            m = line.match(/^stash@\{(\d+)\}:\s+(.+)$/);
            if (m) {
                return { idx: parseInt(m[1]), name: m[2], label: `[${m[1]}] ${m[2]}` };
            }
            return null;
        }).filter(Boolean);
    },

    /** 显示 checkpoint diff */
    async _showCheckpointDiff() {
        const rootDir = SessionPanel.activeProjectDir;
        if (!rootDir) return;
        const fromVal = document.getElementById('cp-from').value;
        const toVal = document.getElementById('cp-to').value;
        const diffArea = document.getElementById('cp-diff-area');
        diffArea.innerHTML = '<span style="color:var(--text-secondary)">加载中...</span>';

        try {
            let url;
            if (fromVal === 'current') {
                // 当前工作区 vs checkpoint
                url = `/api/checkpoints/${toVal}/diff?root_dir=${encodeURIComponent(rootDir)}`;
            } else if (toVal === 'current') {
                // checkpoint vs 当前工作区(反转 from/to)
                url = `/api/checkpoints/${fromVal}/diff?root_dir=${encodeURIComponent(rootDir)}`;
            } else {
                // checkpoint vs checkpoint
                url = `/api/checkpoints/diff-between?from_idx=${fromVal}&to_idx=${toVal}&root_dir=${encodeURIComponent(rootDir)}`;
            }
            const resp = await fetch(url);
            const data = await resp.json();
            const diffOutput = data.output || '无差异';

            // 解析 diff 输出,提取文件列表用于筛选
            const files = this._parseDiffFiles(diffOutput);
            this._cpDiffOutput = diffOutput;
            this._cpDiffMode = 'unified';

            let html = '';
            if (files.length > 0) {
                html += '<label style="color:var(--text-secondary);font-size:11px">文件筛选:</label>';
                html += '<select id="cp-file-filter" onchange="Sidebar._filterCpDiff()" style="width:100%;padding:4px;margin:4px 0 8px;background:var(--bg-primary);border:1px solid var(--border);border-radius:4px;color:var(--text-primary);font-size:12px">';
                html += '<option value="">全部文件</option>';
                files.forEach(f => { html += `<option value="${Utils.escapeHtml(f)}">${Utils.escapeHtml(f)}</option>`; });
                html += '</select>';
            }
            // Unified / Split 切换按钮
            html += '<div style="display:flex;gap:4px;margin-bottom:8px">';
            html += '<button class="btn-secondary cp-diff-btn active" onclick="Sidebar._switchCpDiffMode(\'unified\')" style="font-size:11px;padding:2px 8px">Unified</button>';
            html += '<button class="btn-secondary cp-diff-btn" onclick="Sidebar._switchCpDiffMode(\'split\')" style="font-size:11px;padding:2px 8px">Split</button>';
            html += '</div>';
            html += `<div id="cp-diff-content">${this._renderCpDiff(diffOutput, 'unified')}</div>`;
            diffArea.innerHTML = html;
        } catch (e) {
            diffArea.innerHTML = `<span style="color:#ef4444">加载失败: ${e.message}</span>`;
        }
    },

    /** 显示当前工作区变更(未提交的修改) */
    async _showWorkspaceDiff() {
        const rootDir = SessionPanel.activeProjectDir;
        if (!rootDir) return;
        const diffArea = document.getElementById('cp-diff-area');
        diffArea.innerHTML = '<span style="color:var(--text-secondary)">加载中...</span>';

        try {
            const resp = await fetch(`/api/checkpoints/diff-current?root_dir=${encodeURIComponent(rootDir)}`);
            const data = await resp.json();
            const diffOutput = data.output || '无变更';

            const files = this._parseDiffFiles(diffOutput);
            this._cpDiffOutput = diffOutput;
            this._cpDiffMode = 'unified';

            let html = '';
            if (files.length > 0) {
                html += '<label style="color:var(--text-secondary);font-size:11px">文件筛选:</label>';
                html += '<select id="cp-file-filter" onchange="Sidebar._filterCpDiff()" style="width:100%;padding:4px;margin:4px 0 8px;background:var(--bg-primary);border:1px solid var(--border);border-radius:4px;color:var(--text-primary);font-size:12px">';
                html += '<option value="">全部文件</option>';
                files.forEach(f => { html += `<option value="${Utils.escapeHtml(f)}">${Utils.escapeHtml(f)}</option>`; });
                html += '</select>';
            }
            html += '<div style="display:flex;gap:4px;margin-bottom:8px">';
            html += '<button class="btn-secondary cp-diff-btn active" onclick="Sidebar._switchCpDiffMode(\'unified\')" style="font-size:11px;padding:2px 8px">Unified</button>';
            html += '<button class="btn-secondary cp-diff-btn" onclick="Sidebar._switchCpDiffMode(\'split\')" style="font-size:11px;padding:2px 8px">Split</button>';
            html += '</div>';
            html += `<div id="cp-diff-content">${this._renderCpDiff(diffOutput, 'unified')}</div>`;
            diffArea.innerHTML = html;
        } catch (e) {
            diffArea.innerHTML = `<span style="color:#ef4444">加载失败: ${e.message}</span>`;
        }
    },

    /** 切换 checkpoint diff 视图模式 */
    _switchCpDiffMode(mode) {
        this._cpDiffMode = mode;
        document.querySelectorAll('.cp-diff-btn').forEach(b => b.classList.remove('active'));
        event.target.classList.add('active');
        const filter = document.getElementById('cp-file-filter')?.value || '';
        const diffContent = document.getElementById('cp-diff-content');
        diffContent.innerHTML = this._renderCpDiff(this._cpDiffOutput || '', mode, filter);
    },

    /** 渲染 checkpoint diff(支持 unified 和 split 模式) */
    _renderCpDiff(diffOutput, mode, fileFilter) {
        if (mode === 'split') {
            // Split 模式：解析 unified diff 并转为 split 视图
            return this._renderSplitDiff(diffOutput, fileFilter);
        }
        return this._renderUnifiedDiff(diffOutput, fileFilter);
    },

    /** 渲染 split diff(从 unified diff 解析) */
    _renderSplitDiff(diffOutput, fileFilter) {
        const lines = diffOutput.split('\n');
        let html = '';
        let leftLines = [], rightLines = [];
        let inFile = !fileFilter;
        let pendingDels = [];
        let currentHunkHeader = '';

        const flushPending = () => {
            for (const d of pendingDels) {
                leftLines.push(d);
                rightLines.push({ text: '', type: 'empty' });
            }
            pendingDels = [];
        };

        const flushHunk = () => {
            flushPending();
            if (leftLines.length > 0 || rightLines.length > 0) {
                html += '<div style="margin-bottom:8px">';
                if (currentHunkHeader) {
                    html += `<div style="color:#a78bfa;padding:2px 4px;font-size:10px">${Utils.escapeHtml(currentHunkHeader)}</div>`;
                }
                html += '<div style="display:flex;gap:4px;font-size:11px">';
                html += this._renderSplitPair(leftLines, rightLines);
                html += '</div></div>';
                leftLines = []; rightLines = [];
            }
            currentHunkHeader = '';
        };

        for (const line of lines) {
            if (line.startsWith('diff --git')) {
                flushHunk();
                const m = line.match(/b\/(.+)$/);
                const fname = m ? m[1] : '';
                inFile = !fileFilter || fname === fileFilter;
                continue;
            }
            if (!inFile) continue;
            if (line.startsWith('index ') || line.startsWith('---') || line.startsWith('+++') || line.startsWith('\\ ')) {
                continue;
            }
            if (line.startsWith('@@')) {
                flushHunk();
                currentHunkHeader = line;
                continue;
            }
            if (line.startsWith('-')) {
                pendingDels.push({ text: line, type: 'del' });
            } else if (line.startsWith('+')) {
                if (pendingDels.length > 0) {
                    leftLines.push(pendingDels.shift());
                    rightLines.push({ text: line, type: 'add' });
                } else {
                    leftLines.push({ text: '', type: 'empty' });
                    rightLines.push({ text: line, type: 'add' });
                }
            } else {
                flushPending();
                leftLines.push({ text: line, type: 'ctx' });
                rightLines.push({ text: line, type: 'ctx' });
            }
        }
        flushHunk();
        return html;
    },

    /** 渲染 split diff 的左右两栏 */
    _renderSplitPair(leftLines, rightLines) {
        const maxLen = Math.max(leftLines.length, rightLines.length);
        let leftHtml = '<div style="flex:1;background:var(--bg-primary);border-radius:4px;padding:4px;overflow-x:auto">';
        let rightHtml = '<div style="flex:1;background:var(--bg-primary);border-radius:4px;padding:4px;overflow-x:auto">';
        for (let i = 0; i < maxLen; i++) {
            const l = leftLines[i];
            const r = rightLines[i];
            if (l) {
                if (l.type === 'empty') {
                    leftHtml += '<div style="white-space:pre">&nbsp;</div>';
                } else {
                    const color = l.type === 'del' ? '#f87171' : l.type === 'add' ? '#4ade80' : 'inherit';
                    leftHtml += `<div style="color:${color};white-space:pre">${Utils.escapeHtml(l.text)}</div>`;
                }
            }
            if (r) {
                if (r.type === 'empty') {
                    rightHtml += '<div style="white-space:pre">&nbsp;</div>';
                } else {
                    const color = r.type === 'add' ? '#4ade80' : r.type === 'del' ? '#f87171' : 'inherit';
                    rightHtml += `<div style="color:${color};white-space:pre">${Utils.escapeHtml(r.text)}</div>`;
                }
            }
        }
        leftHtml += '</div>';
        rightHtml += '</div>';
        return leftHtml + rightHtml;
    },

    /** 解析 diff 输出中的文件列表 */
    _parseDiffFiles(diffOutput) {
        const files = [];
        diffOutput.split('\n').forEach(line => {
            const m = line.match(/^diff --git a\/(.+?) b\//);
            if (m && !files.includes(m[1])) files.push(m[1]);
        });
        return files;
    },

    /** 按文件筛选 diff */
    _filterCpDiff() {
        const filter = document.getElementById('cp-file-filter').value;
        const diffContent = document.getElementById('cp-diff-content');
        const mode = this._cpDiffMode || 'unified';
        diffContent.innerHTML = this._renderCpDiff(this._cpDiffOutput || '', mode, filter);
    },

    /** 渲染 unified diff 输出(带颜色) */
    _renderUnifiedDiff(diffOutput, fileFilter) {
        const lines = diffOutput.split('\n');
        let html = '<pre style="font-size:11px;white-space:pre-wrap;background:var(--bg-primary);padding:8px;border-radius:4px;margin:0;height:100%;box-sizing:border-box">';
        let inFile = !fileFilter;
        for (const line of lines) {
            // 文件分隔线
            if (line.startsWith('diff --git')) {
                const m = line.match(/b\/(.+)$/);
                const fname = m ? m[1] : '';
                inFile = !fileFilter || fname === fileFilter;
                if (inFile) html += `<span style="color:#60a5fa;font-weight:bold">${Utils.escapeHtml(line)}\n</span>`;
                continue;
            }
            if (!inFile) continue;
            if (line.startsWith('---') || line.startsWith('+++')) {
                html += `<span style="color:#60a5fa">${Utils.escapeHtml(line)}\n</span>`;
            } else if (line.startsWith('@@')) {
                html += `<span style="color:#a78bfa">${Utils.escapeHtml(line)}\n</span>`;
            } else if (line.startsWith('+')) {
                html += `<span style="color:#4ade80">${Utils.escapeHtml(line)}\n</span>`;
            } else if (line.startsWith('-')) {
                html += `<span style="color:#f87171">${Utils.escapeHtml(line)}\n</span>`;
            } else {
                html += Utils.escapeHtml(line) + '\n';
            }
        }
        html += '</pre>';
        return html;
    },

    /** 恢复到选中的 checkpoint */
    async _restoreCheckpoint() {
        const rootDir = SessionPanel.activeProjectDir;
        if (!rootDir) return;
        const cpIdx = document.getElementById('cp-to').value;
        if (cpIdx === 'current') {
            Utils.showToast('请选择一个 checkpoint 进行恢复');
            return;
        }
        const confirmed = await Utils.confirm(`确定恢复到 checkpoint [${cpIdx}]？当前未保存的更改将丢失。`);
        if (!confirmed) return;
        try {
            Utils.showLoading('正在恢复 checkpoint...');
            const resp = await fetch(`/api/checkpoints/${cpIdx}/restore`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ root_dir: rootDir }),
            });
            if (!resp.ok) {
                const error = await resp.json().catch(() => ({ detail: '恢复失败' }));
                throw new Error(error.detail);
            }
            Utils.showToast('恢复成功');
            this._loadCheckpoints();
        } catch (e) {
            console.error('恢复 checkpoint 失败:', e);
            Utils.showError(e.message || '恢复失败');
        } finally {
            Utils.hideLoading();
        }
    },

    /** 加载 Git 状态 */
    async _loadGitStatus() {
        const rootDir = SessionPanel.activeProjectDir;
        if (!rootDir) return;
        try {
            const resp = await fetch(`/api/git/status?root_dir=${encodeURIComponent(rootDir)}`);
            const data = await resp.json();
            const content = document.getElementById('git-content');
            const lines = (data.output || '').split('\n').filter(l => l.trim());
            if (lines.length === 0) {
                content.innerHTML = '<div style="text-align:center;padding:40px 0;color:var(--text-3)"><div style="font-size:32px;margin-bottom:8px">✓</div><div style="font-size:13px">没有更改</div></div>';
                return;
            }

            const staged = [];
            const changes = [];
            for (const line of lines) {
                const statusCode = line.substring(0, 2);
                const file = line.substring(3);
                const indexStatus = statusCode[0];
                const worktreeStatus = statusCode[1];
                const isUntracked = statusCode === '??';

                if (indexStatus !== ' ' && indexStatus !== '?') {
                    staged.push({ file, statusChar: indexStatus });
                }
                if (worktreeStatus !== ' ' || isUntracked) {
                    changes.push({ file, statusChar: isUntracked ? '?' : worktreeStatus });
                }
            }

            const collapse = this._gitCollapsed;
            let html = '';

            // 提交区域
            html += '<div class="git-commit-box">';
            html += '  <textarea id="git-commit-msg" rows="2" placeholder="提交消息..."></textarea>';
            html += '  <div class="git-commit-bar">';
            html += '    <span class="git-commit-hint">Ctrl+Enter 提交</span>';
            html += '    <div class="git-commit-btns">';
            html += '      <button class="btn-icon git-ai-btn" onclick="Sidebar._aiCommit()" title="AI 生成">✨</button>';
            html += '      <button class="btn-primary git-commit-btn" onclick="Sidebar._gitCommit()">提交</button>';
            html += '    </div>';
            html += '  </div>';
            html += '</div>';

            // 暂存区
            html += this._renderGitSection('staged', '暂存的更改', staged, collapse.staged, true);
            // 工作区
            html += this._renderGitSection('changes', '更改', changes, collapse.changes, false);

            content.innerHTML = html;

            // Ctrl+Enter 快捷提交
            const textarea = document.getElementById('git-commit-msg');
            if (textarea) {
                textarea.addEventListener('keydown', (e) => {
                    if (e.ctrlKey && e.key === 'Enter') {
                        e.preventDefault();
                        Sidebar._gitCommit();
                    }
                });
            }
        } catch (e) {
            console.error('加载 git 状态失败:', e);
        }
    },

    /** 渲染一个 Git 分组 */
    _renderGitSection(key, label, files, collapsed, isStaged) {
        if (files.length === 0) return '';

        let html = `<div class="git-section">`;
        html += `<div class="git-section-header" onclick="Sidebar._toggleGitSection('${key}')">`;
        html += `  <svg class="git-chevron${collapsed ? ' collapsed' : ''}" width="16" height="16" viewBox="0 0 16 16"><path d="M5.7 13.7L5 13l4.6-4.6L5 3.7l.7-.7 5.3 5.3-5.3 5.4z" fill="currentColor"/></svg>`;
        html += `  <span class="git-section-title">${label}</span>`;
        html += `  <span class="git-count">${files.length}</span>`;
        html += '</div>';

        if (!collapsed) {
            html += '<div class="git-file-list">';
            for (const { file, statusChar } of files) {
                const colorCls = this._gitStatusColor(statusChar);
                const checked = isStaged ? 'checked' : '';
                html += `<div class="git-file-item">`;
                html += `  <label class="git-file-check"><input type="checkbox" class="git-file" value="${Utils.escapeHtml(file)}" ${checked} onchange="Sidebar._toggleStage(this)" /></label>`;
                html += `  <span class="git-file-status ${colorCls}">${statusChar}</span>`;
                html += `  <span class="git-file-path" title="${Utils.escapeHtml(file)}">${Utils.escapeHtml(file)}</span>`;
                html += `</div>`;
            }
            html += '</div>';
        }

        html += '</div>';
        return html;
    },

    /** Git 状态字符 → 颜色类 */
    _gitStatusColor(ch) {
        switch (ch) {
            case 'M': return 'status-modified';
            case 'A': return 'status-added';
            case 'D': return 'status-deleted';
            case 'R': return 'status-renamed';
            case 'C': return 'status-copied';
            case '?': return 'status-untracked';
            default:  return 'status-modified';
        }
    },

    /** 折叠/展开 Git 分组 */
    _toggleGitSection(key) {
        this._gitCollapsed[key] = !this._gitCollapsed[key];
        this._loadGitStatus();
    },

    /** 切换文件暂存状态 */
    async _toggleStage(checkbox) {
        const rootDir = SessionPanel.activeProjectDir;
        if (!rootDir) return;
        const file = checkbox.value;
        const endpoint = checkbox.checked ? '/api/git/stage' : '/api/git/unstage';
        try {
            await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ root_dir: rootDir, files: [file] }),
            });
            this._loadGitStatus();
        } catch (e) {
            Utils.showToast('操作失败');
            checkbox.checked = !checkbox.checked;
        }
    },

    /** Git 提交 */
    async _gitCommit() {
        const rootDir = SessionPanel.activeProjectDir;
        const msg = document.getElementById('git-commit-msg')?.value;
        if (!rootDir || !msg) return;
        // 收集暂存区中已勾选的文件
        const stagedSection = document.querySelector('.git-section-staged');
        const files = stagedSection
            ? Array.from(stagedSection.querySelectorAll('.git-file:checked')).map(el => el.value)
            : [];
        try {
            const resp = await fetch('/api/git/commit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ root_dir: rootDir, message: msg, files }),
            });
            const data = await resp.json();
            Utils.showToast('提交成功');
            this._loadGitStatus();
        } catch (e) {
            Utils.showToast('提交失败');
        }
    },

    /** AI 生成 commit 信息 */
    async _aiCommit() {
        const rootDir = SessionPanel.activeProjectDir;
        if (!rootDir) return;

        const btn = event?.target;
        if (btn) { btn.disabled = true; btn.textContent = '⏳'; }

        try {
            const resp = await fetch('/api/git/ai-commit-message', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ root_dir: rootDir }),
            });
            const data = await resp.json();

            if (data.error) {
                Utils.showToast(data.error);
                return;
            }

            const input = document.getElementById('git-commit-msg');
            if (input && data.message) {
                input.value = data.message;
                input.focus();
            }
        } catch (e) {
            Utils.showToast('AI 生成失败: ' + e.message);
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = '✨'; }
        }
    },

    /** 执行控制台命令 */
    _executeConsoleCommand(cmd) {
        if (!cmd.trim()) return;
        const sessionId = SessionPanel.activeSessionId;
        if (!sessionId) {
            this._appendConsoleOutput('错误: 未选择会话\n', 'error');
            return;
        }
        // 记录命令历史
        this._consoleHistory.push(cmd);
        this._consoleHistoryIdx = -1;
        // 显示命令
        this._appendConsoleOutput(`$ ${cmd}\n`, 'command');
        // 通过 WebSocket 发送 shell 命令
        WS.send({ type: 'shell', session_id: sessionId, command: cmd, source: 'console' });
    },

    /** 收到 shell 命令结果 */
    _onShellResult(msg) {
        // 只显示来自控制台的结果(非聊天框 ! 命令)
        if (msg.source !== 'console') return;
        const output = msg.output || '';
        if (output.trim()) {
            this._appendConsoleOutput(output + '\n', 'result');
        }
        if (!msg.success) {
            this._appendConsoleOutput('(命令执行失败)\n', 'error');
        }
    },

    /** 追加控制台输出 */
    _appendConsoleOutput(text, type) {
        const output = document.getElementById('console-output');
        const span = document.createElement('span');
        span.className = `console-${type}`;
        span.textContent = text;
        output.appendChild(span);
        output.scrollTop = output.scrollHeight;
    },

    /** 加载后台进程列表 */
    async _loadMonitors() {
        try {
            const resp = await fetch('/api/monitors');
            const monitors = await resp.json();
            const container = document.getElementById('console-output');
            // 移除旧的进程列表
            container.querySelectorAll('.monitor-item').forEach(el => el.remove());
            if (monitors.length === 0) return;
            const header = document.createElement('div');
            header.className = 'monitor-item';
            header.style.cssText = 'padding:4px 0;font-size:12px;color:var(--text-secondary);border-top:1px solid var(--border);margin-top:8px';
            header.textContent = '后台进程:';
            container.appendChild(header);
            monitors.forEach(m => {
                const el = document.createElement('div');
                el.className = 'monitor-item';
                el.style.cssText = 'padding:2px 0;font-size:12px;display:flex;align-items:center;gap:8px';
                const statusIcon = m.status === 'running' ? '▶' : '⏹';
                el.innerHTML = `<span>${statusIcon} ${Utils.escapeHtml(m.description || m.command)}</span>`;
                if (m.status === 'running') {
                    const stopBtn = document.createElement('button');
                    stopBtn.className = 'btn-text';
                    stopBtn.style.cssText = 'font-size:11px;padding:1px 6px;color:#ef4444';
                    stopBtn.textContent = 'STOP';
                    stopBtn.onclick = () => this._stopMonitor(m.id);
                    el.appendChild(stopBtn);
                }
                container.appendChild(el);
            });
        } catch (e) {
            console.error('加载进程列表失败:', e);
        }
    },

    /** 停止后台进程 */
    async _stopMonitor(monitorId) {
        try {
            await fetch(`/api/monitors/${monitorId}/stop`, { method: 'POST' });
            Utils.showToast('进程已停止');
            this._loadMonitors();
        } catch (e) {
            Utils.showToast('停止失败');
        }
    },
};
