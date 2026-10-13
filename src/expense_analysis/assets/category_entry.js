export default function({parentElement, data, setStateValue}) {
  const root = parentElement.querySelector('.category-entry');
  const description = root.querySelector('[name=description]');
  const merchant = root.querySelector('[name=merchant]');
  const category = root.querySelector('[name=category]');
  const status = root.querySelector('[role=status]');
  const reset = root.querySelector('button');
  const list = root.querySelector('datalist');
  const normalize = value => value.trim().toLocaleLowerCase().replace(/\s+/g, ' ');
  if (!root.dataset.ready) {
    for (const value of data.categories) {
      const option = document.createElement('option');
      option.value = value;
      list.append(option);
    }
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
    if (!composing) timer = setTimeout(predict, 300);
  };
  for (const field of [description, merchant]) {
    field.oninput = schedule;
    field.oncompositionstart = () => { composing = true; clearTimeout(timer); };
    field.oncompositionend = () => { composing = false; schedule(); };
    field.onblur = () => { if (!composing) predict(); };
  }
  category.oninput = () => {
    clearTimeout(timer);
    root.dataset.manual = 'true';
    status.textContent = 'Your choice — automatic updates paused for this entry';
    publish();
  };
  reset.onclick = () => { root.dataset.manual = 'false'; predict(); };
  return () => { clearTimeout(timer); };
}
