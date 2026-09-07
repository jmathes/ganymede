/-- Doubling a natural number is the same as adding it to itself. -/
theorem two_mul_eq_add (n : Nat) : 2 * n = n + n := by
  sorry

/-- The sum of the first n odd numbers is n squared. -/
def sumOdd : Nat → Nat
  | 0 => 0
  | n + 1 => sumOdd n + (2 * n + 1)

theorem sumOdd_eq_sq (n : Nat) : sumOdd n = n * n := by
  sorry
