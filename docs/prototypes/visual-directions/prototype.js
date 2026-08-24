document.addEventListener('DOMContentLoaded', () => {
  const page = document.querySelector('[data-llm-config]');
  if (!page) return;
  const toast = page.querySelector('[data-toast]');
  let timer;
  const notify = (message) => {
    toast.textContent = message;
    toast.hidden = false;
    window.clearTimeout(timer);
    timer = window.setTimeout(() => { toast.hidden = true; }, 2800);
  };
  const fallbackToggle = page.querySelector('[data-llm-fallback-enabled]');
  const fallbackFields = page.querySelectorAll('[data-llm-fallback-model], [data-llm-fallback-endpoint]');
  const syncFallback = () => fallbackFields.forEach((field) => { field.disabled = !fallbackToggle.checked; });
  fallbackToggle.addEventListener('change', syncFallback);
  syncFallback();
  page.querySelectorAll('[data-test-model]').forEach((button) => {
    button.addEventListener('click', () => {
      const original = button.textContent;
      button.disabled = true;
      button.textContent = '测试中…';
      window.setTimeout(() => {
        button.disabled = false;
        button.textContent = original;
        notify(`${button.dataset.testModel}连接成功，未修改配置。`);
      }, 650);
    });
  });
  page.querySelector('[data-llm-reset]').addEventListener('click', () => {
    page.querySelectorAll('input:not([type="checkbox"]), select').forEach((field) => field.value = field.defaultValue || field.options?.[0]?.value || '');
    fallbackToggle.checked = true;
    syncFallback();
    notify('已放弃本次修改。');
  });
  page.querySelector('[data-llm-save]').addEventListener('click', () => {
    notify('配置已保存并发布，版本号已更新为 CFG-20260824-08。');
  });
});

document.addEventListener('DOMContentLoaded', () => {
  const page = document.querySelector('[data-knowledge-config]');
  if (!page) return;
  const toast = page.querySelector('[data-toast]');
  let timer;
  const notify = (message) => {
    toast.textContent = message;
    toast.hidden = false;
    window.clearTimeout(timer);
    timer = window.setTimeout(() => { toast.hidden = true; }, 2400);
  };
  page.querySelectorAll('[data-runtime-save]').forEach((button) => {
    button.addEventListener('click', () => notify('运行规则已保存，新的配置 revision 已发布。'));
  });
});

document.addEventListener('DOMContentLoaded', () => {
  const page = document.querySelector('[data-system-overview]');
  if (!page) return;
  const toast = page.querySelector('[data-toast]');
  let timer;
  const notify = (message) => {
    toast.textContent = message;
    toast.hidden = false;
    window.clearTimeout(timer);
    timer = window.setTimeout(() => { toast.hidden = true; }, 2400);
  };
  page.querySelectorAll('.overview-range button').forEach((button) => {
    button.addEventListener('click', () => {
      page.querySelectorAll('.overview-range button').forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      notify(`已切换到${button.textContent}统计周期。`);
    });
  });
  page.querySelector('[data-overview-refresh]').addEventListener('click', () => notify('运行概览数据已刷新。'));
});

document.addEventListener('DOMContentLoaded', () => {
  const page = document.querySelector('.qa-page');
  if (!page) return;

  const actionTrigger = page.querySelector('[data-session-actions]');
  const actionMenu = page.querySelector('[data-session-actions-menu]');
  const dialog = page.querySelector('[data-session-dialog]');
  const dialogTitle = page.querySelector('[data-session-dialog-title]');
  const dialogBody = page.querySelector('[data-session-dialog-body]');
  const dialogActions = page.querySelector('[data-session-dialog-actions]');
  const title = page.querySelector('.focus-header h1');
  let activeSession = page.querySelector('.session.active');
  const archivedSessions = ['旧版部署方式'];
  const deletedSessions = ['临时问题记录'];
  const sendButton = page.querySelector('[data-send-question]');
  const questionInput = page.querySelector('#focus-question');
  const runningStatus = page.querySelector('[data-query-running-status]');
  let queryRunning = false;
  const notify = (message) => {
    const toast = document.createElement('div');
    toast.className = 'prototype-toast';
    toast.textContent = message;
    document.body.append(toast);
    window.setTimeout(() => toast.remove(), 2600);
  };

  const closeMenu = () => {
    actionMenu.hidden = true;
    actionTrigger.setAttribute('aria-expanded', 'false');
  };
  const closeDialog = () => {
    dialog.hidden = true;
    document.body.classList.remove('modal-open');
  };
  const button = (label, className = '', action = 'close') => {
    const item = document.createElement('button');
    item.type = 'button';
    item.textContent = label;
    if (className) item.className = className;
    item.dataset.dialogAction = action;
    return item;
  };
  const openDialog = (kind) => {
    closeMenu();
    dialog.hidden = false;
    document.body.classList.add('modal-open');
    dialogActions.innerHTML = '';
    if (kind === 'rename') {
      dialogTitle.textContent = '重命名会话';
      dialogBody.innerHTML = `<label>会话名称<input type="text" maxlength="60" value="${title.textContent.trim()}" data-session-name-input></label>`;
      dialogActions.append(button('取消'), button('保存名称', 'primary-action', 'save-rename'));
      dialog.querySelector('[data-session-name-input]').focus();
      return;
    }
    if (kind === 'export') {
      dialogTitle.textContent = '导出对话';
      dialogBody.innerHTML = '<p>将导出当前会话中的问题、综合答案、结构化信息和来源链接。</p><div class="session-dialog-note">不复制完整原文，只保留答案中的来源名称与可访问链接。</div>';
      dialogActions.append(button('取消'), button('下载 Markdown', 'primary-action', 'export-markdown'));
      return;
    }
    if (kind === 'share') {
      dialogTitle.textContent = '分享会话';
      dialogBody.innerHTML = '<p>生成一个仅供公司内部访问的会话快照。快照包含当前对话和来源链接，不包含知识库原文。</p><div class="session-dialog-note">原会话后续更新不会改变已经生成的分享快照。</div>';
      dialogActions.append(button('取消'), button('生成分享链接', 'primary-action', 'create-share'));
      return;
    }
    if (kind === 'archive') {
      dialogTitle.textContent = '归档会话';
      dialogBody.innerHTML = `<p>确认归档“${title.textContent.trim()}”？归档后不会出现在最近会话列表中，但仍可在全部会话中恢复。</p>`;
      dialogActions.append(button('取消'), button('确认归档', 'primary-action', 'confirm-archive'));
      return;
    }
    if (kind === 'delete') {
      dialogTitle.textContent = '删除会话';
      dialogBody.innerHTML = `<p>确认删除“${title.textContent.trim()}”？删除后会进入回收站，7 天后自动彻底删除。</p><div class="session-dialog-note">删除不会影响已生成的分享快照。</div>`;
      dialogActions.append(button('取消'), button('移入回收站', 'primary-action', 'confirm-delete'));
      return;
    }
    dialogTitle.textContent = '全部会话';
    dialogBody.innerHTML = `<p>这里集中管理当前用户的会话。</p>
      <div class="session-dialog-list">
        <strong>已归档（${archivedSessions.length}）</strong>
        ${archivedSessions.map((item, index) => `<div class="session-dialog-row"><span>${item}</span><button type="button" data-restore-session="${index}">恢复</button></div>`).join('') || '<small>暂无归档会话</small>'}
        <strong>回收站（${deletedSessions.length}）</strong>
        ${deletedSessions.map((item, index) => `<div class="session-dialog-row"><span>${item}</span><button type="button" data-restore-deleted="${index}">恢复</button></div>`).join('') || '<small>回收站为空</small>'}
      </div>
      <div class="session-dialog-note">归档会话可恢复；删除后的会话在回收站保留 7 天。</div>`;
    dialogActions.append(button('关闭'));
  };

  actionTrigger.addEventListener('click', () => {
    actionMenu.hidden = !actionMenu.hidden;
    actionTrigger.setAttribute('aria-expanded', String(!actionMenu.hidden));
  });
  actionMenu.addEventListener('click', (event) => {
    const item = event.target.closest('[data-session-action]');
    if (item) openDialog(item.dataset.sessionAction);
  });
  page.querySelector('[data-session-list]').addEventListener('click', () => openDialog('all'));
  page.querySelector('[data-new-session]').addEventListener('click', () => {
    const session = document.createElement('div');
    session.className = 'session active';
    session.dataset.sessionTitle = '新会话';
    session.textContent = '新会话';
    page.querySelectorAll('.session').forEach((item) => item.classList.remove('active'));
    page.querySelector('[data-session-list]').before(session);
    activeSession = session;
    title.textContent = '新会话';
    notify('已创建新会话，可以开始提问。');
  });
  page.querySelector('.focus-nav').addEventListener('click', (event) => {
    const session = event.target.closest('.session');
    if (!session) return;
    page.querySelectorAll('.session').forEach((item) => item.classList.remove('active'));
    session.classList.add('active');
    activeSession = session;
    title.textContent = session.dataset.sessionTitle || session.textContent.trim();
  });
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog || event.target.closest('[data-session-dialog-close]')) closeDialog();
    const action = event.target.closest('[data-dialog-action]')?.dataset.dialogAction;
    if (!action) return;
    if (action === 'close') closeDialog();
    if (action === 'save-rename') {
      const value = dialog.querySelector('[data-session-name-input]').value.trim();
      if (!value) return;
      title.textContent = value;
      if (activeSession) { activeSession.textContent = value; activeSession.dataset.sessionTitle = value; }
      closeDialog();
      notify('会话名称已更新。');
    }
    if (action === 'export-markdown') {
      const markdown = `# ${title.textContent.trim()}\n\n## 问题\nT90000 的 CPU、内存和磁盘配置是什么？\n\n## 综合答案\nT90000 采用 AMD EPYC 7H12，配置 256GB 内存和 16TB 磁盘。\n\n## 来源\n- AE 硬件规格：当前型号规格，更新于 2026-08-12`;
      const link = document.createElement('a');
      link.href = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }));
      link.download = `${title.textContent.trim() || '知识问答会话'}.md`;
      link.click();
      URL.revokeObjectURL(link.href);
      closeDialog();
      notify('对话已导出为 Markdown。');
    }
    if (action === 'create-share') {
      navigator.clipboard?.writeText('https://knowledge.ae.local/share/CONV-20260820-0036').catch(() => {});
      closeDialog();
      notify('分享链接已生成并复制。');
    }
    if (action === 'confirm-archive') {
      archivedSessions.push(title.textContent.trim());
      activeSession?.remove();
      const first = page.querySelector('.session');
      if (first) { first.classList.add('active'); activeSession = first; title.textContent = first.dataset.sessionTitle || first.textContent.trim(); }
      closeDialog();
      notify('会话已归档，可在全部会话中恢复。');
    }
    if (action === 'confirm-delete') {
      deletedSessions.push(title.textContent.trim());
      activeSession?.remove();
      const first = page.querySelector('.session');
      if (first) { first.classList.add('active'); activeSession = first; title.textContent = first.dataset.sessionTitle || first.textContent.trim(); }
      closeDialog();
      notify('会话已移入回收站，7 天内可以恢复。');
    }
  });
  dialog.addEventListener('click', (event) => {
    const restoreArchived = event.target.closest('[data-restore-session]');
    const restoreDeleted = event.target.closest('[data-restore-deleted]');
    if (restoreArchived) {
      const index = Number(restoreArchived.dataset.restoreSession);
      const restored = archivedSessions.splice(index, 1)[0];
      if (restored) notify(`已恢复会话“${restored}”。`);
      openDialog('all');
    }
    if (restoreDeleted) {
      const index = Number(restoreDeleted.dataset.restoreDeleted);
      const restored = deletedSessions.splice(index, 1)[0];
      if (restored) notify(`已从回收站恢复“${restored}”。`);
      openDialog('all');
    }
  });
  document.addEventListener('click', (event) => {
    if (!actionTrigger.contains(event.target) && !actionMenu.contains(event.target)) closeMenu();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { closeMenu(); if (!dialog.hidden) closeDialog(); }
  });
  sendButton.addEventListener('click', () => {
    if (queryRunning) {
      notify('当前会话已有回答生成中，请等待完成后再发送。');
      return;
    }
    if (!questionInput.value.trim()) {
      notify('请输入问题后再发送。');
      questionInput.focus();
      return;
    }
    queryRunning = true;
    sendButton.disabled = true;
    runningStatus.hidden = false;
    notify('问题已提交，正在生成回答。');
    window.setTimeout(() => {
      queryRunning = false;
      sendButton.disabled = false;
      runningStatus.hidden = true;
      questionInput.value = '';
      notify('回答生成完成。');
    }, 1500);
  });
});

document.querySelectorAll('[data-chip]').forEach((chip) => {
  chip.addEventListener('click', () => chip.classList.toggle('selected'));
});

document.querySelectorAll('[data-feedback]').forEach((button) => {
  button.addEventListener('click', () => {
    const group = button.closest('.feedback');
    group.querySelectorAll('button').forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
  });
});

document.querySelectorAll('[data-source-toggle]').forEach((button) => {
  button.addEventListener('click', () => {
    const body = button.nextElementSibling;
    body.classList.toggle('open');
    button.setAttribute('aria-expanded', String(body.classList.contains('open')));
  });
});

document.querySelectorAll('.evidence-tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    tab.parentElement.querySelectorAll('.evidence-tab').forEach((item) => item.classList.remove('active'));
    tab.classList.add('active');
  });
});

document.querySelectorAll('.session').forEach((session) => {
  session.addEventListener('click', () => {
    session.parentElement.querySelectorAll('.session').forEach((item) => item.classList.remove('active'));
    session.classList.add('active');
  });
});

