export function numberVisibleScenarios(scenarios) {
  return scenarios.filter(scenario => scenario.id !== 'S4')
    .map((scenario, index) => ({...scenario, displayNumber: index + 1}));
}
