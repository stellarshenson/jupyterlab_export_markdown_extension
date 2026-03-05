# LaTeX Math Rendering Test

## Inline Math

The equation $E=mc^2$ describes mass-energy equivalence. The quadratic formula gives $x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}$.

Greek letters: $\alpha + \beta = \gamma$ and $\Delta T = T_f - T_i$.

## Display Math

$$\int_0^\infty e^{-x^2} dx = \frac{\sqrt{\pi}}{2}$$

$$\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}$$

$$F = G \frac{m_1 m_2}{r^2}$$

## Currency (should NOT render)

The price is \\$100 and the total is \\$200. We saved \\$50 on the order.

## Math in Code (should NOT render)

```python
# Formula: $E=mc^2$
formula = "$x^2 + y^2$"
```

Inline code: `$E=mc^2$` stays as text.

## Regular Text After Math

This paragraph follows the math section to verify document continues normally.