document.querySelectorAll('[data-scope-composer]').forEach((composer) => {
  const trigger = composer.querySelector('[data-scope-trigger]');
  const panel = composer.querySelector('[data-scope-panel]');
  const product = composer.querySelector('[data-scope-product]');
  const version = composer.querySelector('[data-scope-version]');
  const documentType = composer.querySelector('[data-scope-document-type]');
  const activeScope = composer.querySelector('[data-active-scope]');
  const clear = composer.querySelector('[data-scope-clear]');
  const more = composer.querySelector('[data-scope-more]');
  const advanced = composer.querySelector('[data-scope-advanced]');
  const hint = composer.querySelector('[data-scope-hint]');

  const versionsByProduct = {
    AE: ['7.0.3', '7.0.2', '7.0'],
    TDA: ['7.0.3', '7.0.1', '6.5']
  };

  const setPanelOpen = (open) => {
    panel.hidden = !open;
    trigger.setAttribute('aria-expanded', String(open));
  };

  const setVersionOptions = (productValue, preserveValue = '') => {
    const options = productValue ? versionsByProduct[productValue] : [];
    version.innerHTML = '';
    const defaultOption = document.createElement('option');
    defaultOption.value = '';
    defaultOption.textContent = productValue ? '全部版本' : '请先选择产品';
    version.append(defaultOption);
    options.forEach((item) => {
      const option = document.createElement('option');
      option.value = item;
      option.textContent = item;
      version.append(option);
    });
    version.disabled = !productValue;
    version.value = options.includes(preserveValue) ? preserveValue : '';
  };

  const renderScope = () => {
    const values = [
      { key: 'product', label: '产品', value: product.value },
      { key: 'version', label: '版本', value: version.value },
      { key: 'documentType', label: '文档类型', value: documentType.value }
    ].filter((item) => item.value);

    activeScope.innerHTML = '';
    values.forEach((item) => {
      const chip = document.createElement('button');
      chip.type = 'button';
      chip.className = 'scope-chip';
      chip.dataset.scopeRemove = item.key;
      chip.setAttribute('aria-label', `移除${item.label}条件：${item.value}`);
      chip.textContent = `${item.label}：${item.value}`;
      activeScope.append(chip);
    });

    trigger.textContent = values.length ? `检索范围：${values.length} 项` : '检索范围：全部知识';
  };

  trigger.addEventListener('click', () => {
    setPanelOpen(panel.hidden);
  });

  more.addEventListener('click', () => {
    const open = advanced.hidden;
    advanced.hidden = !open;
    more.setAttribute('aria-expanded', String(open));
  });

  product.addEventListener('change', () => {
    const previousVersion = version.value;
    setVersionOptions(product.value, previousVersion);
    hint.classList.toggle('notice', Boolean(previousVersion && !version.value));
    hint.textContent = previousVersion && !version.value
      ? '产品已变更，原版本不适用于新产品，系统已清除该版本。'
      : '所选条件将在当前会话的后续提问中保持生效。';
    renderScope();
  });

  version.addEventListener('change', renderScope);
  documentType.addEventListener('change', renderScope);

  clear.addEventListener('click', () => {
    product.value = '';
    documentType.value = '';
    setVersionOptions('');
    hint.classList.remove('notice');
    hint.textContent = '所选条件将在当前会话的后续提问中保持生效。';
    renderScope();
  });

  activeScope.addEventListener('click', (event) => {
    const chip = event.target.closest('[data-scope-remove]');
    if (!chip) return;
    if (chip.dataset.scopeRemove === 'product') {
      product.value = '';
      setVersionOptions('');
    }
    if (chip.dataset.scopeRemove === 'version') version.value = '';
    if (chip.dataset.scopeRemove === 'documentType') documentType.value = '';
    renderScope();
  });

  document.addEventListener('click', (event) => {
    if (!composer.contains(event.target)) setPanelOpen(false);
  });

  composer.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      setPanelOpen(false);
      trigger.focus();
    }
  });

  setVersionOptions('');
  renderScope();
});

document.querySelectorAll('[data-import-review]').forEach((review) => {
  const documentCatalog = [
    {
      title: '离线更新操作指导文档',
      kind: '飞书文档',
      location: '云盘',
      updated: '2026-07-29 15:00',
      link: 'https://asiainfo-sec.feishu.cn/docx/DhTBdLmFPod8GRxQOoccHZUYnAb',
      suggestedCategory: '部署文档',
      category: '部署文档',
      product: '',
      versionScope: 'all',
      major: '',
      minor: '',
      note: '',
      status: 'pending'
    },
    {
      title: 'AE硬件平台故障汇总',
      kind: '飞书文档',
      location: '我的文档库',
      updated: '2026-06-10 14:31',
      link: 'https://asiainfo-sec.feishu.cn/wiki/GPzFw3yg2ibKKUkQPhGc7ZMwnOd',
      suggestedCategory: 'SEG 案件',
      category: 'SEG 案件',
      product: '',
      versionScope: 'all',
      major: '',
      minor: '',
      note: '',
      status: 'pending'
    },
    {
      title: 'PXW故障技术分析报告',
      kind: '飞书文档',
      location: '云盘',
      updated: '2026-07-30 14:17',
      link: 'https://asiainfo-sec.feishu.cn/docx/HWdxdQaWKoDl99xTWLXcphMcnWf',
      suggestedCategory: 'SEG 案件',
      category: 'SEG 案件',
      product: '',
      versionScope: 'all',
      major: '',
      minor: '',
      note: '',
      status: 'pending'
    },
    {
      title: 'AE-现场故障日志.docx',
      kind: '本地文件',
      location: '本地选择',
      updated: '刚刚',
      link: '#',
      suggestedCategory: 'SEG 案件',
      category: 'SEG 案件',
      product: '',
      versionScope: 'all',
      major: '',
      minor: '',
      note: '',
      status: 'pending'
    },
    {
      title: 'AE-部署说明.pdf',
      kind: '本地文件',
      location: '本地选择',
      updated: '刚刚',
      link: '#',
      suggestedCategory: '部署文档',
      category: '部署文档',
      product: '',
      versionScope: 'all',
      major: '',
      minor: '',
      note: '',
      status: 'pending'
    }
  ];
  let documents = documentCatalog.map((item) => ({ ...item }));

  const versions = {
    AE: {
      V7: ['7.0.3', '7.0.2', '7.0.1'],
      V6: ['6.5.2', '6.5.1']
    },
    TDA: {
      V7: ['7.0.3', '7.0.1'],
      V6: ['6.5.0']
    }
  };

  const queue = review.querySelector('[data-document-queue]');
  const queueProgress = review.querySelector('[data-queue-progress]');
  const queueTotal = review.querySelector('[data-queue-total]');
  const reviewUploadCount = review.querySelector('[data-review-upload-count]');
  const currentPosition = review.querySelector('[data-current-position]');
  const title = review.querySelector('[data-document-title]');
  const kind = review.querySelector('[data-document-kind]');
  const location = review.querySelector('[data-document-location]');
  const updated = review.querySelector('[data-document-updated]');
  const sourceLink = review.querySelector('[data-document-link]');
  const status = review.querySelector('[data-review-status]');
  const form = review.querySelector('[data-classification-form]');
  const category = review.querySelector('[data-category]');
  const editCategory = review.querySelector('[data-edit-category]');
  const categoryHelp = review.querySelector('[data-category-help]');
  const product = review.querySelector('[data-import-product]');
  const major = review.querySelector('[data-major-version]');
  const minor = review.querySelector('[data-minor-version]');
  const note = review.querySelector('[data-version-note]');
  const versionScope = review.querySelector('[data-version-scope]');
  const versionRequired = review.querySelectorAll('[data-version-required]');
  const formError = review.querySelector('[data-form-error]');
  const saveDraft = review.querySelector('[data-save-draft]');
  const confirmButton = review.querySelector('[data-confirm-index]');
  const retryCurrent = review.querySelector('[data-review-retry]');
  const cancelCurrent = review.querySelector('[data-review-cancel]');
  const toast = document.querySelector('[data-toast]');
  let currentIndex = 0;
  let toastTimer;

  const showToast = (message) => {
    window.clearTimeout(toastTimer);
    toast.textContent = message;
    toast.hidden = false;
    toastTimer = window.setTimeout(() => { toast.hidden = true; }, 2200);
  };

  const populateMajorVersions = (productValue, selected = '') => {
    major.innerHTML = '<option value="">请选择大版本</option>';
    Object.keys(versions[productValue] || {}).forEach((item) => {
      const option = document.createElement('option');
      option.value = item;
      option.textContent = item;
      major.append(option);
    });
    major.disabled = !productValue;
    major.value = selected && versions[productValue]?.[selected] ? selected : '';
  };

  const populateMinorVersions = (productValue, majorValue, selected = '') => {
    const available = versions[productValue]?.[majorValue] || [];
    minor.innerHTML = '<option value="">请选择小版本</option>';
    available.forEach((item) => {
      const option = document.createElement('option');
      option.value = item;
      option.textContent = item;
      minor.append(option);
    });
    minor.disabled = !majorValue;
    minor.value = available.includes(selected) ? selected : '';
  };

  const applyVersionScope = (value) => {
    const specific = value === 'specific';
    versionScope.querySelectorAll('button').forEach((button) => {
      const active = button.dataset.scopeValue === value;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    major.disabled = !specific || !product.value;
    minor.disabled = !specific || !major.value;
    major.required = specific;
    minor.required = specific;
    versionRequired.forEach((marker) => { marker.hidden = !specific; });
  };

  const saveCurrentForm = () => {
    const item = documents[currentIndex];
    if (!item) return;
    item.category = category.value;
    item.product = product.value;
    item.versionScope = versionScope.querySelector('.active')?.dataset.scopeValue || 'all';
    item.major = item.versionScope === 'specific' ? major.value : '';
    item.minor = item.versionScope === 'specific' ? minor.value : '';
    item.note = note.value.trim();
  };

  const renderQueue = () => {
    queue.innerHTML = '';
    const stateMap = {
      confirmed: { className: 'confirmed', text: '已入库', number: '✓' },
      duplicate: { className: 'duplicate', text: '重复跳过', number: '!' },
      failed: { className: 'failed', text: '处理失败', number: '!' },
      processing: { className: 'processing', text: '处理中', number: '…' },
      cancelled: { className: 'cancelled', text: '已取消', number: '–' },
      pending: { className: 'agent', text: '待补充条件' },
    };
    documents.forEach((item, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      const state = stateMap[item.status] || stateMap.pending;
      button.className = `queue-item${index === currentIndex ? ' active' : ''}${item.status !== 'pending' ? ` ${item.status}` : ''}`;
      button.innerHTML = `
        <span class="queue-number">${state.number || index + 1}</span>
        <span>
          <span class="queue-title">${item.title}</span>
          <span class="queue-meta"><span class="queue-state ${state.className}">${state.text}</span>${item.kind}</span>
        </span>`;
      button.addEventListener('click', () => {
        saveCurrentForm();
        currentIndex = index;
        loadCurrentDocument();
      });
      queue.append(button);
    });
    const confirmedCount = documents.filter((item) => item.status === 'confirmed').length;
    const issueCount = documents.filter((item) => ['duplicate', 'failed'].includes(item.status)).length;
    queueProgress.textContent = issueCount
      ? `${confirmedCount} / ${documents.length} 已入库 · ${issueCount} 项需处理`
      : `${confirmedCount} / ${documents.length} 已入库`;
    queueTotal.textContent = `${documents.length} 个文档`;
    reviewUploadCount.textContent = `已上传 ${documents.length} 个飞书文档`;
  };

  const renderStatus = (item) => {
    const confirmed = item.status === 'confirmed';
    const duplicate = item.status === 'duplicate';
    const failed = item.status === 'failed';
    const processing = item.status === 'processing';
    const cancelled = item.status === 'cancelled';
    const locked = confirmed || duplicate || failed || processing || cancelled;
    status.classList.toggle('confirmed', confirmed);
    status.classList.toggle('classified', !confirmed && !duplicate && !failed && !processing);
    status.classList.toggle('duplicate', duplicate);
    status.classList.toggle('failed', failed);
    status.classList.toggle('processing', processing);
    status.classList.toggle('cancelled', cancelled);
    status.querySelector('.status-icon').textContent = confirmed ? '✓' : (processing ? '…' : (cancelled ? '–' : '!'));
    status.querySelector('strong').textContent = confirmed
      ? '当前状态：已入库，正在建立检索索引'
      : duplicate
        ? '当前状态：发现重复文档，已跳过入库'
        : failed
          ? '当前状态：处理失败，需要重试'
          : processing
            ? '当前状态：正在解析并建立索引'
            : cancelled
              ? '当前状态：任务已取消'
            : '当前状态：自动分类完成，等待补充检索条件';
    status.querySelector('p').textContent = confirmed
      ? '检索条件已经提交；索引完成后可用于知识问答。'
      : duplicate
        ? '系统已找到相同来源的已入库文档，当前文档不会重复建立索引。'
        : failed
          ? (item.error || '文档解析或索引失败，修复来源后可以再次重试。')
          : processing
            ? '系统正在处理文档内容，请稍候。'
            : cancelled
              ? '当前文档未继续处理，可以返回文档列表后重新提交。'
            : '文档分类已经由系统写入；补充产品和版本后即可建立检索索引。';
    confirmButton.disabled = locked;
    confirmButton.textContent = confirmed ? '已提交入库' : '保存检索条件并入库';
    saveDraft.disabled = locked;
    category.disabled = locked || editCategory.dataset.editing !== 'true';
    product.disabled = locked;
    note.disabled = locked;
    editCategory.disabled = locked;
    versionScope.querySelectorAll('button').forEach((button) => { button.disabled = locked; });
    retryCurrent.hidden = !failed;
    cancelCurrent.hidden = !processing;
  };

  const loadCurrentDocument = () => {
    const item = documents[currentIndex];
    if (!item) return;
    currentPosition.textContent = `${currentIndex + 1} / ${documents.length}`;
    title.textContent = item.title;
    kind.textContent = item.kind;
    location.textContent = item.location;
    updated.textContent = `更新于 ${item.updated}`;
    sourceLink.href = item.link;
    sourceLink.target = '_blank';
    sourceLink.rel = 'noreferrer';
    category.value = item.category;
    categoryHelp.textContent = `分类器根据文档内容识别为“${item.suggestedCategory}”。`;
    editCategory.dataset.editing = 'false';
    editCategory.textContent = '修改分类';
    category.disabled = true;
    product.value = item.product;
    populateMajorVersions(item.product, item.major);
    populateMinorVersions(item.product, item.major, item.minor);
    note.value = item.note;
    applyVersionScope(item.versionScope);
    formError.hidden = true;
    renderStatus(item);
    renderQueue();
  };

  versionScope.addEventListener('click', (event) => {
    const button = event.target.closest('[data-scope-value]');
    if (!button) return;
    applyVersionScope(button.dataset.scopeValue);
    if (button.dataset.scopeValue === 'all') {
      major.value = '';
      populateMinorVersions('', '');
    }
    formError.hidden = true;
  });

  product.addEventListener('change', () => {
    populateMajorVersions(product.value);
    populateMinorVersions('', '');
    applyVersionScope(versionScope.querySelector('.active')?.dataset.scopeValue || 'all');
    formError.hidden = true;
  });

  major.addEventListener('change', () => {
    populateMinorVersions(product.value, major.value);
    applyVersionScope(versionScope.querySelector('.active')?.dataset.scopeValue || 'all');
    formError.hidden = true;
  });

  [category, minor].forEach((field) => field.addEventListener('change', () => { formError.hidden = true; }));

  editCategory.addEventListener('click', () => {
    if (editCategory.disabled) return;
    const editing = editCategory.dataset.editing !== 'true';
    editCategory.dataset.editing = String(editing);
    editCategory.textContent = editing ? '完成修改' : '修改分类';
    category.disabled = !editing;
    if (editing) category.focus();
  });

  saveDraft.addEventListener('click', () => {
    if (saveDraft.disabled) return;
    saveCurrentForm();
    renderQueue();
    showToast('已保存当前检索条件；文档仍未进入检索索引。');
  });

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    saveCurrentForm();
    const item = documents[currentIndex];
    const valid = Boolean(item.category && item.product && (
      item.versionScope === 'all' || (item.major && item.minor)
    ));
    formError.hidden = valid;
    if (!valid) return;

    item.status = 'confirmed';
    renderStatus(item);
    renderQueue();
    showToast('检索条件保存成功，文档已进入索引任务。');

    const nextPending = documents.findIndex((candidate, index) => (
      candidate.status !== 'confirmed' && index > currentIndex
    ));
    const fallbackPending = documents.findIndex((candidate) => candidate.status !== 'confirmed');
    const nextIndex = nextPending >= 0 ? nextPending : fallbackPending;
    if (nextIndex >= 0) {
      window.setTimeout(() => {
        currentIndex = nextIndex;
        loadCurrentDocument();
      }, 650);
    }
  });

  retryCurrent.addEventListener('click', () => {
    const item = documents[currentIndex];
    if (!item || item.status !== 'failed') return;
    item.status = 'processing';
    renderStatus(item);
    renderQueue();
    showToast('已重新提交处理任务。');
    window.setTimeout(() => {
      item.status = 'pending';
      item.error = '';
      renderStatus(item);
      renderQueue();
      showToast('重试成功，请补充检索条件。');
    }, 700);
  });

  cancelCurrent.addEventListener('click', () => {
    const item = documents[currentIndex];
    if (!item || item.status !== 'processing') return;
    item.status = 'cancelled';
    renderStatus(item);
    renderQueue();
    showToast('已取消当前处理任务。');
  });

  review.startImport = (selectedTitles, demoState = 'normal') => {
    documents = documentCatalog
      .filter((item) => selectedTitles.includes(item.title))
      .map((item) => ({ ...item, status: 'pending' }));
    if (demoState === 'mixed') {
      if (documents[1]) documents[1] = { ...documents[1], status: 'duplicate' };
      if (documents[2]) documents[2] = { ...documents[2], status: 'failed', error: '正文解析失败：飞书文档内容暂时不可读取。' };
    }
    if (demoState === 'all-duplicate') documents = documents.map((item) => ({ ...item, status: 'duplicate' }));
    if (demoState === 'progress') documents = documents.map((item) => ({ ...item, status: 'processing' }));
    if (demoState === 'cancel' && documents[0]) documents[0] = { ...documents[0], status: 'processing' };
    currentIndex = 0;
    loadCurrentDocument();
    if (demoState === 'progress') {
      window.setTimeout(() => {
        documents = documents.map((item) => item.status === 'processing' ? { ...item, status: 'pending' } : item);
        loadCurrentDocument();
        showToast('解析阶段已完成，请补充检索条件。');
      }, 1200);
    }
  };

  loadCurrentDocument();
});

