# Comprehensive Markdown Test

This document tests all markdown elements for PDF and DOCX export.

## Heading 2

### Heading 3

#### Heading 4

## Text Formatting

Regular paragraph with **bold text** and _italic text_ and **_bold italic_**.

This is a second paragraph to test spacing.

## Unicode Symbols (PDF supported)

Arrows: → ← ↑ ↓ ↔ ↕ ⇒ ⇐ ⇔

Bullets: • ◦ ▪ ▫ ► ◄ ▲ ▼

Stars: ★ ☆ ✦ ✧

Math: ± × ÷ ≤ ≥ ≠ ≈ ∞ √ ∑ ∏

Special: © ® ™ § ¶ † ‡ ° ′ ″

## Color Emojis (HTML/DOCX only)

Note: Color emojis require specialized font support not available in PDF export.

Common: ✅ ❌ ⚠️ ℹ️ 🔴 🟢 🔵 ⭐ 📁 📄 🔗 💡

Faces: 😀 😎 🤔 👍 👎 🎉 🚀 ✨

## Bullet Lists

- First bullet item
- Second bullet item
  - Nested bullet 2.1
  - Nested bullet 2.2
    - Deep nested 2.2.1
- Third bullet item

## Numbered Lists

1. First numbered item
2. Second numbered item
   1. Nested number 2.1
   2. Nested number 2.2
      1. Deep nested 2.2.1
      2. Deep nested 2.2.2
   3. Nested number 2.3
3. Third numbered item
4. Fourth numbered item
   1. Nested 4.1
   2. Nested 4.2

## Mixed Lists

1. Numbered parent
   - Bullet child 1
   - Bullet child 2
2. Another numbered
   1. Nested numbered
   2. Another nested

## Tables

| Column A | Column B | Column C |
| -------- | -------- | -------- |
| A1       | B1       | C1       |
| A2       | B2       | C2       |
| A3       | B3       | C3       |

## Code

Inline `code snippet` in a paragraph.

### Python

```python
def hello_world():
    """A simple greeting function."""
    print("Hello, World!")
    return True

class Calculator:
    def add(self, a, b):
        return a + b
```

### INI Configuration

```ini
[database]
host = localhost
port = 5432
name = myapp_db

[logging]
level = INFO
format = %(asctime)s - %(name)s - %(levelname)s
```

### Bash Script

```bash
#!/bin/bash
# Deploy script
echo "Starting deployment..."
for server in web1 web2 web3; do
    ssh $server "cd /app && git pull && systemctl restart app"
done
echo "Deployment complete!"
```

## Blockquotes

> This is a regular blockquote.
> It can span multiple lines.

## GitHub Alerts

> [!NOTE]
> This is a note - useful information that users should know.

> [!TIP]
> This is a tip - helpful advice for doing things better.

> [!IMPORTANT]
> This is important - key information users need to know.

> [!WARNING]
> This is a warning - urgent info that needs attention.

> [!CAUTION]
> This is a caution - advises about risks or negative outcomes.

## Links

This is a [link to Google](https://www.google.com).

## Images

Here is an embedded test image:

![Test Image](test_image.png)

## Mermaid Diagrams

```mermaid
graph LR
    A[Start] --> B[Process]
    B --> C[End]
    style A fill:#d1fae5,stroke:#10b981
    style B fill:#e0f2fe,stroke:#0284c7
    style C fill:#fef3c7,stroke:#f59e0b
```

## LaTeX Math

Inline math: The equation $E=mc^2$ is well known. The quadratic formula gives $x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}$.

Display math:

$$\int_0^\infty e^{-x^2} dx = \frac{\sqrt{\pi}}{2}$$

$$\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}$$

Greek letters inline: $\alpha + \beta = \gamma$

Currency amounts should NOT render as math: The price is $100 and the total is $200.

Math inside code should NOT render: `$E=mc^2$` and `$x^2$`

## Horizontal Rule

---

## Final Paragraph

This is the final paragraph to ensure the document ends properly.
