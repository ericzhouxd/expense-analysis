export default function({parentElement, data, setStateValue}) {
  const root = parentElement.querySelector('.category-entry');
  const description = root.querySelector('[name=description]');
  const merchant = root.querySelector('[name=merchant]');
  const category = root.querySelector('[name=category]');
  const status = root.querySelector('[role=status]');
  const reset = root.querySelector('.category-reset');
  const list = root.querySelector('[role=listbox]');
  const normalize = value => value.trim().toLocaleLowerCase().replace(/\s+/g, ' ');
  if (!root.dataset.ready) {
    const initial = data.initial || {};
    description.value = initial.description || '';
    merchant.value = initial.merchant || '';
    category.value = initial.category || 'Uncategorized';
    root.dataset.manual = initial.manual ? 'true' : 'false';
    root.dataset.ready = 'true';
  }
  let timer;
  let composing = false;
  const publish = () => setStateValue('entry', {
    description: description.value, merchant: merchant.value,
    category: category.value.trim() || 'Uncategorized', manual: root.dataset.manual === 'true'
  });
  const predict = () => {
    clearTimeout(timer);
    if (root.dataset.manual === 'true' || composing) return;
    const desc = normalize(description.value), shop = normalize(merchant.value);
    // Specific description rules take priority over a general merchant history.
    const rules = [...data.rules].sort((a,b) => b[0].length - a[0].length);
    const match = rules.find(([keyword]) => desc.includes(normalize(keyword)))
      || rules.find(([keyword]) => shop.includes(normalize(keyword)));
    const suggestion = match?.[1] || data.merchants[shop] || 'Uncategorized';
    category.value = suggestion;
    status.textContent = match ? 'Suggested from a keyword rule' : data.merchants[shop]
      ? 'Suggested from previous merchant choices' : 'No clear match yet — choose a category';
    publish();
  };
  const schedule = () => {
    clearTimeout(timer);
    publish(); // Form state is buffered locally until Save, including rapid submissions.
    if (!composing) predict();
  };
  for (const field of [description, merchant]) {
    field.oninput = schedule;
    field.oncompositionstart = () => { composing = true; clearTimeout(timer); };
    field.oncompositionend = () => { composing = false; schedule(); };
    field.onblur = () => { if (!composing) predict(); };
  }
  let highlighted = -1;
  let matches = [];
  const close = () => {
    list.hidden = true;
    category.setAttribute('aria-expanded', 'false');
    category.removeAttribute('aria-activedescendant');
  };
  const choose = value => {
    category.value = value;
    root.dataset.manual = 'true';
    status.textContent = 'Your choice — automatic updates paused for this entry';
    publish(); close(); category.focus(); close();
  };
  const show = (all = false) => {
    const query = normalize(category.value);
    matches = data.categories.filter(value => all || normalize(value).includes(query));
    if (query && !data.categories.some(value => normalize(value) === query)) matches.push(category.value.trim());
    list.replaceChildren(); highlighted = -1;
    matches.forEach((value, index) => {
      const option = document.createElement('div');
      option.id = `expense-category-${index}`;
      option.setAttribute('role', 'option');
      option.setAttribute('aria-selected', 'false');
      option.textContent = data.categories.includes(value) ? value : `Create “${value}”`;
      option.onpointerdown = event => { event.preventDefault(); choose(value); };
      list.append(option);
    });
    list.hidden = matches.length === 0;
    category.setAttribute('aria-expanded', String(!list.hidden));
  };
  const toggle = root.querySelector('.category-toggle');
  toggle.onpointerdown = event => event.preventDefault();
  toggle.onclick = () => { const wasOpen = !list.hidden; category.focus(); if (wasOpen) close(); else show(true); };
  category.onfocus = () => show(true);
  category.onblur = close;
  category.onkeydown = event => {
    if (event.isComposing) return;
    if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault();
      if (list.hidden) show(true);
      highlighted = Math.max(0, Math.min(matches.length - 1, highlighted + (event.key === 'ArrowDown' ? 1 : -1)));
      [...list.children].forEach((option, index) => option.setAttribute('aria-selected', String(index === highlighted)));
      const option = list.children[highlighted];
      if (option) { category.setAttribute('aria-activedescendant', option.id); option.scrollIntoView({block:'nearest'}); }
    } else if (event.key === 'Enter' && !list.hidden) {
      event.preventDefault(); event.stopPropagation();
      if (highlighted >= 0) choose(matches[highlighted]); else { publish(); close(); }
    } else if (event.key === 'Escape' && !list.hidden) {
      event.preventDefault(); event.stopPropagation(); close();
    }
  };
  category.oninput = () => {
    show();
    clearTimeout(timer);
    root.dataset.manual = 'true';
    status.textContent = 'Your choice — automatic updates paused for this entry';
    publish();
  };
  reset.onclick = () => { root.dataset.manual = 'false'; predict(); close(); };
  if (root.dataset.manual !== 'true') predict();
  return () => { clearTimeout(timer); };
}