document.querySelectorAll('[data-document-import]').forEach((page) => {
  const uploadStage = page.querySelector('[data-upload-stage]');
  const reviewStage = page.querySelector('[data-review-stage]');
  const checkboxes = Array.from(page.querySelectorAll('[data-upload-select]'));
  const selectAll = page.querySelector('[data-upload-select-all]');
  const selection = page.querySelector('[data-upload-selection]');
  const uploadButton = page.querySelector('[data-upload-selected]');
  const localUploadButton = page.querySelector('[data-local-upload]');
  const backButton = page.querySelector('[data-back-upload]');
  const keyword = page.querySelector('[data-document-keyword]');
  const searchButton = page.querySelector('[data-document-search]');
  const clearButton = page.querySelector('[data-document-clear]');
  const refreshButton = page.querySelector('[data-refresh-documents]');
  const demoState = page.querySelector('[data-import-demo-state]');
  const uploadAlert = page.querySelector('[data-upload-alert]');
  const uploadAlertTitle = page.querySelector('[data-upload-alert-title]');
  const uploadAlertCopy = page.querySelector('[data-upload-alert-copy]');
  const uploadAlertAction = page.querySelector('[data-upload-alert-action]');
  const resultBanner = page.querySelector('[data-import-result-banner]');
  const resultTitle = page.querySelector('[data-import-result-title]');
  const resultCopy = page.querySelector('[data-import-result-copy]');
  const resultRetry = page.querySelector('[data-import-result-retry]');
  const rows = Array.from(page.querySelectorAll('[data-upload-row]'));
  const toast = document.querySelector('[data-toast]');
  let toastTimer;
  let localMode = false;
  let pasteMode = false;
  let demoTimer;
  const localTitles = ['AE-现场故障日志.docx', 'AE-部署说明.pdf'];

  const showToast = (message) => {
    window.clearTimeout(toastTimer);
    toast.textContent = message;
    toast.hidden = false;
    toastTimer = window.setTimeout(() => { toast.hidden = true; }, 2200);
  };

  const selectedDocuments = () => checkboxes.filter((checkbox) => checkbox.checked);

  const setUploadAlert = (mode) => {
    const messages = {
      auth: {
        title: '飞书授权已过期',
        copy: '无法读取最新文档列表，请重新授权后再继续。',
        action: '重新授权',
      },
      empty: {
        title: '没有可选文档',
        copy: '当前目录没有可上传的飞书文档，请切换目录或重新获取列表。',
        action: '',
      },
      search: {
        title: '未找到匹配文档',
        copy: '当前筛选条件没有匹配的飞书文档，请调整关键词或时间范围。',
        action: '',
      },
      rate: {
        title: '请求过于频繁',
        copy: '飞书接口暂时限流，请稍后重试。系统不会重复提交当前选择。',
        action: '稍后重试',
      },
      format: {
        title: '文件格式不支持',
        copy: '检测到不支持的本地文件格式，仅支持 DOCX、PDF 和 XLSX。',
        action: '',
      },
      sha: {
        title: '检测到重复文件',
        copy: '文件 SHA-256 与已有文档一致，系统将跳过重复上传。',
        action: '查看已有文档',
      },
      local: {
        title: '已选择 2 个本地文件',
        copy: '支持批量上传；文件将先解析，再由分类 Agent 自动判断文档分类。',
        action: '',
      },
      unbound: {
        title: '尚未连接飞书',
        copy: '连接飞书后才能扫描和选择个人可访问的云文档。',
        action: '去连接飞书',
      },
      loading: {
        title: '正在获取飞书文档',
        copy: '首次加载可能需要几秒钟，请不要重复提交。',
        action: '',
      },
      paste: {
        title: '已识别飞书文档链接',
        copy: '文档链接有效，提交后将读取文档内容并进入自动分类流程。',
        action: '',
      },
    };
    const message = messages[mode];
    uploadAlert.hidden = !message;
    if (!message) return;
    uploadAlertTitle.textContent = message.title;
    uploadAlertCopy.textContent = message.copy;
    uploadAlertAction.textContent = message.action;
    uploadAlertAction.hidden = !message.action;
  };

  const applyDemoState = () => {
    const mode = demoState.value;
    localMode = mode === 'local';
    pasteMode = mode === 'paste';
    const unavailable = ['auth', 'empty', 'search', 'rate', 'format', 'sha', 'unbound', 'loading'].includes(mode);
    setUploadAlert(mode);
    rows.forEach((row) => {
      row.hidden = mode === 'search' || mode === 'empty';
      const checkbox = row.querySelector('[data-upload-select]');
      if (!checkbox) return;
      checkbox.disabled = unavailable || localMode;
      if (unavailable || localMode) checkbox.checked = false;
    });
    selectAll.disabled = unavailable || localMode;
    refreshButton.disabled = mode === 'auth' || mode === 'rate';
    localUploadButton.disabled = mode === 'auth' || mode === 'rate';
    uploadButton.textContent = localMode ? '⇧ 上传本地文件' : (pasteMode ? '⇧ 导入链接文档' : '⇧ 上传选中文档');
    renderSelection();
    window.clearTimeout(demoTimer);
    if (mode === 'loading') {
      demoTimer = window.setTimeout(() => {
        demoState.value = 'normal';
        applyDemoState();
        showToast('飞书文档列表加载完成。');
      }, 1200);
    }
  };

  const renderSelection = () => {
    const selected = selectedDocuments();
    selection.textContent = localMode ? '已选择 2 个本地文件' : (pasteMode ? '已识别 1 个飞书文档' : `已选择 ${selected.length} 个文档`);
    uploadButton.disabled = (localMode || pasteMode) ? false : selected.length === 0 || ['auth', 'empty', 'search', 'rate', 'format', 'sha', 'unbound', 'loading'].includes(demoState.value);
    selectAll.checked = selected.length === checkboxes.length && checkboxes.length > 0;
    selectAll.indeterminate = selected.length > 0 && selected.length < checkboxes.length;
    checkboxes.forEach((checkbox) => {
      checkbox.closest('tr').classList.toggle('selected', checkbox.checked);
    });
  };

  checkboxes.forEach((checkbox) => checkbox.addEventListener('change', renderSelection));

  selectAll.addEventListener('change', () => {
    checkboxes.forEach((checkbox) => { checkbox.checked = selectAll.checked; });
    renderSelection();
  });

  const filterRows = () => {
    const value = keyword.value.trim().toLowerCase();
    rows.forEach((row) => {
      row.hidden = Boolean(value && !row.dataset.title.toLowerCase().includes(value));
    });
  };

  searchButton.addEventListener('click', () => {
    filterRows();
    if (keyword.value.trim()) {
      demoState.value = 'search';
      applyDemoState();
    }
  });
  keyword.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      filterRows();
    }
  });

  clearButton.addEventListener('click', () => {
    keyword.value = '';
    demoState.value = 'normal';
    rows.forEach((row) => { row.hidden = false; });
    applyDemoState();
  });

  page.querySelector('[data-paste-link]').addEventListener('click', () => {
    demoState.value = 'paste';
    applyDemoState();
    showToast('已模拟识别飞书文档链接。');
  });

  refreshButton.addEventListener('click', () => {
    if (demoState.value === 'auth') {
      setUploadAlert('auth');
      return;
    }
    if (demoState.value === 'rate') {
      setUploadAlert('rate');
      return;
    }
    showToast('已获取最新飞书文档，列表更新时间为刚刚。');
  });

  localUploadButton.addEventListener('click', () => {
    demoState.value = 'local';
    applyDemoState();
    showToast('已模拟选择 2 个本地文件。');
  });

  uploadAlertAction.addEventListener('click', () => {
    demoState.value = 'normal';
    applyDemoState();
    showToast('授权成功，已恢复文档读取。');
  });

  uploadButton.addEventListener('click', () => {
    const selectedTitles = localMode
      ? localTitles
      : (pasteMode ? ['离线更新操作指导文档'] : selectedDocuments().map((checkbox) => checkbox.value));
    if (!selectedTitles.length) return;
    const mode = demoState.value;
    uploadButton.disabled = true;
    uploadButton.textContent = '正在上传并自动分类…';
    window.setTimeout(() => {
      reviewStage.startImport(selectedTitles, mode);
      uploadStage.hidden = true;
      reviewStage.hidden = false;
      uploadButton.textContent = '⇧ 上传选中文档';
      renderSelection();
      showToast(mode === 'progress' ? '文件上传完成，正在进入解析阶段。' : '文档上传并自动分类完成，请补充检索条件。');
      if (mode === 'mixed' || mode === 'all-duplicate' || mode === 'format' || mode === 'sha' || mode === 'progress' || mode === 'cancel') {
        resultBanner.hidden = false;
        resultTitle.textContent = mode === 'all-duplicate' ? '本次导入全部重复' : mode === 'progress' ? '上传完成，解析处理中' : mode === 'cancel' ? '任务正在处理中' : '本次导入存在部分结果';
        resultCopy.textContent = mode === 'all-duplicate'
          ? '所有文档均已在知识库中找到相同来源，未重复建立索引。'
          : mode === 'progress'
            ? '上传阶段已完成，解析、分类和索引阶段正在继续。'
            : mode === 'cancel'
              ? '可以在当前文档状态区域取消单项任务。'
              : '请根据左侧队列处理重复、失败或待补充条件的文档。';
        resultRetry.hidden = mode !== 'mixed';
      } else {
        resultBanner.hidden = true;
        resultRetry.hidden = true;
      }
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }, 650);
  });

  resultRetry.addEventListener('click', () => {
    const failedItem = reviewStage.querySelector('.queue-item.failed');
    if (!failedItem) return;
    failedItem.click();
    const retryButton = reviewStage.querySelector('[data-review-retry]');
    retryButton.click();
    resultRetry.hidden = true;
    resultCopy.textContent = '失败项已重新提交处理，处理完成后请补充检索条件。';
    showToast('失败项已重新提交处理。');
  });

  backButton.addEventListener('click', () => {
    reviewStage.hidden = true;
    uploadStage.hidden = false;
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  demoState.addEventListener('change', applyDemoState);
  applyDemoState();
});

