export const STORAGE_KEY = 'ferqueue.tickets.v1';
export const MAX_HISTORY = 500;
export const CATEGORIES = Object.freeze([
  { code: 'A', label: 'Mobil penumpang' },
  { code: 'B', label: 'Bus penumpang' },
  { code: 'C', label: 'Truk barang' },
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

export const formatWeight = (weight, fractionDigits = 2) => {
  if (weight === null || weight === undefined || weight === '' || Number.isNaN(Number(weight))) {
    return '0,00';
  }
  return new Intl.NumberFormat('id-ID', {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(Number(weight));
};
export const categoryInfo = code => {
  if (!code) return undefined;
  const trimmed = String(code).trim().toUpperCase();
  return CATEGORIES.find(category => category.code.toUpperCase() === trimmed);
};
export function normalizeDriver(value) {
  return String(value ?? '').trim().replace(/\s+/g, ' ');
}
export const normalizePlate = normalizeDriver;
export function validateInspection({ driver, plate, weight, category }) {
  const errors = {};
  const name = normalizeDriver(driver ?? plate);
  if (!name || name.length < 2 || name.length > 60 || !/^[A-Za-zÀ-ÿ\s'.-]{2,60}$/.test(name)) {
    errors.driver = 'Isi nama pengemudi yang valid (minimal 2 huruf, hanya huruf dan tanda baca).';
    errors.plate = errors.driver;
  }
  if (typeof weight !== 'number' || Number.isNaN(weight) || weight <= 0 || weight > 200000) {
    errors.weight = 'Masukkan berat antara 0,01–200.000 kg.';
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
  const driverName = normalizeDriver(inspection.driver ?? inspection.plate);
  return Object.freeze({
    version: 1,
    number: prefix + String(sequence).padStart(3, '0'),
    driver: driverName,
    plate: driverName,
    weight: inspection.weight,
    category: inspection.category,
    length: inspection.length ?? '7,20',
    width: inspection.width ?? '2,50',
    height: inspection.height ?? '3,10',
    vehicleStatus: inspection.vehicleStatus === 'Anomali' ? 'Anomali' : 'Normal',
    createdAt: now.toISOString(),
    source: 'manual-demo',
  });
}
export function parseHistory(raw) {
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const seen = new Set();
    return parsed.filter(ticket => {
      if (!ticket || ticket.version !== 1 || ticket.source !== 'manual-demo') return false;
      if (typeof ticket.number !== 'string' || !/^FQ-\d{6}-\d{3,6}$/.test(ticket.number) || seen.has(ticket.number)) return false;
      if (typeof ticket.weight !== 'number') return false;
      const name = ticket.driver ?? ticket.plate;
      if (typeof name !== 'string' || Object.keys(validateInspection(ticket)).length) return false;
      if (typeof ticket.createdAt !== 'string' || Number.isNaN(Date.parse(ticket.createdAt))) return false;
      seen.add(ticket.number);
      return true;
    }).sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt)).slice(0, MAX_HISTORY);
  } catch {
    return [];
  }
}
