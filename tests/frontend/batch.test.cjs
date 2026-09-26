const test = require("node:test");
const assert = require("node:assert/strict");
const geometry = require("../../src/nmr_companion/static/batch.js");

test("2D chemical shifts keep x columns and y rows with explicit axis directions", () => {
  assert.equal(geometry.axisAt(0, [2, 5, 10], true), 10);
  assert.equal(geometry.axisAt(1, [10, 5, 2], true), 2);
  assert.equal(geometry.axisAt(0, [100, 50, 0], false), 0);
  assert.equal(geometry.axisAt(1, [0, 50, 100], false), 100);
  assert.equal(geometry.fraction(6, [2, 5, 10], true), 0.5);
  assert.equal(geometry.fraction(25, [100, 50, 0], false), 0.25);
});

test("crosspeak inspection reads the nearest original point on nonuniform axes", () => {
  const grid = Object.freeze({x: Object.freeze([10, 7, 1]), y: Object.freeze([0, 4, 20]),
    z: Object.freeze([Object.freeze([1,2,3]), Object.freeze([4,-9,6]), Object.freeze([7,8,9])])});
  const point = geometry.gridPoint(grid, 7.2, 3.8);
  assert.deepEqual(point, {column: 1, row: 1, x: 7, y: 4, intensity: -9});
  assert.equal(grid.z[1][1], -9);
});

test("heatmap display aggregation retains both signs in each display bin", () => {
  const grid = {x:[3,2,1],y:[0,1],z:[[0,80,-30],[-50,5,0]]};
  const bins = geometry.signedBins(grid, 1, 1);
  assert.equal(bins.positive[0], 80);
  assert.equal(bins.negative[0], -50);
  assert.equal(bins.maximum, 80);
  assert.deepEqual(grid.z, [[0,80,-30],[-50,5,0]]);
});

test("page rectangles use bounded normalized coordinates in either drag direction", () => {
  assert.deepEqual(geometry.rectangle({x:0.8,y:0.9},{x:0.2,y:0.3}),
    {x:0.2,y:0.3,width:0.6000000000000001,height:0.6000000000000001});
  assert.deepEqual(geometry.rectangle({x:-1,y:2},{x:0.4,y:0.1}),
    {x:0,y:0.1,width:0.4,height:0.9});
  assert.equal(geometry.rectangle({x:0.2,y:0.2},{x:0.2,y:0.5}), null);
});

test("structure atom selection respects stable identity and geometric tolerance", () => {
  const atoms = [{id:"first",x:0.25,y:0.5},{id:"second",x:0.75,y:0.5}];
  assert.equal(geometry.hitAtom(atoms,{x:0.26,y:0.49},0.03)?.id,"first");
  assert.equal(geometry.hitAtom(atoms,{x:0.5,y:0.5},0.03),null);
  assert.deepEqual(atoms[0],{id:"first",x:0.25,y:0.5});
});

test("Bruker processing selection is explicit; blank keeps strict all-package decoding", () => {
  assert.equal(geometry.processingNumbers("  "), null);
  assert.deepEqual(geometry.processingNumbers("1, 700"), [1, 700]);
  for (const input of ["0", "-1", "1,,2", "1.5", "2e3", "foo", "1,1", "9007199254740993"])
    assert.throws(() => geometry.processingNumbers(input));
});

test("heatmap bins preserve row/column identity for independently reversed storage axes", () => {
  const bins = geometry.signedBins({x:[1,2,3], y:[20,0], z:[[1,2,3],[-4,-5,-6]]}, 3, 2);
  assert.deepEqual([...bins.positive], [0,0,0,3,2,1]);
  assert.deepEqual([...bins.negative], [-6,-5,-4,0,0,0]);
});
