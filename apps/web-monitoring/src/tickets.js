export const STORAGE_KEY = 'ferqueue.tickets.v1';
export const MAX_HISTORY = 500;
export const CATEGORIES = Object.freeze([
  { code: 'I', label: 'Sepeda' },
  { code: 'II', label: 'Sepeda motor' },
  { code: 'III', label: 'Sepeda motor besar / roda tiga' },
  { code: 'IV A', label: 'Mobil penumpang' },
  { code: 'IV B', label: 'Mobil barang' },
  { code: 'V A', label: 'Bus / kendaraan penumpang' },
  { code: 'V B', label: 'Truk / kendaraan barang' },
  { code: 'VI A', label: 'Bus besar / kendaraan penumpang' },
  { code: 'VI B', label: 'Truk / kendaraan barang' },
  { code: 'VII', label: 'Kendaraan barang besar' },
  { code: 'VIII', label: 'Kendaraan barang besar' },
  { code: 'IX', label: 'Kendaraan barang khusus' },
]);

export const formatWeight = weight => new Intl.NumberFormat('id-ID').format(weight);
export const categoryInfo = code => CATEGORIES.find(category => category.code === code);
export function normalizePlate(value) {
  const text = String(value ?? '').trim().toUpperCase();
  const match = text.match(/^([A-Z]{1,2})\s*([1-9]\d{0,3})\s*([A-Z]{0,3})$/);
  return match ? [match[1], match[2], match[3]].filter(Boolean).join(' ') : text.replace(/\s+/g, ' ');
}
export function validateInspection({ plate, weight, category }) {
  const errors = {};
  if (!/^[A-Z]{1,2} [1-9]\d{0,3}(?: [A-Z]{1,3})?$/.test(normalizePlate(plate))) {
    errors.plate = 'Isi nomor polisi yang valid, contoh B 9241 KXS.';
  }
  if (!Number.isInteger(weight) || weight < 1 || weight > 200000) {
    errors.weight = 'Masukkan berat antara 1–200.000 kg dalam bilangan bulat.';
  }
  if (!categoryInfo(category)) errors.category = 'Pilih golongan kendaraan terlebih dahulu.';
  return errors;
}
function dayKey(date) {
  const parts = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Jakarta', year: '2-digit', month: '2-digit', day: '2-digit' }).formatToParts(date);
  return ['year', 'month', 'day'].map(key => parts.find(part => part.type === key).value).join('');
}
export function createTicket(inspection, history = [], now = new Date()) {
  const errors = validateInspection(inspection);
  if (Object.keys(errors).length) throw new Error(Object.values(errors)[0]);
  if (Number.isNaN(now.getTime())) throw new Error('Waktu pemeriksaan tidak valid.');
  const prefix = `FQ-${dayKey(now)}-`;
  const sequence = history.reduce((max, ticket) => {
    if (!ticket.number?.startsWith(prefix)) return max;
    const suffix = ticket.number.slice(prefix.length);
    return /^\d+$/.test(suffix) ? Math.max(max, Number(suffix)) : max;
  }, 0) + 1;
  return Object.freeze({
    version: 1,
    number: prefix + String(sequence).padStart(3, '0'),
    plate: normalizePlate(inspection.plate),
    weight: inspection.weight,
    category: inspection.category,
    createdAt: now.toISOString(),
    gate: '01',
    source: 'manual-demo',
  });
}
export function parseHistory(raw) {
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const seen = new Set();
    return parsed.filter(ticket => {
      if (!ticket || ticket.version !== 1 || ticket.source !== 'manual-demo' || ticket.gate !== '01') return false;
      if (typeof ticket.number !== 'string' || !/^FQ-\d{6}-\d{3,6}$/.test(ticket.number) || seen.has(ticket.number)) return false;
      if (typeof ticket.plate !== 'string' || Object.keys(validateInspection(ticket)).length) return false;
      if (typeof ticket.createdAt !== 'string' || Number.isNaN(Date.parse(ticket.createdAt))) return false;
      seen.add(ticket.number);
      return true;
    }).sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt)).slice(0, MAX_HISTORY);
  } catch {
    return [];
  }
}
