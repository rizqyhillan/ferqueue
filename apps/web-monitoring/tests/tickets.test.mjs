import test from 'node:test';
import assert from 'node:assert/strict';
import { createTicket, parseHistory, validateInspection, formatWeight } from '../static/tickets.js';

const inspection = { driver: 'Budi Santoso', weight: 8420, category: 'VI B' };
test('ticket numbers follow Jakarta calendar boundaries and continue after restored history', () => {
  const first = createTicket(inspection, [], new Date('2026-11-01T16:59:59Z'));
  const second = createTicket(inspection, [first], new Date('2026-11-01T17:00:00Z'));
  const third = createTicket(inspection, parseHistory(JSON.stringify([first, second])), new Date('2026-11-01T17:00:01Z'));
  assert.equal(first.number, 'FQ-261101-001');
  assert.equal(second.number, 'FQ-261102-001');
  assert.equal(third.number, 'FQ-261102-002');
  assert.equal(third.driver, 'Budi Santoso');
  assert.equal(third.plate, 'Budi Santoso');
  assert.equal(third.length, '7,20');
  assert.equal(third.width, '2,50');
  assert.equal(third.height, '3,10');
  assert.equal(third.vehicleStatus, 'Normal');
});
test('tickets cannot be issued with missing readings, invalid drivers, or unknown categories', () => {
  for (const change of [{ weight: null }, { weight: -20 }, { weight: 0 }, { weight: 200001 }, { driver: '' }, { driver: '<script>' }, { category: '' }, { category: 'fake' }]) {
    assert.throws(() => createTicket({ ...inspection, ...change }));
  }
  assert.deepEqual(validateInspection({ driver: 'Ahmad Yani', weight: 1, category: 'IV A' }), {});
  assert.deepEqual(validateInspection({ driver: 'Ahmad Yani', weight: 1.5, category: 'IV A' }), {});
});
test('malformed, tampered, and duplicate persisted records are ignored without losing valid tickets', () => {
  const valid = createTicket(inspection, [], new Date('2026-11-02T01:00:00Z'));
  const records = [null, valid, valid, { ...valid, number: 'bad' }, { ...valid, number: 'FQ-261102-002', weight: '8420' }, { ...valid, number: 'FQ-261102-003', category: '<img>' }];
  assert.deepEqual(parseHistory(JSON.stringify(records)), [valid]);
  assert.deepEqual(parseHistory('broken JSON'), []);
  assert.deepEqual(parseHistory('{}'), []);
});

test('formatWeight formats weight numbers with decimal commas', () => {
  assert.equal(formatWeight(8420), '8.420,00');
  assert.equal(formatWeight(12.5), '12,50');
  assert.equal(formatWeight(0), '0,00');
  assert.equal(formatWeight(250.75), '250,75');
});
