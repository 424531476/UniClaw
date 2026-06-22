/* input.js — 输入框组件 */

const Input = {
    attachedFiles: [],
    completionPopup: null,
    _commandsCache: null,
    _subcommandsCache: null,
    _filesCache: null,
    _filesCacheDir: null,
    _debounceTimer: null,
    _history: [],
    _historyIdx: -1,
    _suppressAutoComplete: false,

    /** 初始化 */
    init() {
        const input = document.getElementById('chat-input');
        const sendBtn = document.getElementById('send-btn');
        const attachBtn = document.getElementById('attach-btn');
        const fileInput = document.getElementById('file-input');

        // 发送
        sendBtn.onclick = () => this.send();
        input.addEventListener('keydown', (e) => {
            // 补全弹窗打开时：↑↓ 切换高亮并填入输入框
            if (this.completionPopup) {
                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    this._completionNav(1);
                    return;
                }
                if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    this._completionNav(-1);
                    return;
                }
            }
            // 补全弹窗关闭时：上下键浏览历史
            if (!this.completionPopup && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
                if (this._historyNav(e.key === 'ArrowUp' ? -1 : 1)) {
                    e.preventDefault();
                }
                return;
            }
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.send();
            }
        });

        // 输入时自动调整高度 + 自动补全
        input.addEventListener('input', () => {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 150) + 'px';
            this._autoComplete();
        });

        // 失焦时延迟隐藏补全(允许点击选中)
        input.addEventListener('blur', () => {
            setTimeout(() => this._hideCompletion(), 150);
        });

        // 附件
        attachBtn.onclick = () => fileInput.click();
        fileInput.onchange = (e) => this._onFilesSelected(e.target.files);
    },

    /** 发送消息 */
    send() {
        const input = document.getElementById('chat-input');
        const text = input.value.trim();
        if (!text && this.attachedFiles.length === 0) return;

        const sessionId = SessionPanel.activeSessionId;
        const rootDir = SessionPanel.activeProjectDir;

        // 没有活跃会话时,需要先有项目目录
        if (!sessionId && !rootDir) {
            Utils.showToast('请先选择或创建一个项目');
            return;
        }

        if (text.startsWith('!')) {
            // Shell 命令(需要 session)
            if (!sessionId) {
                Utils.showToast('请先创建会话(发送一条消息)');
                return;
            }
            const cmd = text.substring(1).trim();
            if (cmd) {
                WS.send({ type: 'shell', session_id: sessionId, command: cmd, source: 'chat' });
                Chat._appendUserMessage(`$ ${cmd}`);
            }
        } else if (text.startsWith('/')) {
            // 拦截 /clear 和 /cls → 创建新会话(效果同新建会话图标)
            const cmdName = text.substring(1).trim().split(/\s+/)[0].toLowerCase();
            if (cmdName === 'clear' || cmdName === 'cls') {
                SessionPanel.createSession(rootDir);
                input.value = '';
                input.style.height = 'auto';
                return;
            }
            // 斜杠命令(需要 session)
            if (!sessionId) {
                Utils.showToast('请先创建会话(发送一条消息)');
                return;
            }
            WS.send({ type: 'command', session_id: sessionId, command: text });
            Chat._appendUserMessage(text);
        } else {
            // 普通消息
            const msg = {
                type: 'chat',
                content: text,
                files: this.attachedFiles.map(f => ({ name: f.name, data: f.data, mime: f.mime })),
            };
            // 有会话 ID 用 session_id,否则用 root_dir(后端创建新会话)
            if (sessionId) {
                msg.session_id = sessionId;
            } else {
                msg.root_dir = rootDir;
            }
            WS.send(msg);
            if (text || this.attachedFiles.length > 0) {
                const imageFiles = this.attachedFiles.filter(f => f.mime.startsWith('image/'));
                if (imageFiles.length > 0) {
                    Chat._appendUserMessageWithImages(text, imageFiles.map(f => f.url));
                } else if (text) {
                    Chat._appendUserMessage(text);
                }
            }
        }

        // 保存到历史(去重：不与最后一条重复)
        if (text && (this._history.length === 0 || this._history[this._history.length - 1] !== text)) {
            this._history.push(text);
        }
        this._historyIdx = -1;

        // 清空输入
        input.value = '';
        input.style.height = 'auto';
        this.attachedFiles = [];
        this._updateFilePreview();
        this._hideCompletion();
    },

    /** 文件选择 */
    _onFilesSelected(files) {
        Array.from(files).forEach(file => {
            const reader = new FileReader();
            reader.onload = () => {
                const base64 = reader.result.split(',')[1];
                this.attachedFiles.push({
                    name: file.name,
                    data: base64,
                    mime: file.type,
                    url: reader.result,
                });
                this._updateFilePreview();
            };
            reader.readAsDataURL(file);
        });
    },

    /** 更新附件预览 */
    _updateFilePreview() {
        const preview = document.getElementById('file-preview');
        if (this.attachedFiles.length === 0) {
            preview.style.display = 'none';
            preview.innerHTML = '';
            return;
        }
        preview.style.display = 'flex';
        preview.innerHTML = this.attachedFiles.map((f, i) => {
            if (f.mime.startsWith('image/')) {
                return `<div class="file-thumb">
                    <img src="${f.url}" alt="${Utils.escapeHtml(f.name)}" />
                    <button class="remove" onclick="Input.removeFile(${i})">×</button>
                </div>`;
            }
            return `<div class="file-thumb" style="display:flex;align-items:center;justify-content:center;background:var(--bg-tertiary)">
                <span style="font-size:10px">${Utils.escapeHtml(f.name)}</span>
                <button class="remove" onclick="Input.removeFile(${i})">×</button>
            </div>`;
        }).join('');
    },

    /** 移除附件 */
    removeFile(index) {
        this.attachedFiles.splice(index, 1);
        this._updateFilePreview();
    },

    /** 历史消息导航,返回 true 表示已切换 */
    _historyNav(delta) {
        const input = document.getElementById('chat-input');
        // 只在输入框为空或正在浏览历史时触发向上导航
        if (this._history.length === 0) return false;
        if (delta === -1 && this._historyIdx === -1 && input.value.trim() !== '') return false;

        let next;
        if (this._historyIdx === -1) {
            // 从当前输入进入历史
            if (delta === -1) {
                next = this._history.length - 1;
            } else {
                return false;
            }
        } else {
            next = this._historyIdx + delta;
            if (next < 0) next = 0;
            if (next >= this._history.length) {
                // 回到空白
                this._historyIdx = -1;
                input.value = '';
                input.style.height = 'auto';
                return true;
            }
        }

        this._historyIdx = next;
        input.value = this._history[next];
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 150) + 'px';
        // 光标移到末尾
        input.selectionStart = input.selectionEnd = input.value.length;
        return true;
    },

    /** 自动触发补全(输入时调用) */
    _autoComplete() {
        clearTimeout(this._debounceTimer);
        // 选中项后抑制一次自动补全(避免 onSelect 改值后弹窗重弹)
        if (this._suppressAutoComplete) {
            this._suppressAutoComplete = false;
            return;
        }
        const input = document.getElementById('chat-input');
        const text = input.value;

        // 判断是否需要补全
        const lastAtIndex = text.lastIndexOf('@');
        const hasSlash = text.startsWith('/');
        const hasAt = lastAtIndex >= 0;

        if (!hasSlash && !hasAt) {
            this._hideCompletion();
            return;
        }

        // 防抖：150ms 后触发
        this._debounceTimer = setTimeout(() => {
            if (hasSlash) {
                this._showCommandCompletion(text);
            } else if (hasAt) {
                this._showFileCompletion(text);
            }
        }, 150);
    },

    /** 显示斜杠命令/子命令补全 */
    async _showCommandCompletion(text) {
        try {
            // 缓存命令和子命令列表
            if (!this._commandsCache) {
                const resp = await fetch('/api/commands');
                const data = await resp.json();
                this._commandsCache = data.commands || [];
                this._subcommandsCache = data.subcommands || {};
            }

            const body = text.substring(1);
            const parts = body.split(/\s+/);
            const cmdName = parts[0] || '';
            const subQuery = parts.length > 1 ? parts.slice(1).join(' ').toLowerCase() : null;

            // 已输入命令名+空格 → 提示子命令
            if (subQuery !== null && cmdName) {
                const subs = this._subcommandsCache[cmdName];
                if (subs && subs.length > 0) {
                    const matches = subs.filter(s => s.toLowerCase().startsWith(subQuery)).slice(0, 10);
                    if (matches.length > 0) {
                        this._renderCompletion(matches.map(s => ({
                            label: `/${cmdName} ${s}`,
                            desc: '子命令',
                            fill: () => { document.getElementById('chat-input').value = `/${cmdName} ${s}`; },
                            onSelect: () => {
                                this._suppressAutoComplete = true;
                                document.getElementById('chat-input').value = `/${cmdName} ${s} `;
                                this._hideCompletion();
                                document.getElementById('chat-input').focus();
                            }
                        })));
                        return;
                    }
                }
                // 没有匹配的子命令,隐藏弹窗
                this._hideCompletion();
                return;
            }

            // 按命令名前缀匹配
            const query = cmdName.toLowerCase();
            const matches = this._commandsCache.filter(c =>
                c.name.startsWith(query)
            ).slice(0, 10);

            if (matches.length === 0) {
                this._hideCompletion();
                return;
            }

            this._renderCompletion(matches.map(c => ({
                label: `/${c.name}`,
                desc: c.description,
                fill: () => { document.getElementById('chat-input').value = `/${c.name}`; },
                onSelect: () => {
                    this._suppressAutoComplete = true;
                    document.getElementById('chat-input').value = `/${c.name} `;
                    this._hideCompletion();
                    document.getElementById('chat-input').focus();
                }
            })));
        } catch (e) {
            console.error('获取命令列表失败:', e);
        }
    },

    /** 显示文件补全 */
    async _showFileCompletion(text) {
        const rootDir = SessionPanel.activeProjectDir;
        if (!rootDir) return;
        try {
            // 按项目目录缓存文件列表
            if (this._filesCacheDir !== rootDir) {
                const resp = await fetch(`/api/files?root_dir=${encodeURIComponent(rootDir)}&recursive=true`);
                this._filesCache = await resp.json();
                this._filesCacheDir = rootDir;
            }
            const lastAtIndex = text.lastIndexOf('@');
            const query = text.substring(lastAtIndex + 1).toLowerCase();
            const matches = this._filesCache.filter(f =>
                f.path.toLowerCase().includes(query)
            ).slice(0, 10);

            if (matches.length === 0) {
                this._hideCompletion();
                return;
            }

            this._renderCompletion(matches.map(f => ({
                label: f.path,
                desc: f.is_dir ? '📁 目录' : '📄',
                fill: () => {
                    const input = document.getElementById('chat-input');
                    const atIdx = input.value.lastIndexOf('@');
                    input.value = input.value.substring(0, atIdx) + `@${f.path}`;
                },
                onSelect: () => {
                    this._suppressAutoComplete = true;
                    const input = document.getElementById('chat-input');
                    const atIdx = input.value.lastIndexOf('@');
                    input.value = input.value.substring(0, atIdx) + `@${f.path} `;
                    this._hideCompletion();
                    input.focus();
                }
            })));
        } catch (e) {
            console.error('获取文件列表失败:', e);
        }
    },

    /** 渲染补全弹窗 */
    _renderCompletion(items) {
        this._hideCompletion();
        const popup = document.createElement('div');
        popup.className = 'completion-popup';
        popup.innerHTML = items.map((item, i) =>
            `<div class="completion-item ${i === 0 ? 'selected' : ''}" data-idx="${i}">
                <span class="cmd-name">${Utils.escapeHtml(item.label)}</span>
                <span class="cmd-desc">${Utils.escapeHtml(item.desc)}</span>
            </div>`
        ).join('');

        const input = document.getElementById('chat-input');
        const rect = input.getBoundingClientRect();
        popup.style.bottom = (window.innerHeight - rect.top + 4) + 'px';
        popup.style.left = rect.left + 'px';
        document.body.appendChild(popup);
        this.completionPopup = { el: popup, items, selectedIdx: 0 };

        popup.querySelectorAll('.completion-item').forEach(el => {
            el.onclick = () => {
                const idx = parseInt(el.dataset.idx);
                items[idx].onSelect();
            };
            // hover 时更新选中索引
            el.onmouseenter = () => {
                popup.querySelectorAll('.completion-item').forEach(e => e.classList.remove('selected'));
                el.classList.add('selected');
                this.completionPopup.selectedIdx = parseInt(el.dataset.idx);
            };
        });
    },

    /** 补全弹窗键盘导航：切换高亮并填入输入框(不关闭弹窗) */
    _completionNav(delta) {
        if (!this.completionPopup) return;
        const { el, items, selectedIdx } = this.completionPopup;
        const total = items.length;
        // 循环导航
        let next = (selectedIdx + delta + total) % total;
        el.querySelectorAll('.completion-item').forEach(e => e.classList.remove('selected'));
        el.querySelector(`[data-idx="${next}"]`).classList.add('selected');
        this.completionPopup.selectedIdx = next;
        // 滚动到可见
        el.querySelector(`[data-idx="${next}"]`).scrollIntoView({ block: 'nearest' });
        // 填入输入框(不关闭弹窗)
        if (items[next].fill) items[next].fill();
    },

    /** 选中当前高亮的补全项 */
    _completionSelect() {
        if (!this.completionPopup) return;
        const { items, selectedIdx } = this.completionPopup;
        items[selectedIdx].onSelect();
    },

    /** 隐藏补全弹窗 */
    _hideCompletion() {
        if (this.completionPopup) {
            this.completionPopup.el.remove();
            this.completionPopup = null;
        }
    },
};
