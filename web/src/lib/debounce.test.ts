import { debounce } from "@/lib/debounce";

beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

test("calls the function after the wait period", () => {
  const fn = jest.fn();
  const debounced = debounce(fn, 200);

  debounced();
  expect(fn).not.toHaveBeenCalled();

  jest.advanceTimersByTime(200);
  expect(fn).toHaveBeenCalledTimes(1);
});

test("resets the timer on subsequent calls", () => {
  const fn = jest.fn();
  const debounced = debounce(fn, 200);

  debounced();
  jest.advanceTimersByTime(100);
  debounced();
  jest.advanceTimersByTime(100);
  expect(fn).not.toHaveBeenCalled();

  jest.advanceTimersByTime(100);
  expect(fn).toHaveBeenCalledTimes(1);
});

test("passes arguments to the underlying function", () => {
  const fn = jest.fn();
  const debounced = debounce(fn, 100);

  debounced("a", "b");
  jest.advanceTimersByTime(100);
  expect(fn).toHaveBeenCalledWith("a", "b");
});

test(".cancel() prevents the pending invocation", () => {
  const fn = jest.fn();
  const debounced = debounce(fn, 200);

  debounced();
  debounced.cancel();
  jest.advanceTimersByTime(200);
  expect(fn).not.toHaveBeenCalled();
});
