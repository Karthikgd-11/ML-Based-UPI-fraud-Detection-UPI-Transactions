/* India-only cascading State -> District -> Sub-District selector.
   Source: Local Government Directory (LGD) sub-district export mirrored by planemad gist.
   The CSV is fetched at runtime so the project does not need a 6,000+ row JS bundle. */
(function () {
  const DATA_URL = 'https://gist.githubusercontent.com/planemad/b2195c7feb506f8436659f36da1e58af/raw/india-subdistricts-lgd.csv';

  function parseCSV(text) {
    const lines = text.split(/\r?\n/).filter(Boolean);
    if (!lines.length) return [];
    // This LGD export uses comma-separated fields and does not require complex quoted parsing
    // for the administrative names used by the selector.
    return lines.slice(1).map(line => {
      const cells = line.split(',');
      return {
        stateCode: (cells[1] || '').trim(),
        state: (cells[2] || '').trim(),
        districtCode: (cells[3] || '').trim(),
        district: (cells[4] || '').trim(),
        subdistrict: (cells[7] || '').trim()
      };
    }).filter(x => x.state && x.district && x.subdistrict);
  }

  function uniqueSorted(values) {
    return [...new Set(values)].sort((a,b) => a.localeCompare(b));
  }

  function fill(select, values, placeholder) {
    select.innerHTML = '';
    const first = document.createElement('option');
    first.value = '';
    first.textContent = placeholder;
    first.disabled = true;
    first.selected = true;
    select.appendChild(first);
    values.forEach(value => {
      const o = document.createElement('option');
      o.value = value;
      o.textContent = value;
      select.appendChild(o);
    });
    select.disabled = values.length === 0;
  }

  window.initIndiaLocationSelector = async function (config) {
    const stateEl = document.getElementById(config.stateId);
    const districtEl = document.getElementById(config.districtId);
    const subEl = document.getElementById(config.subdistrictId);
    const errorEl = config.errorId ? document.getElementById(config.errorId) : null;
    if (!stateEl || !districtEl || !subEl) return;

    stateEl.disabled = districtEl.disabled = subEl.disabled = true;
    fill(stateEl, [], 'Loading Indian states...');
    fill(districtEl, [], 'Select State first');
    fill(subEl, [], 'Select District first');

    try {
      const response = await fetch(DATA_URL, {cache: 'no-store'});
      if (!response.ok) throw new Error('Location data could not be loaded');
      const rows = parseCSV(await response.text());
      if (!rows.length) throw new Error('No location records found');

      const states = uniqueSorted(rows.map(x => x.state));
      stateEl.disabled = false;
      fill(stateEl, states, 'Select State');
      if (config.initialState && states.includes(config.initialState)) stateEl.value = config.initialState;

      function updateDistricts() {
        const state = stateEl.value;
        const districts = uniqueSorted(rows.filter(x => x.state === state).map(x => x.district));
        fill(districtEl, districts, state ? 'Select District' : 'Select State first');
        districtEl.disabled = !state;
        fill(subEl, [], 'Select District first');
        subEl.disabled = true;
        if (config.initialDistrict && districts.includes(config.initialDistrict)) {
          districtEl.value = config.initialDistrict;
          updateSubdistricts();
        }
      }

      function updateSubdistricts() {
        const state = stateEl.value, district = districtEl.value;
        const subs = uniqueSorted(rows.filter(x => x.state === state && x.district === district).map(x => x.subdistrict));
        fill(subEl, subs, district ? 'Select Sub-District' : 'Select District first');
        subEl.disabled = !district;
        if (config.initialSubdistrict && subs.includes(config.initialSubdistrict)) subEl.value = config.initialSubdistrict;
      }

      stateEl.addEventListener('change', updateDistricts);
      districtEl.addEventListener('change', updateSubdistricts);
      updateDistricts();
    } catch (err) {
      fill(stateEl, [], 'Location data unavailable');
      if (errorEl) errorEl.textContent = 'Could not load India location data. Please check your internet connection and refresh.';
      else console.error(err);
    }
  };
})();
