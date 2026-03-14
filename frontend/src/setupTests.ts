import "@testing-library/jest-dom";

// jsdom does not implement scrollIntoView — provide a no-op so components that
// call it don't throw during tests.
window.HTMLElement.prototype.scrollIntoView = vi.fn();
