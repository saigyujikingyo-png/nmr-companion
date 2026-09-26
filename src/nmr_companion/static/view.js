/* Display-only geometry. Scientific arrays are never modified here. */
(function (root) {
  "use strict";
  function bounds(axis) {
    let low = Infinity,
      high = -Infinity;
    for (const v of axis) {
      low = Math.min(low, v);
      high = Math.max(high, v);
    }
    return [low, high];
  }
  function range(a, b, extent) {
    if (![a, b, ...extent].every(Number.isFinite)) return null;
    const low = Math.max(extent[0], Math.min(a, b));
    const high = Math.min(extent[1], Math.max(a, b));
    return high - low > Math.max((extent[1] - extent[0]) * 1e-9, Number.EPSILON)
      ? [low, high]
      : null;
  }
  function at(fraction, limits, reverse) {
    const f = Math.max(0, Math.min(1, fraction));
    return reverse
      ? limits[1] - f * (limits[1] - limits[0])
      : limits[0] + f * (limits[1] - limits[0]);
  }
  function pan(limits, delta, extent) {
    const width = limits[1] - limits[0];
    const low = Math.max(
      extent[0],
      Math.min(extent[1] - width, limits[0] + delta),
    );
    return [low, low + width];
  }
  function indices(x, y, limits, pixelWidth) {
    const visible = [];
    for (let i = 0; i < x.length; i++)
      if (x[i] >= limits[0] && x[i] <= limits[1]) visible.push(i);
    // Include adjacent samples so a sub-sample view still draws the actual line segment.
    if (!visible.length) {
      for (let i = 1; i < x.length; i++) {
        if (
          Math.min(x[i - 1], x[i]) <= limits[0] &&
          Math.max(x[i - 1], x[i]) >= limits[1]
        )
          return [i - 1, i];
      }
      return [];
    }
    const start = Math.max(0, visible[0] - 1),
      end = Math.min(x.length - 1, visible.at(-1) + 1);
    const keep = new Set([start, end]);
    const step = Math.max(
      1,
      Math.ceil((end - start + 1) / Math.max(1, pixelWidth)),
    );
    for (let i = start; i <= end; i += step) {
      let low = i,
        high = i;
      for (let j = i; j <= Math.min(end, i + step - 1); j++) {
        if (y[j] < y[low]) low = j;
        if (y[j] > y[high]) high = j;
      }
      keep.add(low);
      keep.add(high);
    }
    return [...keep].sort((a, b) => a - b);
  }
  const api = { bounds, range, at, pan, indices };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.NMRView = api;
})(globalThis);