document.querySelectorAll('[data-knowledge-documents]').forEach((page) => {
  const statusLabels = {
    available: '可检索',
    processing: '处理中',
    pending: '待补充条件',
    failed: '处理失败',
    withdrawn: '已撤回',
    indexing: '索引中',
  };
  const processingLabels = {
    available: '解析、切片和索引均已完成，当前文档可参与知识问答。',
    processing: '正在解析文档内容并执行自动分类，请稍后查看。',
    pending: '自动分类已完成；补充产品和版本后才能进入检索索引。',
    failed: '本次处理未完成，可在修复原因后重新发起处理。',
    withdrawn: '提交者已撤回该文档，当前不会参与知识问答。',
    indexing: '分类和检索条件已保存，正在建立检索索引。',
  };
  const documents = [
    {
      id: 1,
      title: '离线更新操作指导文档',
      source: 'feishu',
      sourceLabel: '飞书文档',
      category: '部署文档',
      product: 'AE',
      version: 'V7 / 7.0.3',
      status: 'available',
      updated: '2026-08-18 02:03',
      submitter: '薛文李',
      owner: true,
      fileType: 'DOCX',
      link: 'https://asiainfo-sec.feishu.cn/docx/MaIdd4JTPoTiTfxZPMMcjU4TnWc',
    },
    {
      id: 2,
      title: 'AE 硬件平台故障汇总',
      source: 'feishu',
      sourceLabel: '飞书文档',
      category: 'SEG 案件',
      product: 'AE',
      version: '全部版本',
      status: 'processing',
      updated: '2026-08-18 01:42',
      submitter: '薛文李',
      owner: true,
      fileType: 'WIKI',
      link: 'https://asiainfo-sec.feishu.cn/wiki/ZPK3wEWCDifnUhkz0VBcJnbWnCe',
    },
    {
      id: 3,
      title: 'T90000 硬件规格',
      source: 'local',
      sourceLabel: '本地文件',
      category: '产品规格',
      product: 'AE',
      version: '全部版本',
      status: 'available',
      updated: '2026-08-17 16:28',
      submitter: '王强',
      owner: false,
      fileType: 'PDF',
      link: '',
    },
    {
      id: 4,
      title: 'PXW 故障技术分析报告',
      source: 'feishu',
      sourceLabel: '飞书文档',
      category: 'SEG 案件',
      product: 'AE',
      version: 'V7 / 7.0.3',
      status: 'failed',
      updated: '2026-08-17 15:06',
      submitter: '薛文李',
      owner: true,
      fileType: 'DOCX',
      link: 'https://asiainfo-sec.feishu.cn/wiki/HjxUwL7EDigfbxkxvPJcr6man2e',
      error: '文档解析失败：嵌入图片下载超时。本任务已自动重试 3 次。',
    },
    {
      id: 5,
      title: 'TDA 7.0.3 产品白皮书',
      source: 'local',
      sourceLabel: '本地文件',
      category: '白皮书',
      product: 'TDA',
      version: 'V7 / 7.0.3',
      status: 'available',
      updated: '2026-08-16 11:21',
      submitter: '李敏',
      owner: false,
      fileType: 'WORD',
      link: '',
    },
    {
      id: 6,
      title: '网桥部署说明',
      source: 'feishu',
      sourceLabel: '飞书文档',
      category: '部署文档',
      product: '',
      version: '',
      status: 'pending',
      updated: '2026-08-16 09:10',
      submitter: '薛文李',
      owner: true,
      fileType: 'WIKI',
      link: 'https://asiainfo-sec.feishu.cn/wiki/ZPK3wEWCDifnUhkz0VBcJnbWnCe',
    },
  ];

  const rows = page.querySelector('[data-kd-rows]');
  const empty = page.querySelector('[data-kd-empty]');
  const resultCount = page.querySelector('[data-kd-result-count]');
  const statusButtons = Array.from(page.querySelectorAll('[data-document-status]'));
  const keyword = page.querySelector('[data-kd-keyword]');
  const source = page.querySelector('[data-kd-source]');
  const category = page.querySelector('[data-kd-category]');
  const product = page.querySelector('[data-kd-product]');
  const searchButton = page.querySelector('[data-kd-search]');
  const clearButton = page.querySelector('[data-kd-clear]');
  const drawer = document.querySelector('[data-document-drawer]');
  const backdrop = document.querySelector('[data-document-drawer-backdrop]');
  const drawerClose = drawer.querySelector('[data-drawer-close]');
  const drawerTitle = drawer.querySelector('[data-drawer-title]');
  const drawerStatus = drawer.querySelector('[data-drawer-status]');
  const drawerSource = drawer.querySelector('[data-drawer-source]');
  const drawerSubmitter = drawer.querySelector('[data-drawer-submitter]');
  const drawerUpdated = drawer.querySelector('[data-drawer-updated]');
  const drawerSourceLink = drawer.querySelector('[data-drawer-source-link]');
  const drawerCategory = drawer.querySelector('[data-drawer-category]');
  const drawerProduct = drawer.querySelector('[data-drawer-product]');
  const drawerVersion = drawer.querySelector('[data-drawer-version]');
  const drawerProcessing = drawer.querySelector('[data-drawer-processing]');
  const drawerError = drawer.querySelector('[data-drawer-error]');
  const ownershipNote = drawer.querySelector('[data-ownership-note]');
  const editButton = drawer.querySelector('[data-drawer-edit]');
  const withdrawButton = drawer.querySelector('[data-drawer-withdraw]');
  const retryButton = drawer.querySelector('[data-drawer-retry]');
  const saveButton = drawer.querySelector('[data-drawer-save]');
  const toast = document.querySelector('[data-toast]');
  let activeStatus = 'all';
  let activeDocument = null;
  let lastDrawerTrigger = null;
  let toastTimer;

  const showToast = (message) => {
    window.clearTimeout(toastTimer);
    toast.textContent = message;
    toast.hidden = false;
    toastTimer = window.setTimeout(() => { toast.hidden = true; }, 2200);
  };

  const currentFilters = () => ({
    keyword: keyword.value.trim().toLowerCase(),
    source: source.value,
    category: category.value,
    product: product.value,
  });

  const filteredDocuments = () => {
    const filters = currentFilters();
    return documents.filter((item) => (
      item.status !== 'withdrawn'
      && (activeStatus === 'all' || item.status === activeStatus)
      && (!filters.keyword || item.title.toLowerCase().includes(filters.keyword))
      && (filters.source === 'all' || item.source === filters.source)
      && (filters.category === 'all' || item.category === filters.category)
      && (filters.product === 'all' || item.product === filters.product)
    ));
  };

  const closeDrawer = () => {
    drawer.hidden = true;
    backdrop.hidden = true;
    document.body.style.overflow = '';
    if (lastDrawerTrigger) lastDrawerTrigger.focus();
  };

  const setDrawerEditing = (editing) => {
    const editable = Boolean(activeDocument?.owner);
    [drawerCategory, drawerProduct, drawerVersion].forEach((field) => {
      field.disabled = !editable || !editing;
    });
    editButton.textContent = editing ? '取消编辑' : '编辑';
    editButton.dataset.editing = String(editing);
    saveButton.hidden = !editable || !editing;
    if (editing) drawerCategory.focus();
  };

  const renderDrawer = () => {
    if (!activeDocument) return;
    const item = activeDocument;
    drawerTitle.textContent = item.title;
    drawerStatus.innerHTML = `<span class="document-status-pill ${item.status}">${statusLabels[item.status]}</span>`;
    drawerSource.textContent = `${item.sourceLabel} · ${item.fileType}`;
    drawerSubmitter.textContent = item.submitter;
    drawerUpdated.textContent = item.updated;
    if (item.link) {
      drawerSourceLink.textContent = '查看原文';
      drawerSourceLink.href = item.link;
      drawerSourceLink.target = '_blank';
      drawerSourceLink.rel = 'noreferrer';
    } else {
      drawerSourceLink.textContent = '本地上传文件';
      drawerSourceLink.removeAttribute('href');
      drawerSourceLink.removeAttribute('target');
    }
    drawerCategory.value = item.category;
    drawerProduct.value = item.product;
    drawerVersion.value = item.version;
    drawerProcessing.textContent = processingLabels[item.status];
    drawerError.hidden = !item.error;
    drawerError.textContent = item.error || '';
    ownershipNote.hidden = item.owner;
    ownershipNote.textContent = item.owner ? '' : `该文档由“${item.submitter}”提交。你可以查看，但只有提交者可以修改分类、检索条件或撤回文档。`;
    editButton.hidden = !item.owner || item.status === 'withdrawn' || item.status === 'processing';
    withdrawButton.hidden = !item.owner || item.status === 'withdrawn';
    retryButton.hidden = !item.owner || item.status !== 'failed';
    setDrawerEditing(false);
  };

  const openDrawer = (item, trigger) => {
    activeDocument = item;
    lastDrawerTrigger = trigger;
    renderDrawer();
    backdrop.hidden = false;
    drawer.hidden = false;
    document.body.style.overflow = 'hidden';
    drawerClose.focus();
  };

  const renderRows = () => {
    const visible = filteredDocuments();
    rows.innerHTML = '';
    visible.forEach((item) => {
      const row = document.createElement('tr');
      const productValue = item.product || '待补充';
      const versionValue = item.version || '尚未设置版本';
      row.innerHTML = `
        <td><div class="document-name-cell"><strong title="${item.title}">${item.title}</strong><small>${item.fileType}</small></div></td>
        <td><span class="document-source-tag ${item.source}">${item.sourceLabel}</span></td>
        <td><span class="document-category-tag">${item.category}</span></td>
        <td><div class="document-version-cell"><strong>${productValue}</strong><span>${versionValue}</span></div></td>
        <td><span class="document-status-pill ${item.status}">${statusLabels[item.status]}</span></td>
        <td>${item.updated}</td>
        <td>${item.submitter}</td>
        <td><button class="table-action" type="button" aria-label="查看详情：${item.title}">查看详情</button></td>`;
      const trigger = row.querySelector('.table-action');
      trigger.addEventListener('click', () => openDrawer(item, trigger));
      rows.append(row);
    });
    empty.hidden = visible.length > 0;
    resultCount.textContent = `当前显示 ${visible.length} 条，共 986 个文档`;
  };

  statusButtons.forEach((button) => {
    button.addEventListener('click', () => {
      activeStatus = button.dataset.documentStatus;
      statusButtons.forEach((candidate) => {
        const active = candidate === button;
        candidate.classList.toggle('active', active);
        candidate.setAttribute('aria-pressed', String(active));
      });
      renderRows();
    });
  });

  searchButton.addEventListener('click', renderRows);
  keyword.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      renderRows();
    }
  });
  clearButton.addEventListener('click', () => {
    keyword.value = '';
    source.value = 'all';
    category.value = 'all';
    product.value = 'all';
    activeStatus = 'all';
    statusButtons.forEach((button) => {
      const active = button.dataset.documentStatus === 'all';
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    renderRows();
  });

  drawerClose.addEventListener('click', closeDrawer);
  backdrop.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !drawer.hidden) closeDrawer();
  });

  editButton.addEventListener('click', () => {
    setDrawerEditing(editButton.dataset.editing !== 'true');
  });

  saveButton.addEventListener('click', () => {
    if (!activeDocument?.owner) return;
    if (!drawerCategory.value || !drawerProduct.value || !drawerVersion.value) {
      showToast('请先补充完整的分类、产品和版本。');
      return;
    }
    activeDocument.category = drawerCategory.value;
    activeDocument.product = drawerProduct.value;
    activeDocument.version = drawerVersion.value;
    if (activeDocument.status === 'pending') activeDocument.status = 'indexing';
    setDrawerEditing(false);
    renderDrawer();
    renderRows();
    showToast('文档信息已保存。');
  });

  retryButton.addEventListener('click', () => {
    if (!activeDocument?.owner || activeDocument.status !== 'failed') return;
    activeDocument.status = 'processing';
    activeDocument.error = '';
    activeDocument.updated = '2026-08-18 10:32';
    renderDrawer();
    renderRows();
    showToast('已重新提交处理任务。');
  });

  withdrawButton.addEventListener('click', () => {
    if (!activeDocument?.owner) return;
    activeDocument.status = 'withdrawn';
    activeDocument.updated = '2026-08-18 10:35';
    renderRows();
    closeDrawer();
    showToast('文档已撤回，不再参与知识问答。');
  });

  statusButtons.forEach((button) => {
    button.setAttribute('aria-pressed', String(button.dataset.documentStatus === 'all'));
  });
  renderRows();
});

