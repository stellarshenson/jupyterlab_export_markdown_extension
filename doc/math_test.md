# LaTeX Math Rendering Test

## Inline Simple

The equation $E=mc^2$ describes mass-energy equivalence. Greek letters: $\alpha + \beta = \gamma$ and temperature change $\Delta T = T_f - T_i$.

## Inline Complex

The quadratic formula $x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}$ solves any second-degree polynomial. The Euler identity $e^{i\pi} + 1 = 0$ links five constants. Probability density $f(x) = \frac{1}{\sigma\sqrt{2\pi}} e^{-\frac{(x-\mu)^2}{2\sigma^2}}$ defines a Gaussian.

## Display Simple

$$F = G \frac{m_1 m_2}{r^2}$$

$$a^2 + b^2 = c^2$$

$$\vec{F} = m\vec{a}$$

## Display Complex

$$\int_0^\infty e^{-x^2} dx = \frac{\sqrt{\pi}}{2}$$

$$\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}$$

$$\nabla \times \vec{E} = -\frac{\partial \vec{B}}{\partial t}$$

$$\frac{\partial^2 u}{\partial t^2} = c^2 \nabla^2 u$$

$$\mathcal{L} = \int \left( \frac{1}{2} \partial_\mu \phi \partial^\mu \phi - V(\phi) \right) d^4x$$

## Mixed Content

Einstein showed that $E=mc^2$ which leads to the full energy-momentum relation:

$$E^2 = (pc)^2 + (mc^2)^2$$

In thermodynamics, the entropy change $\Delta S = \int \frac{dQ}{T}$ governs irreversibility, while the partition function:

$$Z = \sum_i e^{-\beta E_i}$$

connects statistical mechanics to thermodynamics via $F = -k_B T \ln Z$.

## Currency (should NOT render)

The price is \$100 and the total is \$200. We saved \$50 on the order.

## Math in Code (should NOT render)

```python
# Formula: $E=mc^2$
formula = "$x^2 + y^2$"
result = 3.14 * r**2
```

Inline code: `$E=mc^2$` stays as text.

## Regular Text After Math

This paragraph follows the math section to verify document continues normally with no leftover markers or formatting artifacts.
