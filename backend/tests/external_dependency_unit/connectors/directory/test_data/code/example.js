/**
 * Example JavaScript file for testing.
 */

function fibonacci(n) {
  if (n <= 1) return n;
  return fibonacci(n - 1) + fibonacci(n - 2);
}

class MathUtils {
  static isPrime(num) {
    if (num <= 1) return false;
    for (let i = 2; i <= Math.sqrt(num); i++) {
      if (num % i === 0) return false;
    }
    return true;
  }

  static factorial(n) {
    return n <= 1 ? 1 : n * MathUtils.factorial(n - 1);
  }
}

module.exports = { fibonacci, MathUtils };
