/* Small record-management dialog; all writes go through the existing API client. */
(function () {
  'use strict';
  const api = window.SFA_API;
  const ar = () => document.documentElement.lang === 'ar';
  const tr = (en, arabic) => ar() ? arabic : en;
  const node = (tag, text) => { const n = document.createElement(tag); if (text) n.textContent = text; return n; };
  const dialog = node('dialog'); dialog.className = 'manage-dialog'; document.body.appendChild(dialog);
  const title = node('h2'); dialog.appendChild(title);
  const close = node('button', '×'); close.type = 'button'; close.className = 'manage-close'; close.setAttribute('aria-label', 'Close / إغلاق');
  close.onclick = () => dialog.close(); dialog.appendChild(close);
  const action = node('select'); action.setAttribute('aria-label', 'Operation / العملية'); dialog.appendChild(action);
  const notice = node('p'); dialog.appendChild(notice);
  const form = node('form'); form.className = 'manage-form'; dialog.appendChild(form);
  const fields = node('div'); fields.className = 'manage-fields'; form.appendChild(fields);
  const submit = node('button'); submit.type = 'submit'; submit.className = 'report-btn'; form.appendChild(submit);
  const reset = node('button', 'New record / سجل جديد'); reset.type = 'button'; reset.onclick = () => { api.beginNewOperation(); editing = null; fill(); output.textContent = ''; simulation.replaceChildren(); }; form.appendChild(reset);
  const output = node('pre'); output.setAttribute('role', 'status'); output.className = 'manage-output'; dialog.appendChild(output);
  const simulation = node('section'); simulation.className = 'sim-results'; simulation.setAttribute('aria-live', 'polite'); dialog.appendChild(simulation);
  const list = node('div'); list.className = 'manage-list'; dialog.appendChild(list);
  let farmId, editing = null, rows = [], renderToken = 0, busy = false;
  dialog.addEventListener('close', () => { renderToken++; simulation.replaceChildren(); });
  const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Amman', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
  // [field, English, Arabic, type, required]. Null optional numbers stay unknown, not zero.
  const date = ['date', 'Date', 'التاريخ', 'date', true];
  const quantity = ['quantity_kg', 'Quantity (kg)', 'الكمية (كغ)', 'number', true];
  const notes = ['notes', 'Notes', 'ملاحظات', 'text'];
  const definitions = {
    farm: [
      ['name', 'Farm name', 'اسم المزرعة', 'text', true], ['location', 'Location', 'الموقع', 'text', true],
      ['latitude', 'Latitude', 'خط العرض', 'number', true], ['longitude', 'Longitude', 'خط الطول', 'number', true],
      ['area_dunum', 'Area (dunum = 1,000 m²)', 'المساحة (دونم = ١٠٠٠ م²)', 'number', true],
      ['planting_date', 'Planting date', 'تاريخ الزراعة', 'date', true],
      ['crop_stage', 'Crop stage', 'مرحلة النمو', ['initial', 'development', 'mid_season', 'late_season'], true],
      ['establishment_method', 'Establishment method', 'طريقة الزراعة', ['unknown', 'transplanted', 'direct_seeded'], true],
      ['irrigation_efficiency', 'Verified irrigation efficiency (0–1)', 'كفاءة الري الموثقة (٠–١)', 'number'],
      ['effective_rain_fraction', 'Effective rain fraction (0–1)', 'نسبة المطر الفعال (٠–١)', 'number'],
      ['system_flow_liters_per_hour', 'System flow (L/hour)', 'تدفق النظام (لتر/ساعة)', 'number']
    ],
    expenses: [date, ['category', 'Category', 'الفئة', 'text', true], ['description', 'Description', 'الوصف', 'text', true], ['amount_jod', 'Amount (JOD)', 'المبلغ (دينار)', 'number', true]],
    irrigation: [date, ['volume_m3', 'Confirmed water applied (m³)', 'المياه المضافة المؤكدة (م³)', 'number', true], notes],
    harvests: [date, quantity, ['grade', 'Grade', 'الجودة', 'text'], notes],
    sales: [date, quantity, ['unit_price_jod', 'Unit price (JOD/kg)', 'سعر الوحدة (دينار/كغ)', 'number', true], ['buyer', 'Buyer', 'المشتري', 'text'], notes],
    seasons: [
      ['name', 'Season name', 'اسم الموسم', 'text', true], ['start_date', 'Start date', 'تاريخ البداية', 'date', true],
      ['end_date', 'End date', 'تاريخ النهاية', 'date'], ['is_active', 'Active season', 'الموسم النشط', 'checkbox'],
      ['expected_harvest_kg', 'Remaining marketable harvest (kg)', 'المحصول المتبقي القابل للبيع (كغ)', 'number'],
      ['assumed_sale_price_jod_per_kg', 'Expected price (JOD/kg)', 'السعر المتوقع (دينار/كغ)', 'number'],
      ['projected_costs_jod', 'Remaining expected costs (JOD)', 'التكاليف المتوقعة المتبقية (دينار)', 'number'],
      ['fertilizer_budget_jod', 'Fertilizer budget (JOD)', 'ميزانية السماد (دينار)', 'number'],
      ['water_available_liters', 'Allocated water (liters; blank = unknown)', 'المياه المخصصة (لتر؛ فارغ = غير معروف)', 'number'],
      ['water_period_start', 'Water allocation from (inclusive)', 'بداية فترة تخصيص المياه (شاملة)', 'date'],
      ['water_period_end', 'Water allocation until (inclusive)', 'نهاية فترة تخصيص المياه (شاملة)', 'date']
    ],
    simulate: [
      ['water_available_liters', 'Available water (L)', 'المياه المتاحة (لتر)', 'number'],
      ['expected_marketable_kg', 'Remaining marketable harvest (kg)', 'المحصول المتبقي القابل للبيع (كغ)', 'number'],
      ['sale_price_jod_per_kg', 'Expected price (JOD/kg)', 'السعر المتوقع (دينار/كغ)', 'number'],
      ['additional_costs_jod', 'Additional scenario costs (JOD)', 'تكاليف السيناريو الإضافية (دينار)', 'number']
    ]
  };
  const operations = [ ['newfarm', 'Create farm', 'إنشاء مزرعة'], ['editfarm', 'Edit farm', 'تعديل المزرعة'],
    ['expenses', 'Expenses', 'المصروفات'], ['irrigation', 'Irrigation records', 'سجلات الري'],
    ['harvests', 'Harvest records', 'سجلات الحصاد'], ['sales', 'Sales records', 'سجلات المبيعات'],
    ['seasons', 'Seasons & forecast inputs', 'المواسم ومدخلات التوقع'], ['simulate', 'What-if simulation', 'محاكاة ماذا لو'] ];
  const getMethods = { expenses: 'getExpenses', irrigation: 'getIrrigation', harvests: 'getHarvests', sales: 'getSales', seasons: 'getSeasons' };
  const createMethods = { expenses: 'createExpense', irrigation: 'recordIrrigation', harvests: 'recordHarvest', sales: 'recordSale', seasons: 'createSeason' };
  const updateMethods = { expenses: 'updateExpense', irrigation: 'updateIrrigation', harvests: 'updateHarvest', sales: 'updateSale', seasons: 'updateSeason' };
  const deleteMethods = { expenses: 'deleteExpense', irrigation: 'deleteIrrigation', harvests: 'deleteHarvest', sales: 'deleteSale', seasons: 'deleteSeason' };
  const definition = () => definitions[action.value.endsWith('farm') ? 'farm' : action.value];

  function fill(data = {}) {
    fields.replaceChildren();
    definition().forEach(([key, en, arabic, type, required]) => {
      const label = node('label', tr(en, arabic));
      const input = node(Array.isArray(type) ? 'select' : 'input'); input.name = key;
      if (Array.isArray(type)) type.forEach((value) => { const option = node('option', value); option.value = value; input.appendChild(option); });
      else input.type = type;
      input.required = !!required;
      if (type === 'number') { input.step = 'any'; if (!['latitude', 'longitude'].includes(key)) input.min = '0'; }
      if (type === 'checkbox') input.checked = data[key] == null ? true : data[key];
      else input.value = data[key] == null ? (type === 'date' && !['end_date', 'water_period_start', 'water_period_end'].includes(key) ? today() : Array.isArray(type) ? type[0] : '') : data[key];
      label.appendChild(input); fields.appendChild(label);
    });
    submit.textContent = action.value === 'simulate' ? tr('Run simulation (not saved)', 'تشغيل المحاكاة (دون حفظ)') : editing ? tr('Save changes', 'حفظ التغييرات') : tr('Add record', 'إضافة سجل');
  }

  async function render() {
    const token = ++renderToken, op = action.value;
    editing = null; rows = []; list.replaceChildren(); simulation.replaceChildren(); output.textContent = ''; fill();
    submit.disabled = !api.isLive() || (!farmId && op !== 'newfarm');
    notice.textContent = !api.isLive() ? tr('Read-only sample mode. Open the dashboard without ?demo=1 to save records.', 'وضع تجريبي للقراءة فقط. افتح اللوحة دون demo=1 لحفظ السجلات.') :
      op === 'simulate' ? tr('Hypothetical only. Does not change records or predict yield loss.', 'افتراضية فقط. لا تغير السجلات ولا تتنبأ بخسارة المحصول.') :
      op === 'seasons' ? tr('Enter water amount and both dates together, or leave all three blank. The dates must match the forecast period to calculate a water budget.', 'أدخل كمية المياه وتاريخي الفترة معاً، أو اترك الحقول الثلاثة فارغة. يجب أن تطابق الفترة فترة التوقع لحساب ميزانية المياه.') :
      tr('Tomato / drip irrigation. Financial summaries use the active season; expected harvest means remaining quantity. Blank inputs remain unknown.', 'طماطم / ري بالتنقيط. الملخص المالي للموسم النشط؛ المحصول المتوقع هو الكمية المتبقية. القيم الفارغة غير معروفة.');
    if (!api.isLive() || !farmId) return;
    try {
      if (op === 'editfarm') { const data = await api.getFarm(farmId); if (token === renderToken) fill(data); return; }
      if (!getMethods[op]) return;
      const data = await api[getMethods[op]](farmId);
      if (token !== renderToken) return;
      rows = data[op] || data.records || [];
      rows.forEach((row) => {
        const item = node('div'); item.className = 'manage-record';
        item.appendChild(node('span', (row.name || row.description || row.date || row.id) + (row.season_id ? ' · ' + row.season_id.slice(0, 8) : '') + (row.is_active ? tr(' · Active', ' · نشط') : '')));
        const edit = node('button', tr('Edit', 'تعديل')); edit.type = 'button';
        edit.onclick = () => { api.beginNewOperation(); editing = row; fill(row); output.textContent = ''; };
        const remove = node('button', tr('Delete', 'حذف')); remove.type = 'button';
        remove.onclick = async () => {
          if (!confirm(tr('Delete this record? This cannot be undone.', 'حذف هذا السجل؟ لا يمكن التراجع.'))) return;
          remove.disabled = true;
          try { await api[deleteMethods[op]](farmId, row.id); await render(); }
          catch (e) { output.textContent = e.message; remove.disabled = false; }
        };
        item.append(edit, remove); list.appendChild(item);
      });
    } catch (e) { output.textContent = e.message; }
  }

  form.onsubmit = async (event) => {
    event.preventDefault(); if (busy) return;
    const op = action.value, token = renderToken, requestFarm = farmId;
    const payload = {};
    definition().forEach(([key, , , type]) => {
      const input = form.elements.namedItem(key);
      if (type === 'checkbox') payload[key] = input.checked;
      else if (input.value === '') { if (op !== 'simulate') payload[key] = null; }
      else payload[key] = type === 'number' ? Number(input.value) : input.value;
    });
    if (editing && editing.season_id) payload.season_id = editing.season_id;
    if (op === 'simulate' && (!Object.keys(payload).length || Object.values(payload).some((v) => !Number.isFinite(v) || v < 0))) {
      simulation.replaceChildren(); output.textContent = window.SFA_SIMULATION.errorMessage({status: 422}, ar() ? 'ar' : 'en'); return;
    }
    busy = true; submit.disabled = action.disabled = reset.disabled = true;
    form.setAttribute('aria-busy', 'true'); simulation.replaceChildren(); output.textContent = tr('Working…', 'جارٍ التنفيذ…');
    try {
      let result;
      if (op === 'newfarm') result = await api.createFarm(payload);
      else if (op === 'editfarm') result = await api.updateFarm(farmId, payload);
      else if (op === 'simulate') result = await api.simulate(requestFarm, payload);
      else if (editing) result = await api[updateMethods[op]](farmId, editing.id, payload);
      else result = await api[createMethods[op]](farmId, payload);
      if (token !== renderToken) return;
      if (op === 'newfarm' || op === 'editfarm') { location.reload(); return; }
      if (op === 'simulate') {
        output.textContent = '';
        window.SFA_SIMULATION.render(simulation, result, ar() ? 'ar' : 'en');
      } else { await render(); output.textContent = tr('Saved. Dashboard refreshed.', 'تم الحفظ وتحديث اللوحة.'); }
    } catch (e) { if (token === renderToken) output.textContent = op === 'simulate' ? window.SFA_SIMULATION.errorMessage(e, ar() ? 'ar' : 'en') : e.message; }
    finally { busy = false; submit.disabled = action.disabled = reset.disabled = false; form.removeAttribute('aria-busy'); }
  };
  action.onchange = () => { api.beginNewOperation(); render(); };
  document.getElementById('btn-manage').onclick = () => {
    farmId = document.getElementById('farm-select').value;
    title.textContent = tr('Manage farm', 'إدارة المزرعة'); action.replaceChildren();
    operations.forEach(([key, en, arabic]) => { const option = node('option', tr(en, arabic)); option.value = key; action.appendChild(option); });
    action.value = farmId ? 'expenses' : 'newfarm'; render(); dialog.showModal();
  };
})();
