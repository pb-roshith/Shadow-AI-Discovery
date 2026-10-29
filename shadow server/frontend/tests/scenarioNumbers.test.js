import test from 'node:test';
import assert from 'node:assert/strict';
import {numberVisibleScenarios} from '../src/scenarioNumbers.js';

test('six visible scenarios are numbered consecutively while preserving evidence IDs', () => {
  const scenarios = Array.from({length: 7}, (_, index) => ({id: `S${index + 1}`, candidate_ids: [`candidate-${index}`]}));
  const numbered = numberVisibleScenarios(scenarios);
  assert.deepEqual(numbered.map(s => s.displayNumber), [1, 2, 3, 4, 5, 6]);
  assert.deepEqual(numbered.map(s => s.id), ['S1', 'S2', 'S3', 'S5', 'S6', 'S7']);
  assert.equal(numbered.at(-1).displayNumber, 6);
  assert.deepEqual(numbered.at(-1).candidate_ids, ['candidate-6']);
  assert.equal(scenarios.at(-1).displayNumber, undefined);
});

test('numbering follows the currently visible list without gaps', () => {
  assert.deepEqual(numberVisibleScenarios([]), []);
  assert.deepEqual(numberVisibleScenarios([{id:'S2'}, {id:'S4'}, {id:'S7'}]).map(s => s.displayNumber), [1, 2]);
});
