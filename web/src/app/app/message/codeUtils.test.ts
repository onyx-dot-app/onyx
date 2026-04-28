import {
  preprocessLaTeX,
  escapeIncompleteBlockMath,
  escapeIncompleteInlineMath,
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
        "Sure! The equation for Einstein's mass-energy equivalence, \\(E = mc^2\\), can be written in LaTeX as follows: ```latex\nE = mc^2\n``` When rendered, it looks like this: \\[ E = mc^2 \\]";
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
