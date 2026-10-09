import {
  preprocessLaTeX,
  escapeIncompleteBlockMath,
  escapeIncompleteInlineMath,
  labelBareCodeFences,
} from "./codeUtils";

describe("preprocessLaTeX", () => {
  describe("currency formatting", () => {
    it("should properly escape dollar signs in text with amounts", () => {
      const input =
        "Maria wants to buy a new laptop that costs $1,200. She has saved $800 so far. If she saves an additional $100 each month, how many months will it take her to have enough money to buy the laptop?";
      const processed = preprocessLaTeX(input);

      // Should escape all dollar signs in currency amounts
      expect(processed).toContain("costs \\$1,200");
      expect(processed).toContain("saved \\$800");
      expect(processed).toContain("additional \\$100");
      expect(processed).not.toContain("costs $1,200");
    });

    it("should handle dollar signs with backslashes already present", () => {
      const input =
        "Maria wants to buy a new laptop that costs \\$1,200. She has saved \\$800 so far.";
      const processed = preprocessLaTeX(input);

      // Should preserve the existing escaped dollar signs
      expect(processed).toContain("\\$1,200");
      expect(processed).toContain("\\$800");
    });
  });

  describe("code block handling", () => {
    it("should not process dollar signs in code blocks", () => {
      const input = "```plaintext\nThe total cost is $50.\n```";
      const processed = preprocessLaTeX(input);

      // Dollar sign in code block should remain untouched
      expect(processed).toContain("The total cost is $50.");
      expect(processed).not.toContain("The total cost is \\$50.");
    });

    it("should not process dollar signs in inline code", () => {
      const input =
        'Use the `printf "$%.2f" $amount` command to format currency.';
      const processed = preprocessLaTeX(input);

      // Dollar signs in inline code should remain untouched
      expect(processed).toContain('`printf "$%.2f" $amount`');
      expect(processed).not.toContain('`printf "\\$%.2f" \\$amount`');
    });

    it("should handle mixed content with code blocks and currency", () => {
      const input =
        "The cost is $100.\n\n```javascript\nconst price = '$50';\n```\n\nThe remaining balance is $50.";
      const processed = preprocessLaTeX(input);

      // Dollar signs outside code blocks should be escaped
      expect(processed).toContain("The cost is \\$100");
      expect(processed).toContain("The remaining balance is \\$50");

      // Dollar sign in code block should be preserved
      expect(processed).toContain("const price = '$50';");
      expect(processed).not.toContain("const price = '\\$50';");
    });
  });

  describe("LaTeX handling", () => {
    it("should preserve proper LaTeX delimiters", () => {
      const input =
        "The formula $x^2 + y^2 = z^2$ represents the Pythagorean theorem.";
      const processed = preprocessLaTeX(input);

      // LaTeX delimiters should be preserved
      expect(processed).toContain("$x^2 + y^2 = z^2$");
    });

    it("should convert LaTeX block delimiters", () => {
      const input = "Consider the equation: \\[E = mc^2\\]";
      const processed = preprocessLaTeX(input);

      // Block LaTeX delimiters should be converted
      expect(processed).toContain("$$E = mc^2$$");
      expect(processed).not.toContain("\\[E = mc^2\\]");
    });

    it("should convert LaTeX inline delimiters", () => {
      const input =
        "The speed of light \\(c\\) is approximately 299,792,458 m/s.";
      const processed = preprocessLaTeX(input);

      // Inline LaTeX delimiters should be converted
      expect(processed).toContain("$c$");
      expect(processed).not.toContain("\\(c\\)");
    });
  });

  describe("special cases", () => {
    it("should handle shell variables in text", () => {
      const input =
        "In bash, you can access arguments with $1, $2, and use echo $HOME to print the home directory.";
      const processed = preprocessLaTeX(input);

      // Verify current behavior (numeric shell variables are being escaped)
      expect(processed).toContain("\\$1");
      expect(processed).toContain("\\$2");

      // But $HOME is not escaped (non-numeric)
      expect(processed).toContain("$HOME");
    });

    it("should handle shell commands with dollar signs", () => {
      const input = "Use awk '{print $2}' to print the second column.";
      const processed = preprocessLaTeX(input);

      // Dollar sign in awk command should not be escaped
      expect(processed).toContain("{print $2}");
      expect(processed).not.toContain("{print \\$2}");
    });

    it("should handle Einstein's equation with mixed LaTeX and code blocks", () => {
      const input =
        "Sure! The equation for Einstein's mass-energy equivalence, \\(E = mc^2\\), can be written in LaTeX as follows:\n```latex\nE = mc^2\n```\nWhen rendered, it looks like this: \\[ E = mc^2 \\]";
      const processed = preprocessLaTeX(input);

      // LaTeX inline delimiters should be converted
      expect(processed).toContain("equivalence, $E = mc^2$,");
      expect(processed).not.toContain("equivalence, \\(E = mc^2\\),");

      // LaTeX block delimiters should be converted
      expect(processed).toContain("it looks like this: $$ E = mc^2 $$");
      expect(processed).not.toContain("it looks like this: \\[ E = mc^2 \\]");

      // LaTeX within code blocks should remain untouched
      expect(processed).toContain("```latex\nE = mc^2\n```");
    });
  });
});