document.querySelectorAll('[data-knowledge-config]').forEach((page) => {
  const products = [
    {
      code: 'AE', name: 'AE 产品', enabled: true, documents: 462,
      majors: [
        {
          name: 'V7', description: '当前主线版本', enabled: true, updated: '2026-08-17',
          minors: [
            { name: '7.0.3', description: '当前稳定版本', enabled: true, documents: 156, updated: '2026-08-17' },
            { name: '7.0.2', description: '历史维护版本', enabled: true, documents: 92, updated: '2026-08-12' },
            { name: '7.0.1', description: '历史版本', enabled: false, documents: 41, updated: '2026-07-28' },
          ],
        },
        {
          name: 'V6', description: '上一代产品版本', enabled: true, updated: '2026-08-05',
          minors: [
            { name: '6.5.2', description: '长期维护版本', enabled: true, documents: 104, updated: '2026-08-05' },
            { name: '6.5.1', description: '历史版本', enabled: false, documents: 69, updated: '2026-07-20' },
          ],
        },
      ],
    },
    {
      code: 'TDA', name: 'TDA 产品', enabled: true, documents: 318,
      majors: [
        {
          name: 'V7', description: '当前主线版本', enabled: true, updated: '2026-08-16',
          minors: [
            { name: '7.0.3', description: '当前稳定版本', enabled: true, documents: 128, updated: '2026-08-16' },
            { name: '7.0.1', description: '历史维护版本', enabled: true, documents: 74, updated: '2026-08-03' },
          ],
        },
        {
          name: 'V6', description: '上一代产品版本', enabled: false, updated: '2026-07-18',
          minors: [
            { name: '6.5.0', description: '历史版本', enabled: false, documents: 116, updated: '2026-07-18' },
          ],
        },
      ],
    },
    {
      code: 'AIP', name: 'AIP 产品', enabled: false, documents: 86,
      majors: [
        {
          name: 'V5', description: '存量项目使用', enabled: false, updated: '2026-06-30',
          minors: [
            { name: '5.4.0', description: '存量版本', enabled: false, documents: 86, updated: '2026-06-30' },
          ],
        },
      ],
    },
  ];
  const categories = [
    { name: '产品规格', code: 'product_spec', description: '硬件规格、设备型号、容量和适配信息', documents: 126, enabled: true, updated: '2026-08-17' },
    { name: '产品功能', code: 'product_feature', description: '产品能力、版本功能和功能使用说明', documents: 204, enabled: true, updated: '2026-08-16' },
    { name: '开发设计', code: 'development', description: '架构、接口、模块设计和开发修复记录', documents: 182, enabled: true, updated: '2026-08-15' },
    { name: '测试文档', code: 'testing', description: '测试方案、测试报告和验证记录', documents: 148, enabled: true, updated: '2026-08-14' },
    { name: '部署文档', code: 'deployment', description: '安装部署、升级、配置和运维操作指导', documents: 117, enabled: true, updated: '2026-08-13' },
    { name: '白皮书', code: 'whitepaper', description: '产品白皮书和面向业务的综合说明材料', documents: 76, enabled: true, updated: '2026-08-12' },
    { name: 'SEG 案件', code: 'seg_case', description: '现场问题、原因分析、解决办法和关闭记录', documents: 133, enabled: true, updated: '2026-08-18' },
  ];

  const tabs = Array.from(page.querySelectorAll('[data-config-tab]'));
  const panels = Array.from(page.querySelectorAll('[data-config-panel]'));
  const productList = page.querySelector('[data-product-list]');
  const productSearch = page.querySelector('[data-product-search]');
  const productCount = page.querySelector('[data-product-count]');
  const selectedProductCode = page.querySelector('[data-selected-product-code]');
  const selectedProductName = page.querySelector('[data-selected-product-name]');
  const majorCount = page.querySelector('[data-major-count]');
  const minorCount = page.querySelector('[data-minor-count]');
  const versionDocumentCount = page.querySelector('[data-version-document-count]');
  const majorVersionList = page.querySelector('[data-major-version-list]');
  const categoryRows = page.querySelector('[data-category-rows]');
  const categoryCount = page.querySelector('[data-category-count]');
  const drawer = document.querySelector('[data-config-drawer]');
  const backdrop = document.querySelector('[data-config-drawer-backdrop]');
  const closeButton = drawer.querySelector('[data-config-drawer-close]');
  const cancelButton = drawer.querySelector('[data-config-cancel]');
  const drawerForm = drawer.querySelector('[data-config-drawer-form]');
  const drawerKicker = drawer.querySelector('[data-config-drawer-kicker]');
  const drawerTitle = drawer.querySelector('[data-config-drawer-title]');
  const fields = drawer.querySelector('[data-config-fields]');
  const ruleNote = drawer.querySelector('[data-config-rule-note]');
  const toast = document.querySelector('[data-toast]');
  let selectedCode = 'AE';
  let editorState = null;
  let lastDrawerTrigger = null;
  let toastTimer;

  const selectedProduct = () => products.find((item) => item.code === selectedCode) || products[0];
  const statusMarkup = (enabled) => `<span class="config-status${enabled ? '' : ' disabled'}">${enabled ? '启用' : '停用'}</span>`;
  const showToast = (message) => {
    window.clearTimeout(toastTimer);
    toast.textContent = message;
    toast.hidden = false;
    toastTimer = window.setTimeout(() => { toast.hidden = true; }, 2200);
  };

  const renderProductList = () => {
    const query = productSearch.value.trim().toLowerCase();
    productList.innerHTML = '';
    products
      .filter((item) => !query || `${item.name}${item.code}`.toLowerCase().includes(query))
      .forEach((item) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `product-config-item${item.code === selectedCode ? ' active' : ''}`;
        button.setAttribute('aria-pressed', String(item.code === selectedCode));
        button.innerHTML = `<span><strong>${item.name}</strong><small>${item.code} · ${item.majors.length} 个大版本 · ${item.enabled ? '启用' : '停用'}</small></span><span class="item-count">${item.documents} 篇</span>`;
        button.addEventListener('click', () => {
          selectedCode = item.code;
          renderProductList();
          renderVersions();
        });
        productList.append(button);
      });
    productCount.textContent = products.length;
  };

  const renderVersions = () => {
    const productItem = selectedProduct();
    const totalMinors = productItem.majors.reduce((sum, major) => sum + major.minors.length, 0);
    selectedProductCode.textContent = productItem.code;
    selectedProductName.textContent = productItem.name;
    majorCount.textContent = productItem.majors.length;
    minorCount.textContent = totalMinors;
    versionDocumentCount.textContent = productItem.documents;
    majorVersionList.innerHTML = '';

    productItem.majors.forEach((major, index) => {
      const details = document.createElement('details');
      details.className = 'major-version-card';
      details.open = index === 0;
      const minorRows = major.minors.map((minor) => `
        <tr>
          <td><strong>${minor.name}</strong></td>
          <td>${minor.description}</td>
          <td>${minor.documents} 篇</td>
          <td>${statusMarkup(minor.enabled)}</td>
          <td><button class="config-inline-action" type="button" data-edit-minor="${minor.name}" data-major="${major.name}" aria-label="编辑小版本 ${minor.name}">编辑</button></td>
        </tr>`).join('');
      details.innerHTML = `
        <summary>
          <span class="major-version-title"><span class="version-expand-mark">展开</span><span><strong>${major.name}</strong><small>${major.description} · 更新于 ${major.updated}</small></span></span>
          ${statusMarkup(major.enabled)}
          <span>${major.minors.length} 个小版本</span>
        </summary>
        <div class="minor-version-area">
          <div class="minor-version-toolbar">
            <span>该大版本下的小版本</span>
            <span class="major-summary-actions">
              <button class="config-inline-action" type="button" data-edit-major="${major.name}">编辑大版本</button>
              <button class="ae-button compact" type="button" data-add-minor="${major.name}">＋ 新建小版本</button>
            </span>
          </div>
          <table class="minor-version-table">
            <thead><tr><th>小版本</th><th>说明</th><th>关联文档</th><th>状态</th><th>操作</th></tr></thead>
            <tbody>${minorRows || '<tr><td colspan="5">暂无小版本</td></tr>'}</tbody>
          </table>
        </div>`;
      details.addEventListener('toggle', () => {
        const marker = details.querySelector('.version-expand-mark');
        marker.textContent = details.open ? '收起' : '展开';
      });
      majorVersionList.append(details);
      details.querySelector('.version-expand-mark').textContent = details.open ? '收起' : '展开';
    });
  };

  const renderCategories = () => {
    categoryRows.innerHTML = '';
    categories.forEach((item) => {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td><div class="category-name"><strong>${item.name}</strong><small>${item.code}</small></div></td>
        <td class="category-description">${item.description}</td>
        <td>${item.documents} 篇</td>
        <td>${statusMarkup(item.enabled)}</td>
        <td>${item.updated}</td>
        <td><button class="config-inline-action" type="button" data-edit-category="${item.code}" aria-label="编辑分类 ${item.name}">编辑</button></td>`;
      categoryRows.append(row);
    });
    categoryCount.textContent = categories.length;
  };

  const fieldMarkup = (label, name, value = '', options = null, help = '', required = true) => {
    const marker = required ? ' <b>*</b>' : '';
    const control = options
      ? `<select name="${name}" ${required ? 'required' : ''}>${options.map((option) => `<option value="${option.value}"${String(option.value) === String(value) ? ' selected' : ''}>${option.label}</option>`).join('')}</select>`
      : `<input name="${name}" value="${value}" ${required ? 'required' : ''}>`;
    return `<label class="config-field"><span>${label}${marker}</span>${control}${help ? `<small>${help}</small>` : ''}</label>`;
  };

  const descriptionMarkup = (label, value = '') => `
    <label class="config-field"><span>${label}</span><textarea name="description">${value}</textarea></label>`;

  const openEditor = (state, trigger) => {
    editorState = state;
    lastDrawerTrigger = trigger;
    const productItem = selectedProduct();
    const enabledOptions = [{ value: 'true', label: '启用' }, { value: 'false', label: '停用' }];
    let markup = '';
    let note = '';
    drawerKicker.textContent = '基础配置';

    if (state.type === 'product') {
      const item = state.item;
      drawerTitle.textContent = item ? '编辑产品' : '新建产品';
      markup = [
        fieldMarkup('产品名称', 'name', item?.name || '', null, '用于管理页面和查询条件展示。'),
        fieldMarkup('产品编码', 'code', item?.code || '', null, '编码保存后建议保持稳定。'),
        fieldMarkup('状态', 'enabled', String(item?.enabled ?? true), enabledOptions),
      ].join('');
      note = '产品停用后，不影响历史文档和已有对话；新文档入库及查询条件中不再显示。';
    } else if (state.type === 'major') {
      const item = state.item;
      drawerTitle.textContent = item ? `编辑 ${item.name}` : `为 ${productItem.code} 新建大版本`;
      markup = [
        fieldMarkup('大版本名称', 'name', item?.name || '', null, '例如 V7、V8。'),
        descriptionMarkup('版本说明', item?.description || ''),
        fieldMarkup('状态', 'enabled', String(item?.enabled ?? true), enabledOptions),
      ].join('');
      note = '大版本用于组织小版本。停用大版本时，其下小版本也不会出现在新的选择列表中。';
    } else if (state.type === 'minor') {
      const item = state.item;
      drawerTitle.textContent = item ? `编辑小版本 ${item.name}` : `在 ${state.major.name} 下新建小版本`;
      markup = [
        fieldMarkup('小版本号', 'name', item?.name || '', null, '例如 7.0.3。'),
        descriptionMarkup('版本说明', item?.description || ''),
        fieldMarkup('状态', 'enabled', String(item?.enabled ?? true), enabledOptions),
      ].join('');
      note = '已关联文档的小版本不能直接删除，但可以停用；历史数据仍保留原版本。';
    } else {
      const item = state.item;
      drawerTitle.textContent = item ? `编辑分类 ${item.name}` : '新建文档分类';
      markup = [
        fieldMarkup('分类名称', 'name', item?.name || '', null, '该名称会提供给自动分类器和用户。'),
        fieldMarkup('分类编码', 'code', item?.code || '', null, '使用小写英文和下划线，例如 support_case。'),
        descriptionMarkup('用途说明', item?.description || ''),
        fieldMarkup('状态', 'enabled', String(item?.enabled ?? true), enabledOptions),
      ].join('');
      note = '分类器只读取启用的分类。无法判断分类的文档会进入异常记录，不会直接建立检索索引。';
    }

    fields.className = 'config-fields';
    fields.innerHTML = markup;
    ruleNote.textContent = note;
    backdrop.hidden = false;
    drawer.hidden = false;
    document.body.style.overflow = 'hidden';
    closeButton.focus();
  };

  const closeEditor = () => {
    drawer.hidden = true;
    backdrop.hidden = true;
    document.body.style.overflow = '';
    if (lastDrawerTrigger) lastDrawerTrigger.focus();
  };

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      tabs.forEach((candidate) => {
        const active = candidate === tab;
        candidate.classList.toggle('active', active);
        candidate.setAttribute('aria-selected', String(active));
      });
      panels.forEach((panel) => { panel.hidden = panel.dataset.configPanel !== tab.dataset.configTab; });
    });
  });

  productSearch.addEventListener('input', renderProductList);
  page.querySelector('[data-add-product]').addEventListener('click', (event) => openEditor({ type: 'product', item: null }, event.currentTarget));
  page.querySelector('[data-edit-product]').addEventListener('click', (event) => openEditor({ type: 'product', item: selectedProduct() }, event.currentTarget));
  page.querySelector('[data-add-major]').addEventListener('click', (event) => openEditor({ type: 'major', item: null }, event.currentTarget));
  page.querySelector('[data-add-category]').addEventListener('click', (event) => openEditor({ type: 'category', item: null }, event.currentTarget));

  majorVersionList.addEventListener('click', (event) => {
    const addMinor = event.target.closest('[data-add-minor]');
    const editMajor = event.target.closest('[data-edit-major]');
    const editMinor = event.target.closest('[data-edit-minor]');
    const productItem = selectedProduct();
    if (addMinor) {
      const major = productItem.majors.find((item) => item.name === addMinor.dataset.addMinor);
      openEditor({ type: 'minor', major, item: null }, addMinor);
    } else if (editMajor) {
      const item = productItem.majors.find((major) => major.name === editMajor.dataset.editMajor);
      openEditor({ type: 'major', item }, editMajor);
    } else if (editMinor) {
      const major = productItem.majors.find((item) => item.name === editMinor.dataset.major);
      const item = major.minors.find((minor) => minor.name === editMinor.dataset.editMinor);
      openEditor({ type: 'minor', major, item }, editMinor);
    }
  });

  categoryRows.addEventListener('click', (event) => {
    const button = event.target.closest('[data-edit-category]');
    if (!button) return;
    const item = categories.find((categoryItem) => categoryItem.code === button.dataset.editCategory);
    openEditor({ type: 'category', item }, button);
  });

  [closeButton, cancelButton].forEach((button) => button.addEventListener('click', closeEditor));
  backdrop.addEventListener('click', closeEditor);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !drawer.hidden) closeEditor();
  });

  drawerForm.addEventListener('submit', (event) => {
    event.preventDefault();
    const formData = new FormData(drawerForm);
    const name = String(formData.get('name') || '').trim();
    const code = String(formData.get('code') || '').trim();
    const description = String(formData.get('description') || '').trim();
    const enabled = formData.get('enabled') === 'true';
    const today = '2026-08-18';
    if (!name) return;

    if (editorState.type === 'product') {
      if (editorState.item) {
        editorState.item.name = name;
        editorState.item.code = code.toUpperCase();
        editorState.item.enabled = enabled;
        selectedCode = editorState.item.code;
      } else {
        const normalizedCode = code.toUpperCase();
        if (products.some((item) => item.code === normalizedCode)) {
          showToast('产品编码已经存在，请更换后保存。');
          return;
        }
        products.push({ code: normalizedCode, name, enabled, documents: 0, majors: [] });
        selectedCode = normalizedCode;
      }
      renderProductList();
      renderVersions();
    } else if (editorState.type === 'major') {
      const productItem = selectedProduct();
      if (editorState.item) {
        editorState.item.name = name;
        editorState.item.description = description;
        editorState.item.enabled = enabled;
        editorState.item.updated = today;
      } else {
        if (productItem.majors.some((item) => item.name === name)) {
          showToast('当前产品下已经存在同名大版本。');
          return;
        }
        productItem.majors.unshift({ name, description, enabled, updated: today, minors: [] });
      }
      renderVersions();
    } else if (editorState.type === 'minor') {
      if (editorState.item) {
        editorState.item.name = name;
        editorState.item.description = description;
        editorState.item.enabled = enabled;
        editorState.item.updated = today;
      } else {
        if (editorState.major.minors.some((item) => item.name === name)) {
          showToast('当前大版本下已经存在同名小版本。');
          return;
        }
        editorState.major.minors.unshift({ name, description, enabled, documents: 0, updated: today });
      }
      renderVersions();
    } else {
      if (editorState.item) {
        editorState.item.name = name;
        editorState.item.code = code.toLowerCase();
        editorState.item.description = description;
        editorState.item.enabled = enabled;
        editorState.item.updated = today;
      } else {
        const normalizedCode = code.toLowerCase();
        if (categories.some((item) => item.code === normalizedCode)) {
          showToast('分类编码已经存在，请更换后保存。');
          return;
        }
        categories.push({ name, code: normalizedCode, description, enabled, documents: 0, updated: today });
      }
      renderCategories();
    }
    closeEditor();
    showToast('配置已保存，并将用于新的文档入库和查询条件。');
  });

  renderProductList();
  renderVersions();
  renderCategories();
});

document.querySelectorAll('[data-login-page]').forEach((page) => {
  const tabs = Array.from(page.querySelectorAll('[data-login-tab]'));
  const panels = Array.from(page.querySelectorAll('[data-login-panel]'));
  const passwordForm = page.querySelector('[data-password-login]');
  const message = page.querySelector('[data-login-message]');
  const forgotPassword = page.querySelector('[data-forgot-password]');
  const openFeishu = page.querySelector('[data-open-feishu-auth]');
  const feishuProgress = page.querySelector('[data-feishu-progress]');
  const simulateFeishu = page.querySelector('[data-simulate-feishu]');

  const showMessage = (text, error = false) => {
    message.textContent = text;
    message.classList.toggle('error', error);
    message.hidden = false;
  };

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      tabs.forEach((candidate) => {
        const active = candidate === tab;
        candidate.classList.toggle('active', active);
        candidate.setAttribute('aria-selected', String(active));
      });
      panels.forEach((panel) => { panel.hidden = panel.dataset.loginPanel !== tab.dataset.loginTab; });
      message.hidden = true;
    });
  });

  passwordForm.addEventListener('submit', (event) => {
    event.preventDefault();
    const submit = passwordForm.querySelector('[type="submit"]');
    submit.disabled = true;
    submit.textContent = '正在登录…';
    window.setTimeout(() => {
      submit.disabled = false;
      submit.textContent = '登录';
      showMessage('登录成功，正在进入知识问答工作台。');
    }, 600);
  });

  forgotPassword.addEventListener('click', () => {
    showMessage('请联系系统管理员重置密码。', true);
  });

  openFeishu.addEventListener('click', () => {
    openFeishu.hidden = true;
    feishuProgress.hidden = false;
    showMessage('飞书认证页面已打开，正在等待扫码确认。');
  });

  simulateFeishu.addEventListener('click', () => {
    simulateFeishu.disabled = true;
    simulateFeishu.textContent = '已完成扫码';
    showMessage('已通过飞书 user_id 识别用户，登录成功。');
  });
});

document.querySelectorAll('[data-user-management]').forEach((page) => {
  const users = [
    { id: 1, name: '薛文李', username: 'xuewenli', accountType: 'admin', loginMethods: ['password', 'feishu'], bound: true, feishuName: '薛文李', userId: 'fdf633a26d1026ce8d5d87c9b983c6cb', status: 'active', lastLogin: '2026-08-18 10:57', created: '2026-07-11' },
    { id: 2, name: '王强', username: 'wangqiang', accountType: 'user', loginMethods: ['password', 'feishu'], bound: true, feishuName: '王强', userId: 'a21937ab68ad4d069b1e4c137148af20', status: 'active', lastLogin: '2026-08-18 09:42', created: '2026-07-12' },
    { id: 3, name: '李敏', username: 'limin', accountType: 'user', loginMethods: ['feishu'], bound: true, feishuName: '李敏', userId: '7262b00620534bd3a2996e0481a94076', status: 'active', lastLogin: '2026-08-17 16:20', created: '2026-07-18' },
    { id: 4, name: '陈晨', username: 'chenchen', accountType: 'user', loginMethods: ['password'], bound: false, feishuName: '', userId: '', status: 'active', lastLogin: '2026-08-17 13:06', created: '2026-07-22' },
    { id: 5, name: '赵磊', username: 'zhaolei', accountType: 'user', loginMethods: ['password', 'feishu'], bound: true, feishuName: '赵磊', userId: 'd1c77c821bdd4efbb5c456ae5e5a07af', status: 'disabled', lastLogin: '2026-08-10 11:18', created: '2026-07-25' },
    { id: 6, name: '周婷', username: 'zhouting', accountType: 'user', loginMethods: ['password'], bound: false, feishuName: '', userId: '', status: 'disabled', lastLogin: '从未登录', created: '2026-08-01' },
  ];
  const rows = page.querySelector('[data-user-rows]');
  const empty = page.querySelector('[data-user-empty]');
  const resultCount = page.querySelector('[data-user-result-count]');
  const keyword = page.querySelector('[data-user-keyword]');
  const loginType = page.querySelector('[data-user-login-type]');
  const accountType = page.querySelector('[data-user-account-type]');
  const searchButton = page.querySelector('[data-user-search]');
  const clearButton = page.querySelector('[data-user-clear]');
  const statusButtons = Array.from(page.querySelectorAll('[data-user-status]'));
  const drawer = document.querySelector('[data-user-drawer]');
  const backdrop = document.querySelector('[data-user-drawer-backdrop]');
  const closeButton = drawer.querySelector('[data-user-drawer-close]');
  const cancelButton = drawer.querySelector('[data-user-cancel]');
  const drawerTitle = drawer.querySelector('[data-user-drawer-title]');
  const form = drawer.querySelector('[data-user-form]');
  const passwordField = drawer.querySelector('[data-password-field]');
  const bindingSection = drawer.querySelector('[data-binding-section]');
  const bindingStatus = drawer.querySelector('[data-binding-status]');
  const bindingName = drawer.querySelector('[data-binding-name]');
  const bindingUserId = drawer.querySelector('[data-binding-user-id]');
  const unbindButton = drawer.querySelector('[data-unbind-feishu]');
  const unbindHelp = drawer.querySelector('[data-unbind-help]');
  const toast = document.querySelector('[data-toast]');
  let activeStatus = 'all';
  let activeUser = null;
  let lastDrawerTrigger = null;
  let toastTimer;

  const showToast = (text) => {
    window.clearTimeout(toastTimer);
    toast.textContent = text;
    toast.hidden = false;
    toastTimer = window.setTimeout(() => { toast.hidden = true; }, 2200);
  };

  const visibleUsers = () => {
    const value = keyword.value.trim().toLowerCase();
    return users.filter((user) => (
      (activeStatus === 'all' || (activeStatus === 'bound' ? user.bound : user.status === activeStatus))
      && (!value || `${user.name}${user.username}${user.userId}`.toLowerCase().includes(value))
      && (loginType.value === 'all' || user.loginMethods.includes(loginType.value))
      && (accountType.value === 'all' || user.accountType === accountType.value)
    ));
  };

  const renderRows = () => {
    const visible = visibleUsers();
    rows.innerHTML = '';
    visible.forEach((user) => {
      const row = document.createElement('tr');
      const methods = user.loginMethods.map((method) => `<span class="login-type-tag ${method}">${method === 'password' ? '账号密码' : '飞书登录'}</span>`).join('');
      const binding = user.bound
        ? `<span class="binding-tag bound">已绑定</span><code class="binding-id" title="${user.userId}">${user.userId}</code>`
        : '<span class="binding-tag unbound">未绑定</span>';
      row.innerHTML = `
        <td><div class="user-name-cell"><strong>${user.name}</strong><small>创建于 ${user.created}</small></div></td>
        <td>${user.username}</td>
        <td><span class="account-type-tag ${user.accountType}">${user.accountType === 'admin' ? '管理员' : '普通用户'}</span></td>
        <td><div class="login-methods">${methods}</div></td>
        <td>${binding}</td>
        <td><span class="user-status-pill ${user.status}">${user.status === 'active' ? '正常' : '已停用'}</span></td>
        <td>${user.lastLogin}</td>
        <td><button class="table-action" type="button" aria-label="编辑用户：${user.name}">编辑</button></td>`;
      const trigger = row.querySelector('.table-action');
      trigger.addEventListener('click', () => openDrawer(user, trigger));
      rows.append(row);
    });
    empty.hidden = visible.length > 0;
    resultCount.textContent = `当前显示 ${visible.length} 条，共 30 个用户`;
  };

  const renderBinding = () => {
    if (!activeUser) {
      bindingSection.hidden = true;
      return;
    }
    bindingSection.hidden = false;
    bindingStatus.textContent = activeUser.bound ? '已绑定' : '未绑定';
    bindingName.textContent = activeUser.bound ? activeUser.feishuName : '—';
    bindingUserId.textContent = activeUser.bound ? activeUser.userId : '—';
    unbindButton.hidden = !activeUser.bound;
    const canUnbind = activeUser.loginMethods.includes('password');
    unbindButton.disabled = activeUser.bound && !canUnbind;
    unbindHelp.hidden = !activeUser.bound || canUnbind;
    unbindHelp.textContent = activeUser.bound && !canUnbind ? '该用户当前仅能使用飞书登录。请先设置登录密码，再解除绑定。' : '';
  };

  const openDrawer = (user, trigger) => {
    activeUser = user;
    lastDrawerTrigger = trigger;
    drawerTitle.textContent = user ? `编辑用户：${user.name}` : '新建用户';
    form.elements.name.value = user?.name || '';
    form.elements.username.value = user?.username || '';
    form.elements.accountType.value = user?.accountType || 'user';
    form.elements.status.value = user?.status || 'active';
    form.elements.password.value = '';
    const passwordLabel = passwordField.querySelector('span');
    passwordLabel.innerHTML = user ? '重置密码（选填）' : '临时密码 <b>*</b>';
    form.elements.password.required = !user;
    renderBinding();
    backdrop.hidden = false;
    drawer.hidden = false;
    document.body.style.overflow = 'hidden';
    closeButton.focus();
  };

  const closeDrawer = () => {
    drawer.hidden = true;
    backdrop.hidden = true;
    document.body.style.overflow = '';
    if (lastDrawerTrigger) lastDrawerTrigger.focus();
  };

  statusButtons.forEach((button) => {
    button.addEventListener('click', () => {
      activeStatus = button.dataset.userStatus;
      statusButtons.forEach((candidate) => {
        const active = candidate === button;
        candidate.classList.toggle('active', active);
        candidate.setAttribute('aria-pressed', String(active));
      });
      renderRows();
    });
  });

  searchButton.addEventListener('click', renderRows);
  keyword.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); renderRows(); }
  });
  clearButton.addEventListener('click', () => {
    keyword.value = '';
    loginType.value = 'all';
    accountType.value = 'all';
    activeStatus = 'all';
    statusButtons.forEach((button) => {
      const active = button.dataset.userStatus === 'all';
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    renderRows();
  });

  page.querySelector('[data-add-user]').addEventListener('click', (event) => openDrawer(null, event.currentTarget));
  [closeButton, cancelButton].forEach((button) => button.addEventListener('click', closeDrawer));
  backdrop.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !drawer.hidden) closeDrawer();
  });

  unbindButton.addEventListener('click', () => {
    if (!activeUser?.bound) return;
    activeUser.bound = false;
    activeUser.feishuName = '';
    activeUser.userId = '';
    activeUser.loginMethods = activeUser.loginMethods.filter((method) => method !== 'feishu');
    renderBinding();
    renderRows();
    showToast('已解除飞书账号绑定。');
  });

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const nextUsername = String(data.get('username')).trim();
    const duplicate = users.some((user) => user.username === nextUsername && user !== activeUser);
    if (duplicate) {
      showToast('登录账号已经存在，请更换后保存。');
      return;
    }
    if (activeUser) {
      activeUser.name = String(data.get('name')).trim();
      activeUser.username = nextUsername;
      activeUser.accountType = String(data.get('accountType'));
      activeUser.status = String(data.get('status'));
      if (String(data.get('password') || '').trim() && !activeUser.loginMethods.includes('password')) {
        activeUser.loginMethods.push('password');
      }
    } else {
      users.push({
        id: Date.now(), name: String(data.get('name')).trim(), username: nextUsername,
        accountType: String(data.get('accountType')), loginMethods: ['password'], bound: false, feishuName: '', userId: '',
        status: String(data.get('status')), lastLogin: '从未登录', created: '2026-08-18',
      });
    }
    renderRows();
    closeDrawer();
    showToast(activeUser ? '用户信息已保存。' : '用户创建成功。');
  });

  renderRows();
});

document.querySelectorAll('[data-system-tasks]').forEach((page) => {
  const tasks = [
    {
      id: 'TASK-20260818-0018', document: 'AE 产品白皮书', type: 'wiki', trigger: 'scheduled', owner: '系统任务', status: 'failed', progress: 38,
      retries: 3, started: '2026-08-18 02:00:03', updated: '2026-08-18 02:06:41',
      errorTitle: '读取飞书文档失败', errorMessage: '飞书接口请求超时，连续 3 次自动重试仍未成功。已记录本次同步失败，不影响上一版本继续检索。', nextAction: '等待管理员人工重试',
      steps: [['检查更新时间', '已识别到文档更新', 'completed'], ['读取文档内容', '飞书接口请求超时', 'failed'], ['解析与更新索引', '尚未执行', 'pending']],
      history: [['02:00:03', '定时任务开始执行', '开始'], ['02:02:11', '第 1 次自动重试', '失败'], ['02:04:26', '第 2 次自动重试', '失败'], ['02:06:41', '第 3 次自动重试', '失败']],
    },
    {
      id: 'TASK-20260818-0017', document: '离线更新操作指导文档', type: 'parse', trigger: 'upload', owner: '薛文李', status: 'running', progress: 62,
      retries: 0, started: '2026-08-18 10:58:12', updated: '2026-08-18 10:59:08', nextAction: '继续处理',
      steps: [['读取文件', '正文与表格读取完成', 'completed'], ['内容切片', '正在处理第 48 / 77 个片段', 'running'], ['自动分类', '等待上一步完成', 'pending'], ['建立索引', '尚未执行', 'pending']],
      history: [['10:58:12', '用户提交文档', '开始'], ['10:58:20', '文件解析完成', '成功'], ['10:59:08', '正在生成内容切片', '处理中']],
    },
    {
      id: 'TASK-20260818-0016', document: 'T90000 硬件规格', type: 'classify', trigger: 'upload', owner: '王强', status: 'completed', progress: 100,
      retries: 0, started: '2026-08-18 10:42:05', updated: '2026-08-18 10:42:19', nextAction: '无需处理',
      steps: [['读取分类配置', '已读取 7 个有效分类', 'completed'], ['内容分类', '识别为“产品规格”', 'completed'], ['保存分类结果', '结果已保存', 'completed']],
      history: [['10:42:05', '解析任务触发自动分类', '开始'], ['10:42:19', '分类结果已保存', '成功']],
    },
    {
      id: 'TASK-20260818-0015', document: 'PXW 故障技术分析报告', type: 'index', trigger: 'upload', owner: '薛文李', status: 'retrying', progress: 76,
      retries: 2, started: '2026-08-18 10:31:44', updated: '2026-08-18 10:36:02',
      errorTitle: '向量服务暂时不可用', errorMessage: '向量化请求返回服务繁忙。系统正在执行第 2 次自动重试，达到 3 次后仍失败才会转为处理失败。', nextAction: '10:38 自动重试',
      steps: [['生成关键词索引', 'BM25 索引已完成', 'completed'], ['生成向量', '等待向量服务恢复', 'running'], ['发布检索版本', '尚未执行', 'pending']],
      history: [['10:31:44', '自动分类完成并触发索引', '开始'], ['10:33:16', '第 1 次自动重试', '失败'], ['10:36:02', '第 2 次自动重试执行中', '处理中']],
    },
    {
      id: 'TASK-20260818-0014', document: 'TDA 7.0.3 产品白皮书', type: 'wiki', trigger: 'scheduled', owner: '系统任务', status: 'completed', progress: 100,
      retries: 0, started: '2026-08-18 02:00:02', updated: '2026-08-18 02:00:08', nextAction: '明日定时检查',
      steps: [['检查更新时间', '文档未发生更新', 'completed'], ['结束同步', '沿用当前索引版本', 'completed']],
      history: [['02:00:02', '定时任务开始执行', '开始'], ['02:00:08', '文档无更新，任务结束', '成功']],
    },
    {
      id: 'TASK-20260818-0013', document: '网桥部署说明', type: 'parse', trigger: 'manual', owner: '薛文李', status: 'failed', progress: 22,
      retries: 3, started: '2026-08-18 09:04:27', updated: '2026-08-18 09:11:32',
      errorTitle: '文档内容解析失败', errorMessage: '文档包含无法读取的嵌入对象。系统已保留原文件和失败原因，可修正文档后重新提交，或直接人工重试。', nextAction: '等待人工处理',
      steps: [['读取文件', '文件下载完成', 'completed'], ['提取正文与表格', '嵌入对象读取失败', 'failed'], ['自动分类', '尚未执行', 'pending'], ['建立索引', '尚未执行', 'pending']],
      history: [['09:04:27', '管理员发起人工重试', '开始'], ['09:06:39', '第 1 次自动重试', '失败'], ['09:09:01', '第 2 次自动重试', '失败'], ['09:11:32', '第 3 次自动重试', '失败']],
    },
  ];
  const typeLabels = { wiki: 'Wiki 同步', parse: '文档解析', classify: '自动分类', index: '建立索引' };
  const triggerLabels = { scheduled: '定时任务', upload: '用户提交', manual: '人工重试' };
  const statusLabels = { completed: '已完成', running: '处理中', retrying: '自动重试', failed: '处理失败' };
  const counts = { all: 18, running: 2, retrying: 1, failed: 2, completed: 13 };
  const rows = page.querySelector('[data-task-rows]');
  const empty = page.querySelector('[data-task-empty]');
  const resultCount = page.querySelector('[data-task-result-count]');
  const keyword = page.querySelector('[data-task-keyword]');
  const type = page.querySelector('[data-task-type]');
  const trigger = page.querySelector('[data-task-trigger]');
  const statusButtons = Array.from(page.querySelectorAll('[data-task-status]'));
  const drawer = document.querySelector('[data-task-drawer]');
  const backdrop = document.querySelector('[data-task-drawer-backdrop]');
  const closeButtons = [drawer.querySelector('[data-task-drawer-close]'), drawer.querySelector('[data-task-close]')];
  const retryButton = drawer.querySelector('[data-task-retry]');
  const toast = document.querySelector('[data-toast]');
  let activeStatus = 'all';
  let activeTask = null;
  let lastTrigger = null;
  let toastTimer;

  const showToast = (text) => {
    window.clearTimeout(toastTimer);
    toast.textContent = text;
    toast.hidden = false;
    toastTimer = window.setTimeout(() => { toast.hidden = true; }, 2400);
  };

  const renderCounts = () => {
    statusButtons.forEach((button) => { button.querySelector('strong').textContent = counts[button.dataset.taskStatus]; });
  };

  const visibleTasks = () => {
    const value = keyword.value.trim().toLowerCase();
    return tasks.filter((task) => (
      (activeStatus === 'all' || task.status === activeStatus)
      && (!value || `${task.id}${task.document}`.toLowerCase().includes(value))
      && (type.value === 'all' || task.type === type.value)
      && (trigger.value === 'all' || task.trigger === trigger.value)
    ));
  };

  const renderRows = () => {
    const visible = visibleTasks();
    rows.innerHTML = '';
    visible.forEach((task) => {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td><div class="task-name-cell"><strong>${task.document}</strong><small>${task.id}</small></div></td>
        <td><span class="task-type-tag ${task.type}">${typeLabels[task.type]}</span></td>
        <td><span class="task-trigger-tag ${task.trigger}">${triggerLabels[task.trigger]}</span></td>
        <td><span class="task-status-pill ${task.status}">${statusLabels[task.status]}</span></td>
        <td><div class="task-progress ${task.status}"><div class="task-progress-track"><i style="width:${task.progress}%"></i></div><span>${task.progress}%${task.retries ? ` · 重试 ${task.retries}/3` : ''}</span></div></td>
        <td>${task.updated}</td>
        <td><button class="table-action" type="button" aria-label="查看任务：${task.id}">查看详情</button></td>`;
      const action = row.querySelector('.table-action');
      action.addEventListener('click', () => openDrawer(task, action));
      rows.append(row);
    });
    empty.hidden = visible.length > 0;
    resultCount.textContent = `当前显示 ${visible.length} 条，共 ${counts[activeStatus]} 个${activeStatus === 'all' ? '今日任务' : statusLabels[activeStatus] + '任务'}`;
  };

  const renderDrawer = () => {
    if (!activeTask) return;
    drawer.querySelector('[data-task-drawer-title]').textContent = activeTask.id;
    drawer.querySelector('[data-task-drawer-document]').textContent = activeTask.document;
    drawer.querySelector('[data-task-drawer-type]').textContent = `${typeLabels[activeTask.type]} · 进度 ${activeTask.progress}%`;
    drawer.querySelector('[data-task-drawer-status]').innerHTML = `<span class="task-status-pill ${activeTask.status}">${statusLabels[activeTask.status]}</span>`;
    drawer.querySelector('[data-task-drawer-trigger]').textContent = triggerLabels[activeTask.trigger];
    drawer.querySelector('[data-task-drawer-owner]').textContent = activeTask.owner;
    drawer.querySelector('[data-task-drawer-started]').textContent = activeTask.started;
    drawer.querySelector('[data-task-drawer-updated]').textContent = activeTask.updated;
    drawer.querySelector('[data-task-steps]').innerHTML = activeTask.steps.map(([name, detail, state]) => `<li class="${state}"><div><strong>${name}</strong><small>${detail}</small></div><em>${state === 'completed' ? '已完成' : state === 'running' ? '处理中' : state === 'failed' ? '失败' : '未开始'}</em></li>`).join('');
    const errorSection = drawer.querySelector('[data-task-error-section]');
    errorSection.hidden = !activeTask.errorTitle;
    if (activeTask.errorTitle) {
      drawer.querySelector('[data-task-error-title]').textContent = activeTask.errorTitle;
      drawer.querySelector('[data-task-error-message]').textContent = activeTask.errorMessage;
      drawer.querySelector('[data-task-retry-count]').textContent = `${activeTask.retries} / 3`;
      drawer.querySelector('[data-task-next-action]').textContent = activeTask.nextAction;
    }
    drawer.querySelector('[data-task-history]').innerHTML = activeTask.history.map(([time, action, result]) => `<div class="task-history-item"><time>${time}</time><span>${action}</span><b class="${result === '成功' ? 'success' : result === '失败' ? 'failure' : ''}">${result}</b></div>`).join('');
    retryButton.hidden = activeTask.status !== 'failed';
  };

  const openDrawer = (task, action) => {
    activeTask = task;
    lastTrigger = action;
    renderDrawer();
    backdrop.hidden = false;
    drawer.hidden = false;
    document.body.style.overflow = 'hidden';
    drawer.querySelector('[data-task-drawer-close]').focus();
  };

  const closeDrawer = () => {
    drawer.hidden = true;
    backdrop.hidden = true;
    document.body.style.overflow = '';
    if (lastTrigger) lastTrigger.focus();
  };

  statusButtons.forEach((button) => {
    button.addEventListener('click', () => {
      activeStatus = button.dataset.taskStatus;
      statusButtons.forEach((candidate) => {
        const active = candidate === button;
        candidate.classList.toggle('active', active);
        candidate.setAttribute('aria-pressed', String(active));
      });
      renderRows();
    });
  });
  page.querySelector('[data-task-search]').addEventListener('click', renderRows);
  keyword.addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); renderRows(); } });
  page.querySelector('[data-task-clear]').addEventListener('click', () => {
    keyword.value = '';
    type.value = 'all';
    trigger.value = 'all';
    activeStatus = 'all';
    statusButtons.forEach((button) => {
      const active = button.dataset.taskStatus === 'all';
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    renderRows();
  });
  page.querySelector('[data-refresh-tasks]').addEventListener('click', (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = '刷新中…';
    window.setTimeout(() => {
      button.disabled = false;
      button.textContent = '刷新状态';
      showToast('任务状态已更新。');
    }, 600);
  });
  closeButtons.forEach((button) => button.addEventListener('click', closeDrawer));
  backdrop.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !drawer.hidden) closeDrawer(); });
  retryButton.addEventListener('click', () => {
    if (!activeTask || activeTask.status !== 'failed') return;
    counts.failed -= 1;
    counts.retrying += 1;
    activeTask.status = 'retrying';
    activeTask.progress = 8;
    activeTask.retries = 0;
    activeTask.updated = '2026-08-18 11:08:12';
    activeTask.nextAction = '正在执行新的人工重试任务';
    activeTask.errorMessage = '已发起人工重试。新的执行轮次可再次进行最多 3 次自动重试，原失败记录继续保留。';
    activeTask.history.push(['11:08:12', '管理员发起人工重试', '处理中']);
    renderCounts();
    renderRows();
    renderDrawer();
    showToast('人工重试已启动，原执行记录已保留。');
  });

  renderCounts();
  renderRows();
});

