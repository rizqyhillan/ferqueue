import test from 'node:test';
import assert from 'node:assert/strict';
import { createTicket, parseHistory, validateInspection } from '../src/tickets.js';

const inspection = { plate: 'b9241kxs', weight: 8420, category: 'VI B' };
test('ticket numbers follow Jakarta calendar boundaries and continue after restored history', () => {
  const first = createTicket(inspection, [], new Date('2026-11-01T16:59:59Z'));
  const second = createTicket(inspection, [first], new Date('2026-11-01T17:00:00Z'));
  const third = createTicket(inspection, parseHistory(JSON.stringify([first, second])), new Date('2026-11-01T17:00:01Z'));
  assert.equal(first.number, 'FQ-261101-001');
  assert.equal(second.number, 'FQ-261102-001');
  assert.equal(third.number, 'FQ-261102-002');
  assert.equal(third.plate, 'B 9241 KXS');
});
test('tickets cannot be issued with missing readings, invalid plates, or unknown categories', () => {
  for (const change of [{ weight: null }, { weight: -20 }, { weight: 1.5 }, { weight: 200001 }, { plate: '' }, { plate: '<script>' }, { category: '' }, { category: 'fake' }]) {
    assert.throws(() => createTicket({ ...inspection, ...change }));
  }
  assert.deepEqual(validateInspection({ plate: 'AD 1234', weight: 1, category: 'IV A' }), {});
});
test('malformed, tampered, and duplicate persisted records are ignored without losing valid tickets', () => {
  const valid = createTicket(inspection, [], new Date('2026-11-02T01:00:00Z'));
  const records = [null, valid, valid, { ...valid, number: 'bad' }, { ...valid, number: 'FQ-261102-002', weight: '8420' }, { ...valid, number: 'FQ-261102-003', category: '<img>' }];
  assert.deepEqual(parseHistory(JSON.stringify(records)), [valid]);
  assert.deepEqual(parseHistory('broken JSON'), []);
  assert.deepEqual(parseHistory('{}'), []);
});
