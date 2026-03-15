import { Token, TokenType } from "../types";

const WHITESPACE = /[ \t\r]/;
const DIGIT = /[0-9]/;
const IDENT_START = /[a-zA-Z_]/;
const IDENT_CHAR = /[a-zA-Z0-9_]/;

export class Tokenizer {
  private input: string;
  private pos = 0;
  private line = 1;
  private column = 1;
  private bracketDepth = 0;

  constructor(input: string) {
    this.input = input;
  }

  tokenize(): Token[] {
    const tokens: Token[] = [];

    while (this.pos < this.input.length) {
      this.skipWhitespace();
      if (this.pos >= this.input.length) break;

      const ch = this.input[this.pos]!;

      // Comments — skip to end of line
      if (ch === "/" && this.input[this.pos + 1] === "/") {
        this.skipLineComment();
        continue;
      }

      if (ch === "\n") {
        // Newlines only matter at bracket depth 0
        if (this.bracketDepth === 0) {
          tokens.push(this.makeToken(TokenType.Newline, "\n"));
        }
        this.advance();
        this.line++;
        this.column = 1;
        continue;
      }

      if (ch === '"' || ch === "'") {
        tokens.push(this.readString(ch));
        continue;
      }

      if (
        DIGIT.test(ch) ||
        (ch === "-" && this.peek(1) !== undefined && DIGIT.test(this.peek(1)!))
      ) {
        tokens.push(this.readNumber());
        continue;
      }

      if (IDENT_START.test(ch)) {
        tokens.push(this.readIdentifier());
        continue;
      }

      switch (ch) {
        case "=":
          tokens.push(this.makeToken(TokenType.Equals, "="));
          this.advance();
          break;
        case ":":
          tokens.push(this.makeToken(TokenType.Colon, ":"));
          this.advance();
          break;
        case ",":
          tokens.push(this.makeToken(TokenType.Comma, ","));
          this.advance();
          break;
        case "(":
          this.bracketDepth++;
          tokens.push(this.makeToken(TokenType.LParen, "("));
          this.advance();
          break;
        case ")":
          this.bracketDepth = Math.max(0, this.bracketDepth - 1);
          tokens.push(this.makeToken(TokenType.RParen, ")"));
          this.advance();
          break;
        case "[":
          this.bracketDepth++;
          tokens.push(this.makeToken(TokenType.LBracket, "["));
          this.advance();
          break;
        case "]":
          this.bracketDepth = Math.max(0, this.bracketDepth - 1);
          tokens.push(this.makeToken(TokenType.RBracket, "]"));
          this.advance();
          break;
        case "{":
          this.bracketDepth++;
          tokens.push(this.makeToken(TokenType.LBrace, "{"));
          this.advance();
          break;
        case "}":
          this.bracketDepth = Math.max(0, this.bracketDepth - 1);
          tokens.push(this.makeToken(TokenType.RBrace, "}"));
          this.advance();
          break;
        default:
          // Skip unknown characters
          this.advance();
          break;
      }
    }

    tokens.push(this.makeToken(TokenType.EOF, ""));
    return tokens;
  }

  private skipWhitespace(): void {
    while (
      this.pos < this.input.length &&
      WHITESPACE.test(this.input[this.pos]!)
    ) {
      this.advance();
    }
  }

  private skipLineComment(): void {
    while (this.pos < this.input.length && this.input[this.pos] !== "\n") {
      this.advance();
    }
  }

  private readString(quote: string): Token {
    const startOffset = this.pos;
    const startLine = this.line;
    const startCol = this.column;

    this.advance(); // skip opening quote

    let value = "";
    while (this.pos < this.input.length) {
      const ch = this.input[this.pos]!;

      if (ch === "\\") {
        this.advance();
        if (this.pos < this.input.length) {
          const escaped = this.input[this.pos]!;
          switch (escaped) {
            case "n":
              value += "\n";
              break;
            case "t":
              value += "\t";
              break;
            case "\\":
              value += "\\";
              break;
            case '"':
              value += '"';
              break;
            case "'":
              value += "'";
              break;
            default:
              value += escaped;
          }
          this.advance();
        }
        continue;
      }

      if (ch === quote) {
        this.advance(); // skip closing quote
        break;
      }

      if (ch === "\n") {
        this.line++;
        this.column = 0;
      }

      value += ch;
      this.advance();
    }

    return {
      type: TokenType.String,
      value,
      offset: startOffset,
      line: startLine,
      column: startCol,
    };
  }

  private readNumber(): Token {
    const startOffset = this.pos;
    const startLine = this.line;
    const startCol = this.column;

    let value = "";

    if (this.input[this.pos] === "-") {
      value += "-";
      this.advance();
    }

    while (this.pos < this.input.length && DIGIT.test(this.input[this.pos]!)) {
      value += this.input[this.pos]!;
      this.advance();
    }

    if (this.pos < this.input.length && this.input[this.pos] === ".") {
      value += ".";
      this.advance();
      while (
        this.pos < this.input.length &&
        DIGIT.test(this.input[this.pos]!)
      ) {
        value += this.input[this.pos]!;
        this.advance();
      }
    }

    return {
      type: TokenType.Number,
      value,
      offset: startOffset,
      line: startLine,
      column: startCol,
    };
  }

  private readIdentifier(): Token {
    const startOffset = this.pos;
    const startLine = this.line;
    const startCol = this.column;

    let value = "";
    while (
      this.pos < this.input.length &&
      IDENT_CHAR.test(this.input[this.pos]!)
    ) {
      value += this.input[this.pos]!;
      this.advance();
    }

    // Check for keywords
    if (value === "true" || value === "false") {
      return {
        type: TokenType.Boolean,
        value,
        offset: startOffset,
        line: startLine,
        column: startCol,
      };
    }

    if (value === "null") {
      return {
        type: TokenType.Null,
        value,
        offset: startOffset,
        line: startLine,
        column: startCol,
      };
    }

    return {
      type: TokenType.Identifier,
      value,
      offset: startOffset,
      line: startLine,
      column: startCol,
    };
  }

  private makeToken(type: TokenType, value: string): Token {
    return {
      type,
      value,
      offset: this.pos,
      line: this.line,
      column: this.column,
    };
  }

  private advance(): void {
    this.pos++;
    this.column++;
  }

  private peek(offset: number): string | undefined {
    return this.input[this.pos + offset];
  }
}
