// Minimal toast pub/sub so any component can surface a failure without prop drilling.
let listeners = [];
let counter = 0;

export function toast(message, type = "error") {
  const item = { id: ++counter, message, type };
  listeners.forEach((l) => l(item));
}

export function subscribeToast(fn) {
  listeners.push(fn);
  return () => {
    listeners = listeners.filter((x) => x !== fn);
  };
}
