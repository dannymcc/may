const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const template = fs.readFileSync('app/templates/fuel/quick.html', 'utf8');
const script = template.split('<script>')[1].split('</script>')[0].replace(/{{[\s\S]*?}}/g, '""');
const nodes = {};
const get = id => nodes[id] ||= {value: '', classList: {add() {}, remove() {}}};
get('vehicle_id').options = [
    {dataset: {lastPrice: '1.5', odometerUnit: 'mi'}},
    {dataset: {lastPrice: '1.8', odometerUnit: 'mi'}},
    {dataset: {lastPrice: '', odometerUnit: 'mi'}},
    {dataset: {lastPrice: '0', odometerUnit: 'mi'}},
];
get('vehicle_id').selectedIndex = 0;
const context = vm.createContext({document: {getElementById: get, addEventListener() {}}, parseDecimal: x => x === '' ? null : Number(x)});
vm.runInContext(script, context);
context.updateVehicleOdometer();
assert.equal(get('price_per_unit').value, '1.5');
get('volume').value = '40'; context.calcQuickFuel('volume');
assert.equal(get('total_cost').value, '60.00');
get('total_cost').value = '75'; context.calcQuickFuel('total');
assert.equal(get('volume').value, '50.000');
assert.equal(get('price_per_unit').value, '1.5');
get('vehicle_id').selectedIndex = 1; context.updateVehicleOdometer();
assert.equal(get('price_per_unit').value, '1.8');
assert.equal(get('total_cost').value, '90.00');
get('vehicle_id').selectedIndex = 2; context.updateVehicleOdometer();
assert.equal(get('price_per_unit').value, '');
get('vehicle_id').selectedIndex = 3; context.updateVehicleOdometer();
assert.equal(get('price_per_unit').value, '0');
assert.equal(get('total_cost').value, '0.00');
console.log('Quick fuel vehicle switching and calculation checks passed.');
