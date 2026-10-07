/* Keep the original board list; open known tasks in separate detail pages. */
(() => {
  'use strict';
  const embedded = window.parent !== window;
  const dialog = document.getElementById('detail-dialog');
  const parentOrigin = new URL(document.baseURI).origin;
  const taskIDs = new Set();
  const pendingCopies = new Set();
  function collectTaskIDs(tasks) {
    if (!Array.isArray(tasks)) return;
    for (const task of tasks) {
      if (!task || typeof task !== 'object') continue;
      if (typeof task.id === 'string' && task.id.length > 0 && task.id.length < 200 && !/[\x00-\x1f\x7f]/.test(task.id)) taskIDs.add(task.id);
      collectTaskIDs(task.subtasks);
    }
  }
  try {collectTaskIDs(JSON.parse(document.getElementById('task-data')?.textContent || '[]'));}
  catch { /* Invalid source data leaves the original board behavior available. */ }
  function addCopyButtons() {
    if (!embedded) return;
    document.querySelectorAll('.task-row[data-task],.decision[data-decision]').forEach(card => {
      const id = card.dataset.task || card.dataset.decision;
      if (!taskIDs.has(id) || card.parentElement?.classList.contains('workbench-copy-card')) return;
      const wrapper = document.createElement('div');
      wrapper.className = 'workbench-copy-card';
      if (card.classList.contains('decision')) wrapper.classList.add('workbench-copy-decision');
      card.before(wrapper);wrapper.appendChild(card);
      const button = document.createElement('button');
      button.type = 'button';button.className = 'workbench-copy-html';
      button.dataset.copyTaskHtml = id;button.textContent = '复制 HTML 路径';
      button.title = '复制此任务本地 HTML 文件的绝对路径';
      wrapper.appendChild(button);
    });
  }
  addCopyButtons();
  const taskList = document.getElementById('task-list');
  if (embedded && taskList) new MutationObserver(addCopyButtons).observe(taskList,{childList:true,subtree:true});
  document.addEventListener('click',event => {
    if (!event.isTrusted || event.button !== 0) return;
    const copy = event.target?.closest?.('[data-copy-task-html]');
    if (embedded && copy && taskIDs.has(copy.dataset.copyTaskHtml)) {
      event.preventDefault();event.stopImmediatePropagation();
      const id = copy.dataset.copyTaskHtml;
      if (pendingCopies.has(id)) return;
      pendingCopies.add(id);
      document.querySelectorAll('[data-copy-task-html]').forEach(button => {
        if (button.dataset.copyTaskHtml === id) {button.disabled = true;button.textContent = '正在复制…';}
      });
      report();
      window.parent.postMessage({type:'task-board-copy-html',id},parentOrigin);
      return;
    }
    const trigger = event.target?.closest?.('[data-task]');
    const id = trigger?.dataset.task;
    if (!taskIDs.has(id)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    window.open(`/tasks/${encodeURIComponent(id)}`,'_blank','noopener');
  },true);
  function report() {
    if (!embedded) return;
    const busy = Boolean(pendingCopies.size || dialog?.open || document.activeElement?.matches('input,textarea,select,[contenteditable="true"]'));
    window.parent.postMessage({type:'task-board-state',busy},parentOrigin);
  }
  if (dialog) new MutationObserver(report).observe(dialog,{attributes:true,attributeFilter:['open']});
  window.addEventListener('message',event => {
    if (!embedded || event.source !== window.parent || event.origin !== parentOrigin || event.data?.type !== 'task-board-copy-html-result') return;
    const id = event.data.id;
    if (!pendingCopies.delete(id)) return;
    document.querySelectorAll('[data-copy-task-html]').forEach(button => {
      if (button.dataset.copyTaskHtml !== id) return;
      button.disabled = false;
      button.textContent = event.data.copied ? '已复制路径 ✓' : '复制 HTML 路径';
      if (event.data.copied) setTimeout(() => {if(button.isConnected)button.textContent = '复制 HTML 路径';},2500);
    });
    report();
  });
  document.addEventListener('focusin',report);
  document.addEventListener('focusout',() => queueMicrotask(report));
  window.addEventListener('pagehide',() => {
    if (embedded) window.parent.postMessage({type:'task-board-state',busy:false},parentOrigin);
  });
  const task = new URLSearchParams(location.search).get('task');
  if (taskIDs.has(task)) {
    const detailURL = `/tasks/${encodeURIComponent(task)}`;
    if (!embedded) location.replace(detailURL);
    else {
      // Old workbench deep links remain usable without opening an asynchronous popup.
      const hint = document.createElement('p');
      const link = document.createElement('a');
      link.href = detailURL;link.target = '_blank';link.rel = 'noopener noreferrer';
      link.className = 'text-button';link.textContent = '打开该任务的独立详情页 →';
      hint.appendChild(link);document.body.prepend(hint);
    }
  }
  if (embedded) window.parent.postMessage({type:'task-board-ready'},parentOrigin);
})();