document.querySelectorAll('[data-audit-logs]').forEach((page) => {
  const logs = [
    {
      id: 'AUD-20260818-0126', time: '2026-08-18 11:08:12', operator: '薛文李', account: 'xuewenli', module: 'task', action: '人工重试任务', object: 'AE 产品白皮书', objectType: 'TASK-20260818-0018', result: 'success', ip: '10.21.136.178', requestId: 'REQ-8A10D6F2',
      description: '管理员对已达到三次自动重试上限的 Wiki 同步任务发起人工重试，系统创建新的执行轮次并保留原失败记录。',
      changes: [['任务状态', '处理失败', '自动重试'], ['自动重试次数', '3 / 3', '0 / 3（新轮次）']], error: '',
    },
    {
      id: 'AUD-20260818-0125', time: '2026-08-18 10:57:48', operator: '薛文李', account: 'xuewenli', module: 'query', action: '提交知识查询', object: '知识问答会话', objectType: 'CONV-20260818-0036', result: 'success', ip: '10.21.136.178', requestId: 'REQ-5D1B02AC',
      description: '用户在知识问答会话中提交查询，系统完成检索并生成带来源引用的回答。审计日志仅关联会话编号，不复制对话正文。',
      changes: [['会话状态', '等待提问', '已生成回答'], ['引用来源', '—', '3 份文档']], error: '',
    },
    {
      id: 'AUD-20260818-0124', time: '2026-08-18 10:42:19', operator: '系统任务', account: 'system', module: 'document', action: '更新文档分类', object: 'T90000 硬件规格', objectType: 'DOC-000986', result: 'success', ip: '127.0.0.1', requestId: 'REQ-3BB89210',
      description: '自动分类器完成文档分类，并将分类结果写入文档元数据。',
      changes: [['文档分类', '待分类', '产品规格'], ['文档状态', '处理中', '可检索']], error: '',
    },
    {
      id: 'AUD-20260818-0123', time: '2026-08-18 10:21:06', operator: '薛文李', account: 'xuewenli', module: 'config', action: '修改小版本', object: 'AE / V7 / 7.0.3', objectType: 'VERSION-703', result: 'success', ip: '10.21.136.178', requestId: 'REQ-9C42E132',
      description: '管理员修改了知识查询可选的小版本名称，已关联文档继续保留版本标识。',
      changes: [['版本名称', '7.0.3', '7.0.3 正式版'], ['状态', '启用', '启用']], error: '',
    },
    {
      id: 'AUD-20260818-0122', time: '2026-08-18 09:54:33', operator: '王强', account: 'wangqiang', module: 'document', action: '撤回文档', object: '旧版部署操作手册', objectType: 'DOC-000742', result: 'failed', ip: '10.21.136.165', requestId: 'REQ-2F913DC4',
      description: '提交者尝试撤回文档，系统校验发现该文档由其他用户提交，因此未执行撤回。',
      changes: [], error: '操作未执行：当前用户不是该文档的提交者。文档状态保持“可检索”。',
    },
    {
      id: 'AUD-20260818-0121', time: '2026-08-18 09:31:20', operator: '薛文李', account: 'xuewenli', module: 'user', action: '停用用户', object: '赵磊', objectType: 'USER-000025', result: 'success', ip: '10.21.136.178', requestId: 'REQ-7A6E5C01',
      description: '管理员停用系统账号。用户的历史对话、提交文档和飞书绑定关系继续保留。',
      changes: [['账号状态', '正常', '已停用'], ['登录能力', '允许登录', '禁止登录']], error: '',
    },
  ];
  const moduleLabels = { query: '知识查询', document: '文档管理', config: '系统配置', user: '用户管理', task: '处理任务', login: '用户登录' };
  const scopeCounts = { all: 126, document: 62, config: 18, user: 12, failed: 3 };
  const rows = page.querySelector('[data-audit-rows]');
  const empty = page.querySelector('[data-audit-empty]');
  const resultCount = page.querySelector('[data-audit-result-count]');
  const keyword = page.querySelector('[data-audit-keyword]');
  const moduleFilter = page.querySelector('[data-audit-module]');
  const resultFilter = page.querySelector('[data-audit-result]');
  const startDate = page.querySelector('[data-audit-start]');
  const endDate = page.querySelector('[data-audit-end]');
  const scopeButtons = Array.from(page.querySelectorAll('[data-audit-scope]'));
  const drawer = document.querySelector('[data-audit-drawer]');
  const backdrop = document.querySelector('[data-audit-drawer-backdrop]');
  const closeButtons = [drawer.querySelector('[data-audit-drawer-close]'), drawer.querySelector('[data-audit-close]')];
  const toast = document.querySelector('[data-toast]');
  let activeScope = 'all';
  let activeLog = null;
  let lastTrigger = null;
  let toastTimer;

  const showToast = (text) => {
    window.clearTimeout(toastTimer);
    toast.textContent = text;
    toast.hidden = false;
    toastTimer = window.setTimeout(() => { toast.hidden = true; }, 2400);
  };

  const currentLogs = () => {
    const value = keyword.value.trim().toLowerCase();
    return logs.filter((log) => {
      const day = log.time.slice(0, 10);
      const scopeMatch = activeScope === 'all' || (activeScope === 'failed' ? log.result === 'failed' : log.module === activeScope);
      return scopeMatch
        && (!value || `${log.id}${log.operator}${log.account}${log.object}${log.action}`.toLowerCase().includes(value))
        && (moduleFilter.value === 'all' || log.module === moduleFilter.value)
        && (resultFilter.value === 'all' || log.result === resultFilter.value)
        && (!startDate.value || day >= startDate.value)
        && (!endDate.value || day <= endDate.value);
    });
  };

  const renderRows = () => {
    if (startDate.value && endDate.value && startDate.value > endDate.value) {
      showToast('开始日期不能晚于结束日期。');
      return;
    }
    const visible = currentLogs();
    rows.innerHTML = '';
    visible.forEach((log) => {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td><div class="audit-time-cell"><strong>${log.time}</strong><small>${log.id}</small></div></td>
        <td><div class="audit-operator-cell"><strong>${log.operator}</strong><small>${log.account}</small></div></td>
        <td><span class="audit-module-tag ${log.module}">${moduleLabels[log.module]}</span></td>
        <td>${log.action}</td>
        <td><div class="audit-object-cell"><strong>${log.object}</strong><small>${log.objectType}</small></div></td>
        <td><span class="audit-result-pill ${log.result}">${log.result === 'success' ? '成功' : '失败'}</span></td>
        <td>${log.ip}</td>
        <td><button class="table-action" type="button" aria-label="查看审计日志：${log.id}">查看详情</button></td>`;
      const action = row.querySelector('.table-action');
      action.addEventListener('click', () => openDrawer(log, action));
      rows.append(row);
    });
    empty.hidden = visible.length > 0;
    resultCount.textContent = `当前显示 ${visible.length} 条，共 ${scopeCounts[activeScope]} 条${activeScope === 'all' ? '今日日志' : activeScope === 'failed' ? '失败日志' : moduleLabels[activeScope] + '日志'}`;
  };

  const renderDrawer = () => {
    if (!activeLog) return;
    drawer.querySelector('[data-audit-drawer-title]').textContent = activeLog.id;
    drawer.querySelector('[data-audit-drawer-result]').innerHTML = `<span class="audit-result-pill ${activeLog.result}">${activeLog.result === 'success' ? '成功' : '失败'}</span>`;
    drawer.querySelector('[data-audit-drawer-action]').textContent = activeLog.action;
    drawer.querySelector('[data-audit-drawer-object]').textContent = `${activeLog.object} · ${activeLog.objectType}`;
    drawer.querySelector('[data-audit-drawer-operator]').textContent = activeLog.operator;
    drawer.querySelector('[data-audit-drawer-account]').textContent = activeLog.account;
    drawer.querySelector('[data-audit-drawer-time]').textContent = activeLog.time;
    drawer.querySelector('[data-audit-drawer-ip]').textContent = activeLog.ip;
    drawer.querySelector('[data-audit-drawer-module]').textContent = moduleLabels[activeLog.module];
    drawer.querySelector('[data-audit-drawer-request]').textContent = activeLog.requestId;
    drawer.querySelector('[data-audit-description]').textContent = activeLog.description;
    const changeSection = drawer.querySelector('[data-audit-change-section]');
    changeSection.hidden = activeLog.changes.length === 0;
    drawer.querySelector('[data-audit-changes]').innerHTML = activeLog.changes.map(([field, before, after]) => `<div class="audit-change-row"><b>${field}</b><span>变更前：${before}</span><span>变更后：${after}</span></div>`).join('');
    const errorSection = drawer.querySelector('[data-audit-error-section]');
    errorSection.hidden = !activeLog.error;
    drawer.querySelector('[data-audit-error]').textContent = activeLog.error;
  };

  const openDrawer = (log, triggerElement) => {
    activeLog = log;
    lastTrigger = triggerElement;
    renderDrawer();
    backdrop.hidden = false;
    drawer.hidden = false;
    document.body.style.overflow = 'hidden';
    drawer.querySelector('[data-audit-drawer-close]').focus();
  };

  const closeDrawer = () => {
    drawer.hidden = true;
    backdrop.hidden = true;
    document.body.style.overflow = '';
    if (lastTrigger) lastTrigger.focus();
  };

  scopeButtons.forEach((button) => {
    button.addEventListener('click', () => {
      activeScope = button.dataset.auditScope;
      scopeButtons.forEach((candidate) => {
        const active = candidate === button;
        candidate.classList.toggle('active', active);
        candidate.setAttribute('aria-pressed', String(active));
      });
      renderRows();
    });
  });
  page.querySelector('[data-audit-search]').addEventListener('click', renderRows);
  keyword.addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); renderRows(); } });
  page.querySelector('[data-audit-clear]').addEventListener('click', () => {
    keyword.value = '';
    moduleFilter.value = 'all';
    resultFilter.value = 'all';
    startDate.value = '2026-08-18';
    endDate.value = '2026-08-18';
    activeScope = 'all';
    scopeButtons.forEach((button) => {
      const active = button.dataset.auditScope === 'all';
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    renderRows();
  });
  page.querySelector('[data-audit-export]').addEventListener('click', () => {
    const visible = currentLogs();
    const csv = ['日志编号,操作时间,操作者,账号,业务模块,操作,操作对象,结果,来源IP', ...visible.map((log) => [log.id, log.time, log.operator, log.account, moduleLabels[log.module], log.action, log.object, log.result === 'success' ? '成功' : '失败', log.ip].map((item) => `"${String(item).replaceAll('"', '""')}"`).join(','))].join('\n');
    const url = URL.createObjectURL(new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'audit-logs-2026-08-18.csv';
    link.click();
    URL.revokeObjectURL(url);
    showToast(`已导出 ${visible.length} 条当前筛选结果。`);
  });
  closeButtons.forEach((button) => button.addEventListener('click', closeDrawer));
  backdrop.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !drawer.hidden) closeDrawer(); });
  drawer.querySelector('[data-audit-copy]').addEventListener('click', () => {
    if (!activeLog) return;
    navigator.clipboard?.writeText(activeLog.id).catch(() => {});
    showToast(`已复制日志编号 ${activeLog.id}`);
  });

  renderRows();
});