describe("escapeIncompleteBlockMath", () => {
  it("returns empty content unchanged", () => {
    expect(escapeIncompleteBlockMath("")).toBe("");
  });

  it("returns content with no $$ unchanged", () => {
    const input = "Just some text with no math at all.";
    expect(escapeIncompleteBlockMath(input)).toBe(input);
  });

  it("returns a single balanced $$math$$ unchanged", () => {
    const input = "Before $$x = y$$ after.";
    expect(escapeIncompleteBlockMath(input)).toBe(input);
  });

  it("returns two balanced $$ blocks unchanged", () => {
    const input = "First $$a = b$$ then $$c = d$$ done.";
    expect(escapeIncompleteBlockMath(input)).toBe(input);
  });

  it("escapes a single trailing unmatched $$ and preserves the tail", () => {
    const input = "Some prose then $$\\frac{a}{b";
    expect(escapeIncompleteBlockMath(input)).toBe(
      "Some prose then \\$\\$\\frac{a}{b"
    );
  });

  it("escapes a trailing unmatched $$ after a balanced pair", () => {
    const input = "Done: $$x = y$$ next: $$\\frac{c}{d";
    expect(escapeIncompleteBlockMath(input)).toBe(
      "Done: $$x = y$$ next: \\$\\$\\frac{c}{d"
    );
  });

  it("does not count $$ inside a closed fenced code block", () => {
    const input =
      "Real math: $$x = y$$\n```latex\n$$\\frac{a}{b}$$\n```\nDone.";
    expect(escapeIncompleteBlockMath(input)).toBe(input);
  });

  it("escapes trailing unmatched $$ outside a closed code block without modifying the code block", () => {
    const input =
      "Real math: $$x = y$$\n```latex\n$$\\frac{a}{b}$$\n``` then $$\\frac{c";
    expect(escapeIncompleteBlockMath(input)).toBe(
      "Real math: $$x = y$$\n```latex\n$$\\frac{a}{b}$$\n``` then \\$\\$\\frac{c"
    );
  });

  it("does not affect currency-only content", () => {
    const input = "I have $5 and you have $10.";
    expect(escapeIncompleteBlockMath(input)).toBe(input);
  });

  it("does not escape $$ inside an unclosed trailing fenced code block", () => {
    const input = "Hello\n```\nfoo $$x = y$$ bar";
    expect(escapeIncompleteBlockMath(input)).toBe(input);
  });

  it("leaves balanced $$ untouched when an unclosed code block opens later", () => {
    const input = "Done: $$x = y$$ then ```\nfoo";
    expect(escapeIncompleteBlockMath(input)).toBe(input);
  });

  it("preserves input that literally contains a fixed-shape placeholder token", () => {
    // Input contains the OLD placeholder shape; the new nonce-based
    // placeholder won't collide, so the sentinel must survive intact.
    const input = "See ___MATHESC_CB_0___ and $$x = y$$ done.";
    expect(escapeIncompleteBlockMath(input)).toBe(input);
  });
});

describe("escapeIncompleteInlineMath", () => {
  it("returns empty content unchanged", () => {
    expect(escapeIncompleteInlineMath("")).toBe("");
  });

  it("returns content with no $ unchanged", () => {
    const input = "Just some text with no math at all.";
    expect(escapeIncompleteInlineMath(input)).toBe(input);
  });

  it("returns a balanced single-$ inline expression unchanged", () => {
    const input = "Before $x = y$ after.";
    expect(escapeIncompleteInlineMath(input)).toBe(input);
  });

  it("escapes a trailing unmatched single $", () => {
    const input = "The cost is $\\frac{a}{";
    expect(escapeIncompleteInlineMath(input)).toBe("The cost is \\$\\frac{a}{");
  });

  it("does not double-escape an already-escaped \\$", () => {
    const input = "Maria has \\$5 and \\$10.";
    expect(escapeIncompleteInlineMath(input)).toBe(input);
  });

  it("ignores $ inside a balanced $$...$$ block", () => {
    // Stray `$` between the `$$` fences is part of block math and
    // should not perturb inline parity.
    const input = "Block: $$x$y$$ done.";
    expect(escapeIncompleteInlineMath(input)).toBe(input);
  });

  it("ignores $ inside a closed fenced code block", () => {
    const input = "```\nlet x = $5;\n``` done.";
    expect(escapeIncompleteInlineMath(input)).toBe(input);
  });

  it("ignores $ inside an unclosed trailing fenced code block", () => {
    const input = "Hello\n```\nlet x = $foo";
    expect(escapeIncompleteInlineMath(input)).toBe(input);
  });

  it("escapes the trailing $ outside protected regions", () => {
    const input = "Block: $$x = y$$ then $z";
    expect(escapeIncompleteInlineMath(input)).toBe(
      "Block: $$x = y$$ then \\$z"
    );
  });
});

