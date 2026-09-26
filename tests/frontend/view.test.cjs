const test = require("node:test");
const assert = require("node:assert/strict");
const view = require("../../src/nmr_companion/static/view.js");

test("ppm decreases left to right; elapsed time increases; both clamp to the plot", () => {
  assert.equal(view.at(0, [0, 10], true), 10);
  assert.equal(view.at(1, [0, 10], true), 0);
  assert.equal(view.at(0.25, [0, 10], true), 7.5);
  assert.equal(view.at(0.25, [0, 10], false), 2.5);
  assert.equal(view.at(-4, [0, 10], true), 10);
  assert.equal(view.at(4, [0, 10], true), 0);
});
test("either brush direction gives ordered bounded limits, empty/invalid ranges fail", () => {
  assert.deepEqual(view.range(8, 2, [0, 10]), [2, 8]);
  assert.deepEqual(view.range(2, 8, [0, 10]), [2, 8]);
  assert.deepEqual(view.range(-10, 20, [0, 10]), [0, 10]);
  assert.equal(view.range(4, 4, [0, 10]), null);
  assert.equal(view.range(NaN, 4, [0, 10]), null);
  assert.equal(view.range(12, 15, [0, 10]), null);
});
test("pan preserves span and stops at each edge without mutating its input", () => {
  const limits = Object.freeze([2, 4]),
    extent = Object.freeze([0, 10]);
  assert.deepEqual(view.pan(limits, 100, extent), [8, 10]);
  assert.deepEqual(view.pan(limits, -100, extent), [0, 2]);
  assert.deepEqual(view.pan(limits, 1, extent), [3, 5]);
  assert.deepEqual(limits, [2, 4]);
});
test("display decimation retains isolated positive and negative extrema unchanged", () => {
  const x = Object.freeze(
    Array.from({ length: 1000 }, (_, i) => 10 - i * 0.01),
  );
  const y = Array(1000).fill(0);
  y[321] = 75;
  y[322] = -50;
  Object.freeze(y);
  const selected = view.indices(x, y, [0, 10], 40);
  assert.ok(selected.includes(321));
  assert.ok(selected.includes(322));
  assert.equal(y[321], 75);
  assert.equal(y[322], -50);
  assert.ok(selected.length <= 84);
});
test("a zoom narrower than sample spacing retains the bracketing line segment", () => {
  assert.deepEqual(
    view.indices([1, 0.6, 0.4, 0], [0, 2, -2, 0], [0.45, 0.55], 100),
    [1, 2],
  );
  assert.deepEqual(
    view.indices([0, 0.4, 0.6, 1], [0, -2, 2, 0], [0.45, 0.55], 100),
    [1, 2],
  );
  assert.deepEqual(view.indices([0, 1], [0, 0], [2, 3], 100), []);
});