document.addEventListener('DOMContentLoaded', () => {
  const page = document.querySelector('[data-pending-classification]');
  if (!page) return;

  let documents = [
    { id: 'DOC-000991', title: 'TDA 现场问题处理记录（8月）', source: 'feishu', sourceLabel: '飞书文档', candidate: 'SEG 案件 / 测试文档', reason: 'category', reasonLabel: '分类不明确', reasonDetail: '内容同时包含问题处理过程和测试验证记录', submitter: '张敏', submittedAt: '2026-08-18 09:46', waiting: '2 小时', category: '', product: 'TDA', version: 'V7 / 7.0.3', summary: '文档包含客户问题现象、处理过程和验证结果，分类器无法在“SEG 案件”和“测试文档”之间可靠选择。', evidence: '原文摘录：升级至 7.0.3 后 Analyzer 启动失败；现场调整配置后恢复，并补充执行了升级回归验证。' },
    { id: 'DOC-000990', title: 'AE V7 功能变化说明', source: 'local', sourceLabel: '本地文件', candidate: '产品功能', reason: 'version', reasonLabel: '产品版本不明确', reasonDetail: '正文只出现 V7，未标明具体小版本', submitter: '李伟', submittedAt: '2026-08-18 08:32', waiting: '3 小时', category: '产品功能', product: 'AE', version: '', summary: '文档内容符合产品功能说明，但只标注大版本 V7，无法确定是否适用于 7.0.2、7.0.3 或全部 V7 版本。', evidence: '原文摘录：V7 新增策略批量导入能力，并优化任务执行结果展示。' },
    { id: 'DOC-000989', title: '客户交流材料 2026', source: 'feishu', sourceLabel: '飞书文档', candidate: '白皮书 / 无关', reason: 'relevance', reasonLabel: '相关性不明确', reasonDetail: '包含产品介绍，也包含大量会议安排', submitter: '王强', submittedAt: '2026-08-17 17:20', waiting: '18 小时', category: '', product: '', version: '', summary: '文档同时包含产品能力介绍和内部会议安排，分类器无法确认整篇文档是否适合作为知识来源。', evidence: '原文摘录：本次交流介绍 AE 的部署形态、主要能力；后续章节为参会人、会议时间和分工安排。' },
    { id: 'DOC-000987', title: '国产化环境适配说明（草稿）', source: 'local', sourceLabel: '本地文件', candidate: '部署文档 / 开发设计', reason: 'category', reasonLabel: '分类不明确', reasonDetail: '同时描述部署限制和适配实现', submitter: '陈涛', submittedAt: '2026-08-17 15:08', waiting: '20 小时', category: '', product: 'AE', version: '全部版本', summary: '文档包含国产化环境部署条件和适配实现细节，分类器给出的两个候选接近。', evidence: '原文摘录：在麒麟环境部署时需要调整服务启动参数；适配层通过兼容接口处理目录差异。' },
    { id: 'DOC-000985', title: 'T90000 配置参数补充', source: 'feishu', sourceLabel: '飞书文档', candidate: '产品规格', reason: 'version', reasonLabel: '产品版本不明确', reasonDetail: '未发现适用的软件版本', submitter: '赵磊', submittedAt: '2026-08-17 11:42', waiting: '1 天', category: '产品规格', product: 'TDA', version: '', summary: '文档内容符合硬件规格，但未说明这些参数从哪个软件版本开始适用。', evidence: '原文摘录：T90000 推荐内存为 256 GB，系统盘采用 RAID1，数据盘根据节点容量规划。' }
  ];

  const rows = page.querySelector('[data-pending-rows]');
  const empty = page.querySelector('[data-pending-empty]');
  const resultCount = page.querySelector('[data-pending-result-count]');
  const total = page.querySelector('[data-pending-total]');
  const categoryCount = page.querySelector('[data-pending-category-count]');
  const versionCount = page.querySelector('[data-pending-version-count]');
  const relevanceCount = page.querySelector('[data-pending-relevance-count]');
  const keyword = page.querySelector('[data-pending-keyword]');
  const reasonFilter = page.querySelector('[data-pending-reason]');
  const sourceFilter = page.querySelector('[data-pending-source]');
  const drawer = document.querySelector('[data-pending-drawer]');
  const backdrop = document.querySelector('[data-pending-drawer-backdrop]');
  const toast = document.querySelector('[data-toast]');
  const category = drawer.querySelector('[data-pending-category]');
  const product = drawer.querySelector('[data-pending-product]');
  const version = drawer.querySelector('[data-pending-version]');
  let activeDocument = null;
  let lastTrigger = null;
  let toastTimer;

  const showToast = (text) => {
    window.clearTimeout(toastTimer);
    toast.textContent = text;
    toast.hidden = false;
    toastTimer = window.setTimeout(() => { toast.hidden = true; }, 2600);
  };

  const visibleDocuments = () => {
    const value = keyword.value.trim().toLowerCase();
    return documents.filter((item) => (!value || `${item.title}${item.submitter}`.toLowerCase().includes(value))
      && (reasonFilter.value === 'all' || item.reason === reasonFilter.value)
      && (sourceFilter.value === 'all' || item.source === sourceFilter.value));
  };

  const renderRows = () => {
    const visible = visibleDocuments();
    rows.innerHTML = '';
    visible.forEach((item) => {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td><div class="pending-name-cell"><strong>${item.title}</strong><small>${item.id}</small></div></td>
        <td><span class="pending-source-tag ${item.source}">${item.sourceLabel}</span></td>
        <td><span class="pending-candidate-tag ${item.category ? '' : 'uncertain'}">${item.candidate}</span></td>
        <td><div class="pending-reason-cell"><strong>${item.reasonLabel}</strong><small>${item.reasonDetail}</small></div></td>
        <td>${item.submitter}</td><td>${item.waiting}</td>
        <td><button class="table-action" type="button" aria-label="确认分类：${item.title}">去确认</button></td>`;
      const action = row.querySelector('.table-action');
      action.addEventListener('click', () => openDrawer(item, action));
      rows.append(row);
    });
    empty.hidden = visible.length > 0;
    resultCount.textContent = `当前显示 ${visible.length} 条，共 ${documents.length} 条待确认文档`;
    total.textContent = String(documents.length);
    categoryCount.textContent = String(documents.filter((item) => item.reason === 'category').length);
    versionCount.textContent = String(documents.filter((item) => item.reason === 'version').length);
    relevanceCount.textContent = String(documents.filter((item) => item.reason === 'relevance').length);
  };

  const renderDrawer = () => {
    if (!activeDocument) return;
    drawer.querySelector('[data-pending-drawer-title]').textContent = activeDocument.title;
    drawer.querySelector('[data-pending-detail-source]').textContent = activeDocument.sourceLabel;
    drawer.querySelector('[data-pending-detail-submitter]').textContent = activeDocument.submitter;
    drawer.querySelector('[data-pending-detail-time]').textContent = activeDocument.submittedAt;
    drawer.querySelector('[data-pending-detail-reason]').textContent = activeDocument.reasonLabel;
    drawer.querySelector('[data-pending-summary-copy]').textContent = activeDocument.summary;
    drawer.querySelector('[data-pending-evidence]').textContent = activeDocument.evidence;
    category.value = activeDocument.category;
    product.value = activeDocument.product;
    version.value = activeDocument.version;
  };

  const openDrawer = (item, trigger) => {
    activeDocument = item;
    lastTrigger = trigger;
    renderDrawer();
    backdrop.hidden = false;
    drawer.hidden = false;
    document.body.style.overflow = 'hidden';
    drawer.querySelector('[data-pending-drawer-close]').focus();
  };

  const closeDrawer = () => {
    drawer.hidden = true;
    backdrop.hidden = true;
    document.body.style.overflow = '';
    if (lastTrigger?.isConnected) lastTrigger.focus();
  };

  const finishDocument = (message) => {
    documents = documents.filter((item) => item.id !== activeDocument.id);
    closeDrawer();
    renderRows();
    showToast(message);
  };

  page.querySelector('[data-pending-search]').addEventListener('click', renderRows);
  keyword.addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); renderRows(); } });
  page.querySelector('[data-pending-clear]').addEventListener('click', () => {
    keyword.value = '';
    reasonFilter.value = 'all';
    sourceFilter.value = 'all';
    renderRows();
  });
  drawer.querySelector('[data-pending-drawer-close]').addEventListener('click', closeDrawer);
  backdrop.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !drawer.hidden) closeDrawer(); });
  drawer.querySelector('[data-pending-confirm]').addEventListener('click', () => {
    if (!category.value) {
      category.focus();
      showToast('请先选择文档分类。');
      return;
    }
    finishDocument(`已确认“${activeDocument.title}”，文档进入后续处理。`);
  });
  drawer.querySelector('[data-pending-unrelated]').addEventListener('click', () => finishDocument(`已将“${activeDocument.title}”标记为无关，不进入知识库。`));
  drawer.querySelector('[data-pending-reclassify]').addEventListener('click', () => finishDocument(`已重新提交“${activeDocument.title}”的自动分类任务。`));

  renderRows();
});

document.addEventListener('DOMContentLoaded', () => {
  const page = document.querySelector('[data-profile-settings]');
  if (!page) return;

  const drawer = document.querySelector('[data-profile-drawer]');
  const backdrop = document.querySelector('[data-profile-drawer-backdrop]');
  const toast = document.querySelector('[data-toast]');
  const accountNote = page.querySelector('[data-profile-account-note]');
  const passwordTag = page.querySelector('[data-profile-password-tag]');
  const passwordEmpty = page.querySelector('[data-profile-password-empty]');
  const setPasswordButton = page.querySelector('[data-profile-set-password]');
  const connectionStatus = page.querySelector('[data-profile-connection-status]');
  const connectedView = page.querySelector('[data-profile-connected-view]');
  const unconnectedView = page.querySelector('[data-profile-unconnected-view]');
  const connectionNote = page.querySelector('[data-profile-connection-note]');
  const reauthorizeButton = page.querySelector('[data-profile-reauthorize]');
  const bindButton = page.querySelector('[data-profile-bind]');
  const unbindButton = page.querySelector('[data-profile-unbind]');
  const unbindHelp = page.querySelector('[data-profile-unbind-help]');
  const stateSwitch = page.querySelector('[data-profile-state]');
  const passwordInput = drawer.querySelector('[data-profile-password-input]');
  const passwordConfirm = drawer.querySelector('[data-profile-password-confirm]');
  const formError = drawer.querySelector('[data-profile-form-error]');
  let connectionState = 'connected';
  let passwordSet = false;
  let toastTimer;
  let lastTrigger = null;

  const showToast = (text) => {
    window.clearTimeout(toastTimer);
    toast.textContent = text;
    toast.hidden = false;
    toastTimer = window.setTimeout(() => { toast.hidden = true; }, 2600);
  };

  const render = () => {
    const connected = connectionState !== 'unbound';
    const expired = connectionState === 'expired';
    passwordTag.hidden = !passwordSet;
    passwordEmpty.hidden = passwordSet;
    accountNote.textContent = passwordSet
      ? '账号已经设置密码。飞书授权失效时，仍可以使用账号密码登录。'
      : '当前账号可以使用飞书登录。建议设置账号密码，以便飞书授权失效时继续登录。';
    connectedView.hidden = !connected;
    unconnectedView.hidden = connected;
    reauthorizeButton.hidden = !connected;
    bindButton.hidden = connected;
    unbindButton.hidden = !connected;
    unbindButton.disabled = !passwordSet;
    unbindHelp.hidden = !connected || passwordSet;
    connectionNote.textContent = expired
      ? '飞书授权已失效，暂时无法发现新的文档；已有知识不会受到影响。请重新授权。'
      : connected
        ? '飞书仅用于身份识别、发现你可见的文档和同步你已提交的文档。'
      : '连接飞书后，才可以从自己的飞书文档中选择内容提交到知识库。';
    connectionStatus.className = `profile-connection-pill ${expired ? 'expired' : (connected ? 'connected' : 'unbound')}`;
    connectionStatus.querySelector('span').textContent = expired ? '授权已失效' : (connected ? '已连接' : '未连接');
    stateSwitch.value = connectionState;
  };

  const openPasswordDrawer = (trigger) => {
    lastTrigger = trigger;
    drawer.hidden = false;
    backdrop.hidden = false;
    document.body.style.overflow = 'hidden';
    formError.hidden = true;
    passwordInput.value = '';
    passwordConfirm.value = '';
    passwordInput.focus();
  };

  const closeDrawer = () => {
    drawer.hidden = true;
    backdrop.hidden = true;
    document.body.style.overflow = '';
    if (lastTrigger?.isConnected) lastTrigger.focus();
  };

  setPasswordButton.addEventListener('click', () => openPasswordDrawer(setPasswordButton));
  drawer.querySelector('[data-profile-form-cancel]').addEventListener('click', closeDrawer);
  drawer.querySelector('[data-profile-drawer-close]').addEventListener('click', closeDrawer);
  backdrop.addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !drawer.hidden) closeDrawer(); });
  drawer.querySelector('[data-profile-password-form]').addEventListener('submit', (event) => {
    event.preventDefault();
    if (passwordInput.value.length < 8) {
      formError.textContent = '密码至少需要 8 位。';
      formError.hidden = false;
      passwordInput.focus();
      return;
    }
    if (passwordInput.value !== passwordConfirm.value) {
      formError.textContent = '两次输入的密码不一致。';
      formError.hidden = false;
      passwordConfirm.focus();
      return;
    }
    passwordSet = true;
    render();
    closeDrawer();
    showToast('登录密码已设置，现在可以解除飞书连接。');
  });
  reauthorizeButton.addEventListener('click', () => {
    connectionState = 'connected';
    render();
    showToast('飞书重新授权成功，原有知识不会受到影响。');
  });
  bindButton.addEventListener('click', () => {
    connectionState = 'connected';
    render();
    showToast('飞书连接成功，可以开始选择文档。');
  });
  unbindButton.addEventListener('click', () => {
    if (!passwordSet) return;
    if (!window.confirm('解除飞书连接后，将无法发现新的飞书文档。已有知识不会删除，确定继续吗？')) return;
    connectionState = 'unbound';
    render();
    showToast('飞书连接已解除，已有知识仍然保留。');
  });
  stateSwitch.addEventListener('change', () => {
    connectionState = stateSwitch.value;
    render();
    showToast(`已切换为“${stateSwitch.options[stateSwitch.selectedIndex].textContent}”演示状态。`);
  });

  render();
});
