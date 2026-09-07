# Two small facts about natural numbers

## Definitions

For a natural number $n$, define $S(n)$, the sum of the first $n$ odd numbers, recursively by $S(0) = 0$ and $S(n+1) = S(n) + (2n + 1)$.

## Results

**Theorem 1.** For every natural number $n$, $2n = n + n$.

*Proof.* Immediate from the definition of multiplication by $2$. $\square$

**Theorem 2.** For every natural number $n$, $S(n) = n^2$.

*Proof.* By induction on $n$. For $n = 0$ both sides are $0$. Suppose $S(n) = n^2$. Then $S(n+1) = S(n) + (2n+1) = n^2 + 2n + 1 = (n+1)^2$. $\square$
