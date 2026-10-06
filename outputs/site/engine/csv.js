// A CSV reader that agrees with Python's `csv` module on the files in this repo.
//
// Not a general CSV library. It implements the dialect Python's `csv.reader`
// uses by default — comma delimiter, `"` quote character, a doubled quote
// inside a quoted field standing for one quote — which is the dialect
// `scripts/` writes and `rules/` and `data/reference/` are stored in. It
// deliberately does not guess at anything else: a file this cannot read is a
// file the two engines would read differently, and the right answer is to
// notice, not to cope.
//
// The three CSVs in rules/ that use quoting (actions.csv, communities.csv,
// events.csv) quote only to protect embedded commas; one field in actions.csv
// also carries a doubled quote. None of them has an embedded newline, but this
// handles them anyway, because a bank edited later might.

// Split CSV text into rows of string cells.
export function parseCsv(text) {
  // Strip a UTF-8 BOM: Python's open(encoding="utf-8") leaves one in the first
  // field name, and so would we, which would make every header lookup miss.
  let body = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  // Normalise line endings first, so \r\n and \n behave identically. Python's
  // csv reader is given newline="" and handles both; this is the same thing.
  body = body.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;
  let started = false; // has the current row any content at all?

  for (let i = 0; i < body.length; i += 1) {
    const ch = body[i];
    if (quoted) {
      if (ch === '"') {
        if (body[i + 1] === '"') {
          field += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        field += ch;
      }
      continue;
    }
    if (ch === '"') {
      quoted = true;
      started = true;
    } else if (ch === ',') {
      row.push(field);
      field = '';
      started = true;
    } else if (ch === '\n') {
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
      started = false;
    } else {
      field += ch;
      started = true;
    }
  }
  if (started || field !== '' || row.length) {
    row.push(field);
    rows.push(row);
  }
  // Python's csv.reader yields nothing for a trailing newline; a blank final
  // row here would become a row of empty strings and quietly corrupt a bank.
  return rows.filter((r) => !(r.length === 1 && r[0] === ''));
}

// Rows as objects keyed by the header row, the way csv.DictReader does it.
// A short row fills the missing keys with '' (DictReader uses None; every
// caller here treats both as "absent", and '' keeps the values strings).
export function parseCsvDicts(text) {
  const rows = parseCsv(text);
  if (rows.length === 0) return [];
  const header = rows[0];
  return rows.slice(1).map((cells) => {
    const record = {};
    header.forEach((name, index) => {
      record[name] = index < cells.length ? cells[index] : '';
    });
    return record;
  });
}