describe("labelBareCodeFences", () => {
  it("labels only bare openers and ignores inline backticks in prose", () => {
    const input = [
      "Wrap code in ``` fences. Example:",
      "```python",
      "print('a')",
      "```",
      "Prose between blocks.",
      "```",
      "plain",
      "```",
      "Done.",
    ].join("\n");
    expect(labelBareCodeFences(input)).toBe(
      [
        "Wrap code in ``` fences. Example:",
        "```python",
        "print('a')",
        "```",
        "Prose between blocks.",
        "```plaintext",
        "plain",
        "```",
        "Done.",
      ].join("\n")
    );
  });

  it("keeps a longer fence open across inner triple-backtick lines", () => {
    const input = "````\n```\ninner\n```\n````\nAfter.";
    expect(labelBareCodeFences(input)).toBe(
      "````plaintext\n```\ninner\n```\n````\nAfter."
    );
  });

  it("handles fences inside list items and blockquotes", () => {
    expect(
      labelBareCodeFences("1. Step:\n   ```\n   code\n   ```\nAfter.")
    ).toBe("1. Step:\n   ```plaintext\n   code\n   ```\nAfter.");
    expect(labelBareCodeFences("- ```python\n  code\n  ```\nAfter.")).toBe(
      "- ```python\n  code\n  ```\nAfter."
    );
    expect(labelBareCodeFences("> ```\n> code\n> ```\nAfter.")).toBe(
      "> ```plaintext\n> code\n> ```\nAfter."
    );
  });

  it("handles list continuation after a blank line", () => {
    expect(
      labelBareCodeFences("- item\n\n    ```\n    code\n\n    ```\nAfter.")
    ).toBe("- item\n\n    ```plaintext\n    code\n\n    ```\nAfter.");
  });

  it("expands tabs when checking list item indentation", () => {
    const input = "- ```go\n\tfunc main() {\n\t\ta[1]\n\t}\n  ```\nAfter.";
    expect(labelBareCodeFences(input)).toBe(input);
    expect(labelBareCodeFences("- ```\n\tx\n  ```\nAfter.")).toBe(
      "- ```plaintext\n\tx\n  ```\nAfter."
    );
  });

  it("ends a block when its blockquote or list item ends", () => {
    expect(labelBareCodeFences("> ```\n> code\nOutside\n```\nnext")).toBe(
      "> ```plaintext\n> code\nOutside\n```plaintext\nnext"
    );
    expect(labelBareCodeFences("- ```\n  code\nOutside\n```\nnext")).toBe(
      "- ```plaintext\n  code\nOutside\n```plaintext\nnext"
    );
  });

  it("ignores a top-level fence indented four spaces", () => {
    expect(labelBareCodeFences("    ```\n```\nx\n```\nAfter")).toBe(
      "    ```\n```plaintext\nx\n```\nAfter"
    );
    const input = "    ```\nPrice $5\n    ```";
    expect(labelBareCodeFences(input)).toBe(input);
  });

  it("does not close a tilde fence with backticks", () => {
    const input = "~~~python\n```\ncode\n```\n~~~\n```\nnext\n```";
    expect(labelBareCodeFences(input)).toBe(
      "~~~python\n```\ncode\n```\n~~~\n```plaintext\nnext\n```"
    );
  });

  it("handles an unclosed trailing fence mid-stream", () => {
    expect(labelBareCodeFences("Text:\n```")).toBe("Text:\n```plaintext");
    expect(labelBareCodeFences("Text:\n```\nx = 1")).toBe(
      "Text:\n```plaintext\nx = 1"
    );
    expect(labelBareCodeFences("```python\nx = 1\n```")).toBe(
      "```python\nx = 1\n```"
    );
  });
});

describe("preprocessLaTeX fenced code", () => {
  it("does not treat a four-space indented fence as code", () => {
    expect(preprocessLaTeX("    ~~~\nPrice $5\n~~~")).toBe(
      "    ~~~\nPrice \\$5\n~~~"
    );
  });

  it("protects an unclosed trailing block while streaming", () => {
    expect(preprocessLaTeX("Text $5\n```\nlet x = $5")).toBe(
      "Text \\$5\n```\nlet x = $5"
    );
  });

  it("protects a blockquote code block that ends with the quote", () => {
    expect(preprocessLaTeX("> ```\n> cost $5\nPrice $7")).toBe(
      "> ```\n> cost $5\nPrice \\$7"
    );
  });

  it("leaves dollars inside a four-backtick block with inner fences", () => {
    const input = "````md\n```\ncost $5\n```\nalso $6\n````\nPrice $7";
    expect(preprocessLaTeX(input)).toBe(
      "````md\n```\ncost $5\n```\nalso $6\n````\nPrice \\$7"
    );
  });
});
